"""CV の解析結果から音の「楽譜」を書く (音は作らない。Max の coll が読むテキストを出すだけ)。

使い方: ../.venv/bin/python score.py <名> <fps>
入力: ../out/<名>_cv/####.npz, ../out/<名>_frames/####.png
出力: <名>.txt  (coll 形式: "コマ, trig nnew pan freq ntr motion edge hold;")

  trig    コマ番号 (gen~ はこれが変わったらそのコマのイベントを鳴らす)
  nnew    このコマで新しく現れた追跡 ID の数 → クリック + データ音
  pan     新しく現れた箱のうち最大のものの中心の横位置 (0=左, 1=右)
  freq    そのラベルに割り当てた音高 (Hz)。ラベルごとに固定
  ntr     画面上の箱の数 → コマ内の細かいクリックの密度
  motion  カメラの動き (前のコマとの差、0〜1) → 低いうなり
  edge    重ねの見せ方が切り替わるコマ (composite.py の SWAP ごと) → ノイズの破裂
  hold    ほぼ止まっているコマ (写真の視点) → 1 kHz のテストトーン
"""
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

name, fps = sys.argv[1], float(sys.argv[2])
here = Path(__file__).parent
cv = here.parent / "out" / f"{name}_cv"
frames = sorted((here.parent / "out" / f"{name}_frames").glob("[0-9][0-9][0-9][0-9].png"))

SWAP = 18                                            # composite.py と同じ
TONES = [880, 1320, 1760, 2640, 3520, 5280, 7040]    # データ音の候補 (Hz)

small = [np.asarray(Image.open(p).convert("L").resize((96, 96)), np.float32) for p in frames]
diff = np.array([0.0] + [np.abs(a - b).mean() for a, b in zip(small[1:], small[:-1])])
motion = np.clip(diff / (np.percentile(diff, 95) + 1e-6), 0, 1)

lines, seen = [], set()
for i in range(1, len(frames) + 1):
    d = np.load(cv / f"{i:04d}.npz")
    ids, labels, boxes = d["ids"], [str(s) for s in d["labels"]], d["boxes"]
    W = 1080.0
    new = [k for k, t in enumerate(ids) if int(t) not in seen]
    seen.update(int(t) for t in ids)
    if new:
        k = max(new, key=lambda k: (boxes[k][2] - boxes[k][0]) * (boxes[k][3] - boxes[k][1]))
        pan = float((boxes[k][0] + boxes[k][2]) / 2 / W)
        freq = TONES[zlib.crc32(labels[k].encode()) % len(TONES)]
    else:
        pan, freq = 0.5, 1000
    edge = int(i // SWAP != (i - 1) // SWAP)
    hold = int(motion[i - 1] < 0.08)
    lines.append(f"{i}, {i} {len(new)} {pan:.3f} {freq} {len(ids)} {motion[i - 1]:.3f} {edge} {hold};")

(here / f"{name}.txt").write_text("\n".join(lines) + "\n")
print(name, len(lines), "frames, new-track events", sum(int(l.split()[2]) > 0 for l in lines))
