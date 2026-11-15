"""The preset files in studio/presets/: camera moves, looks, apps, coverage plans, angle sets.

They are plain JSON so they can be read, changed and added to without touching code. A file of the same name in
STUDIO_HOME/presets/ adds to the shipped one (entries with the same id replace it).
"""
import functools
import os

from . import config

FILES = ("cameras", "looks", "apps", "coverage", "angles")


def _merge_lists(base, extra):
    by_id = {e.get("id"): e for e in base}
    for e in extra:
        by_id[e.get("id")] = e
    order = [e.get("id") for e in base] + [e.get("id") for e in extra if e.get("id") not in {b.get("id") for b in base}]
    return [by_id[i] for i in order]


@functools.lru_cache(maxsize=None)
def load(name):
    if name not in FILES:
        raise KeyError(name)
    data = config.read_json(os.path.join(config.PRESETS, name + ".json"), {})
    own = config.read_json(config.home("presets", name + ".json"), {}) or {}
    for key, value in own.items():
        if isinstance(value, list) and isinstance(data.get(key), list):
            data[key] = _merge_lists(data[key], value)
        else:
            data[key] = value
    return data


def everything():
    return {name: load(name) for name in FILES}


def find(name, key, ident):
    """One entry by id, or None: find("cameras", "moves", "push-in")."""
    for e in load(name).get(key, []):
        if e.get("id") == ident:
            return e
    return None


def text(name, key, ident):
    e = find(name, key, ident)
    return e["text"] if e else ""
