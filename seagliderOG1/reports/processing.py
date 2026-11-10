"""The Processing page, and the summaries the Conversion page draws from the same facts.

The Processing page lists every step of the conversion in the order it runs, with the rule
it applies, the variables it touched, whether it keeps the input recoverable, and where a
reader of the OG1 file alone can find what it did. A step whose effect the file does not
record says so ("not recorded") rather than being inferred.

The Conversion page's losses list, stage pills, flight-model panel and traced variable are
built here too, so the two pages cannot disagree.
"""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import xarray as xr

from seagliderOG1 import __version__, vocabularies, writers
from seagliderOG1.reports import _index, _pages, _record, design
from seagliderOG1.reports._env import get_template
from seagliderOG1.reports._index import VariableRow

__all__ = [
    "STAGES",
    "Loss",
    "Step",
    "flight_rows",
    "losses",
    "processing_steps",
    "render_processing",
    "stage_states",
    "traced_variable",
    "write_processing_page",
]

#: The conversion's stages, in run order, as ``(key, label)``; every step belongs to one.
STAGES: tuple[tuple[str, str], ...] = (
    ("read", "Read"),
    ("map", "Map names"),
    ("units", "Units"),
    ("merge", "Merge onto TIME"),
    ("derive", "Derive"),
    ("store", "Store"),
    ("write", "Write"),
)


class Step(TypedDict):
    """One step of the conversion, as the Processing page shows it."""

    number: int
    stage: str
    step: str
    rule: str
    variables: str
    lossless: str
    recorded: str
    recorded_in_file: bool
    code: str


class Loss(TypedDict):
    """One kind of loss: something in the basestation files not in the OG1 file as it was."""

    loss: str
    kind: str
    count: int | None
    examples: list[str]
    recorded: str


def _marked(rows: Sequence[VariableRow], text: str) -> list[str]:
    """Return the basestation names of the index entries carrying a mark with this text."""
    return [
        r["basestation"] or r["name"]
        for r in rows
        if any(m["text"] == text for m in r["marks"])
    ]


def _numbered_copies(ds: xr.Dataset) -> list[str]:
    """Return the output names that are numbered copies of an OG1 name (``DEPTH_2``)."""
    copies = []
    for name in ds.variables:
        match = re.fullmatch(r"(.+)_(\d+)", str(name))
        if match and match[1] in vocabularies.vocab_attrs:
            copies.append(str(name))
    return sorted(copies)


def _count(names: Sequence[str], limit: int = 4) -> str:
    """Return ``"<n>: a, b, c, …"`` for a step's Variables cell."""
    if not names:
        return "none"
    shown = ", ".join(names[:limit])
    return f"{len(names)}: {shown}{', …' if len(names) > limit else ''}"


def processing_steps(
    ds: xr.Dataset,
    ledger: Mapping,
    record: Mapping | None,
    rows: Sequence[VariableRow],
) -> list[Step]:
    """Return every step of the conversion, in run order.

    Parameters
    ----------
    ds : xarray.Dataset
        The open OG1 dataset.
    ledger : collections.abc.Mapping
        Its parsed ledger (:func:`seagliderOG1.reports._record.conversion_ledger`).
    record : collections.abc.Mapping or None
        The conversion record beside the file, or None.
    rows : sequence of VariableRow
        The variable index (:func:`seagliderOG1.reports._index.variable_rows`).

    Returns
    -------
    list of Step
        One entry per step, numbered from 1 in run order.

    """
    inputs = (record or {}).get("inputs") or []
    renamed = [r["basestation"] for r in rows if r["fate"] == "renamed"]
    factors = [
        r["basestation"]
        for r in rows
        if r["factor"] is not None and r["factor"] != 1 and r["basestation"]
    ]
    spelling = _marked(rows, "unit spelling not kept")
    relabelled = _marked(rows, "units relabelled")
    adopted = _marked(rows, "units adopted")
    downcast = _marked(rows, "float64 → float32")
    json_text = _marked(rows, "numbers → JSON text")
    dims = ledger["dimensions"]
    placed = sorted(d for d, info in dims.items() if info["fate"] != "skipped")
    time_sources = list(ledger["derived"].get("TIME", []))
    shifted = "duplicate_timestamp_adjustments" in ds["TIME"].attrs
    derived = [
        r["name"] for r in rows if r["fate"] == "derived" and r["name"] != "TIME"
    ]
    unrecorded = _marked(rows, "inputs not recorded")
    qc = sorted(str(n) for n in ds.variables if str(n).endswith("_QC"))
    sensors = sorted(str(n) for n in ds.variables if str(n).startswith("SENSOR_"))
    gps = "LATITUDE_GPS" in ds.variables
    dropped_fixes = ds.attrs.get("conversion_dropped_gps_fixes")
    input_ok = bool(record and record.get("input_variables"))

    raw: list[tuple[str, str, str, str, str, str, bool, str]] = [
        (
            "read",
            "read dive files",
            "every p<SSS><DDDD>.nc in the mission's raw_dir, in dive order",
            f"{len(inputs)} dive files" if inputs else "not recorded",
            "yes",
            "conversion record: inputs (file, size, checksum)"
            if inputs
            else "not recorded",
            bool(inputs),
            "_convert._convert_mission",
        ),
        (
            "read",
            "reject a dive",
            "a dive without ctd_time or a usable position is left out",
            "not recorded",
            "no: the dive's data is not written",
            "log only",
            False,
            "_pipeline._validate_coords",
        ),
        (
            "map",
            "rename to OG1",
            "config/OG1_variable_names.yaml; eng_, ctd_ and <instrument>_ prefixes "
            "are stripped before the lookup",
            _count(renamed),
            "yes",
            "original_name on each variable",
            True,
            "_pipeline.og1_name_mapping",
        ),
        (
            "map",
            "shared OG1 name",
            "when several basestation variables map to one OG1 name, the first "
            "(CTD first, then not QC, then input order) keeps it; the others become "
            "NAME_2, NAME_3, without OG1 attributes",
            _count(_numbered_copies(ds)),
            "yes",
            "original_name; the rule is stated only here",
            False,
            "_pipeline.og1_name_mapping",
        ),
        (
            "units",
            "convert units",
            "config/OG1_unit_corrections.yaml and the units table: values scaled "
            "by the factor (cm/s to m s-1 ×0.01, S/m to mS cm-1 ×10)",
            _count(factors),
            "yes: the factor is stored",
            "original_units and comment on each; conversion_units global",
            True,
            "_convert._to_canonical_units",
        ),
        (
            "units",
            "correct or adopt a unit label",
            "a wrong basestation label is corrected (values unchanged); a variable "
            "with no units takes the OG1 label",
            _count(relabelled + adopted),
            "yes",
            "original_units and comment on each",
            True,
            "_convert._to_canonical_units",
        ),
        (
            "units",
            "respell units",
            "a known spelling is replaced by the canonical one (meters to m, "
            "degrees to degree), factor 1",
            _count(spelling) if input_ok else "not recorded",
            "the original spelling is not kept",
            "not recorded",
            False,
            "_convert._canonical_passthrough_units",
        ),
        (
            "merge",
            "split by dimension",
            "the variables of each basestation dimension are grouped with that "
            "dimension's time variable",
            _count(placed),
            "yes",
            "original_dimension on each variable; conversion_dimensions global",
            True,
            "tools.split_by_unique_dims",
        ),
        (
            "merge",
            "make G&C state times absolute",
            "gc_state_secs written as seconds since the dive start (all below 1990 "
            "s) gets the file's start_time added",
            "gc_state_secs",
            "yes",
            "log only",
            False,
            "_pipeline._absolute_state_times",
        ),
        (
            "merge",
            "merge onto one time axis",
            "every dimension is joined on exact time (outer join) into "
            "N_MEASUREMENTS; the magnetometer by position",
            _count(time_sources),
            "yes",
            "conversion_derived_variables[TIME]",
            True,
            "_pipeline.merge_datasets_along_time",
        ),
        (
            "merge",
            "drop exact duplicates",
            "a record repeating an earlier one at the same time, identical in every "
            "value, is dropped",
            "not recorded",
            "yes: identical",
            "log only",
            False,
            "_pipeline._exact_duplicate_rows",
        ),
        (
            "merge",
            "shift same-time records",
            "a later record at the same time that differs is moved +0.5 s per repeat",
            "recorded for the first dive only" if shifted else "none in the file",
            "no: the time is moved",
            "TIME attributes, first dive only" if shifted else "TIME attributes",
            False,
            "_pipeline.merge_datasets_along_time",
        ),
        (
            "merge",
            "join the dives",
            "dives concatenated and sorted by TIME",
            f"{ds.sizes.get('N_MEASUREMENTS', 0):,} data points",
            "yes",
            "the data",
            True,
            "_convert._convert",
        ),
        (
            "derive",
            "GPS fixes",
            "each fix is one data point carrying LATITUDE_GPS, LONGITUDE_GPS and "
            "TIME_GPS; LATITUDE and LONGITUDE take the fix and DEPTH 0 m where "
            "they were empty; a re-logged fix at a dive boundary is dropped",
            "LATITUDE_GPS, LONGITUDE_GPS, TIME_GPS" if gps else "none",
            "yes: adds",
            "the fill of LATITUDE, LONGITUDE and DEPTH is not recorded"
            + (
                "; dropped fixes in conversion_dropped_gps_fixes"
                if dropped_fixes
                else ""
            ),
            False,
            "_convert.add_gps_info_to_dataset",
        ),
        (
            "derive",
            "derive variables",
            "PHASE from the OG1 phase table, then PROFILE_NUMBER, PROFILE_DIRECTION, "
            "SEGMENT_NUMBER; DEPTH_Z; POTDENS0 (and PSAL from conductivity) where "
            "the basestation has none; platform and deployment from mission.yaml",
            _count(derived),
            "yes: adds",
            f"conversion_derived_variables; inputs not recorded for {len(unrecorded)}"
            if unrecorded
            else "conversion_derived_variables",
            not unrecorded,
            "tools.add_phase, tools.add_profiles, _pipeline.add_teos10_variables",
        ),
        (
            "derive",
            "sensors",
            "a SENSOR_* variable per instrument, with serial number and calibration "
            "date read from the calibration comments",
            _count(sensors),
            "yes; the per-variable sensor attribute is removed",
            "conversion_sensor_calibration; original_calibcomm on each",
            True,
            "_pipeline.add_sensor_to_dataset",
        ),
        (
            "store",
            "per-dive parameters",
            "a scalar constant across dives is one value; one that changes is JSON "
            'text {"dives": [...], "values": [...]}',
            _count(json_text) if input_ok else "not recorded",
            "no: numbers become text; _FillValue and valid_* are removed",
            "storage_type on each",
            True,
            "_pipeline.add_scalar_parameters",
        ),
        (
            "store",
            "storage types",
            "float64 becomes float32 unless the name contains latitude, longitude "
            "or time; an integer on the shared axis becomes float32",
            _count(downcast) if input_ok else "not recorded",
            "no: precision",
            "not recorded",
            False,
            "_pipeline.set_best_dtype",
        ),
        (
            "store",
            "QC flags",
            "basestation flag text becomes int8; an empty flag becomes 6",
            _count(qc),
            "yes",
            "flag_values and flag_meanings; the empty-to-6 rule is not recorded",
            False,
            "tools.convert_qc_flags",
        ),
        (
            "write",
            "global attributes",
            "OG1 and ACDD attributes from mission.yaml, the first dive file and the "
            "data; the basestation history is not carried",
            f"{len([k for k in ds.attrs if not str(k).startswith('conversion_')])} "
            "attributes",
            "later dives' values are not in the file",
            "conversion_attribute_sources; every file's values in the conversion "
            "record",
            True,
            "_convert.update_dataset_attributes",
        ),
        (
            "write",
            "write the file",
            "zlib-compressed netCDF4; times as seconds since 1970-01-01T00:00:00Z",
            "",
            "yes",
            "the file's encoding",
            True,
            "writers.save_dataset",
        ),
    ]
    return [
        {
            "number": i,
            "stage": stage,
            "step": step,
            "rule": rule,
            "variables": variables,
            "lossless": lossless,
            "recorded": recorded,
            "recorded_in_file": ok,
            "code": code,
        }
        for i, (
            stage,
            step,
            rule,
            variables,
            lossless,
            recorded,
            ok,
            code,
        ) in enumerate(raw, start=1)
    ]


def stage_states(steps: Sequence[Step]) -> list[dict]:
    """Return one pill per stage: ``ok`` when every step of it is recorded, ``gap`` if not.

    Parameters
    ----------
    steps : sequence of Step
        From :func:`processing_steps`.

    Returns
    -------
    list of dict
        ``{"key", "label", "state", "first"}`` per stage in :data:`STAGES`; ``first`` is
        the number of the stage's first step, the pill's link target.

    """
    out = []
    for key, label in STAGES:
        mine = [s for s in steps if s["stage"] == key]
        out.append(
            {
                "key": key,
                "label": label,
                "state": "ok" if all(s["recorded_in_file"] for s in mine) else "gap",
                "first": mine[0]["number"] if mine else 0,
            }
        )
    return out


def losses(record: Mapping | None, rows: Sequence[VariableRow]) -> list[Loss]:
    """Return every kind of loss, with how many variables it touches.

    A loss is dropped structure or a label not kept (the 2026-11-09 definition): changed
    values that are recorded, and additions, are steps instead.

    Parameters
    ----------
    record : collections.abc.Mapping or None
        The conversion record beside the file, or None.
    rows : sequence of VariableRow
        The variable index.

    Returns
    -------
    list of Loss
        One entry per kind, in a fixed order; ``count`` is None where the conversion does
        not record it.

    """
    input_ok = bool(record and record.get("input_variables"))
    not_written = [
        r["basestation"] for r in rows if r["fate"] in ("removed", "dropped", "skipped")
    ]
    varying = sorted(
        name
        for name, entry in ((record or {}).get("basestation_globals") or {}).items()
        if len({json.dumps(v) for v in entry.get("values", [])}) > 1
    )
    return [
        {
            "loss": "Variables not written",
            "kind": "structure",
            "count": len(not_written),
            "examples": not_written,
            "recorded": "conversion_dimensions, conversion_removed_variables",
        },
        {
            "loss": "Dives left out (no ctd_time or position)",
            "kind": "structure",
            "count": None,
            "examples": [],
            "recorded": "not recorded",
        },
        {
            "loss": "Exact-duplicate records dropped",
            "kind": "structure",
            "count": None,
            "examples": [],
            "recorded": "not recorded",
        },
        {
            "loss": "Per-dive numbers stored as JSON text",
            "kind": "structure",
            "count": len(_marked(rows, "numbers → JSON text")) if input_ok else None,
            "examples": _marked(rows, "numbers → JSON text"),
            "recorded": "storage_type on each",
        },
        {
            "loss": "Unit spelling replaced (factor 1)",
            "kind": "label",
            "count": len(_marked(rows, "unit spelling not kept")) if input_ok else None,
            "examples": _marked(rows, "unit spelling not kept"),
            "recorded": "not recorded",
        },
        {
            "loss": "The per-variable sensor attribute",
            "kind": "label",
            "count": None,
            "examples": [],
            "recorded": "not recorded",
        },
        {
            "loss": "Global attributes that differ between dives (first file kept)",
            "kind": "label",
            "count": len(varying) if record else None,
            "examples": varying,
            "recorded": "every file's values in the conversion record",
        },
        {
            "loss": "Basestation history",
            "kind": "label",
            "count": 1,
            "examples": ["history"],
            "recorded": "not recorded",
        },
    ]


def flight_rows(rows: Sequence[VariableRow]) -> list[dict]:
    """Return the flight-model panel: each flight variable, where it went, and its form.

    Parameters
    ----------
    rows : sequence of VariableRow
        The variable index.

    Returns
    -------
    list of dict
        One per :data:`seagliderOG1.vocabularies.FLIGHT_MODEL_VARIABLES` entry, in that
        order: ``role``, the index ``row`` (None when absent from the files),
        ``form`` (on N_MEASUREMENTS, constant, JSON per dive), ``reads_as`` (the
        gliderflightOG1 name, or "") and ``ready`` (``yes``, ``no: …`` or ``—``).

    """
    by_name = {r["basestation"]: r for r in rows if r["basestation"]}
    out = []
    for name, (role, reads_as) in vocabularies.FLIGHT_MODEL_VARIABLES.items():
        row = by_name.get(name)
        if row is None:
            form = "not in these files"
            ready = f"no: {form}" if reads_as else "—"
        elif not row["name"]:
            # Consumed into a derived variable, or not written: absent under this name.
            form = f"{row['fate']}, not in the file under this name"
            ready = f"no: {row['fate']}" if reads_as else "—"
        elif row["storage"] == "per_dive_scalar":
            form, ready = "JSON text, per dive", "no: JSON text" if reads_as else "—"
        elif row["scalar"]:
            form, ready = "one value", "yes" if reads_as else "—"
        else:
            form, ready = "on N_MEASUREMENTS", "yes" if reads_as else "—"
        out.append(
            {
                "basestation": name,
                "role": role,
                "row": row,
                "form": form,
                "reads_as": reads_as or "",
                "ready": ready,
            }
        )
    return out


def traced_variable(
    rows: Sequence[VariableRow], steps: Sequence[Step]
) -> tuple[VariableRow, list[dict]] | None:
    """Return one renamed, unit-converted variable and the steps that touched it.

    Prefers ``speed`` (GLIDE_SPEED); otherwise the first renamed variable with a unit
    factor; None when the file has none.

    Parameters
    ----------
    rows : sequence of VariableRow
        The variable index.
    steps : sequence of Step
        The processing steps.

    Returns
    -------
    tuple of (VariableRow, list of dict) or None
        The variable and ``{"number", "step", "before", "after"}`` per step it went
        through.

    """
    candidates = [
        r
        for r in rows
        if r["fate"] == "renamed" and r["factor"] not in (None, 1) and r["units_in"]
    ]
    if not candidates:
        return None
    row = next((r for r in candidates if r["basestation"] == "speed"), candidates[0])
    number = {s["step"]: s["number"] for s in steps}
    trace = [
        {
            "number": number["rename to OG1"],
            "step": "rename to OG1",
            "before": row["basestation"],
            "after": row["name"],
        },
        {
            "number": number["convert units"],
            "step": "convert units",
            "before": row["units_in"],
            "after": f"{row['units_out']}, values ×{row['factor']:g}; "
            f"original_units = {row['units_in']}",
        },
        {
            "number": number["split by dimension"],
            "step": "split by dimension",
            "before": row["dimension"],
            "after": f"original_dimension = {row['dimension']}",
        },
        {
            "number": number["merge onto one time axis"],
            "step": "merge onto one time axis",
            "before": f"{row['values_in']:,} values on {row['dimension']}"
            if row["values_in"] is not None
            else row["dimension"],
            "after": "on N_MEASUREMENTS; empty at data points from other dimensions",
        },
    ]
    if row["dtype_in"] and row["dtype_out"] and row["dtype_in"] != row["dtype_out"]:
        trace.append(
            {
                "number": number["storage types"],
                "step": "storage types",
                "before": row["dtype_in"],
                "after": row["dtype_out"],
            }
        )
    trace.append(
        {
            "number": number["write the file"],
            "step": "write the file",
            "before": "",
            "after": "vocabulary, coordinates = TIME LONGITUDE LATITUDE DEPTH"
            if row["vocabulary"]
            else "coordinates = TIME LONGITUDE LATITUDE DEPTH",
        }
    )
    return row, trace


def render_processing(path: str | Path, *, title: str | None = None) -> str:
    """Return the Processing page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`, with its conversion
        record beside it.
    title : str, optional
        The page title; defaults to the file name.

    Returns
    -------
    str
        The rendered HTML page.

    """
    # Lazy: the conversion module imports this one at load time.
    from seagliderOG1.reports.conversion import _masthead_meta, _unit_corrections_rows

    record = _record.conversion_sidecar(path)
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        ledger = _record.conversion_ledger(ds)
        rows = _index.variable_rows(ds, ledger, record)
        steps = processing_steps(ds, ledger, record, rows)
        masthead_meta = _masthead_meta(ds, ledger)
        unit_rows = _unit_corrections_rows(ds)
        draft = ds.attrs.get("draft") == vocabularies.DRAFT_NOTE
        has_phase = "PHASE" in ds.variables and not draft
    return get_template("processing.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        masthead_meta=masthead_meta,
        page_nav=_pages.page_nav(path, "processing", has_phase=has_phase, draft=draft),
        steps=steps,
        stages=stage_states(steps),
        stage_labels=dict(STAGES),
        unit_corrections_rows=unit_rows,
    )


def write_processing_page(
    nc_path: str | Path, conversion_page: str | Path, *, title: str | None = None
) -> Path:
    """Write the Processing page beside the conversion page and return it.

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
    target = Path(conversion_page).with_name(
        writers.page_path(nc_path, "processing").name
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_processing(nc_path, title=title), encoding="utf-8")
    return target
