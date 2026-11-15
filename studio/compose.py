"""From a shot's fields to the prompt MiniMax H3 gets, with its pictures and voices in order.

The wording is the one that held up over a 20-part dialogue film (docs/prompting.md says where each sentence comes from):

  new shot       {style}
                 [Shot 1] {place}. The place looks exactly like Picture N; no readable text... {who, with their pictures and
                 where they are}. {framing}. {camera}, one continuous take... {how a conversation looks}.
                 {what happens} {the lines, each with how it is said and <d>[Language] exact words</d>} {only words}.

                 overall_soundscape:
                 {sound}

  continuation   {style}
                 Continue the same shot without a cut: the same place, the same light and the same camera position.
                 {what happens} {lines} ...        (no place, no pictures named: the frames of the part before carry them)

Pictures are numbered in the order the model labels them: a first frame, a last frame, then the reference pictures
(each person's face and outfit sheet, the place, the props that are named, further pictures). Voices are <Audio 1..>.
"""
import re

from . import config, lengths, presets, promptcheck

TAKE = "one continuous take, it never cuts and there are no close-ups"
CONT = "Continue the same shot without a cut: the same place, the same light and the same camera position."
CONT_BLOCKOUT = "Continue the same shot without a cut: the same place and the same light, the camera keeps following <Video 1>."
# a shot that follows a blockout video. Worded after the prompts of a 10-part film rendered this way (2026-11-14,
# docs/prompting.md "Blockouts"): the model has to be told that the shapes are stand-ins, and that the camera is the
# blockout's; a prompt that names a framing of its own ("close to Santa") won over the blockout.
BLOCKOUT = ("<Video 1> is a rough 3D blockout of this shot. It gives only the camera framing, camera movement and "
            "perspective, and the positions, size, motion and timing of everything in it; its flat untextured shapes are "
            "placeholders{shapes}. The video is a photorealistic live-action version of <Video 1>: keep its camera viewpoint, "
            "framing, camera movement, perspective, pacing and the place of everything in the frame exactly, and replace "
            "every flat shape with its real counterpart")
LOOK = ("They look at each other while they talk, like in a real conversation, both faces in three-quarter view and clearly "
        "visible; nobody looks into the camera. They act naturally like good film actors: relaxed body language, small natural "
        "head movements and hand gestures, facial expressions that match every line, and the one who listens reacts while the "
        "other speaks with small nods, smiles or a short laugh; short natural pauses between the lines")
END_MANY = "Those are the only words; after that nobody says anything else"
END_ONE = "After that nobody says anything else"
NOTEXT = "no readable text, letters, signs or logos anywhere"
DEFAULT_SOUND = "Natural ambient sound of the place."
PRONOUNS = {"his": ("he", "his"), "her": ("she", "her"), "their": ("they", "their"), "its": ("it", "its")}
LORA_SUM_LIMIT = 1.3


def blank_bible():
    v = config.settings()["video"]
    return {"logline": "", "world": "", "style": "", "look": "cinematic", "lens": "", "light": "", "notext": True,
            "language": v["language"], "width": v["width"], "height": v["height"], "frames": v["frames"],
            "turbo": v["turbo"], "loras": [], "unet": "", "one_take": True}


def blank_shot():
    return {"id": "", "title": "", "scene": "", "new_shot": True, "mode": "fields", "place": "", "location": "", "cast": [],
            "staging": {}, "framing": "", "camera": "", "camera_text": "", "action": "", "lines": [], "sound": "",
            "props": [], "refs": [], "first_frame": "", "last_frame": "", "prompt": "", "frames": 0, "seed": 0,
            "loras": [], "one_take": None, "talking_head": False, "notes": "",
            "blockout": "", "blockout_start": 0, "blockout_strength": 0, "blockout_shapes": "", "preview": None,
            "status": "todo", "takes": [], "circled": 0, "part": 0, "storyboard": []}


def _cap(t):
    """The first letter as a capital (after a [Shot n] tag when there is one)."""
    m = re.match(r"(\[Shot \d+\]\s*)?([a-z])", t)
    return t[:m.start(2)] + m.group(2).upper() + t[m.end(2):] if m else t


def _sentence(text):
    """Trim, start with a capital, and end with a full stop unless it already ends a sentence."""
    t = " ".join((text or "").split())
    if not t:
        return ""
    t = _cap(t)
    return t if t[-1] in ".!?:;" else t + "."


def _join(*parts):
    return " ".join(p for p in (_sentence(x) for x in parts) if p)


def style_line(bible):
    """The line every prompt of a film opens with: its own words, or the chosen look, lens and light."""
    if (bible.get("style") or "").strip():
        return _sentence(bible["style"])
    if bible.get("look") == "none":                        # every shot opens in its own words (a story brought in whole)
        return ""
    base = presets.text("looks", "styles", bible.get("look") or "cinematic") or presets.text("looks", "styles", "cinematic")
    extra = [presets.text("looks", "lenses", bible.get("lens") or ""), presets.text("looks", "lights", bible.get("light") or "")]
    extra = [e for e in extra if e]
    if not extra:
        return base
    return base.rstrip(".") + ", " + ", ".join(e[0].lower() + e[1:] for e in extra) + "."


def _by_id(items, ident):
    for it in items or []:
        if it.get("id") == ident or it.get("name") == ident:
            return it
    return None


def _speaker_name(film, speaker):
    c = _by_id(film.get("cast"), speaker)
    return c["name"] if c else str(speaker)


def pictures(film, shot, cont):
    """The pictures of a shot in the model's label order.

    Returns (keyframes, refs, labels): keyframes {"first": file, "last": file}, refs [file, ...] and
    labels [{"n", "what", "file", "kind", "id"}] for everything that has a number.
    """
    labels, refs, key = [], [], {}
    n = 0
    if shot.get("first_frame") and not cont:
        n += 1
        key["first"] = shot["first_frame"]
        labels.append({"n": n, "what": "the first frame", "file": shot["first_frame"], "kind": "first", "id": ""})
    if shot.get("last_frame"):
        n += 1
        key["last"] = shot["last_frame"]
        labels.append({"n": n, "what": "the last frame", "file": shot["last_frame"], "kind": "last", "id": ""})

    def add(file, what, kind, ident):
        nonlocal n
        n += 1
        refs.append(file)
        labels.append({"n": n, "what": what, "file": file, "kind": kind, "id": ident})

    for cid in shot.get("cast") or []:
        c = _by_id(film.get("cast"), cid)
        if not c:
            continue
        if c.get("face"):
            add(c["face"], f"{c['name']}'s face", "face", c["id"])
        if c.get("body"):
            add(c["body"], f"{c['name']}'s outfit sheet", "body", c["id"])
    loc = _by_id(film.get("locations"), shot.get("location")) if shot.get("location") else None
    if loc and loc.get("plate") and not cont:
        add(loc["plate"], f"the place: {loc['name']}", "plate", loc["id"])
    text = " ".join([shot.get("action") or "", shot.get("place") or "", shot.get("prompt") or "",
                     " ".join((shot.get("staging") or {}).values())])
    for p in film.get("props") or []:
        if p.get("sheet") and p.get("token") and p["token"] in text:
            add(p["sheet"], p.get("name") or p["token"], "prop", p["id"])
    for r in shot.get("refs") or []:
        if r.get("file"):
            add(r["file"], r.get("label") or "a further picture", "ref", "")
    return key, refs, labels


def _n(labels, kind, ident):
    for lb in labels:
        if lb["kind"] == kind and lb["id"] == ident:
            return lb["n"]
    return 0


def person_clause(c, labels, staging=""):
    """A character as the prompt introduces them: who they are, which pictures show them, where they are."""
    _, poss = PRONOUNS.get(c.get("pronoun") or "their", PRONOUNS["their"])
    f, b = _n(labels, "face", c["id"]), _n(labels, "body", c["id"])
    desc = (c.get("description") or "").strip().rstrip(".")
    if f and b:
        s = f"{c['name']} from Picture {f} and Picture {b}" + (f", {desc}" if desc else "") + f", wearing the outfit from Picture {b}"
    elif f:
        s = f"{c['name']}, {poss} face is exactly the face in Picture {f}" + (f": {desc}" if desc else "")
    elif b:
        s = f"{c['name']} from Picture {b}" + (f", {desc}" if desc else "")
    else:
        s = c["name"] + (f", {desc}" if desc else "")
    st = (staging or "").strip().rstrip(".")
    if st and not re.match(rf"(?:he|she|they|it|{re.escape(c['name'])})\b", st, re.I):
        subj = {"his": "he", "her": "she"}.get(c.get("pronoun") or "", c["name"])
        st = f"{subj} {st[0].lower() + st[1:]}"
    return s + (f"; {st}" if st else "")


def spoken(film, shot, voices_n, multi):
    """The lines of a shot as sentences, each with who says it, how, and the exact words in a <d> tag."""
    lines = shot.get("lines") or []
    lang = (film.get("bible") or {}).get("language") or "English"
    cast = [c for c in (_by_id(film.get("cast"), cid) for cid in shot.get("cast") or []) if c]
    names = [c["name"] for c in cast]
    order = list(names)
    for ln in lines:
        nm = _speaker_name(film, ln.get("speaker"))
        if nm not in order:
            order.append(nm)
    out = []
    prev = None
    for k, ln in enumerate(lines):
        nm = _speaker_name(film, ln.get("speaker"))
        c = _by_id(film.get("cast"), ln.get("speaker")) or _by_id(film.get("cast"), nm) or {}
        _, poss = PRONOUNS.get(c.get("pronoun") or "their", PRONOUNS["their"])
        verb = "says" if k == 0 else ("answers" if prev != nm else "adds")
        if multi:
            others = [x for x in order if x != nm]
            at = others[0] if len(others) == 1 else "the others"
            sync = f"looking at {at}, {poss} face in three-quarter view and clearly visible to the camera, {poss} lips moving clearly and in sync with every word,"
        elif shot.get("talking_head"):
            sync = f"looking into the camera, {poss} lips moving clearly and in sync with every word,"
        else:
            sync = f"{poss} lips moving clearly and in sync with every word,"
        voice = f" speaking in the voice from <Audio {voices_n[nm]}>," if nm in voices_n else ""
        how = (ln.get("how") or "").strip().rstrip(",.")
        how = f" {how}," if how else ""
        tag = f"{nm} (S{order.index(nm) + 1})"
        out.append(f"{tag} {verb}, {sync}{voice}{how} <d>[{lang}] {ln.get('text', '').strip()}</d>")
        prev = nm
    return " ".join(out)


def gather_loras(film, shot, info=None):
    """LoRAs of a shot: the film's, each cast member's, the shot's own and (when installed) the camera move's.
    One entry per file, the strongest wins. Returns ([(file, strength)], triggers, notes)."""
    from . import models
    got, triggers, notes = {}, [], []

    def put(file, strength):
        if file:
            got[file] = max(float(strength or 1.0), got.get(file, 0.0))

    for l in (film.get("bible") or {}).get("loras") or []:
        put(l.get("file") if isinstance(l, dict) else l[0], l.get("strength", 1.0) if isinstance(l, dict) else l[1])
    for cid in shot.get("cast") or []:
        c = _by_id(film.get("cast"), cid) or {}
        if (c.get("lora") or {}).get("file"):
            put(c["lora"]["file"], c["lora"].get("strength", 1.0))
    for l in shot.get("loras") or []:
        put(l.get("file") if isinstance(l, dict) else l[0], l.get("strength", 1.0) if isinstance(l, dict) else l[1])
    move = presets.find("cameras", "moves", shot.get("camera") or "")
    if move and move.get("lora") and info is not None:
        file = models.find_lora(info, move["lora"]["pattern"])
        if file:
            put(file, move["lora"].get("strength", 0.8))
            triggers.append(move["lora"].get("trigger", ""))
        else:
            notes.append(f"\"{move['name']}\" works better with a LoRA matching \"{move['lora']['pattern']}\" (not installed); "
                         "it is rendered from the words alone.")
    extra = sum(s for f, s in got.items()) - sum(
        float((c.get("lora") or {}).get("strength", 0)) for c in ((_by_id(film.get("cast"), cid) or {}) for cid in shot.get("cast") or [])
        if (c.get("lora") or {}).get("file"))
    if extra > LORA_SUM_LIMIT + 1e-6:
        notes.append(f"the extra LoRAs add up to {extra:.1f}: three at full strength on the 8-step turbo made moving objects "
                     f"ghost. Keep the sum around {LORA_SUM_LIMIT}.")
    return [(f, s) for f, s in got.items()], [t for t in triggers if t], notes


def part_frames(bible, shot, cont):
    """(frames this shot renders, a note when its own number did not fit)."""
    frames = int(shot.get("frames") or bible.get("frames") or 243)
    if not lengths.is_count(frames):
        frames = lengths.nearest(frames)
    if lengths.fits(frames, cont):
        return frames, ""
    better = min(lengths.usable(cont), key=lambda c: abs(c - frames))
    return better, (f"{frames} frames does not work for {'a continuation' if cont else 'a new shot'} "
                    f"(its sound would not fit the picture); rendering {better} frames instead")


_FIGURE = {"person": "figure", "child": "small figure", "cyclist": "figure on a bike", "animal": "four-legged shape", "horse": "four-legged shape",
           "dog": "small four-legged shape", "box": "box", "ball": "ball", "bird": "small winged shape"}


def scene_shapes(scene):
    """"the blue figure is Mara; the red car is the taxi": what the moving shapes of a made blockout stand for."""
    if not isinstance(scene, dict):
        return ""
    out = []
    for t in scene.get("things") or []:
        name, kind = (t.get("name") or "").strip(), t.get("kind") or "box"
        if not name or name.lower() == kind:
            continue
        shape = _FIGURE.get(kind, kind)
        out.append(f"the {(t.get('color') or '').strip() + ' ' if t.get('color') else ''}{shape} is {name}")
    return "; ".join(out)


def take_of(film, index):
    """The indices of the take the shot at `index` belongs to: the shot that opens it and the continuations after it."""
    shots = film.get("shots") or []
    first = index
    while first > 0 and not shots[first].get("new_shot", True):
        first -= 1
    out = [first]
    while out[-1] + 1 < len(shots) and not shots[out[-1] + 1].get("new_shot", True):
        out.append(out[-1] + 1)
    return out


def take_frames(film, index):
    """How many frames the take of the shot at `index` runs: its first part whole, each continuation minus the context."""
    bible = {**blank_bible(), **(film.get("bible") or {})}
    shots = film["shots"]
    total = 0
    for k, i in enumerate(take_of(film, index)):
        cont = not (shots[i].get("new_shot", True) or i == 0)
        n = part_frames(bible, shots[i], cont)[0]
        total += n if k == 0 else n - lengths.CONTEXT
    return total


def blockout_plan(film, index):
    """Where the shot at `index` reads its blockout: {"file", "start", "strength", "shapes", "scene"}, or None.

    Its scene's blockout (blockouts.cuts says which stretch), once that is made. A shot can instead follow a video of
    its own ("blockout": a clip of the user's): then a new shot starts at its own blockout_start (frame 0 = the first). A continuation of a shot that uses the same
    blockout starts CONTEXT frames before the end of what that shot used: those frames are the context it takes over,
    and the blockout goes on under them, so the two parts follow one unbroken stretch of it."""
    from . import blockouts
    shots = film.get("shots") or []
    if not 0 <= index < len(shots):
        return None
    shot = shots[index]
    if not (shot.get("blockout") or "").strip():
        b = blockouts.of_shot(film, index)
        if not (b and b.get("video")):
            return None
        c = next(x for x in blockouts.cuts(film, b) if x["index"] == index)
        return {"file": b["video"], "start": c["start"],
                "strength": float(shot.get("blockout_strength") or 0) or float(config.settings()["blockout"]["strength"]),
                "shapes": (shot.get("blockout_shapes") or "").strip() or scene_shapes(b.get("scene")), "scene": b.get("id")}
    bible = {**blank_bible(), **(film.get("bible") or {})}
    cont = not (shot.get("new_shot", True) or index == 0)
    start = max(0, int(shot.get("blockout_start") or 0))
    if cont and not start and (shots[index - 1].get("blockout") or "") == shot["blockout"]:
        before = blockout_plan(film, index - 1)
        prev_cont = not (shots[index - 1].get("new_shot", True) or index - 1 == 0)
        start = before["start"] + part_frames(bible, shots[index - 1], prev_cont)[0] - lengths.CONTEXT
    strength = float(shot.get("blockout_strength") or 0) or float(config.settings()["blockout"]["strength"])
    shapes = (shot.get("blockout_shapes") or "").strip()
    if not shapes and cont and (shots[index - 1].get("blockout") or "") == shot["blockout"]:
        shapes = blockout_plan(film, index - 1)["shapes"]          # the same shapes go on meaning the same things
    return {"file": shot["blockout"], "start": start, "strength": strength, "shapes": shapes, "scene": None}


def compose(film, shot, index=0, info=None):
    """Everything a render of this shot needs. `index` is the shot's place in the film (0 = first: always a new shot).

    Returns {"prompt", "refs", "first_frame", "last_frame", "voices", "pictures", "audios", "lines", "loras", "frames",
             "continuation", "asks_for_cut", "findings"}.
    """
    bible = {**blank_bible(), **(film.get("bible") or {})}
    film = {**film, "bible": bible}
    cont = not (shot.get("new_shot", True) or index == 0)
    findings = []
    blk = None
    if True:
        shots = list(film.get("shots") or [])
        at = next((i for i, x in enumerate(shots) if x.get("id") and x.get("id") == shot.get("id")), None)
        if at is None:                      # a shot that is not saved in the film yet: plan it at its index
            shots = shots[:index] + [shot] + shots[index + 1:]
            at = index
        else:
            shots[at] = shot
        blk = blockout_plan({**film, "shots": shots}, at)
        if blk and (shot.get("first_frame") or shot.get("last_frame")):
            findings.append({"level": "note", "code": "blockout-keyframes", "quote": "",
                             "text": "a shot that follows a blockout opens and ends where the blockout does: its first and last frame are not used"})
            shot = {**shot, "first_frame": "", "last_frame": ""}
    key, refs, labels = pictures(film, shot, cont)
    cast = [c for c in (_by_id(film.get("cast"), cid) for cid in shot.get("cast") or []) if c]
    lines = [ln for ln in (shot.get("lines") or []) if (ln.get("text") or "").strip()]
    shot = {**shot, "lines": lines}
    speakers = []
    for ln in lines:
        nm = _speaker_name(film, ln.get("speaker"))
        if nm not in speakers:
            speakers.append(nm)
    multi = len(speakers) > 1

    # voices: one <Audio n> for every speaker of this shot who has a sample, in cast order
    voices, voices_n, audios = [], {}, []
    for c in cast + [x for x in (film.get("cast") or []) if x not in cast]:
        if c["name"] in speakers and c.get("voice") and c["name"] not in voices_n:
            voices.append(c["voice"])
            voices_n[c["name"]] = len(voices)
            audios.append({"n": len(voices), "speaker": c["name"], "file": c["voice"]})
    if len(voices) > 4:
        findings.append({"level": "warn", "code": "voices", "text": f"{len(voices)} voice samples: a part takes 4", "quote": ""})
        voices, audios = voices[:4], audios[:4]
        voices_n = {k: v for k, v in voices_n.items() if v <= 4}
    if len(refs) > 9:
        findings.append({"level": "warn", "code": "refs", "quote": "",
                         "text": f"{len(refs)} reference pictures: the model takes 9; the last {len(refs) - 9} are left out"})
        refs = refs[:9]

    loras, triggers, lora_notes = gather_loras(film, shot, info)
    for t in lora_notes:
        findings.append({"level": "note", "code": "lora", "text": t, "quote": ""})
    silent_line = config.settings()["video"]["silent_line"]
    said = spoken(film, shot, voices_n, multi)
    has_people = bool(cast) or bool(re.search(r"\b(?:man|woman|person|people|boy|girl|he|she|they|crowd|guests?)\b",
                                              (shot.get("action") or "") + (shot.get("prompt") or ""), re.I))

    if shot.get("mode") == "free":
        body = (shot.get("prompt") or "").strip()
        for p in film.get("props") or []:
            if p.get("token") and p["token"] in body:
                body = body.replace(p["token"], f"Picture {_n(labels, 'prop', p['id'])}")
        if "{DIALOGUE}" in body:
            tail = (" " + (END_MANY if multi else END_ONE) + ".") if said else ""
            body = body.replace("{DIALOGUE}", (said + tail).strip())
        elif said and "<d>" in body:
            # the prompt speaks its lines itself; the Lines of the shot are then only what the speech check listens for
            findings.append({"level": "note", "code": "own-lines", "quote": "",
                             "text": "this prompt has its spoken words in it (<d>…</d>), so the lines of the shot are not added "
                                     "again: they are what the speech check listens for. Keep the two the same."})
        elif said:
            body = _join(body) + " " + said + " " + (END_MANY if multi else END_ONE) + "."
        if blk and "<Video 1>" not in body:
            body = BLOCKOUT.format(shapes=": " + blk["shapes"].rstrip(".") if blk["shapes"] else "") + ". " + body
        sound = (shot.get("sound") or "").strip()
        text = body if ("overall_soundscape" in body or not sound) else f"{body}\n\noverall_soundscape:\n{_sentence(sound)}"
        user_text = body
    else:
        take_on = bible.get("one_take", True) if shot.get("one_take") is None else shot["one_take"]
        framing = presets.text("cameras", "framings", shot.get("framing") or "")
        move = presets.text("cameras", "moves", shot.get("camera") or "")
        cam = (shot.get("camera_text") or "").strip() or move
        action = shot.get("action") or ""
        for p in film.get("props") or []:
            if p.get("token"):
                action = action.replace(p["token"], f"Picture {_n(labels, 'prop', p['id'])}" if _n(labels, 'prop', p['id']) else (p.get("name") or ""))
        head = []
        if blk:
            head.append(BLOCKOUT.format(shapes=": " + blk["shapes"].rstrip(".") if blk["shapes"] else ""))
        if cont:
            head.append(CONT_BLOCKOUT if blk else CONT)
            stage = [f"{c['name']} {(shot.get('staging') or {}).get(c['id'], '').strip().rstrip('.')}"
                     for c in cast if (shot.get("staging") or {}).get(c["id"], "").strip()]
            if stage:
                head.append("; ".join(stage))
            if (shot.get("camera_text") or "").strip():
                head.append(shot["camera_text"])
        else:
            loc = _by_id(film.get("locations"), shot.get("location")) if shot.get("location") else None
            place = (shot.get("place") or "").strip() or (loc.get("description", "") if loc else "")
            bits = []
            if place:
                bits.append(place.rstrip("."))
            plate_n = _n(labels, "plate", loc["id"]) if loc else 0
            first = "[Shot 1] " + (bits[0] + ". " if bits else "")
            tail = []
            if plate_n:
                tail.append(f"The place looks exactly like Picture {plate_n}")
            if key.get("first"):
                tail.append("The shot opens exactly on Picture 1")
            if bible.get("notext"):
                tail.append(NOTEXT)
            head.append((first + _cap("; ".join(t if i == 0 else t[0].lower() + t[1:] for i, t in enumerate(tail)))).strip())
            for c in cast:
                head.append(person_clause(c, labels, (shot.get("staging") or {}).get(c["id"], "")))
            cam_bits = [b for b in (framing, cam) if b]
            if take_on:
                cam_bits.append(TAKE)
            if cam_bits:
                head.append(", ".join(b.rstrip(".") if i == 0 else (b[0].lower() + b[1:]).rstrip(".") for i, b in enumerate(cam_bits)))
        if multi and said:
            head.append(LOOK)
        tail = [action]
        if said:
            tail.append(said + " " + (END_MANY if multi else END_ONE))
        else:
            tail.append(silent_line)
        trig = "" if said else " ".join(triggers)          # H3 speaks trigger words in a part with dialogue
        body = (trig + " " if trig else "") + _join(*head) + "\n" + _join(*tail)
        sound = (shot.get("sound") or "").strip() or DEFAULT_SOUND
        text = f"{body}\n\noverall_soundscape:\n{_sentence(sound)}"
        user_text = " ".join([shot.get("place") or "", action, " ".join((shot.get("staging") or {}).values()),
                              shot.get("camera_text") or "", cam])

    prompt = (style_line(bible) + "\n" + text).strip()

    frames, why = part_frames(bible, shot, cont)
    if why:
        findings.append({"level": "note", "code": "length", "quote": "", "text": why})
    shots_ = film.get("shots") or []
    if 0 <= index < len(shots_) and shots_[index].get("id") == shot.get("id"):
        from . import blockouts
        bs = None if (shot.get("blockout") or "").strip() else blockouts.state(film, index)    # a video of its own wins
        if bs and bs["error"] and not bs["made"]:
            findings.append({"level": "warn", "code": "blockout-scene", "quote": "", "text": "the blockout of this scene: " + bs["error"]})
        elif bs and not bs["made"]:
            findings.append({"level": "warn", "code": "blockout-not-made", "quote": "",
                             "text": "the blockout of this scene is not made yet: make it in the Blockout step"})
        elif bs and (bs["error"] or not bs["current"]):
            findings.append({"level": "warn", "code": "blockout-old", "quote": "",
                             "text": "the blockout of this scene, or the length of one of its shots, changed after it was made: make it again in the Blockout step"})
        if bs and bs["made"] and blockouts.sides(bs.get("stats")):
            findings.append({"level": "note", "code": "blockout-sides", "quote": "",
                             "text": "in the blockout's picture: " + blockouts.sides(bs["stats"]) + ". Left and right in the "
                                     "words have to be the same, or the words win (seen 2026-11-14: a tram the words put on the "
                                     "left came out on the left although the blockout had it on the right)."})
        if bs and bs["made"] and bs.get("small"):
            findings.append({"level": "warn", "code": "blockout-small", "quote": "",
                             "text": "in the blockout, " + "; ".join(f"{n} {why}" for n, why in bs["small"]) +
                                     ". The render keeps the blockout's sizes only when they agree with the prompt; a subject the "
                                     "prompt wants big gets drawn big and the camera moves (seen 2026-11-14). Bring the camera "
                                     "closer, use a longer lens, or keep its keys level with the subject's."})
    pplan = blockout_plan(film, index - 1) if 0 < index <= len(film.get("shots") or []) else None   # what the shot before reads
    if blk and cont and not (blk.get("scene") or shot.get("blockout_start") or 0) and (pplan or {}).get("file") != blk["file"]:
        findings.append({"level": "warn", "code": "blockout-start", "quote": "",
                         "text": "this shot continues one that follows another blockout (or none): it reads this blockout "
                                 "from its start frame, so its first 39 frames (the part before's) and the blockout differ. "
                                 "Use the same blockout on the shot before, or set where in this one it starts."})
    if blk and shot.get("mode") != "free" and (shot.get("framing") or shot.get("camera")):
        findings.append({"level": "warn", "code": "blockout-camera", "quote": "",
                         "text": "this shot follows a blockout and also names a framing or camera move: the blockout sets those. "
                                 "Seen 2026-11-14: a prompt with a framing of its own (a close-up) won over the blockout. Clear Framing and Camera."})
    if blk and voices:
        findings.append({"level": "note", "code": "blockout-voices", "quote": "",
                         "text": "voices with a blockout are untested: the samples go in as the model's reference audio"})

    # the checks on what the user wrote (the stock sentences are the studio's)
    for ln in lines:
        nm = _speaker_name(film, ln.get("speaker"))
        if cast and nm not in [c["name"] for c in cast]:
            findings.append({"level": "warn", "code": "speaker-not-in-shot", "quote": nm,
                             "text": f"{nm} speaks but is not in this shot's cast: add them, or the line has no face"})
    findings += promptcheck.check(user_text if shot.get("mode") != "free" else prompt, new_shot=not cont, lines=lines,
                                  seconds=frames / lengths.FPS, has_people=has_people,
                                  talking_head=bool(shot.get("talking_head")))
    # composed prompts always carry the silence sentence; the check on the user's own words cannot see it
    if shot.get("mode") != "free":
        findings = [f for f in findings if f["code"] != "silence-not-said"]
    if cont and (shot.get("first_frame")):
        findings.append({"level": "note", "code": "first-frame-ignored", "quote": "",
                         "text": "a part that continues the one before opens on its frames: the first frame is not used"})

    return {"prompt": prompt, "refs": refs, "first_frame": key.get("first", ""), "last_frame": key.get("last", ""),
            "voices": voices, "pictures": labels, "audios": audios,
            "lines": [{"speaker": _speaker_name(film, ln.get("speaker")), "text": ln["text"].strip(), "how": ln.get("how", "")} for ln in lines],
            "loras": loras, "frames": frames, "continuation": cont, "asks_for_cut": "[Shot 2]" in prompt,
            "width": int(bible["width"]), "height": int(bible["height"]), "turbo": bool(bible.get("turbo", True)),
            "unet": bible.get("unet") or "", "language": bible.get("language") or "English", "blockout": blk,
            "findings": findings}


_SPOKEN = re.compile(r"(?i)<d>|\b(says?|said|speaks?|speaking|spoken|talks?|talking|words?|voices?|whisper\w*|lips)\b|\b(every|the) lines?\b")
_STAGED = re.compile(r"(?i)^(he|she|they|both)\s+(?!wears?\b|has\b|have\b|is wearing\b|are wearing\b|carr(?:y|ies)\b)")
_OVER_TIME = re.compile(r"(?i)\b(one continuous take|never cuts|without a cut|continue the same shot)\b")


def still_words(prompt):
    """What a prompt written for the video model shows, as words for one picture: without its sound section and its
    spoken lines, and without the clauses that are about speech or about going on without a cut."""
    text = re.split(r"(?im)^\s*overall_soundscape\s*:", prompt or "")[0]
    text = re.sub(r"<d>.*?</d>", "<d>.", text, flags=re.S).replace("{DIALOGUE}", "<d>.")
    text = re.sub(r"\[Shot \d+\]\s*", "", text)
    text = re.sub(r"(?i)\s+while (?:they|he|she|both) (?:talk|speak)s?\b", "", text)
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        if "<d>" in sent or re.match(r"(?i)\s*continue the same shot\b", sent):
            continue
        clauses = []
        for c in sent.split(";"):
            if _SPOKEN.search(c):
                continue
            c = ", ".join(x.strip() for x in c.split(",") if not _OVER_TIME.search(x)).strip()
            if c.strip(" .,:"):
                clauses.append(c)
        if clauses:
            out.append(_sentence("; ".join(clauses)))
    return " ".join(out)


def _setup(words, labels):
    """The sentences that set a scene: up to the last one that names the picture of the place or of a person.
    What comes after is what happens."""
    sents = re.split(r"(?<=[.!?])\s+", words)
    who = [lb["n"] for lb in labels if lb["kind"] != "prop"]
    last = max((i for i, x in enumerate(sents) if any(re.search(rf"\bPicture {n}\b", x) for n in who)), default=min(1, len(sents) - 1))
    out = []
    for x in sents[:last + 1]:
        # "...; he walks on the left": where someone was when the shot opened is not where they are later in it.
        # Seen 2026-11-12: with that clause in a continuation's still, the picture model drew the man twice.
        kept = [c.strip() for c in x.split(";") if not _STAGED.match(c.strip())]
        if kept:
            out.append(_sentence("; ".join(kept)))
    return " ".join(out)


def _own_words(film, shot, cont):
    """A shot's own prompt as words for a picture, with the pictures it counts: (words, labels)."""
    _, _, labels = pictures(film, shot, cont)
    text = shot.get("prompt") or ""
    for p in film.get("props") or []:
        if p.get("token") and p["token"] in text:
            n = _n(labels, "prop", p["id"])
            text = text.replace(p["token"], f"Picture {n}" if n else (p.get("name") or "it"))
    return still_words(text), labels


def _renumber(text, labels, files):
    """"Picture n" counted one way (labels) rewritten to the place of the same file in `files`."""
    by_n = {lb["n"]: lb["file"] for lb in labels}

    def sub(m):
        f = by_n.get(int(m.group(1)))
        return f"Picture {files.index(f) + 1}" if f in files else m.group(0)
    return re.sub(r"\bPicture (\d+)\b", sub, text)


def _opener(film, shot, index):
    """The shot that opened the take a continuation belongs to (the shot itself when it opens one)."""
    shots = film.get("shots") or []
    if not (0 < index < len(shots)) or shot.get("new_shot", True):
        return shot
    while index > 0 and not shots[index].get("new_shot", True):
        index -= 1
    return shots[index]


def still_prompt(film, shot, index=0):
    """A storyboard still of a shot for the picture model: the same people and place, one frozen moment.
    Returns (prompt, pictures in order).

    A shot with its own prompt ("My own prompt") is drawn from those words, without what cannot be seen in one
    picture (still_words), and with the pictures numbered as that prompt counts them. A continuation says nothing
    about its place and often nothing about how the people look, so its still also gets how its shot opened: the
    place and the people of the shot that began it, with that shot's pictures."""
    bible = {**blank_bible(), **(film.get("bible") or {})}
    film = {**film, "bible": bible}
    opener = _opener(film, shot, index)
    cont = opener is not shot
    parts = ["A single cinematic film still, one frozen moment of a film."]
    parts.append(style_line(bible).replace("The video is", "The picture is").replace("The video looks", "The picture looks"))
    if shot.get("mode") == "free" and (shot.get("prompt") or "").strip():
        words, labels = _own_words(film, shot, cont)
        lead, o_labels = "", []
        if cont and opener.get("mode") == "free":
            lead, o_labels = _own_words(film, opener, False)
            lead = _setup(lead, o_labels)
        # the pictures the words name, in the shot's own order; all of the shot's when the words name none by number
        named = lambda text, lbs: [lb["file"] for lb in lbs if re.search(rf"\bPicture {lb['n']}\b", text)]
        files = list(dict.fromkeys(named(words, labels) + named(lead, o_labels))) or [lb["file"] for lb in labels]
        words = _renumber(words, labels, files)
        if not cont:
            parts.append("What the shot shows, frozen at its first moment: " + words)
        else:
            if opener.get("mode") == "free":
                lead = _renumber(lead, o_labels, files)
            else:
                loc = _by_id(film.get("locations"), opener.get("location")) if opener.get("location") else None
                lead = (opener.get("place") or "").strip() or (loc.get("description", "") if loc else "")
            if lead:
                parts.append("The place and the people of this shot, each person in the picture only once: " + lead)
            parts.append("The moment shown: " + words)
        if bible.get("notext"):
            parts.append("Plain surfaces free of lettering")
        return _join(*parts), files[:9]
    if cont and not shot.get("location"):                  # a continuation is in the place its shot opened in
        shot = {**shot, "location": opener.get("location", ""), "place": shot.get("place") or opener.get("place", "")}
    _, refs, labels = pictures(film, {**shot, "first_frame": "", "last_frame": ""}, False)
    cast = [c for c in (_by_id(film.get("cast"), cid) for cid in shot.get("cast") or []) if c]
    loc = _by_id(film.get("locations"), shot.get("location")) if shot.get("location") else None
    place = (shot.get("place") or "").strip() or (loc.get("description", "") if loc else "")
    if place:
        parts.append(place)
    plate_n = _n(labels, "plate", loc["id"]) if loc else 0
    if plate_n:
        parts.append(f"The place looks exactly like Picture {plate_n}")
    for c in cast:
        parts.append(person_clause(c, labels, (shot.get("staging") or {}).get(c["id"], "")))
    framing = presets.text("cameras", "framings", shot.get("framing") or "")
    if framing:
        parts.append(framing)
    action = shot.get("action") or ""
    for p in film.get("props") or []:
        if p.get("token"):
            action = action.replace(p["token"], f"Picture {_n(labels, 'prop', p['id'])}" if _n(labels, 'prop', p['id']) else (p.get("name") or ""))
    first = re.split(r"(?<=[.!?])\s+", action.strip())[0] if action.strip() else ""
    if first:
        parts.append("The moment shown: " + first)
    if bible.get("notext"):
        parts.append("Plain surfaces free of lettering")
    return _join(*parts), refs[:9]
