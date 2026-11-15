"""Clip lengths and sizes MiniMax H3 can make.

H3 makes clips of 17n + 5 frames at 24 frames a second and nothing in between: 22, 39, ... 243, ... 362.
"10 s" is 243 frames, 10.125 s. Width and height must be multiples of 32 (other sizes get a garbage strip
at the bottom or right, e.g. rows 704-719 at 1280x720).

A part that continues the one before starts with 39 of its frames frozen, so it adds 39 frames less than
it renders: a 243-frame continuation adds 204 frames, 8.5 s.
"""
import math

FPS = 24
STEP, BASE = 17, 5
MIN_N, MAX_N = 1, 21
CONTEXT = 39                      # frames of the previous part a continuation keeps frozen
COUNTS = [STEP * n + BASE for n in range(MIN_N, MAX_N + 1)]
USUAL = (124, 192, 243, 362)      # "5 s", "8 s", "10 s", "15 s"

# name, width, height. All multiples of 32. The first is the default the timings below were measured at.
SIZES = [
    ("16:9  1152x640", 1152, 640),
    ("16:9  864x480 (draft)", 864, 480),
    ("16:9  448x256 (preview)", 448, 256),
    ("16:9  1280x704", 1280, 704),
    ("16:9  1344x768", 1344, 768),
    ("9:16  640x1152", 640, 1152),
    ("9:16  480x864 (draft)", 480, 864),
    ("9:16  256x448 (preview)", 256, 448),
    ("9:16  704x1280", 704, 1280),
    ("1:1   768x768", 768, 768),
    ("1:1   960x960", 960, 960),
    ("4:3   1152x864", 1152, 864),
    ("3:4   864x1152", 864, 1152),
    ("21:9  1344x576", 1344, 576),
]
IMAGE_SIZES = [
    ("16:9  1344x768", 1344, 768), ("16:9  1440x800 (video plate)", 1440, 800), ("1:1   1024x1024", 1024, 1024),
    ("9:16  768x1344", 768, 1344), ("4:3   1152x864", 1152, 864), ("3:4   864x1152", 864, 1152),
    ("21:9  1536x640", 1536, 640), ("3:2   1248x832", 1248, 832), ("2:3   832x1248", 832, 1248),
]


def is_count(frames):
    return isinstance(frames, int) and frames in COUNTS


def nearest(frames):
    """The frame count H3 takes that is closest to `frames` (ties go up)."""
    return min(COUNTS, key=lambda c: (abs(c - frames), -c))


def covering(frames):
    """The shortest count that is at least `frames` long (the longest count when nothing covers it)."""
    for c in COUNTS:
        if c >= frames:
            return c
    return COUNTS[-1]


def from_seconds(seconds):
    """Seconds to the nearest count: 6 s is 141 frames, 5.875 s."""
    return nearest(round(float(seconds) * FPS))


def seconds(frames):
    return frames / FPS


def neighbours(frames):
    """The two counts around a number that is not one, for an error message."""
    below = [c for c in COUNTS if c <= frames]
    above = [c for c in COUNTS if c >= frames]
    return (below[-1] if below else COUNTS[0], above[0] if above else COUNTS[-1])


def check_frames(frames):
    """Raise ValueError unless frames is a count H3 takes."""
    if not is_count(frames):
        lo, hi = neighbours(int(frames))
        raise ValueError(f"{frames} frames is not a length H3 makes (17n+5); the nearest are {lo} and {hi}")
    return frames


def new_frames(frames, continuation):
    """Frames a part adds to the film."""
    return frames - CONTEXT if continuation else frames


# H3's sound is 32 kHz on a 40 Hz grid (800 samples a tick), the picture 24 frames a second. The two only meet every
# 0.125 s, so the decoded sound of a part is up to one tick longer than its picture. The long-video nodes stretch it to
# fit and refuse a part where that is more than 0.5 %: measured on a 73-frame continuation (34 new frames, 45600
# samples for 45333, 0.59 %). Short parts are where one tick is a large share.
AUDIO_RATE, TICK, AUDIO_LIMIT = 32000, 800, 0.0045


def audio_mismatch(frames, continuation=False):
    """How far the decoded sound of a part is from its picture's length, as a fraction (the worse of the two ways the
    tick count can round)."""
    cut = round(CONTEXT / FPS * AUDIO_RATE) if continuation else 0
    want = round(new_frames(frames, continuation) / FPS * AUDIO_RATE)
    if want <= 0:
        return 1.0
    exact = frames * 40 / FPS
    return max(abs(t * TICK - cut - want) / want for t in {math.ceil(exact), round(exact)})


def fits(frames, continuation=False):
    """Can a part of this length be written? (A continuation also has to be longer than its frozen frames.)"""
    return is_count(frames) and new_frames(frames, continuation) > 0 and audio_mismatch(frames, continuation) <= AUDIO_LIMIT


def usable(continuation=False):
    """The frame counts a new shot, or a continuation, can use."""
    return [c for c in COUNTS if fits(c, continuation)]


def check_fit(frames, continuation=False):
    check_frames(frames)
    if not fits(frames, continuation):
        ok = usable(continuation)
        near = min(ok, key=lambda c: abs(c - frames))
        what = "a part that continues the one before" if continuation else "a part"
        raise ValueError(f"{frames} frames is too short for {what}: its sound does not fit the picture's length "
                         f"(H3's sound runs on a 40 Hz grid). The nearest length that works is {near} frames "
                         f"({near / FPS:.2f} s).")
    return frames


def snap32(value):
    """A size to the nearest multiple of 32, at least 32."""
    return max(32, int(round(float(value) / 32.0)) * 32)


def preview_size(width, height, short=256):
    """A very small size with the same shape: the short side at `short` (256 is the smallest size H3 takes here)."""
    if width >= height:
        return snap32(width * short / height), short
    return short, snap32(height * short / width)


def check_size(width, height):
    if width % 32 or height % 32:
        raise ValueError(f"{width}x{height}: width and height must be multiples of 32 "
                         f"(nearest: {snap32(width)}x{snap32(height)})")
    if not (256 <= width <= 2560 and 256 <= height <= 2560):
        raise ValueError(f"{width}x{height}: sizes from 256 to 2560 are supported")
    return width, height


def table():
    """Every count with its seconds, for the UI."""
    return [{"frames": c, "seconds": round(c / FPS, 3), "usual": c in USUAL,
             "continuation_seconds": round((c - CONTEXT) / FPS, 3) if c > CONTEXT else 0,
             "new_shot": fits(c, False), "continuation": fits(c, True)} for c in COUNTS]
