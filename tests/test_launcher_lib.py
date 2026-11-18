"""The key scripts against a launcher that drops connections
(scripts/launcher-lib.sh, through cluster-theme.sh).

The launcher serves one command connection at a time and closes any other
that arrives meanwhile, unread: launcher-client then prints "Connection
reset by peer" and the command never ran. The stub here drops every other
call, the first of each pair, and keeps the running app in a file.
"""

import os
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "screens", "display-control", "scripts")


@pytest.fixture
def launcher(tmp_path):
    app = tmp_path / "app"
    app.write_text("none\n")
    n = tmp_path / "n"
    n.write_text("0")
    log = tmp_path / "ran"
    log.write_text("")
    stub = tmp_path / "launcher-client"
    stub.write_text(
        "#!/bin/bash\n"
        f'n=$(( $(cat {n}) + 1 )); echo $n > {n}\n'
        'if [ $((n % 2)) = 1 ] && [ -z "${FLAKY_OFF:-}" ]; then\n'
        '    echo "Error: Failed to receive response: Connection reset by peer" >&2; exit 1\n'
        'fi\n'
        'cmd=""; arg=""\n'
        'for a; do case "$a" in --command=*) cmd=${a#*=} ;; --command-arg=*) arg=${a#*=} ;; esac; done\n'
        f'[ "$cmd" = get-running-app ] || echo "$cmd $arg" >> {log}\n'
        'case "$cmd" in\n'
        f'  get-running-app) cat {app} ;;\n'
        f'  stop-app) echo none > {app}; echo OK ;;\n'
        f'  start-app) if [ "$(cat {app})" != none ]; then echo "ERROR: app-already-running"; '
        f'else echo "$arg" > {app}; echo OK; fi ;;\n'
        'esac\n')
    stub.chmod(0o755)

    class Launcher:
        def run(self, script, *args, flaky=True):
            env = dict(os.environ, LAUNCHER_CLIENT=str(stub))
            if not flaky:
                env["FLAKY_OFF"] = "1"
            out = subprocess.run(["bash", os.path.join(SCRIPTS, script), *args], env=env,
                                 capture_output=True, text=True, timeout=60)
            return out.returncode, out.stdout + out.stderr

        def running(self, name=None):
            if name is not None:
                app.write_text(name + "\n")
            return app.read_text().strip()

        def ran(self):
            return log.read_text().splitlines()

    return Launcher()


def test_switch_from_another_app_despite_dropped_connections(launcher):
    launcher.running("quick-video")
    rc, out = launcher.run("cluster-theme.sh", "harman")
    assert rc == 0, out
    assert launcher.running() == "cluster-v2-harman"
    assert launcher.ran() == ["stop-app ", "start-app cluster-v2-harman"]   # each once


def test_already_running_theme_is_left_alone(launcher):
    launcher.running("cluster-v2-harman")
    rc, _ = launcher.run("cluster-theme.sh", "harman")
    assert rc == 0 and launcher.ran() == []


def test_launcher_gone_fails_without_starting(launcher, tmp_path):
    rc, out = launcher.run("cluster-theme.sh", "harman", flaky=False)
    assert rc == 0 and launcher.running() == "cluster-v2-harman"   # from home: no stop
    launcher.running("quick-video")
    env_gone = dict(os.environ, LAUNCHER_CLIENT=str(tmp_path / "absent"))
    out = subprocess.run(["bash", os.path.join(SCRIPTS, "cluster-theme.sh"), "ev"],
                         env=env_gone, capture_output=True, text=True, timeout=60)
    assert out.returncode == 1 and "did not" in out.stderr
