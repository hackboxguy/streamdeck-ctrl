"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_usb_scan(monkeypatch, request):
    """Daemons under test never look at this machine's real USB sticks."""
    if request.node.get_closest_marker("real_usb_scan"):
        return
    monkeypatch.setattr("streamdeck_ctrl.daemon.find_override", lambda *a, **k: None)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_usb_scan: let the daemon call find_override (tests fake the stick)")
