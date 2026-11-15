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
SKY = {"day": (0.55, 0.7, 0.9), "dusk": (0.45, 0.32, 0.36), "night": (0.05, 0.07, 0.15), "indoor": (0.22, 0.22, 0.24)}
sc.world = bpy.data.worlds.new("sky")
sc.world.color = SKY.get(SPEC["sky"], SKY["day"])
NIGHT = SPEC["sky"] in ("night", "dusk")

COLORS = {
    "red": (0.55, 0.05, 0.05), "dark red": (0.3, 0.03, 0.03), "orange": (0.8, 0.35, 0.05), "yellow": (0.85, 0.7, 0.1),
    "gold": (0.75, 0.6, 0.2), "green": (0.12, 0.45, 0.15), "dark green": (0.05, 0.22, 0.08), "blue": (0.12, 0.25, 0.6),
    "light blue": (0.4, 0.6, 0.85), "navy": (0.05, 0.08, 0.25), "purple": (0.35, 0.12, 0.45), "pink": (0.85, 0.45, 0.55),
    "white": (0.9, 0.9, 0.9), "grey": (0.45, 0.45, 0.47), "gray": (0.45, 0.45, 0.47), "dark grey": (0.18, 0.18, 0.2),
    "black": (0.04, 0.04, 0.05), "brown": (0.32, 0.2, 0.12), "light brown": (0.55, 0.4, 0.25), "beige": (0.75, 0.65, 0.5),
    "skin": (0.85, 0.62, 0.5), "brick": (0.42, 0.22, 0.16), "stone": (0.55, 0.53, 0.5), "wood": (0.45, 0.3, 0.17),
    "glass": (0.55, 0.7, 0.8), "silver": (0.7, 0.72, 0.75), "snow": (0.82, 0.84, 0.88), "grass": (0.2, 0.42, 0.15),
    "asphalt": (0.2, 0.2, 0.22), "sand": (0.76, 0.66, 0.45), "floor": (0.5, 0.42, 0.33), "water": (0.1, 0.25, 0.4),
}
_mats = {}


def mat(color):
    color = (color or "grey").strip().lower()
    if color in _mats:
        return _mats[color]
    if color.startswith("#") and len(color) == 7:
        rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    else:
        rgb = COLORS.get(color, COLORS["grey"])
    m = bpy.data.materials.new(color)
    m.diffuse_color = (*rgb, 1)
    _mats[color] = m
    return m


def add(kind, name, loc, color, parent=None, scale=(1, 1, 1), rot=(0, 0, 0), **kw):
    getattr(bpy.ops.mesh, "primitive_%s_add" % kind)(location=loc, rotation=rot, **kw)
    o = bpy.context.object
    o.name, o.scale = name, scale
    o.data.materials.append(mat(color))
    if parent:
        o.parent = parent
    return o


def box(name, size, loc, color, parent=None, rot=(0, 0, 0)):
    return add("cube", name, loc, color, parent, scale=size, rot=rot, size=1)


def cyl(name, r, depth, loc, color, parent=None, rot=(0, 0, 0)):
    return add("cylinder", name, loc, color, parent, rot=rot, radius=r, depth=depth, vertices=16)


def ball(name, r, loc, color, parent=None, scale=(1, 1, 1)):
    return add("uv_sphere", name, loc, color, parent, scale=scale, radius=r, segments=16, ring_count=8)


def cone(name, r1, r2, depth, loc, color, parent=None, rot=(0, 0, 0)):
    return add("cone", name, loc, color, parent, rot=rot, radius1=r1, radius2=r2, depth=depth, vertices=16)


def empty(name, parent=None):
    o = bpy.data.objects.new(name, None)
    sc.collection.objects.link(o)
    if parent:
        o.parent = parent
    return o


# ---------------------------------------------------------------- the set (does not move)
def windows(x0, x1, y, h, side, rnd, floor_h=3.2):
    """Rows of windows on a front that faces -side*y."""
    lit, dark = mat("#f2c060" if NIGHT else "#8fb0c8"), "dark grey"
    for fl in range(max(1, int(h // floor_h))):
        x = x0 + 1.1
        while x < x1 - 0.8:
            o = box("window", (1.0, 0.1, 1.6), (x, y, 1.6 + fl * floor_h), dark if NIGHT and rnd.random() > 0.55 else "glass")
            if NIGHT and o.data.materials[0].name != "dark grey":
                o.data.materials[0] = lit
            x += 2.2


def street(item, rnd):
    (x0, y0, z0), (length, width, height) = item["at"], item["size"]
    x1 = x0 + length
    box("road", (length, width, 0.04), (x0 + length / 2, y0, z0 + 0.02), "asphalt" if SPEC["ground"] != "snow" else "snow")
    for side in (-1, 1):
        box("pavement", (length, 2.4, 0.15), (x0 + length / 2, y0 + side * (width / 2 + 1.2), z0 + 0.075), "stone")
        x = x0
        while x < x1:
            w = rnd.uniform(6, 9)
            h = height * rnd.uniform(0.8, 1.1)
            yf = y0 + side * (width / 2 + 2.4)
            box("front", (w - 0.15, 10, h), (x + w / 2, yf + side * 5, z0 + h / 2), item["color"] or "brick")
            windows(x, x + w, yf - side * 0.05, h, side, rnd)
            x += w
        for lx in range(int(x0), int(x1), 18):
            cyl("lamp_post", 0.07, 5, (lx, y0 + side * (width / 2 + 0.6), z0 + 2.5), "black")
            ball("lamp", 0.3, (lx, y0 + side * (width / 2 + 0.2), z0 + 5.0), "#ffd870" if NIGHT else "white")


def room(item, rnd):
    (x, y, z), (w, d, h) = item["at"], item["size"]
    c = item["color"] or "beige"
    box("floor", (w, d, 0.05), (x, y, z + 0.025), "floor")
    box("back_wall", (w, 0.15, h), (x, y + d / 2, z + h / 2), c)
    box("left_wall", (0.15, d, h), (x - w / 2, y, z + h / 2), c)
    box("right_wall", (0.15, d, h), (x + w / 2, y, z + h / 2), c)
    box("window", (min(2.0, w / 3), 0.05, 1.3), (x, y + d / 2 - 0.1, z + 1.6), "#f2c060" if NIGHT else "light blue")


def building(item, rnd):
    (x, y, z), (w, d, h) = item["at"], item["size"]
    o = box("building", (w, d, h), (x, y, z + h / 2), item["color"] or "brick")
    o.rotation_euler = (0, 0, math.radians(item["turn"]))
    if not item["turn"]:
        windows(x - w / 2, x + w / 2, y - d / 2 - 0.05, h, 1, rnd)


def city(item, rnd):
    (x, y, z), (w, d, h) = item["at"], item["size"]
    for bx in range(int(x - w / 2), int(x + w / 2), 26):
        for by in range(int(y - d / 2), int(y + d / 2), 26):
            for k in range(3):
                hh = rnd.uniform(0.6, 1.0) * h
                px, py = bx + k * 7 + rnd.uniform(-0.5, 0.5), by + rnd.uniform(-2, 2)
                box("house", (6.4, 18, hh), (px, py, z + hh / 2), item["color"] or "brick")
                box("roof", (4.6, 18.2, 4.6), (px, py, z + hh), "snow" if SPEC["ground"] == "snow" else "dark red",
                    rot=(0, math.radians(45), 0))
            box("lit_street", (26, 1.0, 0.1), (bx + 10, by + 13, z + 0.05), "#ffd870" if NIGHT else "asphalt")


def prop(item, rnd):
    (x, y, z), (a, b, c) = item["at"], item["size"]
    t, col, rot = item["type"], item["color"] or "grey", (0, 0, math.radians(item["turn"]))
    if t in ("box", "wall"):
        box(item["name"] or t, (a, b, c), (x, y, z + c / 2), col, rot=rot)
    elif t == "cylinder":
        add("cylinder", item["name"] or t, (x, y, z + c / 2), col, scale=(a / 2, b / 2, c), rot=rot, radius=1, depth=1, vertices=24)
    elif t == "ball":
        add("uv_sphere", item["name"] or t, (x, y, z + c / 2), col, scale=(a / 2, b / 2, c / 2), radius=1, segments=24, ring_count=12)
    elif t == "cone":
        add("cone", item["name"] or t, (x, y, z + c / 2), col, scale=(a / 2, b / 2, c), radius1=1, radius2=0, depth=1, vertices=24)
    elif t == "tree":
        cyl("trunk", 0.15 * a, c * 0.35, (x, y, z + c * 0.175), "wood")
        cone("crown", a / 2, 0, c * 0.75, (x, y, z + c * 0.6), col if item["color"] else "dark green")


SET = {"street": street, "room": room, "building": building, "city": city}
rnd = random.Random(7)
if SPEC["ground"] != "none":
    box("ground", (4000, 4000, 0.1), (0, 0, -0.05), SPEC["ground"])
for item in SPEC["set"]:
    SET.get(item["type"], prop)(item, rnd)


# ---------------------------------------------------------------- the things that move
class Rig:
    """A thing built facing its local +x with its origin on the ground. legs: hips that swing; head, body, arm: posed."""
    def __init__(self, root):
        self.root, self.legs, self.body, self.head, self.arm, self.height = root, [], None, None, None, 1.0


def person(name, color, s, child=False):
    k = 0.7 * s if child else s
    r = Rig(empty(name))
    r.body = empty(name + "_body", r.root)
    for side in (-0.11, 0.11):
        hip = empty("hip", r.body)
        hip.location = (0, side * k, 0.9 * k)
        cyl("leg", 0.08 * k, 0.88 * k, (0, 0, -0.45 * k), "dark grey", hip)
        box("shoe", (0.28 * k, 0.11 * k, 0.08 * k), (0.06 * k, 0, -0.88 * k), "black", hip)
        r.legs.append((hip, 0 if side < 0 else math.pi, 0.42))
    cone("torso", 0.3 * k, 0.2 * k, 0.75 * k, (0, 0, 1.25 * k), color, r.body)
    r.head = empty(name + "_head", r.body)
    r.head.location = (0, 0, 1.62 * k)
    ball("face", 0.12 * k, (0, 0, 0.06 * k), "skin", r.head, scale=(1, 0.9, 1.15))
    box("nose", (0.06 * k, 0.04 * k, 0.05 * k), (0.12 * k, 0, 0.06 * k), "skin", r.head)    # shows where the face looks
    arm = empty("arm", r.body)
    arm.location = (0, 0.27 * k, 1.5 * k)
    cyl("upper_arm", 0.055 * k, 0.6 * k, (0, 0, -0.3 * k), color, arm)
    other = empty("arm2", r.body)
    other.location = (0, -0.27 * k, 1.5 * k)
    cyl("upper_arm", 0.055 * k, 0.6 * k, (0, 0, -0.3 * k), color, other)
    r.arm, r.height = arm, 1.75 * k
    return r


def vehicle(name, color, s, kind):
    dims = {"car": (4.4, 1.8, 1.45), "van": (5.2, 2.0, 2.3), "truck": (8.0, 2.5, 3.3), "bus": (12, 2.55, 3.2),
            "tram": (30, 2.4, 3.4), "train": (60, 3.0, 4.0)}[kind]
    L, Wd, Ht = (d * s for d in dims)
    r = Rig(empty(name))
    r.body = empty(name + "_body", r.root)
    low = 0.35 * s
    if kind in ("tram", "train"):
        cars = 3 if kind == "tram" else 4
        for i in range(cars):
            seg = L / cars
            x = -L / 2 + seg * (i + 0.5)
            box("car", (seg - 0.3 * s, Wd, Ht - low), (x, 0, low + (Ht - low) / 2), color, r.body)
            box("windows", (seg - 1.2 * s, Wd + 0.04, 0.9 * s), (x, 0, low + (Ht - low) * 0.62), "glass", r.body)
        if kind == "tram":
            cyl("pole", 0.04 * s, 1.6 * s, (0, 0, Ht + 0.6 * s), "black", r.body, rot=(0, math.radians(35), 0))
        r.height = Ht
        return r
    box("chassis", (L, Wd, Ht * 0.45), (0, 0, low + Ht * 0.225), color, r.body)
    cab_l = L * (0.5 if kind == "car" else 0.28)
    cab_x = 0 if kind == "car" else L / 2 - cab_l / 2
    box("cabin", (cab_l, Wd * 0.92, Ht * 0.5), (cab_x - (0.1 * L if kind == "car" else 0), 0, low + Ht * 0.7), "glass" if kind == "car" else color, r.body)
    if kind in ("truck", "van", "bus"):
        box("cargo", (L - cab_l, Wd, Ht - low), (-cab_l / 2, 0, low + (Ht - low) / 2), color, r.body)
    for wx in (L * 0.32, -L * 0.32):
        for wy in (Wd / 2, -Wd / 2):
            hub = empty("wheel", r.body)
            hub.location = (wx, wy, low)
            cyl("tyre", low, 0.25 * s, (0, 0, 0), "black", hub, rot=(math.radians(90), 0, 0))
            box("spoke", (low * 1.6, 0.27 * s, 0.08 * s), (0, 0, 0), "silver", hub)
            r.legs.append((hub, 0, -1))              # -1: a wheel, it rolls with the distance
    r.height = Ht
    return r


def bike(name, color, s):
    r = Rig(empty(name))
    r.body = empty(name + "_body", r.root)
    for wx in (0.55 * s, -0.55 * s):
        hub = empty("wheel", r.body)
        hub.location = (wx, 0, 0.35 * s)
        cyl("tyre", 0.35 * s, 0.05 * s, (0, 0, 0), "black", hub, rot=(math.radians(90), 0, 0))
        box("spoke", (0.6 * s, 0.06 * s, 0.04 * s), (0, 0, 0), "silver", hub)
        r.legs.append((hub, 0, -1))
    box("frame", (1.1 * s, 0.06 * s, 0.06 * s), (0, 0, 0.65 * s), color, r.body, rot=(0, math.radians(-10), 0))
    box("bars", (0.06 * s, 0.6 * s, 0.06 * s), (0.5 * s, 0, 1.0 * s), "black", r.body)
    r.height = 1.1 * s
    return r


def cyclist(name, color, s):
    """A bike with its rider, who pedals while it moves."""
    r = bike(name, "dark grey", s)
    rider = person(name + "_rider", color, s)
    rider.root.parent = r.body
    rider.root.location = (-0.15 * s, 0, 0.12 * s)
    rider.body.rotation_euler = (0, math.radians(25), 0)          # leaning onto the bars (+y tips the top toward +x, forward)
    for hip, off, amp in rider.legs:
        hip.rotation_euler = (0, math.radians(-60), 0)
        r.legs.append((hip, off, -3))                             # -3: a pedalling leg
    r.head, r.arm, r.height = rider.head, rider.arm, 1.75 * s
    return r


def animal(name, color, s, kind):
    dims = {"horse": (2.0, 0.55, 0.9, 0.8), "dog": (0.75, 0.25, 0.35, 0.3), "animal": (1.3, 0.42, 0.5, 0.55)}[kind]
    L, Wd, Bh, leg = (d * s for d in dims)
    r = Rig(empty(name))
    r.body = empty(name + "_body", r.root)
    box("body", (L, Wd, Bh), (0, 0, leg + Bh / 2), color, r.body)
    box("neck", (0.25 * L, Wd * 0.5, Bh * 1.1), (L * 0.5, 0, leg + Bh), color, r.body, rot=(0, math.radians(30), 0))
    r.head = empty(name + "_head", r.body)
    r.head.location = (L * 0.62, 0, leg + Bh * 1.55)
    box("head", (L * 0.3, Wd * 0.55, Bh * 0.45), (L * 0.1, 0, 0), color, r.head)
    for lx in (L * 0.38, -L * 0.38):
        for ly in (Wd * 0.35, -Wd * 0.35):
            hip = empty("hip", r.body)
            hip.location = (lx, ly, leg)
            box("leg", (0.12 * Wd + 0.05 * s, 0.12 * Wd + 0.05 * s, leg), (0, 0, -leg / 2), color, hip)
            r.legs.append((hip, (0 if lx > 0 else math.pi) + (0 if ly > 0 else math.pi / 2), 0.6))
    box("tail", (L * 0.25, 0.06 * s, 0.06 * s), (-L * 0.6, 0, leg + Bh * 0.8), color, r.body, rot=(0, math.radians(-30), 0))
    r.height = leg + Bh * 1.6
    return r


def other(name, color, s, kind):
    r = Rig(empty(name))
    r.body = empty(name + "_body", r.root)
    if kind == "box":
        box("box", (s, s, s), (0, 0, s / 2), color, r.body)
        r.height = s
    elif kind == "ball":
        ball("ball", 0.25 * s, (0, 0, 0.25 * s), color, r.body)
        r.height = 0.5 * s
    elif kind == "sled":
        box("sled", (2.6 * s, 1.5 * s, 0.7 * s), (0, 0, 0.7 * s), color, r.body)
        box("back", (0.25 * s, 1.5 * s, 1.0 * s), (-1.2 * s, 0, 1.2 * s), color, r.body)
        for side in (-0.6, 0.6):
            box("runner", (3.4 * s, 0.08 * s, 0.08 * s), (0.1 * s, side * s, 0.04 * s), "gold", r.body)
        r.height = 1.5 * s
    elif kind == "boat":
        box("hull", (6 * s, 2.2 * s, 1.0 * s), (0, 0, 0.3 * s), color, r.body)
        cone("bow", 1.1 * s, 0, 1.6 * s, (3.6 * s, 0, 0.3 * s), color, r.body, rot=(0, math.radians(90), 0))
        box("cabin", (2 * s, 1.6 * s, 1.2 * s), (-0.8 * s, 0, 1.4 * s), "white", r.body)
        r.height = 2 * s
    elif kind == "plane":
        cyl("fuselage", 1.6 * s, 30 * s, (0, 0, 0), color, r.body, rot=(0, math.radians(90), 0))
        box("wings", (5 * s, 32 * s, 0.4 * s), (1 * s, 0, 0), color, r.body)
        box("fin", (3 * s, 0.3 * s, 5 * s), (-13 * s, 0, 2.5 * s), color, r.body)
        r.height = 4 * s
    elif kind == "bird":
        ball("bird", 0.12 * s, (0, 0, 0), color, r.body, scale=(1.6, 1, 1))
        for side in (-1, 1):
            hip = empty("wing", r.body)
            hip.location = (0, side * 0.1 * s, 0)
            box("wing", (0.2 * s, 0.4 * s, 0.02 * s), (0, side * 0.2 * s, 0), color, hip)
            r.legs.append((hip, 0 if side > 0 else math.pi, -2))      # -2: a wing, it flaps
        r.height = 0.3 * s
    return r


def build(t):
    k, c, s = t["kind"], t["color"] or ("brown" if t["kind"] in ("person", "child", "cyclist", "horse", "dog", "animal") else "red"), t["scale"]
    if k in ("person", "child"):
        return person(t["name"], c, s, child=k == "child")
    if k in ("car", "van", "truck", "bus", "tram", "train"):
        return vehicle(t["name"], c, s, k)
    if k == "bike":
        return bike(t["name"], c, s)
    if k == "cyclist":
        return cyclist(t["name"], c, s)
    if k in ("horse", "dog", "animal"):
        return animal(t["name"], c, s, k)
    return other(t["name"], c, s, k)


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
