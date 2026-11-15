"""The Agent: a chat that plans and makes things with the studio's own tools.

Every turn runs Claude Code with no tools of its own (writer.run_claude): it reads the conversation and a short list
of what is in the Library, and answers with what it says and the actions it wants: make pictures, edit or animate one,
make a clip, start a film with the Writer. Only text goes to Claude; pictures and clips stay on this computer.

Nothing renders until the person allows it, unless they switched "Ask before making" off for the chat. An allowed
action becomes a normal job in the studio's queue; the server (server.agent_run) turns it into one. The chat keeps
each action's job id, and a read of the chat says how far each job got and what it made.

Chats live in agent/<id>.json.
"""
import os
import threading
import time
import uuid

from . import config, films, lengths, library, writer

_lock = threading.RLock()
TOOLS = ("make_picture", "edit_picture", "animate_picture", "make_clip", "start_film")
SHAPES = ("landscape", "portrait", "square", "vertical")
_STR = {"type": "string"}
_LINE = {"type": "object", "additionalProperties": False, "required": ["speaker", "text"], "properties": {"speaker": _STR, "text": _STR}}
_ACTION_PROPS = {
    "tool": {"type": "string", "enum": list(TOOLS)}, "why": _STR, "prompt": _STR, "asset": _STR,
    "shape": {"type": "string", "enum": list(SHAPES)}, "count": {"type": "integer"}, "seconds": {"type": "number"},
    "sound": _STR, "lines": {"type": "array", "items": _LINE}, "story": _STR}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["say", "actions"], "properties": {
    "say": _STR,
    "actions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": list(_ACTION_PROPS),
                                           "properties": _ACTION_PROPS}}}}

SYSTEM = """You are the agent of H3 Studio, a film studio that runs on the user's own computer with ComfyUI. You plan
and make things with the studio's tools. Answer every turn with the JSON object only: "say" (what you tell the user,
short and plain, no Markdown headings) and "actions" (what you want made; [] when you only talk or ask).

The tools (every field of an action must be there; use "" or 0 or [] for the ones a tool does not use):
- make_picture: a still with Qwen-Image. "prompt" describes the picture (who or what, where, light, lens). "shape"
  landscape, portrait, square or vertical. "count" 1 to 4 takes. About 20 to 30 seconds a picture.
- edit_picture: change a picture from the Library. "asset" is its id from the list below; "prompt" says what the
  result looks like (what is not mentioned stays).
- animate_picture: a clip that starts on a Library picture ("asset"). "prompt" says what happens and how the camera
  moves. "seconds" 5, 8, 10 or 15. "sound" what is heard. "lines" every spoken word, exact, with the speaker.
- make_clip: a clip from words with MiniMax H3 (picture and sound together). "prompt" is the place and what happens,
  "shape" landscape or vertical, "seconds", "sound", "lines" as above. About 3 to 10 minutes a clip on this machine.
- start_film: a whole short film. "story" is a small story in a few sentences; the studio's Writer turns it into
  cast, places and shots, and the user goes on in the Writer. Use it when the user wants a film of several shots.

Rules that come from renders that went wrong:
- Every word a person says goes in "lines" as exact words; never describe speech in the prompt.
- One clip is one place and few actions. Name sides (left/right of the picture) when there are two people.
- Do not ask for text, logos or lettering in a picture or clip.
- Do not recreate real people, brands, logos or scenes from existing films, shows or games.
- Make what the user asked for; do not add extra actions. Ask one short question first when the request is unclear.
- When the user says something was wrong with a result, say what you change and make it again.

Results of earlier actions are in the conversation, with the ids of what they made, so you can edit or animate them."""


def _dir():
    d = config.home("agent")
    os.makedirs(d, exist_ok=True)
    return d


def _path(cid):
    if not cid or not all(c.isalnum() for c in cid):
        raise KeyError("chat")
    return os.path.join(_dir(), cid + ".json")


def load(cid):
    c = config.read_json(_path(cid))
    if not c:
        raise KeyError("chat")
    return c


def save(c):
    c["updated"] = time.time()
    with _lock:
        config.write_json(_path(c["id"]), c)
    return c


def new_chat():
    return save({"id": "ag" + uuid.uuid4().hex[:10], "title": "", "created": time.time(), "ask_first": True, "turns": []})


def all_chats():
    out = []
    for name in os.listdir(_dir()):
        if name.endswith(".json"):
            c = config.read_json(os.path.join(_dir(), name))
            if c:
                out.append({"id": c["id"], "title": c.get("title") or "New chat", "updated": c.get("updated", 0)})
    out.sort(key=lambda c: c["updated"], reverse=True)
    return out


def delete(cid):
    p = _path(cid)
    if not os.path.isfile(p):
        raise KeyError("chat")
    os.unlink(p)


# ------------------------------------------------------------------ what Claude reads
def library_words(limit=30):
    rows = []
    for a in library.search(kind="image,sheet,clip,film", limit=limit):
        what = (a.get("prompt") or "").replace("\n", " ")[:140]
        rows.append(f"- {a['id']} · {a['kind']} · {a.get('name', '')[:60]}" + (f" · {what}" if what else ""))
    return "\n".join(rows) or "(empty)"


def transcript(c):
    out = ["What is in the Library, newest first (id · kind · name · prompt):", library_words(), ""]
    names = [f"- {f['name']} ({f.get('shots', 0)} shots)" for f in films.summaries()[:12]]
    if names:
        out += ["The user's films:", *names, ""]
    out.append("The conversation so far:")
    for t in c["turns"]:
        if t["role"] == "user":
            out.append("USER: " + t["text"])
        else:
            out.append("AGENT: " + t.get("say", ""))
            for a in t.get("actions", []):
                res = a.get("status", "")
                if a.get("made"):
                    res += " · made " + ", ".join(a["made"])
                if a.get("error"):
                    res += " · " + a["error"]
                out.append(f"  [{a['tool']}] {a.get('prompt') or a.get('story') or ''}"[:300] + f" -> {res}")
    return "\n".join(out)


def clean_action(a):
    if not isinstance(a, dict) or a.get("tool") not in TOOLS:
        return None
    out = {"id": uuid.uuid4().hex[:8], "tool": a["tool"], "why": str(a.get("why") or "")[:300],
           "prompt": str(a.get("prompt") or "")[:3000], "asset": str(a.get("asset") or "")[:40],
           "shape": a.get("shape") if a.get("shape") in SHAPES else "landscape",
           "count": max(1, min(int(a.get("count") or 1), 4)), "seconds": float(a.get("seconds") or 0),
           "sound": str(a.get("sound") or "")[:600], "story": str(a.get("story") or "")[:4000],
           "lines": [{"speaker": str(x.get("speaker") or "")[:40], "text": str(x.get("text") or "")[:400]}
                     for x in (a.get("lines") or []) if isinstance(x, dict) and (x.get("text") or "").strip()][:12],
           "status": "proposed"}
    if out["tool"] in ("edit_picture", "animate_picture") and not library.get(out["asset"]):
        out["status"] = "failed"
        out["error"] = "no such picture in the Library"
    if out["tool"] == "start_film" and not out["story"]:
        out["story"] = out["prompt"]
    return out


def video_size(shape):
    want = {"landscape": (1152, 640), "vertical": (640, 1152), "portrait": (640, 1152), "square": (768, 768)}[shape]
    return want


def picture_size(shape):
    return {"landscape": (1344, 768), "portrait": (864, 1152), "square": (1024, 1024), "vertical": (768, 1344)}[shape]


def frames_for(seconds):
    return lengths.nearest(int(round((seconds or 8.5) * 24)))


async def turn(cid, text):
    c = load(cid)
    if not text.strip():
        raise ValueError("write something first")
    c["turns"].append({"role": "user", "text": text.strip(), "time": time.time()})
    if not c.get("title"):
        c["title"] = text.strip().split("\n")[0][:70]
    save(c)
    try:
        answer, meta = await writer.run_claude(SYSTEM, SCHEMA, transcript(c), timeout=600)
    except Exception:
        c = load(cid)
        c["turns"].pop()
        save(c)
        raise
    answer = answer if isinstance(answer, dict) else {"say": meta.get("text") or "", "actions": []}
    actions = [x for x in (clean_action(a) for a in (answer.get("actions") or [])[:6]) if x]
    c = load(cid)
    c["turns"].append({"role": "agent", "say": str(answer.get("say") or ""), "actions": actions, "time": time.time(),
                       "meta": {k: meta.get(k) for k in ("seconds", "model")}})
    return save(c)


def find_action(c, aid):
    for t in c["turns"]:
        for a in t.get("actions", []):
            if a["id"] == aid:
                return a
    raise KeyError("action")
