"""The studio's web server: the page and its JSON API.

It listens on this computer only (127.0.0.1) unless told otherwise, has no sign-in, and refuses requests that come from
another site's page (Origin) or under another host name (DNS rebinding). Media is served only from ComfyUI's output
and input folders.

Every route answers JSON; an error is {"error": "..."} with status 400 (cannot do that, and why), 404 or 500.
docs/api.md lists the routes; the MCP server (mcp/studio_mcp.py) is a thin layer over them.
"""
import asyncio
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import shutil
import time
import traceback
import uuid
from urllib.parse import unquote

from aiohttp import web

from . import (agent, blockout_scenes, blockouts, canvas, writer, beats, brain, checks, compose, config, films, finish, lengths, library, machine, models, presets, promptcheck,
               work)
from .comfy import Comfy, ComfyDown, ComfyError
from .jobs import Queue, Refused
from .production import NightShift, Production

routes = web.RouteTableDef()
STUDIO = web.AppKey("studio", object)
HOSTS = web.AppKey("hosts", set)
UPLOAD_EXT = library.IMAGE_EXT + library.VIDEO_EXT + library.AUDIO_EXT
MAX_UPLOAD = 2 * 2 ** 30


def ok(data=None, **kw):
    return web.json_response(data if data is not None else kw, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))


def app_of(request):
    return request.app[STUDIO]


class Studio:
    """Everything that lives as long as the server."""

    def __init__(self):
        config.ensure_home()
        self.comfy = Comfy()
        self.machine = machine.Machine(self.comfy)
        self.queue = Queue(self.comfy, work.HANDLERS, self.machine)
        self.production = Production(self.queue)
        self.nightshift = NightShift(self.queue, self.production)

    async def start(self, app):
        self.queue.load()
        library.forget_missing()             # files deleted outside the studio leave the Library
        self.queue.start()
        self._repair()
        await self.nightshift.resume()
        self.nightshift.start()

    async def stop(self, app):
        await self.nightshift.stop()
        await self.queue.stop()
        await self.comfy.close()

    def _repair(self):
        """After a restart: a shot that was rendering when the studio stopped goes back to what it was."""
        for kind in (False, True):
            for s in films.summaries(quick=kind):
                with films.LOCK:
                    film = films.load(s["id"])
                    changed = False
                    for sh in film["shots"]:
                        if sh["status"] in ("rendering", "queued"):
                            t = films.active_take(sh)
                            sh["status"] = ("approved" if t and t.get("verdict") in ("approved", "auto") else "review") if (t and sh.get("part")) else "todo"
                            changed = True
                    if (film.get("run") or {}).get("active"):
                        film["run"]["active"] = False
                        film["run"]["stopped"] = "the studio was restarted; start the run again to carry on"
                        changed = True
                    if changed:
                        films.save(film)

    async def info(self):
        return await self.comfy.object_info()


def _build():
    """Changes when any page file changes: an open page that sees another build was loaded before an update."""
    h = hashlib.sha1()
    for d, _, files in sorted(os.walk(config.STATIC)):
        for f in sorted(files):
            st = os.stat(os.path.join(d, f))
            h.update(f"{f}:{st.st_mtime_ns}:{st.st_size};".encode())
    return h.hexdigest()[:12]


_BUILD = {"at": 0.0, "id": ""}


def build():
    """_build(), looked at again at most every 3 s: a page file changed without a restart counts too."""
    if time.time() - _BUILD["at"] > 3:
        _BUILD.update(at=time.time(), id=_build())
    return _BUILD["id"]


@web.middleware
async def guard(request, handler):
    resp = await _guarded(request, handler)
    try:
        resp.headers["X-Studio-Build"] = build()
    except (AttributeError, RuntimeError):            # a response that is already sent
        pass
    return resp


async def _guarded(request, handler):
    """Only this computer's own page may call the API, and every failure becomes readable JSON."""
    host = (request.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
    allowed = request.app[HOSTS]
    if host not in allowed:
        return web.json_response({"error": f"this studio is not reachable as '{host}'"}, status=403)
    origin = request.headers.get("Origin")
    if origin and request.method != "GET":
        o = re.sub(r"^https?://", "", origin).rsplit(":", 1)[0].strip("[]")
        if o not in allowed:
            return web.json_response({"error": "requests from other sites are refused"}, status=403)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except KeyError as e:
        return web.json_response({"error": f"not found: {e.args[0] if e.args else ''}"}, status=404)
    except (Refused, ValueError, ComfyError) as e:
        return web.json_response({"error": str(e)}, status=503 if isinstance(e, ComfyDown) else 400)
    except Exception as e:
        traceback.print_exc()
        return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)


async def body(request):
    if not request.can_read_body:
        return {}
    if "application/json" not in (request.headers.get("Content-Type") or ""):
        raise ValueError("send JSON (Content-Type: application/json)")
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("send a JSON object")
    return data


# ============================================================================================ state, machine, settings
def job_view(j):
    out = {k: j.get(k) for k in ("id", "kind", "title", "status", "lane", "created", "started", "finished", "progress", "error",
                                 "result", "film", "shot", "eta")}
    return out


def gate_list():
    """Every take that waits for a person, across films."""
    out = []
    for s in films.summaries():
        film = films.load(s["id"])
        for i, sh in enumerate(film["shots"]):
            if sh["status"] == "review":
                t = films.active_take(sh) or {}
                out.append({"film": film["id"], "film_name": film["name"], "shot": sh["id"], "index": i + 1,
                            "title": sh.get("title", ""), "take": t.get("n"), "ok": (t.get("checks") or {}).get("ok"),
                            "summary": (t.get("checks") or {}).get("summary", ""), "preview": t.get("preview", ""),
                            "sheet": t.get("sheet", ""), "needs_look": bool(t.get("needs_look"))})
    return out


@routes.get("/api/state")
async def state(request):
    st = app_of(request)
    up = await st.comfy.up()
    return ok({"comfy": {"up": up, "starting": st.machine.starting(up), "url": st.comfy.url},
               "jobs": [job_view(j) for j in st.queue.recent(40)],
               "gate": gate_list(), "busy": {"gpu": st.queue.busy("gpu"), "cpu": st.queue.busy("cpu")}, "time": time.time()})


@routes.get("/api/machine")
async def machine_info(request):
    st = app_of(request)
    out = await st.machine.status()
    out["tools"] = {"ffmpeg": checks.have_ffmpeg(), "whisper": checks.whisper_available(), "whisper_dir": config.whisper_dir()}
    out["brain"] = brain.state()
    if out["comfy"]["up"]:
        info = await st.comfy.object_info(refresh=request.query.get("refresh") == "1")
        roles = models.resolve(info)
        usable, quantized = models.loras(info)
        out.update(roles=[{"role": r, "title": models.ROLE_TITLES[r], "file": roles[r], "options": models.options_for(info, r),
                           "chosen": config.settings()["models"].get(r, "")} for r in models.ROLES],
                   features={k: {**v, "why": models.why_not(v)} for k, v in models.features(info).items()},
                   loras=usable, loras_quantized=quantized, voices=models.voices(info), nodes=len(info))
    else:
        out.update(roles=[], features={}, loras=[], loras_quantized=[], voices=[], nodes=0)
    return ok(out)


@routes.post("/api/machine/comfy")
async def comfy_control(request):
    st = app_of(request)
    action = (await body(request)).get("action")
    if action == "start":
        await st.machine.start_comfy()
    elif action == "stop":
        if st.queue.busy("gpu"):
            raise ValueError("the studio still has renders waiting; cancel them first")
        await st.machine.stop_comfy()
    elif action == "free":
        await st.comfy.free()
    else:
        raise ValueError("action is start, stop or free")
    return ok(await st.machine.status())


@routes.get("/api/machine/comfy/output")
async def comfy_output(request):
    return ok(await app_of(request).machine.comfy_output())


@routes.get("/api/settings")
async def get_settings(request):
    return ok(config.settings())


@routes.put("/api/settings")
async def put_settings(request):
    st = app_of(request)
    new = config.update(await body(request))
    st.comfy.url = new["comfy_url"].rstrip("/")
    return ok(new)


@routes.get("/api/presets")
async def get_presets(request):
    return ok({**presets.everything(), "lengths": lengths.table(), "sizes": [{"name": n, "width": w, "height": h} for n, w, h in lengths.SIZES],
               "image_sizes": [{"name": n, "width": w, "height": h} for n, w, h in lengths.IMAGE_SIZES],
               "stock": {"take": compose.TAKE, "cont": compose.CONT, "notext": compose.NOTEXT}})


@routes.post("/api/prompt/check")
async def prompt_check(request):
    d = await body(request)
    f = promptcheck.check(d.get("prompt") or "", new_shot=bool(d.get("new_shot", True)), lines=d.get("lines") or [],
                          seconds=float(d.get("seconds") or 10), talking_head=bool(d.get("talking_head")))
    return ok({"findings": f, "summary": promptcheck.summary(f), "forbids": [p for p, _ in promptcheck.forbids(d.get("prompt") or "")]})


@routes.post("/api/fit")
async def fit(request):
    d = await body(request)
    return ok(machine.fit(int(d["width"]), int(d["height"]), int(d["frames"]), scale=float(d.get("scale") or 1),
                          fps_multiplier=int(d.get("fps_multiplier") or 1)))


# ============================================================================================ jobs
@routes.get("/api/jobs")
async def jobs_list(request):
    return ok([job_view(j) for j in app_of(request).queue.recent(int(request.query.get("limit", 100)))])


@routes.post("/api/jobs")
async def jobs_add(request):
    d = await body(request)
    j = app_of(request).queue.add(d.get("kind"), d.get("params") or {}, title=d.get("title") or "")
    return ok(job_view(j))


@routes.get("/api/jobs/{id}")
async def jobs_get(request):
    j = app_of(request).queue.get(request.match_info["id"])
    if not j:
        raise KeyError("job")
    return ok({**job_view(j), "params": j.get("params"), "trace": j.get("trace")})


@routes.delete("/api/jobs/{id}")
async def jobs_delete(request):
    q = app_of(request).queue
    j = q.get(request.match_info["id"])
    if not j:
        raise KeyError("job")
    if j["status"] in ("queued", "running"):
        await q.cancel(j["id"])
        return ok(cancelled=True)
    q.remove(j["id"])
    return ok(removed=True)


@routes.post("/api/jobs/clear")
async def jobs_clear(request):
    d = await body(request)
    return ok(removed=app_of(request).queue.clear(tuple(d.get("statuses") or ("failed", "cancelled"))))


# ============================================================================================ media and the library
def _serve(root, rel):
    path = os.path.normpath(os.path.join(root, rel))
    if not config.inside(path, root) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    resp = web.FileResponse(path)
    ctype = mimetypes.guess_type(path)[0]
    if path.endswith(".mkv"):
        ctype = "video/x-matroska"
    if ctype:
        resp.content_type = ctype
    return resp


@routes.get("/media/{path:.+}")
async def media(request):
    return _serve(config.OUTPUT_DIR, request.match_info["path"])


@routes.get("/input/{path:.+}")
async def media_input(request):
    return _serve(config.INPUT_DIR, request.match_info["path"])


@routes.get("/thumb/{id}.jpg")
async def thumb(request):
    a = library.get(request.match_info["id"])
    if not a:
        raise web.HTTPNotFound()
    t = await asyncio.to_thread(library.thumb, a)
    if not t:
        raise web.HTTPNotFound()
    return web.FileResponse(t, headers={"Cache-Control": "max-age=30"})


@routes.get("/takeframe/{id}/{sid}.jpg")
async def take_frame(request):
    """A frame from the middle of the take a shot has in the film: what the storyboard shows for a rendered shot.
    Made once and kept beside the take."""
    _, sh = _film_shot(request)
    t = films.active_take(sh)
    src = os.path.join(config.OUTPUT_DIR, (t or {}).get("preview") or "")
    if not t or not t.get("preview") or not os.path.isfile(src):
        raise web.HTTPNotFound()
    dst = os.path.splitext(src)[0] + "_frame.jpg"
    if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        if not await asyncio.to_thread(checks.grab, src, dst, at=float(t.get("duration") or 0) / 2):
            raise web.HTTPNotFound()
    return web.FileResponse(dst, headers={"Cache-Control": "max-age=600"})


@routes.get("/refthumb")
async def ref_thumb(request):
    """A small picture of a loader name (a cast face, a plate), wherever it lives."""
    name = request.query.get("name", "")
    path = config.ref_path(name)
    if not (config.inside(path, config.OUTPUT_DIR) or config.inside(path, config.INPUT_DIR)) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    key = uuid.uuid5(uuid.NAMESPACE_URL, f"{os.path.realpath(path)}|{os.path.getmtime(path)}").hex
    dst = config.home("library", "thumbs", "ref_" + key + ".jpg")
    if not os.path.isfile(dst) and not await asyncio.to_thread(checks.thumbnail, path, dst, 320):
        raise web.HTTPNotFound()
    return web.FileResponse(dst, headers={"Cache-Control": "max-age=600"})


def asset_view(a):
    return {**a, "url": library.url(a), "thumb": f"/thumb/{a['id']}.jpg?m={int(a.get('mtime', 0))}" if a.get("kind") != "audio" else "",
            "ref": config.out_ref(library.abs_path(a))}


@routes.get("/api/library")
async def library_list(request):
    q = request.query
    items = library.search(q.get("q", ""), q.get("kind", ""), q.get("film", ""), trashed=q.get("trashed") == "1",
                           limit=int(q.get("limit", 400)), favorite=q.get("favorite") in ("1", "true"),
                           folder=q.get("folder", ""), source=q.get("source", ""), surface=q.get("surface", ""),
                           sort=q.get("sort", "newest"))
    return ok({"items": [asset_view(a) for a in items], "trash": library.trash_size()})


@routes.get("/api/library/summary")
async def library_summary(request):
    return ok(library.summary())


@routes.post("/api/library/bulk")
async def library_bulk(request):
    """{ids, action: favorite | unfavorite | move, folder}: all of them, or none when one id is unknown."""
    d = await body(request)
    return ok(changed=library.bulk(d.get("ids"), d.get("action"), d.get("folder") or ""))


@routes.patch("/api/library/{id}")
async def library_patch(request):
    """{favorite, folder, name}: change one file's record."""
    d = await body(request)
    a = library.get(request.match_info["id"])
    if not a:
        raise KeyError("asset")
    fields = {}
    if "favorite" in d:
        fields["favorite"] = bool(d["favorite"])
    if "name" in d and str(d["name"]).strip():
        fields["name"] = str(d["name"]).strip()[:120]
    if "folder" in d:
        library.bulk([a["id"]], "move", d.get("folder") or "")
    return ok(asset_view(library.update(a["id"], **fields) if fields else library.get(a["id"])))


@routes.get("/api/folders")
async def folders_list(request):
    return ok(library.summary()["folders"])


@routes.post("/api/folders")
async def folders_add(request):
    return ok(library.add_folder((await body(request)).get("name")))


@routes.patch("/api/folders/{id}")
async def folders_rename(request):
    return ok(library.rename_folder(request.match_info["id"], (await body(request)).get("name")))


@routes.delete("/api/folders/{id}")
async def folders_delete(request):
    library.delete_folder(request.match_info["id"])
    return ok(deleted=True)


@routes.get("/api/library/{id}")
async def library_get(request):
    a = library.get(request.match_info["id"])
    if not a:
        raise KeyError("asset")
    return ok(asset_view(a))


@routes.post("/api/library/trash")
async def library_trash(request):
    d = await body(request)
    ids = d.get("ids") or []
    out = library.trash(ids)
    # a quick clip is its whole project: deleting it deletes that film
    for ident, why in list(out["kept"]):
        a = library.get(ident)
        if a and a.get("quick") and a.get("film"):
            if any(j.get("film") == a["film"] and j["status"] in ("queued", "running") for j in app_of(request).queue.jobs):
                continue
            if films.delete(a["film"]):
                out["kept"].remove((ident, why))
                out["moved"].append(ident)
    return ok(out)


@routes.post("/api/library/restore")
async def library_restore(request):
    d = await body(request)
    return ok(restored=library.restore(d.get("ids")))


@routes.post("/api/library/empty-trash")
async def library_empty(request):
    d = await body(request)
    if d.get("confirm") != "erase":
        raise ValueError('this erases the files in the trash for good; send {"confirm": "erase"}')
    return ok(library.empty_trash())


@routes.post("/api/library/import")
async def library_import(request):
    """Bring a file that is already under ComfyUI's output or input folder into the Library."""
    d = await body(request)
    name = (d.get("path") or "").strip()
    path = name if os.path.isabs(name) else os.path.join(config.OUTPUT_DIR, name)
    if not os.path.isfile(path):
        path = os.path.join(config.INPUT_DIR, name)
    if not os.path.isfile(path) or not (config.inside(path, config.OUTPUT_DIR) or config.inside(path, config.INPUT_DIR)):
        raise ValueError("give a file under ComfyUI's output or input folder")
    if not library.kind_of(path):
        raise ValueError("this is not a picture, a clip or a sound file")
    if not config.inside(path, config.OUTPUT_DIR):
        path = config.ref_path(work.copy_into_uploads(path))
    return ok(asset_view(library.add(path, name=d.get("name") or None, imported=True)))


@routes.post("/api/upload")
async def upload(request):
    """A picture, clip or sound from the browser. It is kept under output/studio/uploads (the big disk)."""
    reader = await request.multipart()
    out = []
    async for part in reader:
        if part.name != "file" or not part.filename:
            continue
        filename = os.path.basename(unquote(part.filename))
        ext = os.path.splitext(filename)[1].lower()
        if ext not in UPLOAD_EXT:
            raise ValueError(f"{filename}: only pictures, clips and sound files can be uploaded")
        base = config.slug(os.path.splitext(filename)[0], "upload", 40)
        dst = config.home("uploads", f"{base}_{uuid.uuid4().hex[:6]}{ext}")
        size = 0
        with open(dst, "wb") as f:
            while True:
                chunk = await part.read_chunk(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD:
                    f.close()
                    os.unlink(dst)
                    raise ValueError("the file is larger than 2 GB")
                f.write(chunk)
        out.append(asset_view(library.add(dst, name=filename, uploaded=True)))
    if not out:
        raise ValueError("no file was sent")
    return ok({"items": out})


@routes.post("/api/frame")
async def frame(request):
    """A frame of a clip as a picture in the Library: {asset, at: seconds | "last" | "first"}."""
    d = await body(request)
    a = library.get(d.get("asset") or "")
    if not a:
        raise KeyError("asset")
    src = library.abs_path(a)
    dst = config.home("images", f"{os.path.splitext(os.path.basename(src))[0]}_frame_{uuid.uuid4().hex[:6]}.png")
    at = d.get("at", "last")
    done = await asyncio.to_thread(checks.last_frame, src, dst) if at == "last" else \
        await asyncio.to_thread(checks.grab, src, dst, 0.0 if at == "first" else float(at))
    if not done:
        raise ValueError("the frame could not be read")
    return ok(asset_view(library.add(dst, "image", name=a["name"] + (" (last frame)" if at == "last" else " (frame)"), made_from=a["id"])))


# ============================================================================================ create: pictures and clips
@routes.post("/api/images")
async def images(request):
    d = await body(request)
    st = app_of(request)
    title = "Edit" if d.get("pictures") and not d.get("angles") else ("Angles" if d.get("angles") else "Picture")
    j = st.queue.add("image", d, title=f"{title} · {(d.get('name') or d.get('prompt') or '')[:48]}")
    return ok(job_view(j))


def quick_film(d):
    """A Create form as a one-shot film."""
    bible = {k: d[k] for k in ("style", "look", "lens", "light", "notext", "language", "width", "height", "frames", "turbo",
                               "unet", "one_take") if k in d and d[k] not in (None, "")}
    if d.get("loras"):
        bible["loras"] = d["loras"]
    name = (d.get("name") or d.get("action") or d.get("prompt") or "Clip").strip()[:48]
    film = films.create(name, quick=True, bible=bible)
    film["form"] = {k: v for k, v in d.items() if k not in ("looks",)}       # Recreate fills the composer from it
    if d.get("surface"):
        film["surface"] = str(d["surface"])[:20]
    cast_ids = []
    for p in d.get("people") or []:
        if not (p.get("name") or "").strip():
            continue
        c = {"id": uuid.uuid4().hex[:8], "name": p["name"].strip(), "description": p.get("description", ""),
             "pronoun": p.get("pronoun") or "their", "face": p.get("face", ""), "body": p.get("body", ""),
             "voice": p.get("voice", ""), "lora": p.get("lora") or {}}
        film["cast"].append(c)
        cast_ids.append(c["id"])
    by_name = {c["name"]: c["id"] for c in film["cast"]}
    lines = [{"speaker": by_name.get(ln.get("speaker"), ln.get("speaker", "")), "text": ln.get("text", ""), "how": ln.get("how", "")}
             for ln in d.get("lines") or [] if (ln.get("text") or "").strip()]
    staging = {by_name[k]: v for k, v in (d.get("staging") or {}).items() if k in by_name}
    sh = films.new_shot(film, title=name, new_shot=True, mode="free" if d.get("mode") == "free" else "fields",
                        place=d.get("place", ""), cast=cast_ids, staging=staging, framing=d.get("framing", ""),
                        camera=d.get("camera", ""), camera_text=d.get("camera_text", ""), action=d.get("action", ""),
                        lines=lines, sound=d.get("sound", ""), refs=d.get("refs") or [], first_frame=d.get("first_frame", ""),
                        last_frame=d.get("last_frame", ""), prompt=d.get("prompt", ""), frames=int(d.get("frames") or 0),
                        seed=int(d.get("seed") or 0), talking_head=bool(d.get("talking_head")),
                        blockout=d.get("blockout", ""), blockout_shapes=d.get("blockout_shapes", ""), blockout_start=int(d.get("blockout_start") or 0), blockout_strength=float(d.get("blockout_strength") or 0))
    cover = compose.blockout_cover(d.get("blockout", "")) if d.get("whole_blockout") and d.get("blockout") else None
    if cover:                                    # follow the whole blockout: parts that end on its cuts (compose.blockout_parts)
        parts = compose.blockout_parts(*cover)
        sh["frames"], sh["blockout_start"] = parts[0]["frames"], parts[0]["start"]
        add_blockout_parts(film, sh, parts[1:])
    for beat in ([] if cover else d.get("beats") or []):
        if (beat or "").strip():
            # a long take on a blockout reads on in it: each part starts where the one before stopped (minus the context)
            films.new_shot(film, title=beat.strip()[:48], new_shot=False, mode="fields", cast=cast_ids, action=beat.strip(),
                           sound=d.get("sound", ""), frames=int(d.get("frames") or 0), blockout=d.get("blockout", ""),
                           blockout_strength=float(d.get("blockout_strength") or 0))
    films.save(film)
    return film, sh


def add_blockout_parts(film, base, parts):
    """Shots after `base` that go on following its blockout: the same place, people, action and look; the spoken lines
    stay in the first part."""
    keep = {k: base.get(k) for k in films.USER_SHOT_FIELDS
            if k not in ("title", "new_shot", "lines", "frames", "blockout_start", "first_frame", "last_frame", "seed", "notes")}
    title = (base.get("title") or "Clip")[:40]
    n0 = len(film["shots"])
    for i, p in enumerate(parts):
        films.new_shot(film, **keep, title=f"{title} · part {n0 + i + 1}", new_shot=p["new_shot"], frames=p["frames"],
                       blockout_start=p["start"] if p["new_shot"] else 0)


PARTS_SYSTEM = """A video is made in parts that each follow one stretch of a rough 3D blockout (grey shapes in Blender
that set the camera, positions and timing). The person described the whole video in a few words. Write, for each part,
what happens in that part only: 1 to 3 plain sentences in the present tense, about what is seen in that stretch of the
blockout (who stands, drives, turns, stops, where to), in the order it happens, and nothing that happens before or after
it. Work out from the camera keys and the things' keys where the camera is: say for each car or person in view
whether it comes toward the camera (its front and headlights seen) or drives away from it (its back and tail lights seen),
and which side of the picture it is on; the grey shapes look alike front and back, so the video model needs these words.
Use the person's words for what things really are and for the place. No camera moves (the blockout has the
camera), no spoken words, no titles. Invented people only; no real brands, films, shows or games. Answer with the JSON
object only: {"parts": [{"action": ...}, ...]}, one per part, in order."""
PARTS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["parts"],
                "properties": {"parts": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                     "required": ["action"], "properties": {"action": {"type": "string"}}}}}}


async def part_actions(action, place, ref, parts):
    """What happens in each part of a clip that follows a blockout in parts, written by Claude Code from the person's
    words and the blockout's scene (only text is sent). One description of the whole video in every part made the model
    squeeze the whole story into each part (2026-11-15). None when Claude is not there or fails: then each part keeps the
    person's words."""
    sc = compose.rendered_scene(ref)
    if not sc or not writer.state()["ok"]:
        return None
    small = {"things": [{"name": t["name"], "kind": t["kind"], "color": t.get("color", ""),
                         "keys": [{"t": k["t"], "at": k["at"], "pose": k["pose"]} for k in t.get("keys") or []]} for t in sc.get("things") or []],
             "set": [{"type": i["type"], "name": i.get("name", "")} for i in sc.get("set") or []],
             "camera": [{"t": k["t"], "follows": k.get("follow", ""), "at": k["at"], "cut": k.get("cut", False)} for k in (sc.get("camera") or {}).get("keys") or []]}
    stretch = [f"part {i + 1}: {p['start'] / 24:.1f} to {(p['start'] + p['frames']) / 24:.1f} s" for i, p in enumerate(parts)]
    text = (f"The person's words: {action}\nThe place: {place}\n\nThe parts:\n" + "\n".join(stretch)
            + "\n\nThe blockout scene (metres, seconds; keys say where each thing is at which second):\n" + json.dumps(small)[:50000])
    try:
        answer, _ = await writer.run_claude(PARTS_SYSTEM, PARTS_SCHEMA, text, timeout=600)
    except Exception as e:                           # Claude is optional here: the parts keep the person's words
        print("part actions: Claude failed:", e)
        return None
    got = [(x.get("action") or "").strip() for x in (answer or {}).get("parts") or []]
    return got if len(got) == len(parts) and all(got) else None


async def write_part_actions(fid, first):
    """Give the shots of clip fid from index `first` on their own actions (see part_actions)."""
    film = films.load(fid)
    shots = film["shots"]
    base = shots[0]
    parts = []
    for i in range(len(shots)):
        pl = compose.blockout_plan(film, i)
        parts.append({"start": pl["start"], "frames": int(shots[i].get("frames") or 0)})
    acts = await part_actions(base.get("action", ""), base.get("place", ""), base.get("blockout", ""), parts)
    if not acts:
        return False
    with films.LOCK:
        film = films.load(fid)
        for i in range(first, len(film["shots"])):
            sh = film["shots"][i]
            if not sh.get("takes"):
                sh["notes"] = ((sh.get("notes") or "") + "\nThe whole video: " + base.get("action", "")).strip()
                sh["action"] = acts[i]
        films.save(film)
    return True


@routes.get("/api/blockout_parts")
async def blockout_parts_route(request):
    """?ref=<a blockout video>: how a clip that follows all of it is split ({total, cuts, parts}), or {} when the video
    is not from the Blockout room."""
    cover = compose.blockout_cover(request.query.get("ref", ""))
    if not cover:
        return ok({})
    return ok({"total": cover[0], "cuts": cover[1], "parts": compose.blockout_parts(*cover)})


@routes.post("/api/clips/{film}/cover_blockout")
async def clip_cover_blockout(request):
    """Add the parts a clip needs to follow the rest of its blockout, then render them in order."""
    with films.LOCK:
        film = films.load(request.match_info["film"])
        if not film:
            raise KeyError("clip")
        last = film["shots"][-1]
        cover = compose.blockout_cover(last.get("blockout") or "")
        if not cover:
            raise ValueError("this clip does not follow a blockout from the Blockout room")
        plan = compose.blockout_plan(film, len(film["shots"]) - 1)
        end = plan["start"] + int(last.get("frames") or 0)
        parts = compose.blockout_parts(*cover, pos=end, cont=True)
        if not parts:
            raise ValueError("the clip already covers its whole blockout")
        first_new = len(film["shots"])
        add_blockout_parts(film, last, parts)
        films.save(film)
    await write_part_actions(film["id"], first_new)
    await app_of(request).production.start(film["id"], mode="auto", retries=0)
    return ok({"film": film["id"], "added": len(parts), "shots": len(film["shots"])})


@routes.post("/api/clips")
async def clips(request):
    """Create > Video: one clip (a quick film with one shot), or a long take when "beats" are given."""
    d = await body(request)
    st = app_of(request)
    film, sh = quick_film(d)
    if len(film["shots"]) > 1:
        if d.get("whole_blockout"):                  # each part its own stretch of the story (before anything renders)
            await write_part_actions(film["id"], 0)
        await st.production.start(film["id"], mode="auto", retries=0)
        return ok({"film": film["id"], "shots": len(film["shots"])})
    j = st.production.queue_shot(film, sh, force=True)
    return ok({"film": film["id"], "job": job_view(j)})


@routes.post("/api/clips/variants")
async def clip_variants(request):
    """The same clip in several looks, each a clip of its own."""
    d = await body(request)
    st = app_of(request)
    out = []
    seed = int(d.get("seed") or 0) or work.new_seed()
    for look in (d.get("looks") or [])[:8]:
        film, sh = quick_film({**d, "look": look, "style": "", "seed": seed, "name": f"{(d.get('name') or d.get('action') or 'Clip')[:36]} · {look}", "beats": []})
        out.append({"film": film["id"], "look": look, "job": job_view(st.production.queue_shot(film, sh, force=True))})
    if not out:
        raise ValueError("pick at least one look")
    return ok({"clips": out, "seed": seed})


@routes.post("/api/clips/{film}/extend")
async def clip_extend(request):
    """Carry a clip on: a new part that continues its last frames and sound in latent space."""
    d = await body(request)
    st = app_of(request)
    with films.LOCK:
        film = films.load(request.match_info["film"])
        if not film:
            raise KeyError("film")
        if not film["shots"] or not film["shots"][-1].get("part"):
            raise ValueError("the clip has no rendered part to continue")
        last = film["shots"][-1]
        sh = films.new_shot(film, title=(d.get("action") or "continues")[:48], new_shot=False, mode="fields",
                            cast=last.get("cast", []), action=d.get("action") or "The shot continues.",
                            lines=d.get("lines") or [], sound=d.get("sound") or last.get("sound", ""),
                            frames=int(d.get("frames") or 0))
        films.save(film)
    j = st.production.queue_shot(film, sh, force=True)
    return ok({"film": film["id"], "job": job_view(j)})


async def blockout_notes(c, info):
    """Add to a composed shot that follows a blockout: the frames it reads, how many the video has, and warnings
    when the video is too short or this ComfyUI cannot follow a blockout."""
    blk = c["blockout"]
    c["blockout"] = {**blk, "end": blk["start"] + c["frames"]}
    path = config.ref_path(blk["file"])
    have = await asyncio.to_thread(work.video_frames, path) if os.path.isfile(path) else 0
    c["blockout"]["frames"] = have
    if have and have < c["blockout"]["end"]:
        c["findings"].insert(0, {"level": "warn", "code": "blockout-short", "quote": "",
                                 "text": f"the blockout has {have} frames ({have / 24:.1f} s); this shot reads frames "
                                         f"{blk['start']}–{c['blockout']['end'] - 1}. Make it longer, start earlier in it, or shorten the shot."})
    if info is not None:
        f = models.features(info)["blockout"]
        if not f["ok"]:
            c["findings"].insert(0, {"level": "warn", "code": "blockout-missing", "quote": "",
                                     "text": f"{f['title']} cannot run here: {models.why_not(f)}"})


@routes.post("/api/compose")
async def compose_preview(request):
    """The prompt a Create form would send, without making anything: {form} as for /api/clips."""
    d = await body(request)
    bible = {k: d[k] for k in ("style", "look", "lens", "light", "notext", "language", "width", "height", "frames", "turbo",
                               "one_take") if k in d and d[k] not in (None, "")}
    cast = [{"id": p.get("name", ""), "name": p.get("name", ""), "description": p.get("description", ""),
             "pronoun": p.get("pronoun") or "their", "face": p.get("face", ""), "body": p.get("body", ""), "voice": p.get("voice", ""),
             "lora": p.get("lora") or {}} for p in d.get("people") or [] if (p.get("name") or "").strip()]
    shot = {**compose.blank_shot(), **{k: d.get(k) for k in ("place", "framing", "camera", "camera_text", "action", "sound", "refs",
                                                             "first_frame", "last_frame", "prompt", "talking_head", "blockout",
                                                             "blockout_shapes", "blockout_start", "blockout_strength") if d.get(k) is not None},
            "mode": "free" if d.get("mode") == "free" else "fields", "cast": [c["id"] for c in cast],
            "lines": d.get("lines") or [], "staging": d.get("staging") or {}, "frames": int(d.get("frames") or 0),
            "new_shot": not d.get("continuation")}
    st = app_of(request)
    info = await st.comfy.object_info() if await st.comfy.up() else None
    c = compose.compose({"bible": bible, "cast": cast, "locations": [], "props": []}, shot, 1 if d.get("continuation") else 0, info)
    c["fit"] = machine.fit(c["width"], c["height"], c["frames"])
    v = config.settings()["video"]
    steps = int(v["turbo_steps"] if c["turbo"] else v["steps"])
    c["estimate"] = st.queue.estimate("part", work.clip_units(c, steps), prior=work.CLIP_PRIOR)
    if c.get("blockout"):
        await blockout_notes(c, info)
    return ok(c)


# ============================================================================================ films
def film_view(film):
    out = dict(film)
    out["full"] = os.path.relpath(films.full_path(film), config.OUTPUT_DIR).replace(os.sep, "/") if os.path.isfile(films.full_path(film)) else ""
    up = films.full_path(film, upscaled=True)
    out["full_upscaled"] = os.path.relpath(up, config.OUTPUT_DIR).replace(os.sep, "/") if os.path.isfile(up) else ""
    out["steps"] = films.steps(film)
    out["blockouts"] = [{**b, "state": blockouts.state_of(film, b), "stretches": blockouts.cuts(film, b)} for b in blockouts.all_of(film)]
    return out


@routes.get("/api/films")
async def films_list(request):
    return ok(films.summaries(quick=request.query.get("quick") == "1"))


@routes.post("/api/films")
async def films_create(request):
    d = await body(request)
    return ok(film_view(films.create((d.get("name") or "Untitled").strip()[:80], bible=d.get("bible"))))


@routes.get("/api/projects")
async def projects(request):
    """Long-video projects on disk that no film of the studio owns (made with the story kit or the workflows)."""
    return ok(await asyncio.to_thread(films.projects_on_disk))


def this_computer(request):
    """A story file is a program, and reading it runs it: only for a request that comes from this computer itself."""
    if (request.remote or "") not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        raise ValueError("a story file is run to be read; the studio does that only for the browser on its own computer")


@routes.post("/api/films/adopt")
async def films_adopt(request):
    """Open such a project as a film: {project, name, story}. Its folder stays where it is. `story` is the path of the
    story-kit file it was made from: its prompts, lines, cast, places and props come along."""
    d = await body(request)
    story = (d.get("story") or "").strip()
    if story:
        this_computer(request)
    return ok(film_view(await asyncio.to_thread(films.adopt, d.get("project") or "", (d.get("name") or "").strip()[:80], story)))


@routes.post("/api/films/{id}/story")
async def film_story_in(request):
    """Read the story-kit file a brought-in film was made from: {path}. Answers {film, report}."""
    this_computer(request)
    path = ((await body(request)).get("path") or "").strip()
    if not path:
        raise ValueError("give the path of the story file")
    film, report = await asyncio.to_thread(films.apply_story, request.match_info["id"], path)
    return ok({"film": film_view(film), "report": report})


@routes.get("/api/films/{id}")
async def films_get(request):
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    return ok(film_view(film))


@routes.put("/api/films/{id}")
async def films_put(request):
    film, report = await asyncio.to_thread(films.apply_edit, request.match_info["id"], await body(request))
    return ok({"film": film_view(film), "report": report})


@routes.delete("/api/films/{id}")
async def films_delete(request):
    st = app_of(request)
    fid = request.match_info["id"]
    if any(j.get("film") == fid and j["status"] in ("queued", "running") for j in st.queue.jobs):
        raise ValueError("this film has renders in the queue; cancel them first")
    if not films.delete(fid):
        raise KeyError("film")
    return ok(deleted=True)


def _film_shot(request):
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    sh = films.get_shot(film, request.match_info["sid"])
    if not sh:
        raise KeyError("shot")
    return film, sh


@routes.post("/api/films/{id}/compose/{sid}")
async def films_compose(request):
    """The preflight of a shot: its prompt, its pictures and voices, what the checks say, whether it can render now."""
    st = app_of(request)
    film, sh = _film_shot(request)
    info = await st.comfy.object_info() if await st.comfy.up() else None
    idx = films.shot_index(film, sh["id"])
    c = compose.compose(film, sh, idx, info)
    can, why = films.eligible(film, sh["id"])
    c.update(eligible=can, why=why, fit=machine.fit(c["width"], c["height"], c["frames"]), part=idx + 1,
             scene=blockouts.state(film, idx))
    v = config.settings()["video"]
    c["estimate"] = st.queue.estimate("part", work.clip_units(c, int(v["turbo_steps"] if c["turbo"] else v["steps"])), prior=work.CLIP_PRIOR)
    if c["continuation"] and idx > 0:
        t = films.active_take(film["shots"][idx - 1])
        c["previous_sheet"] = (t or {}).get("sheet", "")
    blk = c.get("blockout")
    if blk:
        await blockout_notes(c, info)
    missing = [n for n in c["refs"] + c["voices"] + [x for x in (c["first_frame"], c["last_frame"], (blk or {}).get("file")) if x]
               if not os.path.isfile(config.ref_path(n))]
    if missing:
        c["findings"].insert(0, {"level": "warn", "code": "missing-file", "quote": "", "text": "missing file(s): " + ", ".join(missing)})
    return ok(c)


@routes.post("/api/films/{id}/preview/{sid}")
async def films_preview(request):
    """A very small render of this shot ({seed}), or with {take: true} of its take up to and including it, in order:
    a continuation's preview continues the preview of the shot before. Nothing in the film itself changes."""
    st = app_of(request)
    d = await body(request)
    film, sh = _film_shot(request)
    idx = films.shot_index(film, sh["id"])
    take = compose.take_of(film, idx)
    todo = take[:take.index(idx) + 1] if d.get("take") else [idx]
    out = []
    for i in todo:
        s = film["shots"][i]
        out.append(job_view(st.queue.add("preview", {"film": film["id"], "shot": s["id"], "seed": int(d.get("seed") or 0) if i == idx else 0},
                                         title=f"{film['name']} · {s.get('title') or 'shot ' + str(i + 1)} (preview)",
                                         film=film["id"], shot=s["id"])))
    return ok({"jobs": out})


def queue_blockout(st, film, b):
    bs = blockouts.state_of(film, b)
    if bs["error"]:
        raise ValueError(f"the blockout of scene {b.get('scene_name') or '(no name)'}: " + bs["error"])
    return st.queue.add("blockout", {"film": film["id"], "blockout": b["id"]},
                        title=f"{film['name']} · blockout of scene {b.get('scene_name') or '(no name)'}", film=film["id"])


@routes.post("/api/films/{id}/blockouts/{bid}/make")
async def films_blockout_make(request):
    """Render a scene's blockout in Blender (cpu lane); the scene's shots then follow their stretches of it."""
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    b = blockouts.find(film, request.match_info["bid"])
    if not b:
        raise KeyError("blockout")
    return ok(job_view(queue_blockout(app_of(request), film, b)))


@routes.post("/api/films/{id}/blockout/{sid}")
async def films_blockout(request):
    """Make the blockout of the scene this shot is in (the same as /blockouts/{bid}/make)."""
    film, sh = _film_shot(request)
    b = blockouts.of_shot(film, films.shot_index(film, sh["id"]))
    if not b:
        raise ValueError("this shot's scene has no blockout")
    return ok(job_view(queue_blockout(app_of(request), film, b)))


@routes.post("/api/blockout/check")
async def blockout_check(request):
    """{scene}: the scene as the renderer takes it, or {error}. Also says whether Blender is here."""
    d = await body(request)
    try:
        scene = blockouts.normalize(d.get("scene"))
        return ok({"scene": scene, "blender": bool(blockouts.blender())})
    except blockouts.BadScene as e:
        return ok({"error": str(e), "blender": bool(blockouts.blender())})


@routes.post("/api/films/{id}/render/{sid}")
async def films_render(request):
    st = app_of(request)
    d = await body(request)
    film, sh = _film_shot(request)
    j = await st.production.reroll(film["id"], sh["id"], seed=int(d.get("seed") or 0), force=bool(d.get("force")))
    return ok(job_view(j))


@routes.post("/api/films/{id}/approve/{sid}")
async def films_approve(request):
    st = app_of(request)
    film, sh = _film_shot(request)
    return ok(film_view(await st.production.approve(film["id"], sh["id"])))


@routes.post("/api/films/{id}/take/{sid}")
async def films_take(request):
    d = await body(request)

    def put_back():
        with films.LOCK:
            film, sh = _film_shot(request)
            report = films.restore_take(film, sh["id"], int(d.get("n") or 0))
            films.save(film)
            return film, report
    film, report = await asyncio.to_thread(put_back)
    return ok({"film": film_view(film), "report": report})


@routes.post("/api/films/{id}/run")
async def films_run(request):
    st = app_of(request)
    d = await body(request)
    mode = d.get("mode")
    if mode not in (None, "hold", "auto", "keep_going"):
        raise ValueError("mode is hold, auto or keep_going")
    run = await st.production.start(request.match_info["id"], mode=mode, retries=d.get("retries"), upscale=bool(d.get("upscale")))
    return ok(run)


@routes.post("/api/films/{id}/stop")
async def films_stop(request):
    await app_of(request).production.stop(request.match_info["id"])
    return ok(stopped=True)


@routes.post("/api/films/{id}/storyboard")
async def films_storyboard(request):
    """A still for every shot (or the ones named) from the film's own pictures: cheap, and looked at before any clip."""
    st = app_of(request)
    d = await body(request)
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    b = film["bible"]
    w, h = lengths.snap32(b["width"] * 1.25), lengths.snap32(b["height"] * 1.25)
    out = []
    for i, sh in enumerate(film["shots"]):
        if d.get("shots") and sh["id"] not in d["shots"]:
            continue
        prompt, refs = compose.still_prompt(film, sh, i)
        j = st.queue.add("image", {"prompt": prompt, "pictures": refs, "width": w, "height": h, "takes": int(d.get("takes") or 1),
                                   "film": film["id"], "shot": sh["id"], "name": f"storyboard {i + 1}"},
                         title=f"{film['name']} · storyboard {i + 1}", film=film["id"], shot=sh["id"])
        out.append(job_view(j))
    return ok({"jobs": out})


@routes.post("/api/films/{id}/storyboard/{sid}/remove")
async def films_storyboard_remove(request):
    d = await body(request)
    with films.LOCK:
        film, sh = _film_shot(request)
        sh["storyboard"] = [s for s in sh.get("storyboard", []) if s.get("asset") != d.get("asset")]
        films.save(film)
    return ok(film_view(film))


@routes.post("/api/films/{id}/upscale")
async def films_upscale(request):
    st = app_of(request)
    d = await body(request)
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    j = st.queue.add("upscale", {"film": film["id"], "first": d.get("first"), "last": d.get("last"), "force": bool(d.get("force"))},
                     title=f"{film['name']} · upscale", film=film["id"])
    return ok(job_view(j))


@routes.post("/api/films/{id}/outline")
async def films_outline(request):
    """Add shots to a film: from a coverage plan ({plan, a, b, place}), or from a logline with the brain
    ({logline, scenes, shots})."""
    d = await body(request)
    fid = request.match_info["id"]
    film = films.load(fid)
    if not film:
        raise KeyError("film")
    added = {"shots": 0, "cast": 0, "locations": 0}
    if d.get("plan"):
        names = {c["id"]: c["name"] for c in film["cast"]}
        a, b = names.get(d.get("a"), d.get("a") or ""), names.get(d.get("b"), d.get("b") or "")
        loc = next((l for l in film["locations"] if l["id"] == d.get("place")), None)
        rows = brain.from_plan(d["plan"], a, b, loc["name"] if loc else (d.get("place") or ""))
        with films.LOCK:
            film = films.load(fid)
            ids = {c["name"]: c["id"] for c in film["cast"]}
            for r in rows:
                films.new_shot(film, title=r["title"], new_shot=r["new_shot"], framing=r["framing"], camera=r["camera"],
                               action=r["action"], location=loc["id"] if loc else "", frames=r["frames"],
                               cast=[ids[n] for n in r["cast_names"] if n in ids],
                               lines=[{**ln, "speaker": ids.get(ln["speaker"], ln["speaker"])} for ln in r["lines"]])
                added["shots"] += 1
            films.save(film)
    else:
        got = await brain.outline(d.get("logline") or film["bible"].get("logline", ""), int(d.get("scenes") or 2),
                                  int(d.get("shots") or 3), [c["name"] for c in film["cast"]], film["bible"]["frames"] / lengths.FPS)
        with films.LOCK:
            film = films.load(fid)
            ids = {c["name"]: c["id"] for c in film["cast"]}
            for c in got["cast"]:
                if c["name"] not in ids:
                    c["id"] = uuid.uuid4().hex[:8]
                    film["cast"].append({**c, "face": "", "body": "", "voice": "", "lora": {}})
                    ids[c["name"]] = c["id"]
                    added["cast"] += 1
            locs = {l["name"]: l["id"] for l in film["locations"]}
            for l in got["locations"]:
                if l["name"] not in locs:
                    l["id"] = uuid.uuid4().hex[:8]
                    film["locations"].append({**l, "plate": ""})
                    locs[l["name"]] = l["id"]
                    added["locations"] += 1
            for s in got["shots"]:
                films.new_shot(film, title=s["title"], scene=s["scene"], new_shot=s["new_shot"], place="" if s["location"] in locs else s["place"],
                               location=locs.get(s["location"], ""), cast=[ids[n] for n in s["cast"] if n in ids],
                               framing=s["framing"], camera=s["camera"], action=s["action"], sound=s["sound"],
                               lines=[{**ln, "speaker": ids.get(ln["speaker"], ln["speaker"])} for ln in s["lines"]])
                added["shots"] += 1
            if d.get("logline"):
                film["bible"]["logline"] = d["logline"]
            films.save(film)
    return ok({"film": film_view(film), "added": added})


@routes.get("/api/films/{id}/story")
async def films_story(request):
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    return web.Response(text=films.to_story(film), content_type="text/plain", charset="utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{film["id"]}.py"'})


@routes.post("/api/films/{id}/timeline")
async def films_timeline(request):
    d = await body(request)
    film = films.load(request.match_info["id"])
    if not film:
        raise KeyError("film")
    tl = await asyncio.to_thread(finish.from_film, film, bool(d.get("upscaled")))
    if not tl["clips"]:
        raise ValueError("this film has no rendered shots yet")
    return ok(finish.save(tl))


# ---------------------------------------------------------------- the cast library: characters kept across films
def _cast_file():
    return config.home("cast", "cast.json")


@routes.get("/api/cast")
async def cast_get(request):
    return ok(config.read_json(_cast_file(), []) or [])


@routes.put("/api/cast")
async def cast_put(request):
    d = await body(request)
    items = d.get("cast")
    if not isinstance(items, list):
        raise ValueError('send {"cast": [...]}')
    for c in items:
        c.setdefault("id", uuid.uuid4().hex[:8])
    config.write_json(_cast_file(), items)
    return ok(items)


# ============================================================================================ timelines, beats, sound
@routes.get("/api/timelines")
async def timelines(request):
    return ok(finish.all_timelines())


@routes.post("/api/timelines")
async def timelines_new(request):
    d = await body(request)
    return ok(finish.save(finish.blank((d.get("name") or "Timeline").strip()[:60])))


@routes.get("/api/timelines/{id}")
async def timeline_get(request):
    tl = finish.load(request.match_info["id"])
    if not tl:
        raise KeyError("timeline")
    return ok(tl)


@routes.put("/api/timelines/{id}")
async def timeline_put(request):
    tl = finish.load(request.match_info["id"])
    if not tl:
        raise KeyError("timeline")
    d = await body(request)
    for k in ("name", "clips", "music", "title", "captions", "width", "height", "fps", "loudness", "match"):
        if k in d:
            tl[k] = d[k]
    return ok(finish.save(tl))


@routes.delete("/api/timelines/{id}")
async def timeline_delete(request):
    p = finish.tl_path(request.match_info["id"])
    if not finish.load(request.match_info["id"]):
        raise KeyError("timeline")
    shutil.move(p, config.home("trash", f"timeline_{request.match_info['id']}_{int(time.time())}.json"))
    return ok(deleted=True)


@routes.post("/api/timelines/{id}/clips")
async def timeline_add(request):
    tl = finish.load(request.match_info["id"])
    if not tl:
        raise KeyError("timeline")
    d = await body(request)
    for ident in d.get("assets") or ([d["asset"]] if d.get("asset") else []):
        await asyncio.to_thread(finish.add_clip, tl, None, ident)
    return ok(finish.save(tl))


@routes.post("/api/timelines/{id}/export")
async def timeline_export(request):
    tl = finish.load(request.match_info["id"])
    if not tl:
        raise KeyError("timeline")
    d = await body(request)
    kind = "resolve" if d.get("resolve") else "export"
    j = app_of(request).queue.add(kind, {"timeline": tl["id"], "language": d.get("language")},
                                  title=f"{tl['name']} · " + ("ProRes for Resolve" if kind == "resolve" else "export"))
    return ok(job_view(j))


def _sound_path(d):
    a = library.get(d.get("asset") or "")
    path = library.abs_path(a) if a else os.path.join(config.OUTPUT_DIR, d.get("path") or "")
    if not os.path.isfile(path) or not config.inside(path, config.OUTPUT_DIR):
        raise ValueError("give a sound file from the Library")
    return path


@routes.post("/api/beats")
async def beats_route(request):
    d = await body(request)
    return ok(await asyncio.to_thread(beats.beats, _sound_path(d), bool(d.get("refresh"))))


@routes.post("/api/roughcut")
async def roughcut(request):
    """Clips cut on a song's beats, as a new timeline: {film | assets, song (asset), mode, order, name}."""
    d = await body(request)
    song = _sound_path({"asset": d.get("song"), "path": d.get("song_path")})
    if d.get("film"):
        film = films.load(d["film"])
        if not film:
            raise KeyError("film")
        paths = [films.part_files(film, s["part"])["segment"] for s in film["shots"] if s.get("part")]
    else:
        paths = [library.abs_path(a) for a in (library.get(i) for i in d.get("assets") or []) if a]
    tl = await asyncio.to_thread(finish.rough_cut, paths, song, d.get("mode") or "own", d.get("order") or "as_filmed",
                                 d.get("name") or "Rough cut")
    return ok(finish.save(tl))


@routes.get("/api/voices")
async def voices(request):
    st = app_of(request)
    tts = models.voices(await st.comfy.object_info()) if await st.comfy.up() else []
    return ok({"tts": tts, "samples": [asset_view(a) for a in library.search(kind="audio")]})


@routes.post("/api/tts")
async def tts(request):
    d = await body(request)
    j = app_of(request).queue.add("tts", d, title=f"Voice · {(d.get('text') or '')[:40]}")
    return ok(job_view(j))


# ============================================================================================ night shift, brain, docs
@routes.get("/api/nightshift")
async def shifts(request):
    return ok(app_of(request).nightshift.all())


@routes.post("/api/nightshift")
async def shift_plan(request):
    d = await body(request)
    return ok(app_of(request).nightshift.plan(d.get("film"), d.get("start") or "idle", int(d.get("retries", 1)),
                                              bool(d.get("upscale")), d.get("name") or ""))


@routes.post("/api/nightshift/{id}/{action}")
async def shift_action(request):
    ns = app_of(request).nightshift
    sid, action = request.match_info["id"], request.match_info["action"]
    if action == "start":
        return ok(await ns.start_now(sid))
    if action == "cancel":
        s = ns.get(sid)
        if s and s["status"] == "running":
            await app_of(request).production.stop(s["film"], "the night shift was stopped")
            s["status"] = "cancelled"
            config.write_json(ns._file(sid), s)
            return ok(s)
        return ok(ns.cancel(sid))
    raise ValueError("action is start or cancel")


@routes.post("/api/dailies")
async def dailies(request):
    d = await body(request)
    j = app_of(request).queue.add("dailies", {"film": d.get("film"), "since": d.get("since") or 0}, title="Dailies reel")
    return ok(job_view(j))


# ============================================================================================ the Writer
@routes.get("/api/writer")
async def writer_list(request):
    return ok({"state": writer.state(), "conversations": await asyncio.to_thread(writer.all_conversations)})


@routes.post("/api/writer")
async def writer_new(request):
    """A new conversation: {film} to talk about an existing film, or nothing for a new one."""
    this_computer(request)
    return ok(writer.new_conversation((await body(request)).get("film") or ""))


@routes.get("/api/writer/{cid}")
async def writer_get(request):
    return ok(writer.load(request.match_info["cid"]))


@routes.post("/api/writer/{cid}/say")
async def writer_say(request):
    """{text}: the user's turn. Waits for Claude's answer (seconds to minutes) and returns the conversation."""
    this_computer(request)
    return ok(await writer.turn(request.match_info["cid"], (await body(request)).get("text") or ""))


@routes.post("/api/writer/{cid}/apply")
async def writer_apply(request):
    """{turn}: apply that answer's proposal. Returns {film, report, conversation}."""
    this_computer(request)
    cid = request.match_info["cid"]
    film, report = await asyncio.to_thread(writer.apply, cid, int((await body(request)).get("turn", -1)))
    st = app_of(request)
    for bid in report.get("blockouts") or []:          # the Writer's blockouts go to Blender straight away
        b = blockouts.find(film, bid)
        if b:
            queue_blockout(st, film, b)
    return ok({"film": film_view(film), "report": report, "conversation": writer.load(cid)})


@routes.delete("/api/writer/{cid}")
async def writer_delete(request):
    path = writer._path(request.match_info["cid"])
    if os.path.isfile(path):
        dst = config.home("trash", "writer", os.path.basename(path))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(path, dst)
    return ok({})


@routes.get("/api/brain")
async def brain_state(request):
    return ok(brain.state())


@routes.post("/api/brain/rewrite")
async def brain_rewrite(request):
    d = await body(request)
    text = await brain.ask(brain.RULES.replace("Answer with JSON only.", "Answer with the rewritten text only."),
                           f"Rewrite this for the video model. {d.get('instruction') or 'Make it clearer and shorter, in positive words.'}\n\n{d.get('text', '')}")
    return ok(text=text.strip())


DOCS = {"guide": "docs/guide.md", "prompting": "docs/prompting.md", "tutorial": "docs/tutorial.md", "api": "docs/api.md", "long-video": "docs/long-video.md",
        "readme": "README.md"}


# ============================================================================================ estimates
@routes.post("/api/estimate")
async def estimate(request):
    """{kind: "image", takes}: about how many seconds a job takes on this machine (None when nothing is known yet)."""
    d = await body(request)
    st = app_of(request)
    if d.get("kind") == "image":
        n = max(1, min(int(d.get("takes") or 1), 12))
        return ok(seconds=st.queue.estimate("image", n, prior=(4.0, 22.0)))
    raise ValueError("kind is image (a clip's estimate comes with /api/compose)")


# ============================================================================================ blockout room
@routes.get("/api/blockouts")
async def blockout_list(request):
    return ok({"items": blockout_scenes.all_of(), "blender": bool(blockouts.blender()), "sizes": list(blockout_scenes.SIZES)})


@routes.post("/api/blockouts")
async def blockout_new(request):
    d = await body(request)
    return ok(blockout_scenes.view(blockout_scenes.create(d.get("name") or "", d.get("scene"), d.get("idea") or "", d.get("size") or "")))


@routes.get("/api/blockouts/{id}")
async def blockout_get(request):
    b = blockout_scenes.load(request.match_info["id"])
    making = [j for j in app_of(request).queue.jobs if j.get("kind") == "blockout_free" and j["params"].get("blockout") == b["id"]
              and j["status"] in ("queued", "running")]
    return ok({**blockout_scenes.view(b), "job": job_view(making[-1]) if making else None, "write": running_write(b["id"])})


@routes.put("/api/blockouts/{id}")
async def blockout_put(request):
    d = await body(request)
    why = d.get("why") if d.get("why") in ("words",) else ""                  # Claude changed it: keep the scene before
    return ok(blockout_scenes.view(blockout_scenes.save(request.match_info["id"], d, why=why)))


@routes.delete("/api/blockouts/{id}")
async def blockout_delete(request):
    blockout_scenes.delete(request.match_info["id"])
    return ok({"deleted": True})


def running_write(bid):
    """The change in words running for this blockout, if any (the page shows its progress after a reload)."""
    k = next((k for k, t in WRITES.items() if t.get("blockout") == bid and not t["done"]), None)
    return _write_view(k) if k else None


@routes.get("/api/blockouts/{id}/versions")
async def blockout_versions(request):
    return ok(blockout_scenes.versions(request.match_info["id"]))


@routes.post("/api/blockouts/{id}/versions/{v}")
async def blockout_restore(request):
    """Go back to an earlier version; the scene it replaces is kept as a version too."""
    bid = request.match_info["id"]
    scene = blockout_scenes.version(bid, request.match_info["v"])
    return ok(blockout_scenes.view(blockout_scenes.save(bid, {"scene": scene}, why="restore")))


@routes.post("/api/blockouts/{id}/make")
async def blockout_make(request):
    """Render it in Blender (cpu lane). The video lands in the Library (surface "blockout")."""
    st = app_of(request)
    b = blockout_scenes.load(request.match_info["id"])
    stt = blockout_scenes.state(b)
    if stt["error"]:
        raise ValueError("the scene: " + stt["error"])
    if not stt["blender"]:
        raise ValueError("Blender was not found on this computer: set its path in Machine → Settings (blender)")
    j = st.queue.add("blockout_free", {"blockout": b["id"]}, title=f"Blockout · {b['name']} ({stt['seconds']} s)")
    return ok(job_view(j))


def blender_here(request):
    """Blender opens on the studio's own screen, and only Blender on it may send scenes back."""
    if (request.remote or "") not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        raise ValueError("Blender opens on the studio's own computer: use this from the browser there")


@routes.post("/api/blockouts/{id}/blender")
async def blockout_blender(request):
    """Open the blockout in Blender's own window (blender/blockout_edit.py). What is changed there comes back through
    /from_blender when the person presses "Send to H3 Studio" or saves."""
    blender_here(request)
    b = blockout_scenes.load(request.match_info["id"])
    stt = blockout_scenes.state(b)
    if stt["error"]:
        raise ValueError("fix the scene first: " + stt["error"])
    exe = blockouts.blender()
    if not exe:
        raise ValueError("Blender was not found on this computer: set its path in Machine → Settings (blender)")
    scene = blockouts.normalize(b["scene"])
    w, hgt = blockout_scenes.size_of(b)
    spec = config.home("blockout_scenes", b["id"] + "_edit.json")
    config.write_json(spec, scene)
    blend = config.home("blockout_scenes", b["id"] + ".blend")
    log = open(config.home("blockout_scenes", b["id"] + "_blender.log"), "w")
    script = os.path.join(os.path.dirname(blockouts.SCRIPT), "blockout_edit.py")
    subprocess.Popen([exe, "-P", script, "--", spec, str(stt["frames"]), str(w), str(hgt), f"http://{request.host}", b["id"], blend],
                     stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    log.close()
    return ok({"opened": True, "blend": blend, "blender_at": b.get("blender_at") or 0})


@routes.post("/api/blockouts/{id}/from_blender")
async def blockout_from_blender(request):
    """{scene}: the scene as Blender read it back from its objects. Saved like an edit in the studio."""
    blender_here(request)
    d = await body(request)
    if not isinstance(d.get("scene"), dict):
        raise ValueError("send the scene")
    b = blockout_scenes.save(request.match_info["id"], {"scene": d["scene"]}, blender=True, why="Blender")
    return ok(blockout_scenes.view(b))


WRITES = {}                       # task id → {phase, chars, expect, started, done, result, error, proc}


def _write_stats():
    return config.read_json(config.home("writer", "blockout_write_stats.json")) or {}


@routes.post("/api/blockouts/write")
async def blockout_write(request):
    """{idea, scene?, size?}: Claude Code writes a blockout scene from words, or changes the scene it is given. Only
    text is sent. Starts it and answers {task}; GET /api/blockouts/write/{task} shows how far it is and the result."""
    this_computer(request)
    d = await body(request)
    idea = (d.get("idea") or "").strip()
    if not idea:
        raise ValueError("say what should happen first")
    text = "What to make: " + idea[:4000]
    if d.get("scene"):
        text += "\n\nThe current scene (change it as asked):\n" + json.dumps(d["scene"])[:60000]
    if d.get("size"):
        text += f"\n\nThe video is {d['size']} pixels (width x height)."
    bid = d.get("blockout") or ""
    if bid:
        blockout_scenes.load(bid)                    # it exists
        running = next((k for k, t in WRITES.items() if t.get("blockout") == bid and not t["done"]), None)
        if running:                                  # one change at a time: a second click joins the running one
            return ok(_write_view(running))
    stats = _write_stats()
    # about how long the answer is: the scene it changes plus a sentence, or what new scenes were like before
    # (changes are often longer than the scene they change: a camera that circles gets many keys)
    expect = int(len(json.dumps(d["scene"])) * (stats.get("grow") or 1.4)) + 200 if d.get("scene") else int(stats.get("new_chars") or 3500)
    for k in [k for k, t in WRITES.items() if t["done"] and time.time() - t["started"] > 600]:
        WRITES.pop(k, None)
    tid = uuid.uuid4().hex[:12]
    task = WRITES[tid] = {"phase": "starting", "chars": 0, "expect": expect, "started": time.time(), "done": False,
                          "result": None, "error": "", "typical": stats.get("seconds") or 0,
                          "blockout": bid, "idea": idea[:4000], "saved": False}

    async def run():
        try:
            answer, meta = await writer.run_claude(blockout_scenes.WRITE_SYSTEM, blockout_scenes.WRITE_SCHEMA, text,
                                                   timeout=900, progress=task)
            if not isinstance(answer, dict) or not isinstance(answer.get("scene"), dict):
                raise ValueError("Claude sent no scene; try again")
            try:
                blockouts.normalize(answer["scene"])
                problem = ""
            except blockouts.BadScene as e:
                problem = str(e)
            task["result"] = {"scene": answer["scene"], "say": answer.get("say") or "", "problem": problem, "seconds": meta.get("seconds")}
            if bid:                                  # saved here, so it is kept even when no page waits for it any more
                try:
                    old = blockout_scenes.load(bid)
                    blockout_scenes.save(bid, {"scene": answer["scene"], "idea": ((old.get("idea") or "") + "\n" + idea).strip()}, why="words")
                    task["saved"] = True
                except KeyError:                     # the blockout was deleted meanwhile
                    pass
            st = _write_stats()
            st["seconds"] = round(0.5 * (st.get("seconds") or meta.get("seconds") or 0) + 0.5 * (meta.get("seconds") or 0), 1)
            if not d.get("scene"):
                st["new_chars"] = int(0.5 * (st.get("new_chars") or 3500) + 0.5 * len(json.dumps(answer)))
            else:
                grow = (task["chars"] or len(json.dumps(answer))) / max(1, len(json.dumps(d["scene"])))
                st["grow"] = round(min(4.0, max(1.0, 0.5 * (st.get("grow") or 1.4) + 0.5 * grow)), 2)
            config.write_json(config.home("writer", "blockout_write_stats.json"), st)
        except Exception as e:                       # shown in the page
            task["error"] = "Stopped." if task.get("stopped") else str(e) or e.__class__.__name__
        finally:
            task["done"] = True
            task.pop("proc", None)
    fut = asyncio.ensure_future(run())
    if not d.get("progress"):          # a page from before progress existed (or a script): wait, answer with the scene
        await asyncio.shield(fut)
        if task["error"]:
            raise ValueError(task["error"])
        return ok(task["result"])
    return ok(_write_view(tid))


def _write_view(tid):
    t = WRITES.get(tid)
    if not t:
        raise KeyError("task")
    return {"task": tid, **{k: v for k, v in t.items() if k != "proc"}, "seconds": round(time.time() - t["started"], 1)}


@routes.get("/api/blockouts/write/{task}")
async def blockout_write_state(request):
    return ok(_write_view(request.match_info["task"]))


@routes.delete("/api/blockouts/write/{task}")
async def blockout_write_stop(request):
    t = WRITES.get(request.match_info["task"])
    if not t:
        raise KeyError("task")
    t["stopped"] = True
    p = t.get("proc")
    if p and p.returncode is None:
        p.kill()
    return ok(_write_view(request.match_info["task"]))


# ============================================================================================ canvas
@routes.get("/api/canvas")
async def canvas_list(request):
    return ok(canvas.all_boards())


@routes.post("/api/canvas")
async def canvas_new(request):
    return ok(canvas.create((await body(request)).get("name") or ""))


@routes.get("/api/canvas/{id}")
async def canvas_get(request):
    b = canvas.load(request.match_info["id"])
    known = {}
    for i in b["items"]:
        if i["type"] == "asset" and i["asset"] not in known:
            a = library.get(i["asset"])
            known[i["asset"]] = asset_view(a) if a and not a.get("trashed") else None
    return ok({**b, "assets": known})


@routes.put("/api/canvas/{id}")
async def canvas_put(request):
    return ok(canvas.save(request.match_info["id"], await body(request)))


@routes.delete("/api/canvas/{id}")
async def canvas_delete(request):
    canvas.delete(request.match_info["id"])
    return ok(deleted=True)


# ============================================================================================ the agent
def _speakers_as_people(lines):
    names = []
    for ln in lines or []:
        n = (ln.get("speaker") or "").strip()
        if n and n not in names:
            names.append(n)
    return [{"name": n, "pronoun": "their", "description": ""} for n in names]


def agent_run(st, c, a):
    """An allowed action becomes a job. Returns the action, changed."""
    if a["status"] not in ("proposed", "denied", "failed"):
        raise ValueError("this action already ran")
    for k in ("error", "made", "job", "progress"):
        a.pop(k, None)
    tool = a["tool"]
    if tool == "make_picture":
        w, hh = agent.picture_size(a["shape"])
        j = st.queue.add("image", {"prompt": a["prompt"], "width": w, "height": hh, "takes": a["count"], "surface": "agent"},
                         title="Picture · " + a["prompt"][:48])
        a.update(status="queued", job=j["id"])
    elif tool == "edit_picture":
        src = library.get(a["asset"])
        if not src:
            raise ValueError("that picture is no longer in the Library")
        j = st.queue.add("image", {"prompt": a["prompt"], "pictures": [config.out_ref(library.abs_path(src))], "keep_size": True,
                                   "takes": 1, "surface": "agent"}, title="Edit · " + a["prompt"][:48])
        a.update(status="queued", job=j["id"])
    elif tool in ("animate_picture", "make_clip"):
        d = {"action": a["prompt"], "sound": a["sound"], "lines": a["lines"], "people": _speakers_as_people(a["lines"]),
             "frames": agent.frames_for(a["seconds"]), "surface": "agent", "name": a["prompt"][:48]}
        if tool == "animate_picture":
            src = library.get(a["asset"])
            if not src:
                raise ValueError("that picture is no longer in the Library")
            d["first_frame"] = config.out_ref(library.abs_path(src))
            portrait = (src.get("height") or 0) > (src.get("width") or 1)
            d["width"], d["height"] = agent.video_size("vertical" if portrait else "landscape")
        else:
            d["width"], d["height"] = agent.video_size(a["shape"])
        film, sh = quick_film(d)
        j = st.production.queue_shot(film, sh, force=True)
        a.update(status="queued", job=j["id"], film=film["id"])
    elif tool == "start_film":
        conv = writer.new_conversation()
        a.update(status="running", writer=conv["id"])

        async def write():
            try:
                await writer.turn(conv["id"], a["story"])
                state = "done"
            except Exception as e:                       # noqa: BLE001 - the chat shows what went wrong
                state = "failed: " + str(e)[:200]
            with agent._lock:
                cc = agent.load(c["id"])
                aa = agent.find_action(cc, a["id"])
                aa["status"] = "done" if state == "done" else "failed"
                if state != "done":
                    aa["error"] = state[8:]
                agent.save(cc)
        asyncio.get_running_loop().create_task(write())
    return a


def agent_view(st, c):
    """The chat, with each action's job looked up: how far it got and what it made."""
    changed = False
    for t in c["turns"]:
        for a in t.get("actions", []):
            if not a.get("job") or a["status"] in ("done", "failed", "denied"):
                continue
            j = st.queue.get(a["job"])
            if not j:
                continue
            if j["status"] in ("queued", "running"):
                a["status"] = j["status"]
                a["progress"] = (j.get("progress") or {}).get("text", "")
                continue
            if j["status"] == "done":
                res = j.get("result") or {}
                made = list(res.get("assets") or [])
                if a.get("film"):
                    f = films.load(a["film"])
                    if f and f.get("asset"):
                        made = [f["asset"]]
                a.update(status="done", made=made)
            else:
                a.update(status="failed", error=j.get("error") or j["status"])
            a.pop("progress", None)
            changed = True
    if changed:
        agent.save(c)
    out = json.loads(json.dumps(c))
    for t in out["turns"]:
        for a in t.get("actions", []):
            a["assets"] = [asset_view(x) for x in (library.get(i) for i in a.get("made", [])) if x]
            if a.get("asset"):
                src = library.get(a["asset"])
                a["source"] = asset_view(src) if src else None
    out["writer"] = writer.state()
    return out


@routes.get("/api/agent")
async def agent_list(request):
    return ok({"chats": agent.all_chats(), "state": writer.state()})


@routes.post("/api/agent")
async def agent_new(request):
    this_computer(request)
    return ok(agent_view(app_of(request), agent.new_chat()))


@routes.get("/api/agent/{id}")
async def agent_get(request):
    return ok(agent_view(app_of(request), agent.load(request.match_info["id"])))


@routes.patch("/api/agent/{id}")
async def agent_patch(request):
    d = await body(request)
    with agent._lock:
        c = agent.load(request.match_info["id"])
        if "ask_first" in d:
            c["ask_first"] = bool(d["ask_first"])
        if str(d.get("title") or "").strip():
            c["title"] = str(d["title"]).strip()[:80]
        agent.save(c)
    return ok(agent_view(app_of(request), c))


@routes.post("/api/agent/{id}/say")
async def agent_say(request):
    """{text}: the user's turn. Waits for the answer. With "ask first" off, the actions start straight away."""
    this_computer(request)
    st = app_of(request)
    c = await agent.turn(request.match_info["id"], (await body(request)).get("text") or "")
    if not c.get("ask_first", True):
        with agent._lock:
            c = agent.load(c["id"])
            for a in c["turns"][-1].get("actions", []):
                if a["status"] == "proposed":
                    try:
                        agent_run(st, c, a)
                    except (ValueError, KeyError) as e:
                        a.update(status="failed", error=str(e))
            agent.save(c)
    return ok(agent_view(st, c))


@routes.post("/api/agent/{id}/act")
async def agent_act(request):
    """{action, allow}: run an action the agent proposed, or turn it down."""
    d = await body(request)
    st = app_of(request)
    with agent._lock:
        c = agent.load(request.match_info["id"])
        a = agent.find_action(c, str(d.get("action") or ""))
        if d.get("allow"):
            agent_run(st, c, a)
        elif a["status"] == "proposed":
            a["status"] = "denied"
        agent.save(c)
    return ok(agent_view(st, c))


@routes.delete("/api/agent/{id}")
async def agent_delete(request):
    agent.delete(request.match_info["id"])
    return ok(deleted=True)


# ============================================================================================ shorts
SHORT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "look", "place", "people", "beats"], "properties": {
    "title": {"type": "string"}, "look": {"type": "string"}, "place": {"type": "string"},
    "people": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "description"],
                                          "properties": {"name": {"type": "string"}, "description": {"type": "string"}}}},
    "beats": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["action", "sound", "lines"], "properties": {
        "action": {"type": "string"}, "sound": {"type": "string"},
        "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["speaker", "text"],
                                             "properties": {"speaker": {"type": "string"}, "text": {"type": "string"}}}}}}}}}


@routes.post("/api/shorts/plan")
async def shorts_plan(request):
    """{idea, parts}: Claude splits one idea into parts of one continuous vertical take. Only text is sent."""
    this_computer(request)
    d = await body(request)
    idea = (d.get("idea") or "").strip()
    if not idea:
        raise ValueError("write the idea first")
    n = max(1, min(int(d.get("parts") or 3), 6))
    looks = [s["id"] for s in presets.load("looks")["styles"]]
    system = f"""You plan a short vertical video (9:16) for H3 Studio. It is ONE continuous take made of {n} parts of about
8.5 seconds; each part after the first continues the one before without a cut (same place, same light, the camera
goes on). Answer with the JSON object only.
- "title": a short title. "look": one of {json.dumps(looks)}. "place": the place, as the camera sees it, with its light.
- "people": everyone in it, with a one-sentence description (age, face, hair, clothes). Invented people only.
- "beats": exactly {n}, in order. "action": what happens in that part, few actions, with sides (left/right of the picture).
  A later beat names only what is in view at the end of the beat before. "sound": what is heard besides words.
  "lines": every spoken word, exact, with the speaker's name; [] when nobody speaks. At most 20 words a part.
- No text, logos or lettering in the picture. No real people, brands or scenes from existing films or shows."""
    answer, meta = await writer.run_claude(system, SHORT_SCHEMA, "The idea: " + idea, timeout=300)
    if not isinstance(answer, dict):
        raise ValueError("Claude sent no plan; try again")
    answer["beats"] = (answer.get("beats") or [])[:n]
    return ok({"plan": answer, "seconds": meta.get("seconds")})


@routes.post("/api/shorts")
async def shorts_make(request):
    """{plan, size, face, voice}: the plan as a quick film of parts that continue each other, rendered in order."""
    d = await body(request)
    st = app_of(request)
    plan = d.get("plan") or {}
    beats = [b for b in plan.get("beats") or [] if (b.get("action") or "").strip()]
    if not beats:
        raise ValueError("the plan has no parts")
    w, hh = [int(x) for x in (d.get("size") or "640x1152").split("x")]
    people = [{"name": p["name"], "pronoun": "their", "description": p.get("description", "")} for p in plan.get("people") or [] if p.get("name")]
    if people and (d.get("face") or d.get("voice")):
        people[0]["face"] = d.get("face") or ""
        people[0]["voice"] = d.get("voice") or ""
    first = beats[0]
    film, sh = quick_film({"name": plan.get("title") or "Short", "place": plan.get("place", ""), "action": first["action"],
                           "sound": first.get("sound", ""), "lines": first.get("lines") or [], "people": people,
                           "look": plan.get("look") or "cinematic", "width": w, "height": hh, "frames": 209, "surface": "shorts",
                           "turbo": True, "one_take": True, "notext": True})
    cast = {c["name"]: c["id"] for c in film["cast"]}
    for b in beats[1:]:
        lines = [{"speaker": cast.get(ln.get("speaker"), ln.get("speaker", "")), "text": ln.get("text", ""), "how": ""}
                 for ln in b.get("lines") or [] if (ln.get("text") or "").strip()]
        films.new_shot(film, title=b["action"][:48], new_shot=False, mode="fields", cast=list(cast.values()), action=b["action"],
                       sound=b.get("sound", ""), lines=lines, frames=209)
    film["form"] = {"short": plan, "size": f"{w}x{hh}"}
    films.save(film)
    await st.production.start(film["id"], mode="auto", retries=1)
    return ok({"film": film["id"], "parts": len(film["shots"])})


@routes.get("/api/docs/{name}")
async def docs(request):
    rel = DOCS.get(request.match_info["name"])
    path = os.path.join(config.REPO, rel) if rel else ""
    if not rel or not os.path.isfile(path):
        raise KeyError("doc")
    with open(path, encoding="utf-8") as f:
        return ok(text=f.read(), name=request.match_info["name"])


# ============================================================================================ the page
def page():
    """index.html, with the time each script and stylesheet was last changed in its address.

    A browser keeps a file that came without an expiry for a share of its age (an hour for a file ten hours old) and
    does not ask for it again on a reload. So after an update the page went on running the old script: a new button
    was missing until the cache ran out. A file that changed now has a new address."""
    with open(os.path.join(config.STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()

    def stamp(m):
        try:
            return f'{m.group(1)}/static/{m.group(2)}?v={int(os.path.getmtime(os.path.join(config.STATIC, m.group(2))))}"'
        except OSError:
            return m.group(0)
    return re.sub(r'((?:src|href)=")/static/([\w.-]+)"', stamp, html)


@routes.get("/")
async def index(request):
    return web.Response(text=await asyncio.to_thread(page), content_type="text/html", headers={"Cache-Control": "no-cache"})


async def fresh_static(request, response):
    """The page's own files are checked for a newer version every time; an unchanged one costs an empty answer."""
    if request.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")


def make_app(hosts=("127.0.0.1", "localhost", "::1")):
    app = web.Application(middlewares=[guard], client_max_size=64 * 2 ** 20)
    app[HOSTS] = set(hosts)
    studio = Studio()
    app[STUDIO] = studio
    app.on_startup.append(studio.start)
    app.on_cleanup.append(studio.stop)
    app.on_response_prepare.append(fresh_static)
    app.add_routes(routes)
    app.router.add_static("/static/", config.STATIC, append_version=False)
    app.router.add_static("/docs/img/", os.path.join(config.REPO, "docs", "img"), append_version=False)   # the guide's pictures
    return app


def _take_lock(port):
    """One server per data folder: two would write the same film files at once."""
    config.ensure_home()
    path = config.home("server.lock")
    try:
        with open(path) as f:
            pid, was = (f.read().split() + ["", ""])[:2]
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            alive = b"studio" in f.read() and int(pid) != os.getpid()
    except (OSError, ValueError):
        alive = False
    if alive:
        raise SystemExit(f"Another studio (pid {pid}, port {was}) already uses {config.STUDIO_HOME}. Stop it first, "
                         "or give this one its own data folder with STUDIO_HOME=...")
    with open(path, "w") as f:
        f.write(f"{os.getpid()} {port}\n")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m studio", description="H3 Studio: a local film studio on ComfyUI.")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1: this computer only)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_PORT", 8191)))
    ap.add_argument("--allow-host", action="append", default=[], help="another name this studio may be reached under")
    a = ap.parse_args(argv)
    hosts = {"127.0.0.1", "localhost", "::1", a.host, *a.allow_host}
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: listening on {a.host}. The studio has no sign-in: anyone who can reach it can use it and read "
              "ComfyUI's output folder. Keep it on a network you trust.")
    _take_lock(a.port)
    print(f"H3 Studio  http://{a.host}:{a.port}   ComfyUI {config.settings()['comfy_url']}   data {config.STUDIO_HOME}", flush=True)
    web.run_app(make_app(hosts), host=a.host, port=a.port, print=None)


if __name__ == "__main__":
    main()
