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


def _reconciliation_rows(ds: xr.Dataset, ledger: dict) -> list[tuple[str, str, str]]:
    """Return the Reconciliation rows (where the variables went) for ``properties_table``.

    Counts only — not an asserted closing sum. The merged/derived categories overlap (a
    GPS fix is a merged input and a derived output), so a single closing identity does not
    hold; the page states where things went rather than proving a total.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger from :func:`seagliderOG1.convert.conversion_ledger`.

    Returns
    -------
    list of (str, str, str)
        ``(label, count, "")`` rows.

    """
    renamed = passed_through = 0
    for name in ds.variables:
        original = ds[name].attrs.get("original_name")
        if original is None:
            continue
        if original == name:
            passed_through += 1
        else:
            renamed += 1
    fates = [info["fate"] for info in ledger["dimensions"].values()]
    scalar_storage = [e["storage"] for e in ledger["scalar_parameters"].values()]
    rows = [
        ("Renamed from a basestation name", renamed),
        ("Passed through unrenamed", passed_through),
        ("Derived by the converter", len(ledger["derived"])),
        ("Dropped by keep_variables", len(ledger["dropped"])),
        ("Dimensions: backbone", fates.count("backbone")),
        ("Dimensions: merged", fates.count("merged")),
        ("Dimensions: skipped", fates.count("skipped")),
        ("Constant scalars", scalar_storage.count("constant_scalar")),
        ("Per-dive JSON scalars", scalar_storage.count("per_dive_scalar")),
    ]
    return [(label, str(count), "") for label, count in rows]


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
        reconciliation = _reconciliation_rows(ds, ledger)
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
        dimensions=dimensions,
        variable_groups=groups,
        variables_source=var_source,
        scalar_rows=scalar_rows,
        scalar_source=scalar_source,
        interim=interim,
    )
