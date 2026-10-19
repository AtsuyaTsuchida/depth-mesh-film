"""Join the segments into one loop (no overlay yet). The overlay comes after film_composite.py.

Usage: .venv/bin/python film_edit.py <film>      (film = a key of PLANS in film_plans.py: people / arch)
Input: out/film/seg_<segment>/####.png
Output: out/film/<film>/base/####.png, out/film/<film>/timeline.json (scene and transition flags per frame)

Transitions (30fps, 1280x1280):
  T1 blocky dissolve (N1 frames, the two segments overlap)
  T2 box reveal (hard cut here; going black except the boxes is done by film_composite)
  T5 stretched-pixel smear (N5 frames overlap)
For the loop, the last transition goes back into the start of the first segment, and the film starts at the
first segment's frame (overlap + 1).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from film_plans import PLANS

film = sys.argv[1]
plan = PLANS[film]
ROOT = Path(__file__).parent / "out" / "film"
OUT = ROOT / film / "base"
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.glob("*.png"):
    old.unlink()
N1, N5, NX = 14, 12, 6
OVERLAP = {"T1": N1, "T2": 0, "T5": N5, "TX": NX}
BLOCK = 40          # block size for the T1 dissolve (px)
H = Wd = 1280


def seg(name):
    return sorted((ROOT / f"seg_{name}").glob("[0-9][0-9][0-9][0-9].png"))


rd = lambda p: np.asarray(Image.open(p).convert("RGB"), np.float32)


def smooth(t):
    return t * t * (3 - 2 * t)


ORDER = np.random.default_rng(7).random((H // BLOCK + 1, Wd // BLOCK + 1))


def block_dissolve(a, b, t):
    # blocks switch in random order from A to B (the reference's rectangular patch swaps), with a short crossfade
    m = np.clip((t * 1.3 - ORDER) / 0.3, 0, 1)
    m = np.kron(m, np.ones((BLOCK, BLOCK)))[:H, :Wd, None]
    soft = smooth(t)
    return (a * (1 - m) + b * m) * 0.8 + (a * (1 - soft) + b * soft) * 0.2


def smear(a, b, t):
    # stretched-pixel smear: rows are cut into bands, each band stretches one column horizontally
    # and slides, building to a peak in the middle and settling into B
    amt = np.sin(np.pi * t)
    out = a * (1 - smooth(t)) + b * smooth(t)
    y = 0
    r = np.random.default_rng(int(t * 1000) // 97)
    while y < H:
        hgt = int(r.integers(6, 48))
        if r.random() < 0.75 * amt:
            src = b if r.random() < t else a
            col = int(r.integers(0, Wd))
            x0 = int(r.integers(0, Wd // 2))
            x1 = min(Wd, x0 + int(r.integers(Wd // 4, Wd)))
            out[y:y + hgt, x0:x1] = src[y:y + hgt, col:col + 1]
        y += hgt
    return out


def label(segname, j):
    name = None
    for start, n in plan["labels"][segname]:
        if j >= start:
            name = n
    return name


segs = [seg(s) for s in plan["segs"]]
frames, info = [], []
n = len(segs)
head = OVERLAP[plan["trans"][-1]]          # the first segment's head is used by the loop's transition
for si, (name, files) in enumerate(zip(plan["segs"], segs)):
    tr_in = plan["trans"][si - 1] if si > 0 else None
    tr_out = plan["trans"][si]
    a = OVERLAP[tr_in] if tr_in else head
    b = OVERLAP[tr_out]
    if tr_in == "T2":
        info_cut = len(frames)
    for j in range(a, len(files) - b):
        frames.append(files[j])
        info.append({"scene": label(name, j + 1)})
    nxt = (si + 1) % n
    for k in range(b):
        t = (k + 1) / (b + 1)
        fa, fb = files[len(files) - b + k], segs[nxt][k]
        kind = {"T1": "dissolve", "T5": "smear", "TX": "fade"}[tr_out]
        frames.append((kind, fa, fb, t))
        info.append({"scene": label(name, len(files) - b + k + 1) if t < 0.5 else label(plan["segs"][nxt], k + 1),
                     "trans": tr_out})
    if tr_in == "T2":
        info[info_cut]["cut"] = "T2"

for i, fr in enumerate(frames, 1):
    if isinstance(fr, tuple):
        kind, a, b, t = fr
        if kind == "dissolve":
            img = block_dissolve(rd(a), rd(b), t)
        elif kind == "smear":
            img = smear(rd(a), rd(b), t)
        else:
            img = rd(a) * (1 - smooth(t)) + rd(b) * smooth(t)
        Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(OUT / f"{i:04d}.png")
    else:
        Image.open(fr).convert("RGB").save(OUT / f"{i:04d}.png")
(ROOT / film / "timeline.json").write_text(json.dumps(info))
cuts = [i + 1 for i, t in enumerate(info) if t.get("cut")]
print(film, len(frames), "frames,", round(len(frames) / 30, 2), "s; T2 cut at", cuts)
