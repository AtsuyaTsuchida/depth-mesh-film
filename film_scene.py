"""Shoot one segment of the final film in Blender as a "texture-mapped depth mesh". Runs in the background.

/Applications/Blender.app/Contents/MacOS/Blender -b -P film_scene.py -- <segment> [--still]
Output: out/film/seg_<segment>/####.png (1280x1280, 30fps), out/film/seg_<segment>.blend

Unlike the dots in scene*.py, this is a grid mesh with the photo mapped onto it:
- Where neighbouring vertices jump sharply in depth, the face is torn (the threshold varies by face, so the edges break up raggedly)
- The outline is cut by mask.png from film_prep.py into an irregular, ragged blob
- Video scenes have their vertices, tears and texture swapped every frame (source fps → 30fps)
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
seg = argv[0]
still = "--still" in argv
ROOT = Path(__file__).parent / "out" / "film"
RES, FPS = 1280, 30
TEAR = 0.10            # tear a face when depth inside it changes by more than this ratio (×0.6–1.6 per face)

LIGHT = (0.78, 0.77, 0.74)      # warm light grey (linear). Reference background
SLATE = (0.035, 0.040, 0.046)   # dark slate for the plant scene

# Scenes: (name, photo camera position, yaw[, smear]). Camera keys: (frame, position, yaw, pitch=90 is level[, roll])
# yaw is positive to the left (toward -X). When the camera moves off to one side, face it back toward the centre of the space
# (from x<0 a negative yaw, from x>0 a positive yaw). Facing outward leaves the frame empty
# smear: how far the untorn layer behind may stretch to fill the gaps. None = unlimited (fills every gap),
#   0 = no smear layer (gaps stay open), a number = faces whose depth ratio exceeds this stay open
def orb(fr, d, ang, r=1.0, z=0.0, pitch=90, roll=0):
    """Camera key orbiting the subject at d metres in front: ang degrees round, distance d*r, height z, facing the subject"""
    a = math.radians(ang)
    return (fr, (d * r * math.sin(a), d - d * r * math.cos(a), z), ang, pitch, roll)


P0 = (0, 0, 0)   # photo viewpoint

SEGMENTS = {
    "walker": {
        "frames": 155, "bg": LIGHT,
        "scenes": [("walker", (0, 0, 0), 0)],
        "orbit": 2.7,
        "keys": [(1, 8, 1.0, 0.05, 90), (80, 0, 1.0, 0.05, 90), (155, -7, 1.0, 0.0, 90)],   # pulling back brings the image top edge into frame and cuts off her head, so orbit only
    },
    "greenhouse": {
        "frames": 155, "bg": SLATE,
        "scenes": [("greenhouse", (0, 0, 0), 0)],
        "orbit": 3.5,
        "keys": [(1, -12, 1.0, -0.2, 92), (80, -2, 0.92, 0.0, 90.5), (155, 10, 0.85, 0.2, 89)],
    },
    "journey": {
        "frames": 270, "bg": LIGHT,
        # runner at the origin. The platform starts just behind its backdrop (~6.4m), the gates beyond the platform's far end
        # the runner needs the hole to fly through, so no smear. With smear on the platform, its far end became a grey wall, so none there either
        "scenes": [("runner", (0, 0, 0), 0, 0), ("platform", (0, 7.5, 0), 0, 0), ("gates", (0, 71.5, 0), 0, 0.8)],
        "pos_keys": [   # transitions about 0.5 s like the reference (any longer and the tearing alone drags)
            (1,   (0.2, -1.2, 0.0),   -3,  90),   # pulled back from the runner's photo view so all of her fits in the square
            (34,  (1.6, 1.3, 0.3),    28,  89),   # orbit right; the platform shows through the hole she left in the backdrop
            (62,  (1.4, 5.0, 0.2),    41,  90),   # behind the runner, facing the hole
            (78,  (0.2, 6.2, 0.1),    5,   90),   # into the hole
            (92,  (0, 7.5, 0),        0,   90),   # match the platform photo
            (104, (0, 7.6, 0),        0,   90),
            (170, (0.5, 30, 0.3),     -8,  89),   # down the platform
            (205, (0, 58, 0),         0,   90),   # punch through the far end
            (226, (0, 71.1, 0),       0,   90),   # match the gates photo
            (246, (0, 71.5, 0),       0,   90),
            (270, (0, 73.2, 0.2),     -6,  89),   # keep pushing into the next transition
        ],
    },
    # ---- people film (film_plans.py "people") ----
    "runner_solo": {
        "frames": 150, "bg": LIGHT,
        "scenes": [("runner", (0, 0, 0), 0, 0)],      # no smear: the tears read like ripped paper
        "pos_keys": [   # orbit around the runner (pivot 0, 4.3, 0)
            (1,   (0.2, -1.2, 0.0),   -3,  90),   # pulled back from the photo view so all of her fits in the square
            (60,  (1.6, 1.3, 0.3),    28,  89),   # round to the right; the hole she left in the backdrop shows
            (110, (-1.2, 1.33, -0.2), -22, 92),   # round to the left, looking slightly up
            (150, (0.1, -0.8, 0.0),   -2,  90),   # back to the photo view
        ],
    },
    # ---- architecture film (film_plans.py "arch") ----
    # all one-point perspective. Each next scene sits 64 m beyond the previous one (just past its far end,
    # about 60 m), so the camera punches through the far end straight into the next photo view. No smear (it closes the far end)
    "arch1": {
        "frames": 410, "bg": LIGHT,
        "scenes": [("platform", (0, 0, 0), 0, 0), ("gates", (0, 64, 0), 0, 0),
                   ("corridor", (0, 128, 0), 0, 0), ("escalator", (0, 192, 0), 0, 0)],
        "pos_keys": [   # if you change these, also update arch1's labels in film_plans.py
            (1,   (0, 0, 0),          0,   90),   # platform photo
            (14,  (0, 0.1, 0),        0,   90),
            (80,  (0.5, 22, 0.3),     -8,  89),   # down the platform
            (110, (0, 50, 0),         0,   90),   # punch through the far end
            (130, (0, 63.6, 0),       0,   90),   # gates photo
            (146, (0, 64, 0),         0,   90),
            (190, (0.3, 90, 0.4),     -5,  89),   # through the gates
            (215, (0, 118, 0),        0,   90),   # punch through the far windows
            (236, (0, 127.6, 0),      0,   90),   # corridor photo
            (252, (0, 128, 0),        0,   90),
            (310, (-0.3, 160, 0.2),   6,   90),   # down the corridor
            (340, (0, 183, 0),        0,   90),   # punch through the far end
            (362, (0, 191.6, 0),      0,   90),   # escalator photo (its centre divider is close, so the box reveal goes to the next one)
            (380, (0, 192, 0),        0,   90),
            (410, (0, 193.5, 0.8),    0,   84),   # rise up the escalator a little, looking up
        ],
    },
    # ---- people film v2 (film_plans.py "people"): scene → morph → scene ... ----
    # Every segment starts and ends at the photo viewpoint (position 0, facing forward, level). There the depth
    # mesh looks the same as the photo, so even with each scene's depth normalised differently the joins can't be seen
    # (Runway's morph clips start on the previous scene's last frame and end on the next scene's first frame)
    "walker2": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("walker", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), orb(35, 2.7, 35, 0.9, 0.6, 84), orb(70, 2.7, -30, 0.8, -0.3, 93), (100, P0, 0, 90)],   # big orbit (bold camera)
    },
    "m_wg": {
        "frames": 120, "fit": True, "bg": LIGHT, "bg2": SLATE,
        "scenes": [("m_wg", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (60, (0.45, -0.9, 0.15), -6, 90), (120, (0, 0, 0), 0, 90)],
    },
    "greenhouse2": {
        "frames": 100, "fit": True, "bg": SLATE,
        "scenes": [("greenhouse", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), orb(35, 3.5, -38, 0.85, 0.8, 84), orb(70, 3.5, 30, 0.8, -0.2, 92), (100, P0, 0, 90)],
    },
    "m_gr": {
        "frames": 120, "fit": True, "bg": SLATE, "bg2": LIGHT,
        "scenes": [("m_gr", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (60, (-0.45, -0.9, 0.15), 6, 90), (120, (0, 0, 0), 0, 90)],
    },
    "runner2": {
        "frames": 100, "bg": LIGHT,
        "scenes": [("runner", (0, 0, 0), 0, 0)],
        "pos_keys": [(1, P0, 0, 90), orb(35, 4.3, 45, 0.75, 0.5, 87), orb(70, 4.3, -35, 0.7, -0.4, 93), (100, P0, 0, 90)],
    },
    "m_rw": {
        "frames": 120, "fit": True, "bg": LIGHT,
        "scenes": [("m_rw", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (60, (0.4, -0.9, 0.1), -5, 90), (120, (0, 0, 0), 0, 90)],
    },
    # ---- architecture film v2 (film_plans.py "arch"): space → morph → space ... ----
    # As in the people film, every segment starts and ends at the photo viewpoint (joins can't be seen). Stills push in and come back
    "plat3": {
        "frames": 80, "bg": LIGHT,
        "scenes": [("platform", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), (28, (-2.0, 14, 1.6), -18, 84), (55, (2.2, 8, 0.6), 20, 92), (80, P0, 0, 90)],   # big curve deep in, rising and coming back
    },
    "gates3": {
        "frames": 80, "bg": LIGHT,
        "scenes": [("gates", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), (28, (3, 10, 2.5), 18, 78), (55, (-3.5, 6, 0.4), -20, 93), (80, P0, 0, 90)],
    },
    "corr3": {
        "frames": 80, "bg": LIGHT,
        "scenes": [("corridor", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), (28, (0, 18, 0), 0, 90, 60), (55, (0.6, 9, 0.3), 8, 90, -15), (80, P0, 0, 90)],   # roll the frame while moving
    },
    "esc3": {
        "frames": 80, "bg": LIGHT,
        "scenes": [("escalator", (0, 0, 0), 0)],
        "pos_keys": [(1, P0, 0, 90), (28, (0, 1.5, 2.2), 0, 70), (55, (1.2, 2.0, 0.5), 15, 95), (80, P0, 0, 90)],   # crane up to look down
    },
    "rev3": {
        "frames": 80, "bg": LIGHT,
        "scenes": [("revolving", (0, 0, 0), 0, 0.6)],   # with no smear limit, the glass and metal smeared like liquid
        "pos_keys": [(1, P0, 0, 90), (28, (-1.8, 3, 0.3), -15, 90), (55, (1.6, 3.5, 1.0), 15, 86), (80, P0, 0, 90)],   # sweep across the lobby
    },
    "ma_pg": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("ma_pg", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (50, (0.3, -0.7, 0.1), -4, 90), (100, (0, 0, 0), 0, 90)],
    },
    "ma_gc": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("ma_gc", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (50, (0.3, -0.7, 0.1), -4, 90), (100, (0, 0, 0), 0, 90)],
    },
    "ma_ce": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("ma_ce", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (50, (0.3, -0.7, 0.1), -4, 90), (100, (0, 0, 0), 0, 90)],
    },
    "ma_er": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("ma_er", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (50, (0.3, -0.7, 0.1), -4, 90), (100, (0, 0, 0), 0, 90)],
    },
    "ma_rp": {
        "frames": 100, "fit": True, "bg": LIGHT,
        "scenes": [("ma_rp", (0, 0, 0), 0)],
        "pos_keys": [(1, (0, 0, 0), 0, 90), (50, (0.3, -0.7, 0.1), -4, 90), (100, (0, 0, 0), 0, 90)],
    },
    "arch2": {
        "frames": 110, "bg": LIGHT,
        "scenes": [("revolving", (0, 0, 0), 0)],      # no punch-through needed here, so let the smear fill gaps freely
        "pos_keys": [
            (1,   (0.3, -0.5, 0),     -3,  90),
            (110, (0, 4, 0.15),       2,   90),   # push toward the revolving doors (pushing all the way in distorts it too much)
        ],
    },
}
cfg = SEGMENTS[seg]
FRAMES = cfg["frames"]

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene


def build(name, loc, yaw, smear=None):
    d = ROOT / name
    meta = json.loads((d / "meta.json").read_text())
    gw, gh, w, h, f = meta["gw"], meta["gh"], meta["w"], meta["h"], meta["f"]
    nq = (gw - 1) * (gh - 1)
    me = bpy.data.meshes.new(name)
    me.vertices.add(gw * gh)
    me.loops.add(nq * 4)
    me.polygons.add(nq)
    j, i = np.mgrid[0:gh - 1, 0:gw - 1]
    v00 = (j * gw + i).ravel()
    quads = np.stack([v00, v00 + 1, v00 + gw + 1, v00 + gw], 1)
    me.loops.foreach_set("vertex_index", quads.ravel().astype(np.int32))
    me.polygons.foreach_set("loop_start", (np.arange(nq) * 4).astype(np.int32))
    me.polygons.foreach_set("loop_total", np.full(nq, 4, np.int32))
    # UV: grid vertex → pixel centre (v flipped)
    gu = (np.arange(gw) + 0.5) / gw
    gv = 1 - (np.arange(gh) + 0.5) / gh
    uvv = np.stack(np.meshgrid(gu, gv), -1).reshape(-1, 2)
    me.uv_layers.new(name="uv").data.foreach_set("uv", uvv[quads.ravel()].ravel().astype(np.float32))
    me.attributes.new("keep", "FLOAT", "FACE")
    me.attributes.new("keep_s", "FLOAT", "FACE")
    me.update()

    # pixel position of each grid vertex (for back-projection)
    px = ((np.arange(gw) + 0.5) * w / gw - w / 2) / f
    py = -((np.arange(gh) + 0.5) * h / gh - h / 2) / f
    PX, PY = np.meshgrid(px, py)
    thr = TEAR * (0.6 + np.random.default_rng(len(name)).random(nq))

    imgs = {}

    def tex(k):
        if k not in imgs:
            imgs[k] = bpy.data.images.load(str(d / "rgb" / f"{k:04d}.png"), check_existing=True)
        return imgs[k]

    nodes = {}

    def make_mat(mname, attr):
        mat = bpy.data.materials.new(mname)
        mat.use_nodes = True
        mat.surface_render_method = "DITHERED"
        mat.use_backface_culling = False
        nt = mat.node_tree
        nt.nodes.clear()
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = "uv"
        it = nt.nodes.new("ShaderNodeTexImage")
        it.interpolation = "Cubic"
        it.extension = "EXTEND"
        it.image = tex(1)
        mk = nt.nodes.new("ShaderNodeTexImage")
        mk.image = mask_img
        kp = nt.nodes.new("ShaderNodeAttribute")
        kp.attribute_type = "GEOMETRY"
        kp.attribute_name = attr or "keep"
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = 1.0
        gt = nt.nodes.new("ShaderNodeMath")
        gt.operation = "GREATER_THAN"
        gt.inputs[1].default_value = 0.5
        em = nt.nodes.new("ShaderNodeEmission")
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        L = nt.links.new
        L(uv.outputs["UV"], it.inputs["Vector"])
        L(uv.outputs["UV"], mk.inputs["Vector"])
        L(it.outputs["Color"], em.inputs["Color"])
        L(mk.outputs["Color"], mul.inputs[0])
        if attr:
            L(kp.outputs["Fac"], mul.inputs[1])
        L(mul.outputs["Value"], gt.inputs[0])
        L(gt.outputs["Value"], mix.inputs["Fac"])
        L(tr.outputs[0], mix.inputs[1])
        L(em.outputs[0], mix.inputs[2])
        L(mix.outputs[0], out.inputs["Surface"])
        nodes.setdefault("tex", []).append(it)
        return mat

    mask_img = bpy.data.images.load(str(d / "mask.png"))
    mask_img.colorspace_settings.name = "Non-Color"
    me.materials.append(make_mat(name, "keep"))

    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = (0, 0, math.radians(yaw))
    sc.collection.objects.link(ob)
    # smear layer: an untorn copy of the same mesh, pushed 0.4% back. The torn gaps fill with
    # stretched pixels instead of bare background (the reference's long streaks)
    if smear != 0:
        sm_ob = bpy.data.objects.new(name + "_smear", me)
        sm_ob.location = loc
        sm_ob.rotation_euler = (0, 0, math.radians(yaw))
        sm_ob.scale = (1.004, 1.004, 1.004)
        sc.collection.objects.link(sm_ob)
        sm_ob.material_slots[0].link = "OBJECT"
        sm_ob.material_slots[0].material = make_mat(name + "_smear", "keep_s" if smear else None)

    state = {"k": None}

    def load(k):
        k = min(max(k, 1), meta["frames"])
        if state["k"] == k:
            return
        state["k"] = k
        z = np.load(d / "z" / f"{k:04d}.npy")
        co = np.stack([PX * z, z, PY * z], -1).reshape(-1, 3).astype(np.float32)
        me.vertices.foreach_set("co", co.ravel())
        zq = np.stack([z[:-1, :-1], z[:-1, 1:], z[1:, 1:], z[1:, :-1]], -1).reshape(-1, 4)
        ratio = zq.max(1) / zq.min(1) - 1
        me.attributes["keep"].data.foreach_set("value", (ratio < thr).astype(np.float32))
        if smear:
            me.attributes["keep_s"].data.foreach_set("value", (ratio < smear).astype(np.float32))
        for t in nodes["tex"]:
            t.image = tex(k)
        me.update()

    def at_frame(fr):
        if meta["frames"] > 1 and cfg.get("fit"):
            # play the video across the whole segment (when shortened, it plays slightly faster; first and last frames always match)
            load(round((fr - 1) * (meta["frames"] - 1) / max(FRAMES - 1, 1)) + 1)
        elif meta["frames"] > 1:
            load(int((fr - 1) * meta["fps"] / FPS) + 1)
        else:
            load(1)

    at_frame(1)
    return at_frame, meta


updaters = []
meta0 = None
for name, loc, yaw, *opt in cfg["scenes"]:
    upd, m = build(name, loc, yaw, *opt)
    updaters.append(upd)
    meta0 = meta0 or m


def on_frame(scene, *_):
    for u in updaters:
        u(scene.frame_current)


bpy.app.handlers.frame_change_pre.append(on_frame)

world = bpy.data.worlds.new("w")
world.use_nodes = True
bgc = world.node_tree.nodes["Background"].inputs["Color"]
bgc.default_value = (*cfg["bg"], 1)
if "bg2" in cfg:     # in a morph, the background colour moves to the next scene's
    bgc.keyframe_insert("default_value", frame=1)
    bgc.default_value = (*cfg["bg2"], 1)
    bgc.keyframe_insert("default_value", frame=FRAMES)
sc.world = world

cd = bpy.data.cameras.new("cam")
cd.sensor_fit = "HORIZONTAL"
cd.angle = 2 * math.atan((meta0["h"] / 2) / meta0["f"])
cd.clip_start = 0.03
cd.clip_end = 500
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.rotation_mode = "XYZ"


def key(fr, loc, yaw, pitch, roll=0):
    cam.location = loc
    cam.rotation_euler = (math.radians(pitch), math.radians(roll), math.radians(yaw))   # Y is roll about the view axis
    cam.keyframe_insert("location", frame=fr)
    cam.keyframe_insert("rotation_euler", frame=fr)


if "orbit" in cfg:
    dist = cfg["orbit"]
    for fr, ang, rr, zz, pitch in cfg["keys"]:
        a = math.radians(ang)
        key(fr, (dist * rr * math.sin(a), dist - dist * rr * math.cos(a), zz), ang, pitch)
else:
    for fr, loc, yaw, pitch, *roll in cfg["pos_keys"]:
        key(fr, loc, yaw, pitch, *roll)
for fc in cam.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "BEZIER"
        kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"

sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = 32
sc.render.filter_size = 1.2
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, FRAMES
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
outdir = ROOT / f"seg_{seg}"
outdir.mkdir(exist_ok=True)
sc.render.filepath = str(outdir / "####")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / f"seg_{seg}.blend"))

if still:
    for fr in range(1, FRAMES + 1, max(1, FRAMES // 10)):
        sc.frame_set(fr)
        sc.render.filepath = str(outdir / f"still_{fr:04d}")
        bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
