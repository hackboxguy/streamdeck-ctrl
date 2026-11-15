"""flash-fpga-ab.sh (12.3-NQ5 FPGA Flash) against a fake openFPGALoader and disptool.

The flow follows sp6bins docs/fpga-ab-update-procedure.md and the first-install
notes: classify the flash before writing, ask before replacing a non-GOLDEN
address 0, back the flash up, write GOLDEN + UPDATE in ONE session without a
reset in between, read back, reconfigure once, judge by what runs.
"""
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "screens", "display-control", "scripts")
FIX = os.path.join(REPO, "tests", "fixtures")
SLOT = 0x400000
NID = "fpga.flash_12_3_nq5"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("socat", "flock", "dd", "cmp", "python3")),
    reason="needs socat, flock, dd, cmp and python3")


def t1(reg, n):
    return 0x30000000 | (reg << 13) | n


def bitstream(golden, frames=64, iprog=None, watchdog=True, fallback=True, idcode=0x0362F093):
    """A minimal raw 7-series configuration stream (UG470 packet format)."""
    words = [0xFFFFFFFF] * 8 + [0x000000BB, 0x11220044, 0xFFFFFFFF, 0xFFFFFFFF, 0xAA995566]
    words += [t1(17, 1), 0x40000000 if watchdog else 0]            # TIMER
    words += [t1(16, 1), (SLOT >> 8) if golden else 0]             # WBSTAR
    words += [t1(4, 1), 0x0F if (golden if iprog is None else iprog) else 0]   # CMD
    words += [t1(12, 1), idcode]                                    # IDCODE
    words += [t1(5, 1), 0x101 if fallback else 0x501]               # CTL0
    words += [t1(2, 0), 0x50000000 | frames]                        # FDRI, type 2
    words += [(0x5A5A0000 + i + (0 if golden else 0x1000)) for i in range(frames)]
    words += [t1(4, 1), 0x0D]                                       # DESYNC
    return b"".join(struct.pack(">I", w) for w in words)


class Rig:
    def __init__(self, tmp, addr0="vendor", slot="blank", golden=None, update=None,
                 manifest_sha_ok=True, **state):
        self.tmp = str(tmp)
        self.state = os.path.join(self.tmp, "state")
        self.otatmp = os.path.join(self.tmp, "otatmp")
        self.backups = os.path.join(self.tmp, "backups")
        home = os.path.join(self.tmp, "micropanel")
        fpga = os.path.join(home, "share", "sp6bins", "firmware", "fpga")
        share = os.path.join(home, "fpga", "share", "openFPGALoader")
        for d in (self.state, self.otatmp, os.path.join(home, "bin"),
                  os.path.join(home, "fpga", "bin"), fpga, share):
            os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(FIX, "fake-ofl-xc7s50.sh"),
                    os.path.join(home, "fpga", "bin", "openFPGALoader"))
        shutil.copy(os.path.join(FIX, "fake-disptool-xc7s50.sh"),
                    os.path.join(home, "bin", "disptool"))
        open(os.path.join(share, "spiOverJtag_xc7s50.bit.gz"), "wb").write(b"bridge")
        upd = os.path.join(home, "bin", "update-fpga.sh")
        open(upd, "w").write(
            '#!/bin/bash\nr=$(%s/bin/disptool --device=fpganew --command=activbitstream)\n'
            'echo "RESULT board=fpga display=12.3 running=x/x/$r status=$([ "$r" = OTA ]'
            ' && echo ok || echo failed)"\n' % home)
        os.chmod(upd, 0o755)
        self.lsusb = os.path.join(home, "bin", "lsusb")
        open(self.lsusb, "w").write('#!/bin/bash\n[ "$(cat %s/blaster)" = ok ]\n' % self.state)
        os.chmod(self.lsusb, 0o755)

        self.golden = golden if golden is not None else bitstream(True)
        self.update = update if update is not None else bitstream(False)
        self.gpath = os.path.join(fpga, "12-3-inch-new.bin")
        self.upath = os.path.join(fpga, "12-3-inch-new_ota.bin")
        open(self.gpath, "wb").write(self.golden)
        open(self.upath, "wb").write(self.update)
        sha = lambda b: hashlib.sha256(b).hexdigest()
        open(os.path.join(fpga, "manifest.txt"), "w").write(
            "# test\nfile: 12-3-inch-new.bin\nsha256: %s\nversion: 0x50\n\n"
            "file: 12-3-inch-new_ota.bin\nsha256: %s\nversion: 0x88\n"
            % (sha(self.golden), sha(self.update) if manifest_sha_ok else "0" * 64))

        flash = bytearray(b"\xff" * 16 * 1024 * 1024)
        self.vendor = bytes((i * 7 + 3) & 0xFF for i in range(len(self.golden) + 333))
        if addr0 == "vendor":
            flash[:len(self.vendor)] = self.vendor
        elif addr0 == "golden":
            flash[:len(self.golden)] = self.golden
        if slot == "match":
            flash[SLOT:SLOT + len(self.update)] = self.update
        elif slot == "other":
            flash[SLOT:SLOT + 100] = b"\x12" * 100
        self.flash_path = os.path.join(self.state, "flash")
        open(self.flash_path, "wb").write(flash)
        self.flash_before = bytes(flash)

        defaults = dict(jtag="ok", jedec="0x9d6018", failwrite="0", fpga="image",
                        ioc="ok", power="on", blaster="ok",
                        golden=self.gpath, update=self.upath)
        defaults.update(state)
        for k, v in defaults.items():
            self.set(k, v)

        self.sock_path = os.path.join(self.tmp, "notify.sock")
        self.messages = []
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.sock_path)
        self._srv.listen(16)
        threading.Thread(target=self._serve, daemon=True).start()
        self.env = dict(os.environ, MICROPANEL_HOME=home, FAKE_STATE=self.state,
                        OTA_TMP=self.otatmp, OTA_NOTIFY_SOCK=self.sock_path,
                        OTA_CONFIRM_SEC="20", FPGA_BACKUP_DIR=self.backups,
                        FPGA_AB_OFL_SUDO="0", FPGA_AB_POWER_OFF_SEC="0",
                        FPGA_AB_BOOT_WAIT_SEC="3", LSUSB=self.lsusb)

    def _serve(self):
        while True:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            conn.close()
            for line in data.decode().splitlines():
                if line.strip():
                    self.messages.append(json.loads(line))

    def close(self):
        self._srv.close()

    def set(self, key, value):
        open(os.path.join(self.state, key), "w").write(value + "\n")

    def flash(self):
        return open(self.flash_path, "rb").read()

    def calls(self, prefix="ofl"):
        p = os.path.join(self.state, "calls")
        if not os.path.exists(p):
            return []
        return [c for c in open(p).read().splitlines() if c.startswith(prefix)]

    def writes(self):
        return [c for c in self.calls() if " -f " in c + " " and "--detect" not in c]

    def states(self):
        return [m["state"] for m in self.messages if m.get("id") == NID and "state" in m]

    def log(self):
        return open(os.path.join(self.otatmp, "fpga-flash.log")).read()

    def start(self, **env):
        e = dict(self.env, **env)
        return subprocess.Popen(
            [os.path.join(SCRIPTS, "flash-fpga-ab.sh"), "--id=" + NID, "--label=12.3-NQ5",
             "--golden=12-3-inch-new.bin", "--update=12-3-inch-new_ota.bin"],
            env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def run(self, **env):
        p = self.start(**env)
        p.wait(timeout=120)
        time.sleep(0.2)
        return p.returncode

    def installed(self):
        f = self.flash()
        return (f[:len(self.golden)] == self.golden
                and f[SLOT:SLOT + len(self.update)] == self.update)


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(**kw):
        r = Rig(tmp_path, **kw)
        made.append(r)
        return r
    yield make
    for r in made:
        r.close()


def wait_for(path, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


class TestVendorBoard:
    def test_asks_backs_up_and_writes_both_in_one_session(self, rig):
        r = rig(addr0="vendor", slot="blank")
        p = r.start()
        wait = os.path.join(r.otatmp, "fpga-ab-confirm.wait")
        assert wait_for(wait)
        assert r.writes() == []                       # nothing written while asking
        assert r.run() == 0                           # the second hold: yes
        assert p.wait(timeout=120) == 0
        time.sleep(0.2)

        assert r.installed()
        writes = r.writes()
        assert len(writes) == 1                       # GOLDEN + UPDATE in ONE session
        assert "--skip-reset" in writes[0] and "--verify" in writes[0]
        assert " -o " not in writes[0]                # the combined image from 0
        # No reset/reconfiguration of the FPGA between the read, the write and
        # the readback: every bridge call keeps the bridge loaded.
        bridge_calls = [c for c in r.calls() if " -B " in c]
        assert all("--skip-reset" in c for c in bridge_calls if "--detect" not in c)
        # the backup: the whole flash as it was, with its sha256
        bks = [f for f in os.listdir(r.backups) if f.endswith(".bin")]
        assert len(bks) == 1 and bks[0].startswith("12.3-NQ5-flash-")
        assert open(os.path.join(r.backups, bks[0]), "rb").read() == r.flash_before
        assert os.path.exists(os.path.join(r.backups, bks[0] + ".sha256"))
        # one deliberate reconfiguration, through the IOC
        assert r.calls("disptool --device=ioc --command=disppower --value=off")
        assert "confirm" in r.states() and r.states()[-1] == "success"
        log = r.log()
        assert "readback: identical" in log
        assert "SUCCESS: migrated" in log
        assert not os.path.exists(wait)

    def test_no_answer_writes_nothing_and_gives_the_vendor_image_back(self, rig):
        r = rig(addr0="vendor")
        assert r.run(OTA_CONFIRM_SEC="1") == 1
        assert r.writes() == []
        assert r.flash() == r.flash_before
        assert not os.path.exists(r.backups) or os.listdir(r.backups) == []
        assert r.calls("disptool --device=ioc --command=disppower --value=on")
        assert r.states()[-1] == "failure"
        assert "no answer: nothing was written" in r.log()

    def test_blank_address_zero_also_asks(self, rig):
        r = rig(addr0="blank")
        assert r.run(OTA_CONFIRM_SEC="1") == 1
        assert "confirm" in r.states()
        assert "an empty address 0" in r.log()

    def _cut_then_rerun(self, r, asks_again):
        p = r.start()
        assert wait_for(os.path.join(r.otatmp, "fpga-ab-confirm.wait"))
        r.run()
        assert p.wait(timeout=120) == 1
        time.sleep(0.2)
        assert r.states()[-1] == "failure"
        assert not r.installed()
        r.set("failwrite", "0")
        r.messages.clear()
        p = r.start()
        if asks_again:
            assert wait_for(os.path.join(r.otatmp, "fpga-ab-confirm.wait"))
            r.run()
        assert p.wait(timeout=120) == 0
        time.sleep(0.2)
        assert r.installed()
        assert ("confirm" in r.states()) == asks_again

    def test_write_cut_inside_golden_asks_again_and_completes(self, rig):
        # address 0 now holds a partial GOLDEN: unknown, so the question again
        self._cut_then_rerun(rig(addr0="vendor", failwrite="40"), asks_again=True)

    def test_write_cut_after_golden_completes_the_slot_without_asking(self, rig):
        # GOLDEN verifies at 0: the rerun writes only the slot
        self._cut_then_rerun(rig(addr0="vendor", failwrite="8192"), asks_again=False)


class TestOurBoard:
    def test_current_pair_writes_nothing_and_still_checks_what_runs(self, rig):
        r = rig(addr0="golden", slot="match")
        assert r.run() == 0
        assert r.writes() == []
        assert "confirm" not in r.states()
        assert r.states()[-1] == "success"
        assert "SUCCESS: already installed" in r.log()

    def test_golden_present_writes_only_the_slot(self, rig):
        r = rig(addr0="golden", slot="other")
        assert r.run() == 0
        writes = r.writes()
        assert len(writes) == 1
        assert "-o 0x400000" in writes[0] and "12-3-inch-new_ota.bin" in writes[0]
        assert "confirm" not in r.states()
        assert r.installed()
        assert "SUCCESS: updated" in r.log()
        assert not os.path.exists(r.backups) or os.listdir(r.backups) == []

    def test_ioc_missing_falls_back_to_a_jtag_reset(self, rig):
        r = rig(addr0="golden", slot="other", ioc="none")
        assert r.run() == 0
        assert any("--reset" in c for c in r.calls())
        assert "reconfigured (jtag)" in r.log()

    def test_power_cycle_that_does_not_restart_the_fpga_falls_back_to_jtag(self, rig):
        r = rig(addr0="golden", slot="other", iocrails="0")
        assert r.run() == 0
        assert r.calls("disptool --device=ioc --command=disppower --value=off")
        assert any("--reset" in c for c in r.calls())
        assert "did not restart the FPGA" in r.log()
        assert "SUCCESS: updated" in r.log()


class TestRefusals:
    @pytest.mark.parametrize("kw,msg", [
        (dict(golden=bitstream(True, iprog=False)), "no IPROG"),
        (dict(update=bitstream(False, iprog=True)), "IPROG present"),
        (dict(update=bitstream(False, watchdog=False)), "watchdog off"),
        (dict(update=bitstream(False, fallback=False)), "fallback disabled"),
        (dict(golden=bitstream(True, idcode=0x037C4093)), "IDCODE"),
        (dict(manifest_sha_ok=False), "sha256 differs"),
    ])
    def test_bad_images_are_refused_before_touching_the_board(self, rig, kw, msg):
        r = rig(addr0="vendor", **kw)
        assert r.run() == 1
        assert r.calls() == []                         # not even a probe
        assert msg in r.log()
        assert r.states()[-1] == "failure"

    def test_no_blaster(self, rig):
        r = rig(blaster="none")
        assert r.run() == 1
        assert "no USB-Blaster" in r.log()
        assert r.calls() == []

    def test_wrong_flash_id_writes_nothing(self, rig):
        r = rig(addr0="vendor", jedec="0xffffff")
        assert r.run() == 1
        assert r.writes() == []
        assert r.flash() == r.flash_before
        assert "not the IS25LP128" in r.log()

    def test_wrong_running_version_is_a_failure(self, rig):
        # The slot holds the UPDATE but the FPGA came up on the GOLDEN.
        r = rig(addr0="golden", slot="match")
        fake = os.path.join(r.tmp, "micropanel", "bin", "disptool")
        body = open(fake).read().replace('OTA)    echo "Raw Bytes   : 0x10 0x18 0x00 0x88"',
                                         'OTA)    echo "Raw Bytes   : 0x09 0x28 0x00 0x50"')
        open(fake, "w").write(body)
        assert r.run() == 1
        assert "does not run the UPDATE" in r.log()
