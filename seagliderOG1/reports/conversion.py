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
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr
import yaml

if TYPE_CHECKING:
    from matplotlib.figure import Figure

from seagliderOG1 import __version__, contributors, convert, vocabularies, writers
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
    # Real basestation dimensions first (name-sorted), then the variables with no
    # original dimension (built by the converter) last — their full provenance is in
    # the Derived section.
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


def _origin(ds: xr.Dataset, name: str, derived: set[str]) -> tuple[str, str]:
    """Return ``(original variable, original dimension)`` for an OG1 variable.

    The original variable is the basestation name it came from, or how the converter built it
    (``"(derived)"`` / ``"(built)"``); a variable kept under its own name shows that name. The
    original dimension is the basestation dimension it sat on, or ``"—"`` when none is recorded
    (a derived or built variable).

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    name : str
        The OG1 variable name.
    derived : set of str
        Names the ledger records as derived (built by the converter).

    Returns
    -------
    tuple of (str, str)
        ``(original_variable, original_dimension)``.

    """
    attrs = ds[name].attrs
    origin = attrs.get("original_name")
    dim = str(attrs.get("original_dimension") or "—")
    if origin and origin != name:
        return str(origin), dim
    if name in derived:
        # A derived variable may still name its source dimension (the GPS variables).
        return "(derived)", dim
    if origin == name:
        return name, dim
    return "(built)", "—"


def _og1_required_rows(
    ds: xr.Dataset, ledger: dict, valid_by_name: dict[str, float]
) -> tuple[list[dict[str, object]], str, bool]:
    """Return the OG1-required tier: one row per required variable, then the required dimension.

    The required names come from :data:`seagliderOG1.vocabularies.OG1_REQUIRED_VARS` (the
    upstream checker list). A variable present in the file gets its came-from, dims, units and
    Valid %; an absent one is flagged (the caller ambers it). The caption counts how many of
    the required names are present and names any that are missing.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger (for the derived set).
    valid_by_name : dict of str to float
        Valid % per dimensioned variable/coordinate (from the vendored row builders); a
        required scalar is not in it and shows ``"—"``.

    Returns
    -------
    rows : list of dict
        ``{"name", "present", "orig_var", "orig_dim", "dims", "units", "valid"}`` rows.
    caption : str
        The OG1-required count line, naming any missing variables.
    incomplete : bool
        True when a required variable or dimension is missing (the caller ambers the caption).

    """
    derived = set(ledger["derived"])
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for name in vocabularies.OG1_REQUIRED_VARS:
        present = name in ds.variables
        if present:
            v = ds[name]
            valid = valid_by_name.get(name)
            orig_var, orig_dim = _origin(ds, name, derived)
            rows.append(
                {
                    "name": name,
                    "present": True,
                    "orig_var": orig_var,
                    "orig_dim": orig_dim,
                    "dims": " × ".join(str(d) for d in v.dims) or "(scalar)",
                    "units": str(v.attrs.get("units", "")),
                    "valid": f"{valid}" if valid is not None else "—",
                }
            )
        else:
            missing.append(name)
            rows.append(
                {
                    "name": name,
                    "present": False,
                    "orig_var": "—",
                    "orig_dim": "—",
                    "dims": "—",
                    "units": "—",
                    "valid": "—",
                }
            )
    for dim in vocabularies.OG1_REQUIRED_DIMS:
        present = dim in ds.dims
        if not present:
            missing.append(dim)
        rows.append(
            {
                "name": f"{dim} (dimension)",
                "present": present,
                "orig_var": "—",
                "orig_dim": "—",
                "dims": f"{ds.sizes[dim]:,}" if present else "—",
                "units": "—",
                "valid": "—",
            }
        )
    n_vars = len(vocabularies.OG1_REQUIRED_VARS)
    have = n_vars - len([m for m in missing if m in vocabularies.OG1_REQUIRED_VARS])
    caption = f"OG1 required: {have} of {n_vars} variables present"
    if missing:
        caption += f" — missing: {', '.join(missing)}"
    return rows, caption, bool(missing)


# Basestation families summarised in the carried-through tier, longest prefix first; the
# display label and a one-line note on what they are (so the 300-odd leftovers read as a few
# rows, not a wall of names).
_CARRIED_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("sg_calib_constants_", "sg_cal_*", "glider calibration constants"),
    ("sg_cal_", "sg_cal_*", "glider calibration constants"),
    ("log_", "log_*", "basestation dive-log parameters, kept for provenance"),
    ("gc_", "gc_*", "guidance-and-control event records"),
    ("eng_", "eng_*", "engineering channels"),
)


def _carried_family(name: str) -> tuple[str, str]:
    """Return the ``(label, description)`` of the carried-through family a name belongs to."""
    for prefix, label, what in _CARRIED_FAMILIES:
        if name.startswith(prefix):
            return label, what
    if name.endswith("_gsm"):
        return "*_gsm", "glider flight-model estimates"
    if name.endswith("_RAW"):
        return "*_RAW", "raw instrument channels before calibration"
    if name.lower().endswith("_qc"):
        return "*_qc", "basestation per-variable QC strings"
    return "other", "other carried-through variables"


def _og1_tiers(
    ds: xr.Dataset, ledger: dict, valid_by_name: dict[str, float]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the "named by OG1" rows and the "carried through" family summary.

    A variable not in :data:`seagliderOG1.vocabularies.OG1_REQUIRED_VARS` is "named by OG1"
    when it has an OG1 attribute vocabulary or is an OG1 ``*_QC`` flag (``SENSOR_*`` variables
    have their own table, :func:`_og1_sensor_rows`); everything else is carried through and summarised by basestation family so the ~300
    engineering/log leftovers read as a handful of rows.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger (for the derived set).
    valid_by_name : dict of str to float
        Valid % per dimensioned variable/coordinate (a scalar is absent and shows ``"—"``).

    Returns
    -------
    named : list of dict
        ``{"name", "orig_var", "orig_dim", "dims", "units", "valid"}`` rows, name-sorted.
    carried : list of dict
        ``{"family", "what", "count", "names"}`` family rows, largest first.

    """
    derived = set(ledger["derived"])
    required = set(vocabularies.OG1_REQUIRED_VARS)
    candidates = set(vocabularies.OG1_CANDIDATE_VARS)
    og1_named = set(vocabularies.vocab_attrs)
    named: list[dict[str, object]] = []
    carried: dict[str, dict[str, object]] = {}
    for name in sorted(map(str, ds.variables)):
        if (
            name in required or name in candidates
        ):  # candidates are their own group (2.5)
            continue
        if design.is_sensor(name):  # their own table (_og1_sensor_rows)
            continue
        if name in og1_named or name.endswith("_QC"):
            v = ds[name]
            valid = valid_by_name.get(name)
            orig_var, orig_dim = _origin(ds, name, derived)
            named.append(
                {
                    "name": name,
                    "orig_var": orig_var,
                    "orig_dim": orig_dim,
                    "dims": " × ".join(str(d) for d in v.dims) or "(scalar)",
                    "units": str(v.attrs.get("units", "")),
                    "valid": f"{valid}" if valid is not None else "—",
                }
            )
        else:
            label, what = _carried_family(name)
            entry = carried.setdefault(
                label, {"family": label, "what": what, "names": []}
            )
            entry["names"].append(name)  # type: ignore[attr-defined]
    rows = sorted(carried.values(), key=lambda f: -len(f["names"]))
    for entry in rows:
        names = entry["names"]
        entry["count"] = len(names)  # type: ignore[arg-type]
        entry["names"] = ", ".join(names)  # type: ignore[arg-type]
    return named, rows


def _is_placeholder(value: str) -> bool:
    """Return True for an empty value or one whose digits are all zero (``0000``, ``00-00-0000``)."""
    digits = [c for c in value if c.isdigit()]
    return not value.strip() or (bool(digits) and set(digits) == {"0"})


def _og1_sensor_rows(ds: xr.Dataset) -> list[dict[str, object]]:
    """Return one row per ``SENSOR_*`` variable: what the sensor is and which variables use it.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of dict
        ``{"name", "type", "maker", "model", "serial", "calibration", "used_by", "n_used",
        "shared", "bad"}`` rows, name-sorted; ``used_by`` names the variables whose
        ``sensor`` attribute is this sensor; ``shared`` when another sensor has the same
        serial number (a basestation calibration comment copied between instruments);
        ``bad`` when the serial or calibration date is a placeholder (empty, or every digit
        zero) or the serial is shared.

    """
    users: dict[str, list[str]] = {}
    for name, var in ds.variables.items():
        sensor = var.attrs.get("sensor")
        if sensor:
            users.setdefault(str(sensor), []).append(str(name))
    names = sorted(str(n) for n in ds.variables if design.is_sensor(str(n)))
    serials: dict[str, int] = {}
    for name in names:
        serial = str(ds[name].attrs.get("sensor_serial_number", ""))
        serials[serial] = serials.get(serial, 0) + 1
    rows = []
    for name in names:
        attrs = ds[name].attrs
        serial = str(attrs.get("sensor_serial_number", ""))
        calibration = str(attrs.get("sensor_calibration_date", ""))
        used = sorted(users.get(name, []))
        rows.append(
            {
                "name": name,
                "type": str(attrs.get("sensor_type", "")),
                "maker": str(attrs.get("sensor_maker", "")),
                "model": str(attrs.get("sensor_model", "")),
                "serial": serial,
                "calibration": calibration,
                "used_by": ", ".join(used),
                "n_used": len(used),
                "shared": serials[serial] > 1 and not _is_placeholder(serial),
                "bad": _is_placeholder(serial)
                or _is_placeholder(calibration)
                or serials[serial] > 1,
            }
        )
    return rows


def _og1_candidate_groups(
    ds: xr.Dataset, ledger: dict, valid_by_name: dict[str, float]
) -> list[dict[str, object]]:
    """Return the candidate (uplift) groups: variables the project proposes to canonise.

    Each group named in :data:`seagliderOG1.vocabularies.OG1_CANDIDATE_VARS` is listed
    present/absent (from the curated list, so a variable the file lacks still shows), recording
    what the project wants to require — e.g. for a flight model — independent of the upstream
    OG1 vocabulary. Absence is informational, not an error: the file may predate the candidate.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : dict
        The parsed ledger (for the derived set).
    valid_by_name : dict of str to float
        Valid % per dimensioned variable/coordinate (a scalar is absent and shows ``"—"``).

    Returns
    -------
    list of dict
        ``{"label", "rows", "n_present", "n_total"}`` per group, label-sorted; each row is
        ``{"name", "present", "orig_var", "orig_dim", "dims", "units", "valid"}``.

    """
    derived = set(ledger["derived"])
    groups: dict[str, list[dict[str, object]]] = {}
    for name, label in vocabularies.OG1_CANDIDATE_VARS.items():
        if name in ds.variables:
            v = ds[name]
            valid = valid_by_name.get(name)
            orig_var, orig_dim = _origin(ds, name, derived)
            row = {
                "name": name,
                "present": True,
                "orig_var": orig_var,
                "orig_dim": orig_dim,
                "dims": " × ".join(str(d) for d in v.dims) or "(scalar)",
                "units": str(v.attrs.get("units", "")),
                "valid": f"{valid}" if valid is not None else "—",
            }
        else:
            row = {
                "name": name,
                "present": False,
                "orig_var": "—",
                "orig_dim": "—",
                "dims": "—",
                "units": "—",
                "valid": "—",
            }
        groups.setdefault(label, []).append(row)
    out = []
    for label in sorted(groups):
        group_rows = groups[label]
        out.append(
            {
                "label": label,
                "rows": group_rows,
                "n_present": sum(1 for r in group_rows if r["present"]),
                "n_total": len(group_rows),
            }
        )
    return out


_UNIT_SPELLING = {"meters": "m", "metre": "m", "metres": "m", "meter": "m"}


def _norm_unit(unit: str) -> str:
    """Return a unit string normalised for spelling (``meters`` → ``m``), lowercased."""
    text = unit.strip().lower()
    return _UNIT_SPELLING.get(text, text)


def _unit_factor(u_from: str, u_to: str) -> float | None:
    """Return the multiplier converting ``u_from`` into ``u_to``, or None when unrelated.

    Same unit (after spelling normalisation) is ``1.0``; otherwise the family alias table
    (:data:`seagliderOG1.vocabularies.unit1_to_unit2`) is consulted. No conversion is invented:
    units the table does not relate return None and the comparison is marked not comparable.
    """
    if _norm_unit(u_from) == _norm_unit(u_to):
        return 1.0
    # The table keys a direct conversion by exact spelling; fall back to the normalised
    # spellings so a "meters"/"m" variant still finds an "m_to_cm"-style entry.
    entry = vocabularies.unit1_to_unit2.get(
        f"{u_from}_to_{u_to}"
    ) or vocabularies.unit1_to_unit2.get(f"{_norm_unit(u_from)}_to_{_norm_unit(u_to)}")
    return float(entry["factor"]) if entry else None


def _duplicate_groups(ds: xr.Dataset) -> list[dict[str, object]]:
    """Return groups of output variables that encode the same quantity, compared to a reference.

    Variables sharing a ``standard_name`` (grouping by meaning, never by name prefix) are one
    group when the group has a reference member — one that is OG1-required or OG1-named,
    preferring required then the shortest name. The reference is listed first; each other member
    is compared to it (member minus reference) over the samples both carry, in the reference's
    units. A member whose units the alias table cannot relate is "not comparable" rather than
    converted by guess. ``status_flag`` (the QC flags) and groups without a reference are
    excluded.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of dict
        ``{"standard_name", "reference", "reference_units", "rows"}`` per group; each row is
        ``{"name", "units", "reference", "n_overlap", "offset", "rmsd", "max_abs", "note"}``,
        the reference row first.

    """
    required = set(vocabularies.OG1_REQUIRED_VARS)
    og1_named = set(vocabularies.vocab_attrs)
    by_sn: dict[str, list[str]] = {}
    for name in map(str, ds.variables):
        v = ds[name]
        if v.ndim >= 1 and v.dtype.kind in "fiu":
            sn = str(v.attrs.get("standard_name", "")).strip()
            if sn and sn != "status_flag":
                by_sn.setdefault(sn, []).append(name)
    groups: list[dict[str, object]] = []
    for sn, members in sorted(by_sn.items()):
        if len(members) < 2:
            continue
        canon = [m for m in members if m in required] or [
            m for m in members if m in og1_named
        ]
        if not canon:
            continue  # no OG1 canonical: not a converter-made OG1 duplicate
        reference = min(canon, key=lambda m: (m not in required, len(m), m))
        ref_vals = np.asarray(ds[reference].values, dtype=float)
        ref_units = str(ds[reference].attrs.get("units", ""))
        # Reference row first, then each other member's difference from it.
        rows: list[dict[str, object]] = [
            _duplicate_row(reference, ref_units, reference=True)
        ]
        for member in members:
            if member == reference:
                continue
            units = str(ds[member].attrs.get("units", ""))
            factor = _unit_factor(units, ref_units)
            if factor is None:
                rows.append(
                    _duplicate_row(
                        member, units, note=f"not comparable ({units} vs {ref_units})"
                    )
                )
                continue
            vals = np.asarray(ds[member].values, dtype=float) * factor
            mask = np.isfinite(vals) & np.isfinite(ref_vals)
            n = int(mask.sum())
            if not n:
                rows.append(
                    _duplicate_row(member, units, n_overlap="0", note="no overlap")
                )
                continue
            diff = vals[mask] - ref_vals[mask]  # member minus reference
            rows.append(
                _duplicate_row(
                    member,
                    units,
                    n_overlap=f"{n:,}",
                    offset=nc_tables._fmt_minmax(float(diff.mean())),
                    rmsd=nc_tables._fmt_minmax(float(np.sqrt((diff**2).mean()))),
                    max_abs=nc_tables._fmt_minmax(float(np.abs(diff).max())),
                )
            )
        groups.append(
            {
                "standard_name": sn,
                "reference": reference,
                "reference_units": ref_units,
                "rows": rows,
            }
        )
    return groups


def _duplicate_row(
    name: str,
    units: str,
    *,
    reference: bool = False,
    n_overlap: str = "—",
    offset: str = "—",
    rmsd: str = "—",
    max_abs: str = "—",
    note: str = "",
) -> dict[str, object]:
    """Return one duplicate-comparison row with its defaults (an en-dash where not computed)."""
    return {
        "name": name,
        "units": units,
        "reference": reference,
        "n_overlap": n_overlap,
        "offset": offset,
        "rmsd": rmsd,
        "max_abs": max_abs,
        "note": "reference" if reference else note,
    }


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
            "Not in the file itself; its data went into a variable the converter built (see Derived variables).",
        ),
        (
            "Removed (package drop list)",
            removed,
            "Not in the file; was on the package drop list, now empty (see Dropped and removed variables).",
        ),
        (
            "Dropped (keep_variables)",
            dropped,
            "Not in the file; left out by your keep_variables.",
        ),
        (
            "Skipped (dimension)",
            skipped,
            "Not in the file; its dimension is not placed on N_MEASUREMENTS (see Dimensions).",
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
    # ASCII arrows in the figure only: U+2192 is missing from common figure fonts
    # (Helvetica Neue on macOS), which matplotlib warns about; the HTML keeps "→".
    labels = [str(row[0]).replace("→", "->") for row in fate_rows]
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
    # The colorbar gets its own grid column: the renderer calls tight_layout, which cannot
    # place a colorbar that steals space from the strips (fig.colorbar(ax=...)).
    fig = plt.figure(figsize=(W_FULL, height))
    grid = fig.add_gridspec(
        2, 2 if has_density else 1, width_ratios=[40, 1][: 2 if has_density else 1]
    )
    top = fig.add_subplot(grid[0, 0])
    axes = [top, fig.add_subplot(grid[1, 0], sharex=top)]
    plt.setp(top.get_xticklabels(), visible=False)
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
            cax=fig.add_subplot(grid[:, 1]),
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
    # n_globals is additive: a schema-1 sidecar from before it still renders ("—").
    counts = (
        sorted({r["n_globals"] for r in inputs if r.get("n_globals") is not None})
        if inputs
        else []
    )
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
    reconciliation: list[tuple[str, str, str]],
    ledger: dict,
    requirement_amber: bool,
    og1_required_incomplete: bool = False,
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
    og1_required_incomplete : bool, default False
        Whether a variable OG1 requires is missing (the "Required by OG1" tier).

    Returns
    -------
    list of dict
        ``{"text", "bad"}`` clauses in display order; ``bad`` styles the clause amber.

    """
    inputs = int(reconciliation[-1][1])
    accounted = sum(int(row[1]) for row in reconciliation[:-1])
    n_dropped = len(ledger["dropped"])
    n_removed = len(ledger["removed"])
    # Mandatory means both the required globals and the required variables.
    missing = [
        part
        for part, short in (
            ("globals", requirement_amber),
            ("variables", og1_required_incomplete),
        )
        if short
    ]
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
            if not missing
            else f"OG1 mandatory incomplete ({' and '.join(missing)})",
            "bad": bool(missing),
        },
    ]


def _conventions_check(ds: xr.Dataset) -> dict[str, object]:
    """Return what the file's ``Conventions`` claims and what it holds against CF / ACDD.

    Presence counts only, not a compliance check: ACDD 1.3 highly recommended and
    recommended globals (:data:`seagliderOG1.vocabularies.ACDD_1_3_HIGHLY_RECOMMENDED`
    / ``ACDD_1_3_RECOMMENDED``) and, for CF, the floating-point data variables on a
    dimension with no ``units`` attribute.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 (or draft) dataset.

    Returns
    -------
    dict
        ``claim`` (the ``Conventions`` text), ``acdd`` (one ``{"level", "have",
        "total", "missing"}`` per level), ``no_units`` (sorted names) and ``short``
        (any count short).

    """
    present = {name for name, value in ds.attrs.items() if str(value).strip()}
    acdd = []
    for level, names in (
        ("highly recommended", vocabularies.ACDD_1_3_HIGHLY_RECOMMENDED),
        ("recommended", vocabularies.ACDD_1_3_RECOMMENDED),
    ):
        missing = [name for name in names if name not in present]
        acdd.append(
            {
                "level": level,
                "have": len(names) - len(missing),
                "total": len(names),
                "missing": missing,
            }
        )
    no_units = sorted(
        str(name)
        for name, var in ds.data_vars.items()
        if var.dtype.kind == "f" and var.ndim and "units" not in var.attrs
    )
    return {
        "claim": str(ds.attrs.get("Conventions", "")),
        "acdd": acdd,
        "no_units": no_units,
        "short": bool(no_units) or any(level["missing"] for level in acdd),
    }


def _draft_snippets(
    from_file: dict | None, dives: list[int] | None, og1_id: str
) -> list[dict[str, str]]:
    """Return the copyable ``mission.yaml`` lines a draft can fill from the files.

    Only what the draft read: the dive range, and the platform fields the converter
    derived from the first basestation file (the sidecar's ``platform_from_file``,
    the same :func:`seagliderOG1.vocabularies.platform_from_file` that ``init`` uses).
    Required fields the files cannot supply stay ``null`` for the user to fill.

    Parameters
    ----------
    from_file : dict or None
        The sidecar's ``platform_from_file`` (OG1 platform field to value).
    dives : list of int or None
        The input dive numbers, in order.
    og1_id : str
        The draft's ``id`` (``..._draft``).

    Returns
    -------
    list of dict
        ``{"title", "text"}`` blocks, in ``mission.yaml`` order; empty when the sidecar
        lacks the dives or the platform fields.

    """
    if from_file is None or not dives:
        return []
    platform = {
        field: from_file.get(field)
        for field, spec in vocabularies.PLATFORM_FIELDS.items()
        if field in from_file or spec.required
    }
    derived_id = og1_id.removesuffix("_draft")
    return [
        {
            "title": "Dive range",
            "text": f"dives: [{dives[0]}, {dives[-1]}]   # {len(dives)} dive files read",
        },
        {
            "title": "Platform (null: not in the files, fill by hand)",
            "text": yaml.safe_dump(
                {"platform": platform}, sort_keys=False, allow_unicode=True
            ).strip(),
        },
        {
            "title": "Deployment id",
            "text": (
                f"# derived for these dives: {derived_id}\n"
                "identity_and_discovery:\n  id: null   # leave null to keep it derived"
            ),
        },
    ]


# ACDD globals the converter can compute from the data or knows as constants: missing ones
# are a converter gap, not something to set in mission.yaml, so no box suggests them.
_ACDD_FROM_THE_DATA = frozenset(
    {
        "geospatial_bounds",
        "geospatial_bounds_crs",
        "geospatial_bounds_vertical_crs",
        "geospatial_vertical_positive",
        "time_coverage_duration",
        "time_coverage_resolution",
        "standard_name_vocabulary",
    }
)


# ACDD people and publisher globals: OG1 defines no creator or publisher and records people
# and organisations in contributor_* / contributing_institutions_* instead, so a missing
# one is covered there and no box suggests it.
_ACDD_COVERED_BY_OG1 = frozenset(
    {
        "creator_name",
        "creator_email",
        "creator_url",
        "creator_type",
        "creator_institution",
        "publisher_name",
        "publisher_email",
        "publisher_url",
        "publisher_type",
        "publisher_institution",
    }
)


def _platform_gaps(ds: xr.Dataset) -> dict[str, str]:
    """Return the required or file-derivable platform fields the conversion could not fill.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    dict of str to str
        Field to what was written: ``"written as UNK"`` or ``"omitted"`` (the numeric
        ``PLATFORM_DEPTH_RATING``). Optional platform variables are not listed.

    """
    gaps = {}
    for field, spec in vocabularies.PLATFORM_FIELDS.items():
        if spec.kind == "optional_string":
            continue
        if field not in ds.variables:
            gaps[field] = "omitted"
        elif str(ds[field].values) == "UNK":
            gaps[field] = "written as UNK"
    return gaps


def _yaml_block(key: str, value: object) -> str:
    """Return ``{key: value}`` as ``mission.yaml`` text, in the given order."""
    return yaml.safe_dump({key: value}, sort_keys=False, allow_unicode=True).strip()


def _null_block(key: str, comments: dict[str, str]) -> str:
    """Return a ``key:`` block with each field null and its comment."""
    lines = [f"{key}:"] + [f"  {f}: null   # {c}" for f, c in comments.items()]
    return "\n".join(lines)


def _config_suggestions(
    sidecar: dict | None,
    platform_gaps: dict[str, str] | None = None,
    acdd_missing: dict[str, str] | None = None,
    og1_id: str | None = None,
    og1_missing: list[str] | None = None,
) -> list[dict[str, object]]:
    """Return the ``mission.yaml`` blocks where the config and the output disagree or fall short.

    Each check is shown only when it finds something:

    - *Dive range*: the requested ``dives`` against the dives that reached the output.
    - *Platform from the files*: each platform field the config set against the value
      derived from the first basestation file
      (:func:`seagliderOG1.vocabularies.platform_from_file`). The config wins by design,
      so a pair is something to check, not an error.
    - *Platform not filled*: required or file-derivable fields written as ``UNK`` or
      omitted.
    - *Institution ids*: config institutions with no ``id`` that the EDMO registry
      resolved, as a block that pins the resolved name and id.
    - *Institution in the basestation files*: the file's ``institution`` global, when
      the registry matched it and no config institution resolved to the same id (the
      converter drops it when the config lists institutions).
    - *Deployment id*: the derived ``id`` when the conversion starts at dive 1 and the
      config left ``identity_and_discovery.id`` null, so a later conversion of part of the
      mission (which would derive a later start time) keeps it.
    - *Missing globals*: OG1 highly-desirable and ACDD 1.3 globals the file lacks, each
      under the global-attribute section that sets it (``identity_and_discovery:`` /
      ``rights_and_access:`` / ``provenance_and_processing:``), else under
      ``global_attributes:``; those the converter can compute, and the
      ``creator_*`` / ``publisher_*`` globals OG1 replaces with its contributor
      attributes, are left out.

    Parameters
    ----------
    sidecar : dict or None
        The conversion sidecar; its ``config`` (written by
        :func:`seagliderOG1.convert.process_mission`), ``presence``,
        ``platform_from_file``, ``institution_from_file`` and
        ``basestation_globals`` are read.
    platform_gaps : dict of str to str, optional
        From :func:`_platform_gaps`. Default is None.
    acdd_missing : dict of str to str, optional
        Missing ACDD 1.3 global to its level. Default is None.
    og1_id : str, optional
        The file's ``id``, offered as ``identity_and_discovery.id`` when the conversion
        starts at dive 1 and the config left ``id`` null. Default is None.
    og1_missing : list of str, optional
        OG1 highly-desirable globals the user supplies (tier ``config``) that the file
        lacks: the ones ``validate`` warns about. Default is None.

    Returns
    -------
    list of dict
        ``{"title", "note", "boxes"}`` blocks; ``boxes`` is a list of ``{"label",
        "text"}`` with ``text`` as ``mission.yaml`` lines.

    """
    sidecar = sidecar or {}
    config = sidecar.get("config") or {}
    blocks = []
    requested = config.get("dives")
    read = (sidecar.get("presence") or {}).get("dives") or []
    if requested and read and [read[0], read[-1]] != list(requested):
        missing = sorted(set(range(read[0], read[-1] + 1)) - set(read))
        note = f"{len(read)} dives converted, {read[0]} to {read[-1]}"
        if missing:
            note += "; not converted: " + ", ".join(str(d) for d in missing)
        blocks.append(
            {
                "title": "Dive range",
                "note": note + ".",
                "boxes": [
                    {
                        "label": "In the config",
                        "text": f"dives: [{requested[0]}, {requested[1]}]",
                    },
                    {
                        "label": "From the basestation files",
                        "text": f"dives: [{read[0]}, {read[-1]}]",
                    },
                ],
            }
        )
    if (
        og1_id
        and read
        and read[0] == 1
        and "deployment_id" in config
        and config["deployment_id"] is None
    ):
        blocks.append(
            {
                "title": "Deployment id",
                "note": (
                    "This conversion starts at dive 1, so the derived id names the "
                    "deployment start. Pin it: a later conversion of part of the mission "
                    "(dives starting after 1) would derive a later start time and so a "
                    "different id."
                ),
                "boxes": [
                    {
                        "label": "Derived from dive 1",
                        "text": f"identity_and_discovery:\n  id: {og1_id}",
                    }
                ],
            }
        )
    from_file = sidecar.get("platform_from_file") or {}
    found = sidecar.get("basestation_globals") or {}
    current, suggested, varies = {}, {}, []
    for field, value in (config.get("platform") or {}).items():
        if field not in from_file or str(value) == str(from_file[field]):
            continue
        current[field] = value
        suggested[field] = from_file[field]
        source = vocabularies.PLATFORM_FIELDS[field].source
        values = (found.get(source) or {}).get("values", [])
        if len(values) > 1:
            varies.append(f"{source} has {len(values)} values ({', '.join(values)})")
    if current:
        note = "From the first basestation file"
        if varies:
            note += "; across the files " + "; ".join(varies)
        blocks.append(
            {
                "title": "Platform from the files",
                "note": note + ".",
                "boxes": [
                    {
                        "label": "In the config",
                        "text": _yaml_block("platform", current),
                    },
                    {
                        "label": "From the basestation files",
                        "text": _yaml_block("platform", suggested),
                    },
                ],
            }
        )
    if platform_gaps:
        blocks.append(
            {
                "title": "Platform not filled",
                "note": "Set in neither the config nor the basestation files.",
                "boxes": [
                    {"label": "To fill", "text": _null_block("platform", platform_gaps)}
                ],
            }
        )
    institutions = config.get("institutions") or []
    # Silenced: the conversion already warned about the unmatched names.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        resolved = contributors.enrich_institutions(institutions)
    if any(_is_null_id(record.get("id")) for record in institutions):
        pinned = [
            {"name": r["name"], "role": r["role"], "id": r["id"] or None}
            for r in resolved
        ]
        newly = [
            r["name"]
            for r, record in zip(resolved, institutions, strict=True)
            if r["id"] and _is_null_id(record.get("id"))
        ]
        if newly:
            blocks.append(
                {
                    "title": "Institution ids",
                    "note": (
                        "Resolved by name against the package's EDMO registry: "
                        + ", ".join(newly)
                        + ". The block pins the registry name and id; an id left null "
                        "had no registry match."
                    ),
                    "boxes": [
                        {
                            "label": "Resolved",
                            "text": _yaml_block("institutions", pinned),
                        }
                    ],
                }
            )
    unmatched = [
        (str(record.get("name") or ""), record.get("role") or None)
        for r, record in zip(resolved, institutions, strict=True)
        if not r["id"] and _is_null_id(record.get("id"))
    ]
    for name, role in unmatched:
        near = _registry_candidates(name)
        if not near:
            continue
        blocks.append(
            {
                "title": "Institution not in the registry",
                "note": (
                    f"{name!r} matches no entry of the package's EDMO registry exactly, so it "
                    "is written with no id. Registry entries whose names contain every word of "
                    "it are below; use one if it is the same institution (the name resolves to "
                    "its id), or add the name to config/institution_registry.yaml."
                ),
                "boxes": [
                    {
                        "label": f"EDMO {code}",
                        "text": "\n".join(
                            [
                                "institutions:",
                                f"- name: {standard}",
                                f"  role: {role or 'null'}",
                                "  id: null   # resolves by name",
                            ]
                        ),
                    }
                    for code, standard in near
                ],
            }
        )
    from_file_institution = sidecar.get("institution_from_file") or {}
    if (
        institutions
        and from_file_institution.get("id")
        and from_file_institution["id"] not in {r["id"] for r in resolved}
    ):
        text = " ".join(from_file_institution["text"].split())
        entry = "\n".join(
            [
                "institutions:",
                f"- name: {from_file_institution['name']}",
                "  role: null   # set the role",
                f"  id: {from_file_institution['id']}",
            ]
        )
        blocks.append(
            {
                "title": "Institution in the basestation files",
                "note": (
                    f"The basestation institution global ({text!r}) matches this "
                    "registry entry. It is not written to the OG1 file because the "
                    "config lists institutions; add it there, with its role, if it "
                    "belongs."
                ),
                "boxes": [
                    {
                        "label": "From the basestation files",
                        "text": entry,
                    }
                ],
            }
        )
    acdd_missing = acdd_missing or {}
    # One label per missing global: OG1's own tier first (validate warns on it), then ACDD.
    labels = dict.fromkeys(og1_missing or (), "OG1 highly desirable")
    for name, level in acdd_missing.items():
        acdd = f"ACDD {level}"
        labels[name] = f"{labels[name]}; {acdd}" if name in labels else acdd
    # One box per mission.yaml section that sets a missing global; the rest go under
    # global_attributes:. program/program_vocabulary/network have no section (the platform
    # registry supplies them), so they fall to global_attributes: here.
    boxes = []
    boxed: set[str] = set()
    for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items():
        block = {name: labels[name] for name in keys if name in labels}
        if block:
            boxes.append({"label": f"{slug}:", "text": _null_block(slug, block)})
            boxed.update(block)
    escape = {
        name: label
        for name, label in labels.items()
        if name not in boxed
        and name not in _ACDD_FROM_THE_DATA
        and name not in _ACDD_COVERED_BY_OG1
    }
    if escape:
        boxes.append(
            {
                "label": "global_attributes:",
                "text": _null_block("global_attributes", escape),
            }
        )
    if boxes:
        left = sorted(_ACDD_FROM_THE_DATA.intersection(acdd_missing))
        note = (
            "OG1 highly desirable and ACDD 1.3 globals the file does not carry (the "
            "OG1 ones are those validate warns about)."
        )
        if left:
            note += (
                " Not listed, because the converter should supply them "
                "(computed from the data, or a constant): " + ", ".join(left) + "."
            )
        covered = sorted(_ACDD_COVERED_BY_OG1.intersection(acdd_missing))
        if covered:
            note += (
                " Not listed, because OG1 records people and organisations in "
                "contributor_* and contributing_institutions_* instead: "
                + ", ".join(covered)
                + "."
            )
        blocks.append({"title": "Missing globals", "note": note, "boxes": boxes})
    return blocks


def _registry_candidates(name: str, limit: int = 3) -> list[tuple[str, str]]:
    """Return registry entries with a name containing every word of ``name``.

    Parameters
    ----------
    name : str
        An institution name the registry did not match exactly.
    limit : int, optional
        At most this many entries, by EDMO code. Default is 3.

    Returns
    -------
    list of (str, str)
        ``(EDMO code, standard_name)`` pairs.

    """
    words = set(re.findall(r"\w+", name.lower()))
    found = []
    for code, entry in contributors.institution_registry().items():
        names = [entry["standard_name"], *entry.get("name_variants", [])]
        if any(words <= set(re.findall(r"\w+", n.lower())) for n in names):
            found.append((str(code), entry["standard_name"]))
    return sorted(found, key=lambda pair: int(pair[0]))[:limit]


def _is_null_id(value: object) -> bool:
    """Return True for an institution ``id`` the config left unset."""
    return value in (None, "", "None")


def _basestation_rows(found: dict | None, n_files: int) -> list[dict[str, object]]:
    """Return one row per basestation global attribute for the draft page.

    Parameters
    ----------
    found : dict or None
        The sidecar's ``basestation_globals`` (name to ``{"values", "n_files"}``), or
        None when the sidecar does not carry it.
    n_files : int
        Input files in the conversion.

    Returns
    -------
    list of dict
        ``{"name", "value", "status", "distinct", "bad"}``: the first file's value; where
        it appears (``"all N files"``, ``"k of N files"``); every distinct value when
        there is more than one; ``bad`` when it varies or is missing from some files.

    """
    rows = []
    for name, entry in (found or {}).items():
        values = entry["values"]
        k = entry["n_files"]
        where = f"all {n_files} files" if k == n_files else f"{k} of {n_files} files"
        varies = len(values) > 1
        rows.append(
            {
                "name": name,
                "value": values[0] if values else "",
                "status": f"{where}; {len(values)} values" if varies else where,
                "distinct": values if varies else [],
                "bad": varies or k != n_files,
            }
        )
    return rows


def render_conversion(
    path: str | Path, *, title: str | None = None, verify: bool = False
) -> str:
    """Return the conversion page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert.to_og1`.
    title : str, optional
        The page title; defaults to the file name.
    verify : bool, optional
        Check the file against the SHA-256 in its sidecar and warn when it changed
        (see :func:`seagliderOG1.convert.conversion_sidecar`). Default is False: a page
        written straight after the conversion has nothing to check.

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
    sidecar = convert.conversion_sidecar(path, verify=verify)
    inputs = sidecar.get("inputs") if sidecar else None
    dim_samples = _dimension_samples(inputs)

    ds = xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False)
    try:
        # A draft (process_mission(draft=True), the draft verb) says so in a global; the
        # page then shows the basestation's own globals instead of the OG1 ones.
        # By value, not by name: a file could carry some other global called draft.
        draft = ds.attrs.get("draft") == convert.DRAFT_NOTE
        ds_id = ds.attrs.get("id", "")
        conventions = _conventions_check(ds)
        platform_gaps = _platform_gaps(ds)
        acdd_missing = {
            name: level["level"]
            for level in conventions["acdd"]
            for name in level["missing"]
        }
        og1_missing = [
            name
            for name, source in vocabularies.REQUIRED_GLOBALS[
                "highly_desirable"
            ].items()
            if source == "config" and not str(ds.attrs.get(name, "")).strip()
        ]
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
        # OG1-first view, tier 1: the required variables. Valid % for the dimensioned ones
        # comes from the coordinate rows and the grouped variable rows already built.
        coord_rows, _coord_source = nc_tables.coords_rows(
            ds, original_name_attrs=design.ORIGINAL_NAME_ATTRS
        )
        valid_by_name = {r["name"]: r["valid_pct"] for r in coord_rows}
        for _group_title, group_rows in groups:
            for r in group_rows:
                valid_by_name[r["name"]] = r["valid_pct"]
        og1_required, og1_required_caption, og1_required_incomplete = (
            _og1_required_rows(ds, ledger, valid_by_name)
        )
        og1_candidate_groups = _og1_candidate_groups(ds, ledger, valid_by_name)
        og1_named, og1_carried = _og1_tiers(ds, ledger, valid_by_name)
        og1_sensors = _og1_sensor_rows(ds)
        duplicate_groups = _duplicate_groups(ds)
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
        verdict_clauses = _verdict_clauses(
            reconciliation, ledger, requirement_amber, og1_required_incomplete
        )
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
        og1_required=og1_required,
        og1_required_caption=og1_required_caption,
        og1_required_incomplete=og1_required_incomplete,
        og1_candidate_groups=og1_candidate_groups,
        og1_named=og1_named,
        og1_sensors=og1_sensors,
        og1_carried=og1_carried,
        duplicate_groups=duplicate_groups,
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
        draft=draft,
        conventions=conventions,
        draft_snippets=_draft_snippets(
            sidecar.get("platform_from_file") if sidecar else None,
            (sidecar.get("presence") or {}).get("dives") if sidecar else None,
            str(ds_id),
        )
        if draft
        else [],
        config_suggestions=[]
        if draft
        else _config_suggestions(
            sidecar, platform_gaps, acdd_missing, str(ds_id), og1_missing
        ),
        basestation_rows=_basestation_rows(
            sidecar.get("basestation_globals") if sidecar else None,
            len(inputs) if inputs else 0,
        ),
    )
