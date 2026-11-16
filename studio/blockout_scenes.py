"""Blockouts on their own, outside a film: a scene made in the Blockout room's 3D editor (or written by Claude Code from
a few words), rendered in Blender into a video that a clip can follow (Video → full form → A blockout video).

One JSON file per blockout in blockout_scenes/<id>.json:
{id, name, idea, size: "WxH", scene (as edited, may not be valid yet), created, updated,
 video (loader ref of the last render), asset (its Library id), made (signature of what it was made from), stats}.
The scene format is the films' (blockouts.normalize): nothing in it is ever run as code.
"""
import json
import os
import shutil
import threading
import time
import uuid

from . import blockouts, config

_lock = threading.RLock()
SIZES = ("1152x640", "640x1152", "1024x1024", "1280x704", "832x480", "480x832")


def _dir():
    d = config.home("blockout_scenes")
    os.makedirs(d, exist_ok=True)
    return d


def _path(bid):
    if not bid or not all(c.isalnum() for c in bid):
        raise KeyError("blockout")
    return os.path.join(_dir(), bid + ".json")


def starter():
    """A scene to start from: a street, one person walking toward the camera, a camera that slowly pulls back."""
    return {"sky": "day", "ground": "asphalt",
            "set": [{"type": "street", "name": "street", "at": [-60, 0, 0], "size": [140, 12, 12], "turn": 0, "color": "brick"}],
            "things": [{"name": "Walker", "kind": "person", "color": "blue", "scale": 1,
                        "keys": [{"t": 0, "at": [14, 1, 0], "face": None, "pose": "walk"}, {"t": 8, "at": [4, 1, 0], "face": None, "pose": "walk"}]}],
            "camera": {"lens": 35, "shake": 0,
                       "keys": [{"t": 0, "at": [8, 0, 1.6], "look_at": [0, 0, 0], "follow": "Walker", "lens": 0, "cut": False},
                                {"t": 8, "at": [-2, 0, 1.7], "look_at": [0, 0, 0], "follow": "Walker", "lens": 0, "cut": False}]}}


def load(bid):
    b = config.read_json(_path(bid))
    if not b:
        raise KeyError("blockout")
    return b


def size_of(b):
    w, h = (int(x) for x in (b.get("size") or SIZES[0]).split("x"))
    return w, h


def state(b):
    """{"error", "frames", "seconds", "current", "small", "blender"}: is the scene valid, how long it runs, and is the
    last render made from the scene as it is now."""
    out = {"error": "", "frames": 0, "seconds": 0, "current": False, "small": blockouts.too_small(b.get("stats")),
           "blender": bool(blockouts.blender())}
    try:
        scene = blockouts.normalize(b.get("scene"))
    except blockouts.BadScene as e:
        out["error"] = str(e)
        return out
    out["frames"] = max(blockouts.scene_frames(scene), 24)
    out["seconds"] = round(out["frames"] / 24, 1)
    w, h = size_of(b)
    out["current"] = bool(b.get("video")) and b.get("made") == blockouts.signature(scene, out["frames"], w, h)
    return out


def view(b):
    return {**b, "state": state(b)}


def all_of():
    out = []
    for name in os.listdir(_dir()):
        if name.endswith(".json"):
            b = config.read_json(os.path.join(_dir(), name))
            if b:
                out.append({k: b.get(k) for k in ("id", "name", "idea", "size", "updated", "video", "asset")}
                           | {"things": len((b.get("scene") or {}).get("things") or []) if isinstance(b.get("scene"), dict) else 0})
    out.sort(key=lambda b: b.get("updated") or 0, reverse=True)
    return out


def create(name="", scene=None, idea="", size=""):
    b = {"id": "bo" + uuid.uuid4().hex[:10], "name": (name or "").strip()[:80] or "Untitled blockout", "idea": (idea or "")[:4000],
         "size": size if size in SIZES else SIZES[0], "scene": scene if scene is not None else starter(),
         "created": time.time(), "updated": time.time(), "video": "", "asset": "", "made": "", "stats": None}
    with _lock:
        config.write_json(_path(b["id"]), b)
    return b


def save(bid, d, blender=False, why=""):
    """Change name, idea, size and/or scene. The scene is kept as sent (the editor shows what is wrong with it).
    blender: the scene came back from Blender (the open editor picks it up by blender_at).
    why: what changed it ("words", "Blender", "restore"); the scene it replaces is kept as an earlier version."""
    with _lock:
        b = load(bid)
        if "name" in d:
            b["name"] = str(d.get("name") or "").strip()[:80] or b["name"]
        if "idea" in d:
            b["idea"] = str(d.get("idea") or "")[:4000]
        if d.get("size") in SIZES:
            b["size"] = d["size"]
        if "scene" in d:
            if not isinstance(d["scene"], (dict, str)):
                raise ValueError("the scene is an object")
            if len(str(d["scene"])) > 400_000:
                raise ValueError("the scene is too big")
            if d["scene"] != b.get("scene"):
                _keep_version(bid, b.get("scene"), d["scene"], why)
            b["scene"] = d["scene"]
        b["updated"] = time.time()
        if blender:
            b["blender_at"] = b["updated"]
        config.write_json(_path(bid), b)
        return b


KEEP = 60                    # earlier versions kept per blockout
EVERY = 120                  # s: edits closer together than this are one version (a drag saves many times)


def _vdir(bid):
    return os.path.join(_dir(), "versions", bid)


def _count(scene):
    return (len(scene.get("things") or []), len(scene.get("set") or [])) if isinstance(scene, dict) else (0, 0)


def _keep_version(bid, old, new, why):
    """Keep the scene that is replaced: always when words, Blender or a restore replace it, or when much of it goes
    away at once; else at most once every EVERY seconds."""
    if not isinstance(old, dict) or not (old.get("things") or old.get("set")):
        return
    d = _vdir(bid)
    os.makedirs(d, exist_ok=True)
    names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    shrinks = sum(_count(new)) < sum(_count(old)) * 0.6 or len(json.dumps(new)) < len(json.dumps(old)) * 0.5
    if names and not why and not shrinks and time.time() - os.path.getmtime(os.path.join(d, names[-1])) < EVERY:
        return
    now = time.time()
    config.write_json(os.path.join(d, f"{int(now * 1000)}.json"), {"at": now, "why": why or "edits", "scene": old})
    for n in names[:max(0, len(names) + 1 - KEEP)]:
        os.unlink(os.path.join(d, n))


def versions(bid):
    """Earlier versions, newest first: [{id, at, why, things, set}]."""
    load(bid)
    d = _vdir(bid)
    out = []
    for n in sorted(os.listdir(d), reverse=True) if os.path.isdir(d) else []:
        v = config.read_json(os.path.join(d, n))
        if v:
            t, st = _count(v.get("scene"))
            out.append({"id": n[:-5], "at": v.get("at"), "why": v.get("why"), "things": t, "set": st})
    return out


def version(bid, vid):
    if not vid.isdigit():
        raise KeyError("version")
    v = config.read_json(os.path.join(_vdir(bid), vid + ".json"))
    if not v:
        raise KeyError("version")
    return v["scene"]


def made(bid, video, asset, sig, stats, shapes=""):
    """A render is done. shapes: what its shapes stand for, from the scene it was made from (for the video form)."""
    with _lock:
        b = load(bid)
        b.update(video=video, asset=asset, made=sig, stats=stats, shapes=shapes, updated=time.time())
        config.write_json(_path(bid), b)
        return b


def delete(bid):
    with _lock:
        p = _path(bid)
        if not os.path.isfile(p):
            raise KeyError("blockout")
        os.unlink(p)
        shutil.rmtree(_vdir(bid), ignore_errors=True)


def shapes_text(scene):
    """What the shapes are, for the video form: "the blue person is Mara; the red car is Car"."""
    from . import compose
    try:
        sc = blockouts.normalize(scene)
    except blockouts.BadScene:
        return ""
    return compose.scene_shapes(sc)


WRITE_SYSTEM = """You write blockout scenes for H3 Studio: rough 3D sketches that Blender renders as grey shapes, so
that a video model can follow their camera, positions and timing. Answer with the JSON object only:
{"say": one or two plain sentences on what you made or changed, "scene": the whole scene}.
When a current scene is given, change it as asked and keep everything else as it is. Invented people only; no real
places, brands, or sets from existing films, shows or games.

""" + blockouts.GUIDE

WRITE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["say", "scene"],
                "properties": {"say": {"type": "string"}, "scene": blockouts.SCHEMA}}
