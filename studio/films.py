"""Films: the plan (bible, cast, places, props, shots) and the files of every take.

A film is one JSON file, films/<id>/film.json, and one long-video project, output/long_video/<long_project>/, where
the nodes keep each part's frames, latent and conditioning. Shot i of the film is part i+1 of that project: a new shot
starts fresh, any other shot continues the one before in latent space.

What this module keeps straight, because the nodes cannot know it:

  takes        every render of a shot is kept (frames, latent, conditioning, a preview and its check report), so an
               earlier take can be put back and compared. The nodes themselves overwrite a part when it is rendered again.
  order        parts are numbered by position. When shots are moved, added or removed, the rendered parts are copied
               to a new project folder under their new numbers (the old folder goes to the trash). A continuation
               whose predecessor changed is "stale": it has to be rendered again, a new shot keeps its take.
  the gate     nothing continues a part that was not approved.

A quick clip from Create is a film with one shot and `quick: true`; extending it adds a shot.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import checks, compose, config, lengths, library

LOCK = threading.RLock()
USER_SHOT_FIELDS = ("title", "scene", "new_shot", "mode", "place", "location", "cast", "staging", "framing", "camera",
                    "camera_text", "action", "lines", "sound", "props", "refs", "first_frame", "last_frame", "prompt",
                    "frames", "seed", "loras", "one_take", "talking_head", "notes",
                    "blockout", "blockout_start", "blockout_strength", "blockout_shapes")
# preview (a small render of the shot, see work.preview) is the server's, like takes
USER_FILM_FIELDS = ("name", "bible", "cast", "locations", "props", "notes", "gate")


# ------------------------------------------------------------------ files and folders
def film_dir(fid):
    return config.home("films", fid)


def film_path(fid):
    return os.path.join(film_dir(fid), "film.json")


def project_dir(film):
    return os.path.join(config.LONG_DIR, film["long_project"])


def part_files(film, part, project=None):
    root = os.path.join(config.LONG_DIR, project or film["long_project"])
    return {"segment": os.path.join(root, "segments", f"part_{part:03d}.mkv"),
            "latent": os.path.join(root, "latents", f"part_{part:03d}.safetensors"),
            "cond": os.path.join(root, "latents", f"part_{part:03d}.cond.pt")}


def full_path(film, upscaled=False):
    name = film["long_project"] + ("_full_upscaled.mp4" if upscaled else "_full.mp4")
    return os.path.join(project_dir(film), name)


def take_dir(film, shot):
    return os.path.join(film_dir(film["id"]), "takes", shot["id"])


def _link(src, dst):
    """A second name for the same data when the disk allows it, else a copy. The nodes replace a part with a new file,
    so a link to the old one keeps the old take."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.unlink(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _shots_json(film, project=None):
    return os.path.join(config.LONG_DIR, project or film["long_project"], "shots.json")


# ------------------------------------------------------------------ load, save, list
def _new_id():
    return uuid.uuid4().hex[:8]


def default_gate():
    g = config.settings()["gate"]
    return {"mode": "auto" if g["auto_approve"] else "hold", "retries": int(g["retries"])}


def create(name, quick=False, bible=None):
    fid = f"{config.slug(name, 'film', 24)}_{uuid.uuid4().hex[:4]}"
    film = {"id": fid, "name": name or "Untitled", "created": time.time(), "updated": time.time(), "quick": bool(quick),
            "long_project": "st_" + fid, "revision": 0,
            "bible": {**compose.blank_bible(), **(bible or {})}, "cast": [], "locations": [], "props": [], "shots": [], "blockouts": [],
            "gate": {"mode": "auto", "retries": 0} if quick else default_gate(), "notes": "", "run": {}}
    save(film)
    return film


def load(fid):
    if not fid or "/" in fid or ".." in fid:
        return None
    film = config.read_json(film_path(fid))
    if not film:
        return None
    film["bible"] = {**compose.blank_bible(), **(film.get("bible") or {})}
    film.setdefault("gate", default_gate())
    from . import blockouts
    blockouts.migrate(film)               # a scene kept on a shot (before blockouts were per scene) moves to its scene
    for s in film.get("shots", []):
        for k, v in compose.blank_shot().items():
            s.setdefault(k, v if not isinstance(v, (list, dict)) else type(v)())
    return film


BLOCKOUT_USER_FIELDS = ("scene_name", "scene", "cuts")      # the rest of a blockout (video, made, stats) is the server's


def merge_blockouts(film, incoming):
    """The film's blockouts as the user left them: their scene names, scenes and cuts; made videos are kept."""
    old = {b.get("id"): b for b in film.get("blockouts") or []}
    out = []
    for inc in incoming or []:
        cur = old.get(inc.get("id")) or {"id": inc.get("id") if inc.get("id") and "/" not in str(inc.get("id")) else "b" + _new_id(),
                                         "scene_name": "", "scene": None, "cuts": {}, "video": "", "made": "", "stats": None}
        for k in BLOCKOUT_USER_FIELDS:
            if k in inc:
                cur[k] = inc[k]
        out.append(cur)
    film["blockouts"] = out


def save(film):
    film["updated"] = time.time()
    config.write_json(film_path(film["id"]), film)
    return film


# The order a film is made in: the tabs of a film, numbered. "optional" steps are not needed to go on.
STEPS = [("bible", "Bible", "the logline, the look and the size"),
         ("cast", "Cast & places", "a face picture for each person, a voice, the places"),
         ("shots", "Shots", "what happens in each shot, in scenes"),
         ("blockout", "Blockout", "a rough 3D version of a scene, refined, then cut into its shots"),
         ("storyboard", "Storyboard", "a still of each shot, to look at before rendering"),
         ("roll", "Roll camera", "preview, render and approve each shot in order"),
         ("deliver", "Deliver", "upscale, then cut, mix and export on a timeline")]
OPTIONAL = {"blockout", "storyboard"}


def _names(items, n=3):
    items = [x or "(no name)" for x in items]
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def steps(film):
    """Each step of making this film, in order: {id, n, label, what, done, optional, todo}; `todo` says what is still
    missing. `next` (on the list) is the first step that is neither done nor optional."""
    from . import blockouts
    b, cast, places, shots = film.get("bible") or {}, film.get("cast") or [], film.get("locations") or [], film.get("shots") or []
    no_face = [c.get("name") for c in cast if not c.get("face") and not (c.get("lora") or {}).get("file")]
    no_plate = [l.get("name") for l in places if not l.get("plate")]
    empty = [i + 1 for i, s in enumerate(shots) if not ((s.get("prompt") if s.get("mode") == "free" else s.get("action")) or "").strip()]
    bstates = [blockouts.state_of(film, b) for b in blockouts.all_of(film)]
    unmade = [b["scene_name"] or "(no scene name)" for b in bstates if not b["current"]]
    approved = sum(1 for s in shots if s.get("status") == "approved")
    gate = sum(1 for s in shots if s.get("status") == "review")
    boarded = sum(1 for s in shots if s.get("storyboard") or active_take(s))
    up = os.path.isfile(full_path(film, upscaled=True))
    state = {
        "bible": (bool(b.get("logline") or shots), "" if b.get("logline") else "write a logline: one sentence of what happens"),
        "cast": (bool(cast) and not no_face,
                 "add the people in the film" if not cast else f"no face picture for {_names(no_face)}: without one a person looks different in every shot" if no_face
                 else f"no plate for {_names(no_plate)} (optional: a picture of the empty place keeps it the same)" if no_plate else ""),
        "shots": (bool(shots) and not empty,
                  "add shots, or let the Writer write them" if not shots else f"shot {_names([str(x) for x in empty])} say(s) nothing about what happens" if empty else ""),
        "blockout": (bool(bstates) and not unmade,
                     f"the blockout of scene {_names(unmade)} is not made, or changed since it was made" if unmade
                     else "" if bstates else "optional: block a scene where the camera or the staging matters"),
        "storyboard": (bool(shots) and boarded == len(shots), f"{boarded} of {len(shots)} shots have a still" if shots and boarded < len(shots) else ""),
        "roll": (bool(shots) and approved == len(shots),
                 (f"{approved} of {len(shots)} shots approved" + (f", {gate} waiting at the gate" if gate else "")) if shots and approved < len(shots) else ""),
        "deliver": (up, "" if up else ("upscale the film" if shots and approved == len(shots) else "after every shot is approved")),
    }
    out = [{"id": i, "n": n + 1, "label": label, "what": what, "done": state[i][0], "optional": i in OPTIONAL and not (i == "blockout" and unmade), "todo": state[i][1]}
           for n, (i, label, what) in enumerate(STEPS)]
    if state["roll"][0]:              # every shot is approved: what came before is behind it, whatever is missing there
        for s in out[:5]:
            s["passed"] = not s["done"]
            s["done"] = True
    return out


def next_step(st):
    return next((s for s in st if not s["done"] and not s["optional"]), None)


def summaries(quick=False):
    out = []
    root = config.home("films")
    for fid in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        f = load(fid)
        if not f or bool(f.get("quick")) != bool(quick):
            continue
        shots = f.get("shots", [])
        out.append({"id": f["id"], "name": f["name"], "updated": f.get("updated", 0), "shots": len(shots),
                    "approved": sum(1 for s in shots if s["status"] == "approved"),
                    "review": sum(1 for s in shots if s["status"] == "review"),
                    "seconds": round(sum(duration_of(s) for s in shots), 1),
                    "logline": f["bible"].get("logline", ""), "running": bool((f.get("run") or {}).get("active")),
                    "next": next_step(steps(f))})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def duration_of(shot):
    t = active_take(shot)
    return float(t.get("duration") or 0) if t else 0.0


def projects_on_disk():
    """Long-video projects made outside the studio (the story kit, the ComfyUI workflows): [{"project", "parts"}]."""
    mine = set()
    for quick in (False, True):
        for s in summaries(quick):
            f = load(s["id"])
            mine.add(f["long_project"])
    out = []
    for name in sorted(os.listdir(config.LONG_DIR)) if os.path.isdir(config.LONG_DIR) else []:
        seg = os.path.join(config.LONG_DIR, name, "segments")
        if name in mine or name.startswith("st_") or not os.path.isdir(seg):
            continue
        n = len([f for f in os.listdir(seg) if f.startswith("part_") and f.endswith(".mkv") and "sheet" not in f])
        if n:
            out.append({"project": name, "parts": n})
    return out


def adopt(project, name="", story=""):
    """Open a long-video project that was made outside the studio as a film: one shot a part, each with its part as an
    approved take. The project folder stays where it is and is never moved or deleted by the studio; new shots can be
    added after the last part. The nodes keep no prompts: `story`, the story-kit file the project was made from, brings
    the prompts, lines, cast, places and props along (see story_into); without it the shots are empty."""
    told = read_story(story) if story else None           # before anything is made: a file that cannot be read stops here
    root = os.path.join(config.LONG_DIR, project)
    if not project or "/" in project or ".." in project or not os.path.isdir(os.path.join(root, "segments")):
        raise ValueError("no such long-video project")
    if project not in [p["project"] for p in projects_on_disk()]:
        raise ValueError("this project already belongs to a film, or is one of the studio's own")
    first = checks.probe(os.path.join(root, "segments", "part_001.mkv"))
    if not first.get("has_video"):
        raise ValueError("part 1 of this project cannot be read")
    with LOCK:
        film = create(name or project.replace("_", " "), bible={"width": first["width"], "height": first["height"]})
        film["long_project"], film["adopted"] = project, True
        film["gate"] = {"mode": "hold", "retries": 0}
        kinds = config.read_json(os.path.join(root, "shots.json"), {}) or {}
        part = 1
        while os.path.isfile(part_files(film, part)["segment"]):
            seg = part_files(film, part)["segment"]
            cont = int(kinds.get(str(part), 0)) > 0
            s = new_shot(film, title=f"Part {part}", new_shot=not cont, mode="free",
                         notes="Brought in from an existing project; its prompt is not known.")
            d = take_dir(film, s)
            os.makedirs(d, exist_ok=True)
            preview, sheet = os.path.join(d, "take_01.mp4"), os.path.join(d, "take_01_sheet.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", seg, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart", preview], capture_output=True)
            checks.contact_sheet(seg, sheet, fps=2.0, cols=8, width=320)
            info = checks.probe(seg)
            rel = lambda p: os.path.relpath(p, config.OUTPUT_DIR).replace(os.sep, "/") if os.path.isfile(p) else ""
            prev = film["shots"][part - 2] if part > 1 else None
            s.update(part=part, circled=1, status="approved", takes=[{
                "n": 1, "seed": 0, "time": os.path.getmtime(seg), "seconds_taken": 0, "job": "", "prompt": "(not known)",
                "frames": int(round((info.get("duration") or 0) * lengths.FPS)) + (lengths.CONTEXT if cont else 0),
                "width": info.get("width"), "height": info.get("height"), "loras": [], "continuation": cont,
                "prev_shot": prev["id"] if (prev and cont) else "", "prev_take": 1 if (prev and cont) else 0,
                "duration": info.get("duration"), "checks": {"ok": None, "summary": "brought in; not checked here", "checks": []},
                "verdict": "approved", "preview": rel(preview), "sheet": rel(sheet), "identity": "", "kept": {}}])
            part += 1
        if told:
            try:
                story_into(film, told, story)
            except ValueError:
                save(film)
                delete(film["id"])                          # not this project's story: nothing is left half made
                raise
        save(film)
        for path, up in ((full_path(film), False), (full_path(film, upscaled=True), True)):
            if os.path.isfile(path):
                library.add(path, "film", name=film["name"] + (" (upscaled)" if up else ""), film=film["id"], film_name=film["name"], upscaled=up or None)
        return film


# ------------------------------------------------------------------ a story-kit story into a brought-in film
def read_story(path):
    """What a story-kit file defines (studio/story_reader.py). The file is a program: it is run, in a process of its own."""
    path = os.path.abspath(os.path.expanduser((path or "").strip()))
    if not path.endswith(".py") or not os.path.isfile(path):
        raise ValueError("the story file is a .py file of the story kit; there is no such file: " + path)
    try:
        r = subprocess.run([sys.executable, "-m", "studio.story_reader", path], cwd=config.REPO, capture_output=True,
                           text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ValueError("the story file did not finish within two minutes")
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("STORY ")), "")
    if r.returncode or not line:
        raise ValueError("the story file could not be read: " + ((r.stderr or "").strip().splitlines() or ["it printed nothing"])[-1][:300])
    return json.loads(line[6:])


def _sentences(text):
    return re.split(r"(?<=[.!?])\s+|\n", text)


def _owner(n, names, prompts):
    """Whose picture is Picture n: the name that stands closest before it in its sentence, in most of the prompts."""
    votes = {}
    for p in prompts:
        for sent in _sentences(p):
            at = sent.find(f"Picture {n}")
            found = [(m.start(), nm) for nm in names for m in re.finditer(rf"\b{re.escape(nm)}\b", sent[:max(at, 0)])]
            if at >= 0 and found:
                votes[max(found)[1]] = votes.get(max(found)[1], 0) + 1
    return max(votes, key=votes.get) if votes else ""


def _described(name, n, prompts):
    """What the prompts say about a person in the same words every time: the sentence that names them with their
    picture, as far as every part has it."""
    found = []
    for p in prompts:
        for sent in _sentences(p):
            m = re.search(rf"\b{re.escape(name)}\b", sent)
            if m and f"Picture {n}" in sent[m.end():]:
                found.append(sent[m.end():])
                break
    if not found:
        return ""
    text = os.path.commonprefix(found)
    if any(len(f) > len(text) for f in found):              # from here the parts go on differently: keep the whole clauses
        cut = max(text.rfind(c) for c in ";,.")
        text = text[:cut] if cut > 0 else text
    text = re.sub(r"\b(?:(?:his|her|their|its) face is exactly the face in|exactly like|from|in|of) Picture \d(?: and Picture \d)?\s*[,:;]?\s*", "", text)
    return " ".join(text.strip(" ,;:.").split())


def _place_names(files):
    """Names for places from their picture files: what the file names do not share ("nn_bar_loc.png" -> "Bar")."""
    stems = [[w for w in re.split(r"[_\-\s]+", os.path.splitext(os.path.basename(f))[0]) if w] or [f] for f in files]
    if len(stems) > 1:
        while all(len(x) > 1 for x in stems) and len({x[0] for x in stems}) == 1:
            stems = [x[1:] for x in stems]
        while all(len(x) > 1 for x in stems) and len({x[-1] for x in stems}) == 1:
            stems = [x[:-1] for x in stems]
    return [" ".join(x).capitalize() for x in stems]


def _place_words(prompt, tokens):
    """How a prompt describes its place: its sentences up to the first one about a picture."""
    out = []
    for sent in _sentences(re.sub(r"^\s*\[Shot \d+\]\s*", "", prompt)):
        tok = next((t for t in tokens if t in sent), "")
        if tok and not out:                                 # "A side street at night, the car from <CAR>: ...": the words before the thing
            head = sent[:sent.index(tok)]
            head = head[:max(head.rfind(c) for c in ",;:")].strip()
            if len(head) > 8:
                out.append(head + ".")
        if not sent.strip() or "Picture" in sent or tok:
            break
        out.append(sent.strip())
    return " ".join(out)[:600]


def story_into(film, story, source=""):
    """Fill a brought-in film from the story-kit story it was made from. Returns what was done.

    Every part's prompt and lines go into its shot ("My own prompt"), the story's people become the cast with their
    pictures, its location pictures the places, its prop sheets the props, and its size, length, model and LoRAs the
    bible. The pictures keep the numbers the story's words use: Picture 1 and 2 are the story's FACE and BODY in every
    part, then the place, then the props a part names. The first line that all parts share becomes the film's own
    words for its look; without one the shots keep theirs and the film adds none. Each shot is then composed the
    studio's way and compared with what the story kit sends: `same` counts the parts that come out identical.
    `missing` names the story's pictures and voice samples that are not in ComfyUI's input folder.
    Parts that the story has and the project does not yet are added as shots to render. Takes, checks and verdicts
    are not touched."""
    parts = story.get("parts") or []
    if not parts:
        raise ValueError("this story has no parts")
    by_part = {s["part"]: s for s in film["shots"] if s.get("part")}
    wrong = [p["part"] for p in parts if p["part"] in by_part and bool(by_part[p["part"]].get("new_shot", True)) != bool(p["new"])]
    if wrong:
        raise ValueError("this does not look like the story of this project: part " + ", ".join(map(str, wrong[:8]))
                         + " opens a new shot in one and continues the part before in the other")
    bible = film["bible"]
    if story.get("seconds"):
        bible["frames"] = lengths.from_seconds(story["seconds"])
    bible["turbo"] = bool(story.get("turbo", True))
    if story.get("unet"):
        bible["unet"] = story["unet"]
    prompts = [p["prompt"] for p in parts]
    firsts = {p.split("\n", 1)[0].strip() for p in prompts}
    style = firsts.pop() if len(parts) > 1 and len(firsts) == 1 and all("\n" in p for p in prompts) else ""
    if style:
        bible["style"] = style
    else:
        bible["style"], bible["look"] = "", "none"        # every prompt opens in its own words: the film adds no line
    words = lambda p: (p["prompt"].split("\n", 1)[1] if style else p["prompt"]).strip()
    common = [l for l in parts[0]["loras"] if all(l in p["loras"] for p in parts)]
    bible["loras"] = [{"file": f, "strength": w} for f, w in common]

    # the cast: everyone with a voice entry, and whoever the story's two pictures belong to
    def member(name):
        c = next((c for c in film["cast"] if c.get("name") == name), None)
        if c is None:
            c = {"id": _new_id(), "name": name, "pronoun": "their", "description": "", "face": "", "body": "", "voice": "", "lora": {}}
            film["cast"].append(c)
        return c
    names = [v[0] for v in story.get("voices") or []]
    for name, voice, pronoun in story.get("voices") or []:
        c = member(name)
        c["voice"], c["pronoun"] = voice or c.get("voice", ""), pronoun if pronoun in compose.PRONOUNS else "their"
    face_of = body_of = ""
    if story.get("face"):
        face_of = _owner(1, names, prompts) or (names[0] if len(names) == 1 else "Main character")
        member(face_of)["face"] = story["face"]
    if story.get("body"):
        body_of = _owner(2, names, prompts) or face_of or "Main character"
        member(body_of)["body" if body_of == face_of else "face"] = story["body"]
    for name, n in ((face_of, 1), (body_of, 2)):
        if name and name != ("" if n == 1 else face_of) and not member(name)["description"]:
            member(name)["description"] = _described(name, n, prompts)
    for f, w in common:                                     # a LoRA named after someone is theirs (the upscale uses it too)
        c = next((c for c in film["cast"] if len(c["name"]) > 2 and c["name"].lower() in os.path.basename(f).lower()), None)
        if c and not (c.get("lora") or {}).get("file"):
            c["lora"] = {"file": f, "strength": w}
    in_every_shot = [member(n)["id"] for n in dict.fromkeys([face_of, body_of]) if n]
    ids = {c["name"]: c["id"] for c in film["cast"]}

    tokens = [t for t, _ in story.get("props") or []]
    for tok, sheet in story.get("props") or []:
        if not any(x.get("token") == tok for x in film["props"]):
            nm = re.sub(r"(?i)ref$", "", tok.strip("<>{}[]")).replace("_", " ").strip().capitalize() or tok
            film["props"].append({"id": _new_id(), "name": nm, "token": tok, "sheet": sheet})
    files = list(dict.fromkeys(p["loc"] for p in parts if p["loc"]))
    place = {}
    for f, nm in zip(files, _place_names(files)):
        loc = next((x for x in film["locations"] if x.get("plate") == f), None)
        if loc is None:
            loc = {"id": _new_id(), "name": nm, "description": "", "plate": f}
            film["locations"].append(loc)
        if not loc.get("description"):
            loc["description"] = _place_words(words(next(p for p in parts if p["loc"] == f)), tokens)
        place[f] = loc["id"]

    name = os.path.basename(source) if source else "the story file"
    filled = added = 0
    told = {}                                               # shot id -> its part of the story
    for p in parts:
        s = by_part.get(p["part"])
        if s is None:
            if any(x > p["part"] for x in by_part):
                continue                                    # a gap in the project's parts: left alone
            s = new_shot(film, title=f"Part {p['part']}")
            added += 1
        else:
            filled += 1
        s.update(mode="free", new_shot=bool(p["new"]), prompt=words(p), cast=list(in_every_shot), location=place.get(p["loc"], ""),
                 lines=[{"speaker": ids.get(who, who), "text": text, "how": how} for who, text, how in p["lines"]],
                 loras=[{"file": f, "strength": w} for f, w in p["loras"] if [f, w] not in common],
                 notes=f"Prompt, lines and pictures read from {name}.")
        told[s["id"]] = p
        for t in s.get("takes") or []:
            if t.get("prompt") in ("", "(not known)"):
                t["prompt"] = p["sent"] or p["prompt"]
                t["loras"] = [list(l) for l in p["loras"]]

    same, differ = 0, []
    for i, s in enumerate(film["shots"]):
        p = told.get(s["id"])
        if not p or not p["sent"]:
            continue
        c = compose.compose(film, s, i)
        if c["prompt"].strip() == p["sent"].strip() and c["refs"] == [x for x in p["pictures"] if x]:
            same += 1
        else:
            differ.append(p["part"])
    film["story"] = {"file": source, "read": time.time(), "parts": len(parts)}
    used = [story.get("face"), story.get("body"), story.get("face_cont")] + files + [x[1] for x in story.get("props") or []] \
        + [v[1] for v in story.get("voices") or []]
    missing = [f for f in dict.fromkeys(x for x in used if x) if not os.path.isfile(config.ref_path(f))]
    return {"parts": len(parts), "filled": filled, "added": added, "same": same, "differ": differ, "style": bool(style), "missing": missing,
            "cast": [c["name"] for c in film["cast"]], "places": [x["name"] for x in film["locations"]],
            "props": [x["name"] for x in film["props"]]}


def apply_story(fid, path):
    """Read a story-kit file into a film that was brought in from a project. Returns (film, what was done)."""
    story = read_story(path)                                # outside the lock: it runs a program
    with LOCK:
        film = load(fid)
        if not film:
            raise KeyError(fid)
        if not film.get("adopted"):
            raise ValueError("a story file is read into a film that was brought in from a project, while its parts are "
                             "still in the order they were made in")
        report = story_into(film, story, os.path.abspath(os.path.expanduser(path.strip())))
        save(film)
        return film, report


def delete(fid):
    """A film and its project folder go to the trash (studio/trash/films/...). A project that was brought in from
    outside stays where it is: only the studio's own file of the film is removed."""
    with LOCK:
        film = load(fid)
        if not film:
            return False
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dst = config.home("trash", "films", f"{fid}_{stamp}")
        os.makedirs(dst, exist_ok=True)
        if os.path.isdir(project_dir(film)) and not film.get("adopted"):
            shutil.move(project_dir(film), os.path.join(dst, "long_video_" + film["long_project"]))
        shutil.move(film_dir(fid), os.path.join(dst, "film"))
        library.forget(film=fid)             # its files went with the folder; the records would point at nothing
        return True


# ------------------------------------------------------------------ shots and takes
def shot_index(film, sid):
    for i, s in enumerate(film["shots"]):
        if s["id"] == sid:
            return i
    return -1


def get_shot(film, sid):
    i = shot_index(film, sid)
    return film["shots"][i] if i >= 0 else None


def active_take(shot):
    n = shot.get("circled") or 0
    for t in shot.get("takes", []):
        if t["n"] == n:
            return t
    return None


def speech_levels(film, but=""):
    """How loud speech peaks in the film's approved takes (LUFS), one number a shot: what a new take is compared with."""
    out = []
    for s in film["shots"]:
        t = active_take(s)
        if s["id"] == but or not t or t.get("verdict") not in ("approved", "auto"):
            continue
        for c in (t.get("checks") or {}).get("checks") or []:
            if c.get("name") == "loudness" and c.get("speech") and c.get("value") is not None:
                out.append(c["value"])
    return out


def new_shot(film, **fields):
    s = compose.blank_shot()
    s["id"] = _new_id()
    s.update({k: v for k, v in fields.items() if k in USER_SHOT_FIELDS})
    film["shots"].append(s)
    return s


def is_continuation(film, index):
    """How shot `index` would render now."""
    return index > 0 and not film["shots"][index].get("new_shot", True)


def eligible(film, sid, ignore_gate=False):
    """(True, "") when the shot can be rendered now, else (False, why)."""
    i = shot_index(film, sid)
    if i < 0:
        return False, "no such shot"
    for j in range(i):
        if not film["shots"][j].get("part"):
            return False, (f"shot {j + 1} has to be rendered first: the parts of a film are appended in order")
    if is_continuation(film, i) and not ignore_gate:
        prev = film["shots"][i - 1]
        if prev["status"] != "approved":
            return False, (f"this shot continues shot {i}, which is not approved yet "
                           f"(nothing is built on a part that has not passed)")
    return True, ""


def next_to_render(film, keep_going=False):
    """The first shot, in order, that has no usable take. A take waiting at the gate stops the search, unless the run
    keeps going past takes that still need a look (the night shift)."""
    for s in film["shots"]:
        if s["status"] in ("todo", "stale", "failed") or not s.get("part"):
            return s
        if s["status"] == "review" and not keep_going:
            return None                      # the gate is waiting on this one
    return None


def apply_edit(fid, incoming):
    """Merge what the user changed into the saved film. The runner's own fields (takes, status, part numbers) are kept.
    Returns (film, report): report lists moved and stale shots when the order of rendered shots changed."""
    with LOCK:
        film = load(fid)
        if not film:
            raise KeyError(fid)
        for k in USER_FILM_FIELDS:
            if k in incoming:
                film[k] = incoming[k]
        for group in ("cast", "locations", "props"):
            for item in film.get(group, []):
                if not item.get("id"):
                    item["id"] = _new_id()
        if "blockouts" in incoming:
            merge_blockouts(film, incoming["blockouts"])
        report = {"moved": [], "stale": [], "removed": []}
        if "shots" in incoming:
            old = {s["id"]: s for s in film["shots"]}
            merged = []
            for inc in incoming["shots"]:
                cur = old.pop(inc.get("id"), None)
                if cur is None:
                    cur = compose.blank_shot()
                    cur["id"] = inc.get("id") if inc.get("id") and "/" not in str(inc.get("id")) else _new_id()
                for k in USER_SHOT_FIELDS:
                    if k in inc:
                        cur[k] = inc[k]
                merged.append(cur)
            for gone in old.values():
                report["removed"].append(gone["id"])
                d = take_dir(film, gone)
                if os.path.isdir(d):
                    dst = config.home("trash", "takes", f"{film['id']}_{gone['id']}_{int(time.time())}")
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(d, dst)
            film["shots"] = merged
            report.update(resequence(film))
        save(film)
        return film, report


def _read_shots(film, project=None):
    return config.read_json(_shots_json(film, project), {}) or {}


def resequence(film):
    """Give every rendered shot the part number of its place in the film.

    Returns {"moved": [...shot ids], "stale": [...shot ids]}. Nothing is done when every rendered shot already sits at
    its place. Otherwise the kept parts are copied into a new project folder and the old one goes to the trash.
    """
    shots = film["shots"]
    plan, stale, keep_ok = [], [], {}
    for i, s in enumerate(shots):
        want = i + 1
        if not s.get("part"):
            keep_ok[s["id"]] = False
            continue
        t = active_take(s) or {}
        ok = True
        if t.get("continuation"):
            prev = shots[i - 1] if i > 0 else None
            ok = bool(prev and keep_ok.get(prev["id"]) and t.get("prev_shot") == prev["id"]
                      and t.get("prev_take") == prev.get("circled"))
        keep_ok[s["id"]] = ok
        if ok:
            plan.append((s, s["part"], want))
        else:
            stale.append(s)
    if not stale and all(a == b for _, a, b in plan):
        return {"moved": [], "stale": []}

    old_project = film["long_project"]
    film["revision"] = int(film.get("revision", 0)) + 1
    new_project = f"st_{film['id']}_r{film['revision']}"
    old_shots = _read_shots(film, old_project)
    new_shots = {}
    for s, src, dst in plan:
        a, b = part_files(film, src, old_project), part_files(film, dst, new_project)
        for key in a:
            if os.path.isfile(a[key]):
                _link(a[key], b[key])
        new_shots[str(dst)] = int(old_shots.get(str(src), lengths.CONTEXT if (active_take(s) or {}).get("continuation") else 0))
    os.makedirs(os.path.join(config.LONG_DIR, new_project, "segments"), exist_ok=True)
    config.write_json(_shots_json(film, new_project), new_shots)
    moved = [s["id"] for s, a, b in plan if a != b]
    for s, _, dst in plan:
        s["part"] = dst
    for s in stale:
        s["part"] = 0
        s["status"] = "stale"
    film["long_project"] = new_project
    film["upscaled"] = {}
    old_dir = os.path.join(config.LONG_DIR, old_project)
    if film.get("adopted"):
        film["adopted"] = False             # the film now lives in its own folder; the project it came from is left alone
    elif os.path.isdir(old_dir):
        dst = config.home("trash", "projects", f"{old_project}_{int(time.time())}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(old_dir, dst)
    rebuild_full(film)
    return {"moved": moved, "stale": [s["id"] for s in stale]}


def rebuild_full(film):
    """Join parts 1..N (as far as they are there without a gap) into <project>_full.mp4, the way the Append node does.
    Returns the path, or None when part 1 is missing."""
    root = project_dir(film)
    last = 0
    while os.path.isfile(part_files(film, last + 1)["segment"]):
        last += 1
    full = full_path(film)
    if last == 0:
        if os.path.isfile(full):
            os.unlink(full)
        return None
    lst = os.path.join(root, "segments", "concat.txt")
    with open(lst, "w") as f:
        for i in range(1, last + 1):
            f.write(f"file 'part_{i:03d}.mkv'\n")
    tmp = full + ".tmp.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("joining the parts failed: " + r.stderr.strip()[-300:])
    os.replace(tmp, full)
    return full


def supersede_after(film, index):
    """After shot `index` got new frames: the continuations that followed it no longer fit. Their parts are moved
    aside (as the Append node does) and they are marked stale, up to the next shot that started fresh."""
    shots_json = _read_shots(film)
    changed = []
    old = os.path.join(project_dir(film), "_superseded")
    for j in range(index + 1, len(film["shots"])):
        s = film["shots"][j]
        t = active_take(s) or {}
        if not s.get("part"):
            if is_continuation(film, j):
                continue
            break
        if not t.get("continuation"):
            break
        for path in part_files(film, s["part"]).values():
            if os.path.isfile(path):
                os.makedirs(old, exist_ok=True)
                shutil.move(path, os.path.join(old, os.path.basename(path)))
        shots_json.pop(str(s["part"]), None)
        s["part"] = 0
        s["status"] = "stale"
        changed.append(s["id"])
    if changed:
        config.write_json(_shots_json(film), shots_json)
    return changed


def record_take(film, shot, *, part, seed, prompt, job_id, review, composed, started):
    """Keep a finished render as a take of its shot: files, preview, contact sheet, check report.
    The shot waits at the gate ("review") afterwards. Returns the take."""
    idx = shot_index(film, shot["id"])
    files = part_files(film, part)
    n = max([t["n"] for t in shot.get("takes", [])] + [0]) + 1
    d = take_dir(film, shot)
    os.makedirs(d, exist_ok=True)
    kept = {}
    if config.settings().get("keep_takes", True):
        for key, ext in (("segment", ".mkv"), ("latent", ".safetensors"), ("cond", ".cond.pt")):
            if os.path.isfile(files[key]):
                kept[key] = os.path.join(d, f"take_{n:02d}{ext}")
                _link(files[key], kept[key])
    preview = os.path.join(d, f"take_{n:02d}.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", files["segment"], "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", preview], capture_output=True)
    sheet = os.path.join(d, f"take_{n:02d}_sheet.jpg")
    checks.contact_sheet(files["segment"], sheet, fps=2.0, cols=8, width=320)
    ident = os.path.join(d, f"take_{n:02d}_identity.jpg")
    checks.identity_sheet(files["segment"], ident)
    prev = film["shots"][idx - 1] if idx > 0 else None
    cont = bool(composed.get("continuation"))
    rel = lambda p: os.path.relpath(p, config.OUTPUT_DIR).replace(os.sep, "/") if p and os.path.isfile(p) else ""
    take = {"n": n, "seed": seed, "time": time.time(), "seconds_taken": round(time.time() - started, 1), "job": job_id,
            "prompt": prompt, "frames": composed.get("frames"), "width": composed.get("width"), "height": composed.get("height"),
            "loras": composed.get("loras", []), "continuation": cont,
            "prev_shot": prev["id"] if (prev and cont) else "", "prev_take": prev.get("circled", 0) if (prev and cont) else 0,
            "duration": review.get("duration"), "checks": {k: review.get(k) for k in ("ok", "summary", "checks", "window", "integrated")},
            "verdict": "pending", "preview": rel(preview), "sheet": rel(sheet), "identity": rel(ident),
            "kept": {k: rel(v) for k, v in kept.items()}}
    shot.setdefault("takes", []).append(take)
    shot["circled"] = n
    shot["part"] = part
    shot["status"] = "review"
    if os.path.isfile(preview) and not film.get("quick"):      # a quick clip is in the Library as its whole video
        a = library.add(preview, "clip", name=f"{film['name']} · {shot.get('title') or 'shot ' + str(idx + 1)} · take {n}",
                        film=film["id"], film_name=film["name"], shot=shot["id"], take=n, prompt=prompt, seed=seed,
                        ok=review.get("ok"), summary=review.get("summary"), quick=bool(film.get("quick")), job=job_id)
        take["asset"] = a["id"]
    supersede_after(film, idx)
    return take


def set_verdict(film, sid, verdict):
    """approve / reject the active take of a shot."""
    shot = get_shot(film, sid)
    t = active_take(shot) if shot else None
    if not t:
        raise ValueError("this shot has no take")
    t["verdict"] = verdict
    shot["status"] = "approved" if verdict in ("approved", "auto") else "review"
    if t.get("asset"):
        library.update(t["asset"], verdict=verdict)
    return shot


def restore_take(film, sid, n):
    """Make an earlier take the shot's part again. The continuations after it become stale."""
    shot = get_shot(film, sid)
    idx = shot_index(film, sid)
    take = next((t for t in shot.get("takes", []) if t["n"] == n), None) if shot else None
    if not take:
        raise ValueError("no such take")
    kept = take.get("kept") or {}
    if not kept.get("segment") or not os.path.isfile(os.path.join(config.OUTPUT_DIR, kept["segment"])):
        raise ValueError("the files of this take were not kept")
    if take.get("continuation"):
        prev = film["shots"][idx - 1] if idx > 0 else None
        if not prev or prev["id"] != take.get("prev_shot") or prev.get("circled") != take.get("prev_take"):
            raise ValueError("this take continued another take of the shot before it; it no longer fits")
    part = shot.get("part") or (idx + 1)
    ok, why = (True, "") if shot.get("part") else eligible(film, sid, ignore_gate=True)
    if not ok:
        raise ValueError(why)
    files = part_files(film, part)
    for key in ("segment", "latent", "cond"):
        if kept.get(key):
            _link(os.path.join(config.OUTPUT_DIR, kept[key]), files[key])
    sj = _read_shots(film)
    sj[str(part)] = lengths.CONTEXT if take.get("continuation") else 0
    config.write_json(_shots_json(film), sj)
    shot["part"], shot["circled"] = part, n
    shot["status"] = "approved" if take.get("verdict") in ("approved", "auto") else "review"
    stale = supersede_after(film, idx)
    rebuild_full(film)
    return {"stale": stale}


def clear_take_state(film, sid, status="todo"):
    shot = get_shot(film, sid)
    if shot:
        shot["status"] = status
    return shot


def to_story(film):
    """The film as a story-kit file (story_kit/run_story.py runs it from the command line). Shots written in fields
    are exported as their composed prompt with {DIALOGUE} where the lines go."""
    lines_out = [f'"""{film["name"]}: exported from H3 Studio. Run with story_kit/run_story.py gen <this file> <project>."""',
                 f'WIDTH, HEIGHT, SECONDS, TURBO = {film["bible"]["width"]}, {film["bible"]["height"]}, '
                 f'{film["bible"]["frames"] / lengths.FPS:.3f}, {bool(film["bible"].get("turbo", True))}']
    cast = film.get("cast") or []
    face = next((c.get("face") for c in cast if c.get("face")), "")
    body = next((c.get("body") for c in cast if c.get("body")), "") or (cast[1].get("face") if len(cast) > 1 else "") or face
    lines_out.append(f"FACE = {face!r}      # Picture 1")
    lines_out.append(f"BODY = {body!r}      # Picture 2")
    if film["bible"].get("unet"):
        lines_out.append(f'UNET = {film["bible"]["unet"]!r}')
    lines_out.append("DIALOGUE_MODE = 'h3'")
    voices = {c["name"]: (c.get("voice") or None, c.get("pronoun") or "their") for c in cast}
    lines_out.append(f"VOICES = {voices!r}")
    lines_out.append(f"PROPS = {{}}")
    lines_out.append("PARTS = {")
    for i, s in enumerate(film["shots"]):
        c = compose.compose(film, s, i)
        loc = ""
        for lb in c["pictures"]:
            if lb["kind"] == "plate":
                loc = lb["file"]
        lns = [(ln["speaker"], ln["text"], ln.get("how", "")) for ln in c["lines"]]
        lines_out.append(f" {i + 1}: ({not c['continuation']!r}, {loc or None!r}, {[tuple(l) for l in c['loras']]!r},\n"
                         f"     {c['prompt']!r}" + (f",\n     {lns!r}" if lns else "") + "),")
    lines_out.append("}")
    return "\n".join(lines_out) + "\n"
