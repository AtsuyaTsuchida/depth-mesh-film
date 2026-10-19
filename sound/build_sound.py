#!/usr/bin/env python3
"""映像ごとの Max 8 レンダー用パッチを書く (パッチの JSON を書くだけで、音は作らない)。

  /usr/bin/python3 build_sound.py <名> <fps> <コマ数>   → render_<名>.maxpat

パッチを開くと、gen~ (scan.genexpr) が coll の楽譜 (<名>.txt) をコマごとに読みながら鳴り、
<名>.wav に実時間で書き出して Max を終了する (dac~ が無いので何も聞こえない)。
状態は udp 7400 に送る (listen.py で受ける)。Patch クラスは maxpatch.py。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from maxpatch import Patch  # noqa: E402

CODE = open(os.path.join(HERE, "scan.genexpr")).read()
FIELDS = ["trig", "nnew", "pan", "freq", "ntr", "motion", "edge", "hold"]
TYPES = "i i f f i f i i"


def gen_box(P, x, y):
    G = Patch()
    cb = G.box("codebox", None, 1, 4, [""] * 4, (20, 60, 900, 700),
               code=CODE, fontface=0, fontname="<Monospaced>", fontsize=12.0)
    G.wire(G.obj("in 1", 0, 1, 20, 20), 0, cb, 0)
    for i in range(4):
        G.wire(cb, i, G.obj("out %d" % (i + 1), 1, 0, 20 + 80 * i, 790), 0)
    gp = G.patcher()["patcher"]
    gp["classnamespace"] = "dsp.gen"
    gid = P.box("newobj", "gen~", 1, 4, ["signal"] * 4, (x, y, 260, 22))
    P.boxes[-1]["box"]["patcher"] = gp
    return gid


def mac(path):
    return "Macintosh HD:%s" % path


def render_patch(name, fps, nframes):
    wav = os.path.join(HERE, f"{name}.wav")
    score = os.path.join(HERE, f"{name}.txt")
    P = Patch()
    udp = P.obj("udpsend 127.0.0.1 7400", 1, 0, 600, 400)
    con = P.obj("console", 1, 2, 600, 340, outtype=["", ""])
    pc = P.obj("prepend con", 1, 1, 600, 370)
    P.wire(con, 1, pc, 0)
    P.wire(pc, 0, udp, 0)
    gen = gen_box(P, 30, 260)

    # 楽譜: gen~ のコマ番号 → coll → 各 Param へ (unpack は右から出るので trig が最後に届く)
    coll = P.obj("coll", 1, 4, 30, 420, outtype=["", "", "", "bang"])
    snap = P.obj("snapshot~ 1", 2, 1, 30, 330, outtype=["float"])
    P.wire(gen, 2, snap, 0)
    toi = P.obj("i", 2, 1, 30, 360, outtype=["int"])
    P.wire(snap, 0, toi, 0)
    chg = P.obj("change", 1, 3, 30, 390, outtype=["", "int", "int"])
    P.wire(toi, 0, chg, 0)
    P.wire(chg, 0, coll, 0)
    unp = P.obj("unpack " + TYPES, 1, len(FIELDS), 30, 450, w=300, outtype=[""] * len(FIELDS))
    P.wire(coll, 0, unp, 0)
    for i, fld in enumerate(FIELDS):
        pre = P.obj("prepend " + fld, 1, 1, 30 + 90 * i, 480)
        P.wire(unp, i, pre, 0)
        P.wire(pre, 0, gen, 0)

    lb = P.obj("loadbang", 1, 1, 30, 20, outtype=["bang"])
    dl = P.obj("delay 1500", 2, 1, 30, 50, outtype=["bang"])
    P.wire(lb, 0, dl, 0)
    t = P.obj("t b b b b b b", 1, 6, 30, 80, outtype=["bang"] * 6)
    P.wire(dl, 0, t, 0)
    sfr = P.obj("sfrecord~ 2", 2, 1, 30, 560, outtype=["signal"])
    # 右から: ドライバ, 楽譜の読み込みと設定, 書き出し先, dsp, 録音開始, 再生
    m_drv = P.msg("1", 560, 110)
    m_read = P.msg("read \"%s\"" % mac(score), 420, 140)
    m_set = P.msg("fps %s, nframes %d" % (fps, nframes), 300, 170)
    m_open = P.msg("open \"%s\"" % mac(wav), 300, 200)
    m_dsp = P.msg("; dsp start", 220, 140)
    m_rec = P.msg("1", 160, 170)
    m_run = P.msg("run 1", 30, 140)
    drv = P.obj("adstatus driver", 2, 2, 560, 140, outtype=["", "int"])
    P.wire(m_drv, 0, drv, 0)
    for i, m in enumerate([m_run, m_rec, m_dsp, m_open, m_read, m_drv]):
        P.wire(t, i, m, 0)
    P.wire(t, 4, m_set, 0)
    P.wire(m_read, 0, coll, 0)
    P.wire(m_set, 0, gen, 0)
    P.wire(m_open, 0, sfr, 0)
    P.wire(m_rec, 0, sfr, 0)
    P.wire(m_run, 0, gen, 0)
    P.wire(gen, 0, sfr, 0)
    P.wire(gen, 1, sfr, 1)

    # 終わり: 録音を止め、dsp を止めて Max を終了
    edge = P.obj("edge~", 1, 2, 330, 520, outtype=["bang", "bang"])
    P.wire(gen, 3, edge, 0)
    t2 = P.obj("t b b", 1, 2, 330, 550, outtype=["bang", "bang"])
    P.wire(edge, 0, t2, 0)
    m_stop = P.msg("0", 430, 580)
    P.wire(t2, 1, m_stop, 0)
    P.wire(m_stop, 0, sfr, 0)
    dl2 = P.obj("delay 500", 2, 1, 330, 580, outtype=["bang"])
    P.wire(t2, 0, dl2, 0)
    m_end = P.msg("; dsp stop; max quit", 330, 610)
    P.wire(dl2, 0, m_end, 0)
    pe = P.msg("end", 430, 640)
    P.wire(t2, 1, pe, 0)
    P.wire(pe, 0, udp, 0)

    # 状態: コマ番号とピーク
    met = P.obj("metro 500", 2, 1, 760, 20, outtype=["bang"])
    P.wire(lb, 0, met, 0)
    s2 = P.obj("snapshot~", 2, 1, 760, 80, outtype=["float"])
    P.wire(gen, 2, s2, 0)
    P.wire(met, 0, s2, 0)
    pp = P.obj("prepend frame", 1, 1, 760, 110)
    P.wire(s2, 0, pp, 0)
    P.wire(pp, 0, udp, 0)
    pk = P.obj("peakamp~ 500", 2, 1, 900, 80, outtype=["float"])
    P.wire(gen, 0, pk, 0)
    pk2 = P.obj("prepend peak", 1, 1, 900, 110)
    P.wire(pk, 0, pk2, 0)
    P.wire(pk2, 0, udp, 0)
    return P.patcher()


if __name__ == "__main__":
    name, fps, nframes = sys.argv[1], sys.argv[2], int(sys.argv[3])
    out = os.path.join(HERE, f"render_{name}.maxpat")
    with open(out, "w") as f:
        json.dump(render_patch(name, fps, nframes), f, indent=1)
    print("wrote", os.path.basename(out))
