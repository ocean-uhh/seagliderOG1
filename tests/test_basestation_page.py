"""The Basestation page: what the dive files held, across the mission.

On the bundled sg271 sample (dives 1-3), whose raw files are read here directly to check
what the page says about them.
"""

import pathlib

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, writers
from seagliderOG1.reports import _pages, _record, basestation

ROOT = pathlib.Path(__file__).resolve().parents[1]
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory):
    path = _convert._convert_mission(
        SG271, tmp_path_factory.mktemp("sg271_basestation"), report=True
    )
    return path, _record.conversion_sidecar(path)


def test_heatmap_sizes_are_the_files_dimension_sizes(sg271):
    """Each cell's size is the dimension's size in that dive file; string lengths are
    left out."""
    path, record = sg271
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        durations = basestation.dive_durations(ds)
    dives, rows = basestation.dimension_heatmap(record["inputs"], durations)
    assert dives == [1, 2, 3]
    by_name = {r["name"]: r for r in rows}
    assert not any(name.startswith("string_") for name in by_name)
    sizes = []
    for raw_path in sorted(SG271.glob("p*.nc")):
        with xr.open_dataset(raw_path, engine="netcdf4", decode_timedelta=False) as raw:
            sizes.append(raw.sizes["ctd_data_point"])
    row = by_name["ctd_data_point"]
    assert row["median_size"] == int(np.median(sizes))
    assert row["dives"] == 3
    titles = [c["title"] for c in row["cells"]]
    assert all(
        f"{size:,} samples" in title for title, size in zip(titles, sizes, strict=True)
    )


def test_durations_are_positive_minutes(sg271):
    """A dive lasts from its first to its last data point, in minutes."""
    path, _record_ = sg271
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        durations = basestation.dive_durations(ds)
    assert set(durations) == {1, 2, 3}
    assert all(10 < minutes < 24 * 60 for minutes in durations.values())


def test_presence_patterns_hold_only_variables_missing_from_a_dive(sg271):
    """A pattern lists variables not in every dive; each is absent from one raw file."""
    _path, record = sg271
    patterns = basestation.presence_patterns(record["presence"], [1, 2, 3])
    files = sorted(SG271.glob("p*.nc"))
    names = []
    for raw_path in files:
        with xr.open_dataset(raw_path, engine="netcdf4", decode_timedelta=False) as raw:
            names.append(set(raw.variables))
    everywhere = set.intersection(*names)
    for pattern in patterns:
        assert pattern["count"] < 3
        assert not set(pattern["variables"]) & everywhere


def test_globals_split_expected_from_unexpected(sg271):
    """The sg271 globals with more than one value are split: dive number and times are
    expected; the rest are highlighted; one with a single value is not listed."""
    _path, record = sg271
    found = record["basestation_globals"]
    unexpected, expected = basestation.differing_globals(found)
    listed = {r["name"] for r in unexpected + expected}
    assert listed == {name for name, e in found.items() if len(e["values"]) > 1}
    assert "dive_number" in {r["name"] for r in expected}
    assert not {r["name"] for r in unexpected} & basestation.EXPECTED_TO_DIFFER
    assert all(r["count"] > 1 for r in unexpected + expected)


def test_a_missing_time_does_not_stretch_a_dive(sg271):
    """A NaT in TIME is left out of the dive's span, not read as a large number."""
    path, _record_ = sg271
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        before = basestation.dive_durations(ds)
        time = ds["TIME"].values.copy()
        first = int(np.flatnonzero(ds["dive_number"].values == 1)[0])
        time[first + 1] = np.datetime64("NaT")
        after = basestation.dive_durations(ds.assign(TIME=("N_MEASUREMENTS", time)))
    assert after[1] <= before[1]
    assert after[1] > 0


def test_every_variable_is_listed_once_by_dimension(sg271):
    """The variables table holds each recorded input once, in its dimension's group."""
    _path, record = sg271
    groups = basestation.variables_by_dimension(
        record["input_variables"], record["presence"]
    )
    names = [r["name"] for _dim, rows in groups for r in rows]
    assert sorted(names) == sorted(record["input_variables"])
    by_dim = dict(groups)
    assert "temperature" in {r["name"] for r in by_dim["ctd_data_point"]}


def test_page_is_written_and_linked(sg271):
    """The report writes the page; it is current on its inventory pill, numbers its
    sections, and every other page links to it."""
    path, _record_ = sg271
    page = writers.page_path(path, "basestation")
    html = page.read_text(encoding="utf-8")
    assert "file-pill file-pill-active" in html
    assert '<a href="#dimensions">(1) Dimension sizes</a>' in html
    assert "(5) Variables by dimension" in html
    for kind in ("variables", "processing", "og1"):
        other = writers.page_path(path, kind).read_text(encoding="utf-8")
        assert f'href="{page.name}"' in other, kind


def test_no_page_without_a_record(tmp_path):
    """Without the conversion record nothing describes the dive files, so no page."""
    path = _convert._convert_mission(SG271, tmp_path)
    writers.conversion_path(path, ".json").unlink()
    assert basestation.render_basestation(path) is None


def test_a_gap_in_the_dive_numbers_is_not_counted(sg271):
    """A range over a missing dive counts only the dives the mission has, in the
    patterns and the variables table. The sg271 record with dive 2 removed stands in for
    a mission whose second file was rejected."""
    _path, record = sg271
    presence = {
        "dives": [1, 3],
        "variables": {
            name: {"present": [[1, 3]]} for name in list(record["input_variables"])[:2]
        },
    }
    groups = basestation.variables_by_dimension(
        {n: record["input_variables"][n] for n in presence["variables"]}, presence
    )
    assert {r["dives"] for _dim, rows in groups for r in rows} == {2}


def test_nav_without_file_paths(sg271):
    """A record of datasets not read from files (path None) labels the pill by dive."""
    _path, record = sg271
    inputs = [dict(entry, path=None) for entry in record["inputs"]]
    assert _pages._basestation_label(inputs) == "dives 1–3"
