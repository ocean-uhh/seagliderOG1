"""Tombstone for the v0.0.2 ``convertOG1`` module, kept for one release (removed in 0.3.0).

The conversion lives in the top-level verbs now (:func:`seagliderOG1.convert`,
:func:`seagliderOG1.process`). ``convert_to_OG1`` and ``apply_keep_variables`` still work and
warn **on use**; ``process_and_save_data`` and ``standardise_OG10`` raise with a message.
Importing the module is silent — so a downstream ``-W error::DeprecationWarning`` can still
import it — and each name warns or raises only when it is used.
"""

from seagliderOG1 import _deprecated

__all__: list[str] = []

# Re-export the tier-B adapter under its old module name (calling it warns).
convert_to_OG1 = _deprecated.convert_to_OG1


def apply_keep_variables(ds: object, keep: list[str]) -> object:
    """Subset to a keep-list; deprecated alias of the ``keep_variables`` helper, removed in 0.3.0."""
    _deprecated._warn("convertOG1.apply_keep_variables", "seagliderOG1 keep_variables")
    from seagliderOG1 import _convert

    return _convert.keep_variables(ds, keep)


_deprecated.install_removed(
    globals(),
    {
        "process_and_save_data": (
            "it filled platform, contributor and institution metadata from package "
            "defaults, which were removed so no file is written with someone else's "
            "identity. Use a mission.yaml: 'seagliderOG1 init out.yaml --raw-dir DIR', "
            "fill it, then seagliderOG1.process('out.yaml')."
        ),
        "standardise_OG10": (
            "the OG1 name/attribute/unit step is internal to seagliderOG1.convert since "
            "0.1.0; call seagliderOG1.convert."
        ),
    },
)
