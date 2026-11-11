"""Tests for tools/layout-builder/make-layout-builder.py."""

import importlib.util
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "layout-builder", "make-layout-builder.py")
CONFIG = os.path.join(REPO, "screens", "display-control", "display-control.json")


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("make_layout_builder", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_superset_key_with_icon_and_deps(builder):
    data = builder.build_data(CONFIG)
    with open(CONFIG) as f:
        keys = json.load(f)["keys"]
    labels = [k["label"] for k in keys if not builder.inert(k)]
    assert [k["label"] for k in data["keys"]] == labels
    # the "Blank N" padding keys do nothing: not offered, but still in the presets
    hidden = [k["label"] for k in keys if builder.inert(k)]
    assert hidden and all(l.startswith("Blank ") for l in hidden)
    assert set(hidden) <= set(data["presets"][0]["keys"])
    assert all(k["icon"] and k["icon"].startswith("data:image/png;base64,") for k in data["keys"])
    pix = next(k for k in data["keys"] if k["label"] == "Pixel Compensation")
    assert pix["needs"] == ["Local Dimming"]
    assert [p["name"].split(" ")[0] for p in data["presets"]] == ["Everything",
                                                                  "display-control-3x2.json"]


def test_page_is_self_contained(builder, tmp_path, monkeypatch):
    out = tmp_path / "b.html"
    monkeypatch.setattr("sys.argv", ["x", "--config", CONFIG, "-o", str(out)])
    builder.main()
    page = out.read_text()
    assert "/*__BUILDER_DATA__*/null" not in page
    # no external resources: nothing loaded by src= / href= from the network
    assert 'src="http' not in page and 'href="http' not in page
    assert '"superset":"display-control.json"' in page
