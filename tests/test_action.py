"""Tests for streamdeck_ctrl.action — token substitution and execution."""

import subprocess
from unittest.mock import patch, MagicMock
import pytest

from streamdeck_ctrl.action import (
    substitute_tokens,
    execute_action,
    _run_script,
    _run_http,
    _substitute_in_obj,
    shutdown_executor,
)


@pytest.fixture(autouse=True)
def _cleanup_executor():
    yield
    shutdown_executor()


# ---------------------------------------------------------------------------
# Token substitution
# ---------------------------------------------------------------------------


class TestTokenSubstitution:
    def test_substitute_state(self):
        assert substitute_tokens("echo {state}", {"state": "on"}) == "echo on"

    def test_substitute_value(self):
        assert substitute_tokens("{value}°C", {"value": "42"}) == "42°C"

    def test_substitute_label(self):
        assert substitute_tokens("key: {label}", {"label": "Backlight"}) == "key: Backlight"

    def test_substitute_key_pos(self):
        assert substitute_tokens("pos={key_pos}", {"key_pos": "0,2"}) == "pos=0,2"

    def test_substitute_multiple(self):
        result = substitute_tokens(
            "{label} is {state}", {"label": "Light", "state": "on"}
        )
        assert result == "Light is on"

    def test_no_tokens(self):
        assert substitute_tokens("plain text", {"state": "on"}) == "plain text"

    def test_missing_context_key(self):
        assert substitute_tokens("{state}", {}) == "{state}"

    def test_non_string_passthrough(self):
        assert substitute_tokens(42, {"state": "on"}) == 42

    def test_substitute_in_dict(self):
        obj = {"mode": "{state}", "pos": "{key_pos}"}
        result = _substitute_in_obj(obj, {"state": "hdr", "key_pos": "0,2"})
        assert result == {"mode": "hdr", "pos": "0,2"}

    def test_substitute_in_nested(self):
        obj = {"body": {"mode": "{state}", "items": ["{label}"]}}
        result = _substitute_in_obj(obj, {"state": "hdr", "label": "Test"})
        assert result == {"body": {"mode": "hdr", "items": ["Test"]}}


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


class TestScriptExecution:
    @patch("streamdeck_ctrl.action.subprocess.run")
    def test_script_called_with_substituted_command(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        on_press = {"type": "script", "command": "echo {state}"}
        context = {"state": "on"}
        _run_script(on_press, context)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == "echo on"
        assert call_args[1]["shell"] is True

    @patch("streamdeck_ctrl.action.subprocess.run")
    def test_script_nonzero_exit_logged(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error msg")
        on_press = {"type": "script", "command": "fail.sh"}
        result = _run_script(on_press, {})
        assert result.returncode == 1

    @patch("streamdeck_ctrl.action.subprocess.run")
    def test_script_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
        on_press = {"type": "script", "command": "slow.sh"}
        result = _run_script(on_press, {})
        assert result is None


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------


class TestHTTPExecution:
    @patch("requests.request")
    def test_http_get(self, mock_req):
        mock_resp = MagicMock(status_code=200)
        mock_req.return_value = mock_resp
        on_press = {
            "type": "http",
            "method": "GET",
            "url": "http://localhost/api?state={state}",
        }
        result = _run_http(on_press, {"state": "on"})
        mock_req.assert_called_once()
        assert "http://localhost/api?state=on" in str(mock_req.call_args)

    @patch("requests.request")
    def test_http_post_with_body(self, mock_req):
        mock_req.return_value = MagicMock(status_code=200)
        on_press = {
            "type": "http",
            "method": "POST",
            "url": "http://localhost/api",
            "body": {"mode": "{state}"},
        }
        _run_http(on_press, {"state": "hdr"})
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"] == {"mode": "hdr"}

    @patch("requests.request")
    def test_http_with_headers(self, mock_req):
        mock_req.return_value = MagicMock(status_code=200)
        on_press = {
            "type": "http",
            "method": "GET",
            "url": "http://localhost/api",
            "headers": {"X-Key": "{label}"},
        }
        _run_http(on_press, {"label": "Backlight"})
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["headers"]["X-Key"] == "Backlight"

    @patch("requests.request")
    def test_http_timeout(self, mock_req):
        import requests
        mock_req.side_effect = requests.Timeout("timed out")
        on_press = {
            "type": "http",
            "method": "GET",
            "url": "http://localhost/api",
            "timeout_sec": 1,
        }
        result = _run_http(on_press, {})
        assert result is None

    @patch("requests.request")
    def test_http_connection_error(self, mock_req):
        import requests
        mock_req.side_effect = requests.ConnectionError("refused")
        on_press = {
            "type": "http",
            "method": "GET",
            "url": "http://localhost/api",
        }
        result = _run_http(on_press, {})
        assert result is None


# ---------------------------------------------------------------------------
# execute_action dispatcher
# ---------------------------------------------------------------------------


class TestExecuteAction:
    def test_none_action_noop(self):
        execute_action(None, {})  # should not raise

    def test_no_on_press_noop(self):
        execute_action({}, {})  # should not raise

    @patch("streamdeck_ctrl.action._run_action")
    def test_sync_action_called_directly(self, mock_run):
        action = {"on_press": {"type": "script", "command": "echo", "async": False}}
        execute_action(action, {"state": "on"})
        mock_run.assert_called_once_with("script", action["on_press"], {"state": "on"})

    @patch("streamdeck_ctrl.action._run_action")
    def test_async_action_submitted_to_pool(self, mock_run):
        action = {"on_press": {"type": "script", "command": "echo", "async": True}}
        execute_action(action, {"state": "on"})
        # Give the thread pool a moment to pick up the task
        import time
        time.sleep(0.1)
        mock_run.assert_called_once()
