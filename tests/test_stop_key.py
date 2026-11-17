"""The Stop key's script (screens/display-control/scripts/stop.sh): two stages.

A press stops a playing video first (player-ctl.sh stop); with nothing playing
it goes to the launcher's home screen (launch-home.sh). Run against stub
player-ctl.sh / launch-home.sh / launcher-client that log their calls.
"""

import os
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOP = os.path.join(REPO, "screens", "display-control", "scripts", "stop.sh")


def _stub(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/bash\n" + body)
    os.chmod(path, 0o755)


@pytest.fixture
def rig(tmp_path):
    """stop.sh in a folder of stubs; set(player=..., app=...) picks what runs."""
    shutil.copy(STOP, tmp_path / "stop.sh")
    log = tmp_path / "calls"
    _stub(tmp_path / "player-ctl.sh",
          f'echo "player-ctl $*" >> {log}\n'
          f'case "$1" in which) cat {tmp_path}/player ;; esac\n')
    _stub(tmp_path / "launch-home.sh", f'echo "launch-home" >> {log}\n')
    _stub(tmp_path / "launcher-client",
          f'case "$*" in *get-running-app*) cat {tmp_path}/app ;; esac\n')

    class Rig:
        def set(self, player="none", app="none"):
            (tmp_path / "player").write_text(player + "\n")
            (tmp_path / "app").write_text(app + "\n")
            log.write_text("")

        def run(self, *args):
            env = dict(os.environ, LAUNCHER_CLIENT=str(tmp_path / "launcher-client"),
                       NOTIFY_SOCK=str(tmp_path / "no.sock"))
            out = subprocess.run([str(tmp_path / "stop.sh"), *args], env=env,
                                 capture_output=True, text=True, timeout=10)
            return out.stdout.strip()

        def actions(self):
            return [line for line in log.read_text().splitlines()
                    if line not in ("player-ctl which",)]

    return Rig()


def test_a_playing_video_is_stopped_first(rig):
    rig.set(player="kodi", app="kodi")
    rig.run()
    assert rig.actions() == ["player-ctl stop"]


def test_with_nothing_playing_it_goes_home(rig):
    rig.set(player="none", app="kodi")          # Kodi at its menu
    rig.run()
    assert rig.actions() == ["launch-home"]
    rig.set(player="none", app="cluster-v2")    # the cluster demo plays no video
    rig.run()
    assert rig.actions() == ["launch-home"]


@pytest.mark.parametrize("player,app,lit", [
    ("dual-video-player", "dual-video", "on"),
    ("sdr-hdr-sync", "none", "on"),             # a player the launcher did not start
    ("none", "kodi", "on"),
    ("none", "none", "off"),
    ("none", "", "off"),                        # launcher not answering
])
def test_lit_while_there_is_something_to_stop(rig, player, app, lit):
    rig.set(player=player, app=app)
    assert rig.run("state") == lit
