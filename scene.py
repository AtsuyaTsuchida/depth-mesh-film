"""点群 → Blender シーン + カメラ移動 + レンダー。バックグラウンド実行用。

/Applications/Blender.app/Contents/MacOS/Blender -b -P scene.py -- <名> [--still] [--orbit 距離m]
出力: out/<名>.blend, out/<名>_frames/####.png
--still は確認用に数コマだけレンダーする。
--orbit は正面の距離 (m) にいる被写体のまわりを回る経路にする (人物向け)。最後は1コマ目に戻ってループする。
指定しなければ、奥へ前進する経路 (駅のような奥行きのある場面向け)。
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
name = argv[0]
still = "--still" in argv
orbit = float(argv[argv.index("--orbit") + 1]) if "--orbit" in argv else None
out = Path(__file__).parent / "out"
d = np.load(out / f"{name}_points.npz")
xyz, rgb, rad = d["xyz"], d["rgb"], d["rad"]
w, h, f, _ = d["meta"]

RES = 1080              # 正方形 (元ネタと同じ 1:1)
FRAMES = 180            # 30fps で 6 秒

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# --- 点群: 頂点だけのメッシュ + 色/半径の属性 → GN で点にする ---
me = bpy.data.meshes.new("cloud")
me.vertices.add(len(xyz))
me.vertices.foreach_set("co", xyz.ravel())
ca = me.color_attributes.new("col", "FLOAT_COLOR", "POINT")
ca.data.foreach_set("color", np.c_[rgb, np.ones(len(rgb), np.float32)].ravel())
ra = me.attributes.new("rad", "FLOAT", "POINT")
ra.data.foreach_set("value", rad)
ob = bpy.data.objects.new("cloud", me)
sc.collection.objects.link(ob)

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
mod = ob.modifiers.new("to_points", "NODES")
mod.node_group = gn

# --- 背景: 元ネタのような明るいグレー ---
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.82, 0.80, 1)
sc.world = world

# --- カメラ: 1コマ目は元写真と同じ位置・画角 (中央の正方形を切り出した見え方) ---
cd = bpy.data.cameras.new("cam")
cd.sensor_fit = "HORIZONTAL"
cd.angle = 2 * math.atan((h / 2) / f)
cd.clip_start = 0.05
cd.clip_end = 500
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.rotation_mode = "XYZ"

def key(fr, loc, rot):
    cam.location = loc
    cam.rotation_euler = [math.radians(a) for a in rot]
    cam.keyframe_insert("location", frame=fr)
    cam.keyframe_insert("rotation_euler", frame=fr)

def orbit_key(fr, ang, r, z=0.0, pitch=90):
    # 被写体 (0, orbit, 0) を中心に、正面から ang 度回った位置から被写体を向く
    a = math.radians(ang)
    key(fr, (r * math.sin(a), orbit - r * math.cos(a), z), (pitch, 0, ang))


if orbit:
    orbit_key(1, 0, orbit)                      # 元写真そのまま
    orbit_key(20, 0, orbit)
    orbit_key(70, 38, orbit * 0.7, 0.4, 88)     # 寄りながら右へ回り、人物の厚みと背景との隙間を見せる
    orbit_key(125, -32, orbit * 0.6, -0.3, 92)  # 反対側へ回って下から見上げる
    orbit_key(165, 0, orbit)                    # 写真の視点へ戻って止まる
    orbit_key(FRAMES + 1, 0, orbit)
else:
    key(1,   (0, 0, 0),          (90, 0, 0))     # 元写真そのまま
    key(24,  (0, 0, 0),          (90, 0, 0))
    key(100, (-0.5, 6, 0.2),     (89, 0, -22))   # ホームを前進しつつ右の電車側へ振る
    key(150, (1.2, 9, 0.8),      (86, 0, 25))    # 柱の方へ振り返す
    key(FRAMES, (3, 7, 2.5),     (78, 0, 48))    # 横へ抜けて点群の裂け目を見せる
for fc in cam.animation_data.action.fcurves:
    for kp in fc.keyframe_points:
        kp.interpolation = "BEZIER"
        kp.easing = "AUTO"

# --- レンダー ---
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
sc.view_settings.view_transform = "Standard"   # 写真の色をそのまま出す
sc.render.image_settings.file_format = "PNG"
frames_dir = out / f"{name}_frames"
frames_dir.mkdir(exist_ok=True)
sc.render.filepath = str(frames_dir / "####")

bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{name}.blend"))

if still:
    for fr in (1, 70, 125, FRAMES):
        sc.frame_set(fr)
        sc.render.filepath = str(frames_dir / f"still_{fr:04d}")
        bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
