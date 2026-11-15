"""Rendering a film in order, with the gate, and the night shift.

A run walks the shots of a film from the first one that has no usable take. After every part the take is checked
(work.shot) and then one of three things happens, depending on the run:

  hold        every take waits until a person approves it or renders it again. Nothing continues an unapproved part.
  auto        a take that passes every automatic check is approved; one that fails is rendered again at a new seed, up
              to `retries` times; a take that still fails waits for a person.
  keep going  (the night shift) like auto, but a take that still fails is kept, marked to be looked at, and the run goes
              on. In the morning the notes say which shots to look at first.

The automatic checks see cuts, a jump at a join, wrong or unwanted speech and shouted lines. They do not see a wrong
prop, an empty bar or a person getting into a car on the wrong side: that is what holding the gate is for.
"""
import asyncio
import datetime
import os
import time
import uuid

from . import config, films


class Production:
    def __init__(self, queue):
        self.queue = queue
        queue.listeners.append(self.on_job)
        self.on_run_end = []                 # async callbacks(film, run)

    # ------------------------------------------------------------------ helpers
    def _film_jobs(self, fid, kinds=("shot",)):
        return [j for j in self.queue.jobs if j["status"] in ("queued", "running") and j.get("film") == fid and j["kind"] in kinds]

    @staticmethod
    def _log(film, text):
        run = film.setdefault("run", {})
        run.setdefault("log", []).append([time.time(), text])
        del run["log"][:-80]

    def queue_shot(self, film, shot, seed=0, front=False, force=False, attempt=0):
        idx = films.shot_index(film, shot["id"])
        title = f"{film['name']} · {shot.get('title') or 'shot ' + str(idx + 1)}"
        return self.queue.add("shot", {"film": film["id"], "shot": shot["id"], "seed": seed, "force": force, "attempt": attempt},
                              title=title, front=front, film=film["id"], shot=shot["id"])

    # ------------------------------------------------------------------ runs
    async def start(self, fid, mode=None, retries=None, upscale=False, shift=""):
        """Render every shot that has no usable take, in order. mode: hold | auto | keep_going (default: the film's gate)."""
        with films.LOCK:
            film = films.load(fid)
            if not film:
                raise KeyError(fid)
            gate = film.get("gate") or films.default_gate()
            film["run"] = {"active": True, "started": time.time(), "mode": mode or gate.get("mode", "hold"),
                           "retries": int(gate.get("retries", 0) if retries is None else retries),
                           "upscale": bool(upscale), "shift": shift, "log": [], "stopped": ""}
            self._log(film, "run started")
            films.save(film)
        await self.advance(fid)
        return films.load(fid)["run"]

    async def stop(self, fid, why="stopped"):
        with films.LOCK:
            film = films.load(fid)
            if not film:
                return
            run = film.setdefault("run", {})
            run["active"] = False
            run["stopped"] = why
            self._log(film, why)
            films.save(film)
        for j in self._film_jobs(fid):
            if j["status"] == "queued":
                await self.queue.cancel(j["id"])

    async def advance(self, fid):
        """Queue the next shot of a running film, or end the run."""
        ended = None
        with films.LOCK:
            film = films.load(fid)
            run = (film or {}).get("run") or {}
            if not film or not run.get("active") or self._film_jobs(fid):
                return
            keep = run.get("mode") == "keep_going"
            nxt = films.next_to_render(film, keep_going=keep)
            if nxt is not None:
                ok, why = films.eligible(film, nxt["id"], ignore_gate=keep)
                if ok:
                    self.queue_shot(film, nxt, force=keep)
                    self._log(film, f"rendering shot {films.shot_index(film, nxt['id']) + 1}")
                else:
                    self._log(film, "waiting: " + why)
                films.save(film)
                return
            held = [i + 1 for i, s in enumerate(film["shots"]) if s["status"] == "review"]
            if held and not keep:
                self._log(film, f"waiting at the gate: shot {held[0]}")
                films.save(film)
                return
            run["active"] = False
            run["finished"] = time.time()
            self._log(film, "every shot has a take" + (f"; {len(held)} to look at" if held else ""))
            if run.get("upscale") and film["shots"]:
                self.queue.add("upscale", {"film": fid}, title=f"{film['name']} · upscale", film=fid)
                self._log(film, "upscale queued")
            films.save(film)
            ended = (film, dict(run))
        if ended:
            for cb in list(self.on_run_end):
                await cb(*ended)

    async def on_job(self, job):
        fid = job.get("film")
        if job["kind"] != "shot" or not fid:
            return
        if job["status"] == "failed":
            with films.LOCK:
                film = films.load(fid)
                if film and (film.get("run") or {}).get("active"):
                    film["run"]["active"] = False
                    film["run"]["stopped"] = "a render failed: " + (job.get("error") or "")[:200]
                    self._log(film, film["run"]["stopped"])
                    films.save(film)
                    ended = (film, dict(film["run"]))
                else:
                    ended = None
            if ended:
                for cb in list(self.on_run_end):
                    await cb(*ended)
            return
        if job["status"] == "done":
            await self.advance(fid)

    # ------------------------------------------------------------------ the gate
    async def approve(self, fid, sid):
        with films.LOCK:
            film = films.load(fid)
            films.set_verdict(film, sid, "approved")
            films.save(film)
        await self.advance(fid)
        return films.load(fid)

    async def reroll(self, fid, sid, seed=0, force=False):
        """Render a shot again (a new take). Its prompt is composed again, so an edit made since counts."""
        with films.LOCK:
            film = films.load(fid)
            shot = films.get_shot(film, sid)
            if not shot:
                raise KeyError(sid)
            if any(j.get("shot") == sid for j in self._film_jobs(fid)):
                raise ValueError("this shot is already in the queue")
            ok, why = films.eligible(film, sid, ignore_gate=force or bool(film.get("quick")))
            if not ok:
                raise ValueError(why)
            t = films.active_take(shot)
            if t and t.get("verdict") == "pending":
                t["verdict"] = "rejected"
            job = self.queue_shot(film, shot, seed=seed, front=True, force=force or bool(film.get("quick")))
            films.save(film)
        return job


# ---------------------------------------------------------------------- the night shift
class NightShift:
    """A batch that starts by itself: now, when the machine has been idle for two minutes, or at a time of day."""
    IDLE = 120

    def __init__(self, queue, production):
        self.queue, self.production = queue, production
        production.on_run_end.append(self._run_ended)
        self._task = None
        self._idle_since = time.time()

    def _file(self, sid):
        return config.home("nightshift", sid + ".json")

    def all(self):
        root = config.home("nightshift")
        out = [config.read_json(os.path.join(root, f)) for f in sorted(os.listdir(root)) if f.endswith(".json")]
        return sorted([s for s in out if s], key=lambda s: s["created"], reverse=True)

    def get(self, sid):
        return config.read_json(self._file(sid)) if sid and "/" not in sid else None

    def plan(self, fid, start="idle", retries=1, upscale=False, name=""):
        film = films.load(fid)
        if not film:
            raise KeyError(fid)
        todo = [s for s in film["shots"] if s["status"] in ("todo", "stale", "failed") or not s.get("part")]
        if not todo:
            raise ValueError("every shot of this film already has a take")
        at = None
        if start not in ("now", "idle"):
            try:
                hh, mm = [int(x) for x in start.split(":")]
                now = datetime.datetime.now()
                at_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if at_dt <= now:
                    at_dt += datetime.timedelta(days=1)
                at = at_dt.timestamp()
            except Exception:
                raise ValueError("start is 'now', 'idle' or a time like 23:00")
        shift = {"id": time.strftime("%Y%m%d_%H%M") + "_" + uuid.uuid4().hex[:4], "film": fid, "film_name": film["name"],
                 "name": name or f"{film['name']} {time.strftime('%d %b')}", "start": start, "at": at, "retries": int(retries),
                 "upscale": bool(upscale), "status": "planned", "created": time.time(), "shots": len(todo)}
        config.write_json(self._file(shift["id"]), shift)
        return shift

    def cancel(self, sid):
        s = self.get(sid)
        if s and s["status"] == "planned":
            s["status"] = "cancelled"
            config.write_json(self._file(sid), s)
        return s

    async def start_now(self, sid):
        s = self.get(sid)
        if not s or s["status"] != "planned":
            raise ValueError("this shift is not waiting to start")
        if any(x["status"] == "running" for x in self.all()):
            raise ValueError("another shift is running; one runs at a time")
        s.update(status="running", started=time.time())
        config.write_json(self._file(sid), s)
        await self.production.start(s["film"], mode="keep_going", retries=s["retries"], upscale=s["upscale"], shift=sid)
        return s

    async def _run_ended(self, film, run):
        sid = run.get("shift")
        s = self.get(sid) if sid else None
        if not s or s["status"] != "running":
            return
        s.update(status="finishing", run_stopped=run.get("stopped", ""))
        config.write_json(self._file(sid), s)
        self.queue.add("dailies", {"shift": sid}, title=f"Dailies · {s['name']}", film=s["film"])

    async def resume(self):
        """After a restart of the studio: a shift that was running carries on from the next shot without a take, and
        one that was cutting its reel cuts it again."""
        for s in self.all():
            if s["status"] == "running":
                await self.production.start(s["film"], mode="keep_going", retries=s["retries"], upscale=s["upscale"], shift=s["id"])
            elif s["status"] == "finishing" and not any(j["kind"] == "dailies" and j["status"] in ("queued", "running")
                                                        and j["params"].get("shift") == s["id"] for j in self.queue.jobs):
                self.queue.add("dailies", {"shift": s["id"]}, title=f"Dailies · {s['name']}", film=s["film"])

    def start(self):
        self._task = asyncio.get_running_loop().create_task(self._tick())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _tick(self):
        while True:
            try:
                if self.queue.busy("gpu"):
                    self._idle_since = time.time()
                shifts = self.all()
                if not any(s["status"] == "running" for s in shifts):
                    for s in reversed(shifts):                       # oldest first
                        if s["status"] != "planned":
                            continue
                        due = (s["start"] == "now" or (s["start"] == "idle" and time.time() - self._idle_since >= self.IDLE)
                               or (s.get("at") and time.time() >= s["at"]))
                        if due:
                            await self.start_now(s["id"])
                            break
            except asyncio.CancelledError:
                raise
            except Exception:
                import traceback
                traceback.print_exc()
            await asyncio.sleep(15)
