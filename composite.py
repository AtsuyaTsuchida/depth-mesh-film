"""analyze.py の結果を元ネタ風に重ねる。

使い方: .venv/bin/python composite.py <名> [コマ番号 ...] [--loop N]
出力: out/<名>_comp/####.png (コマ番号を渡したらそのコマだけ)
--loop N: 最後の N コマを1コマ目の重ねへクロスフェードする。ループ映像の継ぎ目で
          見せ方の切替や追跡 ID の違いによって重ねが飛ぶのを防ぐ (カメラは最後に止まっている前提)

追跡 ID ごとに見せ方を決め、一定コマごとに切り替える:
  box     枠とラベルだけ
  normal  箱の中を法線マップに置き換える
  mask    箱を黄色で塗り、SAM のマスクを緑で抜く
  echo    数コマ前の絵を箱の中に重ねる (残像)
全体には、箱の中心から特徴点への線、十字、カーソル、時々大きな法線の面を足す。
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

name = sys.argv[1]
args = sys.argv[2:]
loop_n = 0
if "--loop" in args:
    k = args.index("--loop")
    loop_n = int(args[k + 1])
    del args[k:k + 2]
only = [int(a) for a in args]
root = Path(__file__).parent / "out"
src = root / f"{name}_frames"
cv = root / f"{name}_cv"
dst = root / f"{name}_comp"
dst.mkdir(exist_ok=True)
paths = sorted(src.glob("[0-9][0-9][0-9][0-9].png"))
font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)

MAX_PER_LABEL = 6                           # 同じラベルの箱の上限
MAX_FILL = 0.25                             # これより大きい箱は枠だけ
SWAP = 18                                   # 見せ方を切り替える間隔 (コマ)
STYLES = ["box", "normal", "mask", "box", "normal", "echo"]
PERSON_STYLES = ["mask", "box", "mask", "normal"]
LINE_COLS = [(255, 255, 255), (235, 30, 70), (230, 240, 40), (40, 70, 255)]
CHIP = {"person": (200, 240, 0)}            # それ以外は ID から決める
CHIP_PAL = [(200, 240, 0), (255, 255, 255), (40, 90, 255), (235, 30, 70), (0, 220, 230)]
YELLOW, GREEN = np.array([255, 255, 0], np.uint8), np.array([20, 255, 20], np.uint8)


def rnd(*k):
    return np.random.default_rng(abs(hash(k)) % (2**32))


def style(k, ids, labels, boxes, phase, W, H):
    r = rnd("style", int(ids[k]), phase)
    # 人物は大きくても塗る (元ネタの黄色地に緑の人型)。マスクを多めにする
    if labels[k] == "person":
        return PERSON_STYLES[r.integers(len(PERSON_STYLES))]
    # それ以外で画面の 1/4 を超える大きな箱は塗らない (塗ると画面全体が埋まる)
    b = boxes[k]
    if (b[2] - b[0]) * (b[3] - b[1]) > MAX_FILL * W * H:
        return "box"
    return STYLES[r.integers(len(STYLES))]


def load(i):
    d = np.load(cv / f"{i:04d}.npz")
    m = np.unpackbits(d["masks"], axis=-1)
    shp = tuple(d["mshape"])
    masks = m[..., :shp[2]].astype(bool) if len(shp) == 3 and shp[0] else np.zeros((0, 1, 1), bool)
    return d, masks


def cursor(draw, x, y, s=1.0):
    pts = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
    pts = [(x + px * s, y + py * s) for px, py in pts]
    draw.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))


def frame(idx):
    i = idx + 1
    img = np.asarray(Image.open(paths[idx]).convert("RGB")).copy()
    H, W = img.shape[:2]
    nrm = np.asarray(Image.open(cv / f"{i:04d}_n.png"))
    prev = np.asarray(Image.open(paths[max(0, idx - 5)]).convert("RGB"))
    d, masks = load(i)
    boxes, ids, labels, kps = d["boxes"], d["ids"], [str(s) for s in d["labels"]], d["kps"]
    # 同じラベルは大きい順に MAX_PER_LABEL 個まで (温室のトマトが orange/apple で大量に出て画面が埋まるため)
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    seen, keep = {}, []
    for k in np.argsort(-area):
        seen[labels[k]] = seen.get(labels[k], 0) + 1
        if seen[labels[k]] <= MAX_PER_LABEL:
            keep.append(k)
    keep = np.sort(np.array(keep, int))
    boxes, ids, labels = boxes[keep], ids[keep], [labels[k] for k in keep]
    masks = masks[keep] if len(masks) == len(area) else masks
    phase = i // SWAP

    # 時々、画面の大きな帯を法線マップに置き換える (元ネタの下半分が水色になるところ)
    r = rnd("band", phase)
    if r.random() < 0.2:
        y0 = int(r.uniform(0.55, 0.75) * H)
        img[y0:] = (0.3 * img[y0:] + 0.7 * nrm[y0:]).astype(np.uint8)

    order = np.argsort([(b[2] - b[0]) * (b[3] - b[1]) for b in boxes])[::-1]  # 大きい箱から塗る
    for k in order:
        x0, y0, x1, y1 = np.clip(boxes[k], 0, [W - 1, H - 1, W - 1, H - 1]).astype(int)
        if x1 - x0 < 6 or y1 - y0 < 6:
            continue
        st = style(k, ids, labels, boxes, phase, W, H)
        sl = np.s_[y0:y1, x0:x1]
        mk = masks[k][sl] if k < len(masks) and masks[k].shape == (H, W) else None
        if st == "normal":
            img[sl] = (0.1 * img[sl] + 0.9 * nrm[sl]).astype(np.uint8)
        elif st == "mask" and mk is not None:
            tex = img[sl].mean(2, keepdims=True) / 255.0
            fill = np.where(mk[..., None], (GREEN * (0.55 + 0.45 * tex)).astype(np.uint8), YELLOW)
            img[sl] = fill
        elif st == "echo":
            img[sl] = (0.5 * img[sl] + 0.5 * prev[sl]).astype(np.uint8)

    ov = Image.fromarray(img)
    dr = ImageDraw.Draw(ov)
    lines = np.zeros_like(img)
    centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]

    # 線: 箱の中心 → 近い特徴点、箱どうし
    for k, (cx, cy) in enumerate(centers):
        r = rnd("lines", int(ids[k]), phase)
        col = LINE_COLS[r.integers(len(LINE_COLS))]
        if len(kps) and r.random() < 0.6:
            dd = np.hypot(kps[:, 0] - cx, kps[:, 1] - cy)
            for p in kps[np.argsort(dd)[: r.integers(6, 30)]]:
                cv2.line(lines, (int(cx), int(cy)), (int(p[0]), int(p[1])), col, 1, cv2.LINE_AA)
        for j in range(k + 1, len(centers)):
            if r.random() < 0.25:
                cv2.line(lines, (int(cx), int(cy)), (int(centers[j][0]), int(centers[j][1])), (230, 240, 120), 1, cv2.LINE_AA)
    a = (lines.max(2, keepdims=True) > 0) * 0.85
    base = np.asarray(ov).astype(np.float32)
    ov = Image.fromarray((base * (1 - a) + lines * a).astype(np.uint8))
    dr = ImageDraw.Draw(ov)

    # 枠・ラベル・十字
    for k in range(len(boxes)):
        x0, y0, x1, y1 = boxes[k]
        lab = labels[k]
        chip = CHIP.get(lab, CHIP_PAL[int(ids[k]) % len(CHIP_PAL)])
        st = style(k, ids, labels, boxes, phase, W, H)
        if st == "box":
            dr.rectangle([x0, y0, x1, y1], outline=chip, width=1)
        tw = dr.textlength(lab, font=font)
        dr.rectangle([x0, y0 - 17, x0 + tw + 8, y0 - 1], fill=chip)
        dr.text((x0 + 4, y0 - 16), lab, fill=(0, 0, 0) if sum(chip) > 300 else (255, 255, 255), font=font)
        cx, cy = centers[k]
        dr.line([cx - 7, cy, cx + 7, cy], fill=(230, 240, 40), width=1)
        dr.line([cx, cy - 7, cx, cy + 7], fill=(230, 240, 40), width=1)
        r = rnd("ui", int(ids[k]), phase)
        if r.random() < 0.25:
            cursor(dr, cx + r.uniform(-40, 40), cy + r.uniform(-40, 40))
        if r.random() < 0.15:
            ux, uy = x1 - r.uniform(10, 60), y1 - r.uniform(10, 40)
            dr.rectangle([ux, uy, ux + 50, uy + 12], fill=(30, 60, 255))
            dr.rectangle([ux, uy + 14, ux + 30, uy + 24], fill=(235, 30, 70))

    ov.save(dst / f"{i:04d}.png")


for idx in ([o - 1 for o in only] if only else range(len(paths))):
    frame(idx)
if loop_n and not only:
    first = np.asarray(Image.open(dst / "0001.png")).astype(np.float32)
    n = len(paths)
    for k in range(loop_n):
        i = n - loop_n + 1 + k
        a = (k + 1) / (loop_n + 1)
        cur = np.asarray(Image.open(dst / f"{i:04d}.png")).astype(np.float32)
        Image.fromarray(((1 - a) * cur + a * first).astype(np.uint8)).save(dst / f"{i:04d}.png")
print("done", len(only) or len(paths))
