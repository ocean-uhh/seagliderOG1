"""The Basestation page: an inventory of a mission's basestation dive files.

A plain description of the input, with no conversion information (that is on the
Conversion, Variables and Processing pages). Built from the conversion record (what each
dive file held) and the OG1 file (dive durations and the per-dive parameters), so it needs
no dive file, and it stays the same size for a mission of 600 dives:

1. **Dimension sizes by dive**: a heatmap, one row per dimension, one column per dive,
   shaded by samples per minute of dive, so a steady sample rate is one even colour
   whatever the depth, a rate change shows as a step, and a dropout as a gap.
2. **Variables not in every dive**: one strip per presence pattern (the variables that
   are in exactly the same dives), with the variables it holds.
3. **Parameters that change between dives**: change points, or a range and a strip.
4. **Salinity**: the basestation's salinity against salinity recomputed from its
   conductivity, so the size of its corrections is visible, overall and by dive.
5. **Global attributes that differ between files**: the ones expected to (times, dive
   number, bounds) folded; any other highlighted.
6. **Variables by dimension**, over the whole mission.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import gsw
import numpy as np
import xarray as xr

from seagliderOG1 import __version__, vocabularies
from seagliderOG1.reports import _masthead, _pages, _record, design, og1
from seagliderOG1.reports._env import get_template

__all__ = [
    "EXPECTED_TO_DIFFER",
    "HEATMAP_WIDTH",
    "dimension_heatmap",
    "differing_globals",
    "dive_durations",
    "presence_patterns",
    "SALINITY_COMPARISONS",
    "render_basestation",
    "salinity_checks",
    "variables_by_dimension",
    "write_basestation_page",
]

#: The heatmap's and the strips' width in pixels, whatever the number of dives.
HEATMAP_WIDTH = 720

#: Global attributes a basestation file is expected to change from dive to dive.
EXPECTED_TO_DIFFER: frozenset[str] = frozenset(
    {
        "date_created",
        "date_modified",
        "dive_number",
        "history",
        "id",
        "start_time",
        "time_coverage_start",
        "time_coverage_end",
        "uuid",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_vertical_min",
        "geospatial_vertical_max",
        "instrument",
    }
)


def dive_durations(ds: xr.Dataset) -> dict[int, float]:
    """Return each dive's duration in minutes, from its first to its last data point.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset with ``dive_number`` and ``TIME`` on ``N_MEASUREMENTS``.

    Returns
    -------
    dict of int to float
        Dive number to minutes; empty when the file has no ``dive_number``.

    """
    if "dive_number" not in ds.variables or "TIME" not in ds.variables:
        return {}
    dives = np.asarray(ds["dive_number"].values, dtype=float)
    raw = np.asarray(ds["TIME"].values).astype("datetime64[s]")
    # NaT cast to float is a large finite number, not NaN, so mark it before casting.
    times = np.where(np.isnat(raw), np.nan, raw.astype("int64").astype(float))
    out: dict[int, float] = {}
    for dive in np.unique(dives[np.isfinite(dives)]):
        mine = times[(dives == dive) & np.isfinite(times)]
        if mine.size:
            out[int(dive)] = float(mine.max() - mine.min()) / 60
    return out


def dimension_heatmap(
    inputs: list[dict], durations: dict[int, float]
) -> tuple[list[int], list[dict]]:
    """Return the heatmap of dimension sizes by dive, shaded by samples per minute.

    Parameters
    ----------
    inputs : list of dict
        The conversion record's ``inputs`` (one per dive file, with ``dive`` and
        ``dimensions``).
    durations : dict of int to float
        Minutes per dive (:func:`dive_durations`).

    Returns
    -------
    dives : list of int
        The dives, in order: the columns.
    rows : list of dict
        One per dimension (string-length dimensions left out): ``name``, ``cells`` (one
        per dive with the dimension: ``x``, ``width``, ``fill``, ``title``), and the
        ``median_size``, ``median_rate`` (per minute; None for a dimension of one size
        in every dive, which is one mid shade), ``dives`` present and ``constant``.

    """
    dives = sorted(int(entry["dive"]) for entry in inputs)
    sizes: dict[str, dict[int, int]] = defaultdict(dict)
    for entry in inputs:
        for dim, size in (entry.get("dimensions") or {}).items():
            if not dim.startswith("string_"):
                sizes[dim][int(entry["dive"])] = int(size)
    width = HEATMAP_WIDTH / max(len(dives), 1)
    rows = []
    for dim in sorted(sizes, key=lambda d: -float(np.median(list(sizes[d].values())))):
        by_dive = sizes[dim]
        # A dimension of one size in every dive (one trajectory, three GPS fixes) does
        # not scale with the dive's length, so a rate would only shade the duration.
        constant = len(set(by_dive.values())) == 1
        rates = (
            {}
            if constant
            else {
                dive: size / durations[dive]
                for dive, size in by_dive.items()
                if durations.get(dive)
            }
        )
        low, high = (min(rates.values()), max(rates.values())) if rates else (0.0, 0.0)
        cells = []
        for i, dive in enumerate(dives):
            if dive not in by_dive:
                continue
            rate = rates.get(dive)
            if rate is None or high == low:
                step = len(og1.STRIP_RAMP) // 2
            else:
                step = round((rate - low) / (high - low) * (len(og1.STRIP_RAMP) - 1))
            per_minute = f", {rate:.3g} per minute" if rate is not None else ""
            cells.append(
                {
                    "x": round(i * width, 2),
                    "width": round(max(width - 0.4, 0.8), 2),
                    "fill": og1.STRIP_RAMP[step],
                    "title": f"dive {dive}: {by_dive[dive]:,} samples{per_minute}",
                }
            )
        rows.append(
            {
                "name": dim,
                "cells": cells,
                "median_size": int(np.median(list(by_dive.values()))),
                "median_rate": float(np.median(list(rates.values())))
                if rates
                else None,
                "dives": len(by_dive),
                "constant": constant,
            }
        )
    return dives, rows


def _ranges_text(ranges: list[list[int]]) -> str:
    """Return dive ranges as text: ``dives 1–150, 300–450``."""
    parts = [f"{a}" if a == b else f"{a}–{b}" for a, b in ranges]
    if len(parts) > 6:
        return f"dives {', '.join(parts[:4])} and {len(parts) - 4} more ranges"
    return (
        "dive " if len(parts) == 1 and "–" not in parts[0] else "dives "
    ) + ", ".join(parts)


def _count_dives(ranges: Iterable[Sequence[int]], dives: list[int]) -> int:
    """Return how many of the mission's dives fall in the ranges.

    A range spans a gap in the dive numbering (a missing or rejected file), so the dives
    are counted from the mission's dive list, not from the range ends.
    """
    return sum(any(a <= dive <= b for a, b in ranges) for dive in dives)


def presence_patterns(presence: dict, dives: list[int]) -> list[dict]:
    """Return the variables not in every dive, grouped by the exact dives they are in.

    Parameters
    ----------
    presence : dict
        The conversion record's ``presence`` (``dives`` and, per variable, ``present``
        as dive ranges).
    dives : list of int
        The dives, in order: the strip's columns.

    Returns
    -------
    list of dict
        One per pattern, most variables first: ``variables`` (names), ``count`` (dives
        present), ``text`` (the ranges), and ``cells`` (``x``, ``width``, ``title``, one
        per range).

    """
    all_dives = presence.get("dives") or dives
    groups: dict[tuple, list[str]] = defaultdict(list)
    for name, entry in (presence.get("variables") or {}).items():
        ranges = tuple(tuple(r) for r in entry.get("present", []))
        if ranges != ((all_dives[0], all_dives[-1]),) or len(all_dives) != (
            all_dives[-1] - all_dives[0] + 1
        ):
            in_dives = {d for a, b in ranges for d in range(a, b + 1)}
            if in_dives >= set(all_dives):
                continue
            groups[ranges].append(name)
    width = HEATMAP_WIDTH / max(len(dives), 1)
    position = {dive: i for i, dive in enumerate(dives)}
    out = []
    for ranges, names in groups.items():
        cells = []
        for a, b in ranges:
            if a in position and b in position:
                cells.append(
                    {
                        "x": round(position[a] * width, 2),
                        "width": round(
                            max((position[b] - position[a] + 1) * width - 0.4, 0.8), 2
                        ),
                        "title": f"dives {a}–{b}" if a != b else f"dive {a}",
                    }
                )
        out.append(
            {
                "variables": sorted(names, key=str.lower),
                "count": _count_dives(ranges, all_dives),
                "text": _ranges_text([list(r) for r in ranges]),
                "cells": cells,
            }
        )
    return sorted(out, key=lambda p: (-len(p["variables"]), p["text"]))


def differing_globals(found: dict) -> tuple[list[dict], list[dict]]:
    """Return the global attributes that differ between dive files, unexpected first.

    Parameters
    ----------
    found : dict
        The conversion record's ``basestation_globals`` (name to the distinct ``values``
        and ``n_files``).

    Returns
    -------
    unexpected : list of dict
        The ones not in :data:`EXPECTED_TO_DIFFER`: ``name``, ``count`` (distinct
        values), ``values`` (up to 5, as text).
    expected : list of dict
        The ones expected to change from dive to dive, as above.

    """
    unexpected, expected = [], []
    for name, entry in sorted(found.items()):
        values = [str(v) for v in entry.get("values", [])]
        if len(values) < 2:
            continue
        row = {"name": name, "count": len(values), "values": values[:5]}
        (expected if name in EXPECTED_TO_DIFFER else unexpected).append(row)
    return unexpected, expected


def variables_by_dimension(
    input_variables: dict, presence: dict
) -> list[tuple[str, list[dict]]]:
    """Return every basestation variable over the mission, grouped by dimension.

    Parameters
    ----------
    input_variables : dict
        The conversion record's ``input_variables`` (dimensions, units, dtype, values).
    presence : dict
        The conversion record's ``presence``.

    Returns
    -------
    list of (str, list of dict)
        ``(dimension, rows)``, largest group first (``scalar`` for no dimension); each
        row has ``name``, ``units``, ``dtype``, ``values`` (summed over dives) and
        ``dives`` (the number of dives it is in).

    """
    dives = presence.get("dives") or []
    in_dives = {
        name: _count_dives(entry.get("present", []), dives)
        for name, entry in (presence.get("variables") or {}).items()
    }
    groups: dict[str, list[dict]] = defaultdict(list)
    for name, entry in input_variables.items():
        dims = entry.get("dimensions") or []
        key = "scalar" if not dims else " × ".join(dims)
        groups[key].append(
            {
                "name": name,
                "units": entry.get("units", ""),
                "dtype": entry.get("dtype", ""),
                "values": entry.get("values", 0),
                "dives": in_dives.get(name),
            }
        )
    return sorted(
        ((k, sorted(v, key=lambda r: r["name"].lower())) for k, v in groups.items()),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )


#: The salinity comparisons, by basestation name: ``(label, minuend, subtrahend, note)``.
#: A name of the form ``SP(conductivity, temperature)`` is practical salinity recomputed
#: with ``gsw.SP_from_C`` from those two and ``ctd_pressure``, for the page only.
SALINITY_COMPARISONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "salinity_raw − SP(conductivity_raw, temperature_raw)",
        "salinity_raw",
        "SP(conductivity_raw, temperature_raw)",
        "the plain conversion: about zero when gsw and the basestation agree on it",
    ),
    (
        "salinity − salinity_raw",
        "salinity",
        "salinity_raw",
        "the basestation's corrections in total",
    ),
    (
        "salinity − SP(conductivity, temperature)",
        "salinity",
        "SP(conductivity, temperature)",
        "what is left after the corrected temperature and conductivity: corrections "
        "the basestation applies to salinity itself",
    ),
)


def _by_original_name(ds: xr.Dataset) -> dict[str, str]:
    """Return the OG1 file's variables by their basestation name (``original_name``)."""
    out = {str(name): str(name) for name in ds.data_vars}
    for name, var in ds.variables.items():
        original = var.attrs.get("original_name")
        if original:
            out[str(original)] = str(name)
    return out


def _series(ds: xr.Dataset, names: dict[str, str], wanted: str) -> np.ndarray | None:
    """Return one comparison term as floats, or None when an input is missing.

    Conductivity is brought to mS cm-1 (what ``gsw.SP_from_C`` takes); a units string
    that cannot be resolved leaves the term out rather than guessing.
    """
    if not wanted.startswith("SP("):
        return (
            np.asarray(ds[names[wanted]].values, dtype=float)
            if wanted in names
            else None
        )
    conductivity, temperature = wanted[3:-1].split(", ")
    if not all(n in names for n in (conductivity, temperature, "ctd_pressure")):
        return None
    var = ds[names[conductivity]]
    factor = vocabularies.unit_factor(str(var.attrs.get("units", "")), "mS cm-1")
    if factor is None:
        return None
    with np.errstate(invalid="ignore"):
        return np.asarray(
            gsw.SP_from_C(
                np.asarray(var.values, dtype=float) * factor,
                np.asarray(ds[names[temperature]].values, dtype=float),
                np.asarray(ds[names["ctd_pressure"]].values, dtype=float),
            ),
            dtype=float,
        )


def _number(value: float) -> str:
    """Return a salinity difference for the page: small ones in exponent form."""
    if value != 0 and abs(value) < 1e-4:
        return f"{value:.1e}"
    return f"{value:+.4f}"


def salinity_checks(ds: xr.Dataset, dives: list[int]) -> dict | None:
    """Return the basestation's salinity against its conductivity, overall and by dive.

    Each comparison of :data:`SALINITY_COMPARISONS` is computed where both terms have a
    value: the median, root-mean-square and largest absolute difference, and the median
    by dive as a strip. Recomputed salinity is for the page only; nothing is written.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset holding the basestation's salinity, conductivity,
        temperature and CTD pressure (under OG1 or basestation names, matched by
        ``original_name``), with ``dive_number``.
    dives : list of int
        The mission's dives: the strips' cells.

    Returns
    -------
    dict or None
        ``rows`` (``label``, ``note``, ``n``, ``median``, ``rmsd``, ``max_abs`` as text,
        ``strip`` and ``legend``), ``raw_count`` and ``count`` (values of
        ``salinity_raw`` and ``salinity``); None when the file has no ``salinity``.

    """
    names = _by_original_name(ds)
    if "salinity" not in names:
        return None
    dive_of = (
        np.asarray(ds["dive_number"].values, dtype=float)
        if "dive_number" in ds.variables
        else None
    )
    rows = []
    for label, minuend, subtrahend, note in SALINITY_COMPARISONS:
        a, b = _series(ds, names, minuend), _series(ds, names, subtrahend)
        if a is None or b is None:
            continue
        diff = a - b
        ok = np.isfinite(diff)
        if not ok.any():
            continue
        both = diff[ok]
        strip, legend = [], ""
        if dive_of is not None:
            per_dive = []
            for dive in dives:
                mine = diff[ok & (dive_of == dive)]
                per_dive.append(float(np.median(mine)) if mine.size else None)
            strip, legend = og1.strip_cells(dives, per_dive)
        rows.append(
            {
                "label": label,
                "note": note,
                "n": int(both.size),
                "median": _number(float(np.median(both))),
                "rmsd": _number(float(np.sqrt(np.mean(both**2)))).lstrip("+"),
                "max_abs": _number(float(np.abs(both).max())).lstrip("+"),
                "strip": strip,
                "legend": legend,
            }
        )
    counts = {
        name: int(np.isfinite(_series(ds, names, name)).sum())
        for name in ("salinity_raw", "salinity")
        if name in names
    }
    return {
        "rows": rows,
        "raw_count": counts.get("salinity_raw"),
        "count": counts.get("salinity"),
    }


def render_basestation(path: str | Path, *, title: str | None = None) -> str | None:
    """Return the Basestation page for an OG1 file, or None without a conversion record.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`, with its conversion
        record beside it.
    title : str, optional
        A title to use instead of the one built from the file.

    Returns
    -------
    str or None
        The rendered page; None when the record (which holds what each dive file had) is
        missing or predates per-dive inputs.

    """
    record = _record.conversion_sidecar(path)
    if not record or not record.get("inputs") or not record.get("input_variables"):
        return None
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        durations = dive_durations(ds)
        per_dive_og1, per_dive_families = og1.per_dive_rows(ds)
        salinity = salinity_checks(
            ds, sorted(int(entry["dive"]) for entry in record["inputs"])
        )
        draft = ds.attrs.get("draft") == vocabularies.DRAFT_NOTE
        has_phase = "PHASE" in ds.variables and not draft
    presence = record.get("presence") or {}
    dives, heatmap = dimension_heatmap(record["inputs"], durations)
    patterns = presence_patterns(presence, dives)
    unexpected, expected = differing_globals(record.get("basestation_globals") or {})
    groups = variables_by_dimension(record["input_variables"], presence)
    files = [
        Path(entry["path"]).name if entry.get("path") else f"dive {entry['dive']}"
        for entry in record["inputs"]
    ]
    return get_template("basestation.html").render(
        masthead=_masthead.masthead(path, "basestation", title=title),
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        page_nav=_pages.page_nav(path, "basestation", has_phase=has_phase, draft=draft),
        width=HEATMAP_WIDTH,
        ramp=og1.STRIP_RAMP,
        fill=og1.STRIP_RUN_SHADES[1],
        dives=dives,
        n_files=len(files),
        first_file=files[0],
        last_file=files[-1],
        heatmap=heatmap,
        has_durations=bool(durations),
        patterns=patterns,
        n_variables=len(record["input_variables"]),
        n_partial=sum(len(p["variables"]) for p in patterns),
        per_dive_og1=per_dive_og1,
        per_dive_families=per_dive_families,
        max_runs=og1.MAX_RUNS,
        strip_width=og1.STRIP_WIDTH,
        salinity=salinity,
        unexpected=unexpected,
        expected=expected,
        groups=groups,
    )


def write_basestation_page(
    nc_path: str | Path, conversion_page: str | Path, *, title: str | None = None
) -> Path | None:
    """Write the Basestation page beside the conversion page; None without a record.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; this page goes in the same folder.
    title : str, optional
        A title to use instead of the one built from the file.

    Returns
    -------
    pathlib.Path or None
        The page written, or None when there is no conversion record to build it from.

    """
    html = render_basestation(nc_path, title=title)
    if html is None:
        return None
    return _pages.write_page(nc_path, conversion_page, "basestation", html)
