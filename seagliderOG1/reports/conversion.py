"""Render the Conversion page: the summary of one conversion.

Sections, in reading order: Summary (a how-to-read box, tiles, stage pills linking to the
Processing page, the verdict line), the mission.yaml suggestions, Losses, Flight model,
Sensors and calibration comments, One variable traced, and the Glossary. A draft adds the
basestation's own global attributes; for an OG1 file those are on the OG1 format page.

The Variables, Processing and OG1 format pages hold the detail; the losses, stages, flight
panel and traced variable come from :mod:`.processing` so the pages agree. Counts that need
the conversion record (``<id>_conversion.json``) read "not recorded" when it is missing.
"""

import json
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr
import yaml

if TYPE_CHECKING:
    pass

from seagliderOG1 import __version__, contributors, vocabularies, writers
from seagliderOG1.reports import _index, _masthead, _pages, _record, design, processing
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


def _is_placeholder(value: str) -> bool:
    """Return True for an empty value, ``UNK``, or one whose digits are all zero.

    Values of only zeros and dashes (``0000``, ``00-00-0000``) are the placeholders files
    written by seagliderOG1 0.2.0 and earlier carry; a serial with letters (``F0000``) is
    an identifier, not a placeholder.
    """
    text = value.strip()
    return not text or text == "UNK" or bool(re.fullmatch(r"[0\-]*0[0\-]*", text))


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
        ``bad`` when the serial or calibration date is a placeholder (empty, ``UNK``, or
        every digit zero) or the serial is shared.

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


def _calibration_comment_rows(ds: xr.Dataset) -> list[dict[str, object]] | None:
    """Return one row per ``SENSOR_*`` variable: the basestation comment and what was read.

    The left side is the source — the basestation variable the comment came from and the
    comment as written (``original_calibcomm``); the right side is the result — the
    ``SENSOR_*`` variable, its serial number, calibration date and per-channel dates, the
    rules that read them, and the note and checks from the ``conversion_sensor_calibration``
    global.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.

    Returns
    -------
    list of dict or None
        ``{"source_variable", "original", "name", "serial", "calibration", "channels",
        "rules", "note", "bad"}`` rows, name-sorted; ``bad`` when the serial or the
        calibration date is a placeholder, the serial was taken from a lone token and not
        corrected by the mission config, or a check fired (a calibration date after the first sample or long before it, a serial
        shared with another sensor). None when the file has no
        ``conversion_sensor_calibration`` global (written by seagliderOG1 0.2.0 or earlier).

    """
    raw = ds.attrs.get("conversion_sensor_calibration")
    if raw is None:
        return None
    records = json.loads(str(raw))
    rows = []
    for name in sorted(records):
        record = records[name]
        attrs = ds[name].attrs if name in ds.variables else {}
        serial = str(attrs.get("sensor_serial_number", ""))
        calibration = str(attrs.get("sensor_calibration_date", ""))
        overridden = record.get("overridden", [])
        notes = [record.get("note", "")] + list(record.get("checks", []))
        notes += [f"{attr} from the mission config" for attr in overridden]
        rows.append(
            {
                "source_variable": record.get("source_variable") or "—",
                "original": str(attrs.get("original_calibcomm", "")) or "—",
                "name": name,
                "serial": serial,
                "calibration": calibration,
                "channels": str(attrs.get("sensor_calibration_dates", "")),
                "rules": f"{record.get('serial_rule', '')} / {record.get('date_rule', '')}",
                "note": "; ".join(n for n in notes if n),
                "bad": _is_placeholder(serial)
                or _is_placeholder(calibration)
                or (
                    record.get("serial_rule") == "bare-token"
                    and "sensor_serial_number" not in overridden
                )
                or bool(record.get("checks")),
            }
        )
    return rows


#: Columns of the calibration-comments table: key, header, relative width, whether the
#: cell wraps, and whether the column is dropped when every row leaves it empty.
_CALIBRATION_COLUMNS = (
    ("source_variable", "Basestation variable", 15, True, False),
    ("original", "Original", 24, True, False),
    ("name", "OG1 Sensor", 18, True, False),
    ("serial", "Serial", 8, False, False),
    ("calibration", "Calibration", 10, False, False),
    ("channels", "Channel dates", 15, True, True),
    ("rules", "Rules (serial / date)", 12, False, False),
    ("note", "Note", 15, True, True),
)


def _calibration_comment_columns(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return the calibration-comments table columns, dropping optional empty ones.

    Channel dates and Note are shown only when at least one row has a value, and the
    widths of the columns kept are rescaled to sum to 100 %, so the remaining columns
    get the space.

    Parameters
    ----------
    rows : list of dict
        The rows from :func:`_calibration_comment_rows`.

    Returns
    -------
    list of dict
        ``{"key", "header", "width", "wrap"}`` per column kept, in table order; ``width``
        is a percentage.

    """
    kept = [
        (key, header, weight, wrap)
        for key, header, weight, wrap, optional in _CALIBRATION_COLUMNS
        if not optional or any(row.get(key) for row in rows)
    ]
    total = sum(weight for _, _, weight, _ in kept)
    return [
        {
            "key": key,
            "header": header,
            "width": round(100 * weight / total),
            "wrap": wrap,
        }
        for key, header, weight, wrap in kept
    ]


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
        The parsed ledger from ``conversion_ledger``.

    Returns
    -------
    rows : list of (str, str, str)
        ``(label, count, meaning)`` rows; the final row is the basestation input total with
        an empty meaning.
    caption : str
        Whether the fates sum to the input count.

    """
    fates = _index.fate_sets(ds, ledger)
    renamed, passed, consumed = (
        fates["renamed"],
        fates["passthrough"],
        fates["consumed"],
    )
    removed, dropped, skipped = fates["removed"], fates["dropped"], fates["skipped"]
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


# At most this many contiguous patterns get a strip each; the rest share the sporadic row.


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


def _unit_corrections_rows(ds: xr.Dataset) -> list[dict[str, object]]:
    """Return one row per variable whose units the conversion corrected, converted, or adopted.

    Reads each variable's ``original_units`` attribute and the ``conversion_units`` ledger
    (``output name -> [source, canonical, factor]``). Three actions appear: a factor-1 label
    correction (the label was wrong for the magnitude, the value is unchanged); a conversion
    (the values were scaled by the factor); and an adoption (the source carried no units, so the
    OG1 label was taken). A pure spelling rewrite (factor 1, resolved from the view, no recorded
    ``original_units``) is not listed — the Unit mapping docs page carries the full spelling view.

    Parameters
    ----------
    ds : xarray.Dataset
        The converted OG1 dataset.

    Returns
    -------
    list of dict
        ``{"name", "original", "written", "action"}`` rows, sorted by name.

    """
    ledger: dict = {}
    raw = ds.attrs.get("conversion_units")
    if raw:
        try:
            ledger = json.loads(raw)
        except (ValueError, TypeError):
            ledger = {}
    rows = []
    for name in ds.variables:
        attrs = ds[name].attrs
        if "original_units" not in attrs and name not in ledger:
            continue
        written = str(attrs.get("units", ""))
        if name in ledger:
            source, _canonical, factor = ledger[str(name)]
            rows.append(
                {
                    "name": str(name),
                    "original": str(source),
                    "written": written,
                    "action": f"converted (×{factor:g})",
                }
            )
        elif str(attrs.get("original_units", "")) == "":
            rows.append(
                {
                    "name": str(name),
                    "original": "— (none)",
                    "written": written,
                    "action": "OG1 label adopted (source unlabelled)",
                }
            )
        else:
            rows.append(
                {
                    "name": str(name),
                    "original": str(attrs["original_units"]),
                    "written": written,
                    "action": "label corrected (value unchanged)",
                }
            )
    return sorted(rows, key=lambda r: r["name"])


def _drop_recommendation(ds: xr.Dataset) -> dict[str, object] | None:
    """Return a ``drop_variables`` suggestion block for variables OG1 defines differently.

    A variable present in the output whose OG1 or basestation name is in
    :data:`seagliderOG1.vocabularies.DROP_RECOMMENDATIONS` is recommended for
    ``drop_variables``, with the reason. Returns None when none are present.

    Parameters
    ----------
    ds : xarray.Dataset
        The converted OG1 dataset.

    Returns
    -------
    dict or None
        A ``{"title", "note", "boxes"}`` block, or None.

    """
    found = {}
    for name in ds.data_vars:
        original = str(ds[name].attrs.get("original_name", ""))
        for candidate in (name, original):
            if candidate in vocabularies.DROP_RECOMMENDATIONS:
                found[candidate] = vocabularies.DROP_RECOMMENDATIONS[candidate]
    if not found:
        return None
    names = sorted(found)
    reasons = " ".join(f"{name}: {found[name]}" for name in names)
    text = "drop_variables:\n" + "\n".join(f"  - {name}" for name in names)
    return {
        "title": "Variables OG1 defines differently",
        "note": (
            "These passed through under their basestation names; OG1 has no home for "
            "them, or names them for a different quantity. Add them to "
            f"drop_variables to leave them out of the file. {reasons}"
        ),
        "boxes": [{"label": "In the config", "text": text}],
    }


def _duplicate_recommendation(ds: xr.Dataset) -> dict[str, object] | None:
    """Return a ``drop_variables`` block for pass-through duplicates of a mapped variable.

    A variable that passed through under its basestation name (its ``original_name``
    equals its own name) and is numerically identical to a mapped OG1 variable (same
    shape, same finite points, values equal to float precision) is redundant. The
    mapped OG1 variable is the one to keep; the pass-through copy is recommended for
    ``drop_variables``. Returns None when none are found.

    Parameters
    ----------
    ds : xarray.Dataset
        The converted OG1 dataset.

    Returns
    -------
    dict or None
        A ``{"title", "note", "boxes"}`` block, or None.

    """
    mapped = {
        name: ds[name]
        for name in ds.data_vars
        if ds[name].ndim >= 1
        and ds[name].dtype.kind in "fiu"
        and str(ds[name].attrs.get("original_name", "")) not in ("", name)
    }
    pairs = []  # (passthrough_name, mapped_og1_name)
    for name in ds.data_vars:
        var = ds[name]
        if (
            var.ndim < 1
            or var.dtype.kind not in "fiu"
            or str(var.attrs.get("original_name", "")) != name
        ):
            continue
        values = np.asarray(var.values, dtype="float64")
        finite = np.isfinite(values)
        if not finite.any():
            continue
        for og1_name, other in mapped.items():
            if other.dims != var.dims or other.shape != var.shape:
                continue
            other_values = np.asarray(other.values, dtype="float64")
            if not np.array_equal(finite, np.isfinite(other_values)):
                continue
            if np.allclose(values[finite], other_values[finite], rtol=1e-5, atol=1e-3):
                pairs.append((name, og1_name))
                break
    if not pairs:
        return None
    pairs.sort()
    reasons = "; ".join(
        f"{passthrough} is identical to {og1}, which maps to the OG1 variable"
        for passthrough, og1 in pairs
    )
    text = "drop_variables:\n" + "\n".join(f"  - {p}" for p, _ in pairs)
    return {
        "title": "Duplicate variables",
        "note": (
            "These passed through under their basestation names but hold the same "
            f"values as a mapped OG1 variable, so they are redundant. {reasons}. Keep "
            "the mapped one and drop the copy."
        ),
        "boxes": [{"label": "In the config", "text": text}],
    }


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
        :func:`seagliderOG1.process`), ``presence``,
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
    # global_attributes:. program/program_vocabulary/network have no section (a local-config
    # overlay will supply them), so they fall to global_attributes: here.
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


def _fate_counts(rows: list[_index.VariableRow]) -> list[tuple[str, int]]:
    """Return ``(fate, count)`` for every fate with entries, in :data:`_index.FATES` order."""
    keys = [key for key, _meaning in _index.FATES] + ["derived"]
    counts = {key: sum(r["fate"] == key for r in rows) for key in keys}
    return [(key, counts[key]) for key in keys if counts[key]]


def _tiles(
    ds: xr.Dataset,
    ledger: dict,
    record: dict | None,
    rows: list[_index.VariableRow],
    loss_rows: list[processing.Loss],
) -> list[dict[str, object]]:
    """Return the summary tiles at the top of the Conversion page.

    Parameters
    ----------
    ds : xarray.Dataset
        The open OG1 dataset.
    ledger : dict
        Its parsed ledger.
    record : dict or None
        The conversion record beside the file, or None.
    rows : list of VariableRow
        The variable index.
    loss_rows : list of Loss
        From :func:`seagliderOG1.reports.processing.losses`.

    Returns
    -------
    list of dict
        ``{"label", "value", "bad"}`` per tile, in display order; ``bad`` highlights it.

    """
    inputs = (record or {}).get("inputs") or []
    dives = ((record or {}).get("presence") or {}).get("dives") or []
    n_in = ledger["input_variable_count"]
    accounted = sum(1 for r in rows if r["basestation"] and r["fate"] != "unattributed")
    counted = [loss for loss in loss_rows if loss["count"]]
    unknown = [loss for loss in loss_rows if loss["count"] is None]
    touched = sum(loss["count"] or 0 for loss in loss_rows)
    fates = dict(_fate_counts(rows))
    factors = sum(1 for r in rows if r["factor"] not in (None, 1) and r["basestation"])
    downcast = sum(
        1 for r in rows if any(m["text"] == "float64 → float32" for m in r["marks"])
    )
    return [
        {
            "label": "Dive files read",
            "value": f"{len(inputs)}" if inputs else "not recorded",
            "bad": not inputs,
        },
        {
            "label": "Variables",
            "value": f"{n_in} in → {len(ds.variables)} out",
            "bad": False,
        },
        {
            "label": "Accounted for",
            "value": f"{accounted} / {n_in}",
            "bad": accounted != n_in,
        },
        {
            "label": "Losses",
            "value": f"{len(counted)} kinds, {touched} items"
            + (f"; {len(unknown)} not recorded" if unknown else ""),
            "bad": bool(counted or unknown),
        },
        {
            "label": "Renamed to OG1",
            "value": str(fates.get("renamed", 0)),
            "bad": False,
        },
        {
            "label": "Passed through",
            "value": str(fates.get("passthrough", 0)),
            "bad": False,
        },
        {
            "label": "Built by the converter",
            "value": str(fates.get("derived", 0)),
            "bad": False,
        },
        {
            "label": "Consumed into others",
            "value": str(fates.get("consumed", 0)),
            "bad": False,
        },
        {"label": "Unit factors applied", "value": str(factors), "bad": False},
        {"label": "float64 → float32", "value": str(downcast), "bad": False},
        {
            "label": "Data points",
            "value": f"{ds.sizes.get('N_MEASUREMENTS', 0):,}",
            "bad": False,
        },
        {
            "label": "Dives in the file",
            "value": str(len(dives)) if dives else "not recorded",
            "bad": not dives,
        },
    ]


def render_conversion(
    path: str | Path, *, title: str | None = None, verify: bool = False
) -> str:
    """Return the conversion page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`.
    title : str, optional
        The page title; defaults to the file name.
    verify : bool, optional
        Check the file against the SHA-256 in its sidecar and warn when it changed
        (see the conversion record). Default is False: a page
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
    sidecar = _record.conversion_sidecar(path, verify=verify)
    inputs = sidecar.get("inputs") if sidecar else None

    ds = xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False)
    try:
        # A draft (the draft verb, the draft verb) says so in a global; the
        # page then shows the basestation's own globals instead of the OG1 ones.
        # By value, not by name: a file could carry some other global called draft.
        draft = ds.attrs.get("draft") == vocabularies.DRAFT_NOTE
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
        ledger = _record.conversion_ledger(ds)
        groups, _var_source = _variable_groups_by_original_dimension(ds)
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
        og1_sensors = _og1_sensor_rows(ds)
        calibration_comments = _calibration_comment_rows(ds)
        calibration_columns = (
            _calibration_comment_columns(calibration_comments)
            if calibration_comments
            else []
        )
        reconciliation, _reconciliation_caption = _reconciliation(ds, ledger)
        requirement_text, requirement_amber = _requirement_summary(ds)
        verdict_clauses = _verdict_clauses(
            reconciliation, ledger, requirement_amber, og1_required_incomplete
        )
        rows = _index.variable_rows(ds, ledger, sidecar)
        steps = processing.processing_steps(ds, ledger, sidecar, rows)
        loss_rows = processing.losses(sidecar, rows)
        flight = processing.flight_rows(rows)
        traced = processing.traced_variable(rows, steps)
        tiles = _tiles(ds, ledger, sidecar, rows, loss_rows)
        has_phase = "PHASE" in ds.variables and not draft
    finally:
        ds.close()

    return get_template("conversion.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        masthead=_masthead.masthead(path, "conversion", title=title),
        # No phase page beside a draft.
        page_nav=_pages.page_nav(path, "conversion", has_phase=has_phase, draft=draft),
        tiles=tiles,
        stages=processing.stage_states(steps),
        processing_href=writers.page_path(path, "processing").name,
        variables_href=writers.page_path(path, "variables").name,
        phase_href=writers.page_path(path, "phase").name if has_phase else "",
        og1_href=writers.page_path(path, "og1").name,
        losses=loss_rows,
        flight=flight,
        traced=traced,
        fates=_fate_counts(rows),
        fate_meanings=dict(_index.FATES)
        | {"derived": "Built by the converter; its inputs are listed."},
        verdict_clauses=verdict_clauses,
        og1_required_incomplete=og1_required_incomplete,
        og1_sensors=og1_sensors,
        calibration_comments=calibration_comments,
        calibration_columns=calibration_columns,
        record_present=sidecar is not None,
        requirement_text=requirement_text,
        requirement_amber=requirement_amber,
        record_name=writers.conversion_path(path, ".json").name,
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
        else [
            *_config_suggestions(
                sidecar, platform_gaps, acdd_missing, str(ds_id), og1_missing
            ),
            *([rec] if (rec := _drop_recommendation(ds)) else []),
            *([dup] if (dup := _duplicate_recommendation(ds)) else []),
        ],
        basestation_rows=_basestation_rows(
            sidecar.get("basestation_globals") if sidecar else None,
            len(inputs) if inputs else 0,
        ),
    )
