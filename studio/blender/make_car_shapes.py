"""Writes studio/static/car_shapes.json: the car shapes of a blockout, read by both Blender (blockout_shapes.py) and the
studio's 3D view (static/blockout.js), so the two always draw the same car. Run it after changing a shape:
    python3 studio/blender/make_car_shapes.py

A car faces +x with its origin on the ground, in metres at scale 1. Parts:
  {"p": "prism", "pts": [[x, z], ...], "w": width, "y": middle, "c": colour}   a side profile pushed out across y
  {"p": "box", "s": [x, y, z], "at": [x, y, z], "c": colour}
  {"p": "disc", "r": radius, "w": thickness, "at": [x, y, z], "c": colour}    faces +x (a steering wheel)
  {"p": "wheel", "r": radius, "w": width, "at": [x, y, z]}                     turns about y; it rolls
Colour "body" is the thing's own colour; "tinted glass" is see-through. "seat": where the driver sits (the hip), on
the left (+y), facing +x; "wheel_at": the steering wheel.
"""
import json
import os

# kind: length, width, height, wheel radius, wheelbase, ground clearance, nose height, tail height, belt (bottom of the
# windows), windscreen base x, roof front x, roof back x, rear window base x
SHAPES = {
    "car":        (4.70, 1.82, 1.45, 0.33, 2.80, 0.16, 0.72, 0.88, 0.95, 0.55, -0.05, -1.00, -1.55),
    "coupe":      (4.55, 1.85, 1.35, 0.34, 2.70, 0.14, 0.66, 0.80, 0.88, 0.50, -0.15, -0.80, -1.65),
    "sports car": (4.50, 1.95, 1.20, 0.34, 2.60, 0.11, 0.55, 0.76, 0.80, 0.35, -0.35, -0.85, -1.80),
    "suv":        (4.80, 1.95, 1.75, 0.40, 2.85, 0.25, 0.95, 1.05, 1.15, 0.95, 0.35, -2.05, -2.32),
    "pickup":     (5.40, 2.00, 1.85, 0.42, 3.40, 0.28, 1.05, 1.20, 1.20, 1.15, 0.60, -0.45, -0.50),
}
ABOUT = {"car": "a saloon", "coupe": "a two-door coupe with a sloping back", "sports car": "a low, wide sports car with a spoiler",
         "suv": "a tall SUV with roof rails", "pickup": "a pickup truck with an open bed"}


def r3(v):
    return [round(x, 3) for x in v]


def shape(kind):
    L, W, H, r, wb, zc, nose, tail, belt, xw, xrf, xrb, xr = SHAPES[kind]
    f, b = L / 2, -L / 2
    parts = []
    back = -0.55 if kind == "pickup" else b                       # where the closed body ends (the pickup's bed follows)
    tail_z = belt if kind == "pickup" else tail
    body = [[back, zc + 0.1], [back + 0.15, zc], [f - 0.15, zc], [f, zc + 0.1], [f, nose], [xw, belt], [xr, belt], [back, tail_z]]
    parts.append({"p": "prism", "pts": [r3(p) for p in body], "w": W, "y": 0, "c": "body"})
    # the windows: one see-through block from the belt to the roof, then the roof, the pillars and the frame on top
    parts.append({"p": "prism", "pts": [r3(p) for p in ([xw, belt], [xrf, H - 0.04], [xrb, H - 0.04], [xr, belt])], "w": W * 0.84, "y": 0, "c": "tinted glass"})
    parts.append({"p": "box", "s": r3([xrf - xrb + 0.06, W * 0.86, 0.06]), "at": r3([(xrf + xrb) / 2, 0, H - 0.03]), "c": "body"})
    for side in (1, -1):
        y = side * W * 0.42
        parts.append({"p": "prism", "pts": [r3(p) for p in ([xw + 0.02, belt], [xrf + 0.02, H - 0.02], [xrf - 0.1, H - 0.02], [xw - 0.12, belt])], "w": 0.08, "y": round(y, 3), "c": "body"})
        parts.append({"p": "prism", "pts": [r3(p) for p in ([xr - 0.02, belt], [xrb - 0.02, H - 0.02], [xrb + 0.14, H - 0.02], [xr + 0.2, belt])], "w": 0.08, "y": round(y, 3), "c": "body"})
        if kind in ("car", "suv"):                                   # four doors: a pillar in the middle
            bx = (xw + xr) / 2 + 0.1
            parts.append({"p": "box", "s": [0.1, 0.08, round(H - belt, 3)], "at": r3([bx, y, (H + belt) / 2]), "c": "body"})
        # lights, mirrors
        parts.append({"p": "box", "s": [0.06, round(W * 0.2, 3), 0.1], "at": r3([f - 0.01, side * W * 0.33, nose - 0.09]), "c": "headlight"})
        parts.append({"p": "box", "s": [0.06, round(W * 0.2, 3), 0.1], "at": r3([back + 0.01, side * W * 0.33, tail_z - 0.1]), "c": "taillight"})
        parts.append({"p": "box", "s": [0.12, 0.17, 0.09], "at": r3([xw - 0.05, side * (W / 2 + 0.07), belt + 0.07]), "c": "body"})
        for wx in (wb / 2, -wb / 2):
            parts.append({"p": "wheel", "r": r, "w": 0.24, "at": r3([wx, side * (W / 2 - 0.13), r])})
    parts.append({"p": "box", "s": [0.04, round(W * 0.38, 3), 0.15], "at": r3([f + 0.005, 0, nose - 0.2]), "c": "black"})          # grille
    for x in (f + 0.02, back - 0.02):                                                                                        # bumpers
        parts.append({"p": "box", "s": [0.1, round(W * 0.98, 3), 0.14], "at": r3([x, 0, zc + 0.14]), "c": "dark grey"})
    # inside: two front seats and the steering wheel (seen through the windows)
    hip = H - 0.88
    sx = xw - 0.75
    for side in (1, -1):
        parts.append({"p": "box", "s": [0.5, 0.48, 0.12], "at": r3([sx, side * W * 0.22, hip - 0.06]), "c": "dark grey"})
        parts.append({"p": "box", "s": [0.12, 0.48, 0.66], "at": r3([sx - 0.28, side * W * 0.22, hip + 0.3]), "c": "dark grey"})
    wheel_at = r3([sx + 0.42, W * 0.22, hip + 0.42])
    parts.append({"p": "disc", "r": 0.19, "w": 0.04, "at": wheel_at, "c": "black"})
    if kind == "sports car":                                   # the spoiler
        parts.append({"p": "box", "s": [0.28, round(W * 0.9, 3), 0.04], "at": r3([b + 0.22, 0, tail + 0.24]), "c": "body"})
        for y in (0.5, -0.5):
            parts.append({"p": "box", "s": [0.07, 0.05, 0.22], "at": r3([b + 0.22, y, tail + 0.11]), "c": "black"})
    if kind == "suv":                                          # roof rails
        for y in (W * 0.38, -W * 0.38):
            parts.append({"p": "box", "s": r3([xrf - xrb - 0.2, 0.05, 0.06]), "at": r3([(xrf + xrb) / 2, y, H + 0.03]), "c": "silver"})
    if kind == "pickup":                                       # the open bed: under it, its floor, sides and tailgate
        bl = back - b
        bxm = (back + b) / 2
        parts.append({"p": "box", "s": r3([bl, W, 0.75 - zc]), "at": r3([bxm, 0, zc + (0.75 - zc) / 2]), "c": "body"})
        parts.append({"p": "box", "s": r3([bl, W * 0.92, 0.04]), "at": r3([bxm, 0, 0.77]), "c": "dark grey"})
        for y in (W / 2 - 0.04, -(W / 2 - 0.04)):
            parts.append({"p": "box", "s": r3([bl, 0.08, belt - 0.75]), "at": r3([bxm, y, (belt + 0.75) / 2]), "c": "body"})
        parts.append({"p": "box", "s": r3([0.08, W, belt - 0.75]), "at": r3([b + 0.04, 0, (belt + 0.75) / 2]), "c": "body"})
    return {"size": [L, W, H], "about": ABOUT[kind], "parts": parts, "seat": r3([sx, W * 0.22, hip]), "wheel_at": wheel_at}


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "car_shapes.json")
    with open(out, "w") as fh:
        json.dump({k: shape(k) for k in SHAPES}, fh, separators=(",", ":"))
    print("wrote", os.path.normpath(out))
