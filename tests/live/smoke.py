"""A live run through the studio's API on a real ComfyUI: a picture, an edit, a clip that opens on the picture, a part
that continues it, the checks, the Library. Needs the studio running (./run_studio.sh) and the models installed.

    python3 tests/live/smoke.py [--url http://127.0.0.1:8190] [--skip-video]

It renders small (864x480, 3 and 5 seconds) and takes about five minutes on an RTX 3090. Nothing is deleted afterwards:
the results are in the Library, named "smoke ...".
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8190")
ap.add_argument("--skip-video", action="store_true")
A = ap.parse_args()


def call(method, path, data=None):
    req = urllib.request.Request(A.url + path, json.dumps(data).encode() if data is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: HTTP {e.code} {e.read().decode()[:500]}")


def wait(job_id, what):
    t0 = time.time()
    last = ""
    while True:
        j = call("GET", f"/api/jobs/{job_id}")
        p = j.get("progress") or {}
        line = p.get("text", "") + (f" {p.get('value')}/{p.get('max')}" if p.get("max") else "")
        if line != last:
            print(f"   {what}: {line}", flush=True)
            last = line
        if j["status"] in ("done", "failed", "cancelled"):
            print(f"   {what}: {j['status']} in {time.time() - t0:.0f} s" + (f"  ERROR {j['error']}" if j.get("error") else ""))
            if j["status"] != "done":
                sys.exit(1)
            return j
        time.sleep(2)


def film_wait(fid, n_takes):
    """Wait until the film's last shot has a checked take."""
    while True:
        f = call("GET", f"/api/films/{fid}")
        sh = f["shots"][-1]
        if sh["status"] in ("review", "approved") and len(sh["takes"]) >= n_takes:
            return f
        if sh["status"] == "failed":
            sys.exit("shot failed: " + sh.get("error", ""))
        time.sleep(3)


m = call("GET", "/api/machine")
print("ComfyUI up:", m["comfy"]["up"], "| features:", {k: v["ok"] for k, v in m["features"].items()})
if not m["comfy"]["up"]:
    sys.exit("ComfyUI is not running")

print("1. a picture")
j = wait(call("POST", "/api/images", {"prompt": "A small wooden rowing boat tied to a jetty on a calm lake at dawn, mist over the water, photo.",
                                      "width": 1024, "height": 576, "takes": 1, "seed": 11, "name": "smoke boat"})["id"], "picture")
pic = call("GET", f"/api/library/{j['result']['assets'][0]}")
print("   ->", pic["path"], pic["width"], "x", pic["height"])

print("2. an edit of it (another view)")
j = wait(call("POST", "/api/images", {"pictures": [pic["ref"]], "angles": ["back-left"], "keep_size": True, "name": "smoke boat angle"})["id"], "edit")
print("   ->", call("GET", f"/api/library/{j['result']['assets'][0]}")["path"])

print("3. prompt check")
c = call("POST", "/api/prompt/check", {"prompt": "A man walks in. No photographs on the wall. The camera pans left on a static shot.", "new_shot": True})
print("   ->", c["summary"], [f["code"] for f in c["findings"]])

if A.skip_video:
    sys.exit(0)

print("4. a clip that opens on the picture (864x480, 73 frames)")
r = call("POST", "/api/clips", {"name": "smoke boat clip", "first_frame": pic["ref"], "width": 864, "height": 480, "frames": 73, "seed": 5,
                                "place": "A calm lake at dawn with mist over the water, a wooden jetty", "camera": "static",
                                "action": "The small wooden rowing boat rocks gently on the water. A duck swims past it from left to right.",
                                "sound": "Soft water lapping against wood, a duck quacking twice, morning birds."})
wait(r["job"]["id"], "clip")
f = film_wait(r["film"], 1)
t = f["shots"][0]["takes"][-1]
print("   -> take", t["n"], "| ok:", t["checks"]["ok"], "|", t["checks"]["summary"])
for ch in t["checks"]["checks"]:
    print("      ", ch["name"], ch["status"], "-", ch["text"])

print("5. extend it (a continuation in latent space, 124 frames)")
r2 = call("POST", f"/api/clips/{r['film']}/extend", {"action": "The duck turns around and swims back toward the boat, then dives under the water.", "frames": 124})
wait(r2["job"]["id"], "extend")
f = film_wait(r["film"], 1)
t = f["shots"][-1]["takes"][-1]
print("   -> take", t["n"], "| ok:", t["checks"]["ok"], "|", t["checks"]["summary"])
print("   full clip:", f["full"])
lib = call("GET", "/api/library?q=smoke")
print("6. library:", [(a["kind"], a["name"]) for a in lib["items"]])
print("OK")
