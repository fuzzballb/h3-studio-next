"""A small async client for ComfyUI's HTTP API and its progress websocket.

Everything the studio renders goes through here: a graph is posted to /prompt, the websocket reports the step
it is on, and /history says when it is done. Errors carry ComfyUI's own message.
"""
import asyncio
import json
import os
import time
import uuid

import aiohttp

from . import config


class ComfyError(Exception):
    """ComfyUI refused a graph or a job failed; the message is ComfyUI's."""


class ComfyDown(ComfyError):
    """ComfyUI does not answer."""


def _node_errors(body):
    """ComfyUI's validation answer as one readable line per problem."""
    try:
        data = json.loads(body)
    except ValueError:
        return body[:600]
    lines = []
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        lines.append(err["message"] + (": " + err["details"] if err.get("details") else ""))
    for nid, ne in (data.get("node_errors") or {}).items():
        for e in ne.get("errors", []):
            lines.append(f'node {nid} ({ne.get("class_type", "?")}): {e.get("message", "")} {e.get("details", "")}'.strip())
    return "; ".join(lines)[:1500] or body[:600]


class Comfy:
    def __init__(self, url=None):
        self.url = (url or config.settings()["comfy_url"]).rstrip("/")
        self.client_id = uuid.uuid4().hex
        self._session = None
        self._info = None
        self._info_time = 0.0
        self.progress = {}          # prompt_id -> {"node", "value", "max", "time"}
        self._ws_task = None

    async def session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_read=600))
        return self._session

    async def close(self):
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method, path, timeout=30, **kw):
        s = await self.session()
        try:
            async with s.request(method, self.url + path, timeout=aiohttp.ClientTimeout(total=timeout), **kw) as r:
                body = await r.read()
                return r.status, body
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError, OSError) as e:
            raise ComfyDown(f"ComfyUI does not answer at {self.url} ({type(e).__name__})") from e

    async def get_json(self, path, timeout=30):
        status, body = await self._request("GET", path, timeout)
        if status != 200:
            raise ComfyError(f"GET {path}: HTTP {status}")
        return json.loads(body.decode("utf-8", "replace"), strict=False)     # history can hold raw control chars

    async def up(self):
        try:
            status, _ = await self._request("GET", "/queue", 4)
            return status == 200
        except ComfyDown:
            return False

    async def queue(self):
        return await self.get_json("/queue", 8)

    async def system_stats(self):
        return await self.get_json("/system_stats", 8)

    async def terminal(self):
        """What ComfyUI printed last, as text with its colour codes and carriage returns: ComfyUI keeps its last few
        hundred writes for its own Logs panel. None when this ComfyUI does not offer them; ComfyDown when it does not
        answer."""
        try:
            data = await self.get_json("/internal/logs/raw", 6)
        except ComfyDown:
            raise
        except (ComfyError, ValueError):
            return None
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return None
        return "".join(str(e.get("m", "")) for e in entries if isinstance(e, dict))

    async def object_info(self, refresh=False, max_age=600):
        """Every node class ComfyUI has, with its inputs. Cached: it is a few megabytes."""
        if refresh or self._info is None or time.time() - self._info_time > max_age:
            self._info = await self.get_json("/object_info", 60)
            self._info_time = time.time()
        return self._info

    async def submit(self, graph, front=False):
        body = {"prompt": graph, "client_id": self.client_id}
        if front:
            body["front"] = True
        status, raw = await self._request("POST", "/prompt", 60, json=body)
        if status != 200:
            raise ComfyError("ComfyUI refused the graph: " + _node_errors(raw.decode("utf-8", "replace")))
        self.ensure_ws()
        return json.loads(raw)["prompt_id"]

    async def history(self, prompt_id):
        h = await self.get_json(f"/history/{prompt_id}", 30)
        return h.get(prompt_id)

    async def position(self, prompt_id):
        """('running', 0) / ('pending', n ahead) / (None, 0) when ComfyUI no longer has it queued."""
        q = await self.queue()
        if any(item[1] == prompt_id for item in q.get("queue_running", [])):
            return "running", 0
        pending = sorted(q.get("queue_pending", []), key=lambda item: item[0])
        for n, item in enumerate(pending):
            if item[1] == prompt_id:
                return "pending", n + len(q.get("queue_running", []))
        return None, 0

    async def wait(self, prompt_id, on_tick=None, poll=1.5, down_after=90):
        """Wait for a prompt. Returns its outputs; raises ComfyError with ComfyUI's message when it failed.

        ComfyUI that stops answering for `down_after` seconds is reported as ComfyDown (it was killed more than
        once by the kernel when a job kept too many full-size frames in RAM).
        """
        down_since = None
        while True:
            try:
                h = await self.history(prompt_id)
                down_since = None
            except ComfyDown:
                down_since = down_since or time.time()
                if time.time() - down_since > down_after:
                    raise
                await asyncio.sleep(poll)
                continue
            if h and h.get("status", {}).get("completed") is not None or (h and h.get("status", {}).get("status_str") == "error"):
                st = h.get("status", {})
                self.progress.pop(prompt_id, None)
                if st.get("status_str") == "error":
                    raise ComfyError(_history_error(st))
                return h.get("outputs", {})
            if h is None:
                state, _ = await self.position(prompt_id)
                if state is None:
                    h = await self.history(prompt_id)         # finished between the two calls?
                    if not h:
                        raise ComfyError("ComfyUI no longer has this job (it was removed from the queue, or ComfyUI restarted)")
                    continue
            if on_tick:
                await on_tick()
            await asyncio.sleep(poll)

    async def interrupt(self, prompt_id):
        """Stop one job: out of the queue when it waits, interrupted when it runs. A bare /interrupt can hit the next job."""
        try:
            await self._request("POST", "/queue", 10, json={"delete": [prompt_id]})
            await self._request("POST", "/interrupt", 10, json={"prompt_id": prompt_id})
        except ComfyDown:
            pass

    async def free(self):
        """Ask ComfyUI to unload its models (before an upscale after a generation run RAM was at 59 of 62 GB)."""
        try:
            await self._request("POST", "/free", 20, json={"unload_models": True, "free_memory": True})
        except ComfyDown:
            pass

    async def upload(self, path, name=None, overwrite=True):
        """Put a file into ComfyUI's input folder. Returns the name ComfyUI stored it under."""
        name = name or os.path.basename(path)
        form = aiohttp.FormData()
        with open(path, "rb") as f:
            form.add_field("image", f.read(), filename=name, content_type="application/octet-stream")
        form.add_field("overwrite", "true" if overwrite else "false")
        status, raw = await self._request("POST", "/upload/image", 120, data=form)
        if status != 200:
            raise ComfyError(f"upload of {name} failed: HTTP {status}")
        return json.loads(raw).get("name", name)

    # ---- progress over the websocket (optional: everything works from /history alone) ----
    def ensure_ws(self):
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.get_running_loop().create_task(self._ws_loop())

    async def _ws_loop(self):
        ws_url = self.url.replace("http", "ws", 1) + f"/ws?clientId={self.client_id}"
        while True:
            try:
                s = await self.session()
                async with s.ws_connect(ws_url, heartbeat=30) as ws:
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue                        # binary frames are preview images
                        try:
                            m = json.loads(msg.data)
                        except ValueError:
                            continue
                        d = m.get("data") or {}
                        pid = d.get("prompt_id")
                        if not pid:
                            continue
                        p = self.progress.setdefault(pid, {"node": None, "value": 0, "max": 0, "time": time.time()})
                        if m.get("type") == "executing":
                            p.update(node=d.get("node"), value=0, max=0, time=time.time())
                        elif m.get("type") == "progress":
                            p.update(node=d.get("node", p.get("node")), value=d.get("value", 0), max=d.get("max", 0), time=time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            await asyncio.sleep(3)


def _history_error(status):
    for kind, data in reversed(status.get("messages", [])):
        if kind == "execution_error":
            return (f'{data.get("node_type", "node")} ({data.get("node_id", "?")}): '
                    f'{data.get("exception_message", "").strip()}')[:1200]
        if kind == "execution_interrupted":
            return "interrupted"
    return "the job failed (no message from ComfyUI)"


def files_of(outputs, keys=("images", "gifs", "audio", "video", "videos")):
    """Every file a finished prompt reported: [{"filename", "subfolder", "type"}]."""
    out = []
    for node in (outputs or {}).values():
        for key in keys:
            for item in node.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    out.append({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output")})
    return out


def combo_options(info, node, field):
    """The choices of a combo input, in both of ComfyUI's schema styles."""
    spec = None
    for section in ("required", "optional"):
        spec = (info.get(node, {}).get("input", {}).get(section, {}) or {}).get(field) or spec
    if not spec:
        return []
    if isinstance(spec[0], list):
        opts = spec[0]
    elif len(spec) > 1 and isinstance(spec[1], dict):
        opts = spec[1].get("options", [])
    else:
        opts = []
    # a dynamic combo lists {"key": ..., "inputs": ...} entries
    return [o.get("key") if isinstance(o, dict) else o for o in opts if not isinstance(o, dict) or o.get("key") is not None]
