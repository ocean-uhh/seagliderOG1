"""Convert Seaglider basestation files to OG1 format.

This module provides the core functionality for converting Seaglider basestation
NetCDF files into OG1 (Ocean Gliders 1) format. It handles data processing,
variable renaming, attribute assignments, and dataset standardization.
"""

import errno
import json
import logging
import os
import pathlib
import uuid
import warnings
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from tqdm import tqdm

from seagliderOG1 import (
    __version__,
    _pipeline,
    contributors,
    readers,
    tools,
    vocabularies,
    writers,
)
from seagliderOG1.exceptions import MetadataError

__all__ = [
    "process_mission",
    "to_og1",
    "name_mapping",
    "keep_variables",
    "conversion_ledger",
    "conversion_sidecar",
    "presence_by_dive",
    "presence_patterns",
    "presence_summary",
    "enrich",
    "MetadataError",
]

_log = logging.getLogger(__name__)

# Global attributes the converter derives from the data; the mission config may
# not set these through global_attributes (a collision is an error). ``id`` is not
# here: it is derived by default but may be overridden via the identity_and_discovery: section.
# Transient per-variable attribute a derived-variable creation site stamps with the JSON
# list of basestation variables its data came from; read and removed when the
# conversion_derived_variables map is built, so it never reaches the file. Defined in
# _pipeline (which also stamps the TIME axis) and aliased here for the local creation sites.
_DERIVED_SOURCES_ATTR = _pipeline.DERIVED_SOURCES_ATTR

# The globals the converter computes; the mission config may not set them. One list in
# vocabularies, read here and by validate.
_DERIVED_GLOBALS = vocabularies.DERIVED_GLOBALS

# OG1 deployment-identity globals the mission config sets through the structured
# global-attribute sections (vocabularies.DEPLOYMENT_GLOBALS is their flat union, merged from
# the three mission.yaml sections at the CLI boundary). A global_attributes key
# duplicating one of these is refused: the escape hatch is for everything else. ``id``
# (derived) and ``comment`` (kept from the basestation files when they carry one) can
# already be set, so a deployment value for them overrides with a warning naming both;
# the rest are config-only.
_DEPLOYMENT_GLOBALS = vocabularies.DEPLOYMENT_GLOBALS

# String platform fields, resolved in order config -> file -> "UNK", derived from
# the one platform table in vocabularies (serial raises when absent, numeric fields
# are omitted; only the string ones take the "UNK" fallback).
_PLATFORM_STRING_FIELDS = tuple(
    field
    for field, spec in vocabularies.PLATFORM_FIELDS.items()
    if spec.kind == "string"
)

# Config-only platform variables written only when the user supplies them (null is
# omitted, never "UNK"). Each entry is (long_name, vocabulary-attribute-name or None,
# default vocabulary URL or None), transcribed from the OG1 manual's platform-variable
# table (OG1.0, v1.0.0). PLATFORM_MAKER's own vocabulary attribute is handled with
# platform_model_vocabulary, not here.
_VOCAB_BASE = (
    "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/"
    "vocabularyCollection"
)
OPTIONAL_PLATFORM_VARS: dict[str, tuple[str, str | None, str | None]] = {
    "PLATFORM_NAME": ("Local or nickname of the glider", None, None),
    "TELECOM_TYPE": (
        "types of telecommunication systems used by the glider, multiple telecom "
        "type are separated by a comma",
        "telecom_type_vocabulary",
        f"{_VOCAB_BASE}/telecom_type.md",
    ),
    "TRACKING_SYSTEM": (
        "type of tracking systems used by the glider, multiple tracking system are "
        "separated by a comma",
        "tracking_system_vocabulary",
        f"{_VOCAB_BASE}/tracking_system.md",
    ),
    "BATTERY_TYPE": (
        "type of the battery",
        "battery_type_vocabulary",
        f"{_VOCAB_BASE}/battery_type.md",
    ),
    "BATTERY_PACK": ("battery packaging", None, None),
}


def _is_empty(value: object) -> bool:
    """Return True for a missing or placeholder value.

    None, or a string that is empty or one of the placeholders the old
    ``attr_mandatory`` fill wrote (``vocabularies.PLACEHOLDER_VALUES``: ``""``,
    ``"None"``, ``"null"``, ``"null@null.com"``). One definition for platform fields,
    deployment globals and the escape-hatch globals, so none of them can leak a
    placeholder that another path would have dropped.

    Parameters
    ----------
    value : object
        The value to test.

    Returns
    -------
    bool
        True when the value counts as unset.

    """
    return value is None or (
        isinstance(value, str) and value.strip() in vocabularies.PLACEHOLDER_VALUES
    )


def _resolve_platform(
    first_ds: xr.Dataset, platform: dict[str, object] | None
) -> dict[str, object]:
    """Resolve OG1 platform fields from the config and the first basestation file.

    Config values override file-derived ones. ``PLATFORM_SERIAL_NUMBER`` is the
    mission identity (it names the output file and OG1 id): if neither the config
    nor the file supplies it, raise. String fields fall back to ``"UNK"`` with a
    warning; the numeric ``PLATFORM_DEPTH_RATING`` is omitted when absent rather
    than written as a string.

    Parameters
    ----------
    first_ds : xarray.Dataset
        The first basestation dataset, read for ``platform_id`` and
        ``wmo_identifier``.
    platform : dict of str to object or None
        The mission config's ``platform`` block; values override the file.

    Returns
    -------
    dict of str to object
        Resolved platform fields to write. ``PLATFORM_DEPTH_RATING`` and
        ``platform_model_vocabulary`` are present only when supplied.

    Raises
    ------
    ValueError
        If ``PLATFORM_SERIAL_NUMBER`` cannot be determined.

    """
    platform = platform or {}
    file_values = vocabularies.platform_from_file(first_ds.attrs)

    def config_or(field: str) -> object | None:
        value = platform.get(field)
        if _is_empty(value):
            value = file_values.get(field)
        return None if _is_empty(value) else value

    serial = config_or("PLATFORM_SERIAL_NUMBER")
    if serial is None:
        msg = (
            "PLATFORM_SERIAL_NUMBER could not be determined: the basestation file "
            "has no platform_id and the mission config does not set "
            "platform.PLATFORM_SERIAL_NUMBER. It names the output file and OG1 id, "
            "so set it in the config (a serial number or a local nickname per OG1)."
        )
        raise ValueError(msg)

    resolved: dict[str, object] = {"PLATFORM_SERIAL_NUMBER": serial}

    for field in _PLATFORM_STRING_FIELDS:
        value = config_or(field)
        if value is None:
            from_file = vocabularies.PLATFORM_FIELDS[field].source is not None
            warnings.warn(
                f"{field} not set in the mission config (platform.{field})"
                + (" or the basestation file" if from_file else "")
                + "; writing 'UNK'.",
                stacklevel=3,
            )
            value = "UNK"
        resolved[field] = value

    depth = platform.get("PLATFORM_DEPTH_RATING")
    if not _is_empty(depth):
        resolved["PLATFORM_DEPTH_RATING"] = depth
    else:
        warnings.warn(
            "PLATFORM_DEPTH_RATING not set in the mission config "
            "(platform.PLATFORM_DEPTH_RATING); it is numeric, so the variable is "
            "omitted rather than written as 'UNK'.",
            stacklevel=3,
        )

    for field in ("platform_model_vocabulary", "platform_maker_vocabulary"):
        vocab = platform.get(field)
        if not _is_empty(vocab):
            resolved[field] = vocab

    # Optional platform variables: written only when the user supplies them.
    for field in OPTIONAL_PLATFORM_VARS:
        value = platform.get(field)
        if not _is_empty(value):
            resolved[field] = value

    return resolved


# OG1-mandatory variables that keep_variables must never drop (plus the PLATFORM_*,
# SENSOR_* and DEPLOYMENT_* families, matched by prefix below).
_MANDATORY_OG1_VARS = frozenset(
    {
        "TIME",
        "LATITUDE",
        "LONGITUDE",
        "DEPTH",
        "TRAJECTORY",
        "WMO_IDENTIFIER",
        "PROFILE_NUMBER",
        "PHASE",
    }
)
_MANDATORY_OG1_PREFIXES = ("PLATFORM_", "SENSOR_", "DEPLOYMENT_")


def keep_variables(ds: xr.Dataset, names: list[str]) -> xr.Dataset:
    """Subset the dataset to a science-variable allow-list, keeping OG1 essentials.

    The requested ``names`` are retained, plus every OG1-mandatory variable
    and the ``_QC`` companion of every kept variable. Dropped science variables are
    warned. Coordinates are retained by xarray.

    Parameters
    ----------
    ds : xarray.Dataset
        The converted OG1 dataset.
    names : list of str
        Science variables the user asked to keep.

    Returns
    -------
    xarray.Dataset
        The subset dataset; every OG1-mandatory variable present in ``ds`` survives.

    """
    requested = set(names)
    kept = set()
    for name in ds.data_vars:
        mandatory = name in _MANDATORY_OG1_VARS or name.startswith(
            _MANDATORY_OG1_PREFIXES
        )
        qc_parent = name[:-3] if name.endswith("_QC") else None
        if (
            name in requested
            or mandatory
            or (qc_parent is not None and qc_parent in requested)
        ):
            kept.add(name)
    dropped = sorted(name for name in ds.data_vars if name not in kept)
    result = ds[sorted(kept)]
    if dropped:
        warnings.warn(
            f"keep_variables dropped science variables: {dropped}", stacklevel=2
        )
        # Record what went, so the file says what the warning said. A second call
        # adds to the list rather than replacing it.
        previous = json.loads(result.attrs.get("conversion_dropped_variables", "[]"))
        result.attrs["conversion_dropped_variables"] = json.dumps(
            sorted(set(previous) | set(dropped))
        )
        # Keep the source ledger complete: the dropped-variables global is one the
        # converter wrote, so categorise it as derived for a subset file too.
        writers.record_attribute_sources(
            result.attrs, ["conversion_dropped_variables"], "derived"
        )
    return result


# process_mission takes a keep_variables= argument, which shadows the function inside it.
_keep_variables = keep_variables


def _decode_per_dive(ds: xr.Dataset, name: str) -> dict:
    """Return the decoded per-dive JSON payload for variable ``name``.

    Parameters
    ----------
    ds : xarray.Dataset
        The OG1 dataset.
    name : str
        A variable whose ``storage_type`` is ``per_dive_scalar``.

    Returns
    -------
    dict
        The decoded ``{"dives": [...], "values": [...]}`` payload.

    Raises
    ------
    MetadataError
        If the stored value is not the per-dive JSON this package writes.

    """
    note = (
        f"{name}: storage_type is 'per_dive_scalar' but the value is not the per-dive "
        "JSON this package writes"
    )
    try:
        payload = json.loads(str(ds[name].values))
    except (json.JSONDecodeError, TypeError) as exc:
        raise MetadataError(f"{note} ({exc}).") from exc
    # Require the object shape the writer produces: a dict with equal-length dives and
    # values lists, so a non-object or ragged payload fails loudly here rather than as a
    # later AttributeError or zip mismatch.
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("dives"), list)
        or not isinstance(payload.get("values"), list)
    ):
        raise MetadataError(f"{note} (expected an object with 'dives' and 'values').")
    if len(payload["dives"]) != len(payload["values"]):
        raise MetadataError(
            f"{note} ('dives' and 'values' have different lengths: "
            f"{len(payload['dives'])} vs {len(payload['values'])})."
        )
    return payload


def conversion_ledger(ds: xr.Dataset) -> dict:
    """Return what the conversion recorded in a file, read from the file alone.

    Parses the conversion-ledger globals and the per-scalar storage once, so a caller
    (the ``inspect`` text view, the HTML page) does not re-decode the JSON or re-walk
    the variables. Everything returned is reconstructable from the file; nothing is
    read from conversion-time state.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset written by :func:`to_og1`.

    Returns
    -------
    dict
        Keys ``dimensions`` (dimension to ``{"fate", "variables"}``), ``derived``
        (derived-variable name to its list of source basestation names), ``dropped``
        (list of names), ``removed`` (list of names), ``input_variable_count`` (int),
        ``attribute_sources`` (category to names), ``history`` (str) and
        ``scalar_parameters`` (name to ``{"storage", "original_name", "units"}``, plus
        ``"dives"`` and ``"values"`` for a per-dive scalar).

    Raises
    ------
    MetadataError
        If ``ds`` predates the ledger (no ``conversion_dimensions``), or a per-dive
        scalar's value is not the per-dive JSON this package writes.

    """
    if "conversion_dimensions" not in ds.attrs:
        msg = (
            "no conversion ledger: the file has no 'conversion_dimensions' global, so "
            "it predates the ledger (not written by this version of to_og1)."
        )
        raise MetadataError(msg)

    scalar_parameters: dict[str, dict] = {}
    for name in ds.variables:
        storage = ds[name].attrs.get("storage_type")
        if storage not in ("constant_scalar", "per_dive_scalar"):
            continue
        entry = {
            "storage": storage,
            "original_name": ds[name].attrs.get("original_name"),
            "units": ds[name].attrs.get("units", ""),
        }
        if storage == "per_dive_scalar":
            payload = _decode_per_dive(ds, name)
            entry["dives"] = payload.get("dives", [])
            entry["values"] = payload.get("values", [])
        scalar_parameters[str(name)] = entry

    return {
        "dimensions": json.loads(ds.attrs["conversion_dimensions"]),
        "derived": json.loads(ds.attrs.get("conversion_derived_variables", "{}")),
        "dropped": json.loads(ds.attrs.get("conversion_dropped_variables", "[]")),
        "removed": json.loads(ds.attrs.get("conversion_removed_variables", "[]")),
        "input_variable_count": int(ds.attrs.get("conversion_input_variable_count", 0)),
        "attribute_sources": json.loads(ds.attrs["conversion_attribute_sources"]),
        "history": str(ds.attrs.get("history", "")),
        "scalar_parameters": scalar_parameters,
    }


def _input_record(ds: xr.Dataset) -> dict[str, object]:
    """Return ``{"path", "bytes", "dive", "dimensions", "n_globals"}`` for one input dataset.

    The dimension lengths and global-attribute count let the conversion page show what each
    file held before conversion (the before → after table) and state each dimension's share of
    the shared axis; both are read from the already-open dataset, so no data is read.

    Parameters
    ----------
    ds : xarray.Dataset
        A basestation dataset as opened by :func:`seagliderOG1.readers.read_mission`.

    Returns
    -------
    dict of str to object
        The file name (not the machine path), its size in bytes (None when the dataset was
        not read from a local file), the dive number, the dimension lengths as a
        ``{name: length}`` map, and the number of global attributes.

    """
    source = ds.encoding.get("source")
    local = pathlib.Path(source) if source else None
    return {
        "path": local.name if local else None,
        "bytes": local.stat().st_size if local and local.is_file() else None,
        "dive": int(ds.attrs["dive_number"]),
        "dimensions": {str(name): int(length) for name, length in ds.sizes.items()},
        "n_globals": len(ds.attrs),
    }


def _dive_runs(flags: Sequence[bool], dives: Sequence[int]) -> list[list[int]]:
    """Return the runs of consecutive input files where ``flags`` is true, as dive ranges.

    Consecutive means adjacent in the input order, not adjacent dive numbers, so a gap in
    the dive numbering (a missing file) does not split a run.

    Parameters
    ----------
    flags : sequence of bool
        One flag per input file, in dive order.
    dives : sequence of int
        The dive number of each input file.

    Returns
    -------
    list of [int, int]
        ``[first_dive, last_dive]`` per run, in order; empty when no flag is true.

    """
    runs: list[list[int]] = []
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        if not flag and start is not None:
            runs.append([dives[start], dives[i - 1]])
            start = None
    if start is not None:
        runs.append([dives[start], dives[len(flags) - 1]])
    return runs


def _has_values(var: xr.Variable) -> bool:
    """Return True when a basestation variable holds at least one non-missing value.

    Floating data is tested for any finite value (the reader has already turned fill
    values into NaN), times for any value that is not NaT, and text for any string that is
    not blank; other data counts as values when the variable is not empty.

    Parameters
    ----------
    var : xarray.Variable
        One variable of one basestation file.

    Returns
    -------
    bool
        Whether the variable has any value in this file.

    """
    if var.size == 0:
        return False
    values = np.asarray(var.values)
    kind = values.dtype.kind
    if kind == "f":
        return bool(np.isfinite(values).any())
    if kind in "mM":
        return bool((~np.isnat(values)).any())
    if kind in "SU":
        return bool((np.char.str_len(np.char.strip(values)) > 0).any())
    if kind == "O":
        # netCDF4 variable-length text decodes to an object array: a dive of only
        # ""/whitespace/None has no value; genuinely non-text object data (rare) counts.
        for item in values.ravel().tolist():
            if item is None:
                continue
            if isinstance(item, bytes):
                item = item.decode("utf-8", "replace")
            if not isinstance(item, str) or item.strip():
                return True
        return False
    return True


def presence_by_dive(list_of_datasets: Sequence[xr.Dataset]) -> dict:
    """Return the dives each basestation variable is present in, and has values in.

    A sensor switched on part-way through a mission, or one that is present but off,
    makes the input files disagree; the converter works from the union of their
    variables, so this records which dives each one came from. Read from the inputs, not
    the output — the OG1 file cannot say which file carried what.

    Parameters
    ----------
    list_of_datasets : sequence of xarray.Dataset
        Basestation datasets, one per dive, each with a ``dive_number`` attribute.

    Returns
    -------
    dict
        ``dives`` (the input dive numbers, in order) and ``variables`` (basestation name
        to ``{"present": runs, "valid": runs}``, each run ``[first_dive, last_dive]``
        over consecutive input files; ``valid`` means present with at least one
        non-missing value).

    """
    ordered = sorted(list_of_datasets, key=lambda ds: int(ds.attrs["dive_number"]))
    dives = [int(ds.attrs["dive_number"]) for ds in ordered]
    names = sorted({str(name) for ds in ordered for name in ds.variables})
    variables = {}
    for name in names:
        present = [name in ds.variables for ds in ordered]
        valid = [
            is_present and _has_values(ds.variables[name])
            for is_present, ds in zip(present, ordered, strict=True)
        ]
        variables[name] = {
            "present": _dive_runs(present, dives),
            "valid": _dive_runs(valid, dives),
        }
    return {"dives": dives, "variables": variables}


def _run_label(runs: list[list[int]], dives: Sequence[int]) -> str:
    """Return a dive-range label: ``every dive``, ``from dive 12``, ``dives 3–7``, ...

    Parameters
    ----------
    runs : list of [int, int]
        Dive ranges from :func:`presence_by_dive`.
    dives : sequence of int
        The input dive numbers, in order.

    Returns
    -------
    str
        One of ``every dive``, ``never``, ``from dive k``, ``until dive k``,
        ``dive k only``, ``dives a–b`` or ``sporadic``.

    """
    if not runs:
        return "never"
    if len(runs) > 1:
        return "sporadic"
    first, last = runs[0]
    if first == dives[0] and last == dives[-1]:
        return "every dive"
    if first == last:
        return f"dive {first} only"
    if last == dives[-1]:
        return f"from dive {first}"
    if first == dives[0]:
        return f"until dive {last}"
    return f"dives {first}–{last}"


def _run_mask(runs: list[list[int]], dives: Sequence[int]) -> list[bool]:
    """Return one flag per input file: whether it falls inside ``runs``.

    The inverse of :func:`_dive_runs`.

    Parameters
    ----------
    runs : list of [int, int]
        Dive ranges.
    dives : sequence of int
        The input dive numbers, in order.

    Returns
    -------
    list of bool
        One flag per input dive.

    """
    return [any(a <= d <= b for a, b in runs) for d in dives]


def presence_patterns(presence: dict) -> list[dict]:
    """Group variables by the dives they are valid in, then present in — the page's rows.

    Hundreds of variables over hundreds of dives is a table of patterns, not of
    variables: on a normal mission a handful of patterns cover everything ("every dive",
    "from dive 12", "until dive 40", "sporadic").

    Parameters
    ----------
    presence : dict
        As returned by :func:`presence_by_dive`.

    Returns
    -------
    list of dict
        One per distinct ``(valid, present)`` pair, the ``every dive`` row first, then
        by variable count: ``label`` (from the valid runs), ``valid`` and ``present``
        (runs), ``valid_mask`` / ``present_mask`` (one flag per input dive),
        ``n_valid`` / ``n_present`` (dives covered), ``uniform`` (valid on every dive),
        and ``variables`` (sorted names).

    """
    dives = presence["dives"]
    groups: dict[tuple, list[str]] = {}
    for name, entry in presence["variables"].items():
        key = (
            tuple(map(tuple, entry["valid"])),
            tuple(map(tuple, entry["present"])),
        )
        groups.setdefault(key, []).append(name)
    rows = []
    for (valid, present), names in groups.items():
        valid_runs = [list(run) for run in valid]
        present_runs = [list(run) for run in present]
        label = _run_label(valid_runs, dives)
        valid_mask = _run_mask(valid_runs, dives)
        present_mask = _run_mask(present_runs, dives)
        rows.append(
            {
                "label": label,
                "valid": valid_runs,
                "present": present_runs,
                "valid_mask": valid_mask,
                "present_mask": present_mask,
                "n_valid": sum(valid_mask),
                "n_present": sum(present_mask),
                "uniform": label == "every dive",
                "variables": sorted(names),
            }
        )
    rows.sort(
        key=lambda row: (not row["uniform"], -len(row["variables"]), row["label"])
    )
    return rows


def presence_summary(presence: dict) -> str | None:
    """Return a one-line summary when the input dives disagree, else None.

    Parameters
    ----------
    presence : dict
        As returned by :func:`presence_by_dive`.

    Returns
    -------
    str or None
        e.g. ``"343 variables over 5 dives; 338 on every dive, 5 on some (3 patterns)"``,
        or None when every variable has values on every dive.

    """
    patterns = presence_patterns(presence)
    if all(row["uniform"] for row in patterns):
        return None
    total = sum(len(row["variables"]) for row in patterns)
    every = sum(len(row["variables"]) for row in patterns if row["uniform"])
    n_dives = len(presence["dives"])
    return (
        f"{total} variables over {n_dives} dives; {every} on every dive, "
        f"{total - every} on some ({len(patterns)} patterns)"
    )


def conversion_sidecar(path: str | os.PathLike, *, verify: bool = False) -> dict | None:
    """Return the conversion sidecar written beside an OG1 file, or None.

    The sidecar (``<id>_conversion.json``, see :func:`seagliderOG1.writers.write`)
    holds what the file cannot say about its own conversion. It is bound to the file by
    ``id`` and ``tracking_id`` (``id`` and ``date_created`` for a sidecar written
    before ``tracking_id``); a sidecar from another conversion is not returned. With
    ``verify``, the file's SHA-256 is compared with the one recorded and a mismatch
    warns that the file changed after the sidecar was written (the sidecar is still
    returned).

    Parameters
    ----------
    path : str or os.PathLike
        The OG1 netCDF file.
    verify : bool, optional
        Hash the file and compare (reads the whole file). Default is False.

    Returns
    -------
    dict or None
        The sidecar contents, or None when it is missing, unreadable, of another
        schema, or belongs to another conversion (each but the first warned).

    """
    path = pathlib.Path(path)
    sidecar_path = writers.conversion_path(path, ".json")
    if not sidecar_path.is_file():
        return None
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.warn(
            f"{sidecar_path.name} could not be read ({exc}); ignoring it.", stacklevel=2
        )
        return None
    if not isinstance(sidecar, dict) or sidecar.get("schema") != writers.SIDECAR_SCHEMA:
        warnings.warn(
            f"{sidecar_path.name} is not a schema-{writers.SIDECAR_SCHEMA} conversion "
            "sidecar; ignoring it.",
            stacklevel=2,
        )
        return None
    keys = ("id", "tracking_id") if "tracking_id" in sidecar else ("id", "date_created")
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        binding = {key: ds.attrs.get(key) for key in keys}
    if {key: sidecar.get(key) for key in binding} != binding:
        warnings.warn(
            f"{sidecar_path.name} belongs to another conversion "
            f"({'/'.join(keys)} differ from {path.name}); ignoring it.",
            stacklevel=2,
        )
        return None
    if (
        verify
        and "sha256" in sidecar
        and sidecar["sha256"] != writers.file_sha256(path)
    ):
        warnings.warn(
            f"{path.name} has changed since {sidecar_path.name} was written "
            "(SHA-256 differs).",
            stacklevel=2,
        )
    return sidecar


# The one sentence a draft carries in its ``draft`` global (see process_mission).
DRAFT_NOTE = "converted without a mission config; not an OG1 file"


def _institution_from_file(attrs: Mapping) -> dict | None:
    """Return a basestation file's ``institution`` global and its EDMO registry match.

    Parameters
    ----------
    attrs : collections.abc.Mapping
        The first basestation file's global attributes.

    Returns
    -------
    dict or None
        ``{"text", "name", "id"}``: the global as written, the registry
        ``standard_name`` and EDMO URL (both None without a match); None when the file
        has no ``institution`` global.

    """
    if "institution" not in attrs:
        return None
    text = str(attrs["institution"])
    # Silenced: an unmatched name is already warned by get_contributors when it is used.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        (resolved,) = contributors.enrich_institutions([{"name": text, "role": ""}])
    matched = bool(resolved["id"])
    return {
        "text": text,
        "name": resolved["name"] if matched else None,
        "id": resolved["id"] if matched else None,
    }


def _basestation_globals(list_of_datasets: Sequence[xr.Dataset]) -> dict:
    """Return each basestation global attribute's distinct values across the inputs.

    What the files say about themselves, before any OG1 enrichment — the draft page's
    global-attributes section reads it from the sidecar.

    Parameters
    ----------
    list_of_datasets : sequence of xarray.Dataset
        The basestation datasets that reached the output.

    Returns
    -------
    dict
        Attribute name to ``{"values": [distinct values as text, first-seen order],
        "n_files": files that carry it}``, names sorted.

    """
    found: dict[str, dict] = {}
    for ds in list_of_datasets:
        for name, value in ds.attrs.items():
            entry = found.setdefault(str(name), {"values": [], "n_files": 0})
            entry["n_files"] += 1
            text = str(value)
            if text not in entry["values"]:
                entry["values"].append(text)
    return {name: found[name] for name in sorted(found)}


def _check_metadata_keys(
    deployment: Mapping[str, object], global_attributes: Mapping[str, object]
) -> None:
    """Raise on a mission-config global the converter owns or that has another home.

    Parameters
    ----------
    deployment : collections.abc.Mapping
        The deployment mapping (the three ``mission.yaml`` global-attribute sections merged).
    global_attributes : collections.abc.Mapping
        The ``global_attributes:`` block.

    Raises
    ------
    ValueError
        If ``global_attributes`` sets a converter-derived key or a key with a structured home
        in a global-attribute section, or the deployment mapping has an unknown key.

    """
    # Only a real (non-null) value collides; a null is skipped later, so a template that
    # lists reserved keys as null still converts.
    set_globals = {k for k, v in global_attributes.items() if not _is_empty(v)}
    collisions = _DERIVED_GLOBALS.intersection(set_globals)
    if collisions:
        msg = (
            "global_attributes may not set converter-derived keys: "
            f"{sorted(collisions)}. Remove them from the mission config."
        )
        raise ValueError(msg)
    structured = set(_DEPLOYMENT_GLOBALS).intersection(set_globals)
    if structured:
        home = {
            key: slug
            for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items()
            for key in keys
        }
        moves = "; ".join(f"{key} -> {home[key]}:" for key in sorted(structured))
        msg = (
            "global_attributes may not set keys that have a structured home in a "
            f"global-attribute section: move {moves}."
        )
        raise ValueError(msg)
    unknown_deployment = set(deployment) - set(_DEPLOYMENT_GLOBALS)
    if unknown_deployment:
        msg = (
            f"deployment has unknown keys: {sorted(unknown_deployment)}. Allowed "
            f"keys are {list(_DEPLOYMENT_GLOBALS)}; set anything else under "
            "global_attributes."
        )
        raise ValueError(msg)


# Globals enrich writes itself (besides the converter-owned _DERIVED_GLOBALS): a
# config may not set them, or the file's own record of the edit would be overwritten.
_ENRICH_OWNED = frozenset(
    {"date_modified", "history", "draft", "conversion_attribute_sources"}
)


def _enrich_value(key: str, value: object) -> str | int | float:
    """Return ``value`` as a netCDF global attribute value, or raise.

    Parameters
    ----------
    key : str
        The global's name (for the error message).
    value : object
        The value from the config or the command line.

    Returns
    -------
    str or int or float
        Text and numbers unchanged; a date or datetime as ISO 8601 text (YAML reads an
        unquoted ``2024-05-01`` as a date).

    Raises
    ------
    ValueError
        If the value is a bool, a list, a mapping or any other type netCDF cannot
        store as a global attribute unchanged.

    """
    if isinstance(value, bool):
        msg = f"{key}: a true/false value cannot be a global attribute; quote it."
        raise ValueError(msg)
    if isinstance(value, str | int | float | np.integer | np.floating):
        return value
    if isinstance(value, date):
        return value.isoformat()
    msg = (
        f"{key}: a {type(value).__name__} cannot be a global attribute; give text or "
        "a number."
    )
    raise ValueError(msg)


def enrich(
    path: str | os.PathLike,
    *,
    deployment: Mapping[str, object] | None = None,
    global_attributes: Mapping[str, object] | None = None,
    doi: str | None = None,
) -> pathlib.Path:
    """Set global attributes on a written OG1 file without converting again.

    For metadata that exists only after the file is written — a DOI assigned on
    publication — or a corrected global-attribute or ``global_attributes:`` value. Only
    global attributes change (edited in place; variables are not rewritten). The file
    gets ``date_modified`` set to now, a ``history`` line naming the keys, and a new
    ``tracking_id``; ``date_created`` is kept. Every value is checked before the file
    is opened for writing, so a refused value leaves the file as it was. Replacing a
    different value already in the file warns with both values. The set keys move to
    the ``enriched`` category of ``conversion_attribute_sources``. A sidecar beside the
    file is rebound to the new ``tracking_id`` and SHA-256.

    Parameters
    ----------
    path : str or os.PathLike
        The OG1 netCDF file.
    deployment : collections.abc.Mapping, optional
        Deployment-identity globals to set (as in :func:`to_og1`); null values are skipped.
    global_attributes : collections.abc.Mapping, optional
        ``global_attributes:`` keys to set (as in :func:`to_og1`).
    doi : str, optional
        The DOI, written as the ``doi`` global (wins over ``deployment["doi"]``).

    Returns
    -------
    pathlib.Path
        The enriched file.

    Raises
    ------
    ValueError
        If nothing is given to set; a key is one the converter owns or that belongs in
        the other block (as for :func:`to_og1`); a value is not text, a number or a
        date; a key is one ``enrich`` writes itself (``date_modified``, ``history``,
        ``tracking_id``, ``draft``) or a ``conversion_*`` record; or
        ``deployment["id"]`` differs from the file's ``id`` (the file name and the
        sidecar are bound to it: convert again to change it).
    FileNotFoundError
        If ``path`` does not exist.

    """
    path = pathlib.Path(path)
    if not path.is_file():
        raise FileNotFoundError(errno.ENOENT, "no such OG1 file", str(path))
    deployment = dict(deployment or {})
    global_attributes = dict(global_attributes or {})
    _check_metadata_keys(deployment, global_attributes)
    owned = sorted(
        key
        for key, value in global_attributes.items()
        if not _is_empty(value)
        and (key in _ENRICH_OWNED or key.startswith("conversion_"))
    )
    if owned:
        msg = (
            f"enrich writes {owned} itself (or they are the conversion record); "
            "remove them from global_attributes."
        )
        raise ValueError(msg)
    if doi is not None:
        deployment["doi"] = doi
    updates = {
        key: _enrich_value(key, value)
        for block in (deployment, global_attributes)
        for key, value in block.items()
        if not _is_empty(value)
    }
    if not updates:
        msg = "nothing to enrich: no deployment, global_attributes or doi value given."
        raise ValueError(msg)

    with netCDF4.Dataset(path, "r") as nc:
        current = {key: nc.getncattr(key) for key in nc.ncattrs()}
    if "id" in updates and str(updates["id"]) != str(current.get("id")):
        msg = (
            f"deployment id {updates['id']!r} differs from the file's id "
            f"{current.get('id')!r}; the file name and sidecar are bound to the id, so "
            "convert again (process) to change it."
        )
        raise ValueError(msg)
    for key, value in updates.items():
        if key in current and str(current[key]) != str(value):
            warnings.warn(
                f"enrich replaces {key}: {current[key]!r} -> {value!r}", stacklevel=2
            )

    now = datetime.now(UTC)
    line = (
        f"{now.isoformat(timespec='seconds')} seagliderOG1 {__version__}: "
        f"enrich set {', '.join(sorted(updates))}"
    )
    history = str(current.get("history", "")).strip()
    attrs = {
        **current,
        **updates,
        "date_modified": now.strftime("%Y%m%dT%H%M%S"),
        "history": f"{history}\n{line}" if history else line,
        "tracking_id": str(uuid.uuid4()),
    }
    writers.record_attribute_sources(attrs, updates, "enriched")
    writers.record_attribute_sources(attrs, ["date_modified", "tracking_id"], "derived")
    with netCDF4.Dataset(path, "a") as nc:
        for key, value in attrs.items():
            if key not in current or current[key] is not value:
                nc.setncattr(key, value)

    sidecar_file = writers.conversion_path(path, ".json")
    if sidecar_file.is_file():
        try:
            contents = json.loads(sidecar_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.warn(
                f"{sidecar_file.name} could not be read ({exc}); not rebound.",
                stacklevel=2,
            )
        else:
            writers.write_sidecar(path, attrs, contents)
    _log.info("enriched %s: %s", path, sorted(updates))
    return path


def _apply_deployment(
    ds_og1: xr.Dataset,
    deployment: Mapping[str, object],
    sources: dict[str, str],
) -> None:
    """Write the deployment-identity globals, overriding a derived value with a warning.

    Mission config takes precedence over a converter-derived global, so a deployment
    value that differs from one already on the dataset (``id`` and ``comment`` are the
    two with a derived default) is applied, with a warning naming both values. Null
    and placeholder values are skipped. Called after the derived globals are set.

    Filling a global that is absent or empty is not an override (there is no derived
    value to replace), so it is applied silently; only replacing a present, differing
    value warns.

    Parameters
    ----------
    ds_og1 : xarray.Dataset
        The assembled OG1 dataset, modified in place.
    deployment : collections.abc.Mapping
        The mission config ``deployment`` block.
    sources : dict of str to str
        The conversion-ledger source map, updated in place: a key is ``overridden``
        when it replaced a value the conversion had already set, else ``mission``.

    """
    for key, value in deployment.items():
        if _is_empty(value):
            continue
        existing = ds_og1.attrs.get(key)
        replaced = existing is not None and str(existing) != str(value)
        if replaced:
            warnings.warn(
                f"deployment.{key} overrides the converter value {existing!r} with "
                f"{value!r}.",
                stacklevel=2,
            )
        ds_og1.attrs[key] = value
        sources[key] = "overridden" if replaced else "mission"


def _is_raw_count(name: str, attrs: Mapping[str, object]) -> bool:
    """Return True for a raw instrument count channel that carries no units.

    Parameters
    ----------
    name : str
        Basestation variable name.
    attrs : collections.abc.Mapping
        Its attributes.

    Returns
    -------
    bool
        Whether ``name`` ends in one of :data:`vocabularies.RAW_COUNT_SUFFIXES` and
        has no ``units`` attribute.

    """
    return "units" not in attrs and name.endswith(vocabularies.RAW_COUNT_SUFFIXES)


def _check_required_globals(attrs: Mapping[str, object]) -> None:
    """Fail loud on a missing mandatory global; log missing highly-desirable ones.

    Runs after the three metadata sources are merged. Every OG1-mandatory global is
    a package constant or derived from the data (none come from the user), so a gap
    is a converter regression, not a config omission, and raises ``MetadataError``.
    Highly-desirable globals the user did not supply are reported at INFO, not raised:
    seagliderOG1 lets a user specify OG1 metadata but does not enforce the format;
    the external ``cc-plugin-og`` checker is where completeness is judged.

    Parameters
    ----------
    attrs : collections.abc.Mapping
        The assembled global attributes of the converted dataset.

    Raises
    ------
    MetadataError
        If any mandatory global attribute is missing or a placeholder.

    """
    gaps = [
        name
        for name in vocabularies.REQUIRED_GLOBALS["mandatory"]
        if _is_empty(attrs.get(name))
    ]
    if gaps:
        msg = (
            f"OG1-mandatory global attributes missing after conversion: {gaps}. "
            "These are all package constants or derived from the data, so this is a "
            "converter problem rather than a mission-config omission."
        )
        raise MetadataError(msg)
    unset_desirable = [
        name
        for name in vocabularies.REQUIRED_GLOBALS["highly_desirable"]
        if _is_empty(attrs.get(name))
    ]
    if unset_desirable:
        _log.info(
            "OG1 highly-desirable global attributes are unset: %s. Set them in the "
            "mission config to improve discoverability.",
            unset_desirable,
        )


# Conversion-ledger categories, in report order. A written global belongs to exactly
# one; "mixed" holds the contributor/institution attributes, whose value blends the
# mission config and the files, so the ledger names them without guessing one source.
_LEDGER_CATEGORIES = (
    "basestation",
    "renamed",
    "derived",
    "package",
    "mission",
    "overridden",
    "mixed",
    "enriched",
)


def _attribute_source_ledger(
    attrs: Mapping[str, object], sources: Mapping[str, str]
) -> str:
    """Return the ``conversion_attribute_sources`` JSON global (names only).

    One category per written global, from the source map the conversion built: which
    globals the files supplied (``basestation``), which were renamed from a file
    attribute (``renamed``), computed by the converter (``derived``), package constants
    (``package``), from ``mission.yaml`` (``mission``), a mission value that replaced a
    converter one (``overridden``), or a blend of config and files (``mixed``). Values
    are not recorded — they are in the file already.

    Parameters
    ----------
    attrs : collections.abc.Mapping
        The final global attributes (every one is categorised).
    sources : collections.abc.Mapping
        Each attribute name mapped to its category.

    Returns
    -------
    str
        A JSON object of ``category -> sorted list of attribute names``, categories in
        report order, omitting any category with no members.

    """
    ledger: dict[str, list[str]] = {category: [] for category in _LEDGER_CATEGORIES}
    for name in attrs:
        if name == "conversion_attribute_sources":
            continue
        ledger[sources[name]].append(name)
    return json.dumps(
        {category: sorted(names) for category, names in ledger.items() if names}
    )


def _dimension_ledger(
    list_of_datasets: Sequence[xr.Dataset],
    ctd_dim: str,
    all_dims: Sequence[str],
    ds_og1: xr.Dataset,
) -> str:
    """Return the ``conversion_dimensions`` JSON global (fate and variables per dimension).

    One entry per basestation dimension, each with its fate and the basestation
    variable names that lived on it. The fate is read from the output, not from the
    pre-conversion merge plan: the CTD dimension that became ``N_MEASUREMENTS`` is
    ``backbone``; a dimension any of whose variables reaches the output (carrying
    ``original_dimension == dim``) is ``merged``; a dimension with no variable in the
    output is ``skipped`` and its names are recorded here because nothing else carries
    them. A variable defined on more than one dimension is listed under each of them,
    so the per-dimension counts are "variables on this dimension", not a partition.

    Parameters
    ----------
    list_of_datasets : collections.abc.Sequence of xarray.Dataset
        The raw basestation datasets, read for their per-dimension variable names.
    ctd_dim : str
        The CTD dimension that becomes ``N_MEASUREMENTS`` (fate ``backbone``).
    all_dims : collections.abc.Sequence of str
        Every dimension present across the inputs.
    ds_og1 : xarray.Dataset
        The assembled OG1 output, read for which dimensions survived (via each
        variable's ``original_dimension`` attribute).

    Returns
    -------
    str
        A JSON object of ``dimension -> {"fate", "variables"}``, keys sorted.

    """
    # ds.variables[name] is the bare Variable; ds[name] would build a DataArray with
    # all its coordinates for every variable of every dive.
    in_output = {
        str(var.attrs["original_dimension"])
        for var in ds_og1.variables.values()
        if "original_dimension" in var.attrs
    }
    ledger = {}
    for dim in all_dims:
        if dim == ctd_dim:
            fate = "backbone"
        elif dim in in_output:
            fate = "merged"
        else:
            fate = "skipped"
        names = sorted(
            {
                str(name)
                for ds in list_of_datasets
                for name, var in ds.variables.items()
                if dim in var.dims
            }
        )
        ledger[dim] = {"fate": fate, "variables": names}
    return json.dumps(ledger, sort_keys=True)


def to_og1(
    list_of_datasets: Sequence[xr.Dataset],
    *,
    contributors: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
    platform: dict[str, object] | None = None,
    deployment: dict[str, object] | None = None,
    global_attributes: dict[str, object] | None = None,
    sensors: Mapping[str, Mapping[str, object]] | None = None,
    mode: str = "realtime",
    provenance: dict | None = None,
) -> xr.Dataset:
    """Convert Seaglider basestation datasets to OG1 format.

    Maps and standardises each dataset, concatenates them on a shared time axis,
    sorts by time, and applies platform, deployment and contributor attributes.

    Parameters
    ----------
    list_of_datasets : sequence of xarray.Dataset
        A list of xarray datasets in basestation format. The datasets are
        concatenated and sorted by time, so the input order does not matter:
        ``start_date``, ``TRAJECTORY`` and the output ``id`` are seeded from the
        earliest measurement time and so always agree with ``time_coverage_start``.
    contributors : sequence of dict, optional
        Contributor records (``name``, ``role`` and optional ``email``, ``orcid``)
        merged with those already on the files. When None, contributors come from
        the files' own attributes; no package default is applied. Default is None.
    institutions : sequence of dict, optional
        Institution records (``name``, ``role`` and optional ``id``) merged with
        those on the files and resolved against the EDMO registry. Default is None.
    platform : dict of str to object, optional
        Platform fields from the mission config (``PLATFORM_SERIAL_NUMBER``,
        ``PLATFORM_MODEL``, ``PLATFORM_MAKER``, ``PLATFORM_DEPTH_RATING``,
        ``GLIDER_FIRMWARE_VERSION``, ``LANDSTATION_VERSION``, ``WMO_IDENTIFIER``,
        ``platform_model_vocabulary``). Config values override file-derived ones.
        Default is None.
    deployment : dict of str to object, optional
        The deployment-identity globals from the mission config ``deployment`` block
        (``id``, ``program``, ``license``, ``doi``, ``site``, ...). Written as global
        attributes; a value for ``id`` (derived) or ``comment`` (kept from the
        basestation files when they carry one) overrides it with a warning. Nulls skipped. Default is None.
    global_attributes : dict of str to object, optional
        Global attributes written verbatim into the output (nulls skipped). A key
        that collides with a converter-derived global, or with a key that has a
        structured home in ``deployment``, raises. Default is None.
    sensors : collections.abc.Mapping, optional
        Corrections to the basestation sensor records, from the mission config
        ``sensors:`` block: sensor key (a name in the ``instrument`` global) to
        ``{"serial_number": ..., "calibration_date": ...}``. A corrected serial names the
        ``SENSOR_*`` variable; the sensor's ``comment`` records the value it replaced.
        Default is None.
    mode : str, optional
        Data mode, ``"realtime"`` (default) or ``"delayed"``. Sets the ``id``
        suffix (``R`` or ``delayed``) and so the output filename, per the OG1
        manual, which defines no separate data-mode attribute. Default is "realtime":
        a file is delayed mode only when the user says so.
    provenance : dict, optional
        When given, filled in place with what the output file cannot record about its own
        conversion: ``inputs`` (one ``{"path", "bytes", "dive"}`` per input file) and
        ``presence`` (:func:`presence_by_dive`). Pass it to
        ``writers.write(..., sidecar=provenance)`` to write it beside the file. Default
        is None.

    Returns
    -------
    xarray.Dataset
        The concatenated and processed dataset in OG1 format.

    Raises
    ------
    MetadataError
        If an OG1-mandatory global attribute is absent after all metadata sources
        are merged (a converter problem: the mandatory set is derived or constant).
    ValueError
        If ``global_attributes`` sets a converter-derived or deployment-home key, if
        ``deployment`` has an unknown key, if no datasets are valid, or if ``mode`` is
        not ``"delayed"``/``"realtime"``.

    """
    if isinstance(list_of_datasets, xr.Dataset):
        msg = "to_og1 takes a sequence of datasets; pass a sequence, e.g. [ds]."
        raise TypeError(msg)
    if isinstance(contributors, Mapping):
        msg = (
            "to_og1(contributors=...) is now a list of records "
            "[{'name': ..., 'role': ..., 'email': ..., 'orcid': ...}], not a dict "
            "of OG1 attributes. See CHANGELOG."
        )
        raise TypeError(msg)

    global_attributes = global_attributes or {}
    deployment = deployment or {}
    _check_metadata_keys(deployment, global_attributes)

    if mode not in vocabularies.MODE_SUFFIX:
        msg = f"mode must be one of {sorted(vocabularies.MODE_SUFFIX)}, not {mode!r}."
        raise ValueError(msg)

    _log.info(
        "Start converting %d raw datasets to OG1 format ...", len(list_of_datasets)
    )

    processed_datasets = []

    # This would be faster if we concatenated the basestation files first, and then processed them.
    # But we need to process them first to get the dive number, assign GPS (could be after), ?

    # Find dimensions to merge across all datasets
    ctd_dim, dims_to_merge, all_dims = _pipeline._get_merge_dimensions(list_of_datasets)

    # Create a mapping from original variable names to OG1 variable names for all variables across the datasets
    og1_mapping, time_variables = _pipeline.og1_name_mapping(list_of_datasets)
    # Build the original->OG1 name lookup once; it is loop-invariant across dives.
    name_lookup = og1_mapping.set_index("original_name")["OG1_name"]

    used_inputs = []
    for ds1_base in tqdm(list_of_datasets, desc="Processing datasets", unit="dataset"):
        if provenance is not None:
            # Presence reads every variable; loading the file once here lets both it
            # and the conversion work from memory instead of reading the file twice.
            ds1_base.load()
        ds_new, attr_warnings = process_dataset(
            ds1_base, og1_mapping, time_variables, name_lookup=name_lookup
        )
        if ds_new:
            processed_datasets.append(ds_new)
            used_inputs.append(ds1_base)
        else:
            _log.warning(
                f"Dataset for dive number {ds1_base.attrs['dive_number']} is empty or invalid."
            )

    if not processed_datasets:
        raise ValueError(
            "No valid datasets were processed. Check the input datasets "
            "and the warnings from coordinate validation."
        )

    if provenance is not None:
        # Only the dives that reach the output: a rejected dive contributed nothing.
        provenance["inputs"] = [_input_record(ds) for ds in used_inputs]
        provenance["presence"] = presence_by_dive(used_inputs)
        provenance["basestation_globals"] = _basestation_globals(used_inputs)
        # What init would propose for platform:, from the file the resolver reads.
        provenance["platform_from_file"] = vocabularies.platform_from_file(
            list_of_datasets[0].attrs
        )
        provenance["institution_from_file"] = _institution_from_file(
            list_of_datasets[0].attrs
        )

    ds_og1 = xr.concat(processed_datasets, dim="N_MEASUREMENTS")
    ds_og1 = ds_og1.sortby("TIME")

    # Add sensor information to the dataset - can be done on the concatenated data
    # -----------------------------------------------------------------------------
    sensor_dict = _pipeline.gather_sensor_info(list_of_datasets, overrides=sensors)
    # delete old sensor attribute if it exists and add new one
    for var in ds_og1.data_vars:
        if "sensor" in ds_og1[var].attrs:
            del ds_og1[var].attrs["sensor"]
    ds_og1 = _pipeline.add_sensor_to_dataset(ds_og1, sensor_dict, og1_mapping)

    # Apply attributes
    ordered_attributes, attribute_sources = update_dataset_attributes(
        list_of_datasets[0], people=contributors, institutions=institutions
    )
    for key, value in ordered_attributes.items():
        # A null or wholly-empty attribute is never written (not as an empty string,
        # not as the word "null"): an absent global is absent. A multi-value string
        # with an empty slot (e.g. ", PI" for a role-less first contributor) is kept.
        # _check_required_globals reports any mandatory gap before the return.
        if not _is_empty(value):
            ds_og1.attrs[key] = value

    # start_date names TRAJECTORY and the output id, so it must be the deployment
    # time, not whichever dive happened to be first in the input sequence. ds_og1 is
    # already sorted by TIME, so TIME[0] is the earliest measurement; seeding
    # start_date from it keeps start_date, TRAJECTORY and id in agreement with
    # time_coverage_start no matter what order the datasets were passed in.
    ds_og1.attrs["start_date"] = _pipeline._clean_time_string(
        np.datetime_as_string(ds_og1["TIME"][0], unit="s")
    )

    ### Add information needed/used for hydrodynamic (flight) model (hdm)
    _log.info("Collecting scalar parameters to the dataset ...")
    extracted = _pipeline.extract_scalar_parameters(list_of_datasets)
    _log.info("Adding scalar parameters to the dataset ...")
    ds_og1, og1_mapping = _pipeline.add_scalar_parameters(
        ds_og1, extracted, og1_mapping
    )

    # Resolve platform fields from the config and the first file (no silent
    # fallbacks: missing serial raises, other strings warn + "UNK", the numeric
    # depth rating is omitted rather than written as a string).
    platform_fields = _resolve_platform(list_of_datasets[0], platform)
    platform_serial_number = platform_fields["PLATFORM_SERIAL_NUMBER"]

    # If the config renamed the serial (a local nickname replacing the basestation
    # platform_id), record the replaced value so it survives in the file, as a sensor
    # serial correction does in the sensor's comment.
    file_serial = vocabularies.platform_from_file(list_of_datasets[0].attrs).get(
        "PLATFORM_SERIAL_NUMBER"
    )
    serial_comment = (
        f"mission config PLATFORM_SERIAL_NUMBER; the basestation platform_id was "
        f"{file_serial!r}."
        if not _is_empty(file_serial) and str(file_serial) != str(platform_serial_number)
        else None
    )

    # Mandatory OG1 platform string variables and their long_names.
    platform_long_names = {
        "PLATFORM_SERIAL_NUMBER": "glider serial number",
        "PLATFORM_MODEL": "model of the glider",
        "PLATFORM_MAKER": "glider manufacturer",
        "GLIDER_FIRMWARE_VERSION": "glider firmware version",
        "LANDSTATION_VERSION": "version of the landstation",
        "WMO_IDENTIFIER": "wmo id",
    }
    for field, long_name in platform_long_names.items():
        ds_og1[field] = platform_fields[field]
        ds_og1[field].attrs["long_name"] = long_name
    if serial_comment is not None:
        ds_og1["PLATFORM_SERIAL_NUMBER"].attrs["comment"] = serial_comment

    if "platform_model_vocabulary" in platform_fields:
        ds_og1["PLATFORM_MODEL"].attrs["platform_model_vocabulary"] = platform_fields[
            "platform_model_vocabulary"
        ]
    if "platform_maker_vocabulary" in platform_fields:
        ds_og1["PLATFORM_MAKER"].attrs["platform_maker_vocabulary"] = platform_fields[
            "platform_maker_vocabulary"
        ]

    if "PLATFORM_DEPTH_RATING" in platform_fields:
        ds_og1["PLATFORM_DEPTH_RATING"] = platform_fields["PLATFORM_DEPTH_RATING"]
        ds_og1["PLATFORM_DEPTH_RATING"].attrs["long_name"] = "maximum rated depth"

    # Optional platform variables: written only when the config supplied a value,
    # each with its OG1 long_name and (where defined) its vocabulary attribute.
    for field, (long_name, vocab_attr, vocab_url) in OPTIONAL_PLATFORM_VARS.items():
        if field not in platform_fields:
            continue
        ds_og1[field] = platform_fields[field]
        ds_og1[field].attrs["long_name"] = long_name
        if vocab_attr is not None:
            ds_og1[field].attrs[vocab_attr] = vocab_url

    # Trajectory
    ds_og1["TRAJECTORY"] = (
        ds_og1["PLATFORM_SERIAL_NUMBER"] + "_" + ds_og1.attrs["start_date"]
    )
    ds_og1["TRAJECTORY"].attrs["long_name"] = "trajectory name"
    ds_og1["TRAJECTORY"].attrs["cf_role"] = "trajectory_id"

    ds_og1["DEPLOYMENT_LATITUDE"] = xr.DataArray(
        ds_og1.LATITUDE.values[~np.isnan(ds_og1.LATITUDE)][0],
        attrs={"long_name": "latitude of deployment"},
    )
    ds_og1["DEPLOYMENT_LONGITUDE"] = xr.DataArray(
        ds_og1.LONGITUDE.values[~np.isnan(ds_og1.LONGITUDE)][0],
        attrs={"long_name": "longitude of deployment"},
    )
    ds_og1["DEPLOYMENT_TIME"] = xr.DataArray(
        ds_og1.TIME.values[~np.isnan(ds_og1.TIME)][0],
        attrs={"long_name": "time of deployment"},
    )

    # ---- -------------------------------------------- ----

    # Update time_coverage attributes
    # EFW note: 2025-01-31
    # CHECK LOGIC HERE: Should we be using the first and last time from the first and last dive?
    # Or is time_coverage_start from the base station file a better time to use?
    # Or is there an earlier TIME_GPS timestamp?
    tstart_in_numpy_datetime64 = ds_og1["TIME"][0]
    tend_in_numpy_datetime64 = ds_og1["TIME"][-1]
    tstart_str = _pipeline._clean_time_string(
        np.datetime_as_string(tstart_in_numpy_datetime64, unit="s")
    )
    tend_str = _pipeline._clean_time_string(
        np.datetime_as_string(tend_in_numpy_datetime64, unit="s")
    )
    _log.info("Start of mission from TIME[0]: " + tstart_str)
    _log.info("End of mission from TIME[-1]: " + tend_str)
    ds_og1.attrs["time_coverage_start"] = (
        tstart_str  # ds_og1.TIME[0].values.strftime('%Y%m%dT%H%M%S')
    )
    ds_og1.attrs["time_coverage_end"] = (
        tend_str  # ds_og1.TIME[-1].values.strftime('%Y%m%dT%H%M%S')
    )

    # Update geospatial attributes
    lat_min = ds_og1.LATITUDE.min().values
    lat_max = ds_og1.LATITUDE.max().values
    lon_min = ds_og1.LONGITUDE.min().values
    lon_max = ds_og1.LONGITUDE.max().values
    ds_og1.attrs["geospatial_lat_min"] = lat_min
    ds_og1.attrs["geospatial_lat_max"] = lat_max
    ds_og1.attrs["geospatial_lon_min"] = lon_min
    ds_og1.attrs["geospatial_lon_max"] = lon_max
    depth_min = ds_og1.DEPTH.min().values
    depth_max = ds_og1.DEPTH.max().values
    ds_og1.attrs["geospatial_vertical_min"] = depth_min
    ds_og1.attrs["geospatial_vertical_max"] = depth_max

    # geospatial_bounds: the lat/lon bounding box as a WKT polygon, latitude first
    # (EPSG:4326 axis order), matching the OceanGliders format checker's reference.
    ds_og1.attrs["geospatial_bounds"] = (
        "POLYGON (("
        f"{lat_max:.6f} {lon_min:.6f}, "
        f"{lat_max:.6f} {lon_max:.6f}, "
        f"{lat_min:.6f} {lon_max:.6f}, "
        f"{lat_min:.6f} {lon_min:.6f}, "
        f"{lat_max:.6f} {lon_min:.6f}))"
    )
    # geospatial_vertical_positive: the direction of increasing DEPTH. DEPTH carries the
    # CF standard name "depth" (positive downward), so a positive mean confirms "down";
    # label by the data's sign, and warn rather than assert "down" over depths that do
    # not increase downward.
    depth = ds_og1.DEPTH.values
    if np.all(np.isnan(depth)):
        _log.warning("DEPTH is all-NaN; geospatial_vertical_positive not set.")
    else:
        depth_mean = np.nanmean(depth)
        if depth_mean >= 0:
            ds_og1.attrs["geospatial_vertical_positive"] = "down"
        else:
            _log.warning(
                f"Mean DEPTH is negative ({depth_mean:.3f}); "
                "geospatial_vertical_positive set to 'up', not 'down'."
            )
            ds_og1.attrs["geospatial_vertical_positive"] = "up"
    # time_coverage_duration: end minus start as an ISO 8601 duration.
    ds_og1.attrs["time_coverage_duration"] = pd.Timedelta(
        tend_in_numpy_datetime64.values - tstart_in_numpy_datetime64.values
    ).isoformat()

    # Construct the unique identifier attribute. The data-mode suffix (delayed/R)
    # is the only place OG1 records data mode; there is no data-mode attribute.
    id = (
        f"{platform_serial_number}_{ds_og1.start_date}_{vocabularies.MODE_SUFFIX[mode]}"
    )
    ds_og1.attrs["id"] = id

    # The globals the converter computed here (geospatial, time coverage, id, the
    # earliest-TIME start_date) are "derived" in the conversion ledger.
    for key in (*_DERIVED_GLOBALS, "id"):
        if key in ds_og1.attrs:
            attribute_sources[key] = "derived"

    # Mission config is the last word: the structured deployment block (which may
    # override the derived id or comment, with a warning) then the verbatim escape
    # hatch. Both skip null and placeholder values, and record their source.
    _apply_deployment(ds_og1, deployment, attribute_sources)
    for key, value in global_attributes.items():
        if not _is_empty(value):
            attribute_sources[key] = "overridden" if key in ds_og1.attrs else "mission"
            ds_og1.attrs[key] = value

    # Every metadata source is now merged: fail loud on a missing mandatory global.
    _check_required_globals(ds_og1.attrs)

    # history (ACDD): one provenance line for this conversion, appended to any history the
    # dataset already carries (never replacing it). The basestation history is a per-dive QC
    # log (which samples were flagged, dive-specific warnings), not a mission record, so it is
    # not carried here — carrying one dive's log would assert that dive's QC story for the file.
    conversion_line = (
        f"{datetime.now(UTC).isoformat(timespec='seconds')} "
        f"seagliderOG1 {__version__}: basestation to OG1 (to_og1)"
    )
    existing_history = str(ds_og1.attrs.get("history", "")).strip()
    ds_og1.attrs["history"] = (
        f"{existing_history}\n{conversion_line}"
        if existing_history
        else conversion_line
    )

    # Write down what happened to the dimensions (fate read from the output, and the
    # basestation variable names each dimension carried).
    ds_og1.attrs["conversion_dimensions"] = _dimension_ledger(
        list_of_datasets, ctd_dim, all_dims, ds_og1
    )
    # Warn from the ledger, so the warning names only dimensions whose variables are
    # really absent (the merge list alone misses those placed by the retention path).
    skipped_dims = [
        dim
        for dim, entry in json.loads(ds_og1.attrs["conversion_dimensions"]).items()
        if entry["fate"] == "skipped"
    ]
    if skipped_dims:
        _log.warning(
            "Dimensions not in the OG1 dataset: %s; their variables are not written "
            "(see conversion_dimensions).",
            skipped_dims,
        )

    # Variables the converter created rather than renamed or passed through carry no
    # original_name. Record them as a map ``{derived: [source basestation names]}`` so the
    # reconciliation can account for each basestation variable exactly once. The per-source
    # lists are stamped at each creation site; a variable built from nothing (or not yet
    # stamped) maps to ``[]``. Always written, so an absent attribute is never ambiguous.
    derived_map = {
        str(name): sorted(
            json.loads(ds_og1[name].attrs.pop(_DERIVED_SOURCES_ATTR, "[]"))
        )
        for name in ds_og1.variables
        if "original_name" not in ds_og1[name].attrs
    }
    ds_og1.attrs["conversion_derived_variables"] = json.dumps(
        {name: derived_map[name] for name in sorted(derived_map)}
    )

    # Basestation variables the converter removed outright (the package drop list), distinct
    # from a user keep_variables drop; removed variables leave no trace in the output, so the
    # reconciliation can only see them if recorded here.
    removed = {
        str(v)
        for ds in list_of_datasets
        for v in ds.variables
        if str(v) in vocabularies.VARIABLES_TO_DROP
    }
    ds_og1.attrs["conversion_removed_variables"] = json.dumps(sorted(removed))

    # Distinct basestation variable names across the input dives, so the page can check that
    # the per-fate counts sum to it.
    ds_og1.attrs["conversion_input_variable_count"] = len(
        {str(v) for ds in list_of_datasets for v in ds.variables}
    )

    # Write down which source each global came from (names only; values are in the
    # file). Every written global is categorised; a converter-set global not otherwise
    # attributed is "derived".
    for key in ds_og1.attrs:
        attribute_sources.setdefault(key, "derived")
    ds_og1.attrs["conversion_attribute_sources"] = _attribute_source_ledger(
        ds_og1.attrs, attribute_sources
    )

    # Re-fix QC flags the concat re-promoted to float, then optimise dtypes once on the
    # fully-assembled dataset (coordinates and post-concat variables included).
    for qc_name in [v for v in ds_og1.variables if v[-2:].lower() == "qc"]:
        if qc_name[:-3] in ds_og1.variables:
            ds_og1 = tools.convert_qc_flags(ds_og1, qc_name)

    return _pipeline.set_best_dtype(ds_og1)


def process_mission(
    source: str | os.PathLike,
    output_dir: str | os.PathLike,
    *,
    dives: tuple[int, int] | None = None,
    contributors: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
    platform: dict[str, object] | None = None,
    deployment: dict[str, object] | None = None,
    global_attributes: dict[str, object] | None = None,
    sensors: Mapping[str, Mapping[str, object]] | None = None,
    mode: str = "realtime",
    keep_variables: Sequence[str] | None = None,
    repair: bool = False,
    overwrite: bool = False,
    report: bool = False,
    report_dir: str | os.PathLike | None = None,
    draft: bool = False,
) -> pathlib.Path:
    """Convert one Seaglider mission to an OG1 file: read, convert, subset, write.

    The library form of ``seagliderOG1 process`` for a single mission: the CLI calls
    this once per selected mission. The file is written as ``<output_dir>/<id>.nc``,
    where ``id`` is the converter-derived (or ``deployment``-supplied) identifier, with
    the conversion sidecar ``<id>_conversion.json`` beside it (the input files, which
    dives each variable came from and, except for a draft, the ``dives``, ``platform``
    and ``institutions`` values this call was given; see :func:`conversion_sidecar`).

    Parameters
    ----------
    source : str or os.PathLike
        One mission directory holding basestation files (``pSSSDDDD*.nc``). A root of
        ``SN/DATE`` missions is refused; select one with
        :func:`seagliderOG1.readers.discover_missions` and pass its ``path``.
    output_dir : str or os.PathLike
        Directory the OG1 file is written to; created if missing.
    dives : tuple of (int, int), optional
        First and last dive to convert, inclusive. Default is None (every dive).
    contributors : sequence of dict, optional
        Contributor records, as for :func:`to_og1`. Default is None.
    institutions : sequence of dict, optional
        Institution records, as for :func:`to_og1`. Default is None.
    platform : dict of str to object, optional
        Platform fields, as for :func:`to_og1`. Default is None.
    deployment : dict of str to object, optional
        Deployment-identity globals, as for :func:`to_og1`. Default is None.
    global_attributes : dict of str to object, optional
        Global attributes written verbatim, as for :func:`to_og1`. Default is None.
    sensors : collections.abc.Mapping, optional
        Sensor-record corrections, as for :func:`to_og1`. Default is None.
    mode : str, optional
        Data mode, ``"realtime"`` (default) or ``"delayed"``; sets the ``id`` suffix
        and so the filename. Default is "realtime".
    keep_variables : sequence of str, optional
        Science variables to keep (see :func:`keep_variables`); OG1-mandatory
        variables always survive. Default is None (keep all).
    repair : bool, optional
        Repair basestation time metadata before loading; this rewrites files in the
        source tree (see :func:`seagliderOG1.readers.read_mission`). Default is False.
    overwrite : bool, optional
        Replace an existing output file (and, with ``report``, the page). Default is
        False.
    report : bool, optional
        Also write the HTML conversion page
        (:func:`seagliderOG1.reports.conversion.render_conversion`) beside the file
        as ``<output_dir>/<id>_conversion.html``. Default is False.
    report_dir : str or os.PathLike, optional
        With ``report``, write the page to ``<report_dir>/<id>/`` instead of beside
        the file, so pages can live apart from the archived data (the sidecar stays
        beside the file). Default is None.
    draft : bool, optional
        Mark the output as a draft, not an OG1 file — for a conversion run with no
        mission config, to see what the basestation files hold. The ``id`` (and so
        every file name) ends ``_draft``, a ``draft`` global says why, and
        ``Conventions`` drops ``OG-1.0``. Default is False.

    Returns
    -------
    pathlib.Path
        The path of the written OG1 file.

    Raises
    ------
    ValueError
        If ``source`` is not a directory, holds no basestation files, or is a root of
        ``SN/DATE`` missions; or as raised by :func:`to_og1`.
    FileExistsError
        If the output file or (with ``report``) the page exists and ``overwrite`` is
        False; with ``draft``, also the sidecar or the proposed
        ``<id>_mission.yaml`` (:func:`seagliderOG1.writers.proposal_path`). Otherwise a
        sidecar left beside a missing file is replaced, not refused. Nothing is
        written; ``filename`` is the existing path. The conversion has already run by
        then: the file name derives from the converted ``id``.
    MetadataError
        As raised by :func:`to_og1`.

    Notes
    -----
    With ``report=True`` the page is rendered from the written file. If the render
    fails, the OG1 file stays written and the error propagates.

    See Also
    --------
    to_og1 : The conversion step alone, on datasets already read.

    Examples
    --------
    >>> from seagliderOG1 import convert
    >>> path = convert.process_mission(
    ...     "data/demo_sg005",
    ...     "output",
    ...     contributors=[{"name": "Charlie Eriksen", "role": "PI"}],
    ...     institutions=[{"name": "University of Washington", "role": "Operator"}],
    ... )  # doctest: +SKIP

    """
    missions = readers.discover_missions(str(source))
    if not missions:
        msg = f"no basestation files (pSSSDDDD*.nc) found in {source}"
        raise ValueError(msg)
    if readers.is_root(missions):
        msg = (
            f"{source} is a root of SN/DATE missions; process_mission converts one "
            "mission. Select one with readers.discover_missions and pass its path."
        )
        raise ValueError(msg)

    first, last = dives if dives is not None else (None, None)
    datasets = readers.read_mission(str(source), first, last, repair=repair)
    provenance: dict = {}
    ds = to_og1(
        datasets,
        contributors=contributors,
        institutions=institutions,
        platform=platform,
        deployment=deployment,
        global_attributes=global_attributes,
        sensors=sensors,
        mode=mode,
        provenance=provenance,
    )
    if not draft:
        # What this run was given, so the page can set it against what the files hold:
        # the output cannot say which platform values came from the config.
        provenance["config"] = {
            "dives": list(dives) if dives is not None else None,
            "platform": {
                field: value
                for field, value in (platform or {}).items()
                if not _is_empty(value)
            },
            "deployment_id": None
            if _is_empty((deployment or {}).get("id"))
            else (deployment or {})["id"],
            "institutions": [dict(record) for record in institutions or ()],
        }
    if keep_variables:
        ds = _keep_variables(ds, list(keep_variables))
    if draft:
        ds.attrs["id"] = f"{ds.attrs['id']}_draft"
        ds.attrs["draft"] = DRAFT_NOTE
        writers.record_attribute_sources(ds.attrs, ["draft"], "derived")
        conventions = [
            part.strip()
            for part in str(ds.attrs.get("Conventions", "")).split(",")
            if part.strip() and not part.strip().startswith("OG-")
        ]
        ds.attrs["Conventions"] = ", ".join(conventions)

    output_dir = pathlib.Path(output_dir)
    path = output_dir / f"{ds.attrs['id']}.nc"
    page = writers.conversion_path(path, ".html")
    if report_dir is not None:
        page = pathlib.Path(report_dir) / path.stem / page.name
    targets = [path, page] if report else [path]
    if draft:
        # A draft run writes four files; none is replaced without overwrite, the
        # proposal least of all (the user is told to edit it in place).
        targets += [writers.conversion_path(path, ".json"), writers.proposal_path(path)]
    if not overwrite:
        # Otherwise the sidecar is not checked: it belongs to the .nc, and one left
        # beside a missing .nc is stale and is replaced with it.
        for target in targets:
            if target.exists():
                raise FileExistsError(
                    errno.EEXIST,
                    "output exists; pass overwrite=True to replace it",
                    str(target),
                )
    output_dir.mkdir(parents=True, exist_ok=True)
    writers.write(ds, path, overwrite=overwrite, sidecar=provenance)
    _log.info("wrote %s", path)
    if report:
        # Lazy: reports.conversion imports this module at load time.
        from seagliderOG1.reports.conversion import render_conversion

        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(render_conversion(path), encoding="utf-8")
        _log.info("wrote %s", page)
    return path


def name_mapping(list_of_datasets: Sequence[xr.Dataset]) -> pd.DataFrame:
    """Return the basestation-to-OG1 variable-name mapping for the given datasets.

    The table ``to_og1`` builds internally: one row per unique input variable
    with its OG1 name (empty when unmapped), instrument, dimensions and whether
    OG1 vocabulary attributes were found. Shows which basestation variables carry
    through to OG1 and which are dropped, without running a conversion.

    Parameters
    ----------
    list_of_datasets : sequence of xarray.Dataset
        Basestation datasets, as passed to :func:`to_og1`.

    Returns
    -------
    pandas.DataFrame
        Columns ``original_name``, ``OG1_name``, ``instrument``,
        ``instrument_type``, ``original_dimension`` and ``has_og1_attributes``.

    """
    if isinstance(list_of_datasets, xr.Dataset):
        msg = "name_mapping takes a sequence of datasets; pass a sequence, e.g. [ds]."
        raise TypeError(msg)
    mapping, _ = _pipeline.og1_name_mapping(list(list_of_datasets))
    return mapping


def process_dataset(
    ds1_base: xr.Dataset,
    og1_mapping: pd.DataFrame,
    time_variables: dict[str, list[str]],
    name_lookup: pd.Series | None = None,
) -> tuple[
    xr.Dataset,  # Processed dataset with renamed variables, assigned attributes, and additional information
    list[str],  # List of warnings related to attribute assignments
    pd.DataFrame,  # Dataset containing variables starting with 'sg_cal'
]:
    """Process a dataset by performing a series of transformations and extractions.

    Parameters
    ----------
    ds1_base : xarray.Dataset
        The input dataset from a basestation file, containing various attributes and variables.
    og1_mapping : pandas.DataFrame
        Mapping of original basestation variable names to OG1 variable names.
    time_variables : dict[str, list[str]]
        A dictionary mapping dimension names to lists of time variables.
    name_lookup : pandas.Series or None, optional
        Precomputed ``original_name`` -> ``OG1_name`` lookup. Built from
        ``og1_mapping`` when None; :func:`to_og1` passes it in so it is not
        rebuilt per dive. Default is None.

    Returns
    -------
    tuple
        A tuple containing:
        - ds_new (xarray.Dataset): The processed dataset with renamed variables, assigned attributes,
          converted units, and additional information such as GPS info and dive number.
        - attr_warnings (list[str]): A list of warnings related to attribute assignments.
        - og1_mapping (pd.DataFrame): A DataFrame containing the mapping of original variable names to OG1 variable names.

    Notes
    -----
    - The function performs the following steps:
        1. Handles and splits the inputs:
            - Extracts the dive number from the attributes.
            - Splits the dataset by unique dimensions.
            - Extracts the gps_info from the split dataset.
            - Extracts variables starting with 'sg_cal' (originally from sg_calib_constants.m).
        2. Renames the dataset dimensions, coordinates, and variables according to OG1:
            - Extracts and renames dimensions for 'sg_data_point' (N_MEASUREMENTS).
            - Renames variables according to the OG1 vocabulary.
            - Assigns variable attributes according to OG1 and logs warnings for conflicts.
            - Converts units in the dataset (e.g., cm/s to m/s) where possible.
            - Converts QC flags to int8.
        3. Adds new variables:
            - Adds GPS info as LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS (increasing the length of N_MEASUREMENTS).
            - Adds the divenum as a variable of length N_MEASUREMENTS.
            - Adds the PROFILE_NUMBER (odd for dives, even for ascents).
            - Adds the PHASE of the dive (1 for ascent, 2 for descent, 3 for between the first two surface points).
            - Adds the DEPTH_Z with positive up.
        4. Returns the processed dataset, attribute warnings, and categorized datasets.

    - The function sorts the dataset by TIME and may exhibit undesired behavior if there are not two surface GPS fixes before a dive.

    """
    # Check if the dataset has 'LONGITUDE' as a coordinate
    ds1_base = _pipeline._validate_coords(ds1_base)
    if ds1_base is None or len(ds1_base.variables) == 0:
        return (
            xr.Dataset(),
            [],
        )
    # Split the dataset by unique dimensions
    split_ds = tools.split_by_unique_dims(ds1_base)

    # merge the split datasets along the time dimension using the OG1 mapping and specified dimensions to merge
    merged_ds = _pipeline.merge_datasets_along_time(split_ds, time_variables)
    # Rename variables and attributes to OG1 vocabulary
    # -------------------------------------------------------------------
    # Use variables with dimension 'sg_data_point'
    # Must be after split_ds
    # map the original variable names to the OG1 variable names, and get the instrument type for each variable

    ds_new = standardise_og1(merged_ds, og1_mapping, name_lookup=name_lookup)

    # Add new variables to the dataset (GPS, DIVE_NUMBER, PROFILE_NUMBER, PHASE)
    # -----------------------------------------------------------------------
    # Add the gps_info to the dataset
    # Must be after split_by_unique_dims and after rename_dimensions
    ds_gps = split_ds[("gps_info",)]
    ds_new = add_gps_info_to_dataset(ds_new, ds_gps)
    # Add the profile number (odd for dives, even for get_sgscents)
    ds_new = tools.add_profile_number(ds_new, ds1_base)
    # Assign the phase of the dive (must be after adding divenum)
    ds_new = tools.add_phase(ds_new)
    # Assign DEPTH_Z to the dataset where positive is up.
    ds_new = tools.add_depth(ds_new)

    VARIABLES_TO_DROP = vocabularies.VARIABLES_TO_DROP
    vars_present_to_remove = [
        var for var in VARIABLES_TO_DROP if var in ds_new.variables
    ]

    # Drop them
    ds_new = ds_new.drop_vars(vars_present_to_remove)
    if vars_present_to_remove:
        _log.warning(f"Variables removed from dataset: {vars_present_to_remove}")
    else:
        _log.info("No variables needed to be removed from the dataset.")

    attr_warnings: list[str] = []
    return ds_new, attr_warnings


def standardise_og1(
    ds: xr.Dataset,
    og1_mapping: pd.DataFrame,
    unit_format: dict[str, str] = vocabularies.unit_str_format,
    name_lookup: pd.Series | None = None,
) -> xr.Dataset:
    """Standardize a dataset using OG1 names, attributes, and units.

    Retain all variables, including QC variables. Variables without an OG1
    name keep their original names. Preserve source attributes unless
    replaced by OG1 vocabulary attributes.

    Preserve variable dimensions, renaming ``sg_data_point`` to its OG1
    dimension name. Retain existing coordinates and mark available OG1
    longitude, latitude, depth, and time variables as coordinates.

    Convert units when source and target units are available, standardize
    renamed QC flags, and encode OG1 time.

    Parameters
    ----------
    ds : xarray.Dataset
        Input dataset.
    og1_mapping : pandas.DataFrame
        Mapping containing ``original_name`` and ``OG1_name``.
    name_lookup : pandas.Series or None, optional
        Precomputed ``original_name`` -> ``OG1_name`` lookup. Built from
        ``og1_mapping`` when None. Default is None.
    unit_format : dict[str, str], optional
        Unit spelling replacements. Defaults to
        ``vocabularies.unit_str_format``.

    Returns
    -------
    xarray.Dataset
        Standardized dataset retaining variables without OG1 mappings.
    """
    dsa = ds.copy(deep=True)

    if name_lookup is None:
        name_lookup = og1_mapping.set_index("original_name")["OG1_name"]

    unassigned_variables = []
    variables_without_og1_attributes = []
    output_names = {}
    mapped_variables = set()

    # Determine output names for every variable, including QC variables.
    for original_name in ds.variables:
        og1_name = name_lookup.get(original_name)

        # Derive a QC name from a mapped parent when no explicit entry exists.
        if (og1_name is None or pd.isna(og1_name)) and original_name.lower().endswith(
            "_qc"
        ):
            parent_name = original_name[:-3]
            parent_og1_name = name_lookup.get(parent_name)

            if (
                parent_name in ds.variables
                and parent_og1_name is not None
                and pd.notna(parent_og1_name)
            ):
                og1_name = f"{parent_og1_name}_QC"

        if og1_name is None or pd.isna(og1_name):
            output_names[original_name] = original_name
            unassigned_variables.append(original_name)
        else:
            output_names[original_name] = str(og1_name)
            mapped_variables.add(original_name)

    # Prevent renaming from overwriting another retained variable.
    if len(set(output_names.values())) != len(output_names):
        raise ValueError("OG1 mappings create duplicate output variable names.")

    rename_map = {
        original_name: output_name
        for original_name, output_name in output_names.items()
        if original_name != output_name
    }

    if rename_map:
        dsa = dsa.rename_vars(rename_map)

    # Record each variable's basestation name, so an unmapped variable is visible in
    # the file (its original_name equals its own OG1 name) rather than inferred from
    # the absence of the attribute. Coordinates are included. original_dimension is
    # set only where the dimension changed (merged variables), in _pipeline.
    for original_name, output_name in output_names.items():
        dsa[output_name].attrs["original_name"] = original_name

    # Rename dimensions without changing the shapes of their variables.
    dimension_renames = {
        dimension: vocabularies.DIMENSION_RENAMES[dimension]
        for dimension in dsa.dims
        if dimension in vocabularies.DIMENSION_RENAMES
        and vocabularies.DIMENSION_RENAMES[dimension] != dimension
    }

    if dimension_renames:
        dsa = dsa.rename_dims(dimension_renames)

    for original_name in ds.variables:
        output_name = output_names[original_name]

        # Unmapped variables retain their values and attributes unchanged, except that
        # a raw instrument count with no units is labelled as counts.
        if original_name not in mapped_variables:
            if _is_raw_count(original_name, ds[original_name].attrs):
                dsa[output_name].attrs["units"] = vocabularies.RAW_COUNT_UNITS
            continue

        og1_attributes = vocabularies.vocab_attrs.get(
            output_name,
            {},
        ).copy()

        if not og1_attributes:
            variables_without_og1_attributes.append(output_name)

        # Source attributes provide defaults; OG1 attributes take precedence.
        attributes = ds[original_name].attrs.copy()
        attributes.update(og1_attributes)
        if "units" not in attributes and _is_raw_count(
            original_name, ds[original_name].attrs
        ):
            attributes["units"] = vocabularies.RAW_COUNT_UNITS

        if "units" in ds[original_name].attrs and "units" in og1_attributes:
            original_unit = tools.reformat_units_var(
                ds,
                original_name,
                unit_format,
            )
            target_unit = og1_attributes["units"]

            if original_unit != target_unit:
                converted_values, converted_unit = tools.convert_units_var(
                    ds[original_name].values,
                    original_unit,
                    target_unit,
                    vocabularies.unit1_to_unit2,
                )

                dsa[output_name].data = converted_values
                attributes["units"] = converted_unit

                # Source encoding may no longer suit the converted values.
                dsa[output_name].encoding = {}

        dsa[output_name].attrs = attributes

        # Standardize mapped QC variables, including derived QC mappings.
        if original_name.lower().endswith("_qc") or output_name.upper().endswith("_QC"):
            dsa = tools.convert_qc_flags(dsa, output_name)

    if unassigned_variables:
        _log.debug(
            "Variables retained with their original names: %s",
            sorted(set(unassigned_variables)),
        )
    else:
        _log.debug("All variables have an assigned OG1 name.")

    if variables_without_og1_attributes:
        _log.debug(
            "OG1 variables retained without vocabulary attributes: %s",
            sorted(set(variables_without_og1_attributes)),
        )

    coordinate_names = [
        name
        for name in ("LONGITUDE", "LATITUDE", "DEPTH", "TIME")
        if name in dsa.variables
    ]

    if coordinate_names:
        dsa = dsa.set_coords(coordinate_names)

    if "TIME" in dsa.variables:
        dsa = tools.encode_times_og1(dsa)

    # Optimize dtypes after concatenating datasets in to_og1.
    return dsa


def extract_variables(ds: xr.Dataset) -> tuple[xr.Dataset, xr.Dataset, xr.Dataset]:
    """Split variables from the basestation file that have no dimensions into categorized datasets.

    This function further processes the variables from the basestation file that had no dimensions.
    It categorizes them based on their prefixes or characteristics into three groups:
    variables from `sg_calib_constants`, log files, and other mission/dive-specific values.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset. This function is designed to work on variables from the basestation
        file that had no dimensions, typically after being processed by `split_by_unique_dims`.

    Returns
    -------
    tuple of (xarray.Dataset, xarray.Dataset, xarray.Dataset)
        A tuple containing three xarray Datasets:
        - sg_cal : xarray.Dataset
            Dataset containing variables starting with 'sg_cal_' (originally from `sg_calib_constants.m`).
            The variables are renamed to remove the 'sg_cal_' prefix, so they can be accessed directly
            (e.g., `sg_cal.hd_a`).
        - dc_log : xarray.Dataset
            Dataset containing variables starting with 'log_'. These variables are typically from log files.
        - dc_other : xarray.Dataset
            Dataset containing other mission/dive-specific values. This includes depth-averaged currents
            and other variables like `magnetic_variation`.

    """
    sg_cal_vars = {var: ds[var] for var in ds.variables if var.startswith("sg_cal")}
    divecycle_other = {
        var: ds[var] for var in ds.variables if not var.startswith("sg_cal")
    }
    dc_log_vars = {var: ds[var] for var in divecycle_other if var.startswith("log_")}
    divecycle_other = {
        var: data for var, data in divecycle_other.items() if not var.startswith("log_")
    }

    # Create a new dataset with these variables, renaming to remove the leading 'sg_cal_'
    sg_cal = xr.Dataset(
        {var.replace("sg_cal_", ""): data for var, data in sg_cal_vars.items()}
    )
    dc_other = xr.Dataset(divecycle_other)
    dc_log = xr.Dataset(dc_log_vars)

    return sg_cal, dc_log, dc_other


def add_gps_info_to_dataset(ds: xr.Dataset, gps_ds: xr.Dataset) -> xr.Dataset:
    """Add GPS information (LATITUDE_GPS, LONGITUDE_GPS, TIME_GPS) to the dataset.

    The GPS values will be included within the N_MEASUREMENTS dimension, with non-NaN values
    only when GPS information is available. The dataset will be sorted by TIME.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset with renamed dimensions and variables, representing the main data.
    gps_ds : xarray.Dataset
        The dataset containing GPS information, typically extracted from the original
        basestation dataset.

    Returns
    -------
    xarray.Dataset
        The updated dataset with added GPS information. This includes values for
        LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS only when GPS information is available.

    Notes
    -----
    - The dataset is sorted by TIME (or ctd_time from the original basestation dataset).
    - If the data are not sorted by time, there may be unintended consequences.
    - The function assumes that the GPS dataset contains variables `log_gps_lon`,
      `log_gps_lat`, and `log_gps_time` for longitude, latitude, and time respectively.
    - The function uses the `sg_data_point` dimension as defined in the OG1 vocabulary.

    """
    # Set new dimension name
    newdim = vocabularies.DIMENSION_RENAMES["sg_data_point"]

    # Create a new dataset with GPS information
    gps_ds = xr.Dataset(
        {
            "LONGITUDE": ([newdim], gps_ds["log_gps_lon"].values),
        },
        coords={
            "LATITUDE": ([newdim], gps_ds["log_gps_lat"].values),
            "TIME": ([newdim], gps_ds["log_gps_time"].values),
            "DEPTH": ([newdim], np.full(len(gps_ds["log_gps_lat"]), 0)),
        },
    )
    gps_ds = gps_ds.set_coords("LONGITUDE")

    gps_ds["LATITUDE_GPS"] = (
        [newdim],
        gps_ds.LATITUDE.values,
        vocabularies.vocab_attrs["LATITUDE_GPS"],
        {"dtype": ds["LATITUDE"].dtype},
    )
    gps_ds["LONGITUDE_GPS"] = (
        [newdim],
        gps_ds.LONGITUDE.values,
        vocabularies.vocab_attrs["LONGITUDE_GPS"],
        {"dtype": ds["LONGITUDE"].dtype},
    )
    gps_ds["TIME_GPS"] = (
        [newdim],
        gps_ds.TIME.values,
        vocabularies.vocab_attrs["TIME_GPS"],
        {"dtype": ds["TIME"].dtype},
    )
    # Record each GPS variable's basestation source for the conversion ledger; the
    # transient attr is consumed into conversion_derived_variables before the file is
    # written (see to_og1) and never reaches the output.
    gps_ds["LATITUDE_GPS"].attrs[_DERIVED_SOURCES_ATTR] = json.dumps(["log_gps_lat"])
    gps_ds["LONGITUDE_GPS"].attrs[_DERIVED_SOURCES_ATTR] = json.dumps(["log_gps_lon"])
    gps_ds["TIME_GPS"].attrs[_DERIVED_SOURCES_ATTR] = json.dumps(["log_gps_time"])
    # Their source dimension, as every merged variable carries, so they group with
    # gps_info. No original_name: a derived variable names its sources in the ledger.
    for name in ("LATITUDE_GPS", "LONGITUDE_GPS", "TIME_GPS"):
        gps_ds[name].attrs["original_dimension"] = "gps_info"

    # Concatenate ds and gps_ds
    datasets = []
    datasets.append(ds)
    datasets.append(gps_ds)
    ds_new = xr.concat(datasets, dim=newdim, data_vars="all")
    return ds_new.sortby("TIME")


##-----------------------------------------------------------------------------------------
## Editing attributes
##-----------------------------------------------------------------------------------------
def update_dataset_attributes(
    ds: xr.Dataset,
    people: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
) -> tuple[dict[str, object], dict[str, str]]:
    """Update the attributes of the dataset based on the provided attribute input.

    Processes contributor information, time attributes, and applies OG1
    global attribute vocabulary in the correct order.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset whose attributes need to be updated.
    people : sequence of dict, optional
        Config contributor records to merge with the dataset's own. Default is None.
    institutions : sequence of dict, optional
        Config institution records to merge with the dataset's own. Default is None.

    Returns
    -------
    ordered_attributes : dict
        The ordered attributes with updated values.
    sources : dict of str to str
        Each attribute name mapped to its source for the conversion ledger
        (``package``, ``mixed``, ``derived``, ``renamed`` or ``basestation``).

    """
    attr_as_is = vocabularies.global_attrs["attr_as_is"]
    attr_to_add = vocabularies.global_attrs["attr_to_add"]
    attr_to_rename = vocabularies.global_attrs["attr_to_rename"]
    ATTRIBUTE_ORDER = vocabularies.ATTRIBUTE_ORDER

    # Extract creators and contributors and institution, then reformulate strings
    contrib_attrs = get_contributors(ds, people=people, institutions=institutions)

    # Extract time attributes and reformat basic time strings
    time_attrs = get_time_attributes(ds)

    # Rename some
    renamed_attrs = extract_attr_to_rename(ds, attr_to_rename)

    # Attributes to keep
    keep_attrs = extract_attr_to_keep(ds, attr_as_is)

    # Combine all attributes (last-writer-wins). attr_to_add is applied first and
    # last, so a package constant wins over a file/contributor value of the same name.
    new_attributes = {
        **attr_to_add,
        **contrib_attrs,
        **time_attrs,
        **renamed_attrs,
        **keep_attrs,
        **attr_to_add,
    }

    # Record each attribute's source for the conversion ledger, in the same
    # last-writer-wins order. Contributor/institution attributes are a blend of the
    # mission config and the files, so they are "mixed", never guessed at one source.
    sources: dict[str, str] = {}
    for group, label in (
        (attr_to_add, "package"),
        (contrib_attrs, "mixed"),
        (time_attrs, "derived"),
        (renamed_attrs, "renamed"),
        (keep_attrs, "basestation"),
        (attr_to_add, "package"),
    ):
        for key in group:
            sources[key] = label

    # Reorder attributes according to vocabularies.ATTRIBUTE_ORDER
    ordered_attributes = {
        attr: new_attributes[attr] for attr in ATTRIBUTE_ORDER if attr in new_attributes
    }

    # Add any remaining attributes that were not in the ATTRIBUTE_ORDER list
    for attr in new_attributes:
        if attr not in ordered_attributes:
            ordered_attributes[attr] = new_attributes[attr]

    return ordered_attributes, sources


def get_contributors(
    ds: xr.Dataset,
    people: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
) -> dict[str, str]:
    """Build OG1 contributor and institution attributes.

    Contributors and institutions already on the dataset (``creator_*``,
    ``contributor_*`` and the basestation ``institution`` string, the last only when
    the config gives no ``institutions``) are parsed into records, the mission
    config's ``people`` and ``institutions`` are appended,
    duplicates are consolidated on (name, role) with empty-role fill-in,
    institutions are resolved against the EDMO registry, and everything is
    formatted once into aligned comma-separated lists. No role or EDMO id is ever
    invented; gaps are warned.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset carrying the source contributor/institution attributes.
    people : sequence of dict, optional
        Config contributor records (``name``, ``role`` and optional ``email``,
        ``orcid``). Default is None.
    institutions : sequence of dict, optional
        Config institution records (``name``, ``role`` and optional ``id``).
        Default is None.

    Returns
    -------
    dict of str to str
        The ``contributor_*`` and ``contributing_institutions*`` attributes.

    """
    config_people = [
        {
            "name": person.get("name", ""),
            "email": person.get("email", "") or "",
            "id": contributors.canonical_orcid(person.get("orcid")),
            "role": person.get("role", "") or "",
        }
        for person in (people or [])
    ]
    merged_people = contributors.consolidate(
        contributors.parse_contributors(ds.attrs) + config_people
    )
    for person in merged_people:
        if not (person.get("role") or ""):
            warnings.warn(
                f"no role for contributor {person.get('name')!r}; set one in the "
                "mission config (contributors: - name: ... role: ...).",
                stacklevel=2,
            )
    if not any(
        contributors.canonical_role(person.get("role")) == "PI"
        for person in merged_people
    ):
        warnings.warn(
            "no contributor has the role PI; OG1 requires a principal investigator.",
            stacklevel=2,
        )

    file_institutions = contributors.parse_institutions(ds.attrs)
    # The basestation institution global is free text (a postal address on sg005) with no
    # role. With config institutions it is dropped: kept, it is a role-less second record
    # unless both names resolve to the same registry entry. The conversion page suggests
    # its registry match for the config instead (institution_from_file).
    if "institution" in ds.attrs and not institutions:
        file_institutions = [
            {"name": ds.attrs["institution"], "role": "", "id": ""},
            *file_institutions,
        ]
    config_institutions = [
        {
            "name": institution.get("name", ""),
            "role": institution.get("role", "") or "",
            "id": institution.get("id"),
        }
        for institution in (institutions or [])
    ]
    merged_institutions = contributors.consolidate(
        contributors.enrich_institutions(file_institutions + config_institutions)
    )
    if not any(
        contributors.canonical_role(institution.get("role")) == "Operator"
        for institution in merged_institutions
    ):
        warnings.warn(
            "no institution has the role Operator; OG1 requires an operating "
            "institution.",
            stacklevel=2,
        )

    attributes_dict: dict[str, str] = {}
    attributes_dict.update(contributors.format_contributors(merged_people))
    attributes_dict.update(contributors.format_institutions(merged_institutions))
    return attributes_dict


def get_time_attributes(ds: xr.Dataset) -> dict[str, str]:
    """Extract and clean time-related attributes from the dataset.

    Converts various time formats to OG1-standard YYYYMMDDTHHMMSS format
    and adds date_modified timestamp.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset containing various attributes.

    Returns
    -------
    dict
        A dictionary containing cleaned time-related attributes.

    """
    time_attrs = {}
    # time_coverage_start/end are recomputed authoritatively in to_og1 from the
    # concatenated TIME. time_coverage_start also seeds the start_date fallback
    # below, so it is needed here; the per-dive time_coverage_end is overwritten
    # there and otherwise unused.
    time_attr_list = [
        "time_coverage_start",
        "time_coverage_end",
        "start_time",
    ]
    for attr in time_attr_list:
        if attr in ds.attrs:
            val1 = ds.attrs[attr]
            if isinstance(val1, (int, float)):
                val1 = datetime.fromtimestamp(val1, tz=UTC).strftime("%Y%m%dT%H%M%S")
            if isinstance(val1, str) and ("-" in val1 or ":" in val1):
                val1 = _pipeline._clean_time_string(val1)
            time_attrs[attr] = val1
    # UTC, as every other time the package writes (enrich, history lines).
    time_attrs["date_modified"] = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    # Handle start_date attribute
    if "start_time" in time_attrs:
        time_attrs["start_date"] = time_attrs.pop("start_time")
    if "start_date" not in time_attrs:
        time_attrs["start_date"] = time_attrs["time_coverage_start"]

    # date_created (ACDD) is the creation date of *this* OG1 file, so it is the
    # conversion time, not whatever the basestation file recorded. It must not be in
    # attr_as_is (OG1_global_attributes.yaml): kept attributes are merged after these
    # and would put the basestation's date back.
    time_attrs["date_created"] = time_attrs["date_modified"]

    return time_attrs


def extract_attr_to_keep(
    ds1: xr.Dataset, attr_as_is: list[str] = vocabularies.global_attrs["attr_as_is"]
) -> dict[str, str]:
    """Extract attributes to retain unchanged.

    Parameters
    ----------
    ds1 : xarray.Dataset
        Source dataset.
    attr_as_is : list
        Attribute names to retain without modification.

    Returns
    -------
    dict
        Retained attributes.

    """
    retained_attrs = {}

    # Retain attributes based on attr_as_is
    for attr in attr_as_is:
        if attr in ds1.attrs:
            retained_attrs[attr] = ds1.attrs[attr]

    return retained_attrs


def extract_attr_to_rename(
    ds1: xr.Dataset,
    attr_to_rename: dict[str, str] = vocabularies.global_attrs["attr_to_rename"],
) -> dict[str, str]:
    """Extract and rename attributes according to OG1 vocabulary.

    Parameters
    ----------
    ds1 : xarray.Dataset
        Source dataset.
    attr_to_rename : dict
        Mapping of new_name: old_name for attribute renaming.

    Returns
    -------
    dict
        Renamed attributes.

    """
    renamed_attrs = {}
    # Rename attributes based on values_to_rename
    for new_attr, old_attr in attr_to_rename.items():
        if old_attr in ds1.attrs:
            renamed_attrs[new_attr] = ds1.attrs[old_attr]

    return renamed_attrs
