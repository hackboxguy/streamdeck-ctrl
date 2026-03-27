"""Action executor: script (subprocess) and HTTP (requests) with token substitution."""

import json
import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Shared thread pool for async action execution
_executor = None
_executor_lock = threading.Lock()


def get_executor(max_workers=4):
    """Get or create the shared ThreadPoolExecutor."""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=max_workers)
        return _executor


def shutdown_executor():
    """Shutdown the thread pool. Call on daemon exit."""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False)
            _executor = None


def substitute_tokens(text, context):
    """Replace {state}, {value}, {label}, {key_pos} tokens in a string.

    Args:
        text: String with tokens to replace.
        context: dict with keys: state, value, label, key_pos.

    Returns:
        String with tokens replaced.
    """
    if not isinstance(text, str):
        return text
    result = text
    for token, key in [("{state}", "state"), ("{value}", "value"),
                       ("{label}", "label"), ("{key_pos}", "key_pos")]:
        if token in result and key in context:
            result = result.replace(token, str(context[key]))
    return result


def _substitute_in_obj(obj, context):
    """Recursively substitute tokens in dicts, lists, and strings."""
    if isinstance(obj, str):
        return substitute_tokens(obj, context)
    elif isinstance(obj, dict):
        return {k: _substitute_in_obj(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_in_obj(item, context) for item in obj]
    return obj


def execute_action(action_config, context):
    """Execute an action (script or HTTP) with token substitution.

    Args:
        action_config: The action config dict (contains on_press).
        context: dict with state, value, label, key_pos for token substitution.
    """
    if action_config is None:
        return

    on_press = action_config.get("on_press")
    if on_press is None:
        return

    is_async = on_press.get("async", False)
    action_type = on_press["type"]

    if is_async:
        get_executor().submit(_run_action, action_type, on_press, context)
    else:
        _run_action(action_type, on_press, context)


def _run_action(action_type, on_press, context):
    """Dispatch and run the action."""
    try:
        if action_type == "script":
            _run_script(on_press, context)
        elif action_type == "http":
            _run_http(on_press, context)
        else:
            logger.error("Unknown action type: %s", action_type)
    except Exception:
        logger.exception("Action execution failed (type=%s)", action_type)


def _run_script(on_press, context):
    """Execute a script action via subprocess."""
    command = substitute_tokens(on_press["command"], context)
    logger.info("Executing script: %s", command)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "Script exited with code %d: %s\nstderr: %s",
                result.returncode, command, result.stderr.strip(),
            )
        else:
            logger.debug("Script completed: %s", command)
        return result
    except subprocess.TimeoutExpired:
        logger.error("Script timed out: %s", command)
        return None


def _run_http(on_press, context):
    """Execute an HTTP action via requests."""
    import requests

    method = on_press["method"].upper()
    url = substitute_tokens(on_press["url"], context)
    timeout = on_press.get("timeout_sec", 5)
    headers = _substitute_in_obj(on_press.get("headers", {}), context)
    body = _substitute_in_obj(on_press.get("body"), context)

    logger.info("Executing HTTP %s %s", method, url)
    try:
        kwargs = {"timeout": timeout, "headers": headers}
        if body is not None:
            kwargs["json"] = body

        response = requests.request(method, url, **kwargs)
        logger.debug("HTTP %s %s → %d", method, url, response.status_code)
        return response
    except requests.Timeout:
        logger.warning("HTTP timeout: %s %s", method, url)
        return None
    except requests.RequestException as e:
        logger.error("HTTP error: %s %s → %s", method, url, e)
        return None
