"""What each kind of job does. Every handler is `async def name(job, ctx)` and returns the job's result.

gpu lane   image (also edits, angle sets and storyboard stills), shot (one part of a film, then its checks and the
           gate), upscale, tts
cpu lane   review, captions, location_sound, export, resolve, conform, dailies  (see finish.py for the last four)
"""
import asyncio
import json
import os
import random
import shutil
import subprocess
import time

from . import blockout_scenes, blockouts, checks, compose, config, films, graphs, lengths, library, machine, models, presets
from .comfy import files_of
from .jobs import Cancelled, Refused

HANDLERS = {}



# what a picture job was asked, kept on each picture so Recreate can fill the form again
FORM_KEYS = ("prompt", "template", "width", "height", "takes", "seed", "pictures", "angles", "keep_size", "name")

def handler(lane="gpu"):
    def wrap(fn):
        fn.lane = lane
        HANDLERS[fn.__name__] = fn
        return fn
    return wrap


def new_seed():
    return random.randrange(1, 2 ** 48)


async def _roles(ctx):
    info = await ctx.info()
    return info, models.resolve(info)


def _need_feature(info, key):
    f = models.features(info)[key]
    if not f["ok"]:
        raise Refused(f"{f['title']} cannot run here: {models.why_not(f)}")


# ------------------------------------------------------------------------------------------------ pictures
@handler("gpu")
async def image(job, ctx):
    """Pictures from words, or from words and pictures (an edit).

    params: prompt, width, height, takes, seed, steps, pictures [loader names], keep_size, name,
            template (apps.json templates: the prompt is put into it), angles [view ids] (one picture a view),
            film + shot (the pictures become that shot's storyboard stills)
    """
    p = job["params"]
    info, roles = await _roles(ctx)
    _need_feature(info, "edit" if p.get("pictures") else "image")
    s = config.settings()["image"]
    text = (p.get("prompt") or "").strip()
    tpl = presets.load("apps").get("templates", {}).get(p.get("template") or "")
    if tpl:
        text = tpl.replace("{text}", text)
    pictures = list(p.get("pictures") or [])
    plans = []                                       # (label, prompt)
    if p.get("angles"):
        if not pictures:
            raise Refused("an angle set needs a picture")
        a = presets.load("angles")
        if p["angles"] == "sheet" or p["angles"] == ["sheet"]:
            plans.append(("sheet", a["sheet"] + (" " + text if text else "")))
        else:
            ids = p["angles"] if isinstance(p["angles"], list) else next(
                (st["views"] for st in a["sets"] if st["id"] == p["angles"]), [])
            for vid in ids:
                v = next((x for x in a["views"] if x["id"] == vid), None)
                if v:
                    plans.append((v["name"], a["one"].replace("{view}", v["text"]) + (" " + text if text else "")))
        if not plans:
            raise Refused("no such angle set")
    else:
        if not text:
            raise Refused("write what the picture shows")
        plans = [("", text)] * max(1, min(int(p.get("takes") or 1), 12))
    seed0 = int(p.get("seed") or 0) or new_seed()
    name = config.slug(p.get("name") or text, "picture", 28)
    made = []
    t0 = time.time()
    for i, (label, prompt) in enumerate(plans):
        ctx.check_cancel()
        seed = seed0 if p.get("angles") else seed0 + i
        prefix = f"{config.out_sub('images')}/{name}_{job['id']}_{i + 1}"
        g = graphs.image(roles, prompt=prompt, prefix=prefix, width=int(p.get("width") or s["width"]),
                         height=int(p.get("height") or s["height"]), seed=seed, steps=int(p.get("steps") or s["steps"]),
                         pictures=pictures, keep_size=bool(p.get("keep_size")) and bool(pictures),
                         sampler=s["sampler"], scheduler=s["scheduler"], has_cache_node="QwenImage21Cache" in info)
        out = await ctx.render(g, graphs.IMAGE_STAGES, label=f"picture {i + 1} of {len(plans)}")
        for f in files_of(out, ("images",)):
            path = os.path.join(config.OUTPUT_DIR, f["subfolder"], f["filename"])
            a = library.add(path, "sheet" if label == "sheet" else "image", prompt=prompt, seed=seed, job=job["id"],
                            name=(p.get("name") or "").strip() or None, view=label or None,
                            film=p.get("film") or None, shot=p.get("shot") or None,
                            edited_from=pictures[0] if pictures else None,
                            form={k: p[k] for k in FORM_KEYS if p.get(k) not in (None, "", [])}, surface=p.get("surface") or None)
            made.append(a)
    ctx.queue.note_time("image", len(plans), time.time() - t0)
    if p.get("film") and p.get("prop") and made:
        # a prop's reference picture (the Writer's props get one when they are applied): kept unless one was set meanwhile
        with films.LOCK:
            film = films.load(p["film"])
            prop = next((x for x in (film or {}).get("props") or [] if x.get("id") == p["prop"]), None)
            if prop is not None and not prop.get("sheet"):
                prop["sheet"] = config.out_ref(library.abs_path(made[0]))
                films.save(film)
    if p.get("film") and p.get("shot"):
        with films.LOCK:
            film = films.load(p["film"])
            shot = films.get_shot(film, p["shot"]) if film else None
            if shot is not None:
                for a in made:
                    shot.setdefault("storyboard", []).append(
                        {"asset": a["id"], "file": config.out_ref(library.abs_path(a)), "seed": a.get("seed"), "time": time.time()})
                films.save(film)
    return {"assets": [a["id"] for a in made]}


# ------------------------------------------------------------------------------------------------ a part of a film
# How long a part takes grows faster than its size: on an RTX 3090 a step took 3.3 s for 864x480 x 73 frames and about
# 58 s for 1152x640 x 243 frames, 5.9 times the pixels x frames for 17.6 times the time. That is a power of 1.6.
# Around the sampling there is about a minute of loading, decoding, writing and checking.
CLIP_POWER, CLIP_BASE = 1.6, 60.0
CLIP_RATE = 58.0 / (1152 * 640 * 243) ** CLIP_POWER          # seconds a step, per unit, until this machine has its own
CLIP_PRIOR = (CLIP_BASE, CLIP_RATE)


def clip_units(c, steps):
    return (c["width"] * c["height"] * c["frames"]) ** CLIP_POWER * steps


@handler("gpu")
async def shot(job, ctx):
    """Render one shot of a film as its part of the long video, check it, and take it to the gate.

    params: film, shot, seed (0 = a new one), attempt (how many automatic retakes came before this one)
    """
    p = job["params"]
    info, roles = await _roles(ctx)
    _need_feature(info, "video")
    with films.LOCK:
        film = films.load(p["film"])
        if not film:
            raise Refused("this film no longer exists")
        sh = films.get_shot(film, p["shot"])
        if not sh:
            raise Refused("this shot no longer exists")
        ok, why = films.eligible(film, sh["id"], ignore_gate=bool(p.get("force")))
        if not ok:
            raise Refused(why)
        idx = films.shot_index(film, sh["id"])
        c = compose.compose(film, sh, idx, info)
        was = sh["status"]
        sh["status"] = "rendering"
        films.save(film)
    part = idx + 1
    try:
        if c["turbo"]:
            _need_feature(info, "turbo")
        if c["voices"]:
            _need_feature(info, "voices")
        fit = machine.fit(c["width"], c["height"], c["frames"], "this part")
        if not fit["ok"]:
            raise Refused(fit["text"])
        v = config.settings()["video"]
        steps = int(v["turbo_steps"] if c["turbo"] else v["steps"])
        seed = int(p.get("seed") or 0) or int(sh.get("seed") or 0) or new_seed()
        if p.get("attempt"):
            seed = new_seed()
        bs = blockouts.state(film, idx)
        if bs and not bs["made"] and not (sh.get("blockout") or "").strip():
            raise Refused("the blockout of this shot's scene is not made yet: make it in the film's Blockout step, or remove it there")
        blk = c.get("blockout")
        if blk:
            _need_feature(info, "blockout")
            src = await ctx.thread(blockout_source, blk["file"], blk["start"] + c["frames"])
            b = config.settings()["blockout"]
            g = graphs.blockout_clip(roles, project=film["long_project"], part=part, prompt=c["prompt"], blockout=src,
                                     start=blk["start"], strength=blk["strength"], new_shot=not c["continuation"],
                                     width=c["width"], height=c["height"], frames=c["frames"], seed=seed, turbo=c["turbo"],
                                     refs=c["refs"], voices=c["voices"], loras=c["loras"], steps=steps, crf=int(v["crf"]),
                                     sampler=b["sampler"], scheduler=b["scheduler"])
            stages = graphs.BLOCKOUT_STAGES
        else:
            g = graphs.clip(roles, project=film["long_project"], part=part, prompt=c["prompt"], new_shot=not c["continuation"],
                            width=c["width"], height=c["height"], frames=c["frames"], seed=seed, turbo=c["turbo"],
                            refs=c["refs"], first_frame=c["first_frame"] or None, last_frame=c["last_frame"] or None,
                            voices=c["voices"], loras=c["loras"], unet=c["unet"] or None, steps=steps, crf=int(v["crf"]))
            stages = graphs.CLIP_STAGES
        files = films.part_files(film, part)
        before = os.path.getmtime(files["segment"]) if os.path.isfile(files["segment"]) else 0
        est = ctx.queue.estimate("part", clip_units(c, steps), prior=CLIP_PRIOR)
        job["eta"] = time.time() + est if est else None
        t0 = time.time()
        await ctx.render(g, stages)
        if not os.path.isfile(files["segment"]) or os.path.getmtime(files["segment"]) <= before:
            raise Refused("ComfyUI finished but the part was not written; see ComfyUI's log")
        ctx.queue.note_time("part", clip_units(c, steps), time.time() - t0)

        ctx.say("checking the take")
        prev_seg = films.part_files(film, part - 1)["segment"] if c["continuation"] else None
        first_pic = config.ref_path(c["first_frame"]) if c["first_frame"] else None
        last_pic = config.ref_path(c["last_frame"]) if c["last_frame"] else None
        review = await ctx.thread(checks.review, files["segment"], lines=c["lines"], continuation=c["continuation"],
                                  prev_path=prev_seg, first_picture=first_pic, last_picture=last_pic,
                                  language=c["language"], asks_for_cut=c["asks_for_cut"],
                                  blockout=bool(c.get("blockout")), blockout_cuts=c.get("blockout_cuts") or [],
                                  blockout_file=config.ref_path(c["blockout"]["file"]) if c.get("blockout") else "",
                                  blockout_start=(c["blockout"].get("start") or 0) / 24 if c.get("blockout") else 0.0,
                                  loud_reference=films.speech_levels(film, but=sh["id"]))
    except BaseException as e:
        with films.LOCK:
            film = films.load(p["film"])
            sh = films.get_shot(film, p["shot"]) if film else None
            if sh is not None and sh["status"] == "rendering":
                # the Append node writes at the very end, so a render that failed left the take before it in place
                stopped = isinstance(e, (Cancelled, asyncio.CancelledError))
                sh["status"] = was if (stopped or (sh.get("part") and films.active_take(sh))) else "failed"
                if not stopped:
                    sh["error"] = str(e) or type(e).__name__
                films.save(film)
        raise

    def keep():
        """Record the take and decide at the gate. Runs in a thread: it writes a preview and two sheets with ffmpeg."""
        with films.LOCK:
            film = films.load(p["film"])
            sh = films.get_shot(film, p["shot"])
            take = films.record_take(film, sh, part=part, seed=seed, prompt=c["prompt"], job_id=job["id"], review=review,
                                     composed=c, started=t0)
            sh.pop("error", None)
            run = film.get("run") or {}
            gate = {"mode": run.get("mode"), "retries": run.get("retries")} if run.get("active") else (film.get("gate") or films.default_gate())
            hands_off = gate.get("mode") in ("auto", "keep_going")
            retake = False
            if review["ok"] and hands_off:
                films.set_verdict(film, sh["id"], "auto")
            elif not review["ok"] and hands_off and int(p.get("attempt") or 0) < int(gate.get("retries") or 0):
                take["verdict"] = "rejected"
                retake = True
            elif not review["ok"] and gate.get("mode") == "keep_going":
                take["needs_look"] = True          # kept so the run can go on; the morning notes list it first
            full = films.rebuild_full(film) if not os.path.isfile(films.full_path(film)) else films.full_path(film)
            if full and os.path.isfile(full):
                a = library.add(full, "clip" if film.get("quick") else "film", name=film["name"], film=film["id"],
                                film_name=film["name"], prompt=c["prompt"] if film.get("quick") else None,
                                seed=seed if film.get("quick") else None, quick=bool(film.get("quick")),
                                ok=review["ok"] if film.get("quick") else None, summary=review["summary"] if film.get("quick") else None,
                                form=film.get("form") if film.get("quick") else None, surface=film.get("surface"))
                film["asset"] = a["id"]
            films.save(film)
            return film, sh, take, retake

    film, sh, take, retake = await ctx.thread(keep)
    if retake:
        ctx.queue.add("shot", {"film": film["id"], "shot": sh["id"], "attempt": int(p.get("attempt") or 0) + 1,
                               "force": bool(p.get("force"))},
                      title=job["title"] + " (retake)", front=True, film=film["id"], shot=sh["id"])
    return {"film": film["id"], "shot": sh["id"], "take": take["n"], "ok": review["ok"], "summary": review["summary"],
            "retake": retake, "seed": seed, "preview": take.get("preview")}


@handler("gpu")
async def upscale(job, ctx):
    """Upscale the parts of a film in order (each join is crossfaded into the part before, so order matters).

    params: film, first, last (part numbers; default all), force (again even when the upscaled part is newer)
    """
    p = job["params"]
    info, roles = await _roles(ctx)
    _need_feature(info, "upscale")
    film = films.load(p["film"])
    if not film:
        raise Refused("this film no longer exists")
    u = config.settings()["upscale"]
    interpolate = bool(u["interpolate"]) and models.features(info)["interpolate"]["ok"]
    last_part = 0
    while os.path.isfile(films.part_files(film, last_part + 1)["segment"]):
        last_part += 1
    first, last = int(p.get("first") or 1), min(int(p.get("last") or last_part), last_part)
    if last < first:
        raise Refused("there is no rendered part to upscale")
    up_dir = os.path.join(films.project_dir(film), "upscaled")
    todo = []
    for part in range(first, last + 1):
        seg = films.part_files(film, part)["segment"]
        done = os.path.join(up_dir, f"part_{part:03d}.mkv")
        if not p.get("force") and os.path.isfile(done) and os.path.getmtime(done) >= os.path.getmtime(seg) and not todo:
            continue                      # once one part is redone, every later one is too: their joins depend on it
        todo.append(part)
    if not todo:
        return {"film": film["id"], "parts": [], "note": "every part was upscaled already"}
    await ctx.comfy.free()            # after a generation run RAM was at 59 of 62 GB
    t_all = time.time()
    for n, part in enumerate(todo):
        ctx.check_cancel()
        sh = next((s for s in film["shots"] if s.get("part") == part), None)
        take = films.active_take(sh) if sh else None
        if take:
            fit = machine.fit(take["width"], take["height"], take["frames"], f"the upscale of part {part}",
                              scale=float(u["scale"]), fps_multiplier=2 if interpolate else 1)
            if not fit["ok"]:
                raise Refused(fit["text"])
        loras = []
        for cid in (sh or {}).get("cast", []):
            c = next((x for x in film.get("cast", []) if x["id"] == cid), None)
            if c and (c.get("lora") or {}).get("file"):
                loras.append((c["lora"]["file"], float(c["lora"].get("strength", 1.0))))
        g = graphs.upscale(roles, project=film["long_project"], part=part, loras=loras, scale=float(u["scale"]),
                           interpolate=interpolate, sharpen=bool(u["sharpen"]), seed=new_seed(), sigmas=u["sigmas"])
        t0 = time.time()
        await ctx.render(g, graphs.UPSCALE_STAGES, label=f"part {part} ({n + 1} of {len(todo)})")
        ctx.queue.note_time("upscale", 1, time.time() - t0)
    full = films.full_path(film, upscaled=True)
    asset = None
    if os.path.isfile(full):
        asset = library.add(full, "clip" if film.get("quick") else "film", name=film["name"] + " (upscaled)", film=film["id"],
                            film_name=film["name"], quick=bool(film.get("quick")), upscaled=True)
        with films.LOCK:
            f2 = films.load(film["id"])
            if f2:
                f2["upscaled_asset"] = asset["id"]
                films.save(f2)
    return {"film": film["id"], "parts": todo, "seconds": round(time.time() - t_all), "asset": asset["id"] if asset else None}


# ------------------------------------------------------------------------------------------------ sound
@handler("gpu")
async def tts(job, ctx):
    """A line spoken by ChatterBox in one of the TTS suite's voices. params: text, voice, seed, name, language"""
    p = job["params"]
    info, _ = await _roles(ctx)
    _need_feature(info, "tts")
    voices = models.voices(info)
    voice = p.get("voice") or (voices[0] if voices else "")
    if voice not in voices:
        raise Refused(f"the voice \"{voice}\" is not in the TTS suite's list (models/voices; restart ComfyUI after adding one)")
    text = (p.get("text") or "").strip()
    if not text:
        raise Refused("write the words to speak")
    name = config.slug(p.get("name") or text, "voice", 28)
    g = graphs.tts(text=text, voice=voice, prefix=f"{config.out_sub('audio')}/{name}_{job['id']}", seed=int(p.get("seed") or 1),
                   language=p.get("language") or "local:English")
    out = await ctx.render(g, {"1": "loading the voice model", "2": "speaking", "3": "saving"})
    made = []
    for f in files_of(out, ("audio",)):
        path = os.path.join(config.OUTPUT_DIR, f["subfolder"], f["filename"])
        made.append(library.add(path, "audio", prompt=text, voice=voice, job=job["id"], name=(p.get("name") or "").strip() or None))
    return {"assets": [a["id"] for a in made]}


@handler("cpu")
async def review(job, ctx):
    """Run the checks on a clip again. params: asset, lines [{speaker, text}], language"""
    p = job["params"]
    a = library.get(p.get("asset") or "")
    if not a:
        raise Refused("no such clip")
    ctx.say("checking")
    r = await ctx.thread(checks.review, library.abs_path(a), lines=p.get("lines") or [], language=p.get("language") or "English")
    library.update(a["id"], ok=r["ok"], summary=r["summary"], checks=r["checks"])
    return {"asset": a["id"], "ok": r["ok"], "summary": r["summary"], "checks": r["checks"], "window": r.get("window")}


@handler("cpu")
async def captions(job, ctx):
    """What is said in a clip, as a SubRip file beside it. params: asset, language"""
    p = job["params"]
    a = library.get(p.get("asset") or "")
    if not a:
        raise Refused("no such clip")
    ctx.say("listening")
    path = library.abs_path(a)
    heard = await ctx.thread(checks.transcribe, path, checks.language_code(p.get("language") or "English"))
    if heard is None:
        raise Refused("openai-whisper is not installed in the Python that runs the studio (use ComfyUI's venv)")
    out = config.home("exports", os.path.splitext(os.path.basename(path))[0] + ".srt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(checks.srt(heard))
    library.update(a["id"], transcript=heard["text"].strip(), srt=os.path.relpath(out, config.OUTPUT_DIR).replace(os.sep, "/"))
    return {"asset": a["id"], "text": heard["text"].strip(), "srt": os.path.relpath(out, config.OUTPUT_DIR).replace(os.sep, "/")}


def location_sound_cmd(src, dst, echo=0.22, noise=0.02):
    """The story kit's location_sound.py as one ffmpeg command: band-limit, short wall reflections, faint rumble, -18 LUFS."""
    voice = "highpass=f=150,lowpass=f=6500,equalizer=f=2500:t=q:w=1:g=-2"
    if echo > 0:
        voice += f",aecho=0.85:0.5:23|41|67:{echo:.3f}|{echo * 0.64:.3f}|{echo * 0.36:.3f}"
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", src]
    if noise > 0:
        cmd += ["-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude={noise}:sample_rate=48000"]
        graph = (f"[0:a]{voice},volume=0.95[v];[1:a]lowpass=f=900,highpass=f=60,volume=0.6[n];"
                 f"[v][n]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-18:TP=-1.5:LRA=11[a]")
    else:
        graph = f"[0:a]{voice},loudnorm=I=-18:TP=-1.5:LRA=11[a]"
    return cmd + ["-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-shortest", dst]


@handler("cpu")
async def location_sound(job, ctx):
    """Dialogue that sounds recorded on location, not in a studio. params: asset, echo, noise"""
    p = job["params"]
    a = library.get(p.get("asset") or "")
    if not a:
        raise Refused("no such clip")
    src = library.abs_path(a)
    dst = config.home("exports", os.path.splitext(os.path.basename(src))[0] + f"_location_{job['id']}.mp4")
    ctx.say("re-mixing the sound")
    r = await ctx.thread(subprocess.run, location_sound_cmd(src, dst, float(p.get("echo", 0.22)), float(p.get("noise", 0.02))),
                         capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused("ffmpeg failed: " + r.stderr.strip()[-300:])
    new = library.add(dst, "export", name=a["name"] + " (location sound)", film=a.get("film"), film_name=a.get("film_name"),
                      made_from=a["id"], job=job["id"])
    return {"asset": new["id"]}


async def render_blockout(scene, frames, w, hgt, out, job, ctx, exe):
    """Render a (normalized) blockout scene in Blender into out/blockout.mp4. Returns (mp4 path, stats or None)."""
    os.makedirs(out, exist_ok=True)
    config.write_json(os.path.join(out, "scene.json"), scene)
    ctx.say("Blender: building the scene")
    proc = await asyncio.create_subprocess_exec(
        exe, "-b", "--factory-startup", "-P", blockouts.SCRIPT, "--", os.path.join(out, "scene.json"), out,
        str(frames), str(w), str(hgt), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    tail = []
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            tail = (tail + [text])[-30:]
            if text.startswith("Fra:"):
                try:
                    ctx.say("Blender: rendering frames", int(text.split()[0][4:]), frames)
                except ValueError:
                    pass
            if ctx.queue.cancelled(job):
                proc.kill()
                raise Cancelled()
        await proc.wait()
    finally:
        if proc.returncode is None:
            proc.kill()
    pngs = sorted(f for f in os.listdir(out) if f.startswith("f_") and f.endswith(".png"))
    if proc.returncode != 0 or len(pngs) < frames:
        err = next((t for t in reversed(tail) if "Error" in t or "Traceback" in t), tail[-1] if tail else "")
        raise Refused(f"Blender did not render the blockout ({len(pngs)} of {frames} frames): {err[:300]}")
    ctx.say("making the video")
    mp4 = os.path.join(out, "blockout.mp4")

    def encode():
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "24", "-i", os.path.join(out, "f_%04d.png"),
                            "-frames:v", str(frames), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", mp4],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Refused("ffmpeg could not make the blockout video: " + r.stderr.strip()[-300:])
        for f in pngs:
            os.remove(os.path.join(out, f))
    await ctx.thread(encode)
    try:
        with open(os.path.join(out, "stats.json")) as fh:
            stats = json.load(fh)
    except (OSError, ValueError):
        stats = None
    return mp4, stats


@handler("cpu")
async def blockout(job, ctx):
    """Render the blockout of a scene in Blender and give it its video.

    params: film, blockout (its id). The video runs long enough for every shot of the scene to read its stretch
    (blockouts.cuts) and for the whole scene; each shot then follows its stretch (compose.blockout_plan)."""
    p = job["params"]
    exe = blockouts.blender()
    if not exe:
        raise Refused("Blender was not found: install it, or set its path in Machine → Settings (blender)")
    with films.LOCK:
        film = films.load(p["film"])
        if not film:
            raise Refused("this film no longer exists")
        b = blockouts.find(film, p["blockout"])
        if not b:
            raise Refused("this blockout no longer exists")
        if not b.get("scene"):
            raise Refused("this blockout has no scene written yet")
        try:
            scene = blockouts.normalize(b["scene"])
        except blockouts.BadScene as e:
            raise Refused(f"the blockout scene: {e}")
        frames = blockouts.render_frames(film, b, scene)
        bible = {**compose.blank_bible(), **(film.get("bible") or {})}
        w, hgt = int(bible["width"]), int(bible["height"])
        bid = b["id"]
        label = b.get("scene_name") or "the film"
    sig = blockouts.signature(scene, frames, w, hgt)
    mp4, stats = await render_blockout(scene, frames, w, hgt, config.home("blockouts", f"{film['id']}_{bid}_{sig}"), job, ctx, exe)
    ref = config.out_ref(mp4)

    def keep():
        with films.LOCK:
            film = films.load(p["film"])
            b = blockouts.find(film, bid)
            if not b:
                raise Refused("the blockout was removed while it was made")
            b.update(video=ref, made=sig, stats=stats)
            films.save(film)
            library.add(mp4, "clip", name=f"Blockout · {film['name']} · scene {label}", film=film["id"])
            return [c["id"] for c in blockouts.cuts(film, b) if film["shots"][c["index"]].get("takes")]
    rendered = await ctx.thread(keep)
    return {"film": p["film"], "blockout_id": bid, "scene": label, "blockout": ref, "frames": frames,
            "seconds": round(frames / 24, 1), "rerender": rendered, "stats": stats, "small": blockouts.too_small(stats)}


@handler("cpu")
async def blockout_free(job, ctx):
    """Render a blockout made in the Blockout room (blockout_scenes) in Blender, and put its video in the Library.

    params: blockout (its id)."""
    bid = job["params"]["blockout"]
    exe = blockouts.blender()
    if not exe:
        raise Refused("Blender was not found: install it, or set its path in Machine → Settings (blender)")
    try:
        b = blockout_scenes.load(bid)
    except KeyError:
        raise Refused("this blockout no longer exists")
    try:
        scene = blockouts.normalize(b.get("scene"))
    except blockouts.BadScene as e:
        raise Refused(f"the scene: {e}")
    frames = max(blockouts.scene_frames(scene), 24)
    w, hgt = blockout_scenes.size_of(b)
    sig = blockouts.signature(scene, frames, w, hgt)
    mp4, stats = await render_blockout(scene, frames, w, hgt, config.home("blockouts", f"free_{bid}_{sig}"), job, ctx, exe)
    shapes = blockout_scenes.shapes_text(scene)
    a = library.add(mp4, "clip", name=f"Blockout · {b['name']}", surface="blockout", blockout=bid,
                    form={"blockout_shapes": shapes})
    blockout_scenes.made(bid, config.out_ref(mp4), a["id"], sig, stats, shapes=shapes)
    return {"blockout_id": bid, "blockout": config.out_ref(mp4), "assets": [a["id"]], "frames": frames,
            "seconds": round(frames / 24, 1), "stats": stats, "small": blockouts.too_small(stats)}


def preview_project(film, opener_id):
    return f"{film['long_project']}_preview_{opener_id}"


@handler("gpu")
async def preview(job, ctx):
    """A very small render of a shot to see the staging, the action and the camera before the real one.

    It goes into a project of its own per take (<film project>_preview_<shot that opens the take>), so it never
    replaces a part of the film, never waits at the gate and makes nothing stale. A continuation continues the preview
    of the shot before it, so the joins show as well; that preview must be there.
    params: film, shot, seed (0 = a new one)"""
    p = job["params"]
    info, roles = await _roles(ctx)
    _need_feature(info, "video")
    with films.LOCK:
        film = films.load(p["film"])
        if not film:
            raise Refused("this film no longer exists")
        sh = films.get_shot(film, p["shot"])
        if not sh:
            raise Refused("this shot no longer exists")
        idx = films.shot_index(film, sh["id"])
        take = compose.take_of(film, idx)
        pos = take.index(idx)
        opener = film["shots"][take[0]]
        c = compose.compose(film, sh, idx, info)
        bs = blockouts.state(film, idx)
    if bs and not bs["made"] and not (sh.get("blockout") or "").strip():
        raise Refused("the blockout of this shot's scene is not made yet: make it in the film's Blockout step, or remove it there")
    project = preview_project(film, opener["id"])
    part = pos + 1
    if pos:
        before = film["shots"][take[pos - 1]]
        if not os.path.isfile(films.part_files(film, pos, project)["latent"]):
            raise Refused(f"this shot continues shot {take[pos - 1] + 1} ({before.get('title') or 'untitled'}): preview that one first")
    short = int(config.settings()["preview"]["short_side"])
    w, hgt = lengths.preview_size(c["width"], c["height"], short)
    v = config.settings()["video"]
    steps = int(v["turbo_steps"] if c["turbo"] else v["steps"])
    seed = int(p.get("seed") or 0) or new_seed()
    blk = c.get("blockout")
    if blk:
        _need_feature(info, "blockout")
        src = await ctx.thread(blockout_source, blk["file"], blk["start"] + c["frames"])
        b = config.settings()["blockout"]
        g = graphs.blockout_clip(roles, project=project, part=part, prompt=c["prompt"], blockout=src, start=blk["start"],
                                 strength=blk["strength"], new_shot=pos == 0, width=w, height=hgt, frames=c["frames"],
                                 seed=seed, turbo=c["turbo"], refs=c["refs"], voices=c["voices"], loras=c["loras"],
                                 steps=steps, crf=int(v["crf"]), sampler=b["sampler"], scheduler=b["scheduler"],
                                 ref_scale=1.0)     # half of a preview (224x128) leaves a person a few pixels high
        stages = graphs.BLOCKOUT_STAGES
    else:
        g = graphs.clip(roles, project=project, part=part, prompt=c["prompt"], new_shot=pos == 0, width=w, height=hgt,
                        frames=c["frames"], seed=seed, turbo=c["turbo"], refs=c["refs"],
                        first_frame=(c["first_frame"] or None) if pos == 0 else None, last_frame=c["last_frame"] or None,
                        voices=c["voices"], loras=c["loras"], unet=c["unet"] or None, steps=steps, crf=int(v["crf"]))
        stages = graphs.CLIP_STAGES
    seg = films.part_files(film, part, project)["segment"]
    before_t = os.path.getmtime(seg) if os.path.isfile(seg) else 0
    units = clip_units({**c, "width": w, "height": hgt}, steps)
    est = ctx.queue.estimate("preview", units, prior=CLIP_PRIOR)
    job["eta"] = time.time() + est if est else None
    t0 = time.time()
    await ctx.render(g, stages, label="preview")
    if not os.path.isfile(seg) or os.path.getmtime(seg) <= before_t:
        raise Refused("ComfyUI finished but the preview was not written; see ComfyUI's log")
    took = time.time() - t0
    ctx.queue.note_time("preview", units, took)
    ctx.say("making the preview playable")

    def keep():
        d = films.take_dir(film, sh)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "preview.mp4")
        tmp = out + ".tmp.mp4"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", seg, "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                            "-movflags", "+faststart", tmp], capture_output=True, text=True)
        if r.returncode != 0:
            raise Refused("ffmpeg could not make the preview playable: " + r.stderr.strip()[-300:])
        os.replace(tmp, out)
        rel = os.path.relpath(out, config.OUTPUT_DIR).replace(os.sep, "/")
        with films.LOCK:
            f = films.load(p["film"])
            s = films.get_shot(f, p["shot"])
            if not s:
                return rel
            s["preview"] = {"file": rel, "seed": seed, "width": w, "height": hgt, "frames": c["frames"], "time": time.time(),
                            "seconds_taken": round(took, 1), "prompt": c["prompt"],
                            "blockout": {"start": blk["start"], "end": blk["start"] + c["frames"]} if blk else None}
            i = films.shot_index(f, s["id"])
            for j in compose.take_of(f, i):            # the previews after it continued the one that was replaced
                if j > i:
                    f["shots"][j]["preview"] = None
            films.save(f)
        return rel
    rel = await ctx.thread(keep)
    return {"film": film["id"], "shot": sh["id"], "preview": rel, "seed": seed, "width": w, "height": hgt,
            "seconds": round(took, 1)}


def video_frames(path, fps=24):
    """How many frames a video has at `fps` (0 when it cannot be read)."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration:format=duration",
                            "-of", "json", path], capture_output=True, text=True)
    try:
        d = json.loads(probe.stdout or "{}")
    except ValueError:
        return 0
    for v in [x.get("duration") for x in d.get("streams") or []] + [(d.get("format") or {}).get("duration")]:
        try:
            return int(round(float(v) * fps))       # the picture's own length first: a sound track can run longer
        except (TypeError, ValueError):
            continue
    return 0


def _source_size(dst, size=None):
    """The size of the file a 24 fps copy was made from (kept next to it), to see that it is still the same file."""
    meta = dst + ".src"
    if size is not None:
        with open(meta, "w") as f:
            f.write(str(size))
        return size
    try:
        with open(meta) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return -1


def blockout_source(name, need):
    """A blockout video as the V2V nodes take it: 24 fps, with a sound track a little longer than the picture (the
    V2V node stops with "source audio is N samples short" otherwise; a Blender render has no sound at all).
    Made once per file in studio/blockouts and remade when the file changes. `need` = the last frame this part reads.
    Returns the absolute path. Raises Refused when the blockout is too short for the part."""
    src = config.ref_path(name)
    if not os.path.isfile(src):
        raise Refused(f"the blockout {name} is not there any more")
    # every rendered blockout is called blockout.mp4 in a folder of its own: name the copy after the folder too, or
    # the scenes of a film share one copy and a part reads another scene's motion
    stem = os.path.splitext(os.path.basename(src))[0]
    folder = os.path.basename(os.path.dirname(src))
    base = config.slug(f"{folder}_{stem}" if folder and folder != "blockouts" else stem, "blockout", 100)
    dst = config.home("blockouts", f"{base}_24fps.mkv")
    if not os.path.isfile(dst) or os.path.getmtime(dst) < os.path.getmtime(src) or os.path.getsize(src) != _source_size(dst):
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                               capture_output=True, text=True)
        try:
            seconds = float(probe.stdout.strip())
        except ValueError:
            raise Refused(f"the blockout {name} cannot be read as a video")
        tmp = dst + ".tmp.mkv"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-f", "lavfi", "-t", f"{seconds + 1:.2f}",
                            "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a", "-vf", "fps=24",
                            "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise Refused(f"the blockout {name} could not be prepared: {r.stderr.strip()[-300:]}")
        os.replace(tmp, dst)
        _source_size(dst, os.path.getsize(src))
    have = video_frames(src)
    if have and have < need:
        raise Refused(f"the blockout has {have} frames ({have / 24:.1f} s); this part reads up to frame {need}. "
                      "Make the blockout longer, start the shot earlier in it, or make the shot shorter.")
    return dst


def copy_into_uploads(src, name=None):
    """Copy any readable media file into studio/uploads so it can be used as a reference. Returns its loader name."""
    base = config.slug(os.path.splitext(name or os.path.basename(src))[0], "file", 40)
    ext = os.path.splitext(src)[1].lower()
    dst = config.home("uploads", f"{base}_{int(time.time() * 1000) % 10 ** 9}{ext}")
    shutil.copy2(src, dst)
    return config.out_ref(dst)
