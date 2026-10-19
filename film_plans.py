"""Layout of each film (shared by film_edit.py and film_composite.py).

segs   segments shot by film_scene.py, in order
trans  transition after each segment (the last one goes back to the first: the loop)
         T1 = block dissolve (N1 frames), T2 = box reveal (cut; done by film_composite), T5 = stretched-pixel smear (N5 frames)
         TX = plain crossfade (NX frames). For joins where the two sides are nearly the same picture (into and out of a morph)
labels scene name per segment by local frame [(from local frame, name), ...] (used for the composite's ghost and beats)
beats  frames where the person's yellow box with green silhouette flashes: [(scene name, frames from that scene's first frame, length)]
flash  full-frame normal-map flash: (scene name, frames from that scene's first frame, length) or None
"""

PLANS = {
    # v2: morph from person to person (Runway's first/last-frame clips). TX = 6-frame crossfade at the joins
    "people": {
        "segs": ["walker2", "m_wg", "greenhouse2", "m_gr", "runner2", "m_rw"],
        "trans": ["TX", "TX", "TX", "TX", "TX", "TX"],
        "labels": {"walker2": [(1, "walker")], "m_wg": [(1, "morph")], "greenhouse2": [(1, "greenhouse")],
                   "m_gr": [(1, "morph")], "runner2": [(1, "runner")], "m_rw": [(1, "morph")]},
        "beats": [("walker", 40, 5), ("greenhouse", 45, 5)],   # the runner's mid-orbit mask was patchy, so it was dropped
        "flash": ("greenhouse", 75, 3),
    },
    # v1: block dissolve / box reveal / smear (out/film/tread_people.mp4)
    "people_v1": {
        "segs": ["walker", "greenhouse", "runner_solo"],
        "trans": ["T1", "T2", "T5"],
        "labels": {"walker": [(1, "walker")], "greenhouse": [(1, "greenhouse")], "runner_solo": [(1, "runner")]},
        "beats": [("walker", 52, 6), ("greenhouse", 66, 6), ("runner", 70, 5)],
        "flash": ("greenhouse", 104, 3),
    },
    # v2: morph from space to space (Runway's first/last-frame clips)
    "arch": {
        "segs": ["plat3", "ma_pg", "gates3", "ma_gc", "corr3", "ma_ce", "esc3", "ma_er", "rev3", "ma_rp"],
        "trans": ["TX"] * 10,
        "labels": {"plat3": [(1, "platform")], "gates3": [(1, "gates")], "corr3": [(1, "corridor")],
                   "esc3": [(1, "escalator")], "rev3": [(1, "revolving")],
                   "ma_pg": [(1, "morph")], "ma_gc": [(1, "morph")], "ma_ce": [(1, "morph")],
                   "ma_er": [(1, "morph")], "ma_rp": [(1, "morph")]},
        "beats": [],
        "flash": ("corridor", 30, 3),
    },
    # v1: 3D punch-through + box reveal + smear (out/film/tread_arch.mp4)
    "arch_v1": {
        "segs": ["arch1", "arch2"],
        "trans": ["T2", "T5"],
        # film_scene.py arch1 keys: gates photo at 130, corridor at 236, escalator at 362
        "labels": {"arch1": [(1, "platform"), (122, "gates"), (228, "corridor"), (354, "escalator")],
                   "arch2": [(1, "revolving")]},
        "beats": [],
        "flash": ("corridor", 50, 3),
    },
}
