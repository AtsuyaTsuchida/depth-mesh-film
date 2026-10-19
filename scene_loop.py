"""複数の点群を1つの空間に置き、写真の視点→次の写真の視点→最初へ戻るループを撮る。

/Applications/Blender.app/Contents/MacOS/Blender -b -P scene_loop.py -- <出力名> [--still]
出力: out/<出力名>.blend, out/<出力名>_frames/####.png

配置: platform は原点で +Y 向き。gates はホームの突き当たり (奥行き約60m) のすぐ先に、同じ向きで置く。
カメラの経路:
  platform の写真 → ホームを進んで突き当たりの点群を突き抜ける → gates の写真にぴたりと合う
  → 改札の奥へ → 上へ上がって見下ろしながら2つの点群の上を後ろへ戻る
  → platform の写真の視点 (視錐台の頂点) へ上から降りて最初のコマに戻る
1コマ目と FRAMES+1 コマ目は同じ姿勢。前後で止まるので継ぎ目が見えない。
横に置くと移動中に何もない背景しか映らない区間が長くなるので、縦に並べている。
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
outname = argv[0]
still = "--still" in argv
out = Path(__file__).parent / "out"

RES = 1080
FRAMES = 300            # 30fps で 10 秒。FRAMES+1 は 1 と同じ絵

# (点群名, 写真のカメラ位置, 向き(度, +Y から反時計回り))
SCENES = [
    ("platform", (0, 0, 0), 0),
    ("gates", (0, 64, 0), 0),
]

# (コマ, 位置, 向き yaw, 俯角 pitch=90 が水平)
PATH = [
    (1,   (0, 0, 0),          0,   90),   # platform の写真
    (14,  (0, 0, 0),          0,   90),
    (90,  (0.5, 30, 0.3),     -8,  89),   # ホームを進む
    (125, (0, 58, 0),         0,   90),   # 突き当たりを突き抜ける
    (150, (0, 63.6, 0),       0,   90),   # gates の写真に合う
    (166, (0, 64, 0),         0,   90),
    (205, (2, 76, 0.6),       -15, 88),   # 改札の奥へ
    (235, (1, 74, 9),         0,   40),   # 上へ上がって見下ろす (高すぎると点群が小さくなり余白ばかりになる)
    (262, (0, 30, 9),         0,   40),   # ホームの上を後ろへ戻る
    (280, (0, -4, 2.5),       0,   80),   # 写真の視点の後ろへ降りる
    (292, (0, 0, 0),          0,   90),   # 写真の視点で止まる
    (FRAMES + 1, (0, 0, 0),   0,   90),
]

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

mat = bpy.data.materials.new("cloud")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
at = nt.nodes.new("ShaderNodeAttribute")
at.attribute_name = "col"
em = nt.nodes.new("ShaderNodeEmission")
mo = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(at.outputs["Color"], em.inputs["Color"])
nt.links.new(em.outputs["Emission"], mo.inputs["Surface"])

gn = bpy.data.node_groups.new("to_points", "GeometryNodeTree")
gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
gi = gn.nodes.new("NodeGroupInput")
go = gn.nodes.new("NodeGroupOutput")
m2p = gn.nodes.new("GeometryNodeMeshToPoints")
na = gn.nodes.new("GeometryNodeInputNamedAttribute")
na.data_type = "FLOAT"
na.inputs["Name"].default_value = "rad"
sm = gn.nodes.new("GeometryNodeSetMaterial")
sm.inputs["Material"].default_value = mat
gn.links.new(gi.outputs[0], m2p.inputs["Mesh"])
gn.links.new(na.outputs["Attribute"], m2p.inputs["Radius"])
gn.links.new(m2p.outputs["Points"], sm.inputs["Geometry"])
gn.links.new(sm.outputs["Geometry"], go.inputs[0])

meta = None
for name, loc, yaw in SCENES:
    d = np.load(out / f"{name}_points.npz")
    xyz, rgb, rad = d["xyz"], d["rgb"], d["rad"]
    meta = meta if meta is not None else d["meta"]
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(xyz))
    me.vertices.foreach_set("co", xyz.ravel())
    ca = me.color_attributes.new("col", "FLOAT_COLOR", "POINT")
    ca.data.foreach_set("color", np.c_[rgb, np.ones(len(rgb), np.float32)].ravel())
    ra = me.attributes.new("rad", "FLOAT", "POINT")
    ra.data.foreach_set("value", rad)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = (0, 0, math.radians(yaw))
    sc.collection.objects.link(ob)
    ob.modifiers.new("to_points", "NODES").node_group = gn

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.82, 0.80, 1)
sc.world = world

w, h, f, _ = meta
cd = bpy.data.cameras.new("cam")
cd.sensor_fit = "HORIZONTAL"
cd.angle = 2 * math.atan((h / 2) / f)
cd.clip_start = 0.05
cd.clip_end = 500
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.rotation_mode = "XYZ"
for fr, loc, yaw, pitch in PATH:
    cam.location = loc
    cam.rotation_euler = (math.radians(pitch), 0, math.radians(yaw))
    cam.keyframe_insert("location", frame=fr)
    cam.keyframe_insert("rotation_euler", frame=fr)
for fc in cam.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "BEZIER"
        kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"

for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng
        break
    except TypeError:
        pass
sc.eevee.taa_render_samples = 16
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.fps = 30
sc.frame_start, sc.frame_end = 1, FRAMES
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
frames_dir = out / f"{outname}_frames"
frames_dir.mkdir(exist_ok=True)
sc.render.filepath = str(frames_dir / "####")

bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{outname}.blend"))

if still:
    for fr in range(1, FRAMES + 2, 15):
        sc.frame_set(fr)
        sc.render.filepath = str(frames_dir / f"still_{fr:04d}")
        bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
