"""深度マップ → 点群 (カメラ座標を Blender のワールドへ)。

使い方: .venv/bin/python points.py <名> [間引きpx] [近m 遠m]
入力: out/<名>.png, out/<名>_depth.npy   出力: out/<名>_points.npz (xyz, rgb, rad, meta)

元写真のカメラを原点・+Y向きに置く。Blender の x=右, y=奥, z=上。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HFOV_DEG = 70.0          # 元写真の想定水平画角
NEAR, FAR = 1.5, 60.0    # 相対視差を実距離(m)に割り当てる範囲 (駅のような奥行きのある場面向け)

name = sys.argv[1]
step = int(sys.argv[2]) if len(sys.argv) > 2 else 3
if len(sys.argv) > 4:   # スタジオの人物のように奥行きの浅い場面は狭くする
    NEAR, FAR = float(sys.argv[3]), float(sys.argv[4])
out = Path(__file__).parent / "out"

rgb = np.asarray(Image.open(out / f"{name}.png").convert("RGB"), dtype=np.float32) / 255.0
disp = np.load(out / f"{name}_depth.npy")
h, w = disp.shape

dn = (disp - disp.min()) / (disp.max() - disp.min())
z = 1.0 / (dn * (1.0 / NEAR - 1.0 / FAR) + 1.0 / FAR)

f = (w / 2) / np.tan(np.radians(HFOV_DEG) / 2)
v, u = np.mgrid[0:h:step, 0:w:step]
# 格子のままだとモアレの縞が出るので、各セル内でサンプル位置を揺らす
rng = np.random.default_rng(0)
v = np.clip(v + rng.integers(0, step, v.shape), 0, h - 1)
u = np.clip(u + rng.integers(0, step, u.shape), 0, w - 1)
zs = z[v, u]
x = (u + 0.5 - w / 2) / f * zs
y = -(v + 0.5 - h / 2) / f * zs
xyz = np.stack([x, zs, y], -1).reshape(-1, 3).astype(np.float32)
col = rgb[v, u].reshape(-1, 3)
# Blender の色属性はリニアなので sRGB から戻す
col = np.where(col <= 0.04045, col / 12.92, ((col + 0.055) / 1.055) ** 2.4).astype(np.float32)
# 1点が元写真で覆う大きさ。少し重ねて正面からは隙間が出ないようにする
rad = (zs / f * step * 1.2).reshape(-1).astype(np.float32)

np.savez(out / f"{name}_points.npz", xyz=xyz, rgb=col, rad=rad,
         meta=np.array([w, h, f, HFOV_DEG], dtype=np.float32))
print(name, len(xyz), "points, z", float(zs.min()), float(zs.max()))
