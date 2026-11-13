"""The masthead and nav every report page shares, on the bundled sg271 sample."""

import pathlib

import pytest

from seagliderOG1 import _convert, writers
from seagliderOG1.reports import _masthead, _pages, og1

ROOT = pathlib.Path(__file__).parent.resolve().parents[1]
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return _convert._convert_mission(
        SG271, tmp_path_factory.mktemp("sg271_masthead"), report=True
    )


def test_title_and_facts(sg271):
    """Without a site the title is the file's id; the grid holds the deployment's facts,
    the position in degrees and minutes, and the losses as a warning."""
    m = _masthead.masthead(sg271, "conversion")
    assert m["title"] == sg271.stem
    assert (m["type"], m["role"]) == ("Conversion", "landing")
    facts = {label: (value, warn) for label, value, warn in m["facts"]}
    assert facts["Glider"][0].startswith("sg271")
    assert facts["Deployed"][0].endswith(" UTC")
    assert (
        facts["Deployment position"][0].endswith("E")
        and "°" in facts["Deployment position"][0]
    )
    assert facts["Dives"][0] == "3 (1–3)"
    assert facts["Losses"][1] is True
    assert "seagliderOG1 version" not in facts


def test_every_page_type_and_title_override(sg271):
    """Every page has its own type label; a title passed in replaces the built one."""
    for kind, (label, _subtitle, _role) in _masthead.PAGE_TYPES.items():
        assert _masthead.masthead(sg271, kind)["type"] == label
    assert _masthead.masthead(sg271, "variables", title="x")["title"] == "x"


def test_nav_rows_and_inventory(sg271):
    """Pages and Provenance rows, then the inventory strip: the dive files (linking to the
    Basestation page) and the OG1 file (linking to its OG1 format page, current there); a
    draft keeps the dive files but has no OG1 pill."""
    nav = _pages.page_nav(sg271, "variables")
    assert [row["label"] for row in nav["rows"]] == ["Pages:", "Provenance:"]
    labels = [p["label"] for row in nav["rows"] for p in row["pills"]]
    assert labels == ["Conversion", "Phase", "Variables", "Processing"]
    assert nav["inventory"] == [
        {
            "state": "link",
            "label": "p2710001–0003.nc",
            "href": writers.page_path(sg271, "basestation").name,
        },
        {
            "state": "link",
            "label": sg271.name,
            "href": writers.page_path(sg271, "og1").name,
        },
    ]
    assert _pages.page_nav(sg271, "og1")["inventory"][1]["state"] == "current"
    assert _pages.page_nav(sg271, "basestation")["inventory"][0]["state"] == "current"
    draft = _pages.page_nav(sg271, "conversion", draft=True)["inventory"]
    assert [p["label"] for p in draft] == ["p2710001–0003.nc"]


def test_sections_are_numbered_then_lettered():
    """Sections number (1), (2), …; reference sections letter (A), …; a left-out section
    takes no number, so the jump-to line and the headings agree."""
    secs = _pages.number_sections(
        [("a", "A"), None, ("b", "B"), ("g", "Glossary", "reference")]
    )
    assert [(s["id"], s["mark"]) for s in secs["items"]] == [
        ("a", "(1)"),
        ("b", "(2)"),
        ("g", "(A)"),
    ]
    assert secs["mark"]["g"] == "(A)"


def test_strip_cells_shade_numbers_and_alternate_text():
    """Numbers shade light to dark by value; text alternates shades by run; a dive with no
    value has no cell."""
    cells, legend = og1.strip_cells([1, 2, 3], [0.0, None, 1.0])
    assert [c["fill"] for c in cells] == [og1.STRIP_RAMP[0], og1.STRIP_RAMP[-1]]
    assert legend == "light 0, dark 1"
    cells, _legend = og1.strip_cells([1, 2, 3], ["a", "a", "b"])
    assert [c["fill"] for c in cells] == list(og1.STRIP_RUN_SHADES)
    assert cells[0]["title"] == "dives 1–2: a"
