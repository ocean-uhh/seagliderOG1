"""Read a converted file's conversion record for the ``inspect`` text view and the page.

Everything here reconstructs the conversion from the written artefacts alone — the OG1
file's ``conversion_*`` globals and the ``<id>_conversion.json`` written beside it — so
a caller never depends on conversion-time state. :func:`record` is the one aggregator
the report and ``inspect`` read; :func:`report` writes the HTML page.
"""

import errno
import json
import os
import pathlib
import warnings
from collections.abc import Sequence

import xarray as xr

from seagliderOG1 import writers
from seagliderOG1.exceptions import MetadataError

__all__ = ["record", "report"]


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

    Parses the ``conversion_*`` globals and the per-scalar storage once, so a caller
    (the ``inspect`` text view, the HTML page) does not re-decode the JSON or re-walk
    the variables. Everything returned is reconstructable from the file; nothing is read
    from conversion-time state.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset written by :func:`seagliderOG1.convert`.

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
        If ``ds`` predates the record (no ``conversion_dimensions``), or a per-dive
        scalar's value is not the per-dive JSON this package writes.

    """
    if "conversion_dimensions" not in ds.attrs:
        msg = (
            "no conversion record: the file has no 'conversion_dimensions' global, so "
            "it predates the record (not written by this version of seagliderOG1)."
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


def _run_label(runs: list[list[int]], dives: Sequence[int]) -> str:
    """Return a dive-range label: ``every dive``, ``from dive 12``, ``dives 3–7``, ...

    Parameters
    ----------
    runs : list of [int, int]
        Dive ranges from the conversion record's presence map.
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
        The ``presence`` block of the conversion record.

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
        The ``presence`` block of the conversion record.

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
    """Return the conversion record written beside an OG1 file, or None.

    The record (``<id>_conversion.json``, see :func:`seagliderOG1.writers.write`) holds
    what the file cannot say about its own conversion. It is bound to the file by ``id``
    and ``tracking_id`` (``id`` and ``date_created`` for one written before
    ``tracking_id``); a record from another conversion is not returned. With ``verify``,
    the file's SHA-256 is compared with the one recorded and a mismatch warns that the
    file changed after the record was written (the record is still returned).

    Parameters
    ----------
    path : str or os.PathLike
        The OG1 netCDF file.
    verify : bool, optional
        Hash the file and compare (reads the whole file). Default is False.

    Returns
    -------
    dict or None
        The record contents, or None when it is missing, unreadable, of another schema,
        or belongs to another conversion (each but the first warned).

    """
    path = pathlib.Path(path)
    record_path = writers.conversion_path(path, ".json")
    if not record_path.is_file():
        return None
    try:
        contents = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.warn(
            f"{record_path.name} could not be read ({exc}); ignoring it.", stacklevel=2
        )
        return None
    if (
        not isinstance(contents, dict)
        or contents.get("schema") != writers.RECORD_SCHEMA
    ):
        warnings.warn(
            f"{record_path.name} is not a schema-{writers.RECORD_SCHEMA} conversion "
            "record; ignoring it.",
            stacklevel=2,
        )
        return None
    keys = (
        ("id", "tracking_id") if "tracking_id" in contents else ("id", "date_created")
    )
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        binding = {key: ds.attrs.get(key) for key in keys}
    if {key: contents.get(key) for key in binding} != binding:
        warnings.warn(
            f"{record_path.name} belongs to another conversion "
            f"({'/'.join(keys)} differ from {path.name}); ignoring it.",
            stacklevel=2,
        )
        return None
    if (
        verify
        and "sha256" in contents
        and contents["sha256"] != writers.file_sha256(path)
    ):
        warnings.warn(
            f"{path.name} has changed since {record_path.name} was written "
            "(SHA-256 differs).",
            stacklevel=2,
        )
    return contents


def record(path: str | os.PathLike, *, verify: bool = True) -> dict:
    """Return the conversion record for an OG1 file: its globals and the JSON beside it.

    One read for the report and ``inspect``: the ``conversion_*`` globals parsed from
    the file (:func:`conversion_ledger`) and the ``<id>_conversion.json`` written beside
    it (:func:`conversion_sidecar`), as one mapping.

    Parameters
    ----------
    path : str or os.PathLike
        The OG1 netCDF file.
    verify : bool, optional
        Hash the file and compare against the record's checksum. Default is True.

    Returns
    -------
    dict
        ``{"ledger": <from the file's globals>, "conversion": <the JSON beside it, or
        None>}``.

    """
    path = pathlib.Path(path)
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        ledger = conversion_ledger(ds)
    return {"ledger": ledger, "conversion": conversion_sidecar(path, verify=verify)}


def report(
    nc_path: str | os.PathLike,
    out: str | os.PathLike | None = None,
    *,
    title: str | None = None,
    overwrite: bool = False,
) -> pathlib.Path:
    """Write the HTML conversion page for an OG1 file and return its path.

    Parameters
    ----------
    nc_path : str or os.PathLike
        The OG1 netCDF file.
    out : str or os.PathLike, optional
        Where to write the page. Default is ``<id>_conversion.html`` beside the file.
    title : str or None, optional
        Page title; the file name by default.
    overwrite : bool, optional
        Replace an existing page. Default is False.

    Returns
    -------
    pathlib.Path
        The path of the written page.

    Raises
    ------
    FileNotFoundError
        If ``nc_path`` does not exist.
    FileExistsError
        If the page exists and ``overwrite`` is False.

    """
    nc_path = pathlib.Path(nc_path)
    if not nc_path.is_file():
        raise FileNotFoundError(errno.ENOENT, "no such OG1 file", str(nc_path))
    target = (
        pathlib.Path(out)
        if out is not None
        else writers.conversion_path(nc_path, ".html")
    )
    if target.exists() and not overwrite:
        raise FileExistsError(
            errno.EEXIST, "page exists; pass overwrite=True to replace it", str(target)
        )
    # Lazy: reports.conversion imports this module at load time.
    from seagliderOG1.reports.conversion import render_conversion

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_conversion(nc_path, title=title, verify=True), encoding="utf-8"
    )
    return target
