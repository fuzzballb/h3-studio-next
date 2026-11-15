"""Small synthetic clips, pictures and sounds for the tests, made with ffmpeg."""
import os
import subprocess
import wave

import numpy as np


def run(*args):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])


def clip(path, seconds=2.0, color="blue", size="320x192", fps=24, tone=440, volume=0.05, cut_at=None, second_color="red", audio=True):
    """A clip of one flat colour with a moving box (so frames differ a little), optionally cutting to another colour."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    base = f"color=c={color}:s={size}:r={fps}:d={seconds},drawbox=x='mod(t*40,200)':y=40:w=30:h=30:color=white@0.8:t=fill"
    if cut_at:
        base = (f"color=c={color}:s={size}:r={fps}:d={cut_at}[a];color=c={second_color}:s={size}:r={fps}:d={seconds - cut_at}[b];"
                f"[a][b]concat=n=2:v=1:a=0")
    args = ["-f", "lavfi", "-i", base]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={seconds}", "-af", f"volume={volume}"]
    codec = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"] + (["-c:a", "flac" if path.endswith(".mkv") else "aac"] if audio else [])
    run(*args, *codec, "-t", str(seconds), path)
    return path


def picture(path, color="green", size="320x192"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    run("-f", "lavfi", "-i", f"color=c={color}:s={size}", "-frames:v", "1", path)
    return path


def click_track(path, bpm=120, seconds=16, rate=22050):
    y = np.zeros(int(seconds * rate), dtype=np.float32)
    t, k = 0.35, 0
    while t < seconds - 0.1:
        n, length = int(t * rate), int(0.03 * rate)
        env = np.exp(-np.arange(length) / (0.006 * rate))
        strong = k % 4 == 0
        y[n:n + length] += (1.0 if strong else 0.6) * env * np.sin(2 * np.pi * (1800 if strong else 900) * np.arange(length) / rate)
        t += 60.0 / bpm
        k += 1
    y += 0.01 * np.random.RandomState(1).randn(len(y)).astype(np.float32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return path
