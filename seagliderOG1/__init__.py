"""Convert Seaglider basestation NetCDF files to OG1-format NetCDF.

The public API is a small set of verbs, re-exported here:

- :func:`read` — read a mission directory of basestation files into datasets.
- :func:`convert` — convert those datasets to one OG1 dataset.
- :func:`write` — write an OG1 dataset to a compressed NetCDF file.
- :func:`report` — write the HTML conversion page for a written file.
- :func:`enrich` — set global attributes on a written file, in place.
- :func:`process` — load a mission configuration and run read + convert + write.
- :func:`process_missions` — the same across a root of several missions.
- :mod:`seagliderOG1.mission` — load and check a ``mission.yaml`` (``mission.load`` /
  ``mission.check``).

plus the exceptions :class:`MissionError`, :class:`MetadataError` and :class:`UnitsError`.

The verbs are re-exported lazily (on first access) so that ``import seagliderOG1``
stays free of xarray and matplotlib until a verb that needs them is used.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("seagliderOG1")
except PackageNotFoundError:  # not installed (e.g. a source tree without a build)
    __version__ = "unknown"

__all__ = [
    "MetadataError",
    "MissionError",
    "UnitsError",
    "__version__",
    "convert",
    "enrich",
    "mission",
    "process",
    "process_missions",
    "read",
    "report",
    "write",
]

# Which module each public name is re-exported from, resolved on first access so that
# importing the package does not import the heavy conversion/report stack.
_SOURCES = {
    "convert": "seagliderOG1._convert",
    "process": "seagliderOG1._convert",
    "process_missions": "seagliderOG1._convert",
    "read": "seagliderOG1.readers",
    "write": "seagliderOG1.writers",
    "enrich": "seagliderOG1.writers",
    "report": "seagliderOG1.reports",
    "MetadataError": "seagliderOG1.exceptions",
    "MissionError": "seagliderOG1.exceptions",
    "UnitsError": "seagliderOG1.exceptions",
}


def __getattr__(name: str) -> object:
    """Resolve a public verb or exception from its module on first access.

    Parameters
    ----------
    name : str
        The attribute being looked up.

    Returns
    -------
    object
        The re-exported function, module or exception.

    Raises
    ------
    AttributeError
        If ``name`` is not part of the public API.

    """
    import importlib

    if name == "mission":
        return importlib.import_module("seagliderOG1.mission")
    source = _SOURCES.get(name)
    if source is not None:
        return getattr(importlib.import_module(source), name)
    msg = f"module 'seagliderOG1' has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    """Return the public names, so tab-completion and ``dir()`` show the verb set."""
    return sorted(__all__)
