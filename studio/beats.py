"""Find the beats of a song on this machine, with numpy and ffmpeg and nothing else.

    beats(path) -> {"bpm", "beats": [seconds], "downbeats": [seconds], "bars", "duration", "confidence"}

How: the song is decoded to mono, its onset strength is the rise in spectral energy from one frame to the next, the
tempo is the lag (60 to 200 beats a minute) at which that curve repeats most, and the beats are the path through the
onsets that keeps that spacing (dynamic programming, after Ellis 2007). The first beat of each bar is the phase of
four that carries the most energy (4/4 is assumed). Very fast songs may read at half tempo, which still cuts on the beat.
A result is kept beside the song as <name>.beats.json.
"""
import os
import subprocess

import numpy as np

from . import config

RATE, HOP, WIN = 22050, 512, 2048


def decode(path, rate=RATE):
    """A song as mono float32 samples."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise ValueError("the sound of this file cannot be read")
    return np.frombuffer(r.stdout, dtype="<f4")


def onset_strength(y):
    """Spectral flux: how much the spectrum grows from frame to frame, one value per hop."""
    n = 1 + max(0, (len(y) - WIN) // HOP)
    if n < 8:
        raise ValueError("the sound is too short to find beats in")
    win = np.hanning(WIN).astype(np.float32)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * win, axis=1))
    logm = np.log1p(mag * 100.0)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(17) / 17.0, mode="same")          # a local average out: keep the peaks
    flux = np.maximum(flux, 0.0)
    return flux / (flux.std() + 1e-9)


def tempo(env, lo=60.0, hi=200.0):
    """(beats a minute, confidence 0-1) from the onset curve's autocorrelation, with a mild preference for ~120."""
    fps = RATE / HOP
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lags = np.arange(int(fps * 60 / hi), min(int(fps * 60 / lo) + 1, len(ac) - 1))
    if len(lags) == 0:
        raise ValueError("the sound is too short to find a tempo in")
    bpm = 60.0 * fps / lags
    weight = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = ac[lags] * weight
    best = int(np.argmax(score))
    lag = float(lags[best])
    if 0 < best < len(lags) - 1:                                        # a parabola through the peak for a finer lag
        a, b, c = score[best - 1], score[best], score[best + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-12:
            lag += 0.5 * (a - c) / den
    conf = float(np.clip(ac[lags[best]] / (np.sort(ac[lags])[len(lags) // 2] + 1e-9) / 8.0, 0.0, 1.0)) if len(lags) > 2 else 0.5
    return 60.0 * fps / lag, conf


def track(env, bpm, tightness=100.0):
    """Beat frames: the sequence of onsets that best keeps the tempo's spacing."""
    period = (RATE / HOP) * 60.0 / bpm
    n = len(env)
    score = env.copy()
    back = -np.ones(n, dtype=np.int64)
    lo, hi = int(round(period * 0.5)), int(round(period * 2.0))
    offsets = np.arange(-hi, -lo + 1)
    penalty = -tightness * (np.log(-offsets / period)) ** 2
    for i in range(n):
        j = i + offsets
        ok = j >= 0
        if not ok.any():
            continue
        cand = score[j[ok]] + penalty[ok]
        k = int(np.argmax(cand))
        if cand[k] > 0:
            score[i] = env[i] + cand[k]
            back[i] = j[ok][k]
    tail = max(0, n - int(period * 2))
    i = tail + int(np.argmax(score[tail:]))
    out = []
    while i >= 0:
        out.append(i)
        i = back[i]
    return np.array(out[::-1])


def analyse(path):
    y = decode(path)
    env = onset_strength(y)
    bpm, conf = tempo(env)
    frames = track(env, bpm)
    times = (frames * HOP + WIN / 2 + HOP) / RATE          # the rise is seen one hop before the middle of its frame
    if len(times) >= 4:
        bpm = 60.0 / float(np.polyfit(np.arange(len(times)), times, 1)[0])     # one line through every beat
    strength = env[np.clip(frames, 0, len(env) - 1)]
    phase = int(np.argmax([strength[p::4].mean() if len(strength[p::4]) else 0 for p in range(4)])) if len(frames) >= 8 else 0
    down = times[phase::4]
    return {"bpm": round(float(bpm), 2), "beats": [round(float(t), 3) for t in times],
            "downbeats": [round(float(t), 3) for t in down], "bars": int(len(down)),
            "duration": round(len(y) / RATE, 3), "confidence": round(conf, 2)}


def beats(path, refresh=False):
    """The beats of a song; measured once and kept as <name>.beats.json beside it (or in the studio folder when the
    song's folder cannot be written)."""
    side = path + ".beats.json"
    alt = config.home("audio", os.path.basename(path) + ".beats.json")
    if not refresh:
        for p in (side, alt):
            got = config.read_json(p)
            if got and got.get("mtime") == os.path.getmtime(path):
                return got
    out = analyse(path)
    out["mtime"] = os.path.getmtime(path)
    try:
        config.write_json(side, out)
    except OSError:
        config.write_json(alt, out)
    return out


def slots(beat_times, lengths, mode="own", start=0.0):
    """Lay clips on the beat. `lengths` are the clips' own lengths in seconds.

    mode  own      each clip about its own length, cut on the nearest beat
          bar      one bar (four beats) each       two_bars   two bars each       beat   one beat each
    Returns [(start, end)] on the song's timeline. A clip shorter than its slot keeps its whole length and the next
    cut lands back on the grid.
    """
    b = [t for t in beat_times if t >= start - 1e-6]
    if len(b) < 2:
        raise ValueError("no beats to cut on")
    out, i = [], 0
    step = {"beat": 1, "bar": 4, "two_bars": 8}.get(mode)
    for length in lengths:
        if i >= len(b) - 1:
            break
        if step:
            j = min(i + step, len(b) - 1)
        else:
            target = b[i] + length
            j = min(range(i + 1, len(b)), key=lambda k: abs(b[k] - target))
        out.append((b[i], b[j]))
        i = j
    return out
