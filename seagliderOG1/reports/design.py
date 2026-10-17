"""seagliderOG1's owned report design: the package accent and inventory-table config.

The single owned file that configures the vendored report layer for seagliderOG1 — the
vendored modules under ``reports/_vendored/`` name no package. The package accent is
applied to the shared CSS generator here; change :data:`PACKAGE_ACCENT` to rebrand.
"""

from seagliderOG1 import vocabularies
from seagliderOG1.reports._vendored.css import emit_css
from seagliderOG1.reports._vendored.nc_tables import (
    ATTR_GROUPS as _VENDORED_ATTR_GROUPS,
)

#: seagliderOG1's package accent — one line to rebrand; any CSS colour value works.
#: Points at the vendored palette's ``--ocean`` (shared with ctdcast) until seagliderOG1
#: picks its own.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css(PACKAGE_ACCENT)

#: The per-figure ``source:`` caption is on (kept on for debugging).
FIGURE_SOURCE: bool = True

#: Attribute names, in priority order, that record a variable's source name for the
#: ``original -> name`` cell. seagliderOG1 writes only the family-shared spelling.
ORIGINAL_NAME_ATTRS: tuple[str, ...] = ("original_name",)


def is_qc(name: str) -> bool:
    """Return True when ``name`` is an OG1 QC variable (ends with ``_QC``).

    Parameters
    ----------
    name : str
        A variable name.

    Returns
    -------
    bool
        True for a QC variable.

    """
    return name.endswith("_QC")


def is_sensor(name: str) -> bool:
    """Return True when ``name`` is an OG1 sensor variable (starts with ``SENSOR_``).

    Parameters
    ----------
    name : str
        A variable name.

    Returns
    -------
    bool
        True for a sensor variable.

    """
    return name.startswith("SENSOR_")


#: OG1 global-attribute tier groups (membership only) for the grouped-globals table,
#: from the one requirement table :data:`seagliderOG1.vocabularies.REQUIRED_GLOBALS`,
#: minus any name a vendored convention group already carries — so the two cannot drift.
_VENDORED_ATTR_NAMES: frozenset[str] = frozenset(
    name for _title, names in _VENDORED_ATTR_GROUPS for name in names
)
_TIER_TITLES: dict[str, str] = {
    "mandatory": "OG1 mandatory",
    "highly_desirable": "OG1 highly desirable",
    "suggested": "OG1 suggested",
}
ATTR_GROUP_EXTRAS: dict[str, tuple[str, ...]] = {
    _TIER_TITLES[tier]: tuple(
        name for name in names if name not in _VENDORED_ATTR_NAMES
    )
    for tier, names in vocabularies.REQUIRED_GLOBALS.items()
}

#: Tolerances for the inventory page's coverage check (file-stated ``geospatial_*`` /
#: ``time_coverage_*`` versus the values recomputed from the data): degrees for lat/lon,
#: metres for the vertical axis, seconds for time.
COVERAGE_TOLERANCE: dict[str, float] = {
    "lat": 1e-3,
    "lon": 1e-3,
    "vertical": 1.0,
    "time": 1.0,
}

#: Per-table-kind column widths (``{"variables": [...], ...}``); empty lets the browser
#: lay every table out. Deferred until a column misbehaves.
TABLE_WIDTHS: dict[str, list[str]] = {}
