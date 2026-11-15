"""The Library: everything the studio made or was given, with what is known about it.

One record per file in library/index.json: where it is (relative to ComfyUI's output folder), what it is, the
prompt and seed it was made with, what the checks found. Thumbnails are made on first use.

Deleting moves a file to studio/trash and can be undone until the trash is emptied. Only the studio's own files
(under output/studio) can be moved; the parts inside a long-video project stay where the nodes need them.
"""
import os
import shutil
import threading
import time
import uuid

from . import checks, config

KINDS = ("image", "clip", "audio", "film", "export", "sheet")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm")
AUDIO_EXT = (".wav", ".flac", ".mp3", ".ogg", ".m4a")

_lock = threading.RLock()
_index = None


def _path():
    return config.home("library", "index.json")


def _load():
    global _index
    if _index is None:
        _index = config.read_json(_path(), {}) or {}
    return _index


def _save():
    config.write_json(_path(), _index)


def reset():
    global _index
    with _lock:
        _index = None


def kind_of(path):
    low = path.lower()
    if low.endswith(IMAGE_EXT):
        return "image"
    if low.endswith(VIDEO_EXT):
        return "clip"
    if low.endswith(AUDIO_EXT):
        return "audio"
    return ""


def abs_path(asset):
    return os.path.join(config.OUTPUT_DIR, asset["path"])


def url(asset):
    from urllib.parse import quote
    return "/media/" + quote(asset["path"])


def add(path, kind=None, **meta):
    """Register a file under output/. A file already known keeps its id and gets the new facts."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(config.OUTPUT_DIR)).replace(os.sep, "/")
    if rel.startswith(".."):
        raise ValueError(f"{path} is not under ComfyUI's output folder")
    with _lock:
        idx = _load()
        found = next((a for a in idx.values() if a["path"] == rel and not a.get("trashed")), None)
        a = found or {"id": uuid.uuid4().hex[:12], "path": rel, "created": time.time()}
        a["kind"] = kind or a.get("kind") or kind_of(rel) or "clip"
        a["name"] = meta.pop("name", None) or a.get("name") or os.path.basename(rel)
        a.update({k: v for k, v in meta.items() if v is not None})
        a["updated"] = time.time()
        try:
            st = os.stat(path)
            a["size"], a["mtime"] = st.st_size, st.st_mtime
        except OSError:
            pass
        if a["kind"] in ("clip", "film", "export") and ("duration" not in a or found):
            p = checks.probe(path)
            for k in ("duration", "width", "height", "fps"):
                if p.get(k):
                    a[k] = p[k]
        elif a["kind"] in ("image", "sheet") and "width" not in a:
            try:
                from PIL import Image
                with Image.open(path) as im:
                    a["width"], a["height"] = im.size
            except Exception:
                pass
        idx[a["id"]] = a
        _save()
        return dict(a)


def get(ident):
    with _lock:
        a = _load().get(ident)
        return dict(a) if a else None


def by_path(path):
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(config.OUTPUT_DIR)).replace(os.sep, "/")
    with _lock:
        for a in _load().values():
            if a["path"] == rel and not a.get("trashed"):
                return dict(a)
    return None


def update(ident, **fields):
    with _lock:
        a = _load().get(ident)
        if not a:
            return None
        a.update(fields)
        a["updated"] = time.time()
        _save()
        return dict(a)


def search(q="", kind="", film="", trashed=False, limit=500):
    """Newest first. `q` is looked for in the name, the prompt, the tags and the film's name; every word must be there."""
    words = [w for w in (q or "").lower().split() if w]
    out = []
    with _lock:
        items = list(_load().values())
    for a in items:
        if bool(a.get("trashed")) != bool(trashed):
            continue
        if kind and a.get("kind") != kind:
            continue
        if film and a.get("film") != film:
            continue
        if words:
            hay = " ".join(str(a.get(k, "")) for k in ("name", "prompt", "title", "film_name", "note")).lower() \
                + " " + " ".join(a.get("tags", [])).lower()
            if not all(w in hay for w in words):
                continue
        out.append(dict(a))
    out.sort(key=lambda a: a.get("created", 0), reverse=True)
    return out[:limit]


def thumb(asset):
    """Path of the asset's thumbnail, made when missing or older than the file. None when it cannot be made."""
    src = abs_path(asset)
    if not os.path.isfile(src) or asset.get("kind") == "audio":
        return None
    dst = config.home("library", "thumbs", asset["id"] + ".jpg")
    try:
        if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst
    except OSError:
        pass
    return dst if checks.thumbnail(src, dst) else None


def _movable(asset):
    """Only the studio's own files may be moved; a quick clip's whole project folder counts as one thing."""
    p = abs_path(asset)
    return config.inside(p, config.STUDIO_HOME) and not config.inside(p, config.home("trash"))


def trash(ids):
    """Move files to the trash. Returns {"moved": [...ids], "kept": [(id, why)]}."""
    moved, kept = [], []
    with _lock:
        idx = _load()
        for ident in ids:
            a = idx.get(ident)
            if not a or a.get("trashed"):
                continue
            src = abs_path(a)
            if a.get("locked"):
                kept.append((ident, "it is the active take of a film"))
                continue
            if not _movable(a):
                kept.append((ident, "it belongs to a project folder; delete the film or clip it belongs to"))
                continue
            if os.path.isfile(src):
                dst = config.home("trash", f"{a['id']}_{os.path.basename(src)}")
                shutil.move(src, dst)
                a["trash_path"] = os.path.relpath(dst, config.OUTPUT_DIR).replace(os.sep, "/")
            a["trashed"] = time.time()
            moved.append(ident)
        _save()
    return {"moved": moved, "kept": kept}


def restore(ids=None):
    """Put files back. Without ids: everything of the last deletion (within 5 s of the newest)."""
    back = []
    with _lock:
        idx = _load()
        gone = [a for a in idx.values() if a.get("trashed")]
        if ids is None:
            if not gone:
                return []
            newest = max(a["trashed"] for a in gone)
            gone = [a for a in gone if newest - a["trashed"] < 5]
        else:
            gone = [a for a in gone if a["id"] in ids]
        for a in gone:
            tp = a.get("trash_path")
            if tp and os.path.isfile(os.path.join(config.OUTPUT_DIR, tp)):
                dst = abs_path(a)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(os.path.join(config.OUTPUT_DIR, tp), dst)
            a.pop("trashed", None)
            a.pop("trash_path", None)
            back.append(a["id"])
        _save()
    return back


def trash_size():
    n = size = 0
    for root, _, files in os.walk(config.home("trash")):
        for f in files:
            n += 1
            size += os.path.getsize(os.path.join(root, f))
    return {"files": n, "bytes": size}


def empty_trash():
    """Erase what is in the trash. This is the one thing here that cannot be undone."""
    with _lock:
        idx = _load()
        for ident in [i for i, a in idx.items() if a.get("trashed")]:
            del idx[ident]
        _save()
    root = config.home("trash")
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.unlink(p)
    return trash_size()


def forget(film=None, ids=()):
    """Drop records (not files): everything of a film that was deleted, or the ids given."""
    with _lock:
        idx = _load()
        dead = [i for i, a in idx.items() if (film and a.get("film") == film) or i in ids]
        for i in dead:
            del idx[i]
        if dead:
            _save()
    return len(dead)


def forget_missing():
    """Drop records whose file is gone (deleted outside the studio). Returns how many."""
    with _lock:
        idx = _load()
        dead = [i for i, a in idx.items() if not a.get("trashed") and not os.path.exists(abs_path(a))]
        for i in dead:
            del idx[i]
        if dead:
            _save()
    return len(dead)
