"""動画 → コマごとの深度 → コマごとの点群 (動く点群)。

使い方: .venv/bin/python video_points.py <動画> <名> [間引きpx] [近m 遠m]
出力: out/<名>_vpts/####.npz (xyz, rgb, rad, meta)。全コマ同じ点数 (scene_video.py で頂点を差し替えるため)

深度はコマごとに Depth Anything で出す。視差の正規化をコマごとにすると距離が毎コマ揺れるので、
全コマの視差の 1〜99.5 パーセンタイルでまとめて正規化する。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import pipeline

HFOV_DEG = 70.0
MODEL = "depth-anything/Depth-Anything-V2-Base-hf"

src, name = Path(sys.argv[1]), sys.argv[2]
step = int(sys.argv[3]) if len(sys.argv) > 3 else 2
NEAR, FAR = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (2.0, 80.0)
dst = Path(__file__).parent / "out" / f"{name}_vpts"
dst.mkdir(parents=True, exist_ok=True)

dev = "mps" if torch.backends.mps.is_available() else "cpu"
pipe = pipeline("depth-estimation", model=MODEL, device=dev)

with tempfile.TemporaryDirectory() as tmp:
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), f"{tmp}/%04d.png"], check=True)
    frames = sorted(Path(tmp).glob("*.png"))
    imgs, disps = [], []
    for p in frames:
        img = Image.open(p).convert("RGB")
        d = pipe(img)["predicted_depth"]
        d = d if d.dim() == 3 else d[None]
        d = torch.nn.functional.interpolate(d[None].float(), size=img.size[::-1], mode="bicubic")[0, 0]
        imgs.append(np.asarray(img, dtype=np.float32) / 255.0)
        disps.append(d.cpu().numpy())
        print("depth", p.stem, flush=True)

lo, hi = np.percentile(np.stack(disps)[:, ::8, ::8], [1, 99.5])
h, w = disps[0].shape
f = (w / 2) / np.tan(np.radians(HFOV_DEG) / 2)
rng = np.random.default_rng(0)
v, u = np.mgrid[0:h:step, 0:w:step]
v = np.clip(v + rng.integers(0, step, v.shape), 0, h - 1)   # ジッターは全コマ共通
u = np.clip(u + rng.integers(0, step, u.shape), 0, w - 1)

for i, (rgb, disp) in enumerate(zip(imgs, disps), 1):
    dn = np.clip((disp - lo) / (hi - lo), 0, 1)
    z = 1.0 / (dn * (1.0 / NEAR - 1.0 / FAR) + 1.0 / FAR)
    zs = z[v, u]
    x = (u + 0.5 - w / 2) / f * zs
    y = -(v + 0.5 - h / 2) / f * zs
    xyz = np.stack([x, zs, y], -1).reshape(-1, 3).astype(np.float32)
    col = rgb[v, u].reshape(-1, 3)
    col = np.where(col <= 0.04045, col / 12.92, ((col + 0.055) / 1.055) ** 2.4).astype(np.float32)
    rad = (zs / f * step * 1.2).reshape(-1).astype(np.float32)
    np.savez(dst / f"{i:04d}.npz", xyz=xyz, rgb=col, rad=rad, meta=np.array([w, h, f, HFOV_DEG], np.float32))
print(name, len(imgs), "frames", len(xyz), "points/frame")
