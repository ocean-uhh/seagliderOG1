"""Render the conversion ledger of one OG1 file as an HTML page.

Sections, in reading order for a new user: Before → after (what the conversion read and
wrote, from the sidecar), Reconciliation with a fate histogram and a Meaning column (where
the variables went), Presence across dives (which input dives each variable came from, from
the sidecar), Dimensions (fate from the output, with each dimension's Samples in), Derived
variables with their sources, Dropped and removed variables, Variables grouped by *original*
dimension with the Valid % column and a per-group baseline caption, Global attributes
(grouped by convention and OG1 tier, with the computed spatiotemporal-coverage columns and
the History table), and Scalar parameters last (split Renamed / Log / sg_calib_constants /
Everything else, per-dive values decoded, each group collapsible).

Everything but the presence section and the sidecar-fed columns is read from the file alone
via :func:`seagliderOG1.convert.conversion_ledger`, the vendored row builders, and the
vendored table macros; the sidecar-fed columns show "—" and the presence section says so
when the ``<id>_conversion.json`` beside the file is missing.
"""

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

if TYPE_CHECKING:
    from matplotlib.figure import Figure

from seagliderOG1 import __version__, convert, vocabularies, writers
from seagliderOG1.reports import design
from seagliderOG1.reports._env import get_template
from seagliderOG1.reports._vendored import figure_png, nc_tables
from seagliderOG1.reports._vendored.design_tokens import COLORS, W_FULL, W_THREE_FIFTHS

__all__ = ["render_conversion"]


def _variable_groups_by_original_dimension(
    ds: xr.Dataset,
) -> tuple[list[tuple[str, list]], str]:
    """Return ``variables_tables`` groups keyed by each variable's original dimension.

    The vendored ``variables_rows`` groups by the output dimension; here the flat rows are
    regrouped by each variable's ``original_dimension`` attribute, so the page reads as
    "where each variable came from" (plan D1).

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    groups : list of (str, list)
        ``(original_dimension, rows)`` in sorted order.
    source : str
        The builder's caption string.

    """
    flat, source = nc_tables.variables_rows(
        ds,
        is_qc=lambda name, _ds: design.is_qc(name),
        is_sensor=design.is_sensor,
        group_by_dims=False,
        original_name_attrs=design.ORIGINAL_NAME_ATTRS,
    )
    rows = flat[0][1] if flat else []
    no_dim_title = _NO_DIMENSION_GROUP
    by_dim: dict[str, list] = {}
    for row in rows:
        origin = ds[row["name"]].attrs.get("original_dimension")
        by_dim.setdefault(str(origin) if origin else no_dim_title, []).append(row)
    # Real basestation dimensions first (name-sorted), then the converter-built variables
    # (no original dimension) last — their full provenance is in the Derived section.
    dims = sorted(d for d in by_dim if d != no_dim_title)
    ordered = [(dim, by_dim[dim]) for dim in dims]
    if no_dim_title in by_dim:
        ordered.append((no_dim_title, by_dim[no_dim_title]))
    return ordered, source


_NO_DIMENSION_GROUP = "Derived (no basestation dimension)"


def _variable_group_caption(
    title: str,
    rows: list[dict],
    dim_samples: dict[str, int],
    axis_total: int | None,
) -> str:
    """Return the Valid % baseline caption for one Variables group.

    A dimensioned variable has values only at its own dimension's rows of the shared axis, so
    its Valid % is naturally the share of ``N_MEASUREMENTS`` that dimension supplied, not 100.
    The caption states that share so a reader can tell an expected gap from a real one: with
    the sidecar it is exact (``k`` of ``N`` samples); without it the group's highest Valid %
    stands in ("at least"). The amber still marks any Valid % below 100 (vendored, until F35).

    Parameters
    ----------
    title : str
        The group's original dimension, or the derived-no-dimension title.
    rows : list of dict
        The group's variable rows (each with a ``valid_pct``).
    dim_samples : dict of str to int
        Each dimension's samples summed over the inputs (empty without the sidecar).
    axis_total : int or None
        The length of ``N_MEASUREMENTS`` (the shared axis), or None when absent.

    Returns
    -------
    str
        The caption for this group.

    """
    amber = (
        "Amber marks any Valid % below 100 — the variable sits at its own times on the "
        "shared axis, not interpolated."
    )
    if title == _NO_DIMENSION_GROUP:
        return (
            "Converter-built variables carry values at their own times on the shared axis; "
            f"a low Valid % is expected here. {amber}"
        )
    if axis_total and title in dim_samples:
        k = dim_samples[title]
        pct = round(100 * k / axis_total, 1)
        return (
            f"{title} supplied {k:,} of {axis_total:,} samples ({pct} %); a variable with a "
            f"lower Valid % has missing values of its own. {amber}"
        )
    best = max((r["valid_pct"] for r in rows), default=0.0)
    return (
        f"{title}: at least {best} % of the shared axis; a variable with a lower Valid % "
        f"has missing values of its own. {amber}"
    )


def _reconciliation(
    ds: xr.Dataset, ledger: dict
) -> tuple[list[tuple[str, str, str]], str]:
    """Return the Reconciliation rows and caption: each basestation variable's one fate.

    Every basestation variable has exactly one fate — renamed, passed through, consumed
    (its data fed a derived variable), removed (the package drop list), dropped
    (``keep_variables``), or skipped (its dimension) — resolved by name with that priority
    so a variable on more than one dimension is not double-counted. The six counts should
    sum to the recorded basestation input count; the caption states whether they do and, if
    not, how many are unattributed (today, variables whose consumed→derived sources are not
    yet recorded).

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger from :func:`seagliderOG1.convert.conversion_ledger`.

    Returns
    -------
    rows : list of (str, str, str)
        ``(label, count, meaning)`` rows; the final row is the basestation input total with
        an empty meaning.
    caption : str
        Whether the fates sum to the input count.

    """
    renamed = {
        str(ds[n].attrs["original_name"])
        for n in ds.variables
        if ds[n].attrs.get("original_name") not in (None, n)
    }
    passed = {str(n) for n in ds.variables if ds[n].attrs.get("original_name") == n}
    consumed = {s for sources in ledger["derived"].values() for s in sources}
    removed = set(ledger["removed"])
    dropped = set(ledger["dropped"])
    skipped = {
        v
        for info in ledger["dimensions"].values()
        if info["fate"] == "skipped"
        for v in info["variables"]
    }
    # One fate per name, in priority order (an output wins over a dimension listing). The
    # third item is the Meaning text for the owned table; the fate histogram reads only the
    # label and count, so it is unaffected.
    buckets = [
        (
            "Renamed from a basestation name",
            renamed,
            "In the file under its OG1 name; original_name holds the basestation name.",
        ),
        (
            "Passed through unrenamed",
            passed,
            "In the file under its basestation name.",
        ),
        (
            "Consumed → derived",
            consumed,
            "Not in the file itself; its data went into a variable the converter built (§5).",
        ),
        (
            "Removed (package drop list)",
            removed,
            "Not in the file; was on the package drop list, now empty (§6).",
        ),
        (
            "Dropped (keep_variables)",
            dropped,
            "Not in the file; left out by your keep_variables.",
        ),
        (
            "Skipped (dimension)",
            skipped,
            "Not in the file; its dimension is not placed on N_MEASUREMENTS (§4).",
        ),
    ]
    seen: set[str] = set()
    rows = []
    total = 0
    for label, names, meaning in buckets:
        count = len(names - seen)
        seen |= names
        total += count
        rows.append((label, str(count), meaning))
    inputs = ledger["input_variable_count"]
    rows.append(("Basestation inputs", str(inputs), ""))
    unattributed = inputs - total
    if unattributed == 0:
        caption = f"The six fates sum to the {inputs} basestation input variables."
    else:
        caption = (
            f"{unattributed} of {inputs} basestation variables are not yet attributed — "
            "their data fed derived variables whose per-source lists are not yet recorded; "
            "the sum closes once they are."
        )
    return rows, caption


def draw_fate_histogram(fate_rows: list[tuple[str, str, str]]) -> "Figure | None":
    """Return a horizontal bar chart of the reconciliation fate counts, or None if empty.

    One bar per fate in the table's order (top to bottom), the count as the bar label, a
    single navy figure colour (no data palette — the bars encode one quantity). Styling comes
    from the report mplstyle applied by :func:`render_b64`.

    Parameters
    ----------
    fate_rows : list of (str, str, str)
        The reconciliation fate rows (label, count, ""), excluding the input-total row.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or ``None`` when there are no fates to plot.

    """
    import matplotlib.pyplot as plt

    if not fate_rows:
        return None
    # Full fate labels; the figure is drawn at three-fifths width so they do not crowd.
    labels = [str(row[0]) for row in fate_rows]
    counts = [int(row[1]) for row in fate_rows]
    positions = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(W_THREE_FIFTHS, 3.0))
    ax.barh(positions, counts, color=COLORS["ocean"])
    ax.set_yticks(positions)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # first fate at the top, matching the table order
    ax.set_xlabel("variables")
    for position, count in zip(positions, counts, strict=True):
        ax.text(count, position, f" {count:,}", va="center", ha="left")
    return fig


# At most this many contiguous patterns get a strip each; the rest share the sporadic row.
_MAX_STRIPS = 6


def _dive_ranges(runs: list[list[int]]) -> str:
    """Return ``"2–5"`` (or ``"2–5, 7"``) for a set of dive runs, ``"none"`` when empty.

    The count the ranges cover is carried in its own Valid % / Present % column, so the range
    cell holds only the ranges.

    Parameters
    ----------
    runs : list of [int, int]
        Dive ranges.

    Returns
    -------
    str
        The ranges, or ``"none"``.

    """
    if not runs:
        return "none"
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)


def _presence_rows(patterns: list[dict], total: int) -> list[dict[str, object]]:
    """Return one table row per presence pattern.

    Parameters
    ----------
    patterns : list of dict
        From :func:`seagliderOG1.convert.presence_patterns`.
    total : int
        Input dives in the mission.

    Returns
    -------
    list of dict
        ``label``, ``valid`` / ``present`` (dive ranges), ``valid_pct`` / ``present_pct`` (the
        share of the input dives, one decimal), ``n`` (variables), ``variables``
        (comma-joined) and ``bad`` (not valid on every dive).

    """
    rows = []
    for pattern in patterns:
        rows.append(
            {
                "label": pattern["label"],
                "valid": _dive_ranges(pattern["valid"]),
                "valid_pct": round(100 * pattern["n_valid"] / total, 1),
                "present": _dive_ranges(pattern["present"]),
                "present_pct": round(100 * pattern["n_present"] / total, 1),
                "n": len(pattern["variables"]),
                "variables": ", ".join(pattern["variables"]),
                "bad": not pattern["uniform"],
            }
        )
    return rows


def _strip_matrix(
    patterns: list[dict],
) -> tuple[np.ndarray, np.ndarray, list[str], bool]:
    """Return the present and valid patterns × dives matrices and the strip labels.

    Contiguous patterns (one run or none) get a strip each, at most ``_MAX_STRIPS``,
    largest first; every other pattern (sporadic, or past the cap) shares one density row
    whose value per dive is the fraction of those variables that cover it. Both matrices
    have the same rows, so one choice of strips serves both panels.

    Parameters
    ----------
    patterns : list of dict
        From :func:`seagliderOG1.convert.presence_patterns`, in display order (not empty).

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray, list of str, bool)
        The present and the valid matrix (1 covered, 0 not; one column per input file, in
        order), one label per row, and whether the last row is the shared density row.

    """
    strips, rest, labels = [], [], []
    for pattern in patterns:
        contiguous = len(pattern["valid"]) <= 1 and len(pattern["present"]) <= 1
        if contiguous and len(strips) < _MAX_STRIPS:
            strips.append(pattern)
            n = len(pattern["variables"])
            labels.append(f"{pattern['label']} · {n} var{'' if n == 1 else 's'}")
        else:
            rest.append(pattern)
    if rest:
        labels.append(
            f"sporadic and other · {sum(len(p['variables']) for p in rest)} vars "
            "(shade = fraction)"
        )

    def matrix(key: str) -> np.ndarray:
        rows = [np.array(p[f"{key}_mask"], dtype=float) for p in strips]
        if rest:
            weights = np.array([len(p["variables"]) for p in rest], dtype=float)
            masks = np.array([p[f"{key}_mask"] for p in rest], dtype=float)
            rows.append(weights @ masks / weights.sum())
        return np.vstack(rows)

    return matrix("present"), matrix("valid"), labels, bool(rest)


def draw_presence_strips(patterns: list[dict], dives: list[int]) -> "Figure | None":
    """Return presence and validity strips, one per pattern, x = dive; None if empty.

    Two panels of the same shape: dives each pattern is *present* in (the variable exists
    in the file) and dives it is *valid* in (it holds a value), so a sensor that is
    present but off shows as a gap in the lower panel only. Drawn with ``imshow`` on the
    patterns × dives matrix, so hundreds of dives map to the pixel width as runs, not
    bars; a dive covered by a single-dive pattern is marked above its strip so it stays
    visible at mission scale. Columns are input files in order, labelled with their dive
    numbers, so a gap in the numbering takes no width. The shared density row is drawn
    in five discrete levels with a colorbar.

    Parameters
    ----------
    patterns : list of dict
        From :func:`seagliderOG1.convert.presence_patterns`.
    dives : list of int
        The input dive numbers, in order.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or ``None`` when there are no patterns.

    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap

    if not patterns or not dives:
        return None
    present, valid, labels, has_density = _strip_matrix(patterns)
    # Five discrete levels: an on/off strip uses the two ends, the density row all five.
    levels = np.linspace(0, 1, 6)
    cmap = LinearSegmentedColormap.from_list(
        "presence", [COLORS["bg"], COLORS["ocean"]], N=len(levels) - 1
    )
    norm = BoundaryNorm(levels, cmap.N)
    n = len(dives)
    height = 1.2 + 0.32 * 2 * len(labels)
    fig, axes = plt.subplots(2, 1, figsize=(W_FULL, height), sharex=True)
    extent = (-0.5, n - 0.5, len(labels) - 0.5, -0.5)
    for ax, matrix, title in (
        (axes[0], present, "present in the file"),
        (axes[1], valid, "has values"),
    ):
        image = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap=cmap,
            norm=norm,
            extent=extent,
        )
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        ax.set_title(title, loc="left")
        if n > 50:  # keep a one-dive pattern visible at mission scale
            strip_rows = matrix[:-1] if has_density else matrix
            for row, values in enumerate(strip_rows):
                if values.sum() == 1:
                    ax.plot(np.argmax(values), row - 0.45, "v", color=COLORS["ocean"])
    if has_density:
        fig.colorbar(
            image,
            ax=axes,
            ticks=levels,
            label="fraction of the sporadic row's variables",
        )
    ticks = np.unique(np.linspace(0, n - 1, min(n, 10)).round().astype(int))
    axes[1].set_xticks(ticks)
    axes[1].set_xticklabels([str(dives[i]) for i in ticks])
    axes[1].set_xlabel("dive number (input files in order)")
    return fig


def _dimension_rows(
    ledger: dict, dim_samples: dict[str, int] | None = None
) -> list[dict[str, object]]:
    """Return one row per basestation dimension, plus a row for the dimensionless scalars.

    The dimensioned rows come from the ledger; a final ``(scalar)`` row accounts for the
    0-d basestation variables (the per-dive and constant scalar parameters), which carry no
    dimension and so appear under none of the real dimensions. With it the Variables column
    sums to the basestation input count.

    Parameters
    ----------
    ledger : dict
        The parsed ledger.
    dim_samples : dict of str to int, optional
        Samples summed over the input files for each dimension (from the conversion sidecar).
        Shown in the Samples in column; ``"—"`` for any dimension absent from it and for the
        scalar row. When omitted the column is ``"—"`` throughout.

    Returns
    -------
    list of dict
        ``{"dimension", "fate", "n", "samples_in", "ended_on", "variables"}`` rows: the
        dimensions sorted, then the scalar row.

    """
    dim_samples = dim_samples or {}

    def samples(dim: str) -> str:
        count = dim_samples.get(dim)
        return f"{count:,}" if count is not None else "—"

    rows = []
    for dim in sorted(ledger["dimensions"]):
        info = ledger["dimensions"][dim]
        ended_on = "N_MEASUREMENTS" if info["fate"] in ("backbone", "merged") else "—"
        rows.append(
            {
                "dimension": dim,
                "fate": info["fate"],
                "n": len(info["variables"]),
                "samples_in": samples(dim),
                "ended_on": ended_on,
                "variables": ", ".join(info["variables"]),
            }
        )
    scalars = ledger["scalar_parameters"]
    n_per_dive = sum(1 for e in scalars.values() if e["storage"] == "per_dive_scalar")
    n_constant = len(scalars) - n_per_dive
    rows.append(
        {
            "dimension": "(scalar)",
            "fate": "scalars",
            "n": len(scalars),
            "samples_in": "—",
            "ended_on": "—",
            "variables": (
                f"{n_constant} constant, {n_per_dive} per-dive — "
                + ", ".join(sorted(scalars))
            ),
        }
    )
    return rows


def _dimension_samples(inputs: list[dict] | None) -> dict[str, int]:
    """Return each basestation dimension's samples summed over the input files.

    Read from the conversion sidecar's per-file ``dimensions`` map; empty when the sidecar is
    absent or predates that field (a schema-1 sidecar from before this column).

    Parameters
    ----------
    inputs : list of dict or None
        The sidecar's ``inputs`` records, each with a ``dimensions`` ``{name: length}`` map.

    Returns
    -------
    dict of str to int
        ``{dimension: total samples}`` over the inputs.

    """
    totals: dict[str, int] = {}
    for record in inputs or []:
        for name, length in record.get("dimensions", {}).items():
            totals[str(name)] = totals.get(str(name), 0) + int(length)
    return totals


_COLUMNED_ATTRS = ("units", "standard_name", "long_name")


def _derived_rows(ds: xr.Dataset, ledger: dict) -> list[dict[str, object]]:
    """Return one row per derived variable with its sources and attribute disclosure.

    A derived variable carries no ``original_name``; its ``sources`` names the basestation
    variables whose data it consumed (from the ledger's derived map), or ``(computed)`` when
    it was built from other OG1 variables, vocabulary or global attributes rather than from a
    basestation input. The three-or-more consumed inputs are therefore findable in this
    column, and their union equals the reconciliation's consumed set.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger.

    Returns
    -------
    list of dict
        ``{"name", "sources", "attrs"}`` rows, one per derived variable, name-sorted.

    """
    rows = []
    for name in sorted(ledger["derived"]):
        sources = ledger["derived"][name]
        attrs = {
            str(k): str(v)
            for k, v in ds[name].attrs.items()
            if str(k) not in _COLUMNED_ATTRS
        }
        rows.append(
            {
                "name": name,
                "sources": ", ".join(sources) if sources else "(computed)",
                "attrs": attrs,
            }
        )
    return rows


def _history_rows(ledger: dict) -> list[tuple[str, str, str]]:
    """Return the history lines as ordinal-numbered rows for ``properties_table``.

    Parameters
    ----------
    ledger : dict
        The parsed ledger.

    Returns
    -------
    list of (str, str, str)
        ``(ordinal, line, "")`` rows, in file order.

    """
    lines = [line for line in str(ledger["history"]).splitlines() if line.strip()]
    return [(str(i), line, "") for i, line in enumerate(lines, start=1)]


def _format_per_dive_value(value: object) -> str:
    """Format one per-dive scalar value: ``null`` as an en-dash, floats to 4 s.f.

    Floats use the vendored :func:`~seagliderOG1.reports._vendored.nc_tables._fmt_minmax`
    so a decoded scalar reads with the same 4 significant figures as the Min / Max column;
    ``None`` (a JSON ``null``) is shown as an en-dash and strings (e.g. QC words) unchanged.

    Parameters
    ----------
    value : object
        One decoded per-dive value (``None``, a number, or a string).

    Returns
    -------
    str
        The display string for this value.

    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "—" if not math.isfinite(value) else nc_tables._fmt_minmax(value)
    return str(value)


def _apply_decoded_scalar_values(
    scalar_rows: list[dict], scalar_parameters: dict
) -> None:
    """Replace each per-dive row's ``value`` with its decoded ``dive N: v`` string, in place.

    A per-dive scalar is stored as a JSON ``{"dives": [...], "values": [...]}`` string, which
    is not readable in a table cell; show the decoded values instead (the raw serialization
    stays in the Attributes disclosure). A constant scalar's value is left as the builder set it.

    Parameters
    ----------
    scalar_rows : list of dict
        The vendored scalar rows (mutated: the per-dive rows' ``value`` is replaced).
    scalar_parameters : dict
        The ledger's ``scalar_parameters`` map.

    """
    for row in scalar_rows:
        entry = scalar_parameters.get(row["name"])
        if entry and entry["storage"] == "per_dive_scalar":
            row["value"] = ", ".join(
                f"dive {dive}: {_format_per_dive_value(value)}"
                for dive, value in zip(entry["dives"], entry["values"], strict=True)
            )


def _scalar_groups(scalar_rows: list[dict]) -> list[dict]:
    """Partition scalar rows into Renamed / Log / sg_calib_constants / Everything else.

    Each row lands in exactly one group, tested in this order: a scalar that was renamed to
    an OG1 name (its ``original_name`` is set) goes under Renamed whatever its prefix; then an
    unrenamed ``log_*`` under Log parameters; an unrenamed ``sg_calib_constants_*`` under the
    ``sg_calib_constants`` group (named for the basestation block that governed them, since not
    all of them are calibrations); the rest under Everything else. Empty groups are dropped, so
    the counts sum to the input.

    Parameters
    ----------
    scalar_rows : list of dict
        The scalar rows (each with ``name`` and ``original_name``).

    Returns
    -------
    list of dict
        ``{"title", "mono", "rows"}`` for each non-empty group, in display order; ``mono`` marks
        a title that names a basestation variable prefix (rendered monospace).

    """
    renamed, log, calib, other = [], [], [], []
    for row in scalar_rows:
        if row.get("original_name"):
            renamed.append(row)
        elif row["name"].startswith("log_"):
            log.append(row)
        elif row["name"].startswith("sg_calib_constants_") or row["name"].startswith(
            "sg_cal_"
        ):
            calib.append(row)
        else:
            other.append(row)
    groups = [
        ("Renamed", False, renamed),
        ("Log parameters", False, log),
        ("sg_calib_constants", True, calib),
        ("Everything else", False, other),
    ]
    return [
        {"title": title, "mono": mono, "rows": rows}
        for title, mono, rows in groups
        if rows
    ]


_REQUIREMENT_TIERS = (
    ("mandatory", "mandatory"),
    ("highly_desirable", "highly desirable"),
    ("suggested", "suggested"),
)


def _requirement_summary(ds: xr.Dataset) -> tuple[str, bool]:
    """Return the OG1-requirement coverage line and whether a mandatory global is missing.

    Counts, per tier of :data:`seagliderOG1.vocabularies.REQUIRED_GLOBALS`, how many required
    globals are present in the file and names the missing ones. A missing *mandatory* global
    makes the caller flag the line amber.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    text : str
        The one-line summary (e.g. ``"OG1 requirement: mandatory 9/9 present · …"``).
    mandatory_incomplete : bool
        True when at least one mandatory global is absent.

    """
    present = set(ds.attrs)
    parts = []
    mandatory_incomplete = False
    for tier_key, tier_label in _REQUIREMENT_TIERS:
        names = list(vocabularies.REQUIRED_GLOBALS.get(tier_key, ()))
        missing = [name for name in names if name not in present]
        have = len(names) - len(missing)
        if tier_key == "mandatory":
            mandatory_incomplete = bool(missing)
            part = f"mandatory {have}/{len(names)} present"
        else:
            part = f"{tier_label} {have}/{len(names)}"
        if missing:
            part += f" (missing: {', '.join(missing)})"
        parts.append(part)
    return "OG1 requirement: " + " · ".join(parts), mandatory_incomplete


def _coverage_computed(ds: xr.Dataset) -> dict[str, dict[str, object]]:
    """Return the computed-vs-stated spatiotemporal coverage for the globals table.

    For each ``geospatial_*`` / ``time_coverage_*`` global present, recompute the bound from
    the data (``LATITUDE`` / ``LONGITUDE`` / ``DEPTH`` / ``TIME``) and report the computed
    value, the absolute difference from the stated value, and whether that difference exceeds
    :data:`seagliderOG1.reports.design.COVERAGE_TOLERANCE` (the macro ambers an over-tolerance
    cell). The stated value in the table is left verbatim.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    dict
        ``{attribute: {"value", "diff", "over"}}`` for the coverage attributes present.

    """
    tol = design.COVERAGE_TOLERANCE
    out: dict[str, dict[str, object]] = {}

    def stated(attr: str) -> float | None:
        """Return a coverage global as a float, or None if absent/not a single number."""
        if attr not in ds.attrs:
            return None
        try:
            return float(np.asarray(ds.attrs[attr]).ravel()[0])
        except (TypeError, ValueError, IndexError):
            return None

    def numeric_bounds(lo_attr: str, hi_attr: str, var: str, key: str) -> None:
        if var not in ds.variables:
            return
        values = np.asarray(ds[var].values)
        values = values[np.isfinite(values)]  # flattens to the finite values
        if not values.size:
            return
        for attr, computed in (
            (lo_attr, float(values.min())),
            (hi_attr, float(values.max())),
        ):
            value = stated(attr)
            if value is None:
                continue
            diff = abs(computed - value)
            out[attr] = {
                "value": f"{computed:.4f}",
                "diff": f"{diff:.4f}",
                "over": diff > tol[key],
            }

    numeric_bounds("geospatial_lat_min", "geospatial_lat_max", "LATITUDE", "lat")
    numeric_bounds("geospatial_lon_min", "geospatial_lon_max", "LONGITUDE", "lon")
    numeric_bounds(
        "geospatial_vertical_min", "geospatial_vertical_max", "DEPTH", "vertical"
    )

    # TIME must be datetime64 before np.isnat; a non-decoded (numeric) TIME skips the
    # temporal check rather than aborting the whole render.
    if "TIME" in ds.variables and ds["TIME"].dtype.kind == "M":
        times = np.asarray(ds["TIME"].values)
        times = times[~np.isnat(times)]
        if times.size:
            for attr, computed in (
                ("time_coverage_start", times.min()),
                ("time_coverage_end", times.max()),
            ):
                if attr not in ds.attrs:
                    continue
                try:
                    reference = np.datetime64(
                        datetime.strptime(str(ds.attrs[attr]), "%Y%m%dT%H%M%S")
                    )
                except ValueError:
                    continue
                diff_s = abs(float((computed - reference) / np.timedelta64(1, "s")))
                out[attr] = {
                    "value": nc_tables.fmt_datetime(computed),
                    "diff": f"{diff_s:.1f} s",
                    "over": diff_s > tol["time"],
                }
    return out


def _time_coverage_span(start: object, end: object) -> str:
    """Return a compact ``YYYY-MM-DD HH:MM → HH:MM`` span (date stated once when same day).

    The ``time_coverage_*`` globals are compact ``YYYYmmddTHHMMSS`` strings; render them to the
    minute so one coverage pair fits one masthead line. Returns ``""`` if either is missing or
    unparseable.

    Parameters
    ----------
    start, end : object
        The ``time_coverage_start`` / ``time_coverage_end`` global values.

    Returns
    -------
    str
        The formatted span, or ``""``.

    """
    if not start or not end:
        return ""
    try:
        t0 = datetime.strptime(str(start), "%Y%m%dT%H%M%S")
        t1 = datetime.strptime(str(end), "%Y%m%dT%H%M%S")
    except ValueError:
        return ""
    left = t0.strftime("%Y-%m-%d %H:%M")
    right = (
        t1.strftime("%H:%M")
        if t0.date() == t1.date()
        else t1.strftime("%Y-%m-%d %H:%M")
    )
    return f"{left} → {right}"


def _masthead_meta(ds: xr.Dataset, ledger: dict) -> list[tuple[str, str]]:
    """Return the masthead metadata as ``(label, value)`` pairs, absent fields omitted.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger.

    Returns
    -------
    list of (str, str)
        The brief metadata shown in the masthead grid.

    """
    attrs = ds.attrs
    meta: list[tuple[str, str]] = []
    if "PLATFORM_SERIAL_NUMBER" in ds.variables:
        serial = str(ds["PLATFORM_SERIAL_NUMBER"].values)
        platform = str(attrs.get("platform", "")).strip()
        meta.append(("Platform", f"{platform} ({serial})" if platform else serial))
    dives = sorted(
        {
            dive
            for entry in ledger["scalar_parameters"].values()
            if entry["storage"] == "per_dive_scalar"
            for dive in entry.get("dives", [])
        }
    )
    if dives:
        span = f"{dives[0]}" if dives[0] == dives[-1] else f"{dives[0]}–{dives[-1]}"
        meta.append(("Dives", span))
    coverage = _time_coverage_span(
        attrs.get("time_coverage_start"), attrs.get("time_coverage_end")
    )
    if coverage:
        meta.append(("Time coverage", coverage))

    def _range(label: str, lo: str, hi: str) -> None:
        if lo not in attrs or hi not in attrs:
            return
        try:
            lo_val = float(np.asarray(attrs[lo]).ravel()[0])
            hi_val = float(np.asarray(attrs[hi]).ravel()[0])
        except (TypeError, ValueError, IndexError):
            return
        meta.append((label, f"{lo_val:.3f} → {hi_val:.3f}"))

    _range("Latitude", "geospatial_lat_min", "geospatial_lat_max")
    _range("Longitude", "geospatial_lon_min", "geospatial_lon_max")
    if "file_version" in attrs:
        meta.append(("Basestation version", str(attrs["file_version"])))
    meta.append(("seagliderOG1 version", __version__))
    # The input → output variable counts are the first row of the Before → after table (§1),
    # so the masthead no longer repeats them.
    return meta


def _page_nav(has_inventory: bool = False) -> dict:
    """Return the page-nav structure for the vendored ``page_nav`` macro.

    The conversion page is current; the inventory page is a link when it exists and a
    disabled "not yet generated" pill otherwise.

    Parameters
    ----------
    has_inventory : bool, default False
        Whether an inventory page exists to link to.

    Returns
    -------
    dict
        ``{"rows": [...]}`` for ``page_nav``.

    """
    return {
        "rows": [
            {
                "label": "",
                "pills": [
                    {
                        "role": "conversion",
                        "state": "current",
                        "label": "conversion",
                        "href": "",
                    },
                    {
                        "role": "inventory",
                        "state": "link" if has_inventory else "missing",
                        "label": "inventory",
                        "href": "inventory.html" if has_inventory else "",
                    },
                ],
            }
        ]
    }


def _format_bytes(total: int | None) -> str:
    """Return a byte count as megabytes to two decimals, or ``"—"`` when unknown.

    Parameters
    ----------
    total : int or None
        A size in bytes, or None when it was not recorded.

    Returns
    -------
    str
        ``"1.22 MB"`` or ``"—"``.

    """
    if total is None:
        return "—"
    return f"{total / 1_000_000:.2f} MB"


def _summary_rows(
    ds: xr.Dataset,
    ledger: dict,
    inputs: list[dict] | None,
    dim_samples: dict[str, int],
    path: str | Path,
    requirement_text: str,
) -> list[dict[str, object]]:
    """Return the Before → after rows: one quantity per row, basestation input and OG1 output.

    The input column is read from the conversion sidecar (``inputs``) and the output column
    from the OG1 file; a quantity the sidecar does not hold shows ``"—"`` in the input column.

    Parameters
    ----------
    ds : xarray.Dataset
        The open OG1 dataset.
    ledger : dict
        The parsed ledger.
    inputs : list of dict or None
        The sidecar's input records, or None when the sidecar is absent.
    dim_samples : dict of str to int
        Each dimension's samples summed over the inputs (empty without the sidecar).
    path : str or pathlib.Path
        The OG1 file, for its size on disk.
    requirement_text : str
        The OG1-requirement summary line (its prefix is stripped for the cell).

    Returns
    -------
    list of dict
        ``{"quantity", "input", "output", "indent"}`` rows in display order.

    """
    if inputs:
        dives = sorted(record["dive"] for record in inputs)
    else:  # no sidecar: fall back to the per-dive scalar dives, as the masthead does
        dives = sorted(
            {
                dive
                for entry in ledger["scalar_parameters"].values()
                if entry["storage"] == "per_dive_scalar"
                for dive in entry.get("dives", [])
            }
        )
    dive_span = (
        "—"
        if not dives
        else (str(dives[0]) if dives[0] == dives[-1] else f"{dives[0]}–{dives[-1]}")
    )
    input_bytes = (
        sum(record["bytes"] for record in inputs)
        if inputs and all(record.get("bytes") is not None for record in inputs)
        else None
    )
    backbone = next(
        (d for d, info in ledger["dimensions"].items() if info["fate"] == "backbone"),
        None,
    )
    axis_in = dim_samples.get(backbone) if backbone else None
    axis_out = int(ds.sizes["N_MEASUREMENTS"]) if "N_MEASUREMENTS" in ds.sizes else None
    counts = sorted({record["n_globals"] for record in inputs}) if inputs else []
    if not counts:
        globals_in = "—"
    elif len(counts) == 1:
        globals_in = str(counts[0])
    else:
        globals_in = f"{counts[0]}–{counts[-1]}"
    n_scalars = len(ledger["scalar_parameters"])
    time_span = _time_coverage_span(
        ds.attrs.get("time_coverage_start"), ds.attrs.get("time_coverage_end")
    )

    def count(value: int | None) -> str:
        return f"{value:,}" if value is not None else "—"

    return [
        {
            "quantity": "Files",
            "input": count(len(inputs)) if inputs else "—",
            "output": "1",
            "indent": False,
        },
        {"quantity": "Dives", "input": dive_span, "output": "same", "indent": False},
        {
            "quantity": "Size on disk",
            "input": _format_bytes(input_bytes),
            "output": _format_bytes(Path(path).stat().st_size),
            "indent": False,
        },
        {
            "quantity": "Samples on the axis",
            "input": count(axis_in),
            "output": count(axis_out),
            "indent": False,
        },
        {
            "quantity": "Variables",
            "input": count(ledger["input_variable_count"]),
            "output": count(len(ds.variables)),
            "indent": False,
        },
        {
            "quantity": "of which scalar parameters",
            "input": count(n_scalars),
            "output": count(n_scalars),
            "indent": True,
        },
        {
            "quantity": "Global attributes",
            "input": globals_in,
            "output": count(len(ds.attrs)),
            "indent": False,
        },
        {
            "quantity": "Time span",
            "input": "—",
            "output": time_span or "—",
            "indent": False,
        },
        {
            "quantity": "OG1 requirement",
            "input": "—",
            "output": requirement_text.removeprefix("OG1 requirement: "),
            "indent": False,
        },
    ]


def _verdict_clauses(
    reconciliation: list[tuple[str, str, str]], ledger: dict, requirement_amber: bool
) -> list[dict[str, object]]:
    """Return the Before → after verdict clauses, each amber when false.

    Parameters
    ----------
    reconciliation : list of (str, str, str)
        The reconciliation rows; the last is the basestation input total.
    ledger : dict
        The parsed ledger.
    requirement_amber : bool
        Whether a mandatory OG1 global is missing.

    Returns
    -------
    list of dict
        ``{"text", "bad"}`` clauses in display order; ``bad`` styles the clause amber.

    """
    inputs = int(reconciliation[-1][1])
    accounted = sum(int(row[1]) for row in reconciliation[:-1])
    n_dropped = len(ledger["dropped"])
    n_removed = len(ledger["removed"])
    return [
        {
            "text": f"{accounted} of {inputs} inputs accounted for",
            "bad": accounted != inputs,
        },
        {
            "text": "nothing dropped"
            if not n_dropped
            else f"{n_dropped} dropped (keep_variables)",
            "bad": bool(n_dropped),
        },
        {
            "text": "nothing removed" if not n_removed else f"{n_removed} removed",
            "bad": bool(n_removed),
        },
        {
            "text": "OG1 mandatory complete"
            if not requirement_amber
            else "OG1 mandatory incomplete",
            "bad": requirement_amber,
        },
    ]


def render_conversion(path: str | Path, *, title: str | None = None) -> str:
    """Return the conversion page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert.to_og1`.
    title : str, optional
        The page title; defaults to the file name.

    Returns
    -------
    str
        The rendered HTML page.

    Raises
    ------
    MetadataError
        If the file predates the conversion ledger (no ``conversion_dimensions``).

    """
    # Several sections read the conversion sidecar beside the file (the before → after table,
    # the Samples in column, the Valid % baseline); read it once here and say so loudly where
    # it is missing. Which dives each variable came from is known only at conversion time.
    sidecar = convert.conversion_sidecar(path)
    inputs = sidecar.get("inputs") if sidecar else None
    dim_samples = _dimension_samples(inputs)

    ds = xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False)
    try:
        ledger = convert.conversion_ledger(ds)
        groups, var_source = _variable_groups_by_original_dimension(ds)
        # Each Variables group gets its own Valid % baseline caption (the share of the shared
        # axis its dimension supplied), rendered one group at a time through the vendored macro.
        axis_total = (
            int(ds.sizes["N_MEASUREMENTS"]) if "N_MEASUREMENTS" in ds.sizes else None
        )
        variable_blocks = [
            {
                "title": title,
                "rows": rows,
                "caption": _variable_group_caption(
                    title, rows, dim_samples, axis_total
                ),
            }
            for title, rows in groups
        ]
        reconciliation, reconciliation_caption = _reconciliation(ds, ledger)
        # The fate rows excluding the input-total row (the last), for the histogram.
        fate_histogram = figure_png.render_b64(
            draw_fate_histogram,
            reconciliation[:-1],
            source="conversion.py:draw_fate_histogram",
        )
        fate_histogram_source = figure_png.source_of(fate_histogram)
        dimensions = _dimension_rows(ledger, dim_samples)
        # Scalar parameters as a vendored table, so each row's Attributes disclosure shows a
        # per-dive scalar's serialization / storage_type / original_name (how to decode it).
        all_scalars, scalar_source = nc_tables.scalars_rows(
            ds,
            exclude=design.is_sensor,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
        param_names = set(ledger["scalar_parameters"])
        scalar_rows = [r for r in all_scalars if r["name"] in param_names]
        _apply_decoded_scalar_values(scalar_rows, ledger["scalar_parameters"])
        scalar_groups = _scalar_groups(scalar_rows)
        derived_rows = _derived_rows(ds, ledger)
        dropped = sorted(ledger["dropped"])
        removed = sorted(ledger["removed"])
        # Global attributes grouped into the five vendored convention groups (the package's own
        # names placed by meaning via extras). history has its own ordinal table below;
        # conversion_attribute_sources is provenance detail shown via the attribute marks, not here.
        # requirement= adds the OG1 tier column (vendored, F29); the summary caption stays too.
        requirement_labels = {
            name: label
            for tier_key, label in _REQUIREMENT_TIERS
            for name in vocabularies.REQUIRED_GLOBALS.get(tier_key, ())
        }
        global_groups, globals_source = nc_tables.globals_rows(
            ds,
            extras=design.ATTR_GROUP_EXTRAS,
            exclude=["history", "conversion_attribute_sources"],
            requirement=requirement_labels,
        )
        coverage_computed = _coverage_computed(ds)
        requirement_text, requirement_amber = _requirement_summary(ds)
        summary_rows = _summary_rows(
            ds, ledger, inputs, dim_samples, path, requirement_text
        )
        verdict_clauses = _verdict_clauses(reconciliation, ledger, requirement_amber)
        history_rows = _history_rows(ledger)
        masthead_meta = _masthead_meta(ds, ledger)
    finally:
        ds.close()

    presence = sidecar.get("presence") if sidecar else None
    if presence:
        patterns = convert.presence_patterns(presence)
        presence_rows = _presence_rows(patterns, len(presence["dives"]))
        presence_strips = figure_png.render_b64(
            draw_presence_strips,
            patterns,
            presence["dives"],
            source="conversion.py:draw_presence_strips",
        )
        presence_summary = convert.presence_summary(presence) or (
            f"Every variable has values on every one of the {len(presence['dives'])} "
            "input dives."
        )
    else:
        presence_rows, presence_strips, presence_summary = [], None, None

    return get_template("conversion.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        masthead_meta=masthead_meta,
        page_nav=_page_nav(),
        summary_rows=summary_rows,
        verdict_clauses=verdict_clauses,
        reconciliation=reconciliation,
        reconciliation_caption=reconciliation_caption,
        sidecar_present=sidecar is not None,
        fate_histogram=fate_histogram,
        fate_histogram_source=fate_histogram_source,
        dimensions=dimensions,
        variable_blocks=variable_blocks,
        variables_source=var_source,
        scalar_groups=scalar_groups,
        scalar_source=scalar_source,
        derived_rows=derived_rows,
        dropped=dropped,
        removed=removed,
        global_groups=global_groups,
        globals_source=globals_source,
        coverage_computed=coverage_computed,
        requirement_text=requirement_text,
        requirement_amber=requirement_amber,
        history_rows=history_rows,
        presence_rows=presence_rows,
        presence_strips=presence_strips,
        presence_strips_source=figure_png.source_of(presence_strips),
        presence_summary=presence_summary,
        sidecar_name=writers.conversion_path(path, ".json").name,
    )
