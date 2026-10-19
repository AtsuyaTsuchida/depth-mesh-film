"""静止画 → 深度マップ (Depth Anything V2)。

使い方: .venv/bin/python depth.py <画像> [出力名]
出力: out/<名>.png (元画像のコピー), out/<名>_depth.npy (float32, 大きいほど近い=相対視差),
      out/<名>_depth.png (確認用 8bit)
"""
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import pipeline

MODEL = "depth-anything/Depth-Anything-V2-Base-hf"

src = Path(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else src.stem
out = Path(__file__).parent / "out"
out.mkdir(exist_ok=True)

img = Image.open(src).convert("RGB")
dev = "mps" if torch.backends.mps.is_available() else "cpu"
pipe = pipeline("depth-estimation", model=MODEL, device=dev)
res = pipe(img)

# predicted_depth はモデル解像度。元画像サイズへ補間する
d = res["predicted_depth"]
d = d if d.dim() == 3 else d[None]
d = torch.nn.functional.interpolate(d[None].float(), size=img.size[::-1], mode="bicubic", align_corners=False)[0, 0]
d = d.cpu().numpy().astype(np.float32)

img.save(out / f"{name}.png")
np.save(out / f"{name}_depth.npy", d)
v = (d - d.min()) / (d.max() - d.min() + 1e-8)
Image.fromarray((v * 255).astype(np.uint8)).save(out / f"{name}_depth.png")
print(name, img.size, "disp range", float(d.min()), float(d.max()))
