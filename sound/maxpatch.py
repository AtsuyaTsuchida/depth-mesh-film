"""Write Max patches (.maxpat) as JSON. The same Patch class as the author's ikeda-max/build.py."""


class Patch:
    def __init__(self):
        self.boxes, self.lines, self.n = [], [], 0

    def box(self, maxclass="newobj", txt=None, ins=1, outs=0, outtype=None, rect=(0, 0, 80, 22),
            pres=None, **kw):
        self.n += 1
        bid = "obj-%d" % self.n
        b = {"id": bid, "maxclass": maxclass, "numinlets": ins, "numoutlets": outs,
             "patching_rect": list(rect)}
        if outs:
            b["outlettype"] = outtype or [""] * outs
        if txt is not None:
            b["text"] = txt
        if pres:
            b["presentation"] = 1
            b["presentation_rect"] = list(pres)
        b.update(kw)
        self.boxes.append({"box": b})
        return bid

    def obj(self, text, ins, outs, x, y, w=None, outtype=None, **kw):
        return self.box("newobj", text, ins, outs, outtype, (x, y, w or max(40, 7 * len(text)), 22), **kw)

    def msg(self, text, x, y, w=None):
        return self.box("message", text, 2, 1, [""], (x, y, w or max(30, 7 * len(text)), 22))

    def wire(self, a, ao, b, bi):
        self.lines.append({"patchline": {"source": [a, ao], "destination": [b, bi]}})

    def patcher(self, **extra):
        p = {"fileversion": 1,
             "appversion": {"major": 8, "minor": 6, "revision": 5, "architecture": "x64", "modernui": 1},
             "classnamespace": "box", "rect": [60, 60, 1100, 720], "bglocked": 0,
             "openinpresentation": 0, "default_fontsize": 12.0, "default_fontface": 0,
             "default_fontname": "Arial", "gridonopen": 1, "gridsize": [15.0, 15.0],
             "gridsnaponopen": 1, "objectsnaponopen": 1, "statusbarvisible": 2, "toolbarvisible": 1,
             "boxes": self.boxes, "lines": self.lines}
        p.update(extra)
        return {"patcher": p}
