"""The studio's queue.

Every render and every long task is a job here. Two lanes run side by side: "gpu" (one job at a time: ComfyUI renders
one graph at a time anyway, and a second big model beside a render is how a machine runs out of memory) and "cpu"
(checks, exports, speech-to-text on the processor), so a film can be cut while the next part renders.

A job is a dict: id, kind, title, params, status (queued, running, done, failed, cancelled), progress, result, error.
Handlers live in work.py: `async def handler(job, ctx)` returns the job's result.
"""
import asyncio
import time
import traceback
import uuid

from . import config, graphs, models
from .comfy import ComfyDown, ComfyError

KEEP = 400            # finished jobs kept in jobs.json
LANES = ("gpu", "cpu")


class Cancelled(Exception):
    pass


class Refused(Exception):
    """A job that cannot run as asked; the message says why and what would work."""


class Queue:
    def __init__(self, comfy, handlers, machine=None):
        self.comfy = comfy
        self.handlers = handlers
        self.machine = machine
        self.jobs = []
        self._wake = {lane: asyncio.Event() for lane in LANES}
        self._tasks = []
        self._cancel = set()
        self._dirty = False
        self.listeners = []          # async callbacks(job) after a job ends
        self.times = config.read_json(config.home("telemetry.json"), {}) or {}

    # ---------------------------------------------------------------- persistence
    def load(self):
        saved = config.read_json(config.home("jobs.json"), []) or []
        for j in saved:
            if j.get("status") == "running":
                j["status"] = "failed"
                j["error"] = "the studio was stopped while this was running"
                j["finished"] = time.time()
        self.jobs = saved

    def save(self):
        done = [j for j in self.jobs if j["status"] in ("done", "failed", "cancelled")]
        if len(done) > KEEP:
            drop = {j["id"] for j in done[:len(done) - KEEP]}
            self.jobs = [j for j in self.jobs if j["id"] not in drop]
        config.write_json(config.home("jobs.json"), [{k: v for k, v in j.items() if k != "progress"} for j in self.jobs])

    # ---------------------------------------------------------------- the list
    def add(self, kind, params=None, title="", lane=None, front=False, **meta):
        if kind not in self.handlers:
            raise Refused(f"no such kind of job: {kind}")
        lane = lane or getattr(self.handlers[kind], "lane", "gpu")
        job = {"id": uuid.uuid4().hex[:10], "kind": kind, "title": title or kind, "params": params or {}, "lane": lane,
               "status": "queued", "created": time.time(), "started": None, "finished": None,
               "progress": {"text": "waiting"}, "result": None, "error": None, "prompt_ids": [], **meta}
        if front:
            first = next((i for i, j in enumerate(self.jobs) if j["status"] == "queued" and j["lane"] == lane), len(self.jobs))
            self.jobs.insert(first, job)
        else:
            self.jobs.append(job)
        self.save()
        self._wake[lane].set()
        return job

    def get(self, jid):
        return next((j for j in self.jobs if j["id"] == jid), None)

    def recent(self, limit=60):
        live = [j for j in self.jobs if j["status"] in ("queued", "running")]
        done = [j for j in self.jobs if j["status"] not in ("queued", "running")]
        return live + done[-limit:][::-1]

    def waiting(self, lane="gpu"):
        return [j for j in self.jobs if j["status"] in ("queued", "running") and j["lane"] == lane]

    def busy(self, lane="gpu"):
        return bool(self.waiting(lane))

    async def cancel(self, jid):
        """Take a waiting job out of the queue, or stop a running one."""
        job = self.get(jid)
        if not job:
            return False
        if job["status"] == "queued":
            job.update(status="cancelled", finished=time.time())
            self.save()
            await self._notify(job)
            return True
        if job["status"] == "running":
            self._cancel.add(jid)
            for pid in job.get("prompt_ids", [])[-1:]:
                await self.comfy.interrupt(pid)
            return True
        return False

    def remove(self, jid):
        """Forget a finished job (its files stay)."""
        job = self.get(jid)
        if not job or job["status"] in ("queued", "running"):
            return False
        self.jobs.remove(job)
        self.save()
        return True

    def clear(self, statuses=("failed", "cancelled")):
        n = len(self.jobs)
        self.jobs = [j for j in self.jobs if j["status"] not in statuses]
        self.save()
        return n - len(self.jobs)

    # ---------------------------------------------------------------- running
    def start(self):
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._lane(lane)) for lane in LANES]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _lane(self, lane):
        while True:
            job = next((j for j in self.jobs if j["status"] == "queued" and j["lane"] == lane), None)
            if job is None:
                self._wake[lane].clear()
                await self._wake[lane].wait()
                continue
            await self._run(job)

    async def _run(self, job):
        job.update(status="running", started=time.time(), progress={"text": "starting"})
        self.save()
        ctx = Context(self, job)
        try:
            job["result"] = await self.handlers[job["kind"]](job, ctx)
            job["status"] = "done"
        except Cancelled:
            job["status"] = "cancelled"
        except asyncio.CancelledError:
            job.update(status="failed", error="the studio was stopped while this was running", finished=time.time())
            self.save()
            raise
        except (Refused, ValueError, ComfyError) as e:
            job["status"] = "failed"
            job["error"] = str(e)
            if isinstance(e, ComfyDown) and self.machine:
                job["error"] += self.machine.why_down()
        except Exception as e:      # a bug in a handler must not stop the queue
            job["status"] = "failed"
            job["error"] = f"{type(e).__name__}: {e}"
            job["trace"] = traceback.format_exc()[-2000:]
        job["finished"] = time.time()
        job["progress"] = {"text": job["status"]}
        self._cancel.discard(job["id"])
        self.save()
        await self._notify(job)

    async def _notify(self, job):
        for cb in list(self.listeners):
            try:
                await cb(job)
            except Exception:
                traceback.print_exc()

    def cancelled(self, job):
        return job["id"] in self._cancel

    # ---------------------------------------------------------------- how long things take
    def note_time(self, key, units, seconds):
        """Remember how long a render took: key = kind of work, units = its size (pixels x frames x steps)."""
        rows = self.times.setdefault(key, [])
        rows.append([float(units), round(float(seconds), 1)])
        del rows[:-40]
        config.write_json(config.home("telemetry.json"), self.times)

    def estimate(self, key, units, prior=None):
        """Seconds a job of this size will take: a fixed share (loading, decoding, writing; `prior[0]`) plus a rate per
        unit of work, the median of what this machine's own renders of that kind took. Without any yet: `prior[1]`."""
        base, rate0 = prior if prior else (0.0, None)
        rates = sorted((r[1] - base) / r[0] for r in (self.times.get(key) or []) if r[0] > 0 and r[1] > base)
        if rates:
            mid = len(rates) // 2
            rate = rates[mid] if len(rates) % 2 else (rates[mid - 1] + rates[mid]) / 2
        elif rate0 is not None:
            rate = rate0
        else:
            return None
        return max(5.0, base + rate * units)


class Context:
    """What a handler works with."""

    def __init__(self, queue, job):
        self.queue, self.job, self.comfy = queue, job, queue.comfy

    def say(self, text, value=None, total=None):
        p = {"text": text}
        if total:
            p.update(value=value or 0, max=total)
        self.job["progress"] = p

    def check_cancel(self):
        if self.queue.cancelled(self.job):
            raise Cancelled()

    async def info(self):
        try:
            return await self.comfy.object_info()
        except ComfyDown:
            if self.queue.machine and await self.queue.machine.ensure_comfy(self):
                return await self.comfy.object_info(refresh=True)
            raise

    async def render(self, graph, stages=None, label=""):
        """Queue one graph in ComfyUI and wait for it, showing the step it is on. Returns ComfyUI's outputs.

        The graph is checked first against what this ComfyUI has, so a missing node, model or picture is reported
        in words before anything is queued."""
        self.check_cancel()
        info = await self.info()
        problems = models.validate(graph, info)
        missing = graphs.missing_inputs(graph)
        if missing:
            problems.append("missing file(s): " + ", ".join(missing))
        if problems:
            raise Refused("this cannot be rendered: " + "; ".join(problems[:6]))
        pid = await self.comfy.submit(graph)
        self.job["prompt_ids"].append(pid)
        stages = stages or {}
        label = (label + ": ") if label else ""

        async def tick():
            if self.queue.cancelled(self.job):
                await self.comfy.interrupt(pid)
                raise Cancelled()
            p = self.comfy.progress.get(pid)
            if p and p.get("node"):
                name = stages.get(str(p["node"]).split(":")[-1], "working")
                if p.get("max"):
                    self.say(f"{label}{name}", p["value"], p["max"])
                else:
                    self.say(f"{label}{name}")
            else:
                state, ahead = await self.comfy.position(pid)
                if state == "pending":
                    self.say(f"{label}waiting in ComfyUI's queue" + (f" ({ahead} ahead)" if ahead else ""))
        try:
            return await self.comfy.wait(pid, on_tick=tick)
        except ComfyError as e:
            if "interrupted" in str(e) and self.queue.cancelled(self.job):
                raise Cancelled()
            raise

    async def thread(self, fn, *args, **kw):
        """Run blocking work (ffmpeg, Whisper) off the event loop."""
        return await asyncio.to_thread(fn, *args, **kw)
