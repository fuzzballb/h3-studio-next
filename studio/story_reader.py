"""Read a story-kit file for the studio.

A story file is a Python program (see docs/long-video.md, "Make your own story video"): reading it means running it,
the same as story_kit/run_story.py does. So it is run here, in a process of its own, and what the studio needs is
printed as one line of JSON: the sizes, the pictures, the voices, and for every video part its prompt, lines and
pictures, with the exact prompt the story kit sends for it (from the kit's own build()).

    python -m studio.story_reader /path/to/story.py        prints: STORY {...}
"""
import contextlib
import importlib.util
import json
import os
import runpy
import sys

KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "story_kit", "run_story.py")


def _kit():
    spec = importlib.util.spec_from_file_location("run_story", KIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path):
    st = runpy.run_path(path)
    parts_in = st.get("PARTS")
    if not isinstance(parts_in, dict) or not parts_in:
        raise ValueError("this file defines no PARTS: it is not a story of the story kit")
    try:
        kit = _kit()
    except Exception:                          # the prompts are still worth having without the kit's own wording
        kit = None
    order = list(st.get("STORY") or sorted(parts_in))        # video part n = story part order[n - 1]
    props = [[tok, img] for tok, img in (st.get("PROPS") or {}).items()]
    parts = []
    for video_part, s in enumerate(order, 1):
        entry = parts_in[s]
        new, loc, loras, prompt = entry[:4]
        lines = entry[4] if len(entry) > 4 and entry[4] else []
        new = bool(new or video_part == 1)
        sent = ""
        if kit:
            try:
                sent = kit.build(st, "story", s, video_part, seed=1)["22"]["inputs"]["value"]
            except (SystemExit, Exception):    # e.g. the tts mode wants its timing file first
                sent = ""
        # the pictures in the order the kit numbers them: face, body, the place, then each prop the prompt names
        pictures = [st.get("FACE", "") if new else st.get("FACE_CONT", st.get("FACE", "")), st.get("BODY", "")]
        if loc:
            pictures.append(loc)
        pictures += [img for tok, img in props if tok in prompt]
        parts.append({"part": video_part, "story_part": s, "new": new, "loc": loc or "", "prompt": prompt, "sent": sent,
                      "loras": [[n, float(w)] for n, w in (loras or [])], "pictures": pictures,
                      "lines": [[str(ln[0]), str(ln[1]), str(ln[2]) if len(ln) > 2 and ln[2] else ""] for ln in lines]})
    return {"width": st.get("WIDTH"), "height": st.get("HEIGHT"), "seconds": st.get("SECONDS"), "turbo": bool(st.get("TURBO", True)),
            "unet": st.get("UNET") or "", "face": st.get("FACE") or "", "body": st.get("BODY") or "",
            "face_cont": st.get("FACE_CONT") or "", "props": props, "dialogue_mode": st.get("DIALOGUE_MODE", "h3"),
            "voices": [[name, (v[0] or "") if v else "", (v[1] if v and len(v) > 1 else "their")] for name, v in (st.get("VOICES") or {}).items()],
            "parts": parts}


if __name__ == "__main__":
    out = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):       # whatever the story prints is not the answer
            story = read(sys.argv[1])
    except Exception as e:
        sys.exit(f"{type(e).__name__}: {e}")
    out.write("STORY " + json.dumps(story) + "\n")
