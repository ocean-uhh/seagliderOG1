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

__all__: list[str] = []

_VERSION = "0.3.0"
_URL = "https://ocean-uhh.github.io/seagliderOG1/migrating_0_1_0.html"


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

            with xr.open_dataset(data, engine="netcdf4", decode_timedelta=False) as ds:
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
        The converted dataset and its data-variable names.

    """
    _warn("convertOG1.convert_to_OG1", "seagliderOG1.convert")
    import xarray as xr

    from seagliderOG1 import convert

    datasets = [ds_or_list] if isinstance(ds_or_list, xr.Dataset) else list(ds_or_list)
    contributors, institutions = _split_contrib_to_append(contrib_to_append)
    ds = convert(datasets, contributors=contributors, institutions=institutions)
    return ds, list(ds.data_vars)


def _split_contrib_to_append(contrib: object) -> tuple:
    """Translate the v0.0.2 ``contrib_to_append`` into ``(contributors, institutions)`` records.

    A list of records passes through as ``contributors``. The flat dict form (the keys of
    the deleted ``OG1_author.yaml``) maps ``contributor_*`` to one contributor record and
    ``contributing_institutions*`` to one institution record; ``*_vocabulary`` keys are
    dropped (the converter writes them). Any other key raises, showing the records built so
    the caller sees the new shape.
    """
    if contrib is None:
        return None, None
    if isinstance(contrib, (list, tuple)):
        return list(contrib), None
    if not isinstance(contrib, dict):
        msg = f"contrib_to_append must be a dict or a list of records, not {type(contrib).__name__}."
        raise TypeError(msg)
    person = {
        "name": contrib.get("contributor_name"),
        "email": contrib.get("contributor_email"),
        "role": contrib.get("contributor_role"),
    }
    institution = {
        "name": contrib.get("contributing_institutions"),
        "role": contrib.get("contributing_institutions_role"),
    }
    known = {
        "contributor_name",
        "contributor_email",
        "contributor_role",
        "contributing_institutions",
        "contributing_institutions_role",
    }
    extra = [
        key for key in contrib if key not in known and not key.endswith("_vocabulary")
    ]
    if extra:
        contributors = (
            [{k: v for k, v in person.items() if v}] if person.get("name") else []
        )
        institutions = (
            [{k: v for k, v in institution.items() if v}]
            if institution.get("name")
            else []
        )
        msg = (
            f"contrib_to_append keys {extra} have no place in the new contributors/institutions "
            f"records; pass contributors={contributors} and institutions={institutions} to "
            "seagliderOG1.convert instead."
        )
        raise ValueError(msg)
    contributors = (
        [{k: v for k, v in person.items() if v}] if person.get("name") else None
    )
    institutions = (
        [{k: v for k, v in institution.items() if v}]
        if institution.get("name")
        else None
    )
    return contributors, institutions


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


def load_sample_dataset(dataset_name: object = None) -> object:  # noqa: ARG001  # kept for v0.0.2 signature compatibility; the online registry is gone, so it is ignored
    """Return the bundled sample; deprecated alias of ``readers.load_sample_basestation``.

    v0.0.2 fetched ``dataset_name`` from an online pooch registry; that registry was removed,
    so this returns the bundled sg005 sample regardless of ``dataset_name`` (read your own
    file with :func:`seagliderOG1.readers.read_file` for anything else).

    Parameters
    ----------
    dataset_name : object, optional
        Ignored; accepted for signature compatibility.

    Returns
    -------
    xarray.Dataset
        The bundled sample dataset.

    """
    _warn(
        "readers.load_sample_dataset",
        "seagliderOG1.readers.load_sample_basestation (the bundled sample; the online "
        "pooch registry was removed — use readers.read_file for your own file)",
    )
    from seagliderOG1 import readers

    return readers.load_sample_basestation()
