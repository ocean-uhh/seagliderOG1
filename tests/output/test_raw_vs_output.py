"""The written OG1 file against the raw basestation files, line by line of two tables.

``tests/data/raw_vs_output.csv``: each line names a raw variable, its OG1 variable, how they
relate and the tolerance. ``tests/data/og1_names.csv``: each line names a basestation variable,
the OG1 name it is written under, its units and its sensor record. A line whose status starts ``known:`` is a
strict expected failure: it fails today, and the test reports it if it starts passing, so the
marker is removed when the fix lands.

Data: the sg271 sample (three dives) and the sg005 demo (five dives), converted once each
(``converted_missions`` in conftest.py). The written file is opened per test (not held open by
the fixture) — see the fixture docstring for why.
"""

import json
import pathlib
import re

import numpy as np
import pytest
import xarray as xr
from conftest import read_table

from seagliderOG1 import _convert

#: Two times are the same instant when they differ by less than this (seconds). The file
#: stores TIME through nanosecond datetimes, which moves a raw time by up to one rounding
#: step of a float (2.4e-7 s at these dates).
SAME_TIME = 1e-6

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"


def _params(rows: list[dict], label) -> list:
    """One pytest parameter per table line; a ``known:`` line is a strict expected failure."""
    out = []
    for row in rows:
        marks = []
        if row["status"].startswith("known:"):
            marks.append(pytest.mark.xfail(strict=True, reason=row["status"]))
        out.append(pytest.param(row, id=label(row), marks=marks))
    return out


CHECKS = read_table(DATA / "raw_vs_output.csv")
NAMES = read_table(DATA / "og1_names.csv")


def _dive(raw: xr.Dataset) -> int:
    return int(raw.attrs["dive_number"])


# --- Raw vs output ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check", _params(CHECKS, lambda r: f"{r['mission']}-{r['check']}-{r['og1']}")
)
def test_raw_vs_output(check: dict, converted_missions: dict) -> None:
    """One line of raw_vs_output.csv holds on the converted mission."""
    path, raws = converted_missions[check["mission"]]
    og1, src, relation = check["og1"], check["basestation"], check["relation"]
    tol = float(check["tolerance"])
    with xr.open_dataset(path, engine="netcdf4", decode_times=False) as ds:
        dive_of = ds["dive_number"].values
        time = ds["TIME"].values

        if relation == "equal":
            factor = float(check["factor"])
            out_time = (
                ds["TIME_GPS"].values if check["axis"] == "log_gps_time" else time
            )
            out_values = ds[og1].values.astype(float)
            # The only raw points allowed to be absent are the GPS fixes the file records
            # as dropped (a fix logged again at a dive boundary).
            allowed_absent = (
                len(json.loads(ds.attrs.get("conversion_dropped_gps_fixes") or "[]"))
                if check["axis"] == "log_gps_time"
                else 0
            )
            worst, compared, absent, lost = 0.0, 0, 0, 0
            for raw in raws:
                axis = raw[check["axis"]].values.astype(float)
                values = raw[src].values.astype(float)
                rows = np.flatnonzero((dive_of == _dive(raw)) & np.isfinite(out_time))
                rows = rows[np.argsort(out_time[rows], kind="stable")]
                times = out_time[rows]
                if times.size == 0:
                    absent += axis.size
                    continue
                # For each raw point, the output data point of this dive nearest in time.
                right = np.clip(np.searchsorted(times, axis), 0, times.size - 1)
                left = np.clip(right - 1, 0, times.size - 1)
                nearest = np.where(
                    np.abs(times[left] - axis) <= np.abs(times[right] - axis),
                    left,
                    right,
                )
                found = np.abs(times[nearest] - axis) <= SAME_TIME
                absent += int((~found).sum())
                diff = out_values[rows[nearest[found]]] - factor * values[found]
                has_raw = np.isfinite(values[found])
                lost += int((~np.isfinite(diff[has_raw])).sum())
                diff = diff[np.isfinite(diff)]
                compared += diff.size
                if diff.size:
                    worst = max(worst, float(np.max(np.abs(diff))))
            assert compared > 0, "no data point of the raw axis found in the file"
            assert absent == allowed_absent, (
                f"{absent} raw points are not on the file's time axis "
                f"({allowed_absent} recorded as dropped)"
            )
            assert lost == 0, f"{lost} raw values are missing in the file"
            assert worst <= tol, f"largest difference {worst:.3g} > {tol}"

        elif relation == "count":
            raw_count = sum(_convert.count_values(r[src].values) for r in raws)
            assert _convert.count_values(ds[og1].values) == raw_count

        elif relation == "gps_fixes":
            raw_fixes = sum(r[src].size for r in raws)
            out_fixes = _convert.count_values(ds[og1].values)
            dropped = json.loads(ds.attrs.get("conversion_dropped_gps_fixes") or "[]")
            assert out_fixes == raw_fixes - len(dropped)

        elif relation == "missing_at_fixes":
            at_fix = np.isfinite(ds["TIME_GPS"].values)
            assert not np.isfinite(ds[og1].values[at_fix]).any()

        elif relation == "no_missing_on_read":
            assert not np.isnan(ds[og1].values.astype(float)).any()

        else:
            pytest.fail(f"unknown relation {relation!r} in raw_vs_output.csv")


# --- Names and units ----------------------------------------------------------------------


def _base(name: str) -> str:
    """An OG1 name without a copy number: DEPTH_2 -> DEPTH (which copy is which does not matter)."""
    return re.sub(r"_\d+$", "", name)


@pytest.mark.parametrize(
    "row", _params(NAMES, lambda r: f"{r['mission']}-{r['basestation']}")
)
def test_basestation_name_becomes_the_og1_name(
    row: dict, converted_missions: dict
) -> None:
    """One line of og1_names.csv: the basestation variable is written under that OG1 name and
    units and points to that sensor record (or, with no OG1 name, is not under an OG1 name
    at all)."""
    path, _raws = converted_missions[row["mission"]]
    with xr.open_dataset(path, engine="netcdf4", decode_times=False) as ds:
        written = [
            str(v)
            for v in ds.variables
            if ds[v].attrs.get("original_name") == row["basestation"]
        ]
        renamed = [v for v in written if v != row["basestation"]]
        if not row["og1"]:
            assert not renamed, f"written as {renamed}"
            return
        assert [_base(v) for v in renamed] == [_base(row["og1"])], (
            f"written as {renamed}"
        )
        assert str(ds[renamed[0]].attrs.get("units", "")) == row["units"]
        assert str(ds[renamed[0]].attrs.get("sensor", "")) == row["sensor"]


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_every_renamed_variable_is_in_the_table(
    mission: str, converted_missions: dict
) -> None:
    """No basestation variable is written under a new name the table does not list."""
    path, _raws = converted_missions[mission]
    listed = {r["basestation"] for r in NAMES if r["mission"] == mission}
    with xr.open_dataset(path, engine="netcdf4", decode_times=False) as ds:
        renamed = {
            ds[v].attrs["original_name"]
            for v in ds.variables
            if ds[v].attrs.get("original_name") not in (None, str(v))
            and not str(ds[v].attrs["original_name"]).startswith(("{", "["))
        }
    assert renamed <= listed, f"not in og1_names.csv: {sorted(renamed - listed)}"
