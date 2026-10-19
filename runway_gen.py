"""動く人物の素材を Runway で作る。静止画 (候補) → 選んだ1枚から動画。

既定はドライラン (見積もりと残高を表示)。--run を付けたときだけ送信する。
API の呼び出しは runway_api.py (キーは環境変数 RUNWAYML_API_SECRET か .env)。
人物はすべてオリジナル (既存作品の登場人物や実在の人に似せない)。

  .venv/bin/python runway_gen.py image <場面> [--run]          # 候補 2 枚 → runway/<場面>__1.png, __2.png
  .venv/bin/python runway_gen.py video <場面> [--run] --pick 1 # 選んだ1枚から 5 秒 → runway/<場面>.mp4
  .venv/bin/python runway_gen.py morph <つなぎ> [--run]          # 前の場面の最後のコマ → 次の場面の最初のコマ → runway/morph_<つなぎ>.mp4

morph は元ネタの「人から人へのモーフィング」用。最初と最後のコマを指定して (keyframe モード)、
その間で人物が姿勢ごと連続して次の人物に変わり、周りの場所も育つように変わる動画を作る。
最初・最後のコマは film_prep.py が書き出した各場面のコマ (out/film/<場面>/rgb/) を使う。
"""
import argparse
import sys
from pathlib import Path

import runway_api as gen

HERE = Path(__file__).resolve().parent

OUT = HERE / "runway"

SCENES = {
    "walker": {
        "image": (
            "Wide cinematic still, eye level, camera locked off. A young woman in a faded rust-orange work jumpsuit "
            "and dusty boots walks straight toward the camera across a cracked dry salt flat, full body in frame, "
            "centered, a few metres away. Scattered pale rocks and dry shrubs on the ground, an old dusty pickup truck "
            "parked far behind her on the left, low mesas on the horizon, hard midday sun, clear pale blue sky. "
            "Photoreal, sharp focus, deep depth of field, no text, no logo."
        ),
        "video": (
            "She keeps walking steadily straight toward the camera at a calm pace, natural arm swing. "
            "The camera is completely static on a tripod, no camera movement, no zoom. Constant lighting, "
            "the truck and rocks stay still. Realistic motion, no cuts."
        ),
    },
    "greenhouse": {
        "image": (
            "Cinematic still, eye level, camera locked off. An older man with a short grey beard, wearing a faded navy "
            "windbreaker and work trousers, sits on an upturned wooden crate in the middle of an overgrown glass "
            "greenhouse, full body in frame, centered, a few metres from the camera, elbows on his knees. "
            "Dense tall green plants, potted ferns and tomato vines around him, stacked terracotta pots and a "
            "watering can on the floor, a wooden bench on the right, sunlight through dusty glass panes behind. "
            "Photoreal, sharp focus, deep depth of field, no text, no logo."
        ),
        "video": (
            "He slowly stands up from the crate, straightens, and takes two calm steps toward the camera, "
            "looking ahead. The camera is completely static on a tripod, no camera movement, no zoom. "
            "Constant lighting, the plants barely sway. Realistic motion, no cuts."
        ),
    },
}
FILM = HERE / "out" / "film"
# gen4_turbo は最初のコマしか受け付けない (last を渡すと 400)。h3_max は first/last のキーフレームが使える
MORPH_MODEL, MORPH_RES, MORPH_SECONDS, MORPH_RATE = "h3_max", "768p", 5, 8   # 1秒あたりの credits (目安)
MORPH_STYLE = (" One continuous shot from a fixed camera, the figure stays centred and about the same size the whole time. "
               "The body never cuts or fades: it bends and reshapes smoothly, limbs and clothing flowing into the new pose and person. "
               "Photoreal, no text.")
MORPH_STYLE_ARCH = (" One continuous shot from a fixed camera, no cut and no fade: the architecture bends, slides and reshapes "
                    "smoothly like a fluid transformation, keeping the same one-point perspective. No people. Photoreal, no text.")
MORPHS = {
    "walker_greenhouse": {
        "first": FILM / "walker" / "rgb" / "0124.png", "last": FILM / "greenhouse" / "rgb" / "0001.png",
        "prompt": "The young woman in the rust-orange jumpsuit slows down and gradually sits down; as she lowers herself her "
                  "body continuously transforms into an older bearded man in a navy windbreaker sitting on a wooden crate. "
                  "Around them the cracked salt flat sprouts green plants that grow up into a glass greenhouse full of tomato vines.",
    },
    "greenhouse_runner": {
        "first": FILM / "greenhouse" / "rgb" / "0124.png", "last": FILM / "runner" / "rgb" / "0001.png",
        "prompt": "The older man in the navy windbreaker turns sideways and breaks into a sprint; while he runs his body "
                  "continuously transforms into a lean female sprinter in grey athletic wear seen from the side in full stride, "
                  "flakes peeling off her. The greenhouse dissolves into a plain warm-grey studio backdrop.",
    },
    # ---- architecture film: one space reshapes into the next (no people) ----
    "arch_pg": {
        "first": FILM / "platform" / "rgb" / "0001.png", "last": FILM / "gates" / "rgb" / "0001.png", "arch": True,
        "prompt": "The long empty subway platform continuously reshapes: the train slides away into the wall, the row of "
                  "pillars bends and shrinks into a row of steel ticket gates, the long ceiling light strips rearrange into "
                  "a grid of ceiling panels, until it becomes a bright, empty station ticket-gate hall.",
    },
    "arch_gc": {
        "first": FILM / "gates" / "rgb" / "0001.png", "last": FILM / "corridor" / "rgb" / "0001.png", "arch": True,
        "prompt": "The empty ticket-gate hall continuously reshapes: the ticket gates sink smoothly into the floor, the "
                  "glass wall at the back stretches far away, and the hall narrows and lengthens into a long, clean white "
                  "corridor with a line of ceiling lights running to a vanishing point.",
    },
    "arch_ce": {
        "first": FILM / "corridor" / "rgb" / "0001.png", "last": FILM / "escalator" / "rgb" / "0001.png", "arch": True,
        "prompt": "The long white corridor continuously reshapes: its floor tilts upward and splits into steps, the walls "
                  "fold into polished steel balustrades, until it becomes a pair of symmetrical escalators rising "
                  "straight ahead under a concrete ceiling.",
    },
    "arch_er": {
        "first": FILM / "escalator" / "rgb" / "0001.png", "last": FILM / "revolving" / "rgb" / "0001.png", "arch": True,
        "prompt": "The twin escalators continuously reshape: the steps flatten into a polished stone floor, the steel "
                  "balustrades curve round into the glass drums of revolving doors, and the ceiling lifts and opens into a "
                  "bright lobby with a tall glass wall facing the city.",
    },
    "arch_rp": {
        "first": FILM / "revolving" / "rgb" / "0001.png", "last": FILM / "platform" / "rgb" / "0001.png", "arch": True,
        "prompt": "The bright lobby with revolving doors continuously reshapes: the glass doors stretch backward into a "
                  "row of white pillars, the floor extends into a long platform and a silver train slides in along the "
                  "right side, until it becomes a long, empty underground subway platform.",
    },
    "runner_walker": {
        "first": FILM / "runner" / "rgb" / "0001.png", "last": FILM / "walker" / "rgb" / "0001.png",
        "prompt": "The female sprinter in grey slows from a sprint into a walk and turns to face the camera; as she turns "
                  "her body continuously transforms into a young woman in a rust-orange work jumpsuit walking toward the camera. "
                  "The grey studio opens out into a bright cracked salt flat with an old pickup truck far behind.",
    },
}
COUNT, QUALITY = 2, "high"
DURATION, RES = 5, "768p"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["image", "video", "morph"])
    ap.add_argument("scene", choices=list(SCENES) + list(MORPHS))
    ap.add_argument("--run", action="store_true", help="実際に生成する (付けなければ見積もりのみ)")
    ap.add_argument("--pick", type=int, default=1, help="video の起点にする候補番号")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    sc = SCENES.get(args.scene)

    if args.step == "morph":
        mo = MORPHS[args.scene]
        credits = MORPH_RATE * MORPH_SECONDS
        body = {"model": MORPH_MODEL, "resolution": MORPH_RES, "duration": MORPH_SECONDS,
                "promptText": mo["prompt"] + (MORPH_STYLE_ARCH if mo.get("arch") else MORPH_STYLE),
                "promptImage": [{"uri": "FIRST", "position": "first"}, {"uri": "LAST", "position": "last"}]}
        path, dst = "/image_to_video", OUT / f"morph_{args.scene}.mp4"
        note = {"first": str(mo["first"].relative_to(HERE)), "last": str(mo["last"].relative_to(HERE))}
        print(f"モーフ {MORPH_SECONDS}s / {MORPH_MODEL} ← {mo['first'].parent.parent.name} → {mo['last'].parent.parent.name} → 約 {credits} credits")
    elif args.step == "image":
        credits = gen.IMAGE_RATES[QUALITY] * COUNT
        body = {"model": gen.IMAGE_MODEL, "promptText": sc["image"], "ratio": gen.IMAGE_RATIO,
                "quality": QUALITY, "background": "opaque", "outputCount": COUNT}
        path, dst, note = "/text_to_image", OUT / f"{args.scene}.png", {}
        print(f"静止画 {COUNT} 枚 / {gen.IMAGE_MODEL} {QUALITY} → 約 {credits} credits")
    else:
        src = OUT / f"{args.scene}__{args.pick}.png"
        if not src.exists():
            sys.exit(f"{src.name} がありません (先に image --run)")
        credits = gen.VIDEO_RATES[RES] * DURATION
        body = None
        path, dst, note = "/image_to_video", OUT / f"{args.scene}.mp4", {"promptImage": src.name}
        print(f"動画 {DURATION}s / {gen.VIDEO_MODEL} {RES} ← {src.name} → 約 {credits} credits")

    print(f"  (${credits / 100:.2f})  残高 {gen.request('GET', '/organization').get('creditBalance')} credits")
    if dst.exists() or (args.step == "image" and dst.with_name(f"{dst.stem}__1.png").exists()):
        sys.exit(f"生成済み: {dst.name} (作り直すなら消してから)")
    if not args.run:
        print("ドライラン。生成するには --run")
        return
    if args.step == "morph":
        body["promptImage"] = [{"uri": gen.image_uri(mo["first"]), "position": "first"},
                               {"uri": gen.image_uri(mo["last"]), "position": "last"}]
    if body is None:
        body = {"model": gen.VIDEO_MODEL, "promptImage": gen.image_uri(src), "promptText": sc["video"],
                "resolution": RES, "duration": DURATION}
    gen.submit(path, body, dst, note)


if __name__ == "__main__":
    main()
