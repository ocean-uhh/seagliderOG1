"""Tombstone for the v0.0.2 ``convertOG1`` module, kept for one release (removed in 0.3.0).

Importing it warns; the conversion lives in the top-level verbs now
(:func:`seagliderOG1.convert`, :func:`seagliderOG1.process`). This is the one module named
for a verb — a tombstone, not a module. ``convert_to_OG1`` and ``apply_keep_variables`` still
work and warn; ``process_and_save_data`` and ``standardise_OG10`` raise with a message (their
package-default identity and the internal mapping step are not public replacements).
"""

import warnings

from seagliderOG1 import _deprecated
from seagliderOG1._deprecated import SeagliderDeprecationWarning

__all__: list[str] = []

warnings.warn(
    "the seagliderOG1.convertOG1 module is deprecated and will be removed in 0.3.0; "
    "use the top-level verbs seagliderOG1.convert / seagliderOG1.process. "
    f"See the migration guide: {_deprecated._URL}",
    SeagliderDeprecationWarning,
    stacklevel=2,
)

# Re-export the tier-B adapter under its old module name (calling it warns).
convert_to_OG1 = _deprecated.convert_to_OG1


def apply_keep_variables(ds: object, keep: list[str]) -> object:
    """Subset to a keep-list; deprecated alias of the ``keep_variables`` helper, removed in 0.3.0."""
    _deprecated._warn("convertOG1.apply_keep_variables", "seagliderOG1 keep_variables")
    from seagliderOG1 import _convert

    return _convert.keep_variables(ds, keep)


# Tier C: removed names raise at attribute access with the migration message.
_REMOVED = {
    "process_and_save_data": (
        "it filled platform, contributor and institution metadata from package defaults, "
        "which were removed so no file is written with someone else's identity. Use a "
        "mission.yaml: 'seagliderOG1 init out.yaml --raw-dir DIR', fill it, then "
        "seagliderOG1.process('out.yaml')."
    ),
    "standardise_OG10": (
        "the OG1 name/attribute/unit step is internal to seagliderOG1.convert since 0.1.0; "
        "call seagliderOG1.convert."
    ),
}


def __getattr__(name: str) -> object:
    """Raise for a removed v0.0.2 ``convertOG1`` name, else the normal AttributeError."""
    if name in _REMOVED:
        _deprecated._removed(f"convertOG1.{name}", _REMOVED[name])
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
