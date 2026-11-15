#!/usr/bin/env python3
"""H3 Studio as MCP tools, for an agent (Claude Code, or any MCP client).

    claude mcp add h3-studio -- python3 /path/to/h3_studio/mcp/studio_mcp.py
    STUDIO_URL=http://127.0.0.1:8191   (the default)

A thin layer over the studio's HTTP API (docs/api.md): every tool is one or two calls to it, so everything an agent
renders goes through the studio's queue, is checked like any other take and lands in the Library. Standard library
only; talks MCP over stdin/stdout (JSON-RPC 2.0, one message a line).

Tools that render take "wait" (default true): they return when the job is done, with the files it made as absolute
paths, so the agent can look at a picture or a contact sheet before it goes on.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("STUDIO_URL", "http://127.0.0.1:8191").rstrip("/")
VERSION = "1.0"
_paths = None


class ToolError(Exception):
    pass


def call(method, path, data=None, timeout=60):
    req = urllib.request.Request(URL + path, json.dumps(data).encode() if data is not None else None,
                                 {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error", "")
        except ValueError:
            msg = ""
        raise ToolError(msg or f"HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise ToolError(f"the studio does not answer at {URL} (start it with ./run_studio.sh): {e}")


def output_dir():
    global _paths
    if _paths is None:
        _paths = call("GET", "/api/machine")["paths"]
    return _paths["output"]


def absolute(rel):
    return os.path.join(output_dir(), rel) if rel else ""


def wait_job(job_id, timeout=3600):
    end = time.time() + timeout
    while time.time() < end:
        j = call("GET", f"/api/jobs/{job_id}")
        if j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(2)
    raise ToolError(f"job {job_id} is still running after {timeout} s; ask again with job_status")


def job_report(j):
    out = {"job": j["id"], "status": j["status"], "title": j.get("title")}
    if j.get("error"):
        out["error"] = j["error"]
    r = j.get("result") or {}
    files = []
    for aid in r.get("assets") or ([r["asset"]] if r.get("asset") else []):
        a = call("GET", f"/api/library/{aid}")
        files.append({"asset": a["id"], "kind": a["kind"], "file": absolute(a["path"]), "use_as": a["ref"]})
    if files:
        out["files"] = files
    for k in ("ok", "summary", "seed", "take", "film", "shot", "seconds", "note", "parts"):
        if k in r:
            out[k] = r[k]
    if r.get("film") and r.get("shot"):
        f = call("GET", f"/api/films/{r['film']}")
        sh = next((s for s in f["shots"] if s["id"] == r["shot"]), None)
        t = next((t for t in (sh or {}).get("takes", []) if t["n"] == r.get("take")), None)
        if t:
            out.update(preview=absolute(t.get("preview")), contact_sheet=absolute(t.get("sheet")), status_of_shot=sh["status"],
                       checks=[{"name": c["name"], "status": c["status"], "text": c["text"]} for c in (t.get("checks") or {}).get("checks", [])])
            out["full_video"] = absolute(f.get("full"))
    for k in ("file", "fcpxml", "edl", "srt", "folder", "reel", "notes"):
        if r.get(k):
            out[k] = absolute(r[k])
    return out


def queued(job, wait, timeout=3600):
    return job_report(wait_job(job["id"], timeout)) if wait else {"job": job["id"], "status": job["status"], "note": "ask job_status for the result"}


# ---------------------------------------------------------------- the tools
def t_status(a):
    st, m = call("GET", "/api/state"), call("GET", "/api/machine")
    return {"comfyui_up": st["comfy"]["up"], "rendering": [j["title"] + ": " + (j.get("progress") or {}).get("text", "") for j in st["jobs"] if j["status"] == "running"],
            "waiting": len([j for j in st["jobs"] if j["status"] == "queued"]), "at_the_gate": st["gate"],
            "features": {k: (True if v["ok"] else v["why"]) for k, v in m.get("features", {}).items()},
            "memory_free_gb": round(m["memory"]["available"] / 2 ** 30, 1), "disk_free_gb": round(m["disk"]["free"] / 2 ** 30, 1),
            "loras": m.get("loras", []), "output_folder": m["paths"]["output"]}


def t_presets(a):
    p = call("GET", "/api/presets")
    return {"framings": [(f["id"], f["name"]) for f in p["cameras"]["framings"]], "cameras": [(m["id"], m["name"]) for m in p["cameras"]["moves"]],
            "looks": [(s["id"], s["name"]) for s in p["looks"]["styles"]], "lenses": [s["id"] for s in p["looks"]["lenses"]],
            "lights": [s["id"] for s in p["looks"]["lights"]], "coverage_plans": [(c["id"], c["name"], c["line"]) for c in p["coverage"]["plans"]],
            "angle_views": [v["id"] for v in p["angles"]["views"]],
            "lengths_new_shot": [l["frames"] for l in p["lengths"] if l["new_shot"]], "lengths_continuation": [l["frames"] for l in p["lengths"] if l["continuation"]],
            "sizes": [(s["width"], s["height"]) for s in p["sizes"]]}


def t_prompt_check(a):
    return call("POST", "/api/prompt/check", {"prompt": a["prompt"], "new_shot": a.get("new_shot", True), "lines": a.get("lines") or [], "seconds": a.get("seconds", 10)})


def t_make_picture(a):
    d = {k: a[k] for k in ("prompt", "width", "height", "takes", "seed", "template", "name") if k in a}
    return queued(call("POST", "/api/images", d), a.get("wait", True), 900)


def t_edit_picture(a):
    d = {"pictures": [a["picture"]] + list(a.get("more_pictures") or []), "keep_size": a.get("keep_size", True)}
    for k in ("prompt", "angles", "seed", "takes", "width", "height", "name", "template"):
        if k in a:
            d[k] = a[k]
    if not d.get("prompt") and not d.get("angles"):
        raise ToolError("give a prompt (what changes) or angles (a list of views, or \"sheet\")")
    return queued(call("POST", "/api/images", d), a.get("wait", True), 900)


CLIP_KEYS = ("name", "mode", "place", "action", "sound", "framing", "camera", "camera_text", "look", "lens", "light", "style", "people", "lines",
             "refs", "first_frame", "last_frame", "width", "height", "frames", "turbo", "seed", "prompt", "language", "talking_head", "staging", "beats", "loras")


def t_make_clip(a):
    d = {k: a[k] for k in CLIP_KEYS if k in a}
    if not (d.get("action") or d.get("prompt") or d.get("place")):
        raise ToolError("describe the place, what happens, or give a whole prompt (mode \"free\")")
    pre = call("POST", "/api/compose", d)
    warns = [f["text"] for f in pre["findings"] if f["level"] == "warn"]
    if not pre["fit"]["ok"]:
        raise ToolError(pre["fit"]["text"])
    r = call("POST", "/api/clips", d)
    if "job" not in r:
        return {"film": r["film"], "parts": r["shots"], "note": "a long take was started; follow it with film_get", "prompt_warnings": warns}
    out = queued(r["job"], a.get("wait", True))
    out["film"] = r["film"]
    if warns:
        out["prompt_warnings"] = warns
    return out


def t_extend_clip(a):
    r = call("POST", f"/api/clips/{a['film']}/extend", {k: a[k] for k in ("action", "lines", "sound", "frames") if k in a})
    return {**queued(r["job"], a.get("wait", True)), "film": r["film"]}


def t_job_status(a):
    j = call("GET", f"/api/jobs/{a['job']}")
    if j["status"] in ("done", "failed", "cancelled"):
        return job_report(j)
    return {"job": j["id"], "status": j["status"], "progress": j.get("progress")}


def t_cancel_job(a):
    return call("DELETE", f"/api/jobs/{a['job']}")


def t_library(a):
    q = urllib.request.quote(a.get("q", ""))
    items = call("GET", f"/api/library?q={q}&kind={a.get('kind', '')}&limit={int(a.get('limit', 30))}")["items"]
    return [{"asset": x["id"], "kind": x["kind"], "name": x["name"], "file": absolute(x["path"]), "use_as": x["ref"], "prompt": (x.get("prompt") or "")[:300],
             "checks_ok": x.get("ok"), "film": x.get("film")} for x in items]


def t_import(a):
    x = call("POST", "/api/library/import", {"path": a["path"], "name": a.get("name")})
    return {"asset": x["id"], "kind": x["kind"], "use_as": x["ref"], "file": absolute(x["path"])}


def t_film_list(a):
    return call("GET", "/api/films")


def t_film_get(a):
    f = call("GET", f"/api/films/{a['film']}")
    shots = [{"id": s["id"], "n": i + 1, "title": s["title"], "new_shot": s["new_shot"] or i == 0, "status": s["status"], "takes": len(s["takes"]),
              "action": s["action"], "lines": s["lines"], "cast": s["cast"], "location": s["location"], "framing": s["framing"], "camera": s["camera"],
              "sound": s["sound"], "frames": s["frames"], "error": s.get("error", "")} for i, s in enumerate(f["shots"])]
    return {"id": f["id"], "name": f["name"], "bible": f["bible"], "gate": f["gate"], "cast": f["cast"], "locations": f["locations"], "props": f["props"],
            "shots": shots, "run": {k: (f.get("run") or {}).get(k) for k in ("active", "mode", "stopped")}, "full_video": absolute(f.get("full")),
            "full_upscaled": absolute(f.get("full_upscaled"))}


def t_film_create(a):
    f = call("POST", "/api/films", {"name": a["name"], "bible": a.get("bible") or {}})
    patch = {k: a[k] for k in ("cast", "locations", "props", "shots", "gate") if k in a}
    if patch:
        f = call("PUT", f"/api/films/{f['id']}", patch)["film"]
    return {"film": f["id"], "cast": [(c["id"], c["name"]) for c in f["cast"]], "locations": [(l["id"], l["name"]) for l in f["locations"]],
            "shots": [s["id"] for s in f["shots"]]}


def t_film_update(a):
    patch = {k: a[k] for k in ("name", "bible", "cast", "locations", "props", "shots", "gate", "notes") if k in a}
    r = call("PUT", f"/api/films/{a['film']}", patch)
    return {"film": r["film"]["id"], "report": r["report"], "cast": [(c["id"], c["name"]) for c in r["film"]["cast"]],
            "locations": [(l["id"], l["name"]) for l in r["film"]["locations"]], "shots": [(s["id"], s["status"]) for s in r["film"]["shots"]]}


def t_film_plan(a):
    r = call("POST", f"/api/films/{a['film']}/outline", {k: a[k] for k in ("plan", "a", "b", "place", "logline", "scenes", "shots") if k in a}, timeout=300)
    return {"added": r["added"], "shots": [(s["id"], s["title"]) for s in r["film"]["shots"]]}


def t_shot_preflight(a):
    c = call("POST", f"/api/films/{a['film']}/compose/{a['shot']}", {})
    return {"can_render": c["eligible"], "why_not": c["why"], "prompt": c["prompt"], "pictures": [(p["n"], p["what"]) for p in c["pictures"]],
            "voices": [(x["n"], x["speaker"]) for x in c["audios"]], "frames": c["frames"], "continuation": c["continuation"],
            "findings": [(f["level"], f["text"]) for f in c["findings"]], "estimate_seconds": c.get("estimate"),
            "previous_part_contact_sheet": absolute(c.get("previous_sheet", ""))}


def t_shot_render(a):
    j = call("POST", f"/api/films/{a['film']}/render/{a['shot']}", {"seed": a.get("seed", 0), "force": a.get("force", False)})
    return queued(j, a.get("wait", True))


def t_gate(a):
    return call("GET", "/api/state")["gate"]


def t_approve(a):
    f = call("POST", f"/api/films/{a['film']}/approve/{a['shot']}", {})
    return {"shots": [(s["id"], s["status"]) for s in f["shots"]]}


def t_take_back(a):
    r = call("POST", f"/api/films/{a['film']}/take/{a['shot']}", {"n": a["take"]})
    return r["report"]


def t_film_run(a):
    return call("POST", f"/api/films/{a['film']}/run", {k: a[k] for k in ("mode", "retries", "upscale") if k in a})


def t_film_stop(a):
    return call("POST", f"/api/films/{a['film']}/stop", {})


def t_storyboard(a):
    r = call("POST", f"/api/films/{a['film']}/storyboard", {"shots": a.get("shots"), "takes": a.get("takes", 1)})
    if not a.get("wait", True):
        return {"jobs": [j["id"] for j in r["jobs"]]}
    return [job_report(wait_job(j["id"], 900)) for j in r["jobs"]]


def t_upscale(a):
    return queued(call("POST", f"/api/films/{a['film']}/upscale", {k: a[k] for k in ("first", "last", "force") if k in a}), a.get("wait", False), 6 * 3600)


def t_night(a):
    return call("POST", "/api/nightshift", {k: a[k] for k in ("film", "start", "retries", "upscale", "name") if k in a})


def t_timeline(a):
    tl = call("POST", f"/api/films/{a['film']}/timeline", {"upscaled": a.get("upscaled", False)})
    patch = {k: a[k] for k in ("captions", "title", "music", "loudness", "match") if k in a}
    if patch:
        call("PUT", f"/api/timelines/{tl['id']}", patch)
    return queued(call("POST", f"/api/timelines/{tl['id']}/export", {"resolve": a.get("for_resolve", False)}), a.get("wait", True), 3600)


S = lambda **props: {"type": "object", "properties": props, "additionalProperties": True}
STR, INT, BOOL, ARR, OBJ = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "array"}, {"type": "object"}
REQ = lambda schema, *names: {**schema, "required": list(names)}
PERSON = "people: [{name, pronoun: his|her|their, description, face, body (outfit sheet), voice}] where face/body/voice are 'use_as' names from the Library"
TOOLS = [
    ("studio_status", "Is ComfyUI up, what is rendering, what waits at the gate, which features can run, free memory and disk.", S(), t_status),
    ("presets", "The ids of framings, camera moves, looks, lenses, lights, coverage plans, angle views, and the frame counts and sizes that work.", S(), t_presets),
    ("prompt_check", "Check a prompt before rendering: contradicting camera words, speech without lines, things forbidden by name, too many words for the time.",
     REQ(S(prompt=STR, new_shot=BOOL, lines=ARR, seconds={"type": "number"}), "prompt"), t_prompt_check),
    ("make_picture", "A picture with Qwen-Image (10-30 s). template: portrait (a face reference) | location (an empty place). Returns the file and its 'use_as' name.",
     REQ(S(prompt=STR, width=INT, height=INT, takes=INT, seed=INT, template=STR, name=STR, wait=BOOL), "prompt"), t_make_picture),
    ("edit_picture", "Re-draw a picture: prompt = what changes; or angles = a list of views (front, left, back, ...) or \"sheet\" for a character sheet; "
     "template \"propsheet\" + prompt (what the object is) for a prop sheet. picture and more_pictures are 'use_as' names.",
     REQ(S(picture=STR, prompt=STR, angles={}, more_pictures=ARR, keep_size=BOOL, template=STR, seed=INT, wait=BOOL), "picture"), t_edit_picture),
    ("make_clip", "A video clip with sound (MiniMax H3), checked after rendering. Fields: place, action (what happens; never spoken words), "
     "lines [{speaker, text, how}] (every spoken word), sound, framing, camera, look, " + PERSON + ", first_frame, last_frame, refs [{file, label}], "
     "width, height, frames (see presets), seed. Or mode \"free\" with a whole prompt. beats [..] makes a long take of continuing parts. "
     "Look at contact_sheet before you report: the checks do not see a wrong prop or a person in the wrong place.",
     S(action=STR, place=STR, lines=ARR, people=ARR, sound=STR, framing=STR, camera=STR, look=STR, first_frame=STR, last_frame=STR, refs=ARR, width=INT,
       height=INT, frames=INT, seed=INT, mode=STR, prompt=STR, beats=ARR, name=STR, wait=BOOL), t_make_clip),
    ("extend_clip", "Carry a clip on: a new part that continues its last frames and sound. action must only name what is in view at the end of the clip.",
     REQ(S(film=STR, action=STR, lines=ARR, sound=STR, frames=INT, wait=BOOL), "film", "action"), t_extend_clip),
    ("job_status", "The state or the result of a job.", REQ(S(job=STR), "job"), t_job_status),
    ("cancel_job", "Cancel a waiting or running job.", REQ(S(job=STR), "job"), t_cancel_job),
    ("library_search", "Files in the Library by words of their name or prompt. kind: image | clip | film | audio | export | sheet.", S(q=STR, kind=STR, limit=INT), t_library),
    ("import_file", "Bring a picture, clip or sound that is under ComfyUI's output or input folder into the Library; returns its 'use_as' name.",
     REQ(S(path=STR, name=STR), "path"), t_import),
    ("film_list", "The films.", S(), t_film_list),
    ("film_get", "A film: bible, cast, locations, shots with their status, the run, the full video.", REQ(S(film=STR), "film"), t_film_get),
    ("film_create", "A new film. bible {logline, look, width, height, frames, language}; cast [{name, pronoun, description, face, body, voice}]; "
     "locations [{name, description, plate}]; props [{name, token, sheet}]; shots [{title, new_shot, location (id), cast [ids], staging {id: where}, "
     "framing, camera, action, lines [{speaker (cast id), text, how}], sound, frames}]; gate {mode: hold|auto, retries}. Ids of new cast and "
     "locations are returned: create them first, then add shots with film_update.",
     REQ(S(name=STR, bible=OBJ, cast=ARR, locations=ARR, props=ARR, shots=ARR, gate=OBJ), "name"), t_film_create),
    ("film_update", "Change a film. Send whole lists (cast, locations, props, shots): a shot keeps its takes by its id. Moving or removing rendered "
     "shots renumbers the parts; the report says which continuations went stale.", REQ(S(film=STR, bible=OBJ, cast=ARR, locations=ARR, props=ARR, shots=ARR, gate=OBJ), "film"), t_film_update),
    ("film_add_shots", "Add shots from a coverage plan (plan, a and b = cast ids, place = location id), or from a logline with the writing help.",
     REQ(S(film=STR, plan=STR, a=STR, b=STR, place=STR, logline=STR, scenes=INT, shots=INT), "film"), t_film_plan),
    ("shot_preflight", "The exact prompt a shot will send, its pictures and voices, the prompt check, and whether it can render now.", REQ(S(film=STR, shot=STR), "film", "shot"), t_shot_preflight),
    ("shot_render", "Render a shot (a new take), wait, and return its checks, preview and contact sheet. Parts render in order; a continuation needs "
     "the shot before it approved.", REQ(S(film=STR, shot=STR, seed=INT, wait=BOOL), "film", "shot"), t_shot_render),
    ("gate_list", "Every take that waits for approval.", S(), t_gate),
    ("gate_approve", "Approve the active take of a shot. Look at its contact sheet first: a flaw you notice is a fail, not a note.", REQ(S(film=STR, shot=STR), "film", "shot"), t_approve),
    ("take_put_back", "Make an earlier take of a shot its part again.", REQ(S(film=STR, shot=STR, take=INT), "film", "shot", "take"), t_take_back),
    ("film_run", "Render every shot without a usable take, in order. mode: hold (wait for approval of every take) | auto (approve what passes, "
     "retake what fails, then wait) | keep_going (never wait).", REQ(S(film=STR, mode=STR, retries=INT, upscale=BOOL), "film"), t_film_run),
    ("film_stop", "Stop a film's run.", REQ(S(film=STR), "film"), t_film_stop),
    ("storyboard", "A still for each shot (or the shots named) from the film's own pictures; seconds each.", REQ(S(film=STR, shots=ARR, takes=INT, wait=BOOL), "film"), t_storyboard),
    ("film_upscale", "Upscale the film's parts x1.5 to 48 fps, in order (about 6 minutes a part). wait defaults to false.", REQ(S(film=STR, first=INT, last=INT, force=BOOL, wait=BOOL), "film"), t_upscale),
    ("night_shift", "Plan a batch: start now | idle | HH:MM. It keeps going past takes that fail and leaves a reel and notes.", REQ(S(film=STR, start=STR, retries=INT, upscale=BOOL), "film"), t_night),
    ("film_export", "A film's takes cut together and exported: levels matched, -16 LUFS. captions, title {text, subtitle}, music {path, gain, duck}, "
     "for_resolve (ProRes package instead).", REQ(S(film=STR, upscaled=BOOL, captions=BOOL, title=OBJ, music=OBJ, for_resolve=BOOL, wait=BOOL), "film"), t_timeline),
]
BY_NAME = {name: fn for name, _, _, fn in TOOLS}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "h3-studio", "version": VERSION},
                "instructions": "H3 Studio renders pictures (Qwen-Image) and video with sound (MiniMax H3) on this computer through ComfyUI. Render only "
                                "through these tools, never by queueing into ComfyUI beside them. Call presets for ids. After a clip, look at its "
                                "contact_sheet before reporting or approving."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        fn = BY_NAME.get(p.get("name"))
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"no such tool: {p.get('name')}"}}
        try:
            out, bad = fn(p.get("arguments") or {}), False
        except ToolError as e:
            out, bad = {"error": str(e)}, True
        except KeyError as e:
            out, bad = {"error": f"missing argument: {e.args[0]}"}, True
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}], "isError": bad}}
    if mid is None:
        return None                                    # a notification (notifications/initialized, cancelled...)
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
