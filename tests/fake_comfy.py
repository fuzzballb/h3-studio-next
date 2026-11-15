"""A stand-in for ComfyUI: the endpoints the studio uses, "rendering" by writing small synthetic files where the real
nodes would write theirs. It lets the queue, the checks, the gate and the film logic run without a GPU.

    fake = FakeComfy(); await fake.start(); ...; await fake.stop()        fake.url is its address

fail_next = "message" makes the next prompt fail like a node error; delay = seconds a render takes.
"""
import asyncio
import json
import os
import uuid

from aiohttp import web

from studio import config, lengths

from . import env, media

COLORS = ["blue", "green", "purple", "orange", "teal", "brown", "navy", "olive"]


class FakeComfy:
    def __init__(self):
        self.history, self.pending, self.prompts = {}, {}, []
        self.fail_next, self.delay, self.cut_next, self.jump_next = "", 0.0, False, False
        self.runner = None
        self.url = ""
        self.interrupted = set()
        self.printed = ["Starting server\n", "\x1b[32m[INFO]\x1b[0m models are ready\n", "\r 50%|#####     | 4/8"]

    async def start(self):
        app = web.Application()
        app.add_routes([web.get("/queue", self.queue), web.get("/system_stats", self.stats), web.get("/object_info", self.info),
                        web.post("/prompt", self.prompt), web.get("/history/{pid}", self.hist), web.post("/interrupt", self.interrupt),
                        web.post("/queue", self.ok), web.post("/free", self.ok), web.post("/upload/image", self.ok), web.get("/ws", self.ws),
                        web.get("/internal/logs/raw", self.logs)])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        await self.runner.cleanup()

    async def ok(self, request):
        return web.json_response({})

    async def interrupt(self, request):
        body = await request.json() if request.can_read_body else {}
        self.interrupted.add(body.get("prompt_id"))
        return web.json_response({})

    async def queue(self, request):
        return web.json_response({"queue_running": [[0, p] for p in self.pending], "queue_pending": []})

    async def logs(self, request):
        return web.json_response({"entries": [{"t": "2026-01-01T00:00:00", "m": m} for m in self.printed], "size": {"cols": 80, "rows": 24}})

    async def stats(self, request):
        return web.json_response({"system": {}, "devices": []})

    async def info(self, request):
        return web.json_response(env.object_info())

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _ in ws:
            pass
        return ws

    async def hist(self, request):
        pid = request.match_info["pid"]
        return web.json_response({pid: self.history[pid]} if pid in self.history else {})

    async def prompt(self, request):
        body = await request.json()
        graph = body["prompt"]
        pid = uuid.uuid4().hex
        self.prompts.append(graph)
        self.pending[pid] = True
        asyncio.get_running_loop().create_task(self._render(pid, graph))
        return web.json_response({"prompt_id": pid})

    async def _render(self, pid, graph):
        await asyncio.sleep(self.delay)
        if pid in self.interrupted:
            self.history[pid] = {"status": {"status_str": "error", "completed": False, "messages": [["execution_interrupted", {}]]}, "outputs": {}}
            self.pending.pop(pid, None)
            return
        try:
            if self.fail_next:
                msg, self.fail_next = self.fail_next, ""
                raise RuntimeError(msg)
            outputs = await asyncio.to_thread(self._outputs, graph)
            self.history[pid] = {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": outputs}
        except Exception as e:
            self.history[pid] = {"status": {"status_str": "error", "completed": False, "messages": [
                ["execution_error", {"node_type": "FakeNode", "node_id": "1", "exception_message": str(e)}]]}, "outputs": {}}
        self.pending.pop(pid, None)

    # ---- what the real nodes would have written
    def _outputs(self, graph):
        out = {}
        for nid, node in graph.items():
            ct, i = node["class_type"], node["inputs"]
            if ct == "SaveImage":
                rel = i["filename_prefix"] + "_00001_.png"
                media.picture(os.path.join(config.OUTPUT_DIR, rel), COLORS[hash(rel) % len(COLORS)])
                out[nid] = {"images": [{"filename": os.path.basename(rel), "subfolder": os.path.dirname(rel), "type": "output"}]}
            elif ct == "SaveAudio":
                rel = i["filename_prefix"] + "_00001_.flac"
                path = os.path.join(config.OUTPUT_DIR, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                media.run("-f", "lavfi", "-i", "sine=frequency=300:duration=1.5", path)
                out[nid] = {"audio": [{"filename": os.path.basename(rel), "subfolder": os.path.dirname(rel), "type": "output"}]}
            elif ct == "H3LongVideoAppend":
                out[nid] = self._append(graph, i)
            elif ct == "H3LongVideoUpscaleAppend":
                root = os.path.join(config.LONG_DIR, i["project"])
                seg = os.path.join(root, "segments", f"part_{i['part']:03d}.mkv")
                os.makedirs(os.path.join(root, "upscaled"), exist_ok=True)
                media.run("-i", seg, "-vf", "scale=iw*1.5:-2", "-c:v", "libx264", "-preset", "ultrafast", "-an",
                          os.path.join(root, "upscaled", f"part_{i['part']:03d}.mkv"))
                media.run("-i", os.path.join(root, f"{i['project']}_full.mp4"), "-c", "copy", os.path.join(root, f"{i['project']}_full_upscaled.mp4"))
        return out

    def _append(self, graph, i):
        project, part = i["project"], int(i["part"])
        cont_node = next(n for n in graph.values() if n["class_type"] == "H3LongVideoContinue")
        enc = next(n for n in graph.values() if n["class_type"] in ("PK_MiniMaxH3Combined", "MiniMaxH3ReferenceToVideo"))["inputs"]
        new_shot = bool(cont_node["inputs"].get("new_shot")) or part == 1
        frames = int(enc["length"]) - (0 if new_shot else lengths.CONTEXT)
        root = os.path.join(config.LONG_DIR, project)
        for missing in range(1, part):
            if not os.path.isfile(os.path.join(root, "segments", f"part_{missing:03d}.mkv")):
                raise RuntimeError(f"long video: part {missing} of '{project}' is missing; cannot build up to part {part}")
        os.makedirs(os.path.join(root, "latents"), exist_ok=True)
        shots = config.read_json(os.path.join(root, "shots.json"), {}) or {}
        nxt = part + 1                       # the node moves aside the continuations that followed this part
        while os.path.isfile(os.path.join(root, "segments", f"part_{nxt:03d}.mkv")) and shots.get(str(nxt)) != 0:
            os.makedirs(os.path.join(root, "_superseded"), exist_ok=True)
            for sub, ext in (("segments", ".mkv"), ("latents", ".safetensors")):
                p = os.path.join(root, sub, f"part_{nxt:03d}{ext}")
                if os.path.isfile(p):
                    os.replace(p, os.path.join(root, "_superseded", os.path.basename(p)))
            shots.pop(str(nxt), None)
            nxt += 1
        shots[str(part)] = 0 if new_shot else lengths.CONTEXT
        config.write_json(os.path.join(root, "shots.json"), shots)
        # a continuation keeps the colour of the part before, like a real one keeps its place (unless told to jump)
        prev_color = config.read_json(os.path.join(root, "colors.json"), {}) or {}
        color = prev_color.get(str(part - 1)) if (not new_shot and not self.jump_next) else \
            ("white" if self.jump_next else COLORS[(part + len(self.prompts)) % len(COLORS)])
        self.jump_next = False
        prev_color[str(part)] = color
        config.write_json(os.path.join(root, "colors.json"), prev_color)
        seg = os.path.join(root, "segments", f"part_{part:03d}.mkv")
        seconds = frames / lengths.FPS
        media.clip(seg, seconds, color, size=f"{enc['width'] // 4}x{enc['height'] // 4}", cut_at=seconds / 2 if self.cut_next else None,
                   second_color="white")
        self.cut_next = False
        for name in (f"part_{part:03d}.safetensors", f"part_{part:03d}.cond.pt"):
            with open(os.path.join(root, "latents", name), "wb") as f:
                f.write(os.urandom(64))
        last = part
        while os.path.isfile(os.path.join(root, "segments", f"part_{last + 1:03d}.mkv")):
            last += 1
        with open(os.path.join(root, "segments", "concat.txt"), "w") as f:
            for k in range(1, last + 1):
                f.write(f"file 'part_{k:03d}.mkv'\n")
        full = os.path.join(root, f"{project}_full.mp4")
        media.run("-f", "concat", "-safe", "0", "-i", os.path.join(root, "segments", "concat.txt"), "-c:v", "copy", "-c:a", "aac", full)
        return {"images": [{"filename": os.path.basename(full), "subfolder": f"long_video/{project}", "type": "output"}]}
