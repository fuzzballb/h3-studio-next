"""The machine: is ComfyUI up, how much memory and disk is free, and will a job fit.

ComfyUI was killed by the kernel more than once on a 62 GB machine by jobs that keep many full-size frames in RAM (15 s
of 1440x2560 video; an upscale of 484 frames). So the studio estimates the frames a job holds before it is queued and
says so when it will not fit, and when ComfyUI disappears mid-job it looks in the kernel log for the reason.

Starting and stopping: the studio only ever stops a ComfyUI it started itself, by its process group, and only when
ComfyUI's queue is empty.
"""
import asyncio
import os
import re
import shutil
import signal
import subprocess
import time
from urllib.parse import urlparse

from . import config
from .comfy import ComfyDown

BYTES_PER_PIXEL = 12          # one decoded frame in RAM: float32 RGB
COPIES = 3                    # decode, the node that writes it, ffmpeg's pipe: frames exist about three times


def memory():
    """RAM in bytes: {"total", "available"} (Linux /proc/meminfo; zeros elsewhere)."""
    out = {"total": 0, "available": 0}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k == "MemTotal":
                    out["total"] = int(v.split()[0]) * 1024
                elif k == "MemAvailable":
                    out["available"] = int(v.split()[0]) * 1024
    except OSError:
        pass
    return out


def gpus():
    """[{"name", "used", "total", "util"}] from nvidia-smi; [] without it."""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) == 4:
            out.append({"name": p[0], "used": int(p[1]) * 2 ** 20, "total": int(p[2]) * 2 ** 20, "util": int(p[3])})
    return out


def disk(path=None):
    path = path or config.OUTPUT_DIR
    try:
        u = shutil.disk_usage(os.path.realpath(path))
        return {"path": os.path.realpath(path), "free": u.free, "total": u.total}
    except OSError:
        return {"path": path, "free": 0, "total": 0}


def frames_bytes(width, height, frames, copies=COPIES):
    return int(width) * int(height) * int(frames) * BYTES_PER_PIXEL * copies


WARN_SHARE, REFUSE_SHARE = 0.40, 0.70


def fit(width, height, frames, what="this clip", scale=1.0, fps_multiplier=1):
    """Will the frames of a job fit in RAM? Returns {"ok", "level": ok|tight|no, "need", "total", "text"}.

    A rough estimate, not a model of ComfyUI: frames x pixels x 12 bytes, three copies, against the machine's RAM.
    It is set by what happened on a 62 GB machine: 15 s of 1440x2560 (45 GB by this count, 0.72 of the RAM) was killed
    by the kernel; the x1.5, 48 fps upscale of a 10 s part at 1152x640 (27 GB, 0.44) works, with RAM nearly full.
    So above 0.70 of the RAM a job is refused, and above 0.40 it gets a warning.
    """
    w, h = int(width * scale), int(height * scale)
    need = frames_bytes(w, h, frames * fps_multiplier)
    total = memory()["total"]
    if not total:
        return {"ok": True, "level": "ok", "need": need, "total": 0, "text": ""}
    share = need / total
    gb = lambda b: f"{b / 2 ** 30:.0f} GB"
    if share > REFUSE_SHARE:
        return {"ok": False, "level": "no", "need": need, "total": total,
                "text": f"{what} keeps about {gb(need)} of frames in memory ({w}x{h}, {frames * fps_multiplier} frames) and this "
                        f"machine has {gb(total)}: ComfyUI would be killed. Use a smaller size or a shorter part."}
    if share > WARN_SHARE:
        return {"ok": True, "level": "tight", "need": need, "total": total,
                "text": f"{what} keeps about {gb(need)} of frames in memory, of {gb(total)}: it fits, but close other programs first."}
    return {"ok": True, "level": "ok", "need": need, "total": total, "text": ""}


TERMINAL_CHARS = 200_000       # of ComfyUI's output, the end that is sent to the page
LOG_TAIL = 64_000              # of a log file on disk, its last bytes (a whole start-up is about 22 kB)


def tail(path, limit=LOG_TAIL):
    """The end of a text file, starting at a whole line."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        data = f.read()
    if size > limit:
        cut = data.find(b"\n")
        if cut >= 0:
            data = data[cut + 1:]
    return data.decode("utf-8", "replace")


class Machine:
    def __init__(self, comfy):
        self.comfy = comfy
        self.proc = None            # a ComfyUI this studio started
        self.started_at = 0.0
        self.last_down = ""

    def ours(self):
        """Is a ComfyUI that this studio started running?"""
        return bool(self.proc and self.proc.poll() is None)

    def starting(self, up):
        """The studio started ComfyUI and it is still loading: it runs but does not answer yet."""
        return self.ours() and not up

    async def status(self):
        up = await self.comfy.up()
        out = {"comfy": {"up": up, "url": self.comfy.url, "ours": self.ours(), "starting": self.starting(up),
                         "can_start": bool(config.comfy_start_command())},
               "memory": memory(), "gpus": gpus(), "disk": disk(), "home_disk": disk(os.path.expanduser("~")),
               "paths": {"comfy": config.COMFY_DIR, "output": os.path.realpath(config.OUTPUT_DIR), "studio": config.STUDIO_HOME}}
        if up:
            try:
                q = await self.comfy.queue()
                out["comfy"]["running"] = len(q.get("queue_running", []))
                out["comfy"]["pending"] = len(q.get("queue_pending", []))
            except Exception:
                pass
        return out

    async def start_comfy(self, wait=240):
        """Start ComfyUI with the configured command, detached, and wait until it answers.

        Asked again while that ComfyUI is still loading (a second click, the desktop launcher and the page at once),
        it waits for the same one: a second ComfyUI would load everything and then find the port taken."""
        if await self.comfy.up():
            return True
        if not self.ours():
            cmd = config.comfy_start_command()
            if not cmd:
                raise ValueError("no start command for ComfyUI is set (Settings > ComfyUI), and there is no run.sh in "
                                 + config.COMFY_DIR)
            path = config.home("logs", "comfyui_stdout.log")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.isfile(path):                    # the run before this one stays readable: it may say why it died
                os.replace(path, path[:-4] + ".prev.log")
            with open(path, "wb") as log:               # PYTHONUNBUFFERED: lines reach the file as they are printed
                self.proc = subprocess.Popen(cmd, shell=True, cwd=config.COMFY_DIR, stdout=log, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, start_new_session=True,
                                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
            self.started_at = time.time()
        proc = self.proc
        end = time.time() + wait
        while time.time() < end:
            if await self.comfy.up():
                await self.comfy.object_info(refresh=True)
                return True
            if proc.poll() is not None:
                raise ValueError(f"ComfyUI stopped right after starting (exit {proc.returncode}); see "
                                 + config.home("logs", "comfyui_stdout.log"))
            await asyncio.sleep(min(2.0, max(0.05, end - time.time())))
        raise ValueError(f"ComfyUI did not answer within {wait:g} s; it may still be loading")

    async def stop_comfy(self):
        """Stop the ComfyUI this studio started. Refused while it has jobs, and for a ComfyUI started elsewhere."""
        if not self.ours():
            raise ValueError("this ComfyUI was not started by the studio; stop it where you started it")
        try:
            q = await self.comfy.queue()
            if q.get("queue_running") or q.get("queue_pending"):
                raise ValueError("ComfyUI still has jobs; wait for them or cancel them first")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
        os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        for _ in range(30):
            if self.proc.poll() is not None:
                break
            await asyncio.sleep(0.5)
        self.proc = None
        return True

    def log_files(self):
        """Where a ComfyUI on this computer also leaves its terminal output: the file the studio's own start writes,
        and the one ComfyUI-Manager keeps in ComfyUI's user folder. Nothing for a ComfyUI on another machine."""
        url = urlparse(self.comfy.url)
        if url.hostname not in ("127.0.0.1", "localhost", "::1"):
            return []
        user = os.path.join(config.COMFY_DIR, "user")
        return [config.home("logs", "comfyui_stdout.log"), os.path.join(user, f"comfyui_{url.port or 8188}.log"),
                os.path.join(user, "comfyui.log")]

    def newest_log(self):
        """(path, time written, its end) of the log file ComfyUI wrote to last, or None. Two files written within the
        same minute are the same run: then the first in `log_files` wins, so the view does not jump between them."""
        found = []
        for p in self.log_files():
            try:
                found.append((p, os.path.getmtime(p)))
            except OSError:
                pass
        if not found:
            return None
        newest = max(t for _, t in found)
        path, written = next((p, t) for p, t in found if t >= newest - 60)
        try:
            return path, written, tail(path)
        except OSError:
            return None

    async def comfy_output(self):
        """ComfyUI's terminal output: {"up", "starting", "live", "source", "written", "text"}.

        Live from ComfyUI when it answers. While it is loading, after it died, or when it does not offer its output,
        the end of the newest log file instead ("source" names it), so the reason it is not up can be read too."""
        try:
            text = await self.comfy.terminal()
            up = True
        except ComfyDown:
            text, up = None, False
        out = {"up": up, "starting": self.starting(up), "live": text is not None, "source": "", "written": None, "text": ""}
        if text is not None:
            out["text"] = text[-TERMINAL_CHARS:]
            return out
        log = await asyncio.to_thread(self.newest_log)
        if log:
            path, out["written"], out["text"] = log
            inside = os.path.abspath(path).startswith(os.path.abspath(config.COMFY_DIR) + os.sep)
            out["source"] = os.path.relpath(path, config.COMFY_DIR) if inside else path
        return out

    async def ensure_comfy(self, ctx=None):
        """Bring ComfyUI up when the settings allow it. True when it answers."""
        if await self.comfy.up():
            return True
        if not config.settings().get("auto_start_comfy") or not config.comfy_start_command():
            return False
        if ctx:
            ctx.say("starting ComfyUI")
        try:
            return await self.start_comfy()
        except ValueError:
            return False

    def why_down(self):
        """A hint for a job that lost ComfyUI: the kernel's out-of-memory line when there is one."""
        hint = ""
        try:
            r = subprocess.run(["journalctl", "-k", "--since", "-15 min", "--no-pager"], capture_output=True, text=True, timeout=5)
            lines = [ln for ln in r.stdout.splitlines() if re.search(r"out of memory|oom-kill|Killed process", ln, re.I)]
            if lines:
                hint = ". The kernel log says it ran out of memory: " + lines[-1].split("kernel:")[-1].strip()[:200]
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.last_down = hint
        return hint or ". If it was killed, the usual reason is too many full-size frames in memory (size x length)."
