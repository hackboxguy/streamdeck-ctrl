#!/usr/bin/env python3
"""Image checks for the Spartan-7 A/B first install (flash-fpga-ab.sh).

    fpga-ab-image.py check    <golden> <update> <manifest>
    fpga-ab-image.py combine  <golden> <update> <out>
    fpga-ab-image.py classify <dump> <golden> <update>

check     validates the pair before anything is written (7-series configuration
          header, UG470): the IDCODE is the board's; the GOLDEN carries IPROG and
          a WBSTAR that points at the UPDATE slot and ends below it; the UPDATE
          has no IPROG (it would reboot into itself), its watchdog is on and its
          fallback is not disabled; neither is truncated; both are listed in
          the manifest with the same sha256. Prints
          "golden_version=0x50 update_version=0x88" (from the manifest).
combine   GOLDEN at 0, 0xFF up to the slot, UPDATE at the slot: one image, so
          one programming session writes both and the old image never runs
          between the two writes.
classify  what a readback of the combined range holds:
          "addr0=golden|blank|other slot=match|blank|other".
Exit 0 ok, 1 refused (the reason on stderr), 2 usage.
"""
import hashlib
import struct
import sys

SLOT = 0x400000
BLACKBOX = 0xC00000          # the FPGA's wedge black box; nothing may reach it
IDCODE = 0x0362F093          # XC7S50 / XA7S50 (openFPGALoader: 0x362f093)
SYNC = b"\xaa\x99\x55\x66"
R_FDRI, R_CMD, R_CTL0, R_IDCODE, R_WBSTAR, R_TIMER = 2, 4, 5, 12, 16, 17
CMD_IPROG = 0x0F


def parse(data):
    """The register writes of a raw 7-series configuration stream.

    Returns (writes, end): writes = [(reg, [words])] in stream order (FDRI as
    (2, length-in-words) only), end = the byte offset after the last packet
    that fits in the file; raises ValueError on a stream that does not.
    """
    if data[:1] != b"\xff":
        raise ValueError("not a raw .bin (a .bit header, or no 0xFF padding)")
    i = data.find(SYNC)
    if i < 0:
        raise ValueError("no sync word AA 99 55 66")
    i += 4
    writes, reg = [], None
    while i + 4 <= len(data):
        w = struct.unpack(">I", data[i:i + 4])[0]
        i += 4
        kind = w >> 29
        if kind == 1:
            op, reg, n = (w >> 27) & 3, (w >> 13) & 0x1F, w & 0x7FF
        elif kind == 2:
            op, n = (w >> 27) & 3, w & 0x7FFFFFF
        else:
            continue                   # NOOP / padding words
        if op != 2 or n == 0:
            continue
        if i + 4 * n > len(data):
            raise ValueError("truncated: a packet runs past the end of the file")
        if reg == R_FDRI:
            writes.append((R_FDRI, n))
        else:
            writes.append((reg, list(struct.unpack(">%dI" % n, data[i:i + 4 * n]))))
        i += 4 * n
    if not any(r == R_FDRI and n > 1 for r, n in writes):
        raise ValueError("no frame data (FDRI)")
    return writes


def values(writes, reg):
    return [v for r, vs in writes if r == reg and r != R_FDRI for v in vs]


def check_image(name, data, golden):
    w = parse(data)
    errs = []
    ids = values(w, R_IDCODE)
    if ids != [IDCODE]:
        errs.append("IDCODE %s, expected 0x%08X" % ([hex(x) for x in ids], IDCODE))
    iprog = CMD_IPROG in values(w, R_CMD)
    if golden:
        if not iprog:
            errs.append("no IPROG: a GOLDEN must jump to the UPDATE slot")
        wb = values(w, R_WBSTAR)
        if not wb or (wb[0] & 0x1FFFFFFF) << 8 != SLOT:
            errs.append("WBSTAR %s does not point at the slot 0x%X"
                        % ([hex(x) for x in wb], SLOT))
        if len(data) > SLOT:
            errs.append("%d bytes: runs into the slot at 0x%X" % (len(data), SLOT))
    else:
        if iprog:
            errs.append("IPROG present: an UPDATE would reboot into itself")
        timer = values(w, R_TIMER)
        if not timer or not timer[0] & (1 << 30):
            errs.append("configuration watchdog off (TIMER %s)" % [hex(x) for x in timer])
        # CTL0 bit 10 = ConfigFallback disable; every CTL0 write must leave it clear
        if any(v & (1 << 10) for v in values(w, R_CTL0)):
            errs.append("fallback disabled (CTL0 bit 10)")
        if SLOT + len(data) > BLACKBOX:
            errs.append("%d bytes: the slot would reach the black box at 0x%X"
                        % (len(data), BLACKBOX))
    return ["%s: %s" % (name, e) for e in errs]


def manifest(path):
    blocks, cur = [], {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#"):
            continue
        if not line.strip():
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur:
        blocks.append(cur)
    return {b["file"]: b for b in blocks if "file" in b}


def cmd_check(golden, update, manifest_path):
    errs, vers = [], {}
    try:
        man = manifest(manifest_path)
    except OSError as e:
        print("cannot read the manifest: %s" % e, file=sys.stderr)
        return 1
    for path, is_golden in ((golden, True), (update, False)):
        name = path.rsplit("/", 1)[-1]
        data = open(path, "rb").read()
        entry = man.get(name)
        if entry is None:
            errs.append("%s: not in %s" % (name, manifest_path))
        else:
            if entry.get("sha256", "").lower() != hashlib.sha256(data).hexdigest():
                errs.append("%s: sha256 differs from the manifest" % name)
            vers[is_golden] = entry.get("version", "?")
        try:
            errs += check_image(name, data, is_golden)
        except ValueError as e:
            errs.append("%s: %s" % (name, e))
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    print("golden_version=%s update_version=%s" % (vers[True], vers[False]))
    return 0


def combined(golden, update):
    g, u = open(golden, "rb").read(), open(update, "rb").read()
    return g + b"\xff" * (SLOT - len(g)) + u


def cmd_combine(golden, update, out):
    open(out, "wb").write(combined(golden, update))
    return 0


def cmd_classify(dump, golden, update):
    d = open(dump, "rb").read()
    g, u = open(golden, "rb").read(), open(update, "rb").read()
    if len(d) < SLOT + len(u):
        print("readback is %d bytes, expected %d" % (len(d), SLOT + len(u)), file=sys.stderr)
        return 1
    zero, slot = d[:len(g)], d[SLOT:SLOT + len(u)]
    a0 = "golden" if zero == g else "blank" if zero.count(0xFF) == len(zero) else "other"
    s = "match" if slot == u else "blank" if slot.count(0xFF) == len(slot) else "other"
    print("addr0=%s slot=%s" % (a0, s))
    return 0


def main(argv):
    cmds = {"check": cmd_check, "combine": cmd_combine, "classify": cmd_classify}
    if len(argv) != 5 or argv[1] not in cmds:
        print(__doc__, file=sys.stderr)
        return 2
    return cmds[argv[1]](*argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
