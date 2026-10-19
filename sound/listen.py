# print OSC-ish messages from udpsend (Max sends OSC); exits on "end" or timeout
import socket, sys, time, re
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 7400)); s.settimeout(1)
t0 = time.time(); limit = float(sys.argv[1]) if len(sys.argv) > 1 else 600
while time.time() - t0 < limit:
    try: d = s.recv(4096)
    except socket.timeout: continue
    addr = d.split(b"\0")[0].decode(errors="replace")
    rest = d[(len(addr) // 4 + 1) * 4:]
    tags = rest.split(b"\0")[0].decode(errors="replace")
    off = (len(tags) // 4 + 1) * 4; vals = []
    import struct
    for c in tags[1:]:
        if c == "f": vals.append(round(struct.unpack(">f", rest[off:off+4])[0], 3)); off += 4
        elif c == "i": vals.append(struct.unpack(">i", rest[off:off+4])[0]); off += 4
        elif c == "s":
            e = rest.index(b"\0", off); vals.append(rest[off:e].decode()); off = (e // 4 + 1) * 4
    print(round(time.time() - t0, 1), addr, vals, flush=True)
    if addr.endswith("end"): break
