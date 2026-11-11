"""The variable index: one entry per variable, basestation input beside OG1 output.

Built once from the OG1 file, its ``conversion_*`` ledger and the conversion record beside
it, and read by the Variables page (the index table) and the Conversion page (its counts and
the losses list). An input fact the record does not hold is ``None`` here and "not recorded"
on the page; nothing is inferred.
"""

import json
import re
from collections.abc import Mapping
from typing import TypedDict

import numpy as np
import xarray as xr

from seagliderOG1 import vocabularies
from seagliderOG1._convert import count_values

__all__ = ["FATES", "Mark", "VariableRow", "fate_sets", "variable_rows"]

#: The fates of a basestation variable, in the priority order that gives each name exactly
#: one: an output wins over a dimension listing. Each is ``(key, meaning)``.
FATES: tuple[tuple[str, str], ...] = (
    (
        "renamed",
        "In the file under its OG1 name; original_name holds the basestation name.",
    ),
    ("passthrough", "In the file under its basestation name."),
    (
        "consumed",
        "Not in the file itself; its data went into a variable the converter built.",
    ),
    ("removed", "Not in the file; was on the package drop list."),
    ("dropped", "Not in the file; left out by keep_variables."),
    ("skipped", "Not in the file; its dimension is not placed on N_MEASUREMENTS."),
)

#: Attributes that state how a derived variable was computed, in the order looked for.
_METHOD_ATTRS: tuple[str, ...] = (
    "phase_calculation_method",
    "profile_calculation_method",
    "segment_calculation_method",
    "calculation_method",
)


class Mark(TypedDict):
    """One mark on an index entry: a loss, a recorded step, or a gap in the record."""

    kind: str
    text: str


class VariableRow(TypedDict):
    """One entry of the variable index.

    ``basestation`` is empty for a variable the converter built; ``name`` is empty for a
    basestation variable not written. The ``*_in`` fields are None when the conversion
    record does not hold them (an older record, or a derived variable).
    """

    basestation: str
    name: str
    fate: str
    dimension: str
    units_in: str | None
    units_out: str
    factor: float | None
    dtype_in: str | None
    dtype_out: str
    values_in: int | None
    values_out: int | None
    vocabulary: str
    standard_name: str
    inputs: list[str] | None
    method: str
    subsystem: str
    scalar: bool
    storage: str
    marks: list[Mark]
    attrs: dict[str, str]
    candidate: str


def fate_sets(ds: xr.Dataset, ledger: Mapping) -> dict[str, set[str]]:
    """Return the basestation names of each fate, each name in exactly one set.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset.
    ledger : collections.abc.Mapping
        The parsed ledger from :func:`seagliderOG1.reports._record.conversion_ledger`.

    Returns
    -------
    dict of str to set of str
        Fate key (as in :data:`FATES`, in that order) to basestation names.

    """
    raw = {
        "renamed": {
            str(ds[n].attrs["original_name"])
            for n in ds.variables
            if ds[n].attrs.get("original_name") not in (None, n)
        },
        "passthrough": {
            str(n) for n in ds.variables if ds[n].attrs.get("original_name") == n
        },
        "consumed": {s for sources in ledger["derived"].values() for s in sources},
        "removed": set(ledger["removed"]),
        "dropped": set(ledger["dropped"]),
        "skipped": {
            v
            for info in ledger["dimensions"].values()
            if info["fate"] == "skipped"
            for v in info["variables"]
        },
    }
    seen: set[str] = set()
    out: dict[str, set[str]] = {}
    for key, _meaning in FATES:
        out[key] = raw[key] - seen
        seen |= raw[key]
    return out


def _units(var: xr.DataArray) -> str:
    """Return an output variable's units; a decoded time keeps them in its encoding."""
    return str(var.attrs.get("units", var.encoding.get("units", "")))


def _dtype_out(var: xr.DataArray) -> str:
    """Return the on-disk dtype of an output variable, naming JSON text as such."""
    if var.attrs.get("storage_type") == "per_dive_scalar":
        return "text (JSON)"
    dtype = var.encoding.get("dtype", var.dtype)
    if np.dtype(dtype).kind in "OSU":
        return "text"
    return str(np.dtype(dtype))


def _values_out(var: xr.DataArray, storage: str, values_in: int | None) -> int | None:
    """Return the non-missing values of an output variable, comparable with the input count.

    A per-dive scalar counts its dives with a value; a constant scalar stands for every dive
    that had it, so it counts as the input did. None when a per-dive payload cannot be read.
    """
    if storage == "per_dive_scalar":
        try:
            payload = json.loads(str(np.asarray(var.values).item()))
            return sum(v is not None for v in payload["values"])
        except (ValueError, TypeError, KeyError):
            return None
    if storage == "constant_scalar":
        return values_in if values_in is not None else 1
    return count_values(var.values)


def _marks(
    var: xr.DataArray | None,
    fate: str,
    units_in: str | None,
    units_out: str,
    factor: float | None,
    dtype_in: str | None,
    dtype_out: str,
) -> list[Mark]:
    """Return the loss and step marks of one index entry (see the page's glossary)."""
    marks: list[Mark] = []
    if fate in ("removed", "dropped", "skipped"):
        marks.append({"kind": "loss", "text": "not written"})
    if var is None:
        return marks
    if factor is not None and factor != 1:
        marks.append({"kind": "step", "text": f"×{factor:g}"})
    elif units_in == "" and units_out and "original_units" in var.attrs:
        marks.append({"kind": "step", "text": "units adopted"})
    elif units_in and units_out and units_in != units_out:
        if "original_units" in var.attrs:
            marks.append({"kind": "step", "text": "units relabelled"})
        else:
            marks.append({"kind": "loss", "text": "unit spelling not kept"})
    if dtype_in == "float64" and dtype_out == "float32":
        marks.append({"kind": "step", "text": "float64 → float32"})
    if dtype_out == "text (JSON)" and dtype_in and _numeric(dtype_in):
        marks.append({"kind": "loss", "text": "numbers → JSON text"})
    return marks


def _numeric(dtype: str) -> bool:
    """Return whether a recorded dtype string names a numeric type (False if unreadable)."""
    try:
        return np.dtype(dtype).kind in "fiu"
    except TypeError:
        return False


def _method(var: xr.DataArray) -> str:
    """Return the attribute that states how a derived variable was computed, if any."""
    for name in _METHOD_ATTRS:
        if var.attrs.get(name):
            return str(var.attrs[name])
    return ""


def _factor(entry: object) -> float | None:
    """Return the factor of one ``conversion_units`` entry ``[from, to, factor]``.

    None when the entry is missing or not in that form (an older or hand-edited file),
    so the page shows no factor rather than failing.
    """
    if isinstance(entry, list | tuple) and len(entry) >= 3:
        factor = entry[2]
        if isinstance(factor, int | float) and not isinstance(factor, bool):
            return float(factor)
    return None


def variable_rows(
    ds: xr.Dataset, ledger: Mapping, record: Mapping | None
) -> list[VariableRow]:
    """Return the variable index: every basestation variable, then every derived one.

    Parameters
    ----------
    ds : xarray.Dataset
        An open OG1 dataset written by :func:`seagliderOG1.convert`.
    ledger : collections.abc.Mapping
        The parsed ledger from :func:`seagliderOG1.reports._record.conversion_ledger`.
    record : collections.abc.Mapping or None
        The conversion record beside the file, or None when it is missing; without its
        ``input_variables`` the input columns are None.

    Returns
    -------
    list of VariableRow
        One entry per basestation input (sorted by name, case-insensitive), then one per
        variable the converter built (sorted by name).

    """
    inputs: Mapping[str, Mapping] = (record or {}).get("input_variables") or {}
    # The instrument global is space- or comma-separated, depending on the basestation.
    instruments = {
        token
        for value in ((record or {}).get("basestation_globals") or {})
        .get("instrument", {})
        .get("values", [])
        for token in re.split(r"[\s,;]+", str(value))
        if token
    }
    units_ledger = json.loads(ds.attrs.get("conversion_units", "{}"))
    fates = fate_sets(ds, ledger)
    fate_of = {name: key for key, names in fates.items() for name in names}
    output_of = {
        str(ds[n].attrs.get("original_name", n)): str(n)
        for n in ds.variables
        if ds[n].attrs.get("original_name")
    }
    names = set(fate_of) | set(inputs)

    rows: list[VariableRow] = []
    for bs in sorted(names, key=str.lower):
        fate = fate_of.get(bs, "unattributed")
        out = output_of.get(bs, "") if fate in ("renamed", "passthrough") else ""
        var = ds[out] if out else None
        given = inputs.get(bs)
        units_in = given["units"] if given else None
        dtype_in = given["dtype"] if given else None
        values_in = given["values"] if given else None
        units_out = _units(var) if var is not None else ""
        dtype_out = _dtype_out(var) if var is not None else ""
        factor = _factor(units_ledger.get(out)) if out else None
        storage = str(var.attrs.get("storage_type", "")) if var is not None else ""
        dims = given["dimensions"] if given else []
        rows.append(
            {
                "basestation": bs,
                "name": out,
                "fate": fate,
                "dimension": ", ".join(dims) if dims else ("scalar" if given else ""),
                "units_in": units_in,
                "units_out": units_out,
                "factor": factor,
                "dtype_in": dtype_in,
                "dtype_out": dtype_out,
                "values_in": values_in,
                "values_out": _values_out(var, storage, values_in)
                if var is not None
                else None,
                "vocabulary": str(var.attrs.get("vocabulary", ""))
                if var is not None
                else "",
                "standard_name": str(var.attrs.get("standard_name", ""))
                if var is not None
                else "",
                "inputs": None,
                "method": "",
                "subsystem": vocabularies.subsystem_of(bs, instruments),
                "scalar": bool(given is not None and not dims)
                or (var is not None and not var.dims),
                "storage": storage,
                "marks": _marks(
                    var, fate, units_in, units_out, factor, dtype_in, dtype_out
                ),
                "attrs": {k: str(v) for k, v in var.attrs.items()}
                if var is not None
                else {},
            }
        )

    for name, sources in sorted(ledger["derived"].items()):
        if name not in ds.variables:
            continue
        var = ds[name]
        storage = str(var.attrs.get("storage_type", ""))
        marks: list[Mark] = []
        if not sources:
            marks.append({"kind": "gap", "text": "inputs not recorded"})
        rows.append(
            {
                "basestation": "",
                "name": name,
                "fate": "derived",
                "dimension": ", ".join(str(d) for d in var.dims) or "scalar",
                "units_in": None,
                "units_out": _units(var),
                "factor": None,
                "dtype_in": None,
                "dtype_out": _dtype_out(var),
                "values_in": None,
                "values_out": _values_out(var, storage, None),
                "vocabulary": str(var.attrs.get("vocabulary", "")),
                "standard_name": str(var.attrs.get("standard_name", "")),
                "inputs": list(sources) or None,
                "method": _method(var),
                "subsystem": "derived",
                "scalar": not var.dims,
                "storage": storage,
                "marks": marks,
                "attrs": {k: str(v) for k, v in var.attrs.items()},
            }
        )
    for row in rows:
        # The project's proposed OG1 parameters (vocabularies.OG1_CANDIDATE_VARS).
        role = vocabularies.OG1_CANDIDATE_VARS.get(
            row["name"]
        ) or vocabularies.OG1_CANDIDATE_VARS.get(row["basestation"], "")
        row["candidate"] = role
        if role:
            row["marks"].append({"kind": "candidate", "text": f"OG1 candidate: {role}"})
    return rows
