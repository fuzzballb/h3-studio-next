"""Checks on a prompt before it costs a render.

Nothing here rewrites a prompt. Each finding says what was written, what it did in real runs and what worked instead.
Two kinds:

  warn   patterns that made H3 cut, mumble, shout or draw the wrong thing in our own stories (the same rules as
         story_kit/run_story.py lint, plus the ones learned in gate mode)
  note   things to look at: words that forbid (H3 has no negative prompt, so a named thing can appear), timing of
         the spoken lines, continuation wording

`check(text, ...)` takes the prompt as the user wrote it; the studio's own stock sentences are passed over.
"""
import re

# sentences the studio writes itself; they were tested on this stack and are not reported as "words that forbid"
STOCK = (
    "nobody speaks, there are no words at all",
    "those are the only words; after that nobody says anything else",
    "after that nobody says anything else",
    "one continuous take, it never cuts and there are no close-ups",
    "nobody looks into the camera",
    "no readable text, letters, signs or logos anywhere",
    "continue the same shot without a cut",
    "they make no words",
    "not shouting",
    "not loud at all",
    "without any rasp or hoarseness",
    "whoever is not speaking listens with a closed mouth",
)

NEG = r"\b(?:does not|doesn't|do not|don't|never|no|nobody|without|not)\b(?:\s+\w+){1,3}"
FORBID = re.compile(r"\b(no|without|never|not|nobody|none of the|free of)\s+((?:[a-z'-]+\s?){1,4})", re.I)
# the thing that is forbidden ends where the sentence goes on: "No dogs | are in the yard"
FORBID_END = re.compile(r"\s+(?:is|are|was|were|be|appears?|can|will|shall|may|in|on|at|to|from|with|by|anywhere|here|there|that|which|who|"
                        r"when|while|during|inside|outside|near|behind|above|under)\b.*$", re.I)
# "no" followed by these is grammar, not a thing to draw
FORBID_SKIP = re.compile(r"^(?:longer|more|one|matter|doubt|way|idea|sound|sounds|words|speech|dialogue|music|cut|cuts|"
                         r"close-ups?|shouting|loud|moving|move|moves|speaking|talking|looking|reason)\b", re.I)
SPEECH_RATE = 2.6           # words a second in natural dialogue; H3 fits about this much
LEAD_IN = 0.8               # seconds before the first word
TALK = (r"\b(?:says|said|speaks|talks|counts?(?: down)?|shouts?|calls? out|whispers?|announces?|yells?|asks?|answers?|"
        r"tells?|mouths|sings?|chants?|narrates?)\b")
TRIGGERS = r"(^|[ ,.])(DY|camera motion,|bullet-time)([ ,.]|$)"


def _finding(level, code, text, quote=""):
    return {"level": level, "code": code, "text": text, "quote": quote}


def strip_stock(text):
    low = text
    for s in STOCK:
        low = re.sub(re.escape(s), " ", low, flags=re.I)
    return low


def forbids(text):
    """Things a prompt forbids by name: [(phrase, thing)]. H3 runs without a negative prompt."""
    out, seen = [], set()
    body = strip_stock(re.sub(r"<d>.*?</d>", " ", text, flags=re.S))      # spoken lines are speech, not description
    for m in FORBID.finditer(body):
        thing = FORBID_END.sub("", m.group(2).strip().rstrip(".,;:")).strip()
        if not thing or FORBID_SKIP.match(thing) or FORBID_END.match(" " + thing):
            continue
        phrase = (m.group(1) + " " + thing).strip()
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            out.append((phrase, thing))
    return out


def spoken_words(lines):
    return sum(len(re.findall(r"[\w']+", ln.get("text", "") if isinstance(ln, dict) else ln[1])) for ln in lines or [])


def check(text, new_shot=True, lines=None, seconds=10.0, has_people=True, loras=None, talking_head=False):
    """Findings for one prompt. `lines` = [{"speaker", "text", "how"}] or [(speaker, text[, how])]."""
    lines = lines or []
    has_dialogue = bool(lines)
    t = text.lower()
    desc = re.sub(r"<d>.*?</d>", " ", t, flags=re.S)                     # what is described, without the spoken words
    desc = re.sub(r'"[^"]*"', " ", desc) if has_dialogue else desc
    pos = re.sub(NEG, " ", desc)                                           # negated phrases dropped
    out = []

    static = re.search(r"static|locked-off|locked off|camera (?:does not|doesn't|never) move|camera stays|still camera", desc)
    moving = re.search(r"camera (?:glides|pans|tracks|follows|dollies|moves|zooms|pulls back|pushes in|orbits|circles|swings|"
                       r"rises|cranes|flies)|tracking shot|\bdolly\b|\bcrash zoom\b|\bwhip pan\b", pos)
    if static and moving:
        out.append(_finding("warn", "camera-contradiction",
                            f'"{static.group(0)}" and "{moving.group(0)}" in the same prompt: contradicting camera '
                            "instructions invite cuts. Keep one.", moving.group(0)))

    turns = re.findall(r"\b(?:turns?|spins?|pivots?|twirls?)\b", pos)
    if len(turns) > 1:
        out.append(_finding("warn", "turns",
                            f"{len(turns)} turns in one part: turning back and forth looks unnatural and makes H3 redraw the "
                            "background. Use one turn, and show the back while walking away.", turns[0]))

    thens = len(re.findall(r"\bthen\b", pos))
    if not new_shot and thens >= 2:
        out.append(_finding("warn", "many-actions",
                            f'{thens + 1} actions in a row ("then" x{thens}) in a continuation: fewer actions per part '
                            "means fewer cuts."))

    m = re.search(r"\b(?:wink\w*|blows? a kiss|raises? an eyebrow|sticks? out (?:his|her|their) tongue|licks?)\b", pos)
    if m:
        out.append(_finding("warn", "small-face-action",
                            f'small facial action "{m.group(0)}": H3 tends to cut to a face close-up for it.', m.group(0)))

    talk = re.search(TALK + r'|"[^"]+"', pos)
    if not has_dialogue and talk:
        out.append(_finding("warn", "talk-without-lines",
                            f'"{talk.group(0)}" without spoken lines: H3 speaks it and invents garbled words. Write the '
                            "exact words as a line, or drop it.", talk.group(0)))
    if not has_dialogue and not re.search(r"nobody speaks|no words|no dialogue|nobody says|mouths stay closed|only ambient", t):
        out.append(_finding("warn", "silence-not-said",
                            'no spoken lines and no "Nobody speaks, there are no words at all": H3 fills silence with '
                            "mumbling. The studio adds the sentence when it composes a shot."))

    if has_dialogue and re.search(TRIGGERS, text):
        out.append(_finding("warn", "lora-trigger-spoken",
                            'a LoRA trigger word ("DY", "camera motion,", "bullet-time") in a part with dialogue: H3 may '
                            "speak it. Drop the word and keep the LoRA."))

    if has_dialogue and not talking_head and re.search(r"fac(?:es|ing) the camera|looks? (?:straight )?into the (?:camera|lens)", pos):
        out.append(_finding("warn", "facing-camera",
                            '"facing the camera" in a dialogue: they talk into the lens instead of to each other. Use '
                            '"his face in three-quarter view and clearly visible to the camera".'))

    if re.search(r"\b(?:swerv\w+|yanks? the wheel)\b|streak\w* (?:over|across) the windshield", pos):
        out.append(_finding("warn", "windshield",
                            "a swerve or light streaking over the windshield drew neon signs and labels sliding across "
                            'the glass. Use "the windshield glass is clean and clear", and accelerate instead of swerving.'))

    m = re.search(r"\b(?:run|runs|running|flee|flees|fleeing)\s+away from\b", pos)
    if m:
        out.append(_finding("warn", "run-away",
                            '"run away from ...": H3 showed people walking toward the thing. Say where everyone is '
                            "instead (the alley is empty, the customers duck behind the counter)."))

    m = re.search(r"\b(?:shouts?|yells?|screams?|loudly|at the top of (?:his|her|their) voice)\b", pos)
    if m:
        out.append(_finding("note", "loud-cue",
                            f'"{m.group(0)}": shouted lines came out at -15 to -19 LUFS next to normal speech at -23 to -26. '
                            'For urgency without the jump: "urgent but at a normal speaking volume".', m.group(0)))

    for ln in lines:
        txt = ln.get("text", "") if isinstance(ln, dict) else ln[1]
        how = (ln.get("how", "") if isinstance(ln, dict) else (ln[2] if len(ln) > 2 else "")) or ""
        if txt.strip().endswith("!") and re.search(r"laugh|relief|excited|delight", how, re.I):
            out.append(_finding("note", "exclamation",
                                f'"{txt}" with "{how}": an exclamation mark plus laughing came out shouted. A full stop and '
                                '"quietly ... not loud at all" kept it at speaking level.', txt))

    if not new_shot:
        m = re.search(r"\b(?:towards?|back at|in the distance|far behind|around the corner|off-screen|out of frame)\b[^.,;]*", pos)
        if m:
            out.append(_finding("note", "continuation-offscreen",
                                f'"{m.group(0).strip()}": a continuation must only name what is in view at the END of the '
                                "part before it. Something off-screen makes H3 cut to it, or swap the background at the join.",
                                m.group(0).strip()))

    if re.search(r"\bgets? in(?:to)?\b[^.]*\bcar\b|\bcar\b[^.]*\bgets? in\b", pos) and not re.search(
            r"passenger door|driver'?s door|front door|walks around", pos):
        out.append(_finding("note", "car-doors",
                            "people get into a car: say which door each one uses (\"walks around the front of the car to the "
                            "passenger door on the far side\"), or both get in on the same side."))

    if has_dialogue:
        words = spoken_words(lines)
        room = max(0.5, float(seconds) - LEAD_IN - (lengths_context_seconds() if not new_shot else 0.0))
        need = words / SPEECH_RATE
        if need > room:
            out.append(_finding("warn", "too-many-words",
                                f"{words} spoken words need about {need:.1f} s; this part has {room:.1f} s of new picture. "
                                "Shorten the lines or split the part."))
        elif words and need < room * 0.3 and len(lines) == 1:
            out.append(_finding("note", "one-short-line",
                                f"one short line ({words} words) in {room:.1f} s: H3 fills the rest with chatter. The studio "
                                'ends the lines with "after that nobody says anything else"; also say what happens after it.'))

    for phrase, thing in forbids(text):
        out.append(_finding("note", "forbids",
                            f'"{phrase}": H3 runs without a negative prompt, so naming {thing} can make it appear. '
                            "Say what is there instead.", phrase))
    return out


def lengths_context_seconds():
    from . import lengths
    return lengths.CONTEXT / lengths.FPS


def summary(findings):
    w = sum(1 for f in findings if f["level"] == "warn")
    n = len(findings) - w
    if not findings:
        return "no findings"
    return ", ".join(x for x in (f"{w} warning(s)" if w else "", f"{n} note(s)" if n else "") if x)
