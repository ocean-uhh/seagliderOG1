"""seagliderOG1's owned report design: the package accent and inventory-table config.

The single owned file that configures the vendored report layer for seagliderOG1 — the
vendored modules under ``reports/_vendored/`` name no package. The package accent is
applied to the shared CSS generator here; change :data:`PACKAGE_ACCENT` to rebrand.
"""

from seagliderOG1.reports._vendored.css import emit_css

#: seagliderOG1's package accent — one line to rebrand; any CSS colour value works.
#: Points at the vendored palette's ``--ocean`` (shared with ctdcast) until seagliderOG1
#: picks its own.
PACKAGE_ACCENT: str = "var(--ocean)"

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block, with two
#: owned interim rules both removed at the next re-vendor:
#: ``.var-qc`` makes the inline ``(_QC)`` marker green (the family default) rather than the grey
#: this vendored ``css.py`` still emits — gone when the vendored ``--qc-mark`` token carries it;
#: ``.var-table td:first-child code`` puts a renamed variable's original name on its own line
#: above the ``→ new name`` so the Variable column stays narrow — gone when F28 lands the
#: ``var-orig`` span in the vendored ``name_cell``.
SHARED_CSS: str = (
    emit_css(PACKAGE_ACCENT)
    + "\n.var-qc { color: var(--ok); }"
    + "\n.var-table td:first-child code { display: block; }\n"
)

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


#: seagliderOG1's own global-attribute names placed *into* the five vendored convention
#: groups (:data:`~seagliderOG1.reports._vendored.nc_tables.ATTR_GROUPS`) by meaning, not by
#: OG1 requirement tier — so the grouped-globals table shows those five groups and no more.
#: Passed as the ``extras`` of :func:`~seagliderOG1.reports._vendored.nc_tables.globals_rows`;
#: a name already in a vendored group may be repeated here harmlessly. The requirement tier is
#: shown separately (a summary caption now, a column once F29 vendors it), not as groups.
ATTR_GROUP_EXTRAS: dict[str, tuple[str, ...]] = {
    "Identity & discovery": (
        "internal_mission_identifier",
        "site",
        "site_vocabulary",
        "program",
        "program_vocabulary",
        "network",
        "uri",
        "web_link",
        "data_url",
        "summary",
        "uuid",
        "id",
        "keywords",
        "keywords_vocabulary",
    ),
    "People & institutions": (
        "contributor_id",
        "contributor_role_vocabulary",
        "contributing_institutions_vocabulary",
        "contributor_email",
    ),
    "Rights & access": (
        "doi",
        "license",
        "disclaimer",
        "acknowledgment",
    ),
    "Provenance & processing": (
        "rtqc_method",
        "rtqc_method_doi",
        "start_date",
        "date_created",
        "date_modified",
        "comment",
        "base_station_version",
        "seaglider_software_version",
        "file_version",
        "conversion_dimensions",
        "conversion_derived_variables",
        "conversion_dropped_variables",
        "conversion_removed_variables",
        "conversion_input_variable_count",
    ),
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
