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
    # keys that do nothing ("Blank N" padding) are not offered, but stay in the presets
    hidden = [k["label"] for k in keys if builder.inert(k)]
    assert all(l.startswith("Blank ") for l in hidden)
    assert set(hidden) <= set(data["presets"][0]["keys"])
    blank = {"position": [0, 0], "label": "Blank 99", "icon_type": "static",
             "icons": {"default": "blank.bmp"}, "action": None}
    assert builder.inert(blank)
    assert not builder.inert(dict(blank, notification_id="x.y"))
    assert not builder.inert(dict(blank, action={"on_press": {"type": "script", "command": "true"}}))
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
    # the version stamp: in the page's data and a <meta> tag a text search finds
    version, _ = builder.builder_version()
    assert "<!--__BUILDER_VERSION__-->" not in page
    assert f'<meta name="generator" content="streamdeck-layout-builder {version}">' in page
    assert f'"version":"{version}"' in page


def test_version_is_the_commit(builder):
    version, day = builder.builder_version()
    # this checkout: a short hash, maybe -dirty, and its commit date
    head = version.split("-")[0]
    assert len(head) >= 7 and all(c in "0123456789abcdef" for c in head)
    assert len(day) == 10 and day[4] == "-"


def test_version_outside_git(builder, monkeypatch):
    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(builder.subprocess, "run", no_git)
    assert builder.builder_version() == ("unknown", "")


@pytest.mark.parametrize("name", ["display-control.json", "display-control-3x2.json"])
def test_every_key_says_what_it_does(name):
    """The builder's tooltip and info box explain each key with its description."""
    with open(os.path.join(os.path.dirname(CONFIG), name)) as f:
        keys = json.load(f)["keys"]
    missing = [k["label"] for k in keys if len(k.get("description", "")) < 20]
    assert not missing, f"keys without a description: {missing}"


def test_descriptions_reach_the_page(builder):
    data = builder.build_data(CONFIG)
    home = next(k for k in data["keys"] if k["label"] == "Home")
    assert "home screen" in home["description"]


def test_retired_labels_map_to_their_successor(builder):
    # older USB files and saved layouts name Player Stop / Cluster Stop
    data = builder.build_data(CONFIG)
    assert data["aliases"] == {"Player Stop": "Stop", "Cluster Stop": "Stop"}
    assert not {"Player Stop", "Cluster Stop"} & {k["label"] for k in data["keys"]}
