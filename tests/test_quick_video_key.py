"""The Quick Video key's script (scripts/launch-quick-video.sh).

Run against a stub quick-video.sh (the launcher's entry script), a stub
launcher-client that keeps the running app in a file, and a fake
dual-video-player control socket that answers "playing".
"""

import os
import socket
import subprocess
import threading

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.join(REPO, "screens", "display-control", "scripts", "launch-quick-video.sh")


def _stub(path, body):
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def rig(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    app = tmp_path / "app"
    app.write_text("none\n")
    log = tmp_path / "calls"
    log.write_text("")
    # quick-video.sh: --check passes while ./videos exists; a start (by the
    # launcher stub) records the index it was asked for, as the real one does
    _stub(tmp_path / "quick-video.sh",
          f'if [ "$1" = --check ]; then [ -e {tmp_path}/videos ] || {{ echo "No video"; exit 1; }}; exit 0; fi\n'
          f'n=$(cat {state}/quick-video.next 2>/dev/null || echo 0); rm -f {state}/quick-video.next\n'
          f'n=$((n % 3)); printf "%s\\t/stick/clip-%s.mp4\\t3\\n" $n $n > {state}/quick-video.current\n')
    _stub(tmp_path / "launcher-client",
          f'echo "$*" >> {log}\n'
          f'case "$*" in\n'
          f'  *get-running-app*) cat {app} ;;\n'
          f'  *stop-app*) echo none > {app}; echo OK ;;\n'
          f'  *start-app*quick-video*) echo quick-video > {app}; {tmp_path}/quick-video.sh; echo OK ;;\n'
          f'esac\n')
    sock_path = str(tmp_path / "player.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(8)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.recv(64)
            c.sendall(b'{"player":"dual-video-player","mode":"playlist","state":"playing"}\n')
            c.close()
    threading.Thread(target=serve, daemon=True).start()

    class Rig:
        current = state / "quick-video.current"

        def run(self, *args):
            env = dict(os.environ, QUICK_VIDEO_SH=str(tmp_path / "quick-video.sh"),
                       LAUNCHER_CLIENT=str(tmp_path / "launcher-client"),
                       QUICK_VIDEO_STATE_DIR=str(state), PLAYER_SOCK=sock_path,
                       NOTIFY_SOCK=str(tmp_path / "no.sock"))
            out = subprocess.run(["bash", KEY, *args], env=env, capture_output=True,
                                 text=True, timeout=30)
            self.rc = out.returncode
            return out.stdout.strip()

        def videos(self, present=True):
            p = tmp_path / "videos"
            p.write_text("") if present else p.unlink(missing_ok=True)

        def running(self, name):
            app.write_text(name + "\n")

        def calls(self):
            return [c for c in log.read_text().splitlines() if "get-running-app" not in c]

    yield Rig()
    srv.close()


def test_state(rig):
    assert rig.run("state") == "missing"
    rig.videos()
    assert rig.run("state") == "ready"
    rig.running("quick-video")
    assert rig.run("state") == "playing"


def test_no_launcher_answer_keeps_the_key(rig):
    rig.running("")
    assert rig.run("state") == "" and rig.rc != 0


def test_first_press_plays_the_first_video(rig):
    rig.videos()
    assert rig.run() == "quick-video: 1/3 clip-0.mp4" and rig.rc == 0


def test_press_while_playing_plays_the_next(rig):
    rig.videos()
    rig.run()
    assert rig.run() == "quick-video: 2/3 clip-1.mp4"
    assert rig.run() == "quick-video: 3/3 clip-2.mp4"
    assert rig.run() == "quick-video: 1/3 clip-0.mp4"      # wraps around


def test_another_app_is_stopped_and_the_first_video_plays(rig):
    rig.videos()
    rig.run()
    rig.run()                                               # at clip 2
    rig.running("media-player")                             # then Kodi took over
    assert rig.run() == "quick-video: 1/3 clip-0.mp4"
    assert any("stop-app" in c for c in rig.calls())


def test_no_video_fails_without_starting(rig):
    rig.run()
    assert rig.rc == 1 and not rig.calls()
