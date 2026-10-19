"""Overlay and grade for the final cut. Sparser than composite.py and closer to the reference.

Usage: .venv/bin/python film_composite.py <film> [frame numbers ...]     (film = people / arch, film_plans.py)
Input: out/film/<film>/base/####.png (film_edit.py), out/<film>base_cv/ (analyze.py <film>base), out/film/<film>/timeline.json
Output: out/film/<film>/final/####.png

- Boxes are mostly outlines or lavender semi-transparent normal fills. A box's look is held for SWAP frames
- Person: the head gets a ghost double (echo). The yellow box with green silhouette flashes for a few frames only at the plan's beats
- Lines: only from at most 2 boxes at a time, thin
- T2 (box reveal): just before and after the cut the frame goes black and content shows only inside the boxes; then the surroundings return block by block
- One full-frame normal-map flash (the plan's flash)
- Grade: mild contrast, warm highlights, light sharpening, fine grain
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from film_plans import PLANS

film = sys.argv[1]
plan = PLANS[film]
ROOT = Path(__file__).parent / "out"
BASE = ROOT / "film" / film / "base"
CV = ROOT / f"{film}base_cv"
DST = ROOT / "film" / film / "final"
DST.mkdir(exist_ok=True)
paths = sorted(BASE.glob("[0-9][0-9][0-9][0-9].png"))
TL = json.loads((ROOT / "film" / film / "timeline.json").read_text())
N = len(paths)
font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 12)

SWAP = 15
MAX_PER_LABEL = 5
LIME, WHITE, BLUE, RED, CYAN = (198, 224, 26), (245, 245, 240), (47, 91, 255), (232, 52, 74), (25, 211, 224)
CHIPS = [WHITE, BLUE, CYAN, RED, LIME]
LINE_COLS = [(250, 250, 250), RED, (230, 236, 60), BLUE]
LAVENDER = np.array([176, 164, 240], np.float32)
YELLOW, GREEN = np.array([255, 250, 0], np.uint8), np.array([30, 230, 40], np.uint8)

# scene-local frame of each scene's start → beats are given as local frame numbers
starts = {}
for i, t in enumerate(TL, 1):
    starts.setdefault(t["scene"], i)
CUT = next((i for i, t in enumerate(TL, 1) if t.get("cut") == "T2"), -10**6)   # films without a box reveal (people v2) skip it
MASK_BEATS = [(starts[sc] + k, n) for sc, k, n in plan["beats"]]
FLASH = (starts[plan["flash"][0]] + plan["flash"][1], plan["flash"][2]) if plan["flash"] else (0, 0)
REVEAL_PRE, REVEAL_POST, REVEAL_GROW = 7, 5, 10


def rnd(*k):
    return np.random.default_rng(abs(hash(k)) % (2**32))


def in_win(i, win):
    return win[0] <= i < win[0] + win[1]


def load(i):
    d = np.load(CV / f"{i:04d}.npz")
    shp = tuple(d["mshape"])
    m = np.unpackbits(d["masks"], axis=-1)
    masks = m[..., :shp[2]].astype(bool) if len(shp) == 3 and shp[0] else np.zeros((0, 1, 1), bool)
    boxes, ids, labels = d["boxes"], d["ids"], [str(s) for s in d["labels"]]
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    seen, keep = {}, []
    for k in np.argsort(-area):
        seen[labels[k]] = seen.get(labels[k], 0) + 1
        if seen[labels[k]] <= MAX_PER_LABEL:
            keep.append(k)
    keep = np.sort(np.array(keep, int))
    masks = masks[keep] if len(masks) == len(area) else np.zeros((len(keep), 1, 1), bool)
    labels = [labels[k] for k in keep]
    boxes = boxes[keep]
    # given a box nearly the size of the frame, SAM sometimes picks the background instead of the person.
    # Judge by how much of the box edge the mask touches (a background mask runs along almost all of it;
    # a person mask only parts of it. Area alone misjudges tight boxes like the walker's)
    for k, m in enumerate(masks):
        if labels[k] == "person" and m.ndim == 2 and m.shape[0] > 1:
            x0, y0, x1, y1 = boxes[k].astype(int)
            inner = m[y0:y1, x0:x1]
            if inner.shape[0] > 8 and inner.shape[1] > 8:
                # a standing or seated person almost never fills the box corners. If the mask covers 3 of the 4
                # corners, it picked the background (edge contact and area misjudged both tight and frame-sized boxes)
                ch, cw = max(2, inner.shape[0] // 8), max(2, inner.shape[1] // 8)
                corners = [inner[:ch, :cw], inner[:ch, -cw:], inner[-ch:, :cw], inner[-ch:, -cw:]]
                if sum(c.mean() > 0.5 for c in corners) >= 3:
                    m[y0:y1, x0:x1] = ~inner
    return boxes, ids[keep], labels, masks, d["kps"]


def lavender(nrm):
    n = nrm.astype(np.float32)
    g = n.mean(2, keepdims=True)
    n = g + (n - g) * 0.55                     # desaturate a little
    return n * 0.6 + LAVENDER * 0.4


def style(i, k, ids, labels, boxes, W, H):
    r = rnd("st", int(ids[k]), i // SWAP)
    b = boxes[k]
    big = (b[2] - b[0]) * (b[3] - b[1]) > 0.18 * W * H     # large normal fills bury the frame
    if labels[k] == "person":
        if any(in_win(i, w) for w in MASK_BEATS):
            return "mask"
        if TL[i - 1]["scene"] == "morph":
            return "trail"          # during a morph the head leaves a trail (the reference's stacked heads)
        return ["box", "echo", "box" if big else "normal", "echo"][r.integers(4)]
    if big:
        return "box"
    return ["box", "box", "normal", "normal", "echo"][r.integers(5)]


def cursor(dr, x, y):
    pts = [(0, 0), (0, 15), (4, 11), (7, 18), (9, 17), (6, 10), (11, 10)]
    dr.polygon([(x + a, y + b) for a, b in pts], fill=(255, 255, 255), outline=(0, 0, 0))


def grade(img):
    x = img.astype(np.float32) / 255
    x = 0.5 + (x - 0.5) * 1.06                              # mild contrast
    hi = np.clip((x.mean(2, keepdims=True) - 0.55) / 0.45, 0, 1)
    x = x * (1 + hi * np.array([0.012, 0.0, -0.018]))       # warm the highlights slightly
    x = 0.012 + x * 0.976                                   # lift blacks slightly
    return np.clip(x * 255, 0, 255)


def frame(i):
    base = Image.open(paths[i - 1]).convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=35, threshold=2))
    img = grade(np.asarray(base)).astype(np.uint8)
    H, W = img.shape[:2]
    nrm = lavender(np.asarray(Image.open(CV / f"{i:04d}_n.png")))
    # ghosts only come from the same scene (across the cut, the previous scene's face showed through)
    j = max(1, i - 6)
    while TL[j - 1]["scene"] != TL[i - 1]["scene"] and j < i:
        j += 1
    prev = np.asarray(Image.open(paths[j - 1]).convert("RGB"))
    boxes, ids, labels, masks, kps = load(i)
    boxes = np.clip(boxes, 0, [W - 1, H - 1, W - 1, H - 1])
    trans = TL[i - 1].get("trans")

    if in_win(i, FLASH):
        img = nrm.astype(np.uint8)

    for k in np.argsort([-(b[2] - b[0]) * (b[3] - b[1]) for b in boxes]):
        x0, y0, x1, y1 = boxes[k].astype(int)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        st = style(i, k, ids, labels, boxes, W, H)
        sl = np.s_[y0:y1, x0:x1]
        if st == "normal":
            img[sl] = (img[sl] * 0.4 + nrm[sl] * 0.6).astype(np.uint8)
        elif st == "mask" and masks[k].shape == (H, W):
            tex = img[sl].mean(2, keepdims=True) / 255
            img[sl] = np.where(masks[k][sl][..., None], (GREEN * (0.6 + 0.4 * tex)).astype(np.uint8), YELLOW)
        elif st == "echo":
            # ghost double of the person's head (or the top of the box): blend in a few frames earlier
            hy = y0 + int((y1 - y0) * (0.4 if labels[k] == "person" else 1.0))
            s2 = np.s_[y0:hy, x0:x1]
            img[s2] = (img[s2] * 0.5 + prev[s2] * 0.5).astype(np.uint8)
        elif st == "trail":
            # head trail: stack the head region from 2, 4, 6, 8 frames ago, oldest first.
            # As the person changes shape and moves, the heads pile up in a row
            pad = int((x1 - x0) * 0.3)
            hx0, hx1 = max(0, x0 - pad), min(W, x1 + pad)
            hy = y0 + int((y1 - y0) * 0.45)
            s2 = np.s_[max(0, y0 - pad):hy, hx0:hx1]
            cur = img[s2].copy()
            for d in (8, 6, 4, 2):
                if i - d >= 1:
                    old = np.asarray(Image.open(paths[i - d - 1]).convert("RGB"))
                    img[s2] = (img[s2] * 0.55 + old[s2] * 0.45).astype(np.uint8)
            # keep the current person sharp on top (ghosts only outside the silhouette; laying them over blurred the face)
            if masks[k].shape == (H, W):
                me = masks[k][s2]
                img[s2] = np.where(me[..., None], cur, img[s2])

    # T2 box reveal: black except inside the boxes, then the surroundings return block by block
    if CUT - REVEAL_PRE <= i < CUT + REVEAL_POST + REVEAL_GROW:
        keep = np.zeros((H, W), bool)
        # use mid-size boxes only (the runner's person box covers almost the whole frame, so nothing went black)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        # people are allowed up to 60% (as in the reference, people show inside rectangles)
        ok = np.nonzero((area < 0.25 * W * H) | ((np.array(labels) == "person") & (area < 0.6 * W * H)))[0]
        for b in boxes[ok[np.argsort(-area[ok])]][:6]:
            x0, y0, x1, y1 = b.astype(int)
            keep[y0:y1, x0:x1] = True
        # people show as their SAM silhouette (cut out on black), however large
        for k in range(len(boxes)):
            if labels[k] == "person" and masks[k].shape == (H, W):
                keep |= masks[k]
        if i >= CUT + REVEAL_POST:
            t = (i - CUT - REVEAL_POST + 1) / REVEAL_GROW
            blocks = rnd("reveal").random((H // 64 + 1, W // 64 + 1)) < t
            keep |= np.kron(blocks, np.ones((64, 64), bool))[:H, :W]
        img[~keep] = 8

    ov = Image.fromarray(img)
    dr = ImageDraw.Draw(ov)
    lines = np.zeros_like(img)
    centers = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    if len(boxes) and trans != "T5":
        r = rnd("fan", i // SWAP)
        pick = list(r.choice(len(boxes), size=min(2, len(boxes)), replace=False))
        for k in pick:
            cx, cy = centers[k]
            col = LINE_COLS[rnd("lc", int(ids[k]), i // SWAP).integers(len(LINE_COLS))]
            if len(kps):
                dd = np.hypot(kps[:, 0] - cx, kps[:, 1] - cy)
                for p in kps[np.argsort(dd)[:18]]:
                    cv2.line(lines, (int(cx), int(cy)), (int(p[0]), int(p[1])), col, 1, cv2.LINE_AA)
            for j in range(len(centers)):
                if j != k and rnd("ln", k, j, i // SWAP).random() < 0.35:
                    cv2.line(lines, (int(cx), int(cy)), (int(centers[j][0]), int(centers[j][1])), (230, 236, 140), 1, cv2.LINE_AA)
    a = lines.max(2, keepdims=True).astype(np.float32) / 255 * 0.8
    ov = Image.fromarray((np.asarray(ov) * (1 - a) + lines * a).astype(np.uint8))
    dr = ImageDraw.Draw(ov)

    for k in range(len(boxes)):
        x0, y0, x1, y1 = boxes[k]
        lab = labels[k]
        chip = LIME if lab == "person" else CHIPS[int(ids[k]) % len(CHIPS)]
        st = style(i, k, ids, labels, boxes, W, H)
        if st in ("box", "echo", "trail"):
            dr.rectangle([x0, y0, x1, y1], outline=chip + (0,) if False else chip, width=1)
        tw = dr.textlength(lab, font=font)
        dr.rectangle([x0, y0 - 15, x0 + tw + 6, y0 - 1], fill=chip)
        dr.text((x0 + 3, y0 - 15), lab, fill=(10, 10, 10) if sum(chip) > 300 else (250, 250, 250), font=font)
        cx, cy = centers[k]
        if lab == "person" or rnd("x", int(ids[k])).random() < 0.4:
            dr.line([cx - 6, cy, cx + 6, cy], fill=(230, 236, 60))
            dr.line([cx, cy - 6, cx, cy + 6], fill=(230, 236, 60))
        r = rnd("ui", int(ids[k]), i // SWAP)
        if r.random() < 0.2:
            cursor(dr, cx + r.uniform(-30, 30), cy + r.uniform(-30, 30))
        if r.random() < 0.12:
            ux, uy = x0 + r.uniform(0, max(1, x1 - x0 - 40)), y1 - r.uniform(14, 40)
            dr.rectangle([ux, uy, ux + 36, uy + 9], fill=BLUE)
            dr.rectangle([ux, uy + 11, ux + 22, uy + 19], fill=RED)

    # fine grain (avoids banding after compression too)
    out = np.asarray(ov).astype(np.float32)
    g = np.random.default_rng(i).normal(0, 1.4, out.shape[:2])[..., None]
    Image.fromarray(np.clip(out + g, 0, 255).astype(np.uint8)).save(DST / f"{i:04d}.png")


for i in ([int(a) for a in sys.argv[2:]] or range(1, N + 1)):
    frame(i)
print("done", N, "frames; T2 cut", CUT, "mask beats", MASK_BEATS, "flash", FLASH)
