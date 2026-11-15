"""Timelines and what leaves the studio: the export, the files for an editor, the dailies.

A timeline is one video track: clips in order, each with an In and an Out, an optional song under it, an optional
title card and captions. `export` renders it with ffmpeg on this computer:

  levels     every clip that has speech is brought to the same loudness before the cut is joined (one part of a
             film came out 3 dB hotter than its neighbours; whole-film normalising does not fix that), then the whole
             cut is normalised to -16 LUFS.
  music      laid under the cut and lowered while a clip has sound (a compressor keyed by the clips' own sound).
  captions   what Whisper hears in each clip, burned in. Without Whisper they are left out, never made up.

For an editor: an FCPXML and an EDL of the cut, and for DaVinci Resolve the media as ProRes 422 with PCM sound (the
free Resolve on Linux reads neither H.264 nor AAC). `conform` brings an editor's export back to the film's own size.
"""
import math
import os
import re
import shutil
import subprocess
import time
import uuid
import xml.sax.saxutils as sx

from . import beats as beats_mod
from . import checks, config, films, library
from .jobs import Refused
from .work import handler

SPEECH_FLOOR = -35.0        # integrated LUFS above which a clip counts as having speech or music to level
MAX_UP, MAX_DOWN = 6.0, 15.0    # dB a clip may be raised (more would lift its noise) and lowered (turning down is harmless)


# ---------------------------------------------------------------------------------------- timelines
def tl_path(tid):
    return config.home("timelines", tid + ".json")


def blank(name="Timeline"):
    f = config.settings()["finish"]
    return {"id": uuid.uuid4().hex[:8], "name": name, "created": time.time(), "updated": time.time(), "clips": [],
            "music": {"path": "", "gain": f["music_gain"], "duck": f["duck"]}, "title": {"text": "", "subtitle": "", "seconds": 3.0},
            "captions": False, "width": 0, "height": 0, "fps": 0, "loudness": f["loudness"], "match": f["match_clips"]}


def load(tid):
    if not tid or "/" in tid or ".." in tid:
        return None
    t = config.read_json(tl_path(tid))
    if t:
        for k, v in blank().items():
            t.setdefault(k, v)
    return t


def save(tl):
    tl["updated"] = time.time()
    config.write_json(tl_path(tl["id"]), tl)
    return tl


def all_timelines():
    root = config.home("timelines")
    out = [config.read_json(os.path.join(root, f)) for f in os.listdir(root) if f.endswith(".json")]
    out = [{"id": t["id"], "name": t["name"], "updated": t.get("updated", 0), "clips": len(t.get("clips", [])),
            "seconds": round(sum(max(0.0, (c.get("out") or 0) - (c.get("in") or 0)) for c in t.get("clips", [])), 1)}
           for t in out if t]
    return sorted(out, key=lambda t: t["updated"], reverse=True)


def clip_path(c):
    """The file of a timeline clip: an asset of the Library, or a path under output/."""
    if c.get("asset"):
        a = library.get(c["asset"])
        if a:
            return library.abs_path(a)
    p = os.path.join(config.OUTPUT_DIR, c.get("path") or "")
    return p if c.get("path") and config.inside(p, config.OUTPUT_DIR) else ""


def add_clip(tl, path=None, asset=None, start=None, end=None, title=""):
    a = library.get(asset) if asset else None
    p = library.abs_path(a) if a else path
    info = checks.probe(p) if p else {}
    if not info.get("has_video"):
        raise ValueError("this is not a clip that can go on a timeline")
    dur = info["duration"]
    c = {"id": uuid.uuid4().hex[:6], "asset": asset or "", "path": os.path.relpath(os.path.realpath(p), os.path.realpath(config.OUTPUT_DIR)).replace(os.sep, "/"),
         "in": round(max(0.0, start or 0.0), 3), "out": round(min(dur, end if end else dur), 3), "duration": round(dur, 3),
         "gain": 0.0, "title": title or (a or {}).get("name", os.path.basename(p))}
    tl["clips"].append(c)
    return c


def from_film(film, upscaled=False):
    """A timeline of a film's active takes in order, each at its longest stretch without a cut."""
    tl = blank(film["name"])
    up = os.path.join(films.project_dir(film), "upscaled")
    for i, s in enumerate(film["shots"]):
        t = films.active_take(s)
        if not t or not s.get("part"):
            continue
        seg = os.path.join(up, f"part_{s['part']:03d}.mkv") if upscaled else films.part_files(film, s["part"])["segment"]
        if not os.path.isfile(seg):
            continue
        c = add_clip(tl, path=seg, title=s.get("title") or f"shot {i + 1}")
        w = (t.get("checks") or {}).get("window") or {}
        if w and not w.get("whole") and not upscaled and w.get("out", 0) - w.get("in", 0) > 1.0:
            c["in"], c["out"] = w["in"], w["out"]
    return tl


# ---------------------------------------------------------------------------------------- the export
def _frame_round(t, fps):
    return round(round(t * fps) / fps, 6)


def measure(path, start, end):
    """Integrated loudness of a stretch of a clip (LUFS), or None when it has no sound."""
    r = subprocess.run(["ffmpeg", "-nostats", "-ss", f"{start}", "-t", f"{max(0.05, end - start)}", "-i", path, "-af", "ebur128",
                        "-vn", "-f", "null", "-"], capture_output=True, text=True)
    got = re.findall(r"I:\s*(-?[\d.]+) LUFS", r.stderr)
    return float(got[-1]) if got else None


def match_gains(levels):
    """dB to add to each clip so the ones with speech sit at their common level. Quiet clips (ambience) are left alone."""
    loud = sorted(x for x in levels if x is not None and x > SPEECH_FLOOR)
    if len(loud) < 2:
        return [0.0] * len(levels)
    mid = len(loud) // 2
    target = loud[mid] if len(loud) % 2 else (loud[mid - 1] + loud[mid]) / 2          # the median
    return [round(max(-MAX_DOWN, min(MAX_UP, target - x)), 2) if (x is not None and x > SPEECH_FLOOR) else 0.0 for x in levels]


def timeline_srt(tl, clips, language="en"):
    """Captions of the whole cut from each clip's own transcript, shifted to where the clip sits. None without Whisper."""
    cues, offset = [], float(tl["title"]["seconds"]) if (tl["title"].get("text") or "").strip() else 0.0
    for c, path in clips:
        heard = checks.transcribe(path, language)
        if heard is None:
            return None
        for seg in heard.get("segments", []):
            a, b = max(seg["start"], c["in"]), min(seg["end"], c["out"])
            if b - a > 0.15 and seg["text"].strip():
                cues.append({"start": offset + a - c["in"], "end": offset + b - c["in"], "text": seg["text"].strip(), "words": []})
        offset += c["out"] - c["in"]
    return checks.srt({"segments": cues})


def font_file():
    try:
        r = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 and os.path.isfile(r.stdout.strip()) else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _esc(text):
    """Text for ffmpeg's drawtext."""
    return (text or "").replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")


def card(text, sub, w, h, fps, seconds, label):
    """A title card as a filter chain: [label_v] and [label_a]."""
    font = font_file()
    v = f"color=c=black:s={w}x{h}:r={fps}:d={seconds}"
    if font and text:
        v += (f",drawtext=fontfile='{font}':text='{_esc(text)}':fontcolor=white:fontsize={int(h * 0.075)}:"
              f"x=(w-text_w)/2:y=(h-text_h)/2-{int(h * 0.04)}:alpha='min(1,t/0.6)'")
        if sub:
            v += (f",drawtext=fontfile='{font}':text='{_esc(sub)}':fontcolor=0xBBBBBB:fontsize={int(h * 0.038)}:"
                  f"x=(w-text_w)/2:y=(h/2)+{int(h * 0.05)}:alpha='min(1,t/0.9)'")
    return f"{v},format=yuv420p[{label}_v];anullsrc=r=48000:cl=stereo,atrim=0:{seconds}[{label}_a]"


def build_export(tl, out, clips, gains, srt_path=None, crf=16, audio_only_probe=None):
    """The ffmpeg command for a timeline. clips = [(clip, path, probe)]."""
    first = clips[0][2]
    w = int(tl.get("width") or first["width"]) // 2 * 2
    h = int(tl.get("height") or first["height"]) // 2 * 2
    fps = float(tl.get("fps") or first.get("fps") or 24)
    cmd, filt, pads = ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"], [], []
    total = 0.0
    title = (tl["title"].get("text") or "").strip()
    if title:
        secs = float(tl["title"].get("seconds") or 3.0)
        filt.append(card(title, (tl["title"].get("subtitle") or "").strip(), w, h, fps, secs, "t"))
        pads.append("[t_v][t_a]")
        total += secs
    for i, (c, path, info) in enumerate(clips):
        cmd += ["-i", path]
        a, b = _frame_round(c["in"], fps), _frame_round(c["out"], fps)
        total += b - a
        filt.append(f"[{i}:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}]")
        g = float(c.get("gain") or 0.0) + gains[i]
        if info.get("has_audio"):
            filt.append(f"[{i}:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,"
                        f"volume={g:.2f}dB,apad=whole_dur={b - a:.6f},atrim=0:{b - a:.6f}[a{i}]")
        else:
            filt.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{b - a:.6f}[a{i}]")
        pads.append(f"[v{i}][a{i}]")
    n = len(pads)
    filt.append("".join(pads) + f"concat=n={n}:v=1:a=1[cv][ca]")
    vout, aout = "[cv]", "[ca]"
    if srt_path:
        esc = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filt.append(f"{vout}subtitles='{esc}':force_style='FontSize=18,Outline=1,Shadow=0,MarginV=28'[sv]")
        vout = "[sv]"
    music = os.path.join(config.OUTPUT_DIR, tl["music"]["path"]) if (tl.get("music") or {}).get("path") else ""
    if music and os.path.isfile(music):
        cmd += ["-stream_loop", "-1", "-i", music]
        m = len(clips)
        gain, duck = float(tl["music"].get("gain", -18.0)), float(tl["music"].get("duck", 12.0))
        ratio = max(1.5, min(20.0, 10 ** (duck / 20.0) * 1.5))
        fade = min(2.0, total / 4)
        off = float(tl["music"].get("offset") or 0.0)        # a cut on the beat starts the song at its first bar
        filt.append(f"[{m}:a]aresample=48000,aformat=channel_layouts=stereo,atrim={off:.3f}:{off + total:.3f},asetpts=PTS-STARTPTS,volume={gain:.1f}dB,"
                    f"afade=t=in:d={fade:.2f},afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.2f}[mus]")
        filt.append(f"{aout}asplit=2[dry][key]")
        filt.append(f"[mus][key]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:attack=15:release=450[duck]")
        filt.append("[dry][duck]amix=inputs=2:normalize=0:duration=first[mix]")
        aout = "[mix]"
    f = config.settings()["finish"]
    filt.append(f"{aout}loudnorm=I={float(tl.get('loudness') or f['loudness'])}:TP={f['true_peak']}:LRA=11,aresample=48000[final]")
    cmd += ["-filter_complex", ";".join(filt), "-map", vout, "-map", "[final]", "-c:v", "libx264", "-preset", "medium",
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", out]
    return cmd, total, (w, h, fps)


def run_progress(cmd, total, say):
    """Run an ffmpeg that prints -progress, telling `say(done seconds, total)`. Raises with ffmpeg's message."""
    import tempfile
    with tempfile.TemporaryFile("w+") as errf:                    # stderr to a file: a full pipe would stall ffmpeg
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True) as p:
            for line in p.stdout:
                m = re.match(r"out_time_ms=(\d+)", line)
                if m:
                    say(min(total, int(m.group(1)) / 1e6), total)
            code = p.wait()
        if code != 0:
            errf.seek(0)
            raise Refused("ffmpeg failed: " + (errf.read().strip().splitlines() or ["no message"])[-1][:400])


def resolve_clips(tl):
    out = []
    for c in tl["clips"]:
        path = clip_path(c)
        if not path or not os.path.isfile(path):
            raise Refused(f"a clip of this timeline is gone: {c.get('title') or c.get('path')}")
        info = checks.probe(path)
        if not info.get("has_video"):
            raise Refused(f"{c.get('title')} cannot be read")
        if c["out"] - c["in"] < 0.05:
            raise Refused(f"{c.get('title')}: the Out point is not after the In point")
        out.append((c, path, info))
    if not out:
        raise Refused("the timeline is empty")
    return out


@handler("cpu")
async def export(job, ctx):
    """Render a timeline to one MP4, with its FCPXML and EDL beside it. params: timeline, language"""
    tl = load(job["params"].get("timeline"))
    if not tl:
        raise Refused("no such timeline")
    clips = await ctx.thread(resolve_clips, tl)
    ctx.say("measuring levels")
    levels = [await ctx.thread(measure, path, c["in"], c["out"]) if info.get("has_audio") else None for c, path, info in clips]
    gains = match_gains(levels) if tl.get("match", True) else [0.0] * len(clips)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = config.home("exports", f"{config.slug(tl['name'], 'cut')}_{stamp}")
    srt_path, note = None, ""
    if tl.get("captions"):
        ctx.say("listening for the captions")
        text = await ctx.thread(timeline_srt, tl, [(c, p) for c, p, _ in clips],
                                checks.language_code(job["params"].get("language") or "English"))
        if text is None:
            note = "captions left out: openai-whisper is not installed"
        elif text.strip():
            srt_path = base + ".srt"
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(text)
    out = base + ".mp4"
    cmd, total, (w, h, fps) = build_export(tl, out, clips, gains, srt_path)
    await ctx.thread(run_progress, cmd, total, lambda a, b: ctx.say("rendering the cut", int(a), int(b) or 1))
    with open(base + ".fcpxml", "w", encoding="utf-8") as f:
        f.write(fcpxml(tl, clips, w, h, fps))
    with open(base + ".edl", "w", encoding="utf-8") as f:
        f.write(edl(tl, clips, fps))
    a = library.add(out, "export", name=tl["name"], timeline=tl["id"], job=job["id"],
                    levels=[x for x in levels], gains=gains)
    rel = lambda p: os.path.relpath(p, config.OUTPUT_DIR).replace(os.sep, "/")
    return {"asset": a["id"], "file": rel(out), "fcpxml": rel(base + ".fcpxml"), "edl": rel(base + ".edl"),
            "srt": rel(srt_path) if srt_path else "", "seconds": round(total, 2), "levels": levels, "gains": gains, "note": note}


# ---------------------------------------------------------------------------------------- for an editor
def _tc(seconds, fps):
    f = int(round(fps))
    n = int(round(seconds * f))
    return f"{n // (3600 * f):02d}:{n // (60 * f) % 60:02d}:{n // f % 60:02d}:{n % f:02d}"


def edl(tl, clips, fps):
    """The cut as a CMX 3600 edit decision list (one video track with its sound)."""
    lines = [f"TITLE: {tl['name']}", "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    for i, (c, path, _) in enumerate(clips, 1):
        d = c["out"] - c["in"]
        lines.append(f"{i:03d}  AX       AA/V  C        {_tc(c['in'], fps)} {_tc(c['out'], fps)} {_tc(rec, fps)} {_tc(rec + d, fps)}")
        lines.append(f"* FROM CLIP NAME: {os.path.basename(path)}")
        lines.append("")
        rec += d
    return "\n".join(lines)


def _rat(seconds, fps):
    f = int(round(fps))
    return f"{int(round(seconds * f))}/{f}s"


def fcpxml(tl, clips, w, h, fps, media=None):
    """The cut as FCPXML 1.9 (DaVinci Resolve: File > Import > Timeline). `media` maps a clip's path to another file,
    e.g. its ProRes copy."""
    media = media or {}
    q = sx.quoteattr
    res = [f'  <format id="r1" name="FFVideoFormat{h}p{int(round(fps))}" frameDuration="1/{int(round(fps))}s" width="{w}" height="{h}"/>']
    ids, spine, offset = {}, [], 0.0
    for c, path, info in clips:
        src = media.get(path, path)
        if src not in ids:
            ids[src] = f"r{len(ids) + 2}"
            res.append(f'  <asset id="{ids[src]}" name={q(os.path.basename(src))} start="0s" duration="{_rat(info["duration"], fps)}" '
                       f'hasVideo="1" hasAudio="{1 if info.get("has_audio") else 0}" format="r1" audioSources="1" audioChannels="2" audioRate="48000">\n'
                       f'   <media-rep kind="original-media" src={q("file://" + os.path.abspath(src))}/>\n  </asset>')
        d = c["out"] - c["in"]
        spine.append(f'     <asset-clip ref="{ids[src]}" name={q(c.get("title") or os.path.basename(src))} offset="{_rat(offset, fps)}" '
                     f'start="{_rat(c["in"], fps)}" duration="{_rat(d, fps)}" format="r1" tcFormat="NDF"/>')
        offset += d
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.9">\n <resources>\n' + "\n".join(res)
            + f'\n </resources>\n <library>\n  <event name="H3 Studio">\n   <project name={q(tl["name"])}>\n'
            f'    <sequence format="r1" duration="{_rat(offset, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n'
            '     <spine>\n' + "\n".join(spine) + '\n     </spine>\n    </sequence>\n   </project>\n  </event>\n </library>\n</fcpxml>\n')


def prores_cmd(src, dst):
    """ProRes 422 with PCM sound: what the free DaVinci Resolve on Linux can read."""
    return ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats", "-i", src, "-c:v", "prores_ks", "-profile:v", "2",
            "-pix_fmt", "yuv422p10le", "-vendor", "apl0", "-c:a", "pcm_s16le", "-ar", "48000", dst]


@handler("cpu")
async def resolve(job, ctx):
    """Media an editor can read. params: asset (one clip or export -> one .mov), or timeline (every clip as .mov plus
    an FCPXML and an EDL that point at them)."""
    p = job["params"]
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if p.get("asset"):
        a = library.get(p["asset"])
        if not a:
            raise Refused("no such clip")
        src = library.abs_path(a)
        dst = config.home("exports", f"{os.path.splitext(os.path.basename(src))[0]}_resolve_{stamp}.mov")
        info = checks.probe(src)
        need = int((info.get("duration") or 0) * (info.get("width") or 0) * (info.get("height") or 0) * (info.get("fps") or 24) * 0.33)
        free = shutil.disk_usage(os.path.dirname(dst)).free
        if need > free * 0.9:
            raise Refused(f"the ProRes copy needs about {need / 2 ** 30:.1f} GB and {free / 2 ** 30:.1f} GB is free")
        await ctx.thread(run_progress, prores_cmd(src, dst), info.get("duration") or 1,
                         lambda x, y: ctx.say("writing ProRes", int(x), int(y) or 1))
        new = library.add(dst, "export", name=a["name"] + " (ProRes)", made_from=a["id"], job=job["id"])
        return {"asset": new["id"], "file": new["path"]}
    tl = load(p.get("timeline"))
    if not tl:
        raise Refused("give a clip or a timeline")
    clips = await ctx.thread(resolve_clips, tl)
    root = config.home("exports", f"{config.slug(tl['name'], 'cut')}_resolve_{stamp}")
    os.makedirs(os.path.join(root, "media"), exist_ok=True)
    media = {}
    paths = list(dict.fromkeys(path for _, path, _ in clips))
    for n, src in enumerate(paths):
        ctx.check_cancel()
        dst = os.path.join(root, "media", f"{n + 1:03d}_{os.path.splitext(os.path.basename(src))[0]}.mov")
        info = checks.probe(src)
        await ctx.thread(run_progress, prores_cmd(src, dst), info.get("duration") or 1,
                         lambda x, y, n=n: ctx.say(f"ProRes {n + 1} of {len(paths)}", int(x), int(y) or 1))
        media[src] = dst
    first = clips[0][2]
    w, h, fps = int(tl.get("width") or first["width"]), int(tl.get("height") or first["height"]), float(tl.get("fps") or first.get("fps") or 24)
    with open(os.path.join(root, "timeline.fcpxml"), "w", encoding="utf-8") as f:
        f.write(fcpxml(tl, clips, w, h, fps, media))
    with open(os.path.join(root, "timeline.edl"), "w", encoding="utf-8") as f:
        f.write(edl(tl, [(c, media[path], i) for c, path, i in clips], fps))
    with open(os.path.join(root, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"{tl['name']}\n\nDaVinci Resolve: File > Import > Timeline > timeline.fcpxml (the media is in media/).\n"
                f"Project settings: {w}x{h}, {fps:g} frames a second.\nThe clips are ProRes 422 with PCM sound, which the free "
                "Resolve on Linux reads; H.264 with AAC it does not.\n")
    return {"folder": os.path.relpath(root, config.OUTPUT_DIR).replace(os.sep, "/"), "clips": len(paths)}


def detect_bars(path, samples=3):
    """(w, h, x, y) of the picture inside black bars, or None when there are none."""
    info = checks.probe(path)
    dur, crops = info.get("duration") or 0, {}
    for k in range(samples):
        at = dur * (k + 1) / (samples + 1)
        r = subprocess.run(["ffmpeg", "-nostats", "-ss", f"{at}", "-t", "2", "-i", path, "-vf", "cropdetect=limit=24:round=2:reset=0",
                            "-an", "-f", "null", "-"], capture_output=True, text=True)
        for m in re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr):
            crops[m] = crops.get(m, 0) + 1
    if not crops:
        return None
    w, h, x, y = map(int, max(crops, key=crops.get))
    if (w, h) == (info.get("width"), info.get("height")) or w < 64 or h < 64:
        return None
    return w, h, x, y


@handler("cpu")
async def conform(job, ctx):
    """Bring an editor's export back to a film's own size and to H.264 with AAC: black bars are cut off, the picture is
    scaled, the sound is kept. params: asset or path (under output/), width, height, fps (0 = keep)"""
    p = job["params"]
    a = library.get(p.get("asset") or "")
    src = library.abs_path(a) if a else os.path.join(config.OUTPUT_DIR, p.get("path") or "")
    if not os.path.isfile(src) or not config.inside(src, config.OUTPUT_DIR):
        raise Refused("give a clip from the Library, or a file under ComfyUI's output folder")
    info = checks.probe(src)
    w, h = int(p.get("width") or 0), int(p.get("height") or 0)
    if not (w and h):
        raise Refused("give the width and height to bring it back to")
    ctx.say("looking for black bars")
    bars = await ctx.thread(detect_bars, src)
    vf = (f"crop={bars[0]}:{bars[1]}:{bars[2]}:{bars[3]}," if bars else "") + f"scale={w}:{h}:flags=lanczos,format=yuv420p,setsar=1"
    dst = config.home("exports", f"{os.path.splitext(os.path.basename(src))[0]}_{w}x{h}_{time.strftime('%H%M%S')}.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf]
    if p.get("fps"):
        cmd += ["-r", str(p["fps"])]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "15", "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", dst]
    await ctx.thread(run_progress, cmd, info.get("duration") or 1, lambda x, y: ctx.say("encoding", int(x), int(y) or 1))
    new = library.add(dst, "export", name=(a or {}).get("name", os.path.basename(src)) + f" ({w}x{h})", job=job["id"],
                      made_from=(a or {}).get("id"))
    return {"asset": new["id"], "file": new["path"], "bars_removed": list(bars) if bars else None}


# ---------------------------------------------------------------------------------------- cut to the beat
def rough_cut(paths, song, mode="own", order="as_filmed", name="Rough cut"):
    """A timeline of clips cut on a song's beats. A clip is trimmed around its middle to fill its slot.

    paths  clip files (under output/), in film order    mode  own | bar | two_bars | beat    order  as_filmed | shuffled
    """
    import random as _random
    info = [(p, checks.probe(p)) for p in paths]
    info = [(p, i) for p, i in info if i.get("has_video")]
    if not info:
        raise ValueError("no clips to cut")
    if order == "shuffled":
        _random.Random(len(info)).shuffle(info)
    b = beats_mod.beats(song)
    grid = beats_mod.slots(b["beats"], [i["duration"] for _, i in info], mode, start=b["downbeats"][0] if b["downbeats"] else 0.0)
    tl = blank(name)
    tl["music"]["path"] = os.path.relpath(os.path.realpath(song), os.path.realpath(config.OUTPUT_DIR)).replace(os.sep, "/")
    tl["music"]["offset"] = grid[0][0] if grid else 0.0
    for (p, i), (a, z) in zip(info, grid):
        want = z - a
        dur = i["duration"]
        if want >= dur:
            start, end = 0.0, dur
        else:
            start = max(0.0, (dur - want) / 2)
            end = start + want
        add_clip(tl, path=p, start=start, end=end)
    tl["beats"] = {"bpm": b["bpm"], "mode": mode, "slots": len(grid), "clips_left_out": max(0, len(info) - len(grid))}
    return tl


# ---------------------------------------------------------------------------------------- dailies
def dailies_notes(film, takes, shift):
    lines = [f"# Dailies: {shift.get('name', film['name'])}", "",
             f"{len(takes)} take(s) rendered. " + (f"{sum(1 for _, _, t in takes if not (t.get('checks') or {}).get('ok'))} to look at first." if takes else ""), ""]
    if shift.get("run_stopped"):
        lines += [f"The run stopped early: {shift['run_stopped']}", ""]
    bad = [x for x in takes if not (x[2].get("checks") or {}).get("ok")]
    good = [x for x in takes if (x[2].get("checks") or {}).get("ok")]
    for head, group in (("Look at these first", bad), ("Passed the automatic checks", good)):
        if group:
            lines += [f"## {head}", ""]
            for i, s, t in group:
                lines.append(f"- **Shot {i + 1}{': ' + s['title'] if s.get('title') else ''}**, take {t['n']}, seed {t['seed']}: "
                             f"{(t.get('checks') or {}).get('summary', '')}")
            lines.append("")
    lines += ["The automatic checks see cuts, a jump at a join, wrong or unwanted speech and shouted lines. They do not see a "
              "wrong prop or a person in the wrong place: watch the reel.", ""]
    return "\n".join(lines)


@handler("cpu")
async def dailies(job, ctx):
    """A reel of every take a night shift made, each after a title card, and notes on what the checks found.
    params: shift (id), or film + since (timestamp)"""
    p = job["params"]
    shift = config.read_json(config.home("nightshift", str(p.get("shift")) + ".json")) if p.get("shift") else {}
    film = films.load((shift or {}).get("film") or p.get("film"))
    if not film:
        raise Refused("no such film")
    since = float((shift or {}).get("started") or p.get("since") or 0)
    takes = []
    for i, s in enumerate(film["shots"]):
        for t in s.get("takes", []):
            if t.get("time", 0) >= since and t.get("preview") and os.path.isfile(os.path.join(config.OUTPUT_DIR, t["preview"])):
                takes.append((i, s, t))
    stamp = time.strftime("%Y%m%d_%H%M")
    base = config.home("dailies", f"{stamp}_{config.slug(film['name'], 'film')}")
    notes = dailies_notes(film, takes, shift or {"name": film["name"]})
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(notes)
    out = {"notes": os.path.relpath(base + ".md", config.OUTPUT_DIR).replace(os.sep, "/"), "takes": len(takes)}
    if takes:
        w, h, fps = 1280, 720, 24
        cmd, filt, pads = ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats"], [], []
        total = 0.0
        for k, (i, s, t) in enumerate(takes):
            ok = (t.get("checks") or {}).get("ok")
            filt.append(card(f"Shot {i + 1}  {s.get('title', '')}".strip(), f"take {t['n']}   seed {t['seed']}   "
                             + ("passed" if ok else "to look at"), w, h, fps, 1.5, f"c{k}"))
            pads.append(f"[c{k}_v][c{k}_a]")
            cmd += ["-i", os.path.join(config.OUTPUT_DIR, t["preview"])]
            d = float(t.get("duration") or 0)
            filt.append(f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},"
                        f"format=yuv420p,setsar=1[v{k}];[{k}:a]aresample=48000,aformat=channel_layouts=stereo[a{k}]")
            pads.append(f"[v{k}][a{k}]")
            total += 1.5 + d
        filt.append("".join(pads) + f"concat=n={len(pads)}:v=1:a=1[v][a]")
        reel = base + ".mp4"
        cmd += ["-filter_complex", ";".join(filt), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", reel]
        await ctx.thread(run_progress, cmd, total, lambda x, y: ctx.say("cutting the reel", int(x), int(y) or 1))
        a = library.add(reel, "export", name=f"Dailies · {film['name']} · {time.strftime('%d %b %H:%M')}", film=film["id"],
                        film_name=film["name"], job=job["id"])
        out.update(reel=a["path"], asset=a["id"])
    if shift:
        shift.update(status="done", finished=time.time(), dailies=out)
        config.write_json(config.home("nightshift", shift["id"] + ".json"), shift)
        if shutil.which("notify-send"):
            bad = sum(1 for _, _, t in takes if not (t.get("checks") or {}).get("ok"))
            subprocess.run(["notify-send", "H3 Studio", f"Night shift done: {len(takes)} take(s), {bad} to look at"], capture_output=True)
    return out
