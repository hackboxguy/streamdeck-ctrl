"""ota-update.sh fpga / ota-check.sh fpga against a fake disptool.

The flow mirrors the flasher VM's Update FPGA (run_fpga_update /
install_golden_if_needed): the engine when a pixelpipe image with the OTA
engine answers, else the direct path, which writes GOLDEN at flash address 0
only when 0 is not ours and only after the user holds the key again.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "screens", "display-control", "scripts")
FAKE = os.path.join(REPO, "tests", "fixtures", "fake-disptool-qvue.sh")

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("socat", "stdbuf", "flock", "setsid")),
    reason="needs socat, stdbuf, flock and setsid")

MANIFEST = """file: 3xqvue.bin
version: 0xD7

file: 3xqvue-update.bin
version: 0xDC
"""


class Rig:
    def __init__(self, tmp, **state):
        self.tmp = str(tmp)
        self.state = os.path.join(self.tmp, "state")
        self.otatmp = os.path.join(self.tmp, "otatmp")
        home = os.path.join(self.tmp, "micropanel")
        for d in (self.state, self.otatmp, os.path.join(home, "bin"),
                  os.path.join(home, "share", "sp6bins", "firmware", "fpga")):
            os.makedirs(d, exist_ok=True)
        shutil.copy(FAKE, os.path.join(home, "bin", "disptool"))
        fpga = os.path.join(home, "share", "sp6bins", "firmware", "fpga")
        for f in ("3xqvue.bin", "3xqvue-update.bin", "3xqvue-legacy.bin"):
            open(os.path.join(fpga, f), "wb").write(b"\x00" * 16)
        open(os.path.join(fpga, "manifest.txt"), "w").write(MANIFEST)
        defaults = dict(version="0110", link="02", image="FF", golden="0", engine="0",
                        addr0="vendor", slot="other", flashid="ok", failwrite="", session="0")
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
                        OTA_RECHECK="0", OTA_CONFIRM_SEC="20")

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

    def get(self, key):
        return open(os.path.join(self.state, key)).read().strip()

    def calls(self):
        path = os.path.join(self.state, "calls")
        if not os.path.exists(path):
            return []
        return [c for c in open(path).read().splitlines()
                if c.startswith("fpgaflash")]

    def states(self, nid="ota.fpga"):
        return [m["state"] for m in self.messages if m.get("id") == nid and "state" in m]

    def log(self):
        return open(os.path.join(self.otatmp, "ota-update.log")).read()

    def start(self, *args, **env):
        e = dict(self.env, **env)
        return subprocess.Popen([os.path.join(SCRIPTS, "ota-update.sh"), "fpga", *args],
                                env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def run(self, *args, **env):
        p = self.start(*args, **env)
        p.wait(timeout=120)
        time.sleep(0.2)            # the last notification
        return p.returncode

    def check(self):
        p = subprocess.run([os.path.join(SCRIPTS, "ota-check.sh"), "fpga"],
                           env=self.env, capture_output=True, text=True, timeout=120)
        time.sleep(0.2)
        return p.returncode, p.stdout


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(**state):
        r = Rig(tmp_path, **state)
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


class TestDirectPath:
    def test_vendor_unit_asks_and_installs_golden_then_the_slot(self, rig):
        r = rig(link="02", addr0="vendor")
        p = r.start()
        assert wait_for(os.path.join(r.otatmp, "qvue-fpga-confirm.wait"))
        assert r.calls()[-1].startswith("fpgaflash verify:")   # nothing written yet
        # The second hold of the key: the same command, answered and gone.
        assert r.run() == 0
        assert p.wait(timeout=60) == 0
        time.sleep(0.2)
        calls = r.calls()
        assert calls[0] == "fpgaflash abort"
        assert calls[1] == "fpgaflash begin"
        assert any(c.endswith("3xqvue.bin,0x0,golden") for c in calls)
        writes = [c for c in calls if c.startswith("fpgaflash write:")]
        assert writes[0].endswith("3xqvue.bin,0x0,golden")
        assert "3xqvue-update.bin,0x400000" in writes[1]
        assert calls[-1] == "fpgaflash end"
        assert "confirm" in r.states()
        assert r.states()[-1] == "success"
        assert (r.get("link"), r.get("image"), r.get("golden")) == ("01", "DC", "0")
        assert not os.path.exists(os.path.join(r.otatmp, "qvue-fpga-confirm.wait"))

    def test_no_answer_writes_nothing_and_closes_the_session(self, rig):
        r = rig(link="02", addr0="vendor")
        assert r.run(OTA_CONFIRM_SEC="1") == 1
        calls = r.calls()
        assert not any(c.startswith("fpgaflash write:") for c in calls)
        assert calls[-1] == "fpgaflash abort"
        assert r.get("session") == "0"
        assert r.states()[-1] == "failure"
        assert "nothing was written" in r.log()

    def test_unknown_image_at_zero_also_asks(self, rig):
        r = rig(link="FF", addr0="other")
        assert r.run(OTA_CONFIRM_SEC="1") == 1
        assert "confirm" in r.states()
        assert "holds: unknown" in r.log()

    def test_our_golden_at_zero_writes_only_the_slot(self, rig):
        # GOLDEN at 0, the legacy image in the UPDATE slot: link 0x02 too
        r = rig(link="02", addr0="golden", slot="other")
        assert r.run() == 0
        writes = [c for c in r.calls() if c.startswith("fpgaflash write:")]
        assert len(writes) == 1 and "3xqvue-update.bin,0x400000" in writes[0]
        assert "confirm" not in r.states()
        assert r.states()[-1] == "success"

    def test_flash_that_does_not_answer_is_reported_and_closed(self, rig):
        r = rig(link="00", flashid="ff")
        assert r.run() == 1
        calls = r.calls()
        assert calls[-1] == "fpgaflash abort"
        assert not any(c.startswith("fpgaflash verify") or c.startswith("fpgaflash write")
                       for c in calls)
        log = r.log()
        assert "ID FF FF FF" in log and "Power-cycle the QVue fully" in log
        assert "hardware / JTAG" in log

    def test_failed_write_leaves_the_session_open(self, rig):
        r = rig(link="02", addr0="golden", failwrite="3xqvue-update.bin")
        assert r.run() == 1
        assert r.calls()[-1].startswith("fpgaflash write:")      # no abort, no end
        assert r.get("session") == "direct"
        assert "keep the QVue powered" in r.log()

    def test_a_rerun_resumes_through_the_same_flow(self, rig):
        # A GOLDEN write cut short: 0 holds neither image, the session is open.
        r = rig(link="FF", addr0="other", session="direct")
        p = r.start()
        assert wait_for(os.path.join(r.otatmp, "qvue-fpga-confirm.wait"))
        assert r.run() == 0
        assert p.wait(timeout=60) == 0
        assert r.calls()[0] == "fpgaflash abort"
        assert (r.get("link"), r.get("image")) == ("01", "DC")

    def test_the_answer_must_come_from_the_same_key(self, rig):
        r = rig(link="02", addr0="vendor")
        p = r.start()
        assert wait_for(os.path.join(r.otatmp, "qvue-fpga-confirm.wait"))
        # Qvue-New/FPGA-Flash pressed meanwhile: not an answer; the lock refuses it.
        assert r.run("--id=fpga.flash_qvue_new", "--force") == 1
        assert not os.path.exists(os.path.join(r.otatmp, "qvue-fpga-confirm.yes"))
        assert r.run() == 0
        assert p.wait(timeout=60) == 0


class TestEnginePath:
    def test_running_pixelpipe_image_takes_the_engine(self, rig):
        r = rig(link="01", image="DB", engine="1", addr0="golden", slot="other")
        assert r.run() == 0
        calls = r.calls()
        assert calls == ["fpgaflash write:" + os.path.join(
            r.env["MICROPANEL_HOME"], "share/sp6bins/firmware/fpga/3xqvue-update.bin") + ",0x400000,engine"]
        assert r.states()[-1] == "success"

    def test_golden_running_is_not_an_error_before_the_write(self, rig):
        r = rig(link="01", image="D7", golden="1", engine="1", addr0="golden", slot="other")
        assert r.run() == 0
        assert len(r.calls()) == 1 and r.calls()[0].endswith(",0x400000,engine")

    def test_golden_fallback_after_the_write_is_a_failure(self, rig):
        r = rig(link="01", image="D7", golden="1", engine="1", addr0="golden",
                slot="other", failwrite="")
        # the slot "writes" but the fake keeps booting GOLDEN
        r.set("addr0", "golden")
        open(os.path.join(r.state, "slot"), "w").write("other\n")
        fake = os.path.join(r.env["MICROPANEL_HOME"], "bin", "disptool")
        body = open(fake).read().replace('            put slot update\n', '            :\n')
        open(fake, "w").write(body)
        assert r.run() == 1
        assert "fell back to its GOLDEN image" in r.log()

    def test_current_image_is_nothing_to_do(self, rig):
        r = rig(link="01", image="DC", engine="1", addr0="golden", slot="update")
        assert r.run() == 1
        assert r.calls() == []
        assert "nothing to update" in r.log()

    def test_force_rewrites_a_current_slot_by_the_engine(self, rig):
        r = rig(link="01", image="DC", engine="1", addr0="golden", slot="update")
        assert r.run("--id=fpga.flash_qvue_new", "--force") == 0
        assert len(r.calls()) == 1 and r.calls()[0].endswith(",0x400000,engine")
        assert r.states("fpga.flash_qvue_new")[-1] == "success"
        assert r.states("ota.fpga") == []


class TestLock:
    def test_the_recheck_after_a_run_does_not_keep_the_flash_lock(self, rig):
        """The background ota-check --wait must not inherit the lock's fd: it
        would hold the lock it waits for, and refuse every flash key."""
        r = rig(link="01", image="DB", engine="1", addr0="golden", slot="other")
        assert r.run(OTA_RECHECK="1") == 0
        lock = os.path.join(r.otatmp, "target-flash.lock")
        time.sleep(0.5)
        free = subprocess.run(["flock", "-n", lock, "true"]).returncode == 0
        assert free, "the flash lock is still held after the run"
        # and the recheck itself ran: OTA-FPGA goes idle (0xDC current)
        end = time.time() + 20
        while time.time() < end and "idle" not in r.states():
            time.sleep(0.2)
        assert "idle" in r.states()


class TestPrecheck:
    def test_old_display_manager_points_to_the_mcu_update(self, rig):
        r = rig(version="0102")
        assert r.run() == 1
        assert r.calls() == []
        assert "older than v01.03" in r.log()


class TestCheck:
    def test_vendor_unit_is_offered(self, rig):
        r = rig(link="02")
        rc, out = r.check()
        assert rc == 0
        assert r.states()[-1] == "available"
        assert "first-time install" in out

    def test_current_unit_is_idle(self, rig):
        r = rig(link="01", image="DC", engine="1")
        r.check()
        assert r.states()[-1] == "idle"

    def test_old_unit_waits_for_the_mcu(self, rig):
        r = rig(link="02", version="0102")
        r.check()
        assert r.states()[-1] == "idle"
