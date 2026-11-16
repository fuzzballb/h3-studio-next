# Opens a blockout scene (studio/blockouts.py) in Blender's own window to edit it by hand, and sends it back:
#   blender -P blockout_edit.py -- <scene.json> <frames> <width> <height> <studio url> <blockout id> <file.blend>
#
# Every set piece and every moving thing is ONE object you can click, move, turn and scale. A thing's keys are
# keyframes at the scene's key times (location, and the turn about z); the camera is the object "Camera", which
# looks at the object "Camera aim"; both are keyed at the camera's keys, and the lens in the camera's data.
# Press "Send to H3 Studio" in the sidebar (N → H3 Studio) or save (Ctrl+S): the scene is read back from the
# objects and keyframes and sent to the studio, which shows it in its 3D view.
# Read back: positions, turns, sizes (scale), key times, new keys, deleted or renamed objects, the camera path,
# its aim and lens, and new plain meshes (as boxes). Poses, kinds and colours are changed in the studio.
import json
import math
import os
import random
import sys
import urllib.request

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC = json.load(open(argv[0], encoding="utf-8"))
FRAMES, W, H, URL, BID, BLEND = int(argv[1]), int(argv[2]), int(argv[3]), argv[4], argv[5], argv[6]
FPS = 24

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blockout_shapes as S  # noqa: E402

frame_of = lambda t: 1 + round(t * FPS)                                     # noqa: E731
time_of = lambda f: round((f - 1) / FPS, 3)                                  # noqa: E731

# a clean scene with the studio's settings
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
sc = bpy.context.scene
S.setup(SPEC)
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, FRAMES
sc.frame_set(1)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.engine = "BLENDER_WORKBENCH"
sc.world = sc.world or bpy.data.worlds.new("sky")
sc.world.color = S.SKY.get(SPEC["sky"], S.SKY["day"])
sc["h3_scene"] = json.dumps({"sky": SPEC["sky"], "ground": SPEC["ground"]})


def joined(name, make):
    """Run make() (it builds objects around the origin), then join every mesh it made into one object named name."""
    before = set(bpy.data.objects)
    make()
    made = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in made if o.type == "MESH"]
    for o in meshes:                                   # bake each part's place into its mesh, then drop the parents
        mw = o.matrix_world.copy()
        o.data = o.data.copy()
        o.data.transform(mw)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in made:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    if not meshes:
        ob = bpy.data.objects.new(name, None)
        sc.collection.objects.link(ob)
        return ob
    with bpy.context.temp_override(active_object=meshes[0], selected_editable_objects=meshes, object=meshes[0]):
        bpy.ops.object.join()
    ob = meshes[0]
    ob.name = name
    return ob


# ---------------------------------------------------------------- the set: one object per piece, origin at its "at"
rnd = random.Random(7)
if SPEC["ground"] != "none":
    g = S.box("ground (not sent)", (4000, 4000, 0.1), (0, 0, -0.05), SPEC["ground"])
    g.hide_select = True
for i, item in enumerate(SPEC["set"]):
    flat = {**item, "at": [0, 0, 0], "turn": 0}
    build = S.SET.get(item["type"], S.prop)
    ob = joined(f"Set {i + 1}: {item['name'] or item['type']}", lambda: build(flat, rnd))
    ob.location = item["at"]
    ob.rotation_euler = (0, 0, math.radians(item["turn"]))
    ob["h3_set"] = json.dumps({k: item[k] for k in ("type", "name", "color", "size")})


# ---------------------------------------------------------------- the things: keyed at their keys
def hermite(keys):
    ts = [k["t"] for k in keys]
    vs = [Vector(k["at"]) for k in keys]
    n = len(keys)
    tan = [Vector((0, 0, 0)) if i in (0, n - 1) or (vs[i] - vs[i - 1]).length < 1e-4 or (vs[i + 1] - vs[i]).length < 1e-4
           else (vs[i + 1] - vs[i - 1]) / max(1e-6, ts[i + 1] - ts[i - 1]) for i in range(n)]

    def at(t):
        if t <= ts[0]:
            return vs[0]
        if t >= ts[-1]:
            return vs[-1]
        i = max(j for j in range(n - 1) if ts[j] <= t)
        dt = max(1e-6, ts[i + 1] - ts[i])
        u = (t - ts[i]) / dt
        return (vs[i] * (2 * u ** 3 - 3 * u ** 2 + 1) + tan[i] * ((u ** 3 - 2 * u ** 2 + u) * dt) + vs[i + 1] * (-2 * u ** 3 + 3 * u ** 2)
                + tan[i + 1] * ((u ** 3 - u ** 2) * dt))
    return at


def auto_face(pos, t, first):
    for k in range(40):
        tt = t - k * 0.2
        d = pos(tt + 0.1) - pos(tt - 0.1)
        if d.xy.length > 0.02:
            return math.degrees(math.atan2(d.y, d.x))
        if tt < 0:
            break
    return first


POS = {}
for t in SPEC["things"]:
    rig_parts = {}
    ob = joined(t["name"], lambda: rig_parts.setdefault("rig", S.build(t)))
    rig = rig_parts["rig"]
    keys = t["keys"]
    pos = hermite(keys)
    POS[t["name"]] = (pos, rig.height)
    first = 0.0
    for a, b in zip(keys, keys[1:]):
        d = Vector(b["at"]) - Vector(a["at"])
        if d.xy.length > 0.05:
            first = math.degrees(math.atan2(d.y, d.x))
            break
    meta = []
    prev_face = None
    for k in keys:
        f = frame_of(k["t"])
        auto = auto_face(pos, k["t"], first)
        face = k["face"] if k["face"] is not None else auto
        if prev_face is not None:                                  # turn the short way round
            face = prev_face + ((face - prev_face + 180) % 360 - 180)
        prev_face = face
        ob.location = k["at"]
        ob.rotation_euler = (0, 0, math.radians(face))
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_euler", index=2, frame=f)
        meta.append({"t": k["t"], "face": k["face"], "auto": face, "pose": k["pose"]})
    ob["h3_thing"] = json.dumps({"name": t["name"], "kind": t["kind"], "color": t["color"], "scale": t["scale"], "driver": t.get("driver", ""), "keys": meta})
    ob["h3_height"] = rig.height

# ---------------------------------------------------------------- the camera and its aim
C = SPEC["camera"]
cam_data = bpy.data.cameras.new("Camera")
cam_data.clip_end = 5000
cam = bpy.data.objects.new("Camera", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
aim = bpy.data.objects.new("Camera aim", None)
aim.empty_display_type, aim.empty_display_size = "SPHERE", 0.4
sc.collection.objects.link(aim)
con = cam.constraints.new("TRACK_TO")
con.target, con.track_axis, con.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
cmeta = []
for k in C["keys"]:
    f = frame_of(k["t"])
    if k["follow"] and k["follow"] in POS:
        p, height = POS[k["follow"]]
        look = p(k["t"]) + Vector((0, 0, height * 0.75))
    else:
        look = Vector(k["look_at"])
    cam.location = k["at"]
    cam.keyframe_insert("location", frame=f)
    aim.location = look
    aim.keyframe_insert("location", frame=f)
    cam_data.lens = k["lens"] or C["lens"]
    cam_data.keyframe_insert("lens", frame=f)
    cmeta.append({"t": k["t"], "follow": k["follow"], "look": list(look), "look_at": k["look_at"], "lens": k["lens"], "cut": k["cut"]})
cam["h3_camera"] = json.dumps({"lens": C["lens"], "shake": C["shake"], "keys": cmeta})


# ---------------------------------------------------------------- reading it back
def fcurves(idb):
    """The F-curves of an object or camera data (Blender 4 and 5: actions with or without layers)."""
    ad = getattr(idb, "animation_data", None)
    act = ad and ad.action
    if not act:
        return []
    if hasattr(act, "fcurves") and act.fcurves:
        return list(act.fcurves)
    out = []
    try:
        slot = ad.action_slot
        for layer in act.layers:
            for strip in layer.strips:
                cb = strip.channelbag(slot) if slot else None
                if cb:
                    out += list(cb.fcurves)
    except AttributeError:
        pass
    return out


def key_frames(*idbs, paths=None):
    fr = set()
    for idb in idbs:
        for fc in fcurves(idb):
            if paths is None or fc.data_path in paths:
                fr.update(round(p.co[0]) for p in fc.keyframe_points)
    return sorted(fr)


def value(idb, path, index, frame, default):
    for fc in fcurves(idb):
        if fc.data_path == path and fc.array_index == index:
            return fc.evaluate(frame)
    return default


def near(meta, t, eps=0.6 / FPS):
    return next((m for m in meta if abs(m["t"] - t) <= eps), None)


def colour_of(ob):
    m = ob.active_material
    if not m:
        return ""
    r, g, b = (max(0.0, min(1.0, c)) for c in m.diffuse_color[:3])
    return "#%02x%02x%02x" % tuple(round(255 * (c ** (1 / 2.2))) for c in (r, g, b))


def read_back():
    base = json.loads(sc.get("h3_scene") or "{}")
    out = {"sky": base.get("sky", "day"), "ground": base.get("ground", "grass"), "set": [], "things": [], "camera": {}}
    renamed = {}
    for ob in sc.objects:
        if ob.get("h3_set"):
            it = json.loads(ob["h3_set"])
            out["set"].append({"type": it["type"], "name": it["name"], "color": it["color"],
                               "at": [round(v, 3) for v in ob.location], "turn": round(math.degrees(ob.rotation_euler.z), 2),
                               "size": [round(s * abs(f), 3) for s, f in zip(it["size"], ob.scale)]})
        elif ob.get("h3_thing"):
            th = json.loads(ob["h3_thing"])
            name = ob.name.strip() or th["name"]
            renamed[th["name"]] = name
            frames = key_frames(ob, paths={"location", "rotation_euler"}) or [sc.frame_current]
            rot_frames = set()
            for fc in fcurves(ob):
                if fc.data_path == "rotation_euler" and fc.array_index == 2:
                    rot_frames.update(round(p.co[0]) for p in fc.keyframe_points)
            keys, pose = [], th["keys"][0]["pose"] if th["keys"] else "stand"
            for f in frames:
                t = max(0.0, time_of(f))
                at = [round(value(ob, "location", i, f, ob.location[i]), 3) for i in range(3)]
                rot = math.degrees(value(ob, "rotation_euler", 2, f, ob.rotation_euler.z))
                m = near(th["keys"], t)
                if m:
                    pose = m["pose"]
                    face = None if m["face"] is None and abs(rot - m["auto"]) < 0.5 else round(rot, 1)
                else:
                    face = round(rot, 1) if f in rot_frames else None
                keys.append({"t": t, "at": at, "face": face, "pose": pose})
            sc_x = abs(ob.scale.x) if ob.scale.x else 1
            out["things"].append({"name": name, "kind": th["kind"], "color": th["color"], "scale": round(th["scale"] * sc_x, 3),
                                  "driver": th.get("driver", ""), "keys": keys})
        elif ob.type == "MESH" and not ob.hide_select and ob.name != "Camera":   # a mesh made here: a box
            bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
            hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
            out["set"].append({"type": "box", "name": ob.name[:60], "color": colour_of(ob), "turn": 0,
                               "at": [round((lo.x + hi.x) / 2, 3), round((lo.y + hi.y) / 2, 3), round(lo.z, 3)],
                               "size": [round(max(0.05, hi.x - lo.x), 3), round(max(0.05, hi.y - lo.y), 3), round(max(0.05, hi.z - lo.z), 3)]})
    cam_ob = sc.objects.get("Camera")
    aim_ob = sc.objects.get("Camera aim")
    cm = json.loads(cam_ob["h3_camera"]) if cam_ob and cam_ob.get("h3_camera") else {"lens": 35, "shake": 0, "keys": []}
    names = {t["name"] for t in out["things"]}
    keys = []
    if cam_ob:
        data = cam_ob.data
        frames = key_frames(cam_ob, aim_ob, data) if aim_ob else key_frames(cam_ob, data)
        for f in frames or [1]:
            t = max(0.0, time_of(f))
            at = [round(value(cam_ob, "location", i, f, cam_ob.location[i]), 3) for i in range(3)]
            look = [round(value(aim_ob, "location", i, f, aim_ob.location[i]), 3) for i in range(3)] if aim_ob else [0, 0, 0]
            lens = value(data, "lens", 0, f, data.lens)
            m = near(cm["keys"], t)
            follow = ""
            if m and m["follow"] and (Vector(look) - Vector(m["look"])).length < 0.02:
                follow = renamed.get(m["follow"], m["follow"])
            if follow not in names:
                follow = ""
            if (Vector(at) - Vector(look)).length < 1e-3:
                look = [look[0] + 1, look[1], look[2]]
            keys.append({"t": t, "at": at, "look_at": m["look_at"] if follow else look, "follow": follow,
                         "lens": 0 if m and not m["lens"] and abs(lens - cm["lens"]) < 0.01 else round(lens, 2),
                         "cut": bool(m and m["cut"])})
    out["camera"] = {"lens": cm["lens"], "shake": cm["shake"], "keys": keys}
    return out


def send():
    scene = read_back()
    req = urllib.request.Request(f"{URL}/api/blockouts/{BID}/from_blender", data=json.dumps({"scene": scene}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


class H3_OT_send(bpy.types.Operator):
    bl_idname = "h3.send_blockout"
    bl_label = "Send to H3 Studio"
    bl_description = "Read the scene back from the objects and their keyframes and send it to the studio"

    def execute(self, context):
        try:
            r = send()
        except Exception as e:                       # the studio is not running, or it refused the scene
            self.report({"ERROR"}, f"Not sent: {e}")
            return {"CANCELLED"}
        err = (r.get("state") or {}).get("error")
        self.report({"WARNING"} if err else {"INFO"}, f"Sent to H3 Studio, but: {err}" if err else "Sent to H3 Studio")
        return {"FINISHED"}


class H3_PT_panel(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category, bl_label = "VIEW_3D", "UI", "H3 Studio", "H3 Studio blockout"

    def draw(self, context):
        col = self.layout.column()
        col.operator("h3.send_blockout", icon="EXPORT")
        for line in ("Saving (Ctrl+S) sends it too.", "Move, turn and scale objects;", "insert keys (I) at other frames", "for new keys. The camera looks", "at 'Camera aim'. Poses, kinds and", "colours: change them in the studio."):
            col.label(text=line)


def on_save(_):
    try:
        send()
    except Exception as e:
        print("H3 Studio: not sent:", e)


bpy.utils.register_class(H3_OT_send)
bpy.utils.register_class(H3_PT_panel)
bpy.app.handlers.save_post.append(on_save)


def show():
    """Look through the camera, open the H3 Studio tab in the sidebar, and save the file so Ctrl+S works."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.type = "SOLID"
                space.shading.color_type = "MATERIAL"
                space.show_region_ui = True
                space.region_3d.view_perspective = "CAMERA"
                for region in area.regions:
                    if region.type == "UI":
                        try:
                            region.active_panel_category = "H3 Studio"
                        except (AttributeError, TypeError):
                            pass
    bpy.app.handlers.save_post.remove(on_save)          # the first save is ours, not the user's
    try:
        bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    finally:
        bpy.app.handlers.save_post.append(on_save)
    return None


if os.environ.get("H3_BLOCKOUT_DUMP"):                   # tests: read the scene straight back, write it, stop
    if os.environ.get("H3_BLOCKOUT_EDITS"):              # tests only: edits made as a person would, before reading back
        exec(open(os.environ["H3_BLOCKOUT_EDITS"]).read())
    with open(os.environ["H3_BLOCKOUT_DUMP"], "w") as fh:
        json.dump(read_back(), fh)
elif not bpy.app.background:
    bpy.app.timers.register(show, first_interval=0.5)
