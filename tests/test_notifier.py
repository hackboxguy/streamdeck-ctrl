"""Tests for streamdeck_ctrl.notifier — Unix socket server."""

import json
import os
import socket
import tempfile
import time
import shutil
import pytest

from streamdeck_ctrl.notifier import Notifier


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def sock_path(tmpdir):
    return os.path.join(tmpdir, "test.sock")


class MockHandler:
    """Records notifications and returns configurable responses."""

    def __init__(self):
        self.calls = []
        self.response = (True, None)

    def __call__(self, nid, state=None, value=None):
        self.calls.append({"id": nid, "state": state, "value": value})
        return self.response


@pytest.fixture
def handler():
    return MockHandler()


@pytest.fixture
def notifier(sock_path, handler):
    n = Notifier(sock_path, handler)
    n.start()
    # Wait for socket to be ready
    for _ in range(50):
        if os.path.exists(sock_path):
            break
        time.sleep(0.01)
    yield n
    n.stop()


def _send(sock_path, messages):
    """Send messages to the notifier and return responses."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.settimeout(2.0)

    responses = []
    for msg in messages:
        s.sendall(json.dumps(msg).encode() + b"\n")
        # Read response
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        if data:
            responses.append(json.loads(data.strip()))

    s.close()
    return responses


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------


class TestBasicOperations:
    def test_socket_created(self, notifier, sock_path):
        assert os.path.exists(sock_path)

    def test_state_notification(self, notifier, sock_path, handler):
        responses = _send(sock_path, [{"id": "test.key", "state": "on"}])
        assert len(responses) == 1
        assert responses[0]["status"] == "ok"
        assert len(handler.calls) == 1
        assert handler.calls[0] == {"id": "test.key", "state": "on", "value": None}

    def test_value_notification(self, notifier, sock_path, handler):
        responses = _send(sock_path, [{"id": "sensor.temp", "value": "42.5"}])
        assert responses[0]["status"] == "ok"
        assert handler.calls[0]["value"] == "42.5"

    def test_multiple_messages_one_connection(self, notifier, sock_path, handler):
        msgs = [
            {"id": "key1", "state": "on"},
            {"id": "key2", "value": "55"},
        ]
        responses = _send(sock_path, msgs)
        assert len(responses) == 2
        assert all(r["status"] == "ok" for r in responses)
        assert len(handler.calls) == 2

    def test_stop_cleans_up_socket(self, sock_path, handler):
        n = Notifier(sock_path, handler)
        n.start()
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.01)
        n.stop()
        assert not os.path.exists(sock_path)


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_id(self, notifier, sock_path, handler):
        responses = _send(sock_path, [{"state": "on"}])
        assert responses[0]["status"] == "error"
        assert "missing" in responses[0]["reason"]

    def test_missing_state_and_value(self, notifier, sock_path, handler):
        responses = _send(sock_path, [{"id": "test.key"}])
        assert responses[0]["status"] == "error"
        assert "must include" in responses[0]["reason"]

    def test_handler_error(self, notifier, sock_path, handler):
        handler.response = (False, "unknown notification_id: bad.id")
        responses = _send(sock_path, [{"id": "bad.id", "state": "on"}])
        assert responses[0]["status"] == "error"
        assert "unknown" in responses[0]["reason"]

    def test_invalid_json(self, notifier, sock_path, handler):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.settimeout(2.0)
        s.sendall(b"{bad json\n")
        data = s.recv(4096)
        s.close()
        resp = json.loads(data.strip())
        assert resp["status"] == "error"
        assert "invalid JSON" in resp["reason"]


# ---------------------------------------------------------------------------
# Multiple clients
# ---------------------------------------------------------------------------


class TestMultipleClients:
    def test_two_concurrent_clients(self, notifier, sock_path, handler):
        responses1 = _send(sock_path, [{"id": "key1", "state": "on"}])
        responses2 = _send(sock_path, [{"id": "key2", "state": "off"}])
        assert responses1[0]["status"] == "ok"
        assert responses2[0]["status"] == "ok"
        assert len(handler.calls) == 2
