"""Where things live, and the studio's settings.

Paths
    COMFY_DIR    the ComfyUI folder (env COMFYUI_DIR, else two levels above this repo when it sits in
                 custom_nodes/, else ~/ComfyUI)
    OUTPUT_DIR   ComfyUI's output folder, INPUT_DIR its input folder (both may be symlinks to another disk)
    STUDIO_HOME  the studio's own data (env STUDIO_HOME, else <output>/studio_next): settings, jobs, library index,
                 films, takes, exports, trash. It sits under output/ on purpose: that is where the big disk is,
                 and ComfyUI can serve files from it.

Settings are one JSON file, `settings.json` in STUDIO_HOME; anything missing falls back to DEFAULTS.
"""
import copy
import json
import os
import re
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_comfy_dir():
    env = os.environ.get("COMFYUI_DIR")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    up = os.path.dirname(REPO)                            # <ComfyUI>/<repo>
    if os.path.isfile(os.path.join(up, "main.py")):
        return up
    up = os.path.dirname(up)                              # <ComfyUI>/custom_nodes/<repo>
    if os.path.isfile(os.path.join(up, "main.py")) and os.path.basename(os.path.dirname(REPO)) == "custom_nodes":
        return up
    return os.path.expanduser("~/ComfyUI")


COMFY_DIR = _find_comfy_dir()
OUTPUT_DIR = os.path.abspath(os.path.expanduser(os.environ.get("COMFYUI_OUTPUT", os.path.join(COMFY_DIR, "output"))))
INPUT_DIR = os.path.abspath(os.path.expanduser(os.environ.get("COMFYUI_INPUT", os.path.join(COMFY_DIR, "input"))))
STUDIO_HOME = os.path.abspath(os.path.expanduser(os.environ.get("STUDIO_HOME", os.path.join(OUTPUT_DIR, "studio_next"))))
LONG_DIR = os.path.join(OUTPUT_DIR, "long_video")        # the long-video nodes write here; the name is theirs
TEMPLATES = os.path.join(REPO, "story_kit", "templates")
PRESETS = os.path.join(REPO, "studio", "presets")
STATIC = os.path.join(REPO, "studio", "static")

# studio folders, all relative to STUDIO_HOME
FOLDERS = ("images", "films", "exports", "trash", "library", "library/thumbs", "library/words", "sheets", "audio",
           "nightshift", "dailies", "timelines", "cast", "logs", "tmp", "uploads", "presets", "blockouts")

DEFAULTS = {
    "comfy_url": os.environ.get("COMFY", "http://127.0.0.1:8188"),
    # command that starts ComfyUI; empty = <ComfyUI>/run.sh when that exists
    "comfy_start": "",
    # start ComfyUI when a job needs it and it does not answer (also after a crash)
    "auto_start_comfy": False,
    # model files by role, as ComfyUI lists them; empty = picked from what is installed (see models.py)
    "models": {
        "video_unet": "", "video_clip": "", "video_vae": "", "audio_vae": "", "turbo_lora": "", "tiny_vae": "",
        "upscaler": "", "film": "", "image_unet": "", "image_clip": "", "image_vae": "", "blockout_unet": "",
    },
    "video": {
        "width": 1152, "height": 640, "frames": 243, "turbo": True,
        "steps": 13, "turbo_steps": 8, "turbo_strength": 0.95, "shift_video": 12.0, "shift_audio": 3.0,
        "language": "English", "crf": 14,
        # what a part without spoken lines is told; tested on this stack ("Nobody speaks..." stopped the mumbling)
        "silent_line": "Nobody speaks, there are no words at all",
    },
    # a shot that follows a blockout video (H3 V2V). How much of the blockout's own picture is kept: 1 = none.
    # Measured on a 10-part film (2026-11-14): 0.9995 often dropped the blocked camera (an eye-level shot instead of a
    # high diagonal one), 0.997 follows camera, framing and positions and still looks real, 0.994 leaves the buildings
    # as flat textured blocks, 0.99 and below show the blockout with textures.
    "blockout": {"strength": 0.997, "sampler": "er_sde", "scheduler": "beta"},
    # a preview of a shot: rendered this small (the short side, in pixels) into a project of its own
    "preview": {"short_side": 256},
    # the Blender program that renders blockout scenes; empty = `blender` on the PATH
    "blender": "",
    "image": {"width": 1344, "height": 768, "steps": 25, "sampler": "euler", "scheduler": "simple"},
    "upscale": {"scale": 1.5, "interpolate": True, "sharpen": True, "sigmas": "0.6316, 0.3158, 0.0000"},
    "checks": {
        "cut": 30.0,           # frame jump (0-255, 64x36 gray) that counts as a hard cut
        "join": 25.0,          # last frame of part N-1 vs first frame of part N; good joins measured 1-9, bad 29-44
        "loud": -21.0,         # LUFS while someone speaks: above this a part gets a note when its film has nothing to compare with
        "loud_over": 2.5,      # dB above the median speech peak of the film's other approved parts that fails a part
        "speech_min": 0.8,     # word match between the script and what Whisper hears
        "nsp": 0.5,            # Whisper no_speech_prob below this = "sure it is speech" (parts without lines)
        "whisper_model": "small",
        "whisper_dir": "",     # empty = <ComfyUI>/models/whisper when it exists
        "whisper_device": "cpu",   # cpu keeps the GPU for rendering
    },
    "gate": {
        "auto_approve": False,  # approve a take by itself when every automatic check passes
        "retries": 2,           # extra takes (next seed) when an automatic check fails
    },
    # the optional writing help. none = templates only. Rendering never uses it.
    "brain": {"kind": "none", "endpoint": "http://127.0.0.1:11434/v1", "model": "", "command": "", "timeout": 180},
    "writer": {"command": "claude", "model": "opus"},          # the Writer: Claude Code signed in on this computer
    "keep_takes": True,         # keep every take's files so an earlier take can be put back
    "finish": {"loudness": -16.0, "true_peak": -1.5, "match_clips": True, "music_gain": -18.0, "duck": 12.0},
}

_lock = threading.RLock()
_cache = None


def home(*parts):
    """A path inside STUDIO_HOME."""
    return os.path.join(STUDIO_HOME, *parts)


def ensure_home():
    for f in FOLDERS:
        os.makedirs(home(f), exist_ok=True)


def write_json(path, data):
    """Write JSON so a crash never leaves half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def settings():
    """The settings, DEFAULTS filled in. A copy: change it with update()."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _merge(DEFAULTS, read_json(home("settings.json"), {}))
        return copy.deepcopy(_cache)


def update(patch):
    """Merge a patch into the saved settings and return the result. Unknown top-level keys are refused."""
    global _cache
    unknown = sorted(set(patch) - set(DEFAULTS))
    if unknown:
        raise ValueError("unknown setting(s): " + ", ".join(unknown))
    with _lock:
        saved = _merge(read_json(home("settings.json"), {}), patch)
        write_json(home("settings.json"), saved)
        _cache = _merge(DEFAULTS, saved)
        return copy.deepcopy(_cache)


def reset_cache():
    global _cache
    with _lock:
        _cache = None


def slug(text, fallback="untitled", limit=40):
    """A file-safe lower-case name: letters, digits and underscores."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:limit].strip("_")
    return s or fallback


def inside(path, root):
    """True when path is root or lies in it, symlinks resolved (output/ is often a symlink to another disk)."""
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


# ---- names of media files as ComfyUI's loaders take them -------------------------------------------------------
# "face.png" is a file in input/; "studio/uploads/face.png [output]" one under output/ (ComfyUI's own annotation).
# The studio keeps what it makes and what is uploaded under output/studio, on the big disk, and names it the second way.
def ref_path(name):
    """A loader name to the file it means."""
    name = (name or "").strip()
    for suffix, base in ((" [output]", OUTPUT_DIR), (" [input]", INPUT_DIR)):
        if name.endswith(suffix):
            return os.path.join(base, name[:-len(suffix)])
    return os.path.join(INPUT_DIR, name)


def out_ref(path):
    """A file under output/ as a loader name."""
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(OUTPUT_DIR))
    if rel.startswith(".."):
        raise ValueError(f"{path} is not under ComfyUI's output folder")
    return rel.replace(os.sep, "/") + " [output]"


def ref_url(name):
    """Where the browser gets a loader name from."""
    name = (name or "").strip()
    if not name:
        return ""
    from urllib.parse import quote
    if name.endswith(" [output]"):
        return "/media/" + quote(name[:-9])
    if name.endswith(" [input]"):
        return "/input/" + quote(name[:-8])
    return "/input/" + quote(name)


def comfy_start_command():
    cmd = settings().get("comfy_start") or ""
    if cmd:
        return cmd
    run = os.path.join(COMFY_DIR, "run.sh")
    return run if os.path.isfile(run) else ""


def whisper_dir():
    d = settings()["checks"].get("whisper_dir") or ""
    if d:
        return os.path.expanduser(d)
    guess = os.path.join(COMFY_DIR, "models", "whisper")
    return guess if os.path.isdir(guess) else ""
