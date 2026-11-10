"""The OG1 format page: an inventory of the OG1 file, with its conformance to OG1 first.

A plain description of the output file, with no conversion information (that is on the
Conversion, Variables and Processing pages):

1. **Conformance**: the OG1 requirements (globals, dimension, variables, vocabulary links,
   units) and whether the file meets each.
2. **OG1 variables**: the variables under OG1 names, grouped.
3. **Sensors**: the ``SENSOR_*`` records.
4. **Per-dive parameters**: the scalars stored as JSON text, decoded by dive.
5. **Passed-through variables**: the rest, folded by the basestation dimension they came
   from.
6. **Global attributes**: grouped, with the OG1 tier and where each value came from.
"""

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import numpy as np
import xarray as xr

from seagliderOG1 import __version__, vocabularies, writers
from seagliderOG1.reports import _pages, _record, design
from seagliderOG1.reports._env import get_template
from seagliderOG1.reports._vendored import nc_tables

__all__ = [
    "Requirement",
    "conformance_rows",
    "og1_variable_groups",
    "per_dive_rows",
    "value_runs",
    "passthrough_groups",
    "render_og1",
    "write_og1_page",
]

#: The groups of OG1-named variables on the page, in order.
OG1_GROUPS: tuple[str, ...] = (
    "Coordinates",
    "Measured and model",
    "Built by the converter",
    "QC flags",
    "Platform and deployment",
)

_COORDINATES = ("TIME", "LATITUDE", "LONGITUDE", "DEPTH")


class Requirement(TypedDict):
    """One OG1 requirement and whether the file meets it."""

    kind: str
    name: str
    tier: str
    met: bool
    value: str


def _og1_names(ds: xr.Dataset) -> list[str]:
    """Return the variables in the file under an OG1 name (a vocabulary table entry)."""
    table = vocabularies.vocab_attrs
    return sorted(str(n) for n in ds.variables if isinstance(table.get(str(n)), dict))


def _text(value: object, limit: int = 80) -> str:
    """Return a value as one line of at most ``limit`` characters."""
    out = " ".join(str(value).split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


def conformance_rows(ds: xr.Dataset) -> list[Requirement]:
    """Return the OG1 requirements and whether this file meets each.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of Requirement
        The global attributes of every tier (present and not blank or ``UNK``), the
        ``N_MEASUREMENTS`` dimension, the required variables, and two checks over every
        OG1-named variable: its ``vocabulary`` link and its ``units`` are as the package's
        OG1 table gives them.

    """
    out: list[Requirement] = []
    for tier, names in vocabularies.REQUIRED_GLOBALS.items():
        for name in names:
            value = str(ds.attrs.get(name, "")).strip()
            out.append(
                {
                    "kind": "global attribute",
                    "name": name,
                    "tier": tier.replace("_", " "),
                    "met": value not in ("", "UNK"),
                    "value": _text(value, 60),
                }
            )
    for dim in vocabularies.OG1_REQUIRED_DIMS:
        out.append(
            {
                "kind": "dimension",
                "name": dim,
                "tier": "mandatory",
                "met": dim in ds.sizes,
                "value": f"{ds.sizes[dim]:,}" if dim in ds.sizes else "",
            }
        )
    for name in vocabularies.OG1_REQUIRED_VARS:
        present = name in ds.variables
        value = ""
        if present and ds[name].ndim:
            value = f"{int(ds[name].notnull().sum()):,} values"
        elif present:
            value = _text(ds[name].values.item(), 40)
        out.append(
            {
                "kind": "variable",
                "name": name,
                "tier": "mandatory",
                "met": present,
                "value": value,
            }
        )
    named = _og1_names(ds)
    table = vocabularies.vocab_attrs
    wrong_vocab = [
        n
        for n in named
        if table[n].get("vocabulary")
        and ds[n].attrs.get("vocabulary") != table[n]["vocabulary"]
    ]
    wrong_units = [
        n
        for n in named
        if table[n].get("units")
        and ds[n].attrs.get("units", ds[n].encoding.get("units")) != table[n]["units"]
    ]
    for label, wrong in (
        ("vocabulary link as the OG1 table", wrong_vocab),
        ("units as the OG1 table", wrong_units),
    ):
        out.append(
            {
                "kind": "every OG1 variable",
                "name": label,
                "tier": "mandatory",
                "met": not wrong,
                "value": f"{len(named) - len(wrong)} of {len(named)}"
                + (f"; not: {', '.join(wrong)}" if wrong else ""),
            }
        )
    return out


def _minmax(var: xr.DataArray) -> str:
    """Return ``min / max`` of a numeric or time variable, or ``—``."""
    values = np.asarray(var.values)
    if values.dtype.kind in "mM":
        finite = values[~np.isnat(values)]
        if not finite.size:
            return "—"
        return f"{nc_tables.fmt_datetime(finite.min())} / {nc_tables.fmt_datetime(finite.max())}"
    if values.dtype.kind not in "fiu":
        return "—"
    finite = values[np.isfinite(values)] if values.dtype.kind == "f" else values
    if not finite.size:
        return "—"
    return f"{finite.min():.6g} / {finite.max():.6g}"


def _row(ds: xr.Dataset, name: str) -> dict:
    """Return one table row describing an output variable."""
    var = ds[name]
    if var.ndim:
        value, count = _minmax(var), int(var.notnull().sum())
    else:
        value, count = _text(var.values.item(), 50), 1
    dtype = var.encoding.get("dtype", var.dtype)
    return {
        "name": name,
        "long_name": str(var.attrs.get("long_name", "")),
        "standard_name": str(var.attrs.get("standard_name", "")),
        "units": str(var.attrs.get("units", var.encoding.get("units", ""))),
        "dtype": "text" if np.dtype(dtype).kind in "OSU" else str(np.dtype(dtype)),
        "value": value,
        "count": count,
        "vocabulary": str(var.attrs.get("vocabulary", "")),
        "attrs": {k: str(v) for k, v in var.attrs.items()},
    }


def _group_of(ds: xr.Dataset, name: str) -> str:
    """Return the page group of an OG1-named variable."""
    var = ds[name]
    if name in _COORDINATES:
        return "Coordinates"
    if name.endswith("_QC"):
        return "QC flags"
    if not var.ndim:
        return "Platform and deployment"
    if "original_name" not in var.attrs:
        return "Built by the converter"
    return "Measured and model"


def og1_variable_groups(ds: xr.Dataset) -> list[tuple[str, list[dict]]]:
    """Return the OG1-named variables in their page groups (per-dive scalars excluded).

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of (str, list of dict)
        ``(group, rows)`` in :data:`OG1_GROUPS` order, empty groups left out.

    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for name in _og1_names(ds):
        if ds[name].attrs.get("storage_type") == "per_dive_scalar":
            continue
        groups[_group_of(ds, name)].append(_row(ds, name))
    return [(g, groups[g]) for g in OG1_GROUPS if groups.get(g)]


#: A per-dive parameter with at most this many runs of equal values is shown as its runs
#: ("dives 1-45: 0.0036; 46-600: 0.0041"); one that changes more often as a range.
MAX_RUNS = 6


def _fmt(value: object) -> str:
    """Return a per-dive value for the page: numbers to 6 significant figures."""
    if isinstance(value, float):
        return f"{value:.6g}"
    return _text(value, 40)


def value_runs(dives: list[int], values: list[object]) -> list[tuple[int, int, object]]:
    """Return the runs of equal values over consecutive entries, as ``(first, last, value)``.

    Parameters
    ----------
    dives : list of int
        The dive numbers, in order.
    values : list
        One value per dive (None where the dive has none).

    Returns
    -------
    list of (int, int, object)
        The first and last dive of each run and its value.

    """
    runs: list[tuple[int, int, object]] = []
    for dive, value in zip(dives, values, strict=True):
        if runs and runs[-1][2] == value:
            runs[-1] = (runs[-1][0], dive, value)
        else:
            runs.append((dive, dive, value))
    return runs


def _summary(dives: list[int], values: list[object]) -> tuple[str, list[str]]:
    """Return a per-dive parameter as one line and, when it has few runs, the runs."""
    runs = value_runs(dives, values)
    if len(runs) <= MAX_RUNS:
        lines = [
            (f"dive {a}" if a == b else f"dives {a}–{b}") + f": {_fmt(v)}"
            if v is not None
            else (f"dive {a}" if a == b else f"dives {a}–{b}") + ": no value"
            for a, b, v in runs
        ]
        return (
            f"{len(runs)} value{'s' if len(runs) > 1 else ''} over the mission",
            lines,
        )
    numbers = [
        v for v in values if isinstance(v, int | float) and not isinstance(v, bool)
    ]
    if numbers:
        return (
            f"changes {len(runs) - 1} times; min {_fmt(float(min(numbers)))}, "
            f"median {_fmt(float(np.median(numbers)))}, max {_fmt(float(max(numbers)))}",
            [],
        )
    return f"changes {len(runs) - 1} times", []


def per_dive_rows(ds: xr.Dataset) -> tuple[list[dict], list[tuple[str, list[dict]]]]:
    """Return the per-dive parameters decoded and summarised, OG1-named first.

    A parameter with at most :data:`MAX_RUNS` runs of equal values lists them (a
    calibration constant or pilot setting changed a few times); one that changes more often
    is summarised by its range, so the table does not grow with the number of dives.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    og1 : list of dict
        The OG1-named parameters: ``name``, ``units``, ``dives`` (with a value),
        ``summary`` (one line) and ``runs`` (lines, empty when summarised by range).
    families : list of (str, list of dict)
        The other parameters, grouped as ``log_*``, ``sg_cal_*`` and ``other``.

    """
    og1: list[dict] = []
    family: dict[str, list[dict]] = defaultdict(list)
    for name in sorted(str(n) for n in ds.variables):
        var = ds[name]
        if var.attrs.get("storage_type") != "per_dive_scalar":
            continue
        try:
            payload = json.loads(str(np.asarray(var.values).item()))
            dives, values = list(payload["dives"]), list(payload["values"])
        except (ValueError, TypeError, KeyError):
            # Not the JSON form this package writes; shown as unreadable, not guessed.
            dives, values = [], []
        summary, runs = (
            _summary(dives, values) if dives else ("not readable as per-dive JSON", [])
        )
        row = {
            "name": name,
            "units": str(var.attrs.get("units", "")),
            "dives": sum(v is not None for v in values),
            "summary": summary,
            "runs": runs,
        }
        if isinstance(vocabularies.vocab_attrs.get(name), dict):
            og1.append(row)
            continue
        key = next(
            (p + "*" for p in ("log_", "sg_cal_") if name.startswith(p)), "other"
        )
        family[key].append(row)
    return og1, sorted(family.items())


def passthrough_groups(ds: xr.Dataset) -> list[tuple[str, list[dict]]]:
    """Return the variables kept under their basestation names, by original dimension.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of (str, list of dict)
        ``(dimension, rows)``, largest group first. A variable with no
        ``original_dimension`` is under ``scalar`` when it has no dimension, else under
        "no original_dimension recorded".

    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for name in sorted((str(n) for n in ds.variables), key=str.lower):
        var = ds[name]
        if (
            var.attrs.get("original_name") != name
            or var.attrs.get("storage_type") == "per_dive_scalar"
            or isinstance(vocabularies.vocab_attrs.get(name), dict)
        ):
            continue
        dim = var.attrs.get("original_dimension") or (
            "scalar" if not var.ndim else "no original_dimension recorded"
        )
        groups[str(dim)].append(_row(ds, name))
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def render_og1(path: str | Path, *, title: str | None = None) -> str:
    """Return the OG1 format page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`.
    title : str, optional
        The page title; defaults to the file name.

    Returns
    -------
    str
        The rendered HTML page.

    """
    # Lazy: the conversion module imports this one's siblings at load time.
    from seagliderOG1.reports import conversion as conv

    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        ledger = _record.conversion_ledger(ds)
        requirements = conformance_rows(ds)
        groups = og1_variable_groups(ds)
        sensors, sensor_source = nc_tables.sensor_rows(ds)
        per_dive_og1, per_dive_families = per_dive_rows(ds)
        passthrough = passthrough_groups(ds)
        requirement_labels = {
            name: label
            for tier_key, label in conv._REQUIREMENT_TIERS
            for name in vocabularies.REQUIRED_GLOBALS.get(tier_key, ())
        }
        global_groups, globals_source = nc_tables.globals_rows(
            ds,
            extras=design.ATTR_GROUP_EXTRAS,
            exclude=["history"]
            + [k for k in ds.attrs if str(k).startswith("conversion_")],
            requirement=requirement_labels,
        )
        records = sorted(str(k) for k in ds.attrs if str(k).startswith("conversion_"))
        record_sizes = [(k, len(str(ds.attrs[k]))) for k in records]
        coverage_computed = conv._coverage_computed(ds)
        requirement_text, requirement_amber = conv._requirement_summary(ds)
        conventions = conv._conventions_check(ds)
        history_rows = conv._history_rows(ledger)
        masthead_meta = conv._masthead_meta(ds, ledger)
        n_points = int(ds.sizes.get("N_MEASUREMENTS", 0))
        n_vars = len(ds.variables)
        has_phase = "PHASE" in ds.variables
    tiers = defaultdict(lambda: [0, 0])
    for r in requirements:
        tiers[r["tier"]][0] += r["met"]
        tiers[r["tier"]][1] += 1
    return get_template("og1.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        masthead_meta=masthead_meta,
        page_nav=_pages.page_nav(path, "og1", has_phase=has_phase),
        requirements=requirements,
        tier_counts=[(t, met, total) for t, (met, total) in tiers.items()],
        groups=groups,
        n_og1=sum(len(rows) for _g, rows in groups) + len(per_dive_og1),
        sensors=sensors,
        sensor_source=sensor_source,
        max_runs=MAX_RUNS,
        per_dive_og1=per_dive_og1,
        per_dive_families=per_dive_families,
        n_per_dive=len(per_dive_og1) + sum(len(r) for _f, r in per_dive_families),
        passthrough=passthrough,
        n_passthrough=sum(len(rows) for _d, rows in passthrough),
        global_groups=global_groups,
        globals_source=globals_source,
        coverage_computed=coverage_computed,
        requirement_text=requirement_text,
        requirement_amber=requirement_amber,
        conventions=conventions,
        history_rows=history_rows,
        record_sizes=record_sizes,
        n_points=n_points,
        n_vars=n_vars,
        conversion_href=writers.conversion_path(path, ".html").name,
    )


def write_og1_page(
    nc_path: str | Path, conversion_page: str | Path, *, title: str | None = None
) -> Path:
    """Write the OG1 format page beside the conversion page and return it.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; this page goes in the same folder.
    title : str, optional
        Page title; the file name by default.

    Returns
    -------
    pathlib.Path
        The page written.

    """
    target = Path(conversion_page).with_name(writers.page_path(nc_path, "og1").name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_og1(nc_path, title=title), encoding="utf-8")
    return target
