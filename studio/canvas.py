"""Canvas: open boards for laying out pictures, clips and notes. One JSON file per board in canvas/<id>.json.

A board is {id, name, created, updated, items: [...], view: {x, y, zoom}}. An item is
{id, type: "asset" | "note", x, y, w, h, asset?, text?, color?}. Boards keep asset ids, not files: a file that was
deleted shows as missing on the board.
"""
import os
import threading
import time
import uuid

from . import config

_lock = threading.RLock()
MAX_ITEMS = 400
COLORS = ("yellow", "lime", "pink", "blue", "grey")


def _dir():
    d = config.home("canvas")
    os.makedirs(d, exist_ok=True)
    return d


def _path(bid):
    if not bid or not all(c.isalnum() for c in bid):
        raise KeyError("board")
    return os.path.join(_dir(), bid + ".json")


def load(bid):
    b = config.read_json(_path(bid))
    if not b:
        raise KeyError("board")
    return b


def all_boards():
    out = []
    for name in sorted(os.listdir(_dir())):
        if name.endswith(".json"):
            b = config.read_json(os.path.join(_dir(), name))
            if b:
                pics = [i["asset"] for i in b.get("items", []) if i.get("type") == "asset"][:4]
                out.append({"id": b["id"], "name": b["name"], "updated": b.get("updated", 0), "items": len(b.get("items", [])),
                            "preview": pics})
    out.sort(key=lambda b: b["updated"], reverse=True)
    return out


def create(name=""):
    b = {"id": "cv" + uuid.uuid4().hex[:10], "name": (name or "").strip()[:80] or "Untitled board", "created": time.time(),
         "updated": time.time(), "items": [], "view": None}
    with _lock:
        config.write_json(_path(b["id"]), b)
    return b


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi)


def clean_item(i):
    if not isinstance(i, dict) or i.get("type") not in ("asset", "note"):
        return None
    out = {"id": str(i.get("id") or uuid.uuid4().hex[:8])[:16], "type": i["type"],
           "x": _num(i.get("x"), -1e5, 1e5, 0), "y": _num(i.get("y"), -1e5, 1e5, 0),
           "w": _num(i.get("w"), 40, 4000, 240), "h": _num(i.get("h"), 30, 4000, 160)}
    if i["type"] == "asset":
        out["asset"] = str(i.get("asset") or "")[:40]
        if not out["asset"]:
            return None
    else:
        out["text"] = str(i.get("text") or "")[:4000]
        out["color"] = i.get("color") if i.get("color") in COLORS else "yellow"
    return out


def save(bid, d):
    """Replace the board's name, items and view with what the page sends."""
    with _lock:
        b = load(bid)
        if "name" in d:
            b["name"] = (str(d.get("name") or "")).strip()[:80] or b["name"]
        if "items" in d:
            items = [x for x in (clean_item(i) for i in (d.get("items") or [])[:MAX_ITEMS]) if x]
            b["items"] = items
        if isinstance(d.get("view"), dict):
            v = d["view"]
            b["view"] = {"x": _num(v.get("x"), -1e6, 1e6, 0), "y": _num(v.get("y"), -1e6, 1e6, 0), "zoom": _num(v.get("zoom"), 0.1, 4, 1)}
        b["updated"] = time.time()
        config.write_json(_path(bid), b)
        return b


def delete(bid):
    with _lock:
        p = _path(bid)
        if not os.path.isfile(p):
            raise KeyError("board")
        os.unlink(p)
