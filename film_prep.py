"""Prepare each scene for the final film's "depth mesh" (texture + per-frame depth grid + ragged edge mask).

Usage:
  .venv/bin/python film_prep.py image <name> <image> <near m> <far m>    # still image (uses out/<name>_depth.npy if present)
  .venv/bin/python film_prep.py video <name> <video> <near m> <far m>    # video (depth estimated per frame)
  .venv/bin/python film_prep.py mask <name> <bite>                      # remake only the ragged edge mask (default 0.16; smaller bites less)
Output: out/film/<name>/
  rgb/####.png   texture per frame (still images: 0001 only)
  z/####.npy     distance (m) of the GW x GH grid vertices, float32
  mask.png       ragged edge mask (white = keep). Same organic, torn outline as the reference instead of a rectangle
  meta.json      w, h, f (px), grid, frame count, source fps

For video, normalising disparity per frame makes the distance wobble every frame, so all frames are
normalised together with the 1–99.5th percentiles.
In video the subject comes up to the top of the frame, so a deep bite eats the head. Use a mask of about 0.06 for video.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HFOV_DEG = 70.0
GW, GH = 800, 450
MODEL = "depth-anything/Depth-Anything-V2-Base-hf"

kind, name = sys.argv[1], sys.argv[2]
root = Path(__file__).parent / "out"
dst = root / "film" / name


def make_mask(w, h, cut=0.16):
    # ragged edge: distance from the border + noise at several scales, cut at a threshold
    mw, mh = 1024, int(1024 * h / w)
    yy, xx = np.mgrid[0:mh, 0:mw]
    edge = np.minimum.reduce([xx / mw, (mw - 1 - xx) / mw, yy / mh, (mh - 1 - yy) / mh]) * 2
    rng = np.random.default_rng(sum(name.encode()))
    noise = np.zeros((mh, mw), np.float32)
    for octave, amp in ((8, 0.5), (24, 0.3), (80, 0.2)):
        n = rng.random((octave * mh // mw + 2, octave + 2)).astype(np.float32)
        n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((mw, mh), Image.BICUBIC), np.float32) / 255
        noise += amp * n
    alpha = (edge * 2.2 + (noise - 0.5) * 0.55 * cut / 0.16) > cut
    Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(3)).save(dst / "mask.png")


if kind == "mask":
    meta = json.loads((dst / "meta.json").read_text())
    make_mask(meta["w"], meta["h"], float(sys.argv[3]))
    print("mask", name)
    sys.exit()

import torch  # noqa: E402  (not needed for mask alone)
from transformers import pipeline  # noqa: E402

src = Path(sys.argv[3])
NEAR, FAR = float(sys.argv[4]), float(sys.argv[5])
(dst / "rgb").mkdir(parents=True, exist_ok=True)
(dst / "z").mkdir(exist_ok=True)

_pipe = None


def depth_of(img):
    global _pipe
    if _pipe is None:
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        _pipe = pipeline("depth-estimation", model=MODEL, device=dev)
    d = _pipe(img)["predicted_depth"]
    d = d if d.dim() == 3 else d[None]
    d = torch.nn.functional.interpolate(d[None].float(), size=img.size[::-1], mode="bicubic")[0, 0]
    return d.cpu().numpy()


def grid(a):
    # take disparity at the grid vertices (pixel centres)
    h, w = a.shape
    ys = ((np.arange(GH) + 0.5) * h / GH).astype(int)
    xs = ((np.arange(GW) + 0.5) * w / GW).astype(int)
    return a[np.ix_(ys, xs)]


if kind == "image":
    img = Image.open(src).convert("RGB")
    pre = root / f"{name}_depth.npy"
    disps = [np.load(pre) if pre.exists() else depth_of(img)]
    imgs = [img]
    fps = 0
else:
    fps = float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                "stream=r_frame_rate", "-of", "csv=p=0", str(src)],
                               capture_output=True, text=True).stdout.strip().split("/")[0])
    imgs, disps = [], []
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), f"{tmp}/%04d.png"], check=True)
        for p in sorted(Path(tmp).glob("*.png")):
            img = Image.open(p).convert("RGB")
            imgs.append(img)
            disps.append(depth_of(img))
            print("depth", p.stem, flush=True)

lo, hi = np.percentile(np.stack([grid(d) for d in disps]), [1, 99.5])
for i, (img, disp) in enumerate(zip(imgs, disps), 1):
    dn = np.clip((grid(disp) - lo) / (hi - lo), 0, 1)
    z = 1.0 / (dn * (1.0 / NEAR - 1.0 / FAR) + 1.0 / FAR)
    np.save(dst / "z" / f"{i:04d}.npy", z.astype(np.float32))
    img.save(dst / "rgb" / f"{i:04d}.png")

w, h = imgs[0].size
make_mask(w, h, 0.16 if kind == "image" else 0.06)
f = (w / 2) / np.tan(np.radians(HFOV_DEG) / 2)
(dst / "meta.json").write_text(json.dumps({"w": w, "h": h, "f": f, "gw": GW, "gh": GH,
                                           "frames": len(imgs), "fps": fps, "near": NEAR, "far": FAR}))
print(name, len(imgs), "frames", (w, h))
