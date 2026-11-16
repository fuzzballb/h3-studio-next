# Renders a blockout scene description (studio/blockouts.py) in Blender, headless:
#   blender -b --factory-startup -P blockout.py -- <scene.json> <out_dir> <frames> <width> <height>
# Writes <out_dir>/f_0001.png ... and <out_dir>/scene.blend (open it in Blender to refine the shot by hand).
# Grey-ish shapes in the Workbench engine: the video model only needs camera, framing, positions, sizes and timing.
# Conventions: metres, seconds, z up, angles in degrees, a facing of 0 looks along +x, 90 along +y.
# The description is data checked by blockouts.normalize(); this file runs no code from it.
import json
import math
import os
import random
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC = json.load(open(argv[0], encoding="utf-8"))
OUT, FRAMES, W, H = argv[1], int(argv[2]), int(argv[3]), int(argv[4])
FPS = 24

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"
sc = bpy.context.scene
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, FRAMES
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.engine = "BLENDER_WORKBENCH"
sh = sc.display.shading
sh.light, sh.color_type, sh.show_shadows, sh.show_cavity = "STUDIO", "MATERIAL", True, True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockout_shapes                                      # noqa: E402  (the shapes, shared with blockout_edit.py)
from blockout_shapes import (SKY, Rig, box, build, cyl, empty, mat, SET, prop)   # noqa: E402,F401

blockout_shapes.setup(SPEC)
sc.world = bpy.data.worlds.new("sky")
sc.world.color = SKY.get(SPEC["sky"], SKY["day"])
NIGHT = SPEC["sky"] in ("night", "dusk")

rnd = random.Random(7)
if SPEC["ground"] != "none":
    box("ground", (4000, 4000, 0.1), (0, 0, -0.05), SPEC["ground"])
for item in SPEC["set"]:
    if item.get("turn") and item["type"] in ("street", "room", "city"):
        # these are built unturned (a street runs along +x from "at"); turn the finished pieces about "at",
        # the same as blockout_edit.py does, or a side street is drawn along the main street
        from mathutils import Matrix
        before = set(bpy.data.objects)
        SET[item["type"]]({**item, "turn": 0}, rnd)
        at = Vector(item["at"])
        R = Matrix.Translation(at) @ Matrix.Rotation(math.radians(item["turn"]), 4, "Z") @ Matrix.Translation(-at)
        for o in set(bpy.data.objects) - before:
            if o.parent is None:
                o.matrix_world = R @ o.matrix_world
    else:
        SET.get(item["type"], prop)(item, rnd)


# ---------------------------------------------------------------- moving along the keys
def track(keys, value):
    """A smooth curve through keyed values (Hermite: zero speed at the first and last key and where it holds still)."""
    ts = [k["t"] for k in keys]
    vs = [Vector(value(k)) for k in keys]
    n = len(keys)
    tan = []
    for i in range(n):
        if i == 0 or i == n - 1 or (vs[i] - vs[i - 1]).length < 1e-4 or (vs[i + 1] - vs[i]).length < 1e-4:
            tan.append(Vector((0, 0, 0)))
        else:
            tan.append((vs[i + 1] - vs[i - 1]) / max(1e-6, ts[i + 1] - ts[i - 1]))

    def at(t):
        if t <= ts[0]:
            return vs[0].copy()
        if t >= ts[-1]:
            return vs[-1].copy()
        i = max(j for j in range(n - 1) if ts[j] <= t)
        dt = max(1e-6, ts[i + 1] - ts[i])
        u = (t - ts[i]) / dt
        h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
        return vs[i] * h00 + tan[i] * (h10 * dt) + vs[i + 1] * h01 + tan[i + 1] * (h11 * dt)
    return at


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def stepped(keys, value):
    """A value that eases from one key to the next (poses, facings that are given)."""
    def at(t):
        if t <= keys[0]["t"]:
            return value(keys[0])
        for a, b in zip(keys, keys[1:]):
            if a["t"] <= t <= b["t"]:
                u = smooth((t - a["t"]) / max(1e-6, b["t"] - a["t"]))
                va, vb = value(a), value(b)
                return va + (vb - va) * u
        return value(keys[-1])
    return at


POSE = {  # tilt (deg, 90 = lying), sit (0..1), head pitch (deg, + = up), arm raise (deg), lean (deg)
    "stand": (0, 0, 0, 0, 0), "walk": (0, 0, 0, 0, 3), "run": (0, 0, 0, 0, 10), "sit": (0, 1, 0, 0, 0),
    "lie": (90, 0, 0, 0, 0), "look_up": (0, 0, 35, 0, 0), "look_down": (0, 0, -30, 0, 0), "wave": (0, 0, 0, 150, 0),
    "crouch": (0, 0.6, -15, 0, 15),
}
POSITIONS = {}


def animate(t, rig):
    keys = t["keys"]
    pos = track(keys, lambda k: k["at"])
    POSITIONS[t["name"]] = (pos, rig.height)
    given = [k for k in keys if k["face"] is not None]
    pose = {i: stepped(keys, lambda k, i=i: POSE.get(k["pose"], POSE["stand"])[i]) for i in range(5)}
    facing = math.radians(given[0]["face"]) if given else 0.0
    if not given:                                    # face where it goes first
        for a, b in zip(keys, keys[1:]):
            d = Vector(b["at"]) - Vector(a["at"])
            if d.xy.length > 0.05:
                facing = math.atan2(d.y, d.x)
                break
    phase, prev = 0.0, pos(0)
    stride = {"person": 1.5, "child": 1.0, "horse": 2.4, "dog": 0.9, "animal": 1.8, "cyclist": 4.0}.get(t["kind"], 1.5) * t["scale"]
    for f in range(1, FRAMES + 1):
        tt = (f - 1) / FPS
        p = pos(tt)
        move = p - prev
        speed = move.xy.length * FPS
        face_now = [k for k in given if k["t"] <= tt]
        nxt = [k for k in given if k["t"] > tt]
        if face_now and nxt:
            a, b = face_now[-1], nxt[0]
            u = smooth((tt - a["t"]) / max(1e-6, b["t"] - a["t"]))
            d = (b["face"] - a["face"] + 180) % 360 - 180
            facing = math.radians(a["face"] + d * u)
        elif face_now:
            facing = math.radians(face_now[-1]["face"])
        elif speed > 0.3:
            want = math.atan2(move.y, move.x)
            d = (want - facing + math.pi) % (2 * math.pi) - math.pi
            facing += d * 0.25                       # turn into the way it goes, not in one frame
        rig.root.location = p
        rig.root.rotation_euler = (0, 0, facing)
        rig.root.keyframe_insert("location", frame=f)
        rig.root.keyframe_insert("rotation_euler", frame=f)
        dist = move.length
        tilt, sit, look, raise_, lean = (pose[i](tt) for i in range(5))
        for hip, off, amp in rig.legs:
            if amp == -1:                            # a wheel
                hip.rotation_euler = (0, phase / max(0.2, rig.height * 0.2), 0)
            elif amp == -2:                          # a wing
                hip.rotation_euler = (0.9 * math.sin(tt * 14 + off), 0, 0)
            elif amp == -3:                          # a leg on a pedal
                hip.rotation_euler = (0, math.radians(-60) + 0.5 * math.sin(phase * 0.6 + off), 0)
            else:
                swing = amp * math.sin(phase + off) * min(1.0, speed / 0.8) if speed > 0.25 else 0.0
                hip.rotation_euler = (0, swing - math.radians(80) * sit, 0)
            hip.keyframe_insert("rotation_euler", frame=f)
        phase += dist / stride * 2 * math.pi
        if rig.body:
            rig.body.rotation_euler = (0, math.radians(lean - tilt), 0)
            rig.body.location = (0, 0, -0.45 * sit * rig.height / 1.75 + (0.15 * rig.height / 1.75 if tilt > 45 else 0))
            rig.body.keyframe_insert("rotation_euler", frame=f)
            rig.body.keyframe_insert("location", frame=f)
        if rig.head:
            rig.head.rotation_euler = (0, -math.radians(look), 0)
            rig.head.keyframe_insert("rotation_euler", frame=f)
        if rig.arm:
            rig.arm.rotation_euler = (math.radians(-raise_), 0, 0)
            rig.arm.keyframe_insert("rotation_euler", frame=f)
        prev = p


for t in SPEC["things"]:
    animate(t, build(t))


# ---------------------------------------------------------------- the camera
cam_data = bpy.data.cameras.new("cam")
cam_data.clip_end = 5000
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
aim = empty("aim")
con = cam.constraints.new("TRACK_TO")
con.target, con.track_axis, con.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
C = SPEC["camera"]
ck = C["keys"]


def target(k, tt):
    if k["follow"] and k["follow"] in POSITIONS:
        p, height = POSITIONS[k["follow"]]
        return p(tt) + Vector((0, 0, height * 0.75))
    return Vector(k["look_at"])


# a key with "cut" starts a new camera set-up: the camera jumps there (a cut between two shots of the scene)
segs = [[]]
for k in ck:
    if k.get("cut") and segs[-1]:
        segs.append([])
    segs[-1].append(k)
moves = [(sg, track(sg, lambda k: k["at"]), stepped(sg, lambda k: k["lens"] or C["lens"])) for sg in segs]
for f in range(1, FRAMES + 1):
    tt = (f - 1) / FPS
    sg, cpos, lens = next((m for m in reversed(moves) if m[0][0]["t"] <= tt), moves[0])
    r = random.Random(f)
    shake = Vector((r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-1, 1))) * C["shake"]
    cam.location = cpos(tt) + shake
    before = [k for k in sg if k["t"] <= tt] or sg[:1]
    after = [k for k in sg if k["t"] > tt] or sg[-1:]
    a, b = before[-1], after[0]
    u = smooth((tt - a["t"]) / max(1e-6, b["t"] - a["t"])) if b is not a else 0.0
    aim.location = target(a, tt).lerp(target(b, tt), u)
    cam_data.lens = lens(tt)
    cam.keyframe_insert("location", frame=f)
    aim.keyframe_insert("location", frame=f)
    cam_data.keyframe_insert("lens", frame=f)

os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- how big each thing is in the picture
# Measured from the camera as it will render: the share of the picture height between a thing's feet and its top
# (1 = the full height), and the share of the frames in which its middle is in the picture. The studio warns from it.
from bpy_extras.object_utils import world_to_camera_view
followed = sorted({k["follow"] for k in ck if k["follow"]})
seen = {n: [] for n in POSITIONS}
for f in range(1, FRAMES + 1, 6):
    sc.frame_set(f)
    tt = (f - 1) / FPS
    for n, (p, height) in POSITIONS.items():
        base = p(tt)
        lo = world_to_camera_view(sc, cam, base)
        hi = world_to_camera_view(sc, cam, base + Vector((0, 0, height)))
        mid = world_to_camera_view(sc, cam, base + Vector((0, 0, height / 2)))
        inside = mid.z > 0 and 0 <= mid.x <= 1 and 0 <= mid.y <= 1
        seen[n].append((round(abs(hi.y - lo.y), 3) if mid.z > 0 else 0.0, inside, round(mid.x, 3)))
stats = {}
for n, rows in seen.items():
    sizes = sorted(s for s, i, _ in rows if i)
    xs = sorted(x for _, i, x in rows if i)
    x = xs[len(xs) // 2] if xs else None
    stats[n] = {"followed": n in followed, "in_view": round(sum(1 for _, i, _ in rows if i) / max(1, len(rows)), 2),
                "median": sizes[len(sizes) // 2] if sizes else 0.0, "max": sizes[-1] if sizes else 0.0,
                "x": x, "side": None if x is None else "left" if x < 0.4 else "right" if x > 0.6 else "middle"}
with open(os.path.join(OUT, "stats.json"), "w") as fh:
    json.dump(stats, fh, indent=1)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "scene.blend"))
sc.render.filepath = os.path.join(OUT, "f_")
sc.render.image_settings.file_format = "PNG"
bpy.ops.render.render(animation=True)
