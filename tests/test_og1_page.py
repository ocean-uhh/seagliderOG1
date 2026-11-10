"""The OG1 format page: conformance, OG1 variables, per-dive parameters, passed through.

On the bundled sg271 sample (basestation 3.0.6, dives 1-3).
"""

import pathlib

import pytest
import xarray as xr

from seagliderOG1 import _convert, vocabularies, writers
from seagliderOG1.reports import og1

ROOT = pathlib.Path(__file__).resolve().parents[1]
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory):
    path = _convert._convert_mission(
        SG271, tmp_path_factory.mktemp("sg271_og1"), report=True
    )
    ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
    yield path, ds
    ds.close()


def test_conformance_covers_every_requirement(sg271):
    """Every required global, the dimension and every required variable is checked once;
    the file meets the mandatory globals and variables."""
    _path, ds = sg271
    rows = og1.conformance_rows(ds)
    names = [r["name"] for r in rows]
    for tier in vocabularies.REQUIRED_GLOBALS.values():
        assert set(tier) <= set(names)
    assert set(vocabularies.OG1_REQUIRED_VARS) <= set(names)
    mandatory = [
        r
        for r in rows
        if r["tier"] == "mandatory" and r["kind"] != "every OG1 variable"
    ]
    assert all(r["met"] for r in mandatory)


def test_units_check_finds_the_deployment_variables(sg271):
    """DEPLOYMENT_LATITUDE and _LONGITUDE carry no units in the file, so the units check
    names them (a fix still to make in the converter)."""
    rows = og1.conformance_rows(sg271[1])
    units = next(r for r in rows if r["name"] == "units as the OG1 table")
    assert not units["met"]
    assert "DEPLOYMENT_LATITUDE" in units["value"]


def test_og1_variables_are_grouped(sg271):
    """Coordinates come first and hold the four OG1 coordinates; PHASE is built by the
    converter; no group holds a per-dive JSON parameter."""
    groups = dict(og1.og1_variable_groups(sg271[1]))
    assert [r["name"] for r in groups["Coordinates"]] == [
        "DEPTH",
        "LATITUDE",
        "LONGITUDE",
        "TIME",
    ]
    assert "PHASE" in {r["name"] for r in groups["Built by the converter"]}
    assert "GLIDE_SPEED" in {r["name"] for r in groups["Measured and model"]}
    for rows in groups.values():
        assert all(r["dtype"] != "text (JSON)" for r in rows)


def test_value_runs():
    """Equal consecutive values form one run; a missing value is a run of its own."""
    assert og1.value_runs([1, 2, 3, 4], [5, 5, None, 6]) == [
        (1, 2, 5),
        (3, 3, None),
        (4, 4, 6),
    ]


def test_per_dive_parameters_are_summarised(sg271):
    """Each per-dive parameter has one line over the mission; few runs are listed by dive
    range, so the table does not grow with the number of dives."""
    og1_rows, families = og1.per_dive_rows(sg271[1])
    rows = og1_rows + [r for _family, fam in families for r in fam]
    by_name = {r["name"]: r for r in rows}
    assert "log_C_PITCH" in by_name
    assert by_name["log_C_PITCH"]["runs"] == ["dive 1: 2050", "dives 2–3: 2300"]
    assert all(len(r["runs"]) <= og1.MAX_RUNS for r in rows)


def test_passthrough_keeps_basestation_names(sg271):
    """Passed-through variables are those whose original_name is their own name, grouped
    by the basestation dimension; gc_event is one of the groups."""
    _path, ds = sg271
    groups = dict(og1.passthrough_groups(ds))
    assert "gc_event" in groups
    for rows in groups.values():
        for r in rows:
            assert ds[r["name"]].attrs.get("original_name") == r["name"]


def test_page_written_with_the_report_and_linked(sg271):
    """The OG1 format page is written with the report; the Conversion page's globals
    section points to it, and its nav pill is a link."""
    path = sg271[0]
    page = writers.page_path(path, "og1")
    html = page.read_text(encoding="utf-8")
    assert '<section id="conformance">' in html and '<section id="globals">' in html
    conversion = writers.conversion_path(path, ".html").read_text(encoding="utf-8")
    assert f'href="{page.name}#globals"' in conversion
    assert f'href="{page.name}"' in conversion
