"""Write OG1 datasets to compressed NetCDF files."""

import hashlib
import json
import logging
import uuid
from collections.abc import Iterable, MutableMapping
from numbers import Number
from pathlib import Path

import numpy as np
import xarray as xr

from seagliderOG1 import __version__, tools

_log = logging.getLogger(__name__)

__all__ = [
    "write",
    "conversion_path",
    "file_sha256",
    "proposal_path",
    "record_attribute_sources",
    "write_sidecar",
]

# Version of the sidecar layout; bump when a reader would misread the old one.
SIDECAR_SCHEMA = 1

# OG1 serialisation for datetime variables: float64 seconds using the canonical OG1 time
# units (defined once in tools), so the written file matches encode_times_og1 instead of
# silently overriding it.
_TIME_ENCODING = {
    "units": tools.OG1_TIME_UNITS,
    "calendar": tools.OG1_TIME_CALENDAR,
    "dtype": "float64",
}


# Encoding entries that carry data semantics (missing-value sentinel, packing) and
# must be kept when an explicit compression encoding replaces a variable's encoding.
_PRESERVE_ENCODING = ("_FillValue", "missing_value", "scale_factor", "add_offset")


def write(
    ds: xr.Dataset,
    path: str | Path,
    *,
    overwrite: bool = False,
    sidecar: dict | None = None,
) -> Path:
    """Write the dataset to a NetCDF file with lossless compression.

    Every non-scalar numeric variable, coordinates included, is written with zlib
    at level 4 and the shuffle filter. Attributes are checked before anything is
    written: one netCDF cannot store is refused by name, never converted to text.
    The input dataset is copied first, so the caller's dataset is not modified.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to save.
    path : str or pathlib.Path
        Output NetCDF file path.
    overwrite : bool, optional
        If True, an existing file will be deleted and replaced.
        If False, a FileExistsError is raised when the file exists.
    sidecar : dict, optional
        Conversion provenance (as filled by ``to_og1(provenance=...)``) to write beside
        the file as ``<stem>_conversion.json`` (:func:`conversion_path`), bound to it by the
        dataset's ``id`` and ``tracking_id``; a sidecar already there is replaced.
        Nothing from it is written into the NetCDF file. Default is None (no sidecar).

    Returns
    -------
    pathlib.Path
        The path written.

    Raises
    ------
    FileExistsError
        If ``path`` exists and ``overwrite`` is False.
    ValueError
        If the dataset carries a None-valued attribute.
    TypeError
        If an attribute (global or on a variable) has a type netCDF cannot store, such
        as a dict or a bool; the message names each one. Nothing is written or removed.
    """
    ds = ds.copy()

    # Refuse None-valued attributes by name rather than writing the literal "None".
    none_attrs = [name for name, value in ds.attrs.items() if value is None]
    none_attrs += [
        f"{var_name}:{name}"
        for var_name, var in ds.variables.items()
        for name, value in var.attrs.items()
        if value is None
    ]
    if none_attrs:
        msg = f"refusing to write None-valued attribute(s): {none_attrs}"
        raise ValueError(msg)
    # Checked here, before an existing file is removed: an attribute netCDF cannot
    # store is the caller's to fix, so it is named, not converted to text.
    bad_attrs = [
        f"{owner}:{name} ({type(value).__name__})"
        for owner, attrs in [("global", ds.attrs)]
        + [(str(var_name), var.attrs) for var_name, var in ds.variables.items()]
        for name, value in attrs.items()
        if not _storable_attribute(value)
    ]
    if bad_attrs:
        msg = f"refusing to write attribute(s) netCDF cannot store: {bad_attrs}"
        raise TypeError(msg)

    # Handle existing file
    output_path = Path(path)
    if output_path.exists():
        if overwrite:
            _log.info("Removing existing file: %s", path)
            output_path.unlink()
        else:
            raise FileExistsError(
                f"Output file '{path}' already exists. "
                "Use overwrite=True to replace it."
            )

    # A new identity for every written version of the file (ctdcast's tracking_id); the
    # sidecar binds to it, and enrich issues a new one.
    ds.attrs["tracking_id"] = str(uuid.uuid4())
    record_attribute_sources(ds.attrs, ["tracking_id"], "derived")

    encoding = _compression_encoding(ds)
    for name, var in ds.variables.items():
        if np.issubdtype(var.dtype, np.datetime64):
            # Drop units/calendar from attrs so they cannot conflict with the
            # explicit time encoding applied on write.
            var.attrs.pop("units", None)
            var.attrs.pop("calendar", None)
            encoding.setdefault(name, {}).update(_TIME_ENCODING)

    ds.to_netcdf(path, encoding=encoding, format="NETCDF4", engine="netcdf4")
    _log.info("Dataset successfully saved to %s", path)
    if sidecar is not None:
        write_sidecar(path, ds.attrs, sidecar)
    return Path(path)


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes.

    Parameters
    ----------
    path : str or pathlib.Path
        The file to hash.

    Returns
    -------
    str
        The 64-character hex digest.

    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def record_attribute_sources(
    attrs: MutableMapping[str, object], names: Iterable[str], category: str
) -> None:
    """Move global names into one category of the ``conversion_attribute_sources`` ledger.

    For a global written after the conversion built the ledger (``tracking_id`` here,
    ``draft`` and ``enrich``'s keys in :mod:`seagliderOG1.convert`), so the ledger
    still names every global exactly once. Does nothing when ``attrs`` carries no
    ledger.

    Parameters
    ----------
    attrs : collections.abc.MutableMapping
        Global attributes holding the ledger as JSON; modified in place.
    names : collections.abc.Iterable of str
        The globals to record.
    category : str
        The ledger category they now belong to (e.g. ``"derived"``, ``"enriched"``).

    """
    if "conversion_attribute_sources" not in attrs:
        return
    names = set(names)
    sources = json.loads(str(attrs["conversion_attribute_sources"]))
    for members in sources.values():
        members[:] = [name for name in members if name not in names]
    sources[category] = sorted(set(sources.get(category, [])) | names)
    attrs["conversion_attribute_sources"] = json.dumps(
        {key: members for key, members in sources.items() if members}
    )


def write_sidecar(path: str | Path, attrs: dict, contents: dict) -> Path:
    """Write ``<stem>_conversion.json`` beside an OG1 file, bound to its current version.

    The binding is the file's ``id`` and ``tracking_id`` plus the SHA-256 of its bytes,
    so a reader can tell the sidecar belongs to this file and that the file has not
    changed since. A checksum cannot live inside the file it covers, so it lives here.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 netCDF file, already written.
    attrs : dict
        Its global attributes (``id``, ``tracking_id``, ``date_created``).
    contents : dict
        The sidecar body (``inputs``, ``presence``, ...); its binding keys, if any,
        are replaced.

    Returns
    -------
    pathlib.Path
        The sidecar path.

    """
    # The binding keys come last so the body cannot override them.
    payload = {
        **contents,
        "schema": SIDECAR_SCHEMA,
        "id": attrs.get("id"),
        "tracking_id": attrs.get("tracking_id"),
        "date_created": attrs.get("date_created"),
        "sha256": file_sha256(path),
        "converter": {"seagliderOG1": __version__},
    }
    target = conversion_path(path, ".json")
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    _log.info("Conversion sidecar written to %s", target)
    return target


def conversion_path(path: str | Path, suffix: str) -> Path:
    """Return a conversion output beside an OG1 file: ``<stem>_conversion<suffix>``.

    The one place the names of the conversion sidecar (``.json``) and the conversion
    page (``.html``) are built.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 netCDF file.
    suffix : str
        ``".json"`` for the sidecar, ``".html"`` for the page.

    Returns
    -------
    pathlib.Path
        The path, in the same directory as ``path``.

    """
    path = Path(path)
    return path.with_name(f"{path.stem}_conversion{suffix}")


def _storable_attribute(value: object) -> bool:
    """Return whether netCDF can store ``value`` as an attribute unchanged.

    Text, a number, or a sequence or array of text or numbers. Not a bool (netCDF has no
    boolean attribute), None, a mapping, or a sequence holding any of those.

    Parameters
    ----------
    value : object
        The attribute value.

    Returns
    -------
    bool
        True when it can be written as is.

    """

    def scalar(item: object) -> bool:
        if isinstance(item, bool | np.bool_):
            return False
        return isinstance(item, str | bytes | Number | np.number)

    if isinstance(value, np.ndarray):
        return value.dtype.kind in "iufcSU"
    if isinstance(value, list | tuple):
        return all(scalar(item) for item in value)
    return scalar(value)


def proposal_path(path: str | Path) -> Path:
    """Return the proposed mission config beside a draft file: ``<stem>_mission.yaml``.

    Written by the ``draft`` verb; named here, beside :func:`conversion_path`, so the
    verb and :func:`seagliderOG1.convert.process_mission`'s existence check agree. Not
    a ``_conversion`` name: it is a config for the next run, not a record of this one.

    Parameters
    ----------
    path : str or pathlib.Path
        The draft netCDF file.

    Returns
    -------
    pathlib.Path
        The path, in the same directory as ``path``.

    """
    path = Path(path)
    return path.with_name(f"{path.stem}_mission.yaml")


def _compression_encoding(ds: xr.Dataset) -> dict[str, dict]:
    """Build a per-variable zlib encoding for the compressible variables.

    Returns zlib-at-level-4 plus the shuffle filter for every non-scalar numeric
    variable, coordinates included. String and scalar variables are omitted: the
    HDF5 zlib filter does not apply to variable-length strings and cannot chunk a
    scalar. Because an explicit encoding replaces a variable's own encoding on
    write, any existing semantic entries (`_FillValue`, packing) are carried over
    so a missing-value sentinel is not written as an ordinary value.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to be written.

    Returns
    -------
    dict of str to dict
        Mapping of variable name to its compression encoding.

    """
    compression = {"zlib": True, "complevel": 4, "shuffle": True}
    encoding: dict[str, dict] = {}
    for name, var in ds.variables.items():
        if var.ndim > 0 and var.dtype.kind not in ("U", "S", "O"):
            enc = {k: var.encoding[k] for k in _PRESERVE_ENCODING if k in var.encoding}
            enc.update(compression)
            encoding[name] = enc
            if var.ndim == 1 and var.size > 0:
                enc["chunksizes"] = (min(var.size, 65_536),)
    return encoding
