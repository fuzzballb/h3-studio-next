"""The optional writing help: a language model that turns a logline into a shot list or rewrites a prompt.

Rendering never uses it, and nothing here is needed to make a film: without a brain the studio lays scenes out from
its coverage plans. Two kinds can be set in Settings:

  openai    any server that speaks the OpenAI chat API on this computer or network (Ollama, LM Studio, llama.cpp,
            vLLM): an address and a model name
  command   a program that reads the request on its standard input and writes the answer to its standard output,
            e.g. `ollama run llama3` or a command-line assistant you are signed in to. What you send it goes where
            that program sends it.

The brain only ever gets text (the logline, the names, the prompt); pictures and clips stay here.
"""
import asyncio
import json
import re

import aiohttp

from . import config, presets

SHOT_KEYS = ("title", "new_shot", "place", "cast", "staging", "framing", "camera", "action", "lines", "sound")
RULES = """You plan shots for a text-to-video model that renders about 10 seconds a part, with sound and speech.
Rules that come from real renders:
- One place and few actions per shot. A shot that carries on in the same place and framing has "new_shot": false; a new place, size or angle is "new_shot": true.
- Say what IS there, in positive words. The model has no negative prompt: naming a thing can make it appear.
- Name sides: who is on the left and who on the right of the picture.
- Every spoken word is a line with its exact words; at most about 22 words in a shot. A shot without lines has "lines": [].
- "how" says how a line is spoken (a mood and a volume), never loud unless the story needs a shout.
- "sound" describes what is heard besides the words.
- A busy place has other people in it; say that they stay in the background.
Answer with JSON only."""


def state():
    b = config.settings()["brain"]
    kind = b.get("kind") or "none"
    if kind == "openai" and not (b.get("endpoint") and b.get("model")):
        return {"kind": kind, "ok": False, "why": "set the server's address and a model name"}
    if kind == "command" and not b.get("command"):
        return {"kind": kind, "ok": False, "why": "set the command"}
    return {"kind": kind, "ok": kind != "none", "why": "" if kind != "none" else "no brain is set; the coverage plans work without one"}


async def ask(system, user):
    """One question to the brain; the answer as text."""
    b = config.settings()["brain"]
    st = state()
    if not st["ok"]:
        raise ValueError("the writing help is not set up: " + st["why"])
    timeout = float(b.get("timeout") or 180)
    if b["kind"] == "openai":
        url = b["endpoint"].rstrip("/") + "/chat/completions"
        body = {"model": b["model"], "temperature": 0.7,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
                async with s.post(url, json=body) as r:
                    text = await r.text()
                    if r.status != 200:
                        raise ValueError(f"the brain's server answered HTTP {r.status}: {text[:200]}")
                    return json.loads(text)["choices"][0]["message"]["content"]
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise ValueError(f"the brain's server at {b['endpoint']} does not answer ({type(e).__name__})") from e
    proc = await asyncio.create_subprocess_shell(b["command"], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate((system + "\n\n" + user).encode()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError(f"the brain's command gave no answer within {timeout:.0f} s")
    if proc.returncode != 0:
        raise ValueError("the brain's command failed: " + err.decode("utf-8", "replace").strip()[-200:])
    return out.decode("utf-8", "replace")


def parse_json(text):
    """The first JSON object in an answer (models wrap it in prose or code fences)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start = text.find("{")
        depth = 0
        for i in range(start, len(text)) if start >= 0 else []:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            if depth == 0:
                raw = text[start:i + 1]
                break
    if raw is None:
        raise ValueError("the brain did not answer with JSON")
    return json.loads(raw)


def clean_outline(data):
    """Keep only what the studio understands of a brain's outline; everything else is dropped."""
    framings = {f["id"] for f in presets.load("cameras")["framings"]}
    moves = {m["id"] for m in presets.load("cameras")["moves"]}
    cast = [{"name": str(c.get("name", "")).strip()[:40], "description": str(c.get("description", "")).strip()[:400],
             "pronoun": c.get("pronoun") if c.get("pronoun") in ("his", "her", "their") else "their"}
            for c in data.get("cast", []) if isinstance(c, dict) and str(c.get("name", "")).strip()]
    locs = [{"name": str(l.get("name", "")).strip()[:60], "description": str(l.get("description", "")).strip()[:600]}
            for l in data.get("locations", []) if isinstance(l, dict) and str(l.get("name", "")).strip()]
    shots = []
    for s in data.get("shots", []):
        if not isinstance(s, dict):
            continue
        lines = [{"speaker": str(l.get("speaker", "")).strip(), "text": str(l.get("text", "")).strip(), "how": str(l.get("how", "")).strip()}
                 for l in (s.get("lines") or []) if isinstance(l, dict) and str(l.get("text", "")).strip()]
        shots.append({"title": str(s.get("title", "")).strip()[:80], "scene": str(s.get("scene", "")).strip()[:80],
                      "new_shot": bool(s.get("new_shot", True)), "place": str(s.get("place", "")).strip(),
                      "location": str(s.get("location", "")).strip(), "cast": [str(x) for x in (s.get("cast") or [])],
                      "framing": s.get("framing") if s.get("framing") in framings else "",
                      "camera": s.get("camera") if s.get("camera") in moves else "",
                      "action": str(s.get("action", "")).strip(), "lines": lines, "sound": str(s.get("sound", "")).strip()})
    return {"cast": cast, "locations": locs, "shots": shots}


async def outline(logline, scenes=2, shots_per_scene=3, cast=(), seconds=10):
    """A logline to cast, places and shots, as clean_outline() returns them."""
    cams = presets.load("cameras")
    user = (f"Logline: {logline}\nScenes: {scenes}. Shots per scene: {shots_per_scene}. A shot lasts about {seconds} seconds.\n"
            + (f"The cast already exists: {', '.join(cast)}. Use these names.\n" if cast else "")
            + "JSON shape: {\"cast\": [{\"name\", \"description\" (age, face, hair, clothes), \"pronoun\": \"his\"|\"her\"|\"their\"}], "
              "\"locations\": [{\"name\", \"description\" (the empty place, seen from the camera)}], "
              "\"shots\": [{\"title\", \"scene\", \"new_shot\": true|false, \"location\": a location name, \"cast\": [names], "
              "\"framing\": one of " + json.dumps([f["id"] for f in cams["framings"]])
            + ", \"camera\": one of " + json.dumps([m["id"] for m in cams["moves"]])
            + ", \"action\": what happens, with names and sides, \"lines\": [{\"speaker\", \"text\", \"how\"}], \"sound\"}]}")
    return clean_outline(parse_json(await ask(RULES, user)))


def from_plan(plan_id, a="", b="", place=""):
    """Shots from a coverage plan, no brain needed. a and b are the names of the first and second person."""
    plan = presets.find("coverage", "plans", plan_id)
    if not plan:
        raise ValueError("no such coverage plan")
    fill = lambda t: (t or "").replace("{a}", a or "the first person").replace("{b}", b or "the second person").replace(
        "{place}", place or "the place")
    out = []
    for s in plan["shots"]:
        names = [n for n, key in ((a, "{a}"), (b, "{b}")) if n and key in s.get("action", "")]
        n_lines = int(s.get("lines") or 0)
        speakers = names or [a or ""]
        out.append({"title": s["title"], "new_shot": bool(s.get("new")), "framing": s.get("framing", ""), "camera": s.get("camera", ""),
                    "action": fill(s.get("action")), "cast_names": names, "frames": int(s.get("frames") or 0),
                    "lines": [{"speaker": speakers[k % len(speakers)], "text": "", "how": ""} for k in range(n_lines)]})
    return out
