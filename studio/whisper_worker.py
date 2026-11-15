"""Transcribe one media file with openai-whisper and print the result as JSON.

    python -m studio.whisper_worker <file> [--model small] [--lang en] [--dir <folder with the model files>]

Run as a process of its own (checks.transcribe does) so the studio's server never loads torch, and with
CUDA_VISIBLE_DEVICES empty so the GPU stays with the render.
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--model", default="small")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--dir", default=None)
    a = ap.parse_args()
    import torch
    import whisper
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(a.model, download_root=a.dir, device=device)
    r = model.transcribe(a.file, language=a.lang or None, word_timestamps=True, fp16=device == "cuda",
                         condition_on_previous_text=False)
    out = {"text": r.get("text", ""), "language": r.get("language"), "model": a.model, "segments": [
        {"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"],
         "no_speech_prob": round(float(s.get("no_speech_prob", 0.0)), 4),
         "words": [{"start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3), "word": w["word"]}
                   for w in s.get("words", [])]}
        for s in r.get("segments", [])]}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
