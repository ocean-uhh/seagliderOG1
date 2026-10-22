"""Write OG1 datasets to compressed NetCDF files, and edit a written file's globals."""

import errno
import hashlib
import json
import logging
import uuid
import warnings
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import UTC, date, datetime
from numbers import Number
from pathlib import Path

import netCDF4
import numpy as np
import xarray as xr

from seagliderOG1 import __version__, tools
from seagliderOG1 import mission as _mission

_log = logging.getLogger(__name__)

__all__ = [
    "conversion_path",
    "enrich",
    "file_sha256",
    "proposal_path",
    "record_attribute_sources",
    "write",
    "write_record",
]

# Version of the conversion-record layout; bump when a reader would misread the old one.
RECORD_SCHEMA = 1

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
    record: dict | None = None,
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
    record : dict, optional
        The conversion record (as filled by ``convert(record=...)``) to write beside
        the file as ``<stem>_conversion.json`` (:func:`conversion_path`), bound to it by the
        dataset's ``id`` and ``tracking_id``; a record already there is replaced.
        Nothing from it is written into the NetCDF file. Default is None (no record).

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
    if record is not None:
        write_record(path, ds.attrs, record)
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
    """Move global names into one category of the ``conversion_attribute_sources`` record.

    For a global written after the conversion built the source record (``tracking_id``
    here, and ``draft`` and ``enrich``'s keys), so the record still names every global
    exactly once. Does nothing when ``attrs`` carries no such record.

    Parameters
    ----------
    attrs : collections.abc.MutableMapping
        Global attributes holding the source record as JSON; modified in place.
    names : collections.abc.Iterable of str
        The globals to record.
    category : str
        The category they now belong to (e.g. ``"derived"``, ``"enriched"``).

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


def write_record(path: str | Path, attrs: dict, contents: dict) -> Path:
    """Write the conversion record ``<stem>_conversion.json`` beside an OG1 file.

    The record is bound to the file's current version by its ``id`` and ``tracking_id``
    plus the SHA-256 of its bytes, so a reader can tell the record belongs to this file
    and that the file has not changed since. A checksum cannot live inside the file it
    covers, so it lives beside it.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 netCDF file, already written.
    attrs : dict
        Its global attributes (``id``, ``tracking_id``, ``date_created``).
    contents : dict
        The record body (``inputs``, ``presence``, ...); its binding keys, if any,
        are replaced.

    Returns
    -------
    pathlib.Path
        The path of the record file.

    """
    # The binding keys come last so the body cannot override them.
    payload = {
        **contents,
        "schema": RECORD_SCHEMA,
        "id": attrs.get("id"),
        "tracking_id": attrs.get("tracking_id"),
        "date_created": attrs.get("date_created"),
        "sha256": file_sha256(path),
        "converter": {"seagliderOG1": __version__},
    }
    target = conversion_path(path, ".json")
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    _log.info("Conversion record written to %s", target)
    return target


def conversion_path(path: str | Path, suffix: str) -> Path:
    """Return a conversion output beside an OG1 file: ``<stem>_conversion<suffix>``.

    The one place the names of the conversion record (``.json``) and the conversion
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
        # netCDF attributes are scalar or 1-D; a 2-D array would pass a dtype-only check
        # and then fail in to_netcdf after an existing output was already removed.
        return value.ndim <= 1 and value.dtype.kind in "iufcSU"
    if isinstance(value, list | tuple):
        return all(scalar(item) for item in value)
    return scalar(value)


def proposal_path(path: str | Path) -> Path:
    """Return the proposed mission config beside a draft file: ``<stem>_mission.yaml``.

    Written by the ``draft`` verb; named here, beside :func:`conversion_path`, so the
    verb and the converter's existence check agree. Not a ``_conversion`` name: it is a
    config for the next run, not a record of this one.

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


# Globals enrich writes itself (besides the converter-derived ones): a config may not
# set them, or the file's own record of the edit would be overwritten.
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
    path: str | Path,
    *,
    mission: str | Path | Mapping[str, object] | None = None,
    deployment: Mapping[str, object] | None = None,
    global_attributes: Mapping[str, object] | None = None,
    doi: str | None = None,
) -> Path:
    """Set global attributes on a written OG1 file without converting again.

    For metadata that exists only after the file is written — a DOI assigned on
    publication — or a corrected global-attribute value. Only global attributes change
    (edited in place; variables are not rewritten). The file gets ``date_modified`` set
    to now, a ``history`` line naming the keys, and a new ``tracking_id``;
    ``date_created`` is kept. Every value is checked before the file is opened for
    writing, so a refused value leaves the file as it was. Replacing a different value
    already in the file warns with both values. The conversion record beside the file is
    rebound to the new ``tracking_id`` and SHA-256.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 netCDF file.
    mission : str or os.PathLike or collections.abc.Mapping, optional
        A ``mission.yaml`` path or loaded mapping; only its three global-attribute
        sections and ``global_attributes`` are used (merged into ``deployment`` and
        ``global_attributes`` below). The ``platform:`` block and other keys are
        ignored — enrich edits globals only. Default is None.
    deployment : collections.abc.Mapping, optional
        Deployment-identity globals to set (as in :func:`seagliderOG1.convert`); null
        values are skipped. Overrides the mission's merged sections. Default is None.
    global_attributes : collections.abc.Mapping, optional
        ``global_attributes:`` keys to set. Overrides the mission's. Default is None.
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
        the other block; a value is not text, a number or a date; a key is one
        ``enrich`` writes itself (``date_modified``, ``history``, ``tracking_id``,
        ``draft``) or a ``conversion_*`` record; or ``deployment["id"]`` differs from
        the file's ``id`` (the file name and the conversion record are bound to it:
        convert again to change it).
    FileNotFoundError
        If ``path`` does not exist.

    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(errno.ENOENT, "no such OG1 file", str(path))
    deployment = dict(deployment or {})
    global_attributes = dict(global_attributes or {})
    if mission is not None:
        cfg = dict(mission) if isinstance(mission, Mapping) else _load_mission(mission)
        merged = _mission._merge_sections(cfg)
        deployment = {**merged, **deployment}
        global_attributes = {
            **(cfg.get("global_attributes") or {}),
            **global_attributes,
        }
    _mission._check_global_keys(deployment, global_attributes)
    owned = sorted(
        key
        for key, value in global_attributes.items()
        if not _mission._is_placeholder(value)
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
        if not _mission._is_placeholder(value)
    }
    if not updates:
        msg = "nothing to enrich: no mission, deployment, global_attributes or doi value given."
        raise ValueError(msg)

    with netCDF4.Dataset(path, "r") as nc:
        current = {key: nc.getncattr(key) for key in nc.ncattrs()}
    if "id" in updates and str(updates["id"]) != str(current.get("id")):
        msg = (
            f"deployment id {updates['id']!r} differs from the file's id "
            f"{current.get('id')!r}; the file name and conversion record are bound to "
            "the id, so convert again (process) to change it."
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
    record_attribute_sources(attrs, updates, "enriched")
    record_attribute_sources(attrs, ["date_modified", "tracking_id"], "derived")
    with netCDF4.Dataset(path, "a") as nc:
        for key, value in attrs.items():
            if key not in current or current[key] is not value:
                nc.setncattr(key, value)

    record_file = conversion_path(path, ".json")
    if record_file.is_file():
        try:
            contents = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.warn(
                f"{record_file.name} could not be read ({exc}); not rebound.",
                stacklevel=2,
            )
        else:
            write_record(path, attrs, contents)
    _log.info("enriched %s: %s", path, sorted(updates))
    return path


def _load_mission(config: str | Path) -> dict:
    """Read a mission configuration for :func:`enrich`, without validating ``raw_dir``.

    enrich edits a written file and only reads the config's global-attribute sections,
    so it must not require the (possibly moved) raw-data directory to still exist.
    """
    return _mission._load_raw(Path(config))


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


# --- deprecated v0.0.2 names (removed in 0.3.0; see seagliderOG1._deprecated) ----------
from seagliderOG1 import _deprecated  # noqa: E402  # shim follows the definitions above

save_dataset = _deprecated.save_dataset
