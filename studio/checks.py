"""What the studio measures on a finished clip, and the verdict it draws from it.

The same checks the story kit grew in real runs, one function each, all on ffmpeg and (for speech) Whisper:

  cuts      a hard cut inside a part: an isolated jump in the frame-to-frame difference (64x36 gray, 0-255) above 30.
            Fast tracking shots sit at 12-25 from motion alone.
  window    the longest stretch without a cut, as a suggestion where to trim.
  join      a continuation whose first frame is unlike the last frame of the part before: H3 swapped the background
            without a visible cut. Good joins measured 1-9, swapped backgrounds 29 and 44.
  speech    Whisper's transcript against the script (word match, 0-1). A part without lines must stay without words.
  loudness  the loudest moment WHILE SOMEONE SPEAKS (EBU R128 momentary), against the same number of the film's other
            approved parts: a part more than 2.5 dB above their median fails. In the film this was learned on, normal
            lines peaked at -23 to -26 LUFS and shouted ones at -15 to -19, about 3 dB above the median. An absolute
            limit does not travel: a calm talking head in another film came out at -9 and -14. So without three parts
            to compare with, a hot part is a note, not a fail. An engine roar after the last word is not a shouted line:
            sound outside the words is ignored.
  keyframe  a clip that was given a first frame should open on it.

A check whose tool is missing is "skip", never "fail". Every number is in the report so a person can overrule it.
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

from . import config, lengths

FPS = lengths.FPS
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
           "eighteen nineteen twenty").split()
# Whisper writes these on music and crowd noise: not speech
HALLUCINATION = (r"(?:thanks?(?: you)?(?: so much)? for watching|thank you|please subscribe|subscribe to (?:my|the) channel|"
                 r"you|bye|music|applause|\W*)[.!?]*")
WHISPER_LANG = {"english": "en", "dutch": "nl", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
                "portuguese": "pt", "japanese": "ja", "korean": "ko", "chinese": "zh", "russian": "ru", "polish": "pl",
                "turkish": "tr", "swedish": "sv", "norwegian": "no", "danish": "da"}


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def have_ffmpeg():
    try:
        return _run(["ffmpeg", "-version"]).returncode == 0
    except OSError:
        return False


def probe(path):
    """{duration, width, height, fps, frames, has_audio, has_video}; empty dict when ffprobe cannot read the file."""
    r = _run(["ffprobe", "-v", "error", "-show_entries",
              "format=duration:stream=codec_type,width,height,r_frame_rate,nb_frames,duration", "-of", "json", path])
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {}
    if r.returncode != 0 or not data.get("streams"):
        return {}
    out = {"duration": float(data.get("format", {}).get("duration") or 0), "has_audio": False, "has_video": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            out["has_audio"] = True
        elif s.get("codec_type") == "video" and not out["has_video"]:
            out["has_video"] = True
            out["width"], out["height"] = int(s.get("width") or 0), int(s.get("height") or 0)
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            out["fps"] = round(float(num) / float(den or 1), 3) if float(den or 1) else 0.0
            if str(s.get("nb_frames", "")).isdigit():
                out["frames"] = int(s["nb_frames"])
    if out.get("has_video") and "frames" not in out and out.get("fps"):
        out["frames"] = int(round(out["duration"] * out["fps"]))
    return out


def frame_diffs(path):
    """Mean difference between each frame and the one before it (64x36 gray, 0-255)."""
    r = _run(["ffmpeg", "-v", "error", "-i", path, "-vf",
              "scale=64:36,format=gray,tblend=all_mode=difference,signalstats,"
              "metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"])
    return [float(x) for x in re.findall(r"YAVG=([\d.]+)", r.stdout)]


def _small_frames(path, start=0.0, dur=None, w=32, h=18, fps=2):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", path] + (["-t", f"{dur:.3f}"] if dur else []) + \
          ["-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    b = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    n = w * h * 3
    return [b[i:i + n] for i in range(0, len(b) - n + 1, n)]


BLOCKOUT_LOOK = 12.0          # median colour difference (0-255) from the blockout below which a take is still the blockout


def blockout_likeness(path, blockout_path, start=0.0):
    """How far a take is from the blockout it follows: the median mean colour difference of small frames at the same
    moments (0-255). Real takes measured 23-35; one that stayed the grey blockout with headlights 4.5 (2026-11-15)."""
    t = _small_frames(path)
    b = _small_frames(blockout_path, start, len(t) / 2 + 1)
    d = sorted(sum(abs(x - y) for x, y in zip(a, c)) / len(a) for a, c in zip(t, b))
    return d[len(d) // 2] if d else None


def cuts_from(diffs, threshold=30.0, fps=FPS):
    """[(seconds, value)] for every frame-to-frame jump above the threshold."""
    return [((i + 1) / fps, v) for i, v in enumerate(diffs) if v > threshold]


def find_cuts(path, threshold=30.0, fps=FPS):
    return cuts_from(frame_diffs(path), threshold, fps)


def window_from(diffs, threshold=30.0, fps=FPS):
    """The longest stretch without a cut: {"start", "end"} frames (end exclusive) and {"in", "out"} seconds."""
    total = len(diffs) + 1
    edges = [0] + [i + 1 for i, v in enumerate(diffs) if v > threshold] + [total]
    start, end = max(zip(edges, edges[1:]), key=lambda se: se[1] - se[0])
    return {"start": start, "end": end, "in": round(start / fps, 3), "out": round(end / fps, 3), "frames": end - start,
            "whole": start == 0 and end == total}


def describe_cuts(cuts):
    if not cuts:
        return "no cuts"
    return f"{len(cuts)} cut(s) at " + ", ".join(f"{t:.1f}s ({v:.0f})" for t, v in cuts)


def grab(path, out, at=None, from_end=None, size=None):
    """One frame of a clip as an image. at = seconds from the start, from_end = seconds before the end."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if from_end is not None:
        cmd += ["-sseof", f"-{from_end}"]
    elif at:
        cmd += ["-ss", f"{at}"]
    cmd += ["-i", path, "-frames:v", "1"]
    if size:
        cmd += ["-vf", f"scale={size[0]}:{size[1]}"]
    cmd.append(out)
    return _run(cmd).returncode == 0 and os.path.isfile(out)


def last_frame(path, out):
    """The very last frame, at full size (the frame a continuation or an Extend starts from)."""
    d = probe(path)
    fps = d.get("fps") or FPS
    return grab(path, out, from_end=max(1.0 / fps * 1.2, 0.05))


def image_diff(a, b, size=(320, 180)):
    """Mean difference of two pictures, 0-255, the way the join check measures it (ffmpeg blend=difference, YAVG)."""
    r = _run(["ffmpeg", "-v", "error", "-i", a, "-i", b, "-filter_complex",
              f"[0]scale={size[0]}:{size[1]}[a];[1]scale={size[0]}:{size[1]}[b];"
              "[a][b]blend=all_mode=difference,signalstats,metadata=print:file=-", "-f", "null", "-"])
    m = re.search(r"YAVG=([\d.]+)", r.stdout)
    return float(m.group(1)) if m else None


def join_diff(prev_path, cur_path):
    """Last frame of the part before against the first frame of this one (0-255). None when a frame cannot be read."""
    with tempfile.TemporaryDirectory(dir=config.home("tmp")) as tmp:
        a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
        if not (grab(prev_path, a, from_end=0.05, size=(320, 180)) and grab(cur_path, b, size=(320, 180))):
            return None
        return image_diff(a, b)


def keyframe_diff(clip_path, picture, which="first"):
    """How far the clip's first (or last) frame is from the picture it was given, 0-255."""
    with tempfile.TemporaryDirectory(dir=config.home("tmp")) as tmp:
        f = os.path.join(tmp, "f.png")
        ok = grab(clip_path, f, size=(320, 180)) if which == "first" else grab(clip_path, f, from_end=0.05, size=(320, 180))
        return image_diff(f, picture) if ok else None


def loudness(path):
    """EBU R128: {"integrated", "max_momentary", "timeline": [[t, M], ...] at 10 values a second}. None without sound."""
    r = _run(["ffmpeg", "-nostats", "-i", path, "-af", "ebur128", "-vn", "-f", "null", "-"])
    tl = [[float(t), float(m)] for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+)", r.stderr)]
    if not tl:
        return None
    integ = re.findall(r"I:\s*(-?[\d.]+) LUFS", r.stderr)
    real = [m for _, m in tl if m > -100]
    return {"integrated": float(integ[-1]) if integ else None, "max_momentary": max(real) if real else -120.0, "timeline": tl}


def loudest_during(timeline, spans, pad=0.15, window=0.4):
    """The loudest momentary value while a span is on. A momentary value at time t covers the 0.4 s before t."""
    best = None
    for t, m in timeline:
        if m <= -100:
            continue
        if any(a - pad <= t <= b + pad + window for a, b in spans):
            best = m if best is None else max(best, m)
    return best


def contact_sheet(path, out, fps=2.0, cols=10, width=320):
    """Frames of a clip on one sheet, `fps` a second."""
    d = probe(path)
    n = max(1, int((d.get("duration") or 0) * fps))
    rows = max(1, -(-n // cols))
    r = _run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", f"fps={fps},scale={width}:-1,tile={cols}x{rows}",
              "-frames:v", "1", "-q:v", "4", out])
    return r.returncode == 0 and os.path.isfile(out)


def identity_sheet(path, out, height=360):
    """Three frames side by side (1 s in, the middle, 1 s before the end): is it the same face, hair and clothes?"""
    d = probe(path)
    dur = d.get("duration") or 0
    if dur <= 0:
        return False
    times = [min(1.0, dur * 0.1), dur / 2, max(dur - 1.0, dur * 0.9)]
    with tempfile.TemporaryDirectory(dir=config.home("tmp")) as tmp:
        parts = []
        for i, t in enumerate(times):
            f = os.path.join(tmp, f"{i}.png")
            if grab(path, f, at=t):
                parts.append(f)
        if len(parts) < 2:
            return False
        cmd = ["ffmpeg", "-v", "error", "-y"]
        for f in parts:
            cmd += ["-i", f]
        scaled = "".join(f"[{i}]scale=-2:{height}[s{i}];" for i in range(len(parts)))
        cmd += ["-filter_complex", scaled + "".join(f"[s{i}]" for i in range(len(parts))) + f"hstack=inputs={len(parts)}",
                "-q:v", "3", out]
        return _run(cmd).returncode == 0


def thumbnail(path, out, width=480, at=1.0):
    """A small jpg of a picture or of a clip's frame."""
    if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        try:
            from PIL import Image
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((width, width * 4))
                im.save(out, "JPEG", quality=82)
            return True
        except Exception:
            return False
    d = probe(path)
    if not d.get("has_video"):
        return False
    t = min(at, max(0.0, (d.get("duration") or 0) / 2))
    return _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2",
                 "-q:v", "5", out]).returncode == 0


# ---------------------------------------------------------------- speech
def words(text):
    """Lower-case words; Whisper writes numbers as digits ("3, 2, 1"), so 0-20 become words like in a script."""
    return [NUMBERS[int(w)] if w.isdigit() and int(w) <= 20 else w for w in re.findall(r"[a-z0-9']+", (text or "").lower())]


def speech_match(lines, heard):
    """Word match between the script and what was heard, 0-1."""
    want = words(" ".join((ln.get("text", "") if isinstance(ln, dict) else ln[1]) for ln in lines))
    return difflib.SequenceMatcher(None, want, words(heard)).ratio()


def language_code(language):
    lang = (language or "en").strip().lower()
    return WHISPER_LANG.get(lang, lang if len(lang) <= 3 else "en")


def whisper_available():
    """Is openai-whisper importable by the Python that runs the studio? (ComfyUI's venv usually has it.)"""
    import importlib.util
    return importlib.util.find_spec("whisper") is not None


def transcribe(path, language="en", model=None, timeout=900):
    """Whisper on a clip's sound, in a process of its own so the GPU stays with the render (cpu by default).

    Returns {"text", "segments": [{"start", "end", "text", "no_speech_prob", "words": [{"start", "end", "word"}]}]},
    or None when Whisper is not installed. The result is kept under library/words/ and reused while the file is unchanged.
    """
    c = config.settings()["checks"]
    model = model or c["whisper_model"]
    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.realpath(path)}|{st.st_mtime_ns}|{st.st_size}|{model}|{language}".encode()).hexdigest()
    cache = config.home("library", "words", key + ".json")
    got = config.read_json(cache)
    if got is not None:
        return got
    if not whisper_available():
        return None
    env = dict(os.environ)
    if c.get("whisper_device", "cpu") == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    cmd = [sys.executable, "-m", "studio.whisper_worker", path, "--model", model, "--lang", language]
    if config.whisper_dir():
        cmd += ["--dir", config.whisper_dir()]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=config.REPO, env=env, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("Whisper failed: " + (r.stderr.strip().splitlines() or ["no message"])[-1][:300])
    got = json.loads(r.stdout[r.stdout.index("{"):])
    config.write_json(cache, got)
    return got


def sure_speech(result, nsp=0.5):
    """Text of the segments Whisper is fairly sure are speech, hallucinated sign-offs left out."""
    return " ".join(s["text"].strip() for s in result.get("segments", [])
                    if s.get("no_speech_prob", 0) < nsp and not re.fullmatch(HALLUCINATION, s["text"].strip().lower()))


def word_spans(result):
    out = []
    for s in result.get("segments", []):
        ws = s.get("words") or []
        if ws:
            out += [(w["start"], w["end"]) for w in ws]
        else:
            out.append((s["start"], s["end"]))
    return out


def srt(result, max_chars=42):
    """A transcript as SubRip text, one line per segment (long segments split on word times)."""
    def stamp(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    cues = []
    for s in result.get("segments", []):
        ws = s.get("words") or []
        if not ws or len(s["text"].strip()) <= max_chars:
            cues.append((s["start"], s["end"], s["text"].strip()))
            continue
        cur, start = [], None
        for w in ws:
            start = w["start"] if start is None else start
            cur.append(w["word"].strip())
            if len(" ".join(cur)) >= max_chars - 8:
                cues.append((start, w["end"], " ".join(cur)))
                cur, start = [], None
        if cur:
            cues.append((start, ws[-1]["end"], " ".join(cur)))
    return "".join(f"{i}\n{stamp(a)} --> {stamp(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues, 1) if t)


# ---------------------------------------------------------------- the report
def _item(name, status, text, **data):
    return {"name": name, "status": status, "text": text, **data}


def review(path, *, lines=None, continuation=False, prev_path=None, first_picture=None, last_picture=None,
           language="English", asks_for_cut=False, do_speech=True, thresholds=None, loud_reference=None,
           blockout=False, blockout_cuts=(), blockout_file="", blockout_start=0.0):
    """Run every check that applies to one clip. Returns {"ok", "checks": [...], "summary", "window", ...}.

    ok is False only when a check FAILED; skipped checks and notes leave it True.
    """
    th = {**config.settings()["checks"], **(thresholds or {})}
    lines = lines or []
    items = []
    info = probe(path)
    if not info.get("has_video"):
        return {"ok": False, "checks": [_item("file", "fail", "the clip cannot be read")], "summary": "the clip cannot be read"}
    fps = info.get("fps") or FPS

    diffs = frame_diffs(path)
    cuts = cuts_from(diffs, th["cut"], fps)
    window = window_from(diffs, th["cut"], fps)
    if asks_for_cut:
        items.append(_item("cuts", "note", describe_cuts(cuts) + " (the prompt asks for a cut)", cuts=cuts))
    elif blockout and cuts:
        # a clip that follows a blockout cuts where the blockout does: those are wanted. Others are only noted, since a
        # blockout's own sudden moves (a close pass, a whip) can read as a cut too.
        wanted = [t for t, _ in cuts if any(abs(t - b) <= 1.0 for b in blockout_cuts)]
        other = [(t, v) for t, v in cuts if t not in wanted]
        hard = [(t, v) for t, v in other if v >= 2 * th["cut"]]
        if not other:
            items.append(_item("cuts", "pass", describe_cuts(cuts) + ": where the blockout cuts", cuts=cuts))
        elif hard:
            # far above the threshold and nowhere near a cut of the blockout: a real cut (seen: a 2 s insert of a
            # character's face reference on its white background at the end of a blocked drive part, jump 139)
            items.append(_item("cuts", "fail", describe_cuts(hard) + " where the blockout does not cut", cuts=cuts))
        else:
            items.append(_item("cuts", "note", describe_cuts(other) + (" where the blockout does not cut" if blockout_cuts else
                               " (it follows a blockout, so a cut can be the blockout's own)")
                               + (f"; {len(wanted)} more where it does" if wanted else ""), cuts=cuts))
    elif cuts:
        items.append(_item("cuts", "fail", describe_cuts(cuts) + f"; the longest stretch without one is "
                           f"{window['in']:.1f}-{window['out']:.1f} s", cuts=cuts))
    else:
        items.append(_item("cuts", "pass", "no cuts", cuts=[]))

    if blockout_file and os.path.isfile(blockout_file):
        like = blockout_likeness(path, blockout_file, blockout_start)
        if like is None:
            items.append(_item("blockout look", "skip", "could not be compared with the blockout"))
        elif like < BLOCKOUT_LOOK:
            items.append(_item("blockout look", "fail", f"it still looks like the grey blockout (difference {like:.0f}, a real "
                               f"take is over {BLOCKOUT_LOOK:.0f}): render it again with a higher blockout strength, e.g. 0.9995"))
        else:
            items.append(_item("blockout look", "pass", f"painted over the blockout (difference {like:.0f})"))

    if continuation and prev_path and os.path.isfile(prev_path):
        j = join_diff(prev_path, path)
        if j is None:
            items.append(_item("join", "skip", "the join could not be measured"))
        elif j > th["join"]:
            items.append(_item("join", "fail", f"the picture jumps at the join with the part before (difference {j:.0f}, good "
                               f"joins are under 10): the background was swapped. Start the prompt with what is in view at the "
                               f"end of the part before.", value=round(j, 2)))
        else:
            items.append(_item("join", "pass", f"join with the part before {j:.1f}", value=round(j, 2)))

    for which, pic in (("first", first_picture), ("last", last_picture)):
        if pic and os.path.isfile(pic):
            k = keyframe_diff(path, pic, which)
            if k is None:
                items.append(_item(f"{which}-frame", "skip", f"the {which} frame could not be compared"))
            else:
                items.append(_item(f"{which}-frame", "pass" if k <= 12 else "note",
                                   f"{which} frame {'held' if k <= 12 else 'not held'} ({k:.1f} grey levels from the picture)",
                                   value=round(k, 2)))

    loud = loudness(path) if info.get("has_audio") else None
    heard = None
    if not info.get("has_audio"):
        items.append(_item("speech", "skip", "the clip has no sound"))
    elif not do_speech:
        items.append(_item("speech", "skip", "speech was not checked"))
    else:
        try:
            heard = transcribe(path, language_code(language))
        except Exception as e:      # a broken Whisper install must not fail the clip
            items.append(_item("speech", "skip", f"speech not checked: {e}"))
        else:
            if heard is None:
                items.append(_item("speech", "skip", "speech not checked: openai-whisper is not installed in this Python "
                                   "(use ComfyUI's venv)"))
            elif lines:
                score = speech_match(lines, heard["text"])
                ok = score >= th["speech_min"]
                items.append(_item("speech", "pass" if ok else "fail",
                                   f"speech match {score:.2f}" + ("" if ok else f" (needs {th['speech_min']:.2f})")
                                   + f"; heard: {heard['text'].strip() or '(nothing)'}", score=round(score, 3), heard=heard["text"].strip()))
            else:
                said = sure_speech(heard, th["nsp"])
                if len(words(said)) >= 2:
                    items.append(_item("speech", "fail", f"someone speaks in a part without lines: {said}", heard=said))
                else:
                    items.append(_item("speech", "pass", "no speech, as scripted", heard=""))

    if loud:
        spans = word_spans(heard) if (heard and lines) else []
        m = loudest_during(loud["timeline"], spans) if spans else None
        aside = f"; the loudest moment ({loud['max_momentary']:.1f}) is not speech" if (m is not None and loud["max_momentary"] > m + 1.5) else ""
        ref = sorted(x for x in (loud_reference or []) if x is not None)
        if m is None:
            items.append(_item("loudness", "pass", f"loudest moment {loud['max_momentary']:.1f} LUFS"
                               + (" (not compared with the words: no transcript)" if lines else ""), value=loud["max_momentary"]))
        elif len(ref) >= 3:
            mid = len(ref) // 2
            median = ref[mid] if len(ref) % 2 else (ref[mid - 1] + ref[mid]) / 2
            over = m - median
            if over > th["loud_over"]:
                items.append(_item("loudness", "fail", f"speech peaks at {m:.1f} LUFS, {over:.1f} dB above this film's other parts "
                                   f"(their median is {median:.1f}): a shouted line, or a part recorded hot. For a shouted line: a "
                                   "full stop and \"at a normal speaking volume\".", value=m, speech=True, over=round(over, 1)))
            else:
                items.append(_item("loudness", "pass", f"speech peaks at {m:.1f} LUFS ({over:+.1f} dB against this film's other parts)" + aside,
                                   value=m, speech=True, over=round(over, 1)))
        elif m > th["loud"]:
            items.append(_item("loudness", "note", f"speech peaks at {m:.1f} LUFS. In one film normal lines peaked at -23 to -26 and shouted "
                               f"ones at -15 to -19, but the level also differs from clip to clip: listen to it. (With three approved "
                               f"parts with speech, a part is compared with its own film.)" + aside, value=m, speech=True))
        else:
            items.append(_item("loudness", "pass", f"speech peaks at {m:.1f} LUFS" + aside, value=m, speech=True))

    failed = [i for i in items if i["status"] == "fail"]
    summary = "; ".join(re.split(r"[;:](?![^(]*\))", i["text"])[0] for i in failed) if failed else \
        "passed: " + ", ".join(i["name"] for i in items if i["status"] == "pass")
    return {"ok": not failed, "checks": items, "summary": summary, "window": window, "duration": info.get("duration"),
            "width": info.get("width"), "height": info.get("height"), "fps": fps,
            "integrated": loud["integrated"] if loud else None,
            "words": [w for s in (heard or {}).get("segments", []) for w in (s.get("words") or [])] if heard else []}
