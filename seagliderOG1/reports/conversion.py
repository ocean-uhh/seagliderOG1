"""Render the conversion ledger of one OG1 file as an HTML page.

First cut of plan step 3: a Reconciliation summary (where the variables went), Dimensions
(fate per basestation dimension), and Variables grouped by *original* dimension with the
``original -> OG1`` arrow and the Valid % column (the macro ambers Valid % < 100). The
remaining sections (scalars, derived, dropped, global sources, history) are an interim text
block. Everything is read from the file alone via
:func:`seagliderOG1.convert.conversion_ledger` and the vendored row builders.
"""

from datetime import UTC, datetime
from pathlib import Path

import xarray as xr

from seagliderOG1 import __version__, convert
from seagliderOG1.reports import design
from seagliderOG1.reports._env import get_template
from seagliderOG1.reports._vendored import nc_tables

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
    by_dim: dict[str, list] = {}
    for row in rows:
        origin = str(
            ds[row["name"]].attrs.get("original_dimension") or "(no original dimension)"
        )
        by_dim.setdefault(origin, []).append(row)
    return [(dim, by_dim[dim]) for dim in sorted(by_dim)], source


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
        ``(label, count, "")`` rows for ``properties_table``.
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
    # One fate per name, in priority order (an output wins over a dimension listing).
    buckets = [
        ("Renamed from a basestation name", renamed),
        ("Passed through unrenamed", passed),
        ("Consumed → derived", consumed),
        ("Removed (package drop list)", removed),
        ("Dropped (keep_variables)", dropped),
        ("Skipped (dimension)", skipped),
    ]
    seen: set[str] = set()
    rows = []
    total = 0
    for label, names in buckets:
        count = len(names - seen)
        seen |= names
        total += count
        rows.append((label, str(count), ""))
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


def _dimension_rows(ledger: dict) -> list[dict[str, object]]:
    """Return one row per basestation dimension for the Dimensions table.

    Parameters
    ----------
    ledger : dict
        The parsed ledger.

    Returns
    -------
    list of dict
        ``{"dimension", "fate", "n", "ended_on", "variables"}`` rows, dimensions sorted.

    """
    rows = []
    for dim in sorted(ledger["dimensions"]):
        info = ledger["dimensions"][dim]
        ended_on = "N_MEASUREMENTS" if info["fate"] in ("backbone", "merged") else "—"
        rows.append(
            {
                "dimension": dim,
                "fate": info["fate"],
                "n": len(info["variables"]),
                "ended_on": ended_on,
                "variables": ", ".join(info["variables"]),
            }
        )
    return rows


def _interim_sections(ledger: dict) -> str:
    """Return the not-yet-tabled sections (derived, dropped, globals, history) as text.

    Parameters
    ----------
    ledger : dict
        The parsed ledger.

    Returns
    -------
    str
        A plain-text rendering of the interim sections.

    """
    lines = ["Derived variables: " + (", ".join(ledger["derived"]) or "(none)")]
    lines += ["Dropped variables: " + (", ".join(ledger["dropped"]) or "(none)")]
    lines += ["", "Global attributes by source"]
    for category in sorted(ledger["attribute_sources"]):
        lines.append(
            f"  {category}: {', '.join(ledger['attribute_sources'][category])}"
        )
    lines += ["", "History", f"  {ledger['history']}"]
    return "\n".join(lines)


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
    ds = xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False)
    try:
        ledger = convert.conversion_ledger(ds)
        groups, var_source = _variable_groups_by_original_dimension(ds)
        reconciliation, reconciliation_caption = _reconciliation(ds, ledger)
        dimensions = _dimension_rows(ledger)
        # Scalar parameters as a vendored table, so each row's Attributes disclosure shows a
        # per-dive scalar's serialization / storage_type / original_name (how to decode it).
        all_scalars, scalar_source = nc_tables.scalars_rows(
            ds,
            exclude=design.is_sensor,
            original_name_attrs=design.ORIGINAL_NAME_ATTRS,
        )
        param_names = set(ledger["scalar_parameters"])
        scalar_rows = [r for r in all_scalars if r["name"] in param_names]
        interim = _interim_sections(ledger)
    finally:
        ds.close()

    return get_template("conversion.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        reconciliation=reconciliation,
        reconciliation_caption=reconciliation_caption,
        dimensions=dimensions,
        variable_groups=groups,
        variables_source=var_source,
        scalar_rows=scalar_rows,
        scalar_source=scalar_source,
        interim=interim,
    )
