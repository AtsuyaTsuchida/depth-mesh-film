"""動く点群 (video_points.py の出力) を Blender で撮る。コマごとに頂点を差し替える。

/Applications/Blender.app/Contents/MacOS/Blender -b -P scene_video.py -- <名> <被写体までの距離m> [--still]
出力: out/<名>.blend, out/<名>_frames/####.png  (元動画と同じコマ数・fps)

カメラは元動画のカメラ位置から始まり、歩いてくる人物のまわりを回る。
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
name, dist = argv[0], float(argv[1])
still = "--still" in argv
out = Path(__file__).parent / "out"
files = sorted((out / f"{name}_vpts").glob("*.npz"))
FRAMES = len(files)
FPS = 24
RES = 1080

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

d0 = np.load(files[0])
n = len(d0["xyz"])
me = bpy.data.meshes.new(name)
me.vertices.add(n)
me.color_attributes.new("col", "FLOAT_COLOR", "POINT")
me.attributes.new("rad", "FLOAT", "POINT")
ob = bpy.data.objects.new(name, me)
sc.collection.objects.link(ob)


def load_frame(i):
    d = np.load(files[min(max(i, 1), FRAMES) - 1])
    me.vertices.foreach_set("co", d["xyz"].ravel())
    me.color_attributes["col"].data.foreach_set("color", np.c_[d["rgb"], np.ones(n, np.float32)].ravel())
    me.attributes["rad"].data.foreach_set("value", d["rad"])
    me.update()


def on_frame(scene, *_):
    load_frame(scene.frame_current)


load_frame(1)
bpy.app.handlers.frame_change_pre.append(on_frame)

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
ob.modifiers.new("to_points", "NODES").node_group = gn

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.82, 0.82, 0.80, 1)
sc.world = world

w, h, f, _ = d0["meta"]
cd = bpy.data.cameras.new("cam")
cd.sensor_fit = "HORIZONTAL"
cd.angle = 2 * math.atan((h / 2) / f)
cd.clip_start = 0.05
cd.clip_end = 500
cam = bpy.data.objects.new("cam", cd)
sc.collection.objects.link(cam)
sc.camera = cam
cam.rotation_mode = "XYZ"


def orbit_key(fr, ang, r, z=0.0, pitch=90):
    # 被写体 (0, dist, 0) を中心に、正面から ang 度回った位置から被写体を向く
    a = math.radians(ang)
    cam.location = (r * math.sin(a), dist - r * math.cos(a), z)
    cam.rotation_euler = (math.radians(pitch), 0, math.radians(ang))
    cam.keyframe_insert("location", frame=fr)
    cam.keyframe_insert("rotation_euler", frame=fr)


orbit_key(1, 0, dist)                         # 元動画のカメラ
orbit_key(14, 0, dist)
# 回りすぎると人物の後ろの抜け (白い空白) ばかりになるので ±22° 程度に抑える
orbit_key(60, 22, dist * 0.9, 0.3, 89)        # 右へ回って人物の厚みと後ろの裂け目を見せる
orbit_key(100, -18, dist * 0.9, 0.8, 87)      # 反対側へ回りつつ少し上から
orbit_key(FRAMES, -6, dist, 0.3, 89)
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
sc.render.fps = FPS
sc.frame_start, sc.frame_end = 1, FRAMES
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
frames_dir = out / f"{name}_frames"
frames_dir.mkdir(exist_ok=True)
sc.render.filepath = str(frames_dir / "####")

bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{name}.blend"))

if still:
    for fr in (1, 40, 60, 100, FRAMES):
        sc.frame_set(fr)
        sc.render.filepath = str(frames_dir / f"still_{fr:04d}")
        bpy.ops.render.render(write_still=True)
else:
    bpy.ops.render.render(animation=True)
