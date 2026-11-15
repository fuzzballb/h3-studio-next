"""Blockouts: one per scene of a film (the shots that share a Scene name), made after the story is written, refined
until it works, then cut into the scene's shots: each shot follows its own stretch of it (cuts, compose.blockout_plan,
graphs.blockout_clip). A film keeps them in film["blockouts"]: {"id", "scene_name", "scene", "cuts", and the server's
"video", "made", "stats"}.

The scene is plain data: the set, the moving things and the camera,

A scene is plain data, checked here (normalize) and turned into a Blender scene by a fixed script of the studio's
(studio/blender/blockout.py): nothing in a scene is ever run as code, so a scene the Writer wrote is as safe as one a
person wrote. Units are metres and seconds, z is up, angles are degrees and a facing of 0 looks along +x.

{"sky": "night", "ground": "snow",
 "set":    [{"type": "street", "name": "", "at": [-40, 0, 0], "size": [200, 14, 13], "turn": 0, "color": "brick"}],
 "things": [{"name": "Mara", "kind": "person", "color": "blue", "scale": 1,
             "keys": [{"t": 0, "at": [10, -2, 0], "face": null, "pose": "walk"}, {"t": 6, "at": [18, -2, 0], "face": null, "pose": "stand"}]}],
 "camera": {"lens": 35, "shake": 0,
            "keys": [{"t": 0, "at": [4, -6, 1.6], "look_at": [10, -2, 1.2], "follow": "", "lens": 0},
                     {"t": 8, "at": [14, -7, 2.5], "look_at": [0, 0, 0], "follow": "Mara", "lens": 0}]}}
"""
import json
import math
import os

from . import config

SKIES = ("day", "dusk", "night", "indoor")
GROUNDS = ("grass", "snow", "asphalt", "sand", "floor", "water", "none")
SET_TYPES = ("street", "room", "building", "city", "box", "wall", "cylinder", "ball", "cone", "tree")
KINDS = ("person", "child", "cyclist", "car", "van", "truck", "bus", "tram", "train", "bike", "horse", "dog", "animal", "bird",
         "box", "ball", "sled", "boat", "plane")
POSES = ("stand", "walk", "run", "sit", "lie", "crouch", "look_up", "look_down", "wave")
LIMITS = {"set": 120, "things": 30, "keys": 60, "coord": 3000.0}
# what a set item's size means when none is given (and what its "at" is)
SET_SIZE = {"street": [200, 14, 13], "room": [8, 6, 3], "building": [10, 10, 15], "city": [300, 300, 16], "box": [1, 1, 1],
            "wall": [4, 0.2, 3], "cylinder": [1, 1, 2], "ball": [1, 1, 1], "cone": [1, 1, 2], "tree": [3, 3, 6]}

# ---------------------------------------------------------------- the JSON schema the Writer answers in (strict)
_NUM = {"type": "number"}
_STR = {"type": "string"}
_XYZ = {"type": "array", "items": _NUM}
_SET = {"type": "object", "additionalProperties": False, "required": ["type", "name", "at", "size", "turn", "color"],
        "properties": {"type": {"type": "string", "enum": list(SET_TYPES)}, "name": _STR, "at": _XYZ, "size": _XYZ,
                       "turn": _NUM, "color": _STR}}
_KEY = {"type": "object", "additionalProperties": False, "required": ["t", "at", "face", "pose"],
        "properties": {"t": _NUM, "at": _XYZ, "face": {"anyOf": [_NUM, {"type": "null"}]},
                       "pose": {"type": "string", "enum": list(POSES)}}}
_THING = {"type": "object", "additionalProperties": False, "required": ["name", "kind", "color", "scale", "keys"],
          "properties": {"name": _STR, "kind": {"type": "string", "enum": list(KINDS)}, "color": _STR, "scale": _NUM,
                         "keys": {"type": "array", "items": _KEY}}}
_CAMKEY = {"type": "object", "additionalProperties": False, "required": ["t", "at", "look_at", "follow", "lens", "cut"],
           "properties": {"t": _NUM, "at": _XYZ, "look_at": _XYZ, "follow": _STR, "lens": _NUM, "cut": {"type": "boolean"}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["sky", "ground", "set", "things", "camera"],
          "properties": {"sky": {"type": "string", "enum": list(SKIES)}, "ground": {"type": "string", "enum": list(GROUNDS)},
                         "set": {"type": "array", "items": _SET}, "things": {"type": "array", "items": _THING},
                         "camera": {"type": "object", "additionalProperties": False, "required": ["lens", "shake", "keys"],
                                    "properties": {"lens": _NUM, "shake": _NUM, "keys": {"type": "array", "items": _CAMKEY}}}}}

GUIDE = """A blockout is a rough 3D sketch of a whole scene: grey shapes in Blender for the set, simple figures for
people, vehicles and animals, and a camera path. It is made after the story, looked at and refined until it works,
then cut into the scene's shots: each shot follows its own stretch of it, and the video model keeps that stretch's
camera, framing, positions, sizes and timing and paints the real thing over it. Give a scene a blockout when the
camera or the staging matters and words would not hold it: a camera that flies, circles, cranes or follows; vehicles
that stop, turn, crash; a fall; things that land in a given spot; several people placed exactly. A quiet dialogue at
a table needs none.

One blockout per scene (the shots with the same "scene"). Its time runs through the scene's shots in order: the first
shot from 0 for its seconds, each next shot from where the one before ends, except a continuation, which starts 1.6 s
before the end of the shot it continues (it carries those last 1.6 s on). So give the shots the lengths the action
needs, and put each event at the time of the shot it belongs to. A new shot inside the scene (a cut) can show the
action from another angle: give the camera a key at the time that shot starts with "cut": true, and the camera jumps
there instead of moving. On the shots of a scene with a blockout leave "framing" and "camera" empty (the blockout sets
them) and still write in "action" who and what everything is and what happens.

Units are metres and seconds; z is up; the ground is z = 0; angles are degrees; a facing of 0 looks along +x and 90
along +y. A person is 1.75 m tall; a car 4.4 x 1.8 x 1.45 m.
- "sky": day, dusk, night or indoor. "ground": grass, snow, asphalt, sand, floor, water or none.
- "set" (does not move): street (along +x from "at", size = [length, width of the road, house height]; houses with
  windows on both sides of the road at y = at.y +- (width/2 + 2.4)), room (at = middle of the floor, size = [width,
  depth, height]; walls at the back (+y), left and right, the front open for the camera), building (at = middle of its
  footprint), city (blocks of houses around "at", size = [width, depth, max height]; for flights over roofs), box,
  wall, cylinder, ball, cone, tree (at = the middle of its base, size = [x, y, height]). "turn" rotates it about z.
  "color": a name (red, dark red, orange, yellow, gold, green, dark green, blue, light blue, navy, purple, pink, white,
  grey, dark grey, black, brown, light brown, beige, brick, stone, wood, glass, silver) or #rrggbb.
- "things" (can move): kind person, child, cyclist (a person riding a bike), car, van, truck, bus, tram (30 m),
  train, bike (with nobody on it), horse, dog, animal, bird, box, ball, sled, boat or plane; "scale" 1 = normal
  size. Parked cars and other vehicles that do not move are things with one key, so they look like what they are. "keys": where it is at which second ("at" on the ground for people and
  vehicles), its "face" in degrees or null to face the way it moves, and its "pose": stand, walk, run, sit, lie,
  crouch, look_up, look_down or wave. Between keys it moves smoothly; walking legs follow the speed (walk about 1.4
  m/s, run 4, a car in town 8 to 14). Give a key at the start and the end of the take; a thing that stops gets two
  keys at the same place.
- "camera": "lens" in mm (18 = very wide, 35 = normal, 85 = tight), "shake" in metres (0 = steady, 0.03 = handheld),
  "keys": where the camera is ("at") and what it looks at ("look_at" a point, or "follow" the name of a thing, which
  then overrides look_at), with an own "lens" or 0 for the camera's, and "cut": true to jump to this key (a cut to a
  new shot) instead of moving there; false otherwise. Height 1.6 m is eye level, 0.3 m a worm's-eye
  view, 20 m and more is above the roofs. A camera that should stand still has one key.
How big a thing is in the picture is decided here, and the video keeps it: at lens 35 a standing person fills the
height of the picture from about 3 m away, half of it from 6 m, and is small from 15 m. For a medium shot of someone
the camera is 2 to 4 m from them; for a tracking shot it moves with them at the same speed (give the camera keys at
the same times as theirs, at the same distance) so they stay big in the picture. A camera that falls behind or that a
subject passes makes them small or sends them out of the frame.
When the film you are shown has "measured" for a blockout, those are the sizes Blender measured: the share of the
picture height a thing fills (median) and the share of the time it is in the picture. A followed subject under 0.25
or in the picture under 0.7 of the time is too small: the render then draws it the size the words ask for and moves
the camera, so it stops following the blockout. Fix the scene, not the words.
The action of a shot with a blockout says what happens, not where the camera is: the blockout sets the camera.
Left and right in the words are the picture's. A camera that looks back at someone coming toward it sees their right
hand on the left of the picture: place the things so the sides in the scene and in the words agree ("side_of_picture"
in "measured" says where they came out). Put everything that must be seen inside the set: a street "size"
[length, width, height] has its house walls at half the width either side of its middle line, so a shop, a shelter or a
parked car goes within that.
Keep it simple: the model needs where things are and how the camera moves, not detail. Keep the camera out of walls
and houses, and make sure what matters is in front of it and big enough to read in the picture."""


class BadScene(ValueError):
    pass


def _num(v, what, lo=None, hi=None, default=None):
    if v is None and default is not None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BadScene(f"{what}: {v!r} is not a number")
    if not math.isfinite(x):
        raise BadScene(f"{what}: not a finite number")
    if lo is not None and x < lo or hi is not None and x > hi:
        raise BadScene(f"{what}: {x:g} is outside {lo:g} to {hi:g}")
    return x


def _xyz(v, what, default=(0.0, 0.0, 0.0)):
    if v is None:
        return list(default)
    if not isinstance(v, (list, tuple)) or not 2 <= len(v) <= 3:
        raise BadScene(f"{what}: give [x, y, z]")
    c = LIMITS["coord"]
    out = [_num(x, what, -c, c) for x in v]
    return out + [0.0] * (3 - len(out))


def _text(v, n=60):
    return str(v or "").strip()[:n]


def normalize(scene):
    """A scene as the renderer takes it: every field there, numbers checked, lists capped, keys in time order.
    Raises BadScene with what is wrong. Accepts a JSON string."""
    if isinstance(scene, str):
        try:
            scene = json.loads(scene)
        except ValueError as e:
            raise BadScene(f"not valid JSON: {e}")
    if not isinstance(scene, dict):
        raise BadScene("a blockout scene is an object with sky, ground, set, things and camera")
    sky = scene.get("sky") or "day"
    ground = scene.get("ground") or "grass"
    if sky not in SKIES:
        raise BadScene(f"sky: {sky!r} is not one of {', '.join(SKIES)}")
    if ground not in GROUNDS:
        raise BadScene(f"ground: {ground!r} is not one of {', '.join(GROUNDS)}")
    out = {"sky": sky, "ground": ground, "set": [], "things": [], "camera": {}}
    items = scene.get("set") or []
    if len(items) > LIMITS["set"]:
        raise BadScene(f"set: {len(items)} items, at most {LIMITS['set']}")
    for i, it in enumerate(items):
        what = f"set item {i + 1}"
        t = (it or {}).get("type")
        if t not in SET_TYPES:
            raise BadScene(f"{what}: type {t!r} is not one of {', '.join(SET_TYPES)}")
        size = it.get("size") or SET_SIZE[t]
        size = _xyz(size, what + " size", SET_SIZE[t])
        if any(s <= 0 for s in size):
            size = [s if s > 0 else d for s, d in zip(size, SET_SIZE[t])]
        out["set"].append({"type": t, "name": _text(it.get("name")), "at": _xyz(it.get("at"), what + " at"), "size": size,
                           "turn": _num(it.get("turn"), what + " turn", -720, 720, 0.0), "color": _text(it.get("color"), 20)})
    things = scene.get("things") or []
    if len(things) > LIMITS["things"]:
        raise BadScene(f"things: {len(things)}, at most {LIMITS['things']}")
    names = set()
    for i, th in enumerate(things):
        name = _text((th or {}).get("name")) or f"thing {i + 1}"
        what = f"{name}"
        if name in names:
            raise BadScene(f"two things are called {name!r}: names must differ (the camera follows by name)")
        names.add(name)
        kind = th.get("kind") or "box"
        if kind not in KINDS:
            raise BadScene(f"{what}: kind {kind!r} is not one of {', '.join(KINDS)}")
        keys = th.get("keys") or []
        if not keys:
            raise BadScene(f"{what}: give at least one key (where it is at t = 0)")
        if len(keys) > LIMITS["keys"]:
            raise BadScene(f"{what}: {len(keys)} keys, at most {LIMITS['keys']}")
        ks = []
        for j, k in enumerate(keys):
            pose = k.get("pose") or "stand"
            if pose not in POSES:
                raise BadScene(f"{what} key {j + 1}: pose {pose!r} is not one of {', '.join(POSES)}")
            face = k.get("face")
            ks.append({"t": _num(k.get("t"), f"{what} key {j + 1} t", 0, 600, 0.0), "at": _xyz(k.get("at"), f"{what} key {j + 1} at"),
                       "face": None if face is None else _num(face, f"{what} key {j + 1} face", -720, 720), "pose": pose})
        ks.sort(key=lambda k: k["t"])
        out["things"].append({"name": name, "kind": kind, "color": _text(th.get("color"), 20),
                              "scale": _num(th.get("scale"), what + " scale", 0.05, 50, 1.0) or 1.0, "keys": ks})
    cam = scene.get("camera") or {}
    ck = cam.get("keys") or []
    if not ck:
        raise BadScene("camera: give at least one key (where the camera is and what it looks at)")
    if len(ck) > LIMITS["keys"]:
        raise BadScene(f"camera: {len(ck)} keys, at most {LIMITS['keys']}")
    keys = []
    for j, k in enumerate(ck):
        follow = _text(k.get("follow"))
        if follow and follow not in names:
            raise BadScene(f"camera key {j + 1}: it follows {follow!r}, but no thing has that name")
        keys.append({"t": _num(k.get("t"), f"camera key {j + 1} t", 0, 600, 0.0), "at": _xyz(k.get("at"), f"camera key {j + 1} at", (0, -10, 1.6)),
                     "look_at": _xyz(k.get("look_at"), f"camera key {j + 1} look_at"), "follow": follow,
                     "lens": _num(k.get("lens"), f"camera key {j + 1} lens", 0, 300, 0.0), "cut": bool(k.get("cut"))})
        if not follow and all(abs(a - b) < 1e-3 for a, b in zip(keys[-1]["at"], keys[-1]["look_at"])):
            raise BadScene(f"camera key {j + 1}: the camera looks at the point it stands on")
    keys.sort(key=lambda k: k["t"])
    out["camera"] = {"lens": _num(cam.get("lens"), "camera lens", 8, 300, 35.0) or 35.0,
                     "shake": _num(cam.get("shake"), "camera shake", 0, 2, 0.0), "keys": keys}
    return out


def signature(scene, frames, width, height):
    """What a made blockout was made from: a scene changed after it was made shows as out of date."""
    import hashlib
    cam = scene.get("camera") or {}
    if cam.get("keys") and not any(k.get("cut") for k in cam["keys"]):   # made before cuts existed: the same scene
        scene = {**scene, "camera": {**cam, "keys": [{k: v for k, v in key.items() if k != "cut"} for key in cam["keys"]]}}
    return hashlib.sha1(json.dumps([scene, frames, width, height], sort_keys=True).encode()).hexdigest()[:12]


# A followed subject that fills less than this share of the picture height (median over the take), or is in the
# picture less than this share of the time, is "too small". Seen 2026-11-14 (Last Stop): a cyclist the camera followed at
# 9 m with a 28 mm lens filled about a sixth of the height in the blockout, and the render (prompt: "keeps her large")
# drew her big and moved the camera: only the street layout carried over.
SMALL = {"median": 0.25, "in_view": 0.7}


def too_small(stats):
    """[(name, why)] for the followed things the camera keeps too small or out of the picture, from the renderer's stats."""
    out = []
    for n, s in (stats or {}).items():
        if not s.get("followed"):
            continue
        if s.get("in_view", 1) < SMALL["in_view"]:
            out.append((n, f"is in the picture only {round(100 * s['in_view'])}% of the time"))
        elif s.get("median", 1) < SMALL["median"]:
            out.append((n, f"fills only {round(100 * s['median'])}% of the picture height (at most {round(100 * s.get('max', 0))}%)"))
    return out


def sides(stats):
    """Where each thing is in the picture most of the time: "the yellow tram on the right, Mara in the middle"."""
    out = [f"{n} {'in the middle' if s['side'] == 'middle' else 'on the ' + s['side']}" for n, s in (stats or {}).items()
           if s.get("side") and s.get("in_view", 0) >= 0.3]
    return ", ".join(out)


# ---------------------------------------------------------------- a film's blockouts, one per scene
def scene_of(shot):
    return (shot.get("scene") or "").strip()


def all_of(film):
    return film.get("blockouts") or []


def find(film, bid):
    return next((b for b in all_of(film) if b.get("id") == bid), None)


def for_scene(film, name):
    return next((b for b in all_of(film) if (b.get("scene_name") or "").strip() == (name or "").strip()), None)


def of_shot(film, index):
    shots = film.get("shots") or []
    return for_scene(film, scene_of(shots[index])) if 0 <= index < len(shots) else None


def scene_names(film):
    """The scenes of a film in the order they first appear: [(name, [shot indices])]."""
    out = {}
    for i, s in enumerate(film.get("shots") or []):
        out.setdefault(scene_of(s), []).append(i)
    return list(out.items())


def cuts(film, b):
    """Where each shot of the blockout's scene reads it, in order: [{"index", "id", "start", "frames", "end",
    "continuation", "auto"}]. The first shot starts at 0 and each next one where the one before ends; a continuation of
    the shot right before starts CONTEXT frames before that one's end, the frames it carries on. A new shot can be given
    its own start in b["cuts"] ({shot id: frame}); the shots after it go on from there."""
    from . import compose, lengths
    bible = {**compose.blank_bible(), **(film.get("bible") or {})}
    shots = film.get("shots") or []
    manual = b.get("cuts") or {}
    out, prev = [], None
    for i, s in enumerate(shots):
        if scene_of(s) != (b.get("scene_name") or "").strip():
            continue
        cont = not (s.get("new_shot", True) or i == 0)
        n = compose.part_frames(bible, s, cont)[0]
        follows = cont and prev is not None and prev["index"] == i - 1
        start = 0 if prev is None else prev["end"] - lengths.CONTEXT if follows else prev["end"]
        auto = True
        if not follows and s.get("id") in manual:
            try:
                start, auto = max(0, int(manual[s["id"]])), False
            except (TypeError, ValueError):
                pass
        out.append({"index": i, "id": s.get("id"), "start": start, "frames": n, "end": start + n, "continuation": follows, "auto": auto})
        prev = out[-1]
    return out


def scene_frames(scene):
    """How long the scene itself runs: to its last key, at 24 fps."""
    ts = [k["t"] for th in scene.get("things") or [] for k in th.get("keys") or []] + [k["t"] for k in (scene.get("camera") or {}).get("keys") or []]
    return int(round(max(ts + [0]) * 24)) + 1


def render_frames(film, b, scene):
    """The frames the video is made with: enough for every shot's stretch, and for the whole scene."""
    return max([c["end"] for c in cuts(film, b)] + [scene_frames(scene), 24])


def state_of(film, b):
    """{"id", "scene_name", "made", "current", "error", "stats", "small", "frames"} of a film's blockout."""
    from . import compose
    out = {"id": b.get("id"), "scene_name": b.get("scene_name", ""), "made": bool(b.get("video") and b.get("made")),
           "current": False, "error": "", "stats": b.get("stats"), "small": too_small(b.get("stats")), "frames": 0}
    if not b.get("scene"):
        out["error"] = "no scene written yet"
        return out
    try:
        scene = normalize(b["scene"])
    except BadScene as e:
        out["error"] = str(e)
        return out
    bible = {**compose.blank_bible(), **(film.get("bible") or {})}
    out["frames"] = render_frames(film, b, scene)
    out["current"] = out["made"] and b.get("made") == signature(scene, out["frames"], int(bible["width"]), int(bible["height"]))
    return out


def state(film, index):
    """The blockout of the scene of the shot at `index` (see state_of), or None when its scene has none."""
    b = of_shot(film, index)
    return state_of(film, b) if b else None


def migrate(film):
    """Films made before blockouts were per scene kept a scene on the shot that opened a take. Move each to its
    scene's blockout (once; a scene that already has one keeps it). Returns True when something moved."""
    from . import compose
    moved = False
    film.setdefault("blockouts", [])
    for i, s in enumerate(film.get("shots") or []):
        if not s.get("blockout_scene"):
            continue
        sc = s.pop("blockout_scene")
        video = s.get("blockout") or ""
        if not for_scene(film, scene_of(s)):
            import hashlib
            take = compose.take_of(film, i)
            bid = "b" + hashlib.sha1(f"{film.get('id')}/{scene_of(s)}".encode()).hexdigest()[:7]   # the same on every load
            film["blockouts"].append({"id": bid, "scene_name": scene_of(s), "scene": sc, "cuts": {},
                                      "video": video, "made": s.get("blockout_made") or "",
                                      "stats": s.get("blockout_stats")})
            for j in take:                       # the video was the shots' own: now it is the scene's
                if video and film["shots"][j].get("blockout") == video:
                    film["shots"][j]["blockout"] = ""
                    film["shots"][j]["blockout_start"] = 0
        for k in ("blockout_made", "blockout_stats"):
            s.pop(k, None)
        moved = True
    return moved


def blender():
    """The Blender program: Settings → blender, else `blender` on the PATH. '' when there is none."""
    import shutil
    want = (config.settings().get("blender") or "").strip()
    if want:
        return want if os.path.isfile(want) and os.access(want, os.X_OK) else ""
    return shutil.which("blender") or ""


SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender", "blockout.py")
