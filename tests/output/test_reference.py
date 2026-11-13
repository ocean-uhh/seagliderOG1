"""The written file against a stored, readable reference of itself.

``tests/data/reference/<mission>.csv`` holds one line per variable of the written file: dtype,
dimensions, units, fill value, number of values, and min / median / max for numbers. Any change
to the output shows up as a line-by-line diff of that file in a PR. When a change is intended,
regenerate it and commit the diff with the change that caused it::

    SEAGLIDEROG1_UPDATE_REFERENCE=1 pytest tests/output/test_reference.py

Data: the sg271 sample (three dives) and the sg005 demo (five dives), converted once each
(``converted_missions`` in conftest.py).
"""

import csv
import math
import os
import pathlib

import numpy as np
import pytest
import xarray as xr
from conftest import read_table

REFERENCE = pathlib.Path(__file__).resolve().parents[1] / "data" / "reference"
FIELDS = [
    "variable",
    "dtype",
    "dims",
    "units",
    "fill_value",
    "count",
    "min",
    "median",
    "max",
]
# Relative tolerance on min / median / max: float32 precision, so a different numpy or platform
# does not fail it while a real change does.
RTOL = 1e-6


def _summary(path: pathlib.Path) -> list[dict]:
    """One line per variable of the written file, as stored on disk (no decoding)."""
    rows = []
    with xr.open_dataset(
        path, engine="netcdf4", decode_times=False, mask_and_scale=False
    ) as ds:
        for name in sorted(ds.variables, key=str):
            var = ds[name]
            values = np.asarray(var.values)
            fill = var.attrs.get("_FillValue", var.encoding.get("_FillValue"))
            row = {
                "variable": str(name),
                "dtype": str(values.dtype),
                "dims": " ".join(var.dims),
                "units": str(var.attrs.get("units", "")),
                "fill_value": "" if fill is None else str(fill),
                "count": "",
                "min": "",
                "median": "",
                "max": "",
            }
            if values.dtype.kind in "fiu":
                v = values.astype(float).ravel()
                if fill is not None:
                    v = v[v != float(fill)]
                v = v[np.isfinite(v)]
                row["count"] = str(v.size)
                if v.size:
                    row["min"], row["median"], row["max"] = (
                        f"{x:.9g}" for x in (v.min(), np.median(v), v.max())
                    )
            else:
                row["count"] = str(values.size)
            rows.append(row)
    return rows


def _write(mission: str, rows: list[dict]) -> None:
    REFERENCE.mkdir(parents=True, exist_ok=True)
    with (REFERENCE / f"{mission}.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(
            f"# Reference of the written OG1 file for {mission} (bundled raw files, no mission file).\n"
            "# Regenerate only for an intended output change: "
            "SEAGLIDEROG1_UPDATE_REFERENCE=1 pytest tests/output/test_reference.py\n"
        )
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _close(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return math.isclose(float(a), float(b), rel_tol=RTOL, abs_tol=0.0)
    except ValueError:
        return False


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_written_file_matches_the_reference(
    mission: str, converted_missions: dict
) -> None:
    """Every variable, and every field of it, is as in the stored reference."""
    path, _raws = converted_missions[mission]
    now = _summary(path)
    if os.environ.get("SEAGLIDEROG1_UPDATE_REFERENCE"):
        _write(mission, now)
        pytest.skip(f"reference for {mission} rewritten")
    stored = {r["variable"]: r for r in read_table(REFERENCE / f"{mission}.csv")}
    current = {r["variable"]: r for r in now}
    problems = [f"new variable {v}" for v in sorted(set(current) - set(stored))]
    problems += [f"variable gone: {v}" for v in sorted(set(stored) - set(current))]
    for v in sorted(set(stored) & set(current)):
        for field in FIELDS[1:]:
            a, b = stored[v][field], current[v][field]
            # count, dtype, dims, units and fill are exact; only the numeric summary
            # stats carry a tolerance (a different numpy must not fail an unchanged file).
            close = _close(a, b) if field in ("min", "median", "max") else a == b
            if not close:
                problems.append(f"{v}.{field}: {a!r} -> {b!r}")
    assert not problems, "\n".join(problems[:40]) + (
        f"\n... and {len(problems) - 40} more" if len(problems) > 40 else ""
    )
