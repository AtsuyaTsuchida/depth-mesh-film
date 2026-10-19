"""レンダー済みの連番に実際の CV をかけて結果を保存する (合成は composite.py)。

使い方: .venv/bin/python analyze.py <名>
入力: out/<名>_frames/####.png
出力: out/<名>_cv/####.npz  (boxes, ids, labels, scores, masks, kps)
      out/<名>_cv/####_n.png (法線マップ)

- 検出: YOLO-World (駅向けの語彙) + COCO の YOLO11 (誤検出もそのまま使う)
- 追跡: IoU で前のコマの箱とつなぎ、座標をならし、見失っても数コマ残す
- マスク: SAM 2.1 に箱をプロンプトとして渡す
- 法線: コマごとに Depth Anything で深度を出し、その勾配から求める
- 特徴点: ORB
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import pipeline
from ultralytics import SAM, YOLO

name = sys.argv[1]
root = Path(__file__).parent
frames = sorted((root / "out" / f"{name}_frames").glob("[0-9][0-9][0-9][0-9].png"))
dst = root / "out" / f"{name}_cv"
dst.mkdir(exist_ok=True)
models = root / "models"
dev = "mps" if torch.backends.mps.is_available() else "cpu"

WORLD_CLASSES = ["person", "pillar", "train", "door", "window", "ceiling light", "sign",
                 "floor tile", "bench", "rail", "wall", "vehicle"]
world = YOLO(models / "yolov8x-worldv2.pt")
world.set_classes(WORLD_CLASSES)
coco = YOLO(models / "yolo11m.pt")
sam = SAM(models / "sam2.1_b.pt")
depth = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Base-hf", device=dev)
orb = cv2.ORB_create(nfeatures=400)

HOLD = 8        # 見失ってから残すコマ数
SMOOTH = 0.6    # 箱座標のならし (前のコマの重み)


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0


def detect(path):
    dets = []
    for m, conf in ((world, 0.03), (coco, 0.05)):
        r = m.predict(str(path), conf=conf, verbose=False, device=dev)[0]
        for b, c, s in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy()):
            dets.append((b, r.names[int(c)], float(s)))
    return dets


def normals_from(img):
    d = depth(img)["predicted_depth"]
    d = d if d.dim() == 3 else d[None]
    d = torch.nn.functional.interpolate(d[None].float(), size=img.size[::-1], mode="bicubic")[0, 0].cpu().numpy()
    d = cv2.GaussianBlur(d, (0, 0), 2)
    gx = cv2.Sobel(d, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(d, cv2.CV_32F, 0, 1, ksize=5)
    k = 4.0 / (np.abs(d).max() + 1e-6)   # 勾配の強さを深度の範囲で正規化
    n = np.dstack([-gx * k, gy * k, np.ones_like(d)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return ((n * 0.5 + 0.5) * 255).astype(np.uint8)


tracks = []   # dict(id, box, label, score, miss)
next_id = 0
for path in frames:
    img = Image.open(path).convert("RGB")
    dets = detect(path)

    used = set()
    for t in tracks:
        best, bi = 0.3, -1
        for i, (b, lab, s) in enumerate(dets):
            if i not in used and lab == t["label"] and iou(t["box"], b) > best:
                best, bi = iou(t["box"], b), i
        if bi >= 0:
            used.add(bi)
            t["box"] = SMOOTH * t["box"] + (1 - SMOOTH) * dets[bi][0]
            t["score"], t["miss"] = dets[bi][2], 0
        else:
            t["miss"] += 1
    for i, (b, lab, s) in enumerate(dets):
        if i not in used:
            tracks.append(dict(id=next_id, box=b.astype(np.float32), label=lab, score=s, miss=0))
            next_id += 1
    tracks = [t for t in tracks if t["miss"] <= HOLD]

    boxes = np.array([t["box"] for t in tracks], np.float32).reshape(-1, 4)
    if len(boxes):
        r = sam.predict(str(path), bboxes=boxes.tolist(), verbose=False, device=dev)[0]
        masks = r.masks.data.cpu().numpy().astype(bool) if r.masks is not None else np.zeros((0, img.height, img.width), bool)
    else:
        masks = np.zeros((0, img.height, img.width), bool)

    gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    kps = np.array([k.pt for k in orb.detect(gray, None)], np.float32).reshape(-1, 2)

    stem = path.stem
    np.savez_compressed(dst / f"{stem}.npz", boxes=boxes,
                        ids=np.array([t["id"] for t in tracks], np.int32),
                        labels=np.array([t["label"] for t in tracks]),
                        scores=np.array([t["score"] for t in tracks], np.float32),
                        miss=np.array([t["miss"] for t in tracks], np.int32),
                        masks=np.packbits(masks, axis=-1), mshape=np.array(masks.shape), kps=kps)
    Image.fromarray(normals_from(img)).save(dst / f"{stem}_n.png")
    print(stem, len(tracks), "tracks", len(kps), "kps", flush=True)
