"""One-release shims for the v0.0.2 names the 0.1.0 API break renamed or removed.

Every public name that existed in v0.0.2 and not in 0.1.0 is kept for one release. A
renamed name (tiers A/B) stays importable, delegates to the new name, and warns once with
:class:`SeagliderDeprecationWarning`; a removed name (tier C) raises with a message that
points at the migration guide. All of it goes in 0.3.0.

The shims are category-gated, not message- or module-gated: ``pyproject.toml`` has
``filterwarnings = ["error::seagliderOG1._deprecated.SeagliderDeprecationWarning"]``, so the
suite fails if the package ever calls its own shims, while third-party ``DeprecationWarning``s
stay warnings. The module is kept import-light (the delegatees are imported inside the
wrappers) so resolving that filter category does not pull in xarray.
"""

import os
import warnings
from collections.abc import Mapping

__all__: list[str] = []

_VERSION = "0.3.0"
_URL = "https://ocean-uhh.github.io/seagliderOG1/migrating_0_1_0.html"

# The pre-0.1.0 names that stay importable and warn (tiers A/B), bare names only. The one
# list the public-API guard reads (so it cannot drift from a hand-kept copy); the module
# bottoms bind these to _renamed/convert_to_OG1/save_dataset wrappers. ``show_*`` are NOT
# here — they are real 0.1.0 public names that merely regained a path argument.
# 0.3.0 removal deletes: this module, convertOG1.py, and the "deprecated" block at the
# bottom of readers/writers/tools/contributors/plotters/vocabularies.
SHIM_NAMES = frozenset(
    {
        "load_basestation_files",
        "load_first_basestation_file",
        "scan_and_repair_files",
        "repair_netcdf_time_metadata_inplace",
        "profnum_from_filename",
        "glider_sn_from_filename",
        "load_sample_dataset",
        "save_dataset",
        "calc_Z",
        "assign_phase",
        "assign_profile_number",
        "reformat_units_str",
        "reformat_units_var",
        "convert_units_var",
        "registry_institutions",
        "normalize_orcid",
        "normalize_role",
    }
)


class SeagliderDeprecationWarning(DeprecationWarning):
    """A seagliderOG1 name deprecated in 0.1.0 and removed in 0.3.0."""


def _warn(old: str, new: str) -> None:
    """Emit the one-shape deprecation warning pointing ``old`` at ``new``."""
    warnings.warn(
        f"{old} is deprecated and will be removed in {_VERSION}; use {new}. "
        f"See the migration guide: {_URL}",
        SeagliderDeprecationWarning,
        stacklevel=3,
    )


def _renamed(func: object, old: str, new: str) -> object:
    """Return a wrapper that warns ``old`` → ``new`` and delegates to ``func`` unchanged.

    Parameters
    ----------
    func : callable
        The new function to delegate to (resolved at assignment time).
    old : str
        The fully-qualified v0.0.2 name, for the warning.
    new : str
        The fully-qualified 0.1.0 name, for the warning.

    Returns
    -------
    callable
        A wrapper with ``func``'s behaviour that warns once per call.

    """

    def wrapper(*args: object, **kwargs: object) -> object:
        _warn(old, new)
        return func(*args, **kwargs)

    wrapper.__name__ = old.rsplit(".", 1)[-1]
    wrapper.__qualname__ = wrapper.__name__
    wrapper.__doc__ = f"Deprecated alias of ``{new}``; removed in {_VERSION}."
    return wrapper


def _accept_path(func: object, name: str) -> object:
    """Wrap a ``plotters.show_*`` so a str/Path first argument is opened (warns) then passed.

    In v0.0.2 the ``show_*`` functions accepted a file path or a dataset; 0.1.0 takes a
    dataset only. The wrapper restores the path branch for one release.

    Parameters
    ----------
    func : callable
        The 0.1.0 ``show_*`` function (dataset only).
    name : str
        Its bare name, for the warning.

    Returns
    -------
    callable
        A wrapper that opens a path argument, warns, and delegates.

    """

    def wrapper(data: object, *args: object, **kwargs: object) -> object:
        if isinstance(data, (str, os.PathLike)):
            _warn(
                f"plotters.{name}(path)",
                f"plotters.{name}(dataset) — open the file yourself with "
                'xr.open_dataset(path, engine="netcdf4")',
            )
            import xarray as xr

            # decode_cf=False keeps units/calendar on the variables (not moved to
            # .encoding), so show_* reports the same attributes v0.0.2's raw read did.
            with xr.open_dataset(
                data, engine="netcdf4", decode_cf=False, decode_timedelta=False
            ) as ds:
                return func(ds, *args, **kwargs)
        return func(data, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__doc__ = f"{name}; a path argument is deprecated (open it yourself), removed in {_VERSION}."
    return wrapper


def _removed(qualname: str, reason: str) -> None:
    """Raise ``AttributeError`` for a tier-C name, naming why and what replaces it.

    Called from a module ``__getattr__`` so ``from seagliderOG1.tools import X`` fails at
    import with the message, the earliest possible point.

    Parameters
    ----------
    qualname : str
        The fully-qualified removed name.
    reason : str
        What to use instead (the migration guide's wording for this name).

    Raises
    ------
    AttributeError
        Always.

    """
    msg = f"{qualname} was removed in seagliderOG1 0.1.0: {reason} See {_URL}"
    raise AttributeError(msg)


def install_removed(module_globals: dict, removed: dict[str, str]) -> None:
    """Install a module ``__getattr__`` that raises for each tier-C removed name.

    The one mechanism behind every removed name: call it at a module's bottom,
    ``_deprecated.install_removed(globals(), {name: reason})``. A removed name raises
    :func:`_removed` (an ``AttributeError`` naming why and the replacement); any other
    missing name gets the ordinary module ``AttributeError``.

    Parameters
    ----------
    module_globals : dict
        The calling module's ``globals()``.
    removed : dict of str to str
        Removed name to the reason/replacement wording for its error.

    """
    full = module_globals["__name__"]
    short = full.rsplit(".", 1)[-1]

    def __getattr__(name: str) -> object:
        if name in removed:
            _removed(f"{short}.{name}", removed[name])
        msg = f"module {full!r} has no attribute {name!r}"
        raise AttributeError(msg)

    module_globals["__getattr__"] = __getattr__


# --- tier B adapters (delegate, reshape, warn) -------------------------------


def convert_to_OG1(ds_or_list: object, contrib_to_append: dict | None = None) -> tuple:
    """Return the old ``(ds, var_list)`` tuple; deprecated alias of :func:`seagliderOG1.convert`.

    Parameters
    ----------
    ds_or_list : xarray.Dataset or sequence of xarray.Dataset
        One dataset or a sequence; a single dataset is wrapped as ``[ds]``.
    contrib_to_append : dict or None, optional
        The v0.0.2 flat OG1-attribute dict (the shape of the deleted ``OG1_author.yaml``),
        translated to one ``contributors`` and one ``institutions`` record; or a list of
        records, passed through.

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        The converted dataset and, as v0.0.2 returned, the sorted union of the input
        basestation variable names (coordinates included).

    """
    _warn("convertOG1.convert_to_OG1", "seagliderOG1.convert")
    import xarray as xr

    from seagliderOG1 import convert

    if isinstance(ds_or_list, xr.Dataset):
        datasets = [ds_or_list]
    elif isinstance(ds_or_list, str | bytes | Mapping) or not hasattr(
        ds_or_list, "__iter__"
    ):
        msg = "convert_to_OG1 takes a Dataset or a sequence of Datasets."
        raise TypeError(msg)
    else:
        datasets = list(ds_or_list)
    contributors, institutions = _split_contrib_to_append(contrib_to_append)
    ds = convert(datasets, contributors=contributors, institutions=institutions)
    # v0.0.2's second return was the union of the INPUT basestation variable names (not
    # the OG1 output names); reproduce it so an old caller indexing by it still works.
    var_list = sorted({str(name) for d in datasets for name in d.variables})
    return ds, var_list


def _split_contrib_to_append(contrib: object) -> tuple:
    """Translate the v0.0.2 ``contrib_to_append`` into ``(contributors, institutions)`` records.

    A list of records passes through as ``contributors``. The flat dict form (the keys of
    the deleted ``OG1_author.yaml``) maps ``contributor_*`` to contributor records and
    ``contributing_institutions*`` to institution records. v0.0.2's comma convention is
    honoured: a comma-joined ``contributor_name`` splits into one record per name, and a
    comma-joined ``role`` / ``email`` with the same count is paired positionally (a single
    value applies to all). ``*_vocabulary`` keys are dropped (the converter writes them).
    Anything that cannot be mapped unambiguously — an unknown key, a value with no name, a
    count mismatch — raises showing the records it would have built; nothing is dropped.
    """
    if contrib is None:
        return None, None
    if isinstance(contrib, (list, tuple)):
        return list(contrib), None
    if not isinstance(contrib, dict):
        msg = f"contrib_to_append must be a dict or a list of records, not {type(contrib).__name__}."
        raise TypeError(msg)
    known = {
        "contributor_name",
        "contributor_email",
        "contributor_role",
        "contributing_institutions",
        "contributing_institutions_role",
    }
    problems = [
        key for key in contrib if key not in known and not key.endswith("_vocabulary")
    ]
    contributors = _records(
        contrib,
        "contributor_name",
        {"email": "contributor_email", "role": "contributor_role"},
        problems,
    )
    institutions = _records(
        contrib,
        "contributing_institutions",
        {"role": "contributing_institutions_role"},
        problems,
    )
    if problems:
        msg = (
            f"contrib_to_append {problems} cannot be mapped to the new records; pass "
            f"contributors={contributors or []} and institutions={institutions or []} to "
            "seagliderOG1.convert instead."
        )
        raise ValueError(msg)
    return contributors, institutions


def _records(
    contrib: dict, name_key: str, extra_keys: dict[str, str], problems: list
) -> list | None:
    """Build one record per comma-split name, pairing each extra field positionally.

    Parameters
    ----------
    contrib : dict
        The v0.0.2 flat dict.
    name_key : str
        The key holding the (possibly comma-joined) name(s).
    extra_keys : dict of str to str
        Record-field name to the flat dict key holding its (possibly comma-joined) value(s).
    problems : list
        Appended to (in place) with a message for each value that cannot be mapped.

    Returns
    -------
    list of dict or None
        One record per name, or None when no name is given.

    """
    name = contrib.get(name_key)
    extras = {field: contrib.get(key) for field, key in extra_keys.items()}
    if not name:
        if any(v is not None for v in extras.values()):
            problems.append(f"{'/'.join(extra_keys.values())} without {name_key}")
        return None
    names = [part.strip() for part in str(name).split(",")]
    records: list[dict] = [{"name": n} for n in names]
    for field, value in extras.items():
        if value is None:
            continue
        parts = [part.strip() for part in str(value).split(",")]
        if len(parts) == 1:
            for record in records:
                record[field] = parts[0]
        elif len(parts) == len(names):
            for record, part in zip(records, parts, strict=True):
                record[field] = part
        else:
            problems.append(
                f"{name_key} has {len(names)} names but {extra_keys[field]} has "
                f"{len(parts)} values"
            )
    return records


def save_dataset(ds: object, output_file: str | os.PathLike | None = None) -> bool:
    """Write via :func:`seagliderOG1.write`; deprecated, and ``output_file`` is now required.

    The v0.0.2 default path (``../test.nc``) is not reproduced — a shim that writes a file
    unasked is the silent default the release removed on purpose.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to write.
    output_file : str or os.PathLike
        Where to write it; required (no default).

    Returns
    -------
    bool
        True when written.

    """
    _warn("writers.save_dataset", "seagliderOG1.write")
    if output_file is None:
        msg = (
            "writers.save_dataset no longer defaults output_file to '../test.nc'; "
            "give a path: seagliderOG1.write(ds, path, overwrite=True)."
        )
        raise TypeError(msg)
    from seagliderOG1 import writers

    writers.write(ds, output_file, overwrite=True)
    return True


def reformat_units_str(old_unit: str) -> str:
    """Return the canonical spelling of ``old_unit``; deprecated, resolve through the view.

    The three ad-hoc unit tables are gone; a units spelling now resolves through
    :data:`seagliderOG1.vocabularies.UNITS` over the vendored family tables. This returns the
    canonical spelling that view gives (an unrecognised spelling is returned unchanged). The old
    ``unit_format`` dict argument is gone with ``vocabularies.unit_str_format``. Removed in 0.3.0.

    Parameters
    ----------
    old_unit : str
        The units string to normalise.

    Returns
    -------
    str
        The canonical spelling, or ``old_unit`` unchanged when the view does not recognise it.

    """
    _warn("tools.reformat_units_str", "the units view seagliderOG1.vocabularies.UNITS")
    from seagliderOG1 import vocabularies
    from seagliderOG1.reports._vendored import units as _units

    return _units.resolve_units(old_unit, tables=vocabularies.UNITS)[0]


def reformat_units_var(ds: object, var_name: str) -> str:
    """Return the canonical spelling of a variable's units; deprecated. Removed in 0.3.0.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset holding the variable.
    var_name : str
        The variable whose ``units`` attribute is normalised.

    Returns
    -------
    str
        The canonical spelling of the variable's units (unchanged when unrecognised).

    """
    _warn("tools.reformat_units_var", "the units view seagliderOG1.vocabularies.UNITS")
    from seagliderOG1 import vocabularies
    from seagliderOG1.reports._vendored import units as _units

    return _units.resolve_units(ds[var_name].attrs["units"], tables=vocabularies.UNITS)[
        0
    ]


def convert_units_var(var_values: object, current_unit: str, new_unit: str) -> tuple:
    """Convert values between two spellings the view relates; deprecated. Removed in 0.3.0.

    Both spellings resolve through :data:`seagliderOG1.vocabularies.UNITS`; when they share a
    canonical, the ratio of their factors converts ``current_unit`` into ``new_unit``. A pair the
    view cannot relate raises :class:`seagliderOG1.exceptions.UnitsError` — the v0.0.2 silent
    pass-through of an unknown pair is the behaviour being removed. The conversion pipeline itself
    no longer calls this; it resolves units in :func:`seagliderOG1.convert`.

    Parameters
    ----------
    var_values : numpy.ndarray or float
        The values to convert.
    current_unit : str
        The units the values are in.
    new_unit : str
        The units to convert to.

    Returns
    -------
    tuple of (numpy.ndarray or float, str)
        The converted values and the canonical spelling of ``new_unit``.

    Raises
    ------
    seagliderOG1.exceptions.UnitsError
        When the two spellings do not resolve to the same canonical unit.

    """
    _warn(
        "tools.convert_units_var",
        "seagliderOG1.convert (units resolve through vocabularies.UNITS)",
    )
    from seagliderOG1 import vocabularies
    from seagliderOG1.exceptions import UnitsError
    from seagliderOG1.reports._vendored import units as _units

    factor = vocabularies.unit_factor(current_unit, new_unit)
    if factor is None:
        msg = (
            f"convert_units_var cannot relate {current_unit!r} to {new_unit!r} through "
            "vocabularies.UNITS: they resolve to different canonical units (or the "
            "spelling is unknown)."
        )
        raise UnitsError(msg)
    return var_values * factor, _units.resolve_units(
        new_unit, tables=vocabularies.UNITS
    )[0]
