"""The Writer: a conversation with Claude that turns a small story into a film, and changes a film when something is wrong.

It runs the Claude Code command-line program (`claude -p`) that is signed in on this computer, so it uses that
subscription; the studio holds no key. Only text goes to it: the story, the answers, and a film's words (cast, places,
shots, prompts, lines, and what the checks said about each take). Pictures and clips stay here.

The program runs with no tools, no plugins, no settings of its own and no saved session: the studio keeps the
conversation (output/studio/writer/<id>.json) and sends it whole every turn. Each answer is one JSON object
(SCHEMA): what Claude says, its questions, and when it is ready a proposal: a whole film for a new one, or edits to
the shots, cast and places of an existing one. Nothing changes until the person presses Apply.
"""
import asyncio
import json
import os
import shutil
import time
import uuid

from . import blockouts, compose, config, films, lengths, presets

TIMEOUT = 900                       # s: a 20-shot film was written in about 2 minutes (2026-11-13); a slow day is longer

_STR = {"type": "string"}
_LINE = {"type": "object", "additionalProperties": False, "required": ["speaker", "text", "how"],
         "properties": {"speaker": _STR, "text": _STR, "how": _STR}}
_SHOT_PROPS = {
    "title": _STR, "scene": _STR, "new_shot": {"type": "boolean"}, "location": _STR, "cast": {"type": "array", "items": _STR},
    "framing": _STR, "camera": _STR, "action": _STR, "lines": {"type": "array", "items": _LINE}, "sound": _STR,
    "seconds": {"type": "number"}, "prompt": _STR}
_SHOT = {"type": "object", "additionalProperties": False, "required": list(_SHOT_PROPS), "properties": _SHOT_PROPS}
_PERSON = {"type": "object", "additionalProperties": False, "required": ["name", "pronoun", "description"],
           "properties": {"name": _STR, "pronoun": {"type": "string", "enum": ["his", "her", "their"]}, "description": _STR}}
_PLACE = {"type": "object", "additionalProperties": False, "required": ["name", "description"],
          "properties": {"name": _STR, "description": _STR}}
_QUESTION = {"type": "object", "additionalProperties": False, "required": ["id", "question", "options"],
             "properties": {"id": _STR, "question": _STR, "options": {"type": "array", "items": _STR}}}
_BLOCKOUT = {"type": "object", "additionalProperties": False, "required": ["scene", "why", "blockout"],
             "properties": {"scene": _STR, "why": _STR, "blockout": {"anyOf": [blockouts.SCHEMA, {"type": "null"}]}}}
_FILM = {"type": "object", "additionalProperties": False, "required": ["name", "logline", "look", "cast", "locations", "shots", "blockouts"],
         "properties": {"name": _STR, "logline": _STR, "look": _STR, "cast": {"type": "array", "items": _PERSON},
                        "locations": {"type": "array", "items": _PLACE}, "shots": {"type": "array", "items": _SHOT},
                        "blockouts": {"type": "array", "items": _BLOCKOUT}}}
_UPDATE = {"type": "object", "additionalProperties": False, "required": ["id", "why", "changes"],
           "properties": {"id": _STR, "why": _STR,
                          "changes": {"type": "object", "additionalProperties": False, "required": [],
                                      "properties": {k: v for k, v in _SHOT_PROPS.items()}}}}
_ADD = {"type": "object", "additionalProperties": False, "required": ["after", "why", "shot"],
        "properties": {"after": _STR, "why": _STR, "shot": _SHOT}}
_EDITS = {"type": "object", "additionalProperties": False, "required": ["cast", "locations", "update", "add", "remove", "blockouts"],
          "properties": {"cast": {"type": "array", "items": _PERSON}, "locations": {"type": "array", "items": _PLACE},
                         "update": {"type": "array", "items": _UPDATE}, "add": {"type": "array", "items": _ADD},
                         "remove": {"type": "array", "items": _STR}, "blockouts": {"type": "array", "items": _BLOCKOUT}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["say", "questions", "film", "edits"],
          "properties": {"say": _STR, "questions": {"type": "array", "items": _QUESTION},
                         "film": {"anyOf": [_FILM, {"type": "null"}]}, "edits": {"anyOf": [_EDITS, {"type": "null"}]}}}


def system_prompt():
    cams, looks = presets.load("cameras"), presets.load("looks")
    with open(os.path.join(config.REPO, "docs", "prompting.md"), encoding="utf-8") as fh:
        guide = fh.read()
    return f"""You are the writer of H3 Studio, a film studio on the user's own computer. Its films are made of shots; each
shot is rendered by the MiniMax H3 video model as one part of about 5 to 15 seconds with picture, speech and sound.

How a conversation goes:
1. The user gives a small story. Ask 3 to 5 short questions that change the film (tone, length, who is in it and how
   they look, the places, the ending, what is said). Give each question 2 to 4 options; the user can also type their
   own answer. Ask questions only in the first turn or two; do not keep asking.
2. Then write the film: "film" with its cast, places and shots, in scenes. A typical short film is 2 to 4 scenes of
   2 to 5 shots. Say in "say" what you made, in two or three sentences.
3. When the user talks about an existing film (its words are in the message, with what the checks said about each
   take), answer with "edits": change only what has to change, and say in each "why" what was wrong and how the
   change fixes it. A shot that is already rendered must be rendered again after a change; the user decides.

Answer every turn with the JSON object only. "film" and "edits" are null when you only talk or ask. Never both.

The fields of a shot:
- "new_shot": true for a cut to a new place, size or angle; false when it continues the shot before without a cut (the
  same place, light and camera; its last 39 frames and sound carry through, so name no place and only what is in view
  at the end of the shot before). The first shot is always new.
- "location": the name of one of the film's places for a new shot; "" for a continuation.
- "cast": the names of the people in the shot.
- "framing": one of {json.dumps([f["id"] for f in cams["framings"]])} or "".
- "camera": one of {json.dumps([m["id"] for m in cams["moves"]])} or "".
- "action": what happens, with names and sides (who is on the left and who on the right of the picture), in order.
- "lines": every spoken word, as exact words with the speaker's name and "how" it is said. [] for a silent shot.
- "sound": what is heard besides the words.
- "seconds": 5, 8, 10 or 15 (a continuation adds its length minus 1.6 s). About 2.6 spoken words a second at most.
- "prompt": "" for a shot in fields (the studio writes the prompt). A shot the user wrote whole ("mode": "free" in the
  film you are shown) keeps its words in "prompt"; edit that text instead of the fields, keep its Picture numbers and
  its <d>...</d> lines, and keep its "lines" the same as the words in it.
- "blockouts" (of a film, and in edits): one per scene that needs one, {{"scene": the scene's name exactly as in its
  shots, "why": what it pins down, "blockout": the scene}}. In edits, give the whole new scene for a blockout that
  changes, and "blockout": null to remove one. See "Blockouts" below.
- "look" of a new film: one of {json.dumps([s["id"] for s in looks["styles"]])}.
- A person's "description": age, face, hair, clothes, in one sentence. A place's: the empty place as the camera sees it,
  with its light.

Blockouts:
{blockouts.GUIDE}

Keep to the studio's prompting guide below; every rule in it comes from a render that went wrong.

{guide}"""


# ------------------------------------------------------------------ the conversation file
def _dir():
    return config.home("writer")


def _path(cid):
    if not cid or not all(c.isalnum() or c in "_-" for c in cid):
        raise ValueError("no such conversation")
    return os.path.join(_dir(), cid + ".json")


def load(cid):
    c = config.read_json(_path(cid), None)
    if not c:
        raise KeyError("conversation")
    return c


def save(c):
    c["updated"] = time.time()
    config.write_json(_path(c["id"]), c)
    return c


def all_conversations():
    out = []
    if os.path.isdir(_dir()):
        for f in os.listdir(_dir()):
            if f.endswith(".json"):
                c = config.read_json(os.path.join(_dir(), f), None)
                if c:
                    first = next((t["text"] for t in c["turns"] if t["role"] == "user"), "")
                    out.append({"id": c["id"], "film": c.get("film", ""), "title": c.get("title") or first[:70],
                                "updated": c.get("updated", 0), "turns": len(c["turns"])})
    return sorted(out, key=lambda x: -x["updated"])


def new_conversation(film_id=""):
    if film_id and not films.load(film_id):
        raise KeyError("film")
    c = {"id": uuid.uuid4().hex[:10], "film": film_id, "created": time.time(), "turns": [], "title": ""}
    return save(c)


# ------------------------------------------------------------------ what Claude is shown of a film
def film_words(film):
    """A film as text for the writer: its bible, cast, places and every shot with its words and how its take did."""
    cast = {c["id"]: c["name"] for c in film["cast"]}
    places = {l["id"]: l["name"] for l in film["locations"]}
    shots = []
    for i, s in enumerate(film["shots"]):
        t = films.active_take(s)
        checks = (t or {}).get("checks") or {}
        failed = [c for c in checks.get("checks", []) if c.get("status") in ("fail", "warn")] if isinstance(checks, dict) else []
        shots.append({
            "id": s["id"], "part": s.get("part") or None, "title": s.get("title", ""), "scene": s.get("scene", ""),
            "new_shot": bool(i == 0 or s.get("new_shot", True)), "mode": s.get("mode", "fields"),
            "location": places.get(s.get("location"), ""), "cast": [cast.get(x, x) for x in s.get("cast") or []],
            "framing": s.get("framing", ""), "camera": s.get("camera", ""), "action": s.get("action", ""),
            "lines": [{"speaker": cast.get(l.get("speaker"), l.get("speaker", "")), "text": l.get("text", ""), "how": l.get("how", "")}
                      for l in s.get("lines") or []],
            "sound": s.get("sound", ""), "seconds": round(lengths.seconds(s.get("frames") or film["bible"]["frames"]), 1),
            "prompt": s.get("prompt", "") if s.get("mode") == "free" else "",
            "status": s.get("status", "todo"),
            "take": {"verdict": t.get("verdict", ""), "checks": checks.get("summary", "") if isinstance(checks, dict) else "",
                     "problems": [f"{c.get('name', '')}: {c.get('detail', c.get('text', ''))}" for c in failed][:6]} if t else None})
    b = film["bible"]
    return json.dumps({"name": film["name"], "logline": b.get("logline", ""), "look": b.get("look", ""), "style": b.get("style", ""),
                       "cast": [{"name": c["name"], "pronoun": c.get("pronoun", "their"), "description": c.get("description", ""),
                                 "has_face_picture": bool(c.get("face"))} for c in film["cast"]],
                       "locations": [{"name": l["name"], "description": l.get("description", ""), "has_plate": bool(l.get("plate"))}
                                     for l in film["locations"]],
                       "props": [{"name": p.get("name", ""), "token": p.get("token", "")} for p in film["props"]],
                       "shots": shots,
                       "blockouts": [{"scene": bo.get("scene_name", ""), "blockout": bo.get("scene"),
                                      "made": blockouts.state_of(film, bo)["current"],
                                      "stretches": [{"shot": c["id"], "seconds": [round(c["start"] / 24, 2), round(c["end"] / 24, 2)]}
                                                    for c in blockouts.cuts(film, bo)],
                                      "measured": {n: {"share_of_picture_height": v.get("median"), "share_of_time_in_picture": v.get("in_view"),
                                                       "side_of_picture": v.get("side")} for n, v in (bo.get("stats") or {}).items()} or None}
                                     for bo in blockouts.all_of(film)]}, ensure_ascii=False, indent=1)


def transcript(c):
    """The whole conversation as the one message the program gets."""
    out = []
    if c.get("film"):
        film = films.load(c["film"])
        if film:
            out.append("THE FILM AS IT IS NOW (ids of shots are for your edits):\n" + film_words(film))
    for t in c["turns"]:
        if t["role"] == "user":
            out.append("USER: " + t["text"])
        else:
            out.append("YOU ANSWERED: " + json.dumps(t["answer"], ensure_ascii=False))
            if t.get("applied"):
                out.append("(The user applied that proposal" + (f": it became the film {t['applied']}." if t.get("applied") else ".") + ")")
    out.append("Answer the last USER message with the JSON object.")
    return "\n\n".join(out)


# ------------------------------------------------------------------ running Claude
def state():
    exe = shutil.which(config.settings()["writer"]["command"] or "claude")
    return {"ok": bool(exe), "command": exe or "", "model": config.settings()["writer"]["model"],
            "why": "" if exe else "the claude command is not installed or not on the PATH of the studio"}


async def ask(c):
    st = state()
    if not st["ok"]:
        raise ValueError("the Writer needs Claude Code: " + st["why"])
    work = config.home("writer", "workdir")                # an empty folder: nothing of this computer is read
    os.makedirs(work, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))}
    args = [st["command"], "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA), "--system-prompt", system_prompt(),
            "--tools", "", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"]
    if st["model"]:
        args += ["--model", st["model"]]
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*args, cwd=work, env=env, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(transcript(c).encode()), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError(f"Claude gave no answer within {TIMEOUT // 60} minutes")
    text = out.decode("utf-8", "replace").strip()
    try:
        res = json.loads(text)
    except ValueError:
        raise ValueError("Claude Code did not answer: " + (err.decode("utf-8", "replace").strip() or text)[-300:])
    if isinstance(res, list):
        res = next((r for r in reversed(res) if isinstance(r, dict) and r.get("type") == "result"), {})
    if res.get("is_error") or res.get("subtype") != "success":
        raise ValueError("Claude Code: " + str(res.get("result") or res.get("api_error_status") or res.get("subtype"))[:300])
    answer = res.get("structured_output")
    if answer is None:
        try:
            answer = json.loads(res.get("result") or "")
        except ValueError:
            answer = {"say": res.get("result") or "", "questions": [], "film": None, "edits": None}
    meta = {"seconds": round(time.time() - t0, 1), "model": ",".join((res.get("modelUsage") or {}).keys()),
            "cost_usd": res.get("total_cost_usd")}
    return clean(answer), meta


def clean(a):
    a = a if isinstance(a, dict) else {}
    out = {"say": str(a.get("say") or ""), "questions": [], "film": None, "edits": None}
    for q in a.get("questions") or []:
        if isinstance(q, dict) and q.get("question"):
            out["questions"].append({"id": str(q.get("id") or len(out["questions"])), "question": str(q["question"]),
                                     "options": [str(o) for o in (q.get("options") or [])][:6]})
    if isinstance(a.get("film"), dict) and a["film"].get("shots"):
        out["film"] = a["film"]
    elif isinstance(a.get("edits"), dict) and any(a["edits"].get(k) for k in ("cast", "locations", "update", "add", "remove")):
        out["edits"] = a["edits"]
    return out


async def turn(cid, text):
    c = load(cid)
    if not text.strip():
        raise ValueError("write something first")
    c["turns"].append({"role": "user", "text": text.strip(), "time": time.time()})
    if not c.get("title"):
        c["title"] = text.strip().split("\n")[0][:70]
    save(c)
    try:
        answer, meta = await ask(c)
    except Exception:
        c = load(cid)
        c["turns"].pop()                                    # the question can be sent again
        save(c)
        raise
    c = load(cid)
    c["turns"].append({"role": "writer", "answer": answer, "meta": meta, "time": time.time(), "applied": ""})
    return save(c)


# ------------------------------------------------------------------ a proposal into a film
_FRAMINGS = lambda: {f["id"] for f in presets.load("cameras")["framings"]}
_MOVES = lambda: {m["id"] for m in presets.load("cameras")["moves"]}


def _frames(seconds, cont):
    if not seconds:
        return 0
    want = lengths.from_seconds(float(seconds) + (lengths.CONTEXT / lengths.FPS if cont else 0))
    ok = lengths.usable(cont)
    return min(ok, key=lambda n: abs(n - want)) if ok else 0


def _shot_fields(s, film, cont):
    ids = {c["name"]: c["id"] for c in film["cast"]}
    locs = {l["name"]: l["id"] for l in film["locations"]}
    f = {}
    for k in ("title", "scene", "action", "sound"):
        if k in s:
            f[k] = str(s[k] or "")
    if "new_shot" in s:
        f["new_shot"] = bool(s["new_shot"])
    if "location" in s:
        f["location"] = locs.get(s["location"], "")
        if s["location"] and s["location"] not in locs:
            f["place"] = s["location"]
    if "cast" in s:
        f["cast"] = [ids[n] for n in s["cast"] if n in ids]
    if "framing" in s:
        f["framing"] = s["framing"] if s["framing"] in _FRAMINGS() else ""
    if "camera" in s:
        f["camera"] = s["camera"] if s["camera"] in _MOVES() else ""
    if "lines" in s:
        f["lines"] = [{"speaker": ids.get(l.get("speaker"), l.get("speaker", "")), "text": str(l.get("text", "")).strip(),
                       "how": str(l.get("how", ""))} for l in s["lines"] or [] if str(l.get("text", "")).strip()]
    if "seconds" in s:
        f["frames"] = _frames(s["seconds"], cont)
    if (s.get("prompt") or "").strip():
        f["prompt"], f["mode"] = s["prompt"], "free"
    return f


def _set_blockouts(film, items, report):
    """The Writer's blockouts into the film, by scene name; null removes a scene's. A scene that does not check out
    is kept as written: the Blockout step shows what is wrong, and Make refuses it."""
    for it in items or []:
        name = (it.get("scene") or "").strip()
        bo = blockouts.for_scene(film, name)
        if it.get("blockout") is None:
            if bo:
                film["blockouts"].remove(bo)
            continue
        try:
            scene = blockouts.normalize(it["blockout"])
        except blockouts.BadScene:
            scene = it["blockout"]
        if not bo:
            bo = {"id": "b" + uuid.uuid4().hex[:7], "scene_name": name, "cuts": {}, "video": "", "made": "", "stats": None}
            film.setdefault("blockouts", []).append(bo)
        bo["scene"] = scene
        for s in film["shots"]:                    # the blockout sets the framing and the camera of its shots
            if blockouts.scene_of(s) == name:
                s["framing"], s["camera"] = "", ""


def _people_and_places(film, cast, locations):
    for p in cast or []:
        c = next((x for x in film["cast"] if x["name"] == p.get("name")), None)
        if c is None:
            film["cast"].append({"id": uuid.uuid4().hex[:8], "name": p["name"], "pronoun": p.get("pronoun") or "their",
                                 "description": p.get("description", ""), "face": "", "body": "", "voice": "", "lora": {}})
        else:
            c["description"] = p.get("description") or c.get("description", "")
            c["pronoun"] = p.get("pronoun") if p.get("pronoun") in compose.PRONOUNS else c.get("pronoun", "their")
    for l in locations or []:
        x = next((y for y in film["locations"] if y["name"] == l.get("name")), None)
        if x is None:
            film["locations"].append({"id": uuid.uuid4().hex[:8], "name": l["name"], "description": l.get("description", ""), "plate": ""})
        else:
            x["description"] = l.get("description") or x.get("description", "")


def apply(cid, n):
    """Apply the proposal of writer turn n. A new film is made, or the film of the conversation is changed.
    Returns (film, report)."""
    c = load(cid)
    if not (0 <= n < len(c["turns"])) or c["turns"][n]["role"] != "writer":
        raise ValueError("no such answer")
    a = c["turns"][n]["answer"]
    if c["turns"][n].get("applied"):
        raise ValueError("this proposal was applied already")
    report = {"made": False, "updated": [], "added": [], "removed": [], "rerender": []}
    if a.get("film"):
        p = a["film"]
        look = p.get("look") if presets.find("looks", "styles", p.get("look") or "") else "cinematic"
        film = films.create((p.get("name") or "Untitled")[:80], bible={"logline": p.get("logline", ""), "look": look})
        with films.LOCK:
            film = films.load(film["id"])
            _people_and_places(film, p.get("cast"), p.get("locations"))
            for i, s in enumerate(p["shots"]):
                cont = i > 0 and not s.get("new_shot", True)
                films.new_shot(film, **_shot_fields(s, film, cont))
            _set_blockouts(film, p.get("blockouts"), report)
            films.save(film)
        report["made"] = True
        report["added"] = [s["id"] for s in film["shots"]]
        c["film"] = film["id"]
    elif a.get("edits"):
        e = a["edits"]
        with films.LOCK:
            film = films.load(c.get("film") or "")
            if not film:
                raise ValueError("this conversation has no film to change")
            _people_and_places(film, e.get("cast"), e.get("locations"))
            by_id = {s["id"]: s for s in film["shots"]}
            for u in e.get("update") or []:
                s = by_id.get(u.get("id"))
                if not s:
                    continue
                i = film["shots"].index(s)
                ch = u.get("changes") or {}
                s.update(_shot_fields(ch, film, i > 0 and not ch.get("new_shot", s.get("new_shot", True))))
                report["updated"].append(s["id"])
                if s.get("takes"):
                    report["rerender"].append(s["id"])
            for ad in e.get("add") or []:
                s = films.new_shot(film)
                film["shots"].remove(s)
                at = next((k + 1 for k, x in enumerate(film["shots"]) if x["id"] == ad.get("after")), len(film["shots"]) if ad.get("after") else 0)
                film["shots"].insert(at, s)
                s.update(_shot_fields(ad.get("shot") or {}, film, at > 0 and not (ad.get("shot") or {}).get("new_shot", True)))
                report["added"].append(s["id"])
            _set_blockouts(film, e.get("blockouts"), report)
            films.save(film)
        drop = [x for x in e.get("remove") or [] if any(s["id"] == x for s in film["shots"])]
        if drop or report["added"]:
            # removing goes through the same path as the page (takes to the trash, part numbers redone)
            keep = [{k: s.get(k) for k in ("id",) + films.USER_SHOT_FIELDS} for s in film["shots"] if s["id"] not in drop]
            film, rep = films.apply_edit(film["id"], {"shots": keep})
            report["removed"] = drop
            report["rerender"] += rep.get("stale", [])
    else:
        raise ValueError("this answer has nothing to apply")
    report["blockouts"] = [bo["id"] for bo in blockouts.all_of(film)
                           if not blockouts.state_of(film, bo)["current"] and not blockouts.state_of(film, bo)["error"]]
    c = load(cid)
    c["turns"][n]["applied"] = film["id"]
    c["film"] = film["id"]
    save(c)
    return film, report
