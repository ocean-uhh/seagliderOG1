"""Mission-configuration schema, loader and validator.

The mission configuration (``mission.yaml``) lives outside the installed package
so that platform, contributor and global-attribute metadata belong to the user
rather than to seagliderOG1. This module holds the known keys, the validation
checks, and the two public entry points a caller needs:

- :func:`load` reads a ``mission.yaml`` (or an already-loaded mapping), validates
  it, resolves ``raw_dir`` / ``output_dir`` relative to the file, and returns the
  configuration with the file's own keys (the three global-attribute sections
  left unmerged).
- :func:`check` returns the list of validation issues without raising, for the
  ``validate`` verb to print.

It is the single place that parses a mission configuration. The commented
template that ``init`` writes, and the printing of issues, stay in the CLI
(``cli/_mission.py``), which imports the schema tables from here.

Kept import-light on purpose (module-level imports are the standard library and
``yaml`` only); ``readers``, ``vocabularies`` and ``contributors`` are imported
inside the functions that need them, so building the CLI parser and ``--help``
do not pull in xarray or the packaged-YAML reads.
"""

import logging
import os
import pathlib
from collections.abc import Mapping
from typing import NamedTuple

import yaml

from seagliderOG1.exceptions import MissionError

__all__ = [
    "ValidationIssue",
    "check",
    "global_rows",
    "load",
    "platform_rows",
    "select_missions",
]

logger = logging.getLogger(__name__)

KNOWN_KEYS = frozenset(
    {
        "config_version",
        "raw_dir",
        "source",  # deprecated name of raw_dir, read for one release
        "output_dir",
        "mode",
        "dives",
        "repair",
        "keep_variables",
        "report",
        "platform",
        "local_config",
        "identity_and_discovery",
        "rights_and_access",
        "provenance_and_processing",
        "global_attributes",
        "sensors",
        "contributors",
        "institutions",
    }
)
REQUIRED_KEYS = ("raw_dir",)

# The old name of raw_dir; read with a deprecation warning for one release.
DEPRECATED_KEYS = {"source": "raw_dir"}

# Keys whose value load() resolves to an absolute path relative to the config file.
# local_config is a path once the fleet-config overlay reads it; load resolves it now so
# that overlay needs no change (it is null until then, and a null is skipped here).
_PATH_KEYS = ("raw_dir", "output_dir", "local_config")

# The valid data modes, the platform defaults, and the required platform fields all
# derive from the one platform/mode table in ``vocabularies`` (imported lazily so the
# parser build and ``--help`` stay free of its import-time YAML reads).


class ValidationIssue(NamedTuple):
    """A single problem found in a mission configuration.

    Parameters
    ----------
    level : str
        Severity, either ``"ERROR"`` or ``"WARNING"``.
    message : str
        Human-readable description of the problem.
    key : str or None
        The configuration key the problem relates to, or None if general.

    """

    level: str
    message: str
    key: str | None


# --- reading and normalising -------------------------------------------------


def _read_yaml(config_path: pathlib.Path) -> dict:
    """Return the configuration mapping exactly as written in the file.

    Parameters
    ----------
    config_path : pathlib.Path
        Path to the ``mission.yaml`` file.

    Returns
    -------
    dict
        The parsed YAML mapping.

    Raises
    ------
    ValueError
        If the YAML root is not a mapping.

    """
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = "configuration root is not a mapping."
        # Malformed config input, not a programming type error; ValueError matches
        # readers.discover_missions' bad-input style and check() catches it.
        raise ValueError(msg)
    return data


def _normalise(data: dict) -> dict:
    """Return ``data`` with each deprecated key moved to its current name.

    Parameters
    ----------
    data : dict
        The configuration mapping as written.

    Returns
    -------
    dict
        A copy in which ``source`` is read as ``raw_dir``.

    Raises
    ------
    ValueError
        If a deprecated key and its replacement are both set.

    """
    data = dict(data)
    for old, new in DEPRECATED_KEYS.items():
        if old not in data:
            continue
        if new in data:
            msg = f"both {new!r} and its deprecated name {old!r} are set; keep {new!r}."
            raise ValueError(msg)
        data[new] = data.pop(old)
    return data


def _load_raw(config_path: pathlib.Path) -> dict:
    """Return the configuration mapping as written, deprecated keys normalised.

    The non-validating load behind :func:`check` and the CLI, which resolves ``raw_dir``
    / ``output_dir`` itself (so ``process --raw-dir`` can override). :func:`load` is the
    validating public loader. Reading a file as a mission configuration happens only in
    this module.

    Parameters
    ----------
    config_path : pathlib.Path
        Path to the ``mission.yaml`` file.

    Returns
    -------
    dict
        The parsed configuration, with the deprecated ``source`` read as ``raw_dir``.

    """
    return _normalise(_read_yaml(pathlib.Path(config_path)))


def _merge_sections(config: dict) -> dict:
    """Merge the three global-attribute sections into one ``deployment`` mapping.

    :func:`seagliderOG1.convert` and :func:`seagliderOG1.enrich` take a single
    ``deployment`` mapping; the mission file splits those globals across
    ``identity_and_discovery:``, ``rights_and_access:`` and
    ``provenance_and_processing:``. This flattens them back for the conversion
    engine, so the engine is unchanged by the schema's shape.

    Parameters
    ----------
    config : dict
        The parsed mission configuration.

    Returns
    -------
    dict
        The merged section mappings; empty when none are present.

    """
    from seagliderOG1 import vocabularies

    merged: dict = {}
    for slug in vocabularies.CONFIG_GLOBAL_SECTIONS:
        block = config.get(slug)
        if isinstance(block, dict):
            merged.update(block)
    return merged


def _check_global_keys(
    deployment: Mapping[str, object], global_attributes: Mapping[str, object]
) -> None:
    """Raise on a mission-config global the converter owns or that has another home.

    Shared by :func:`seagliderOG1.convert` and :func:`seagliderOG1.enrich`, so both
    agree on which globals the config may set. Only a real (non-null) value collides;
    a null is skipped, so a template that lists reserved keys as null still converts.

    Parameters
    ----------
    deployment : collections.abc.Mapping
        The deployment mapping (the three ``mission.yaml`` global-attribute sections merged).
    global_attributes : collections.abc.Mapping
        The ``global_attributes:`` block.

    Raises
    ------
    ValueError
        If ``global_attributes`` sets a converter-derived key or a key with a structured
        home in a global-attribute section, or the deployment mapping has an unknown key.

    """
    from seagliderOG1 import vocabularies

    derived = vocabularies.DERIVED_GLOBALS
    deployment_globals = vocabularies.DEPLOYMENT_GLOBALS
    set_globals = {k for k, v in global_attributes.items() if not _is_placeholder(v)}
    collisions = set(derived).intersection(set_globals)
    if collisions:
        msg = (
            "global_attributes may not set converter-derived keys: "
            f"{sorted(collisions)}. Remove them from the mission config."
        )
        raise ValueError(msg)
    structured = set(deployment_globals).intersection(set_globals)
    if structured:
        home = vocabularies.CONFIG_GLOBAL_HOME
        moves = "; ".join(f"{key} -> {home[key]}:" for key in sorted(structured))
        msg = (
            "global_attributes may not set keys that have a structured home in a "
            f"global-attribute section: move {moves}."
        )
        raise ValueError(msg)
    unknown_deployment = set(deployment) - set(deployment_globals)
    if unknown_deployment:
        msg = (
            f"deployment has unknown keys: {sorted(unknown_deployment)}. Allowed "
            f"keys are {list(deployment_globals)}; set anything else under "
            "global_attributes."
        )
        raise ValueError(msg)


def _package_version() -> str:
    """Return the installed seagliderOG1 version, or a placeholder when unknown."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("seagliderOG1")
    except PackageNotFoundError:
        return "(unknown version)"


# --- schema tables read by the template and the listings ---------------------

# OG1 requirement tiers as written in templates and listings.
_TIER_LABELS = {
    "mandatory": "mandatory",
    "highly_desirable": "highly desirable",
    "suggested": "suggested",
}

# Notes on deployment keys whose value overrides something the converter derives.
_DEPLOYMENT_HINTS = {
    "id": "leave null for the derived <serial>_<start>_<mode>; set only to override it",
    "naming_authority": "reverse-DNS of the institution naming the dataset, e.g. edu.ucsd.spray",
    "comment": "overrides a comment global the basestation files carry",
    "license": "e.g. CC-BY-4.0",
    "doi": "e.g. https://doi.org/...",
    "data_url": "where the OG1 file is hosted",
}


def _set_in(name: str, source: str) -> str:
    """Return the mission.yaml block a global is set in, or "" when the user does not set it.

    Parameters
    ----------
    name : str
        The OG1 global attribute name.
    source : str
        Its filling source from ``REQUIRED_GLOBALS``: ``derived``, ``constant`` or ``config``.

    Returns
    -------
    str
        the section slug (``identity_and_discovery`` / ``rights_and_access`` /
        ``provenance_and_processing``), ``contributors``, ``institutions`` or
        ``global_attributes``; "" for a derived or constant global that has no override.

    """
    from seagliderOG1 import vocabularies

    slug = vocabularies.CONFIG_GLOBAL_HOME.get(name)
    if slug is not None:
        return slug
    if source != "config":
        return ""
    if name.startswith("contributor_"):
        return "contributors"
    if name.startswith("contributing_institutions"):
        return "institutions"
    return "global_attributes"


def global_rows() -> list[dict[str, str]]:
    """Return one row per OG1 global the package knows a tier or a config home for.

    Every name in ``vocabularies.REQUIRED_GLOBALS``, in tier order, followed by the
    global-section keys with no OG1 tier (``license``, ``acknowledgment``), marked
    ``optional``. The single source for the global-section template comments, the
    ``validate`` highly-desirable check and ``list globals``.

    Returns
    -------
    list of dict of str to str
        Rows with keys ``name``, ``tier``, ``source`` (``derived`` / ``constant`` /
        ``config``), ``set_in`` (the mission.yaml block, or "") and ``note`` (what an
        override does, or "").

    """
    from seagliderOG1 import vocabularies

    rows = [
        {
            "name": name,
            "tier": _TIER_LABELS[tier],
            "source": source,
            "set_in": _set_in(name, source),
            "note": _DEPLOYMENT_HINTS.get(name, ""),
        }
        for tier, names in vocabularies.REQUIRED_GLOBALS.items()
        for name, source in names.items()
    ]
    tiered = {row["name"] for row in rows}
    rows.extend(
        {
            "name": name,
            "tier": "optional",
            "source": "config",
            "set_in": _set_in(name, "config"),
            "note": _DEPLOYMENT_HINTS.get(name, ""),
        }
        for name in vocabularies.DEPLOYMENT_GLOBALS
        if name not in tiered
    )
    return rows


# One hint per platform key, shown in the init template and by `list platform`.
_PLATFORM_HINTS = {
    "PLATFORM_SERIAL_NUMBER": "from platform_id; a serial or a local nickname",
    "PLATFORM_MODEL": "e.g. University of Washington Seaglider M1 glider",
    "platform_model_vocabulary": "e.g. https://vocab.nerc.ac.uk/collection/B76/current/B7600024/",
    "PLATFORM_DEPTH_RATING": "e.g. 1000 (metres)",
    "PLATFORM_MAKER": "e.g. University of Washington, School of Oceanography",
    "platform_maker_vocabulary": "e.g. https://vocab.nerc.ac.uk/collection/B75/current/ORG00142/",
    "GLIDER_FIRMWARE_VERSION": "from seaglider_software_version",
    "LANDSTATION_VERSION": "from base_station_version",
    "WMO_IDENTIFIER": "from wmo_identifier",
    "PLATFORM_NAME": "local or nickname of the glider",
    "TELECOM_TYPE": "e.g. Iridium (comma-separated for several)",
    "TRACKING_SYSTEM": "e.g. ARGOS, GPS",
    "BATTERY_TYPE": "see the OG1 battery_type vocabulary",
    "BATTERY_PACK": "battery packaging",
}

# The two _vocabulary keys are attributes on their parent variable, not variables.
_PLATFORM_VOCABULARY_PARENTS = {
    "platform_model_vocabulary": "PLATFORM_MODEL",
    "platform_maker_vocabulary": "PLATFORM_MAKER",
}

# Template order: each _vocabulary key follows its parent variable.
_PLATFORM_ORDER = (
    "PLATFORM_SERIAL_NUMBER",
    "PLATFORM_MODEL",
    "platform_model_vocabulary",
    "PLATFORM_DEPTH_RATING",
    "PLATFORM_MAKER",
    "platform_maker_vocabulary",
    "GLIDER_FIRMWARE_VERSION",
    "LANDSTATION_VERSION",
    "WMO_IDENTIFIER",
    "PLATFORM_NAME",
    "TELECOM_TYPE",
    "TRACKING_SYSTEM",
    "BATTERY_TYPE",
    "BATTERY_PACK",
)


def platform_rows() -> list[dict[str, str]]:
    """Return one row per ``platform:`` key, in template order.

    Read from ``vocabularies.PLATFORM_FIELDS`` (requirement, basestation source) plus
    the two ``_vocabulary`` keys, which are attributes on ``PLATFORM_MODEL`` /
    ``PLATFORM_MAKER``. The single source for the ``platform:`` template comments and
    ``list platform``.

    Returns
    -------
    list of dict of str to str
        Rows with keys ``key``, ``requirement`` (``required`` / ``optional``),
        ``destination`` (``variable`` or ``attribute on <VARIABLE>``), ``from_file``
        (the basestation global ``init --raw-dir`` reads, or "") and ``hint``.

    """
    from seagliderOG1 import vocabularies

    rows = []
    for key in _PLATFORM_ORDER:
        if key in _PLATFORM_VOCABULARY_PARENTS:
            requirement = "optional"
            destination = f"attribute on {_PLATFORM_VOCABULARY_PARENTS[key]}"
            from_file = ""
        else:
            spec = vocabularies.PLATFORM_FIELDS[key]
            requirement = "required" if spec.required else "optional"
            destination = "variable"
            from_file = spec.source or ""
        rows.append(
            {
                "key": key,
                "requirement": requirement,
                "destination": destination,
                "from_file": from_file,
                "hint": _PLATFORM_HINTS[key],
            }
        )
    return rows


# --- validation --------------------------------------------------------------


def _is_placeholder(value: object) -> bool:
    """Return True for a null or placeholder config value.

    Matches the converter's unset test (``vocabularies.PLACEHOLDER_VALUES``) so
    ``validate`` and :func:`seagliderOG1.convert` agree on what counts as missing — a
    value the converter would drop (``""``, ``"null"``, ``"null@null.com"``) is treated
    as unset here too, not reported as present.

    Parameters
    ----------
    value : object
        The value to test.

    Returns
    -------
    bool
        True when the value counts as unset.

    """
    from seagliderOG1 import vocabularies

    return vocabularies.is_placeholder(value)


def _case_hint(key: str, known: object) -> str | None:
    """Return the correctly-cased known key a mis-cased ``key`` matches, or None.

    OG1 keys are case-sensitive (UPPER names become variables, lower names become
    attributes or globals), and a mis-cased key would otherwise be silently ignored.
    This lets ``validate`` name the exact spelling instead of a bare "unknown key".

    Parameters
    ----------
    key : str
        The user's key.
    known : iterable of str
        The valid keys.

    Returns
    -------
    str or None
        The valid key that ``key`` matches case-insensitively (but not exactly), or
        None when there is no such match.

    """
    lowered = key.lower() if isinstance(key, str) else key
    for candidate in known:
        if candidate != key and candidate.lower() == lowered:
            return candidate
    return None


def _is_dive_pair(dives: object) -> bool:
    """Return True when ``dives`` is a two-element list of integers."""
    return (
        isinstance(dives, list)
        and len(dives) == 2
        and all(isinstance(d, int) for d in dives)
    )


def _check_name(name: object, where: str) -> list[ValidationIssue]:
    """Check a contributor/institution name is a non-empty, comma-free string."""
    if not isinstance(name, str) or not name.strip():
        return [ValidationIssue("ERROR", f"{where} needs a non-empty name.", where)]
    if "," in name:
        return [
            ValidationIssue(
                "ERROR",
                f"{where} name {name!r} contains a comma; commas separate entries, "
                "so write the name without one.",
                where,
            )
        ]
    return []


def _check_role(entry: dict, where: str) -> tuple[list[ValidationIssue], str | None]:
    """Check an entry's role, returning issues and the normalised role (or None).

    The first error wins per entry (no piling a second error on the same cause).
    ``role:`` and ``roles:`` together is an error; a single-element ``roles:`` is a
    warning to prefer ``role:``.
    """
    from seagliderOG1 import contributors, vocabularies

    role = entry.get("role")
    roles = entry.get("roles")
    if role is not None and roles is not None:
        return [
            ValidationIssue(
                "ERROR", f"{where} sets both role: and roles:; use one.", where
            )
        ], None

    warnings_found: list[ValidationIssue] = []
    if roles is not None:
        if not isinstance(roles, list) or len(roles) != 1:
            return [
                ValidationIssue(
                    "ERROR",
                    f"{where} roles: must be a single value; list the entry once per "
                    "role, or use role:.",
                    where,
                )
            ], None
        warnings_found.append(
            ValidationIssue(
                "WARNING", f"{where} uses roles:; prefer role: with one value.", where
            )
        )
        role = roles[0]

    if role in (None, ""):
        return [
            *warnings_found,
            ValidationIssue("ERROR", f"{where} needs a role.", where),
        ], None
    normalized = contributors.canonical_role(role)
    if normalized is None:
        allowed = ", ".join(vocabularies.ROLE_VOCABULARY)
        return [
            *warnings_found,
            ValidationIssue(
                "ERROR",
                f"{where} role {role!r} is not a W08 role (one of: {allowed}).",
                where,
            ),
        ], None
    return warnings_found, normalized


def _validate_people(
    contributors: object, key: str, required_role: str
) -> list[ValidationIssue]:
    """Validate a contributors/institutions block of name+role records.

    Parameters
    ----------
    contributors : object
        The value of the block (a list of mappings).
    key : str
        The config key, for messages (``"contributors"`` or ``"institutions"``).
    required_role : str
        A role at least one entry must carry (``"PI"`` or ``"Operator"``).

    Returns
    -------
    list of ValidationIssue
        Problems found.

    """
    if contributors in (None, [], ""):
        return [
            ValidationIssue(
                "ERROR",
                f"{key} must list at least one entry with role {required_role}.",
                key,
            )
        ]
    if not isinstance(contributors, list):
        return [ValidationIssue("ERROR", f"{key} must be a list.", key)]
    issues: list[ValidationIssue] = []
    has_required = False
    for index, entry in enumerate(contributors):
        where = f"{key}[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                ValidationIssue("ERROR", f"{where} must be a mapping.", where)
            )
            continue
        issues.extend(_check_name(entry.get("name"), where))
        role_issues, normalized = _check_role(entry, where)
        issues.extend(role_issues)
        if normalized == required_role:
            has_required = True
    if not has_required:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"{key} must include at least one entry with role {required_role}.",
                key,
            )
        )
    return issues


def _validate_sensors(sensors: object) -> list[ValidationIssue]:
    """Check the ``sensors:`` block shape: sensor key to a mapping of known fields.

    Whether a key names a sensor of the mission is checked at conversion, which reads
    the ``instrument`` global.

    Parameters
    ----------
    sensors : object
        The ``sensors`` value from the config (None when absent).

    Returns
    -------
    list of ValidationIssue
        One ERROR per malformed entry; empty when the block is absent or well formed.

    """
    from seagliderOG1 import vocabularies

    if sensors is None:
        return []
    if not isinstance(sensors, dict):
        return [ValidationIssue("ERROR", "sensors must be a mapping.", "sensors")]
    issues = []
    allowed = list(vocabularies.SENSOR_OVERRIDE_FIELDS)
    for key, fields in sensors.items():
        where = f"sensors.{key}"
        if not isinstance(fields, dict) or not fields:
            issues.append(
                ValidationIssue(
                    "ERROR", f"{where} must map fields {allowed} to values.", where
                )
            )
            continue
        for field, value in fields.items():
            if field not in allowed:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"{where}: unknown field {field!r}; allowed: {allowed}.",
                        where,
                    )
                )
            elif value is None or not str(value).strip():
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        f"{where}.{field} is empty; remove the line to keep the "
                        "basestation value.",
                        where,
                    )
                )
    return issues


def _validate_raw_dir(
    data: dict[str, object], base_dir: pathlib.Path, strict: bool
) -> list[ValidationIssue]:
    """Check that ``raw_dir`` exists, holds basestation files, and spans ``dives``.

    Parameters
    ----------
    data : dict of str to object
        The parsed configuration.
    base_dir : pathlib.Path
        Directory ``raw_dir`` resolves relative to (the config file's parent, or the
        current directory when loading an already-absolute mapping).
    strict : bool
        When True, every dive in the ``dives`` range must be present (no gaps).

    Returns
    -------
    list of ValidationIssue
        Problems found with the raw-data directory or the dive range.

    """
    raw_dir = data.get("raw_dir")
    if raw_dir in (None, ""):
        return []
    src = (base_dir / str(raw_dir)).resolve()
    if not src.exists():
        return [ValidationIssue("ERROR", f"raw_dir not found: {src}", "raw_dir")]

    from seagliderOG1 import readers

    try:
        missions = readers.discover_missions(str(src))
    except ValueError as exc:
        return [ValidationIssue("ERROR", f"raw_dir unreadable: {exc}", "raw_dir")]
    if not missions:
        return [
            ValidationIssue(
                "ERROR",
                "no basestation files (pSSSDDDD*.nc) under raw_dir "
                "(a mission directory, or a root of SN/DATE directories).",
                "raw_dir",
            )
        ]

    dives = data.get("dives")
    if not _is_dive_pair(dives):
        return []
    # The dive-range check applies to a single mission directory; under a root the
    # range is per mission and is not validated here.
    if readers.is_root(missions):
        return []
    present = missions[0].dives
    first, last = dives
    issues: list[ValidationIssue] = []
    if first < present[0] or last > present[-1]:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"dives {dives} outside files present [{present[0]}, {present[-1]}].",
                "dives",
            )
        )
    if strict:
        have = set(present)
        missing = [d for d in range(first, last + 1) if d not in have]
        if missing:
            issues.append(
                ValidationIssue("ERROR", f"dives missing in range: {missing}", "dives")
            )
    return issues


def _validate_platform(platform: object) -> list[ValidationIssue]:
    """ERROR on a null required platform field when a platform block is present.

    Parameters
    ----------
    platform : object
        The value of the ``platform`` key.

    Returns
    -------
    list of ValidationIssue
        One ERROR per null required field; empty when the block is absent or
        every required field is set.

    """
    if platform in (None, {}, ""):
        return []
    if not isinstance(platform, dict):
        return [ValidationIssue("ERROR", "platform must be a mapping.", "platform")]
    from seagliderOG1 import vocabularies

    # A null in a required field is a validate ERROR rather than a silent default
    # written into the output.
    required = [f for f, spec in vocabularies.PLATFORM_FIELDS.items() if spec.required]
    issues: list[ValidationIssue] = []
    for field in required:
        if _is_placeholder(platform.get(field)):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"platform.{field} is null; fill it (see the template '# e.g.' "
                    "comments) or run 'init --raw-dir DIR'.",
                    f"platform.{field}",
                )
            )
    # A mis-cased platform key (e.g. platform_model for PLATFORM_MODEL) is a loud
    # ERROR naming the exact spelling, not a silently-ignored key.
    known = (
        *vocabularies.PLATFORM_FIELDS,
        "platform_model_vocabulary",
        "platform_maker_vocabulary",
    )
    for key in platform:
        hint = _case_hint(key, known)
        if hint is not None:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"platform.{key} is not a key; the OG1 key is {hint!r} "
                    "(keys are case-sensitive).",
                    f"platform.{key}",
                )
            )
    return issues


def _validate_global_sections(data: dict[str, object]) -> list[ValidationIssue]:
    """ERROR on a non-mapping global-attribute section or a key in the wrong place.

    The three sections (``identity_and_discovery``, ``rights_and_access``,
    ``provenance_and_processing``) each hold a fixed set of OG1 globals
    (``vocabularies.CONFIG_GLOBAL_SECTIONS``). seagliderOG1 does not enforce OG1
    completeness (the external cc-plugin-og checker does), so a null global is not an
    error; a key in the wrong section, a converter-derived global, a platform variable,
    or an unknown name is, each refused with the reason and where it belongs.

    Parameters
    ----------
    data : dict of str to object
        The parsed configuration.

    Returns
    -------
    list of ValidationIssue
        Problems found; empty when the sections are absent or well-formed.

    """
    from seagliderOG1 import vocabularies

    sections = vocabularies.CONFIG_GLOBAL_SECTIONS
    home = vocabularies.CONFIG_GLOBAL_HOME
    platform_keys = set(_PLATFORM_ORDER)
    issues: list[ValidationIssue] = []
    for slug, keys in sections.items():
        block = data.get(slug)
        if block in (None, {}, ""):
            continue
        if not isinstance(block, dict):
            issues.append(ValidationIssue("ERROR", f"{slug} must be a mapping.", slug))
            continue
        allowed = set(keys)
        for key in block:
            if key in allowed:
                continue
            where = f"{slug}.{key}"
            if key in home:
                message = f"{key} belongs under {home[key]}:, not {slug}:."
            elif key in vocabularies.DERIVED_GLOBALS:
                message = f"{key} is computed by the converter; do not set it."
            elif key in platform_keys:
                message = f"{key} is a platform variable; set it under platform:."
            else:
                hint = _case_hint(key, keys)
                message = (
                    f"{key} is not a key; did you mean {hint!r}? (keys are case-sensitive)."
                    if hint is not None
                    else f"{key} is not an OG1 global for {slug}:; put other globals "
                    "under global_attributes:."
                )
            issues.append(ValidationIssue("ERROR", message, where))
    return issues


def _validate_global_attributes(extra: object) -> list[ValidationIssue]:
    """ERROR on a global_attributes key that has a home elsewhere or that the converter sets.

    :func:`seagliderOG1.convert` refuses both; this says so before any file is read,
    and names where the key goes.

    Parameters
    ----------
    extra : object
        The value of the ``global_attributes`` key.

    Returns
    -------
    list of ValidationIssue
        One ERROR per refused key with a value; empty otherwise.

    """
    if not isinstance(extra, dict):
        return []
    from seagliderOG1 import vocabularies

    home = vocabularies.CONFIG_GLOBAL_HOME
    issues = []
    for key, value in extra.items():
        if _is_placeholder(value):
            continue
        where = f"global_attributes.{key}"
        if key in home:
            slug = home[key]
            message = (
                f"{key} has its own key under {slug}:; move it there:\n"
                f"    {slug}:\n      {key}: {value}"
            )
        elif key in vocabularies.DERIVED_GLOBALS:
            message = (
                f"{key} is computed by the converter; remove it from global_attributes."
            )
        else:
            continue
        issues.append(ValidationIssue("ERROR", message, where))
    return issues


def _validate_highly_desirable(data: dict[str, object]) -> list[ValidationIssue]:
    """WARN for each OG1 highly-desirable global the config leaves unset.

    Advisory, not an error: seagliderOG1 does not enforce OG1 completeness. Checks the
    config-supplied highly-desirable globals that have a home validate can read without
    the files — the global-section keys and ``internal_mission_identifier`` in
    ``global_attributes``. Running ``validate`` on an unedited template surfaces these
    as the template telling the user what to fill. The derived and package-constant
    highly-desirable globals (``time_coverage_*``, ``institution``, ``rtqc_method_doi``)
    are always produced and not checked; ``contributor_id`` and
    ``contributing_institutions_vocabulary`` come from the contributor/institution
    records, validated there.

    Parameters
    ----------
    data : dict of str to object
        The parsed configuration.

    Returns
    -------
    list of ValidationIssue
        One WARNING per unset config-supplied highly-desirable global.

    """
    from seagliderOG1 import vocabularies

    extra = data.get("global_attributes")
    extra = extra if isinstance(extra, dict) else {}
    blocks = {
        slug: (data.get(slug) if isinstance(data.get(slug), dict) else {})
        for slug in vocabularies.CONFIG_GLOBAL_SECTIONS
    }
    blocks["global_attributes"] = extra
    issues: list[ValidationIssue] = []
    for row in global_rows():
        block = row["set_in"]
        # contributor/institution globals come from their records, validated there.
        if row["tier"] != "highly desirable" or block not in blocks:
            continue
        name = row["name"]
        present = not _is_placeholder(blocks[block].get(name))
        if not present:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    f"{name} is unset; it is OG1 highly desirable. Set it under "
                    f"{block} to improve discoverability.",
                    name,
                )
            )
    return issues


def _validate(
    written: dict,
    base_dir: pathlib.Path,
    *,
    strict: bool,
    raw_dir_override: str | None,
) -> list[ValidationIssue]:
    """Validate an already-read configuration mapping.

    Parameters
    ----------
    written : dict
        The configuration mapping exactly as read (before :func:`_normalise`), so the
        deprecation warnings can see a deprecated key.
    base_dir : pathlib.Path
        Directory ``raw_dir`` resolves relative to.
    strict : bool
        When True, also require every dive in the ``dives`` range to be present.
    raw_dir_override : str or None
        A command-line ``--raw-dir`` that replaces the config's ``raw_dir`` for
        validation.

    Returns
    -------
    list of ValidationIssue
        All problems found, ERROR and WARNING; empty when the config is valid.

    """
    try:
        data = _normalise(written)
    except ValueError as exc:
        return [ValidationIssue("ERROR", str(exc), None)]
    issues: list[ValidationIssue] = [
        ValidationIssue(
            "WARNING",
            f"{old!r} is deprecated; rename it to {new!r} (read for one more release).",
            old,
        )
        for old, new in DEPRECATED_KEYS.items()
        if old in written
    ]
    if raw_dir_override is not None:
        data = {**data, "raw_dir": raw_dir_override}

    for key in data:
        if key not in KNOWN_KEYS:
            hint = _case_hint(key, KNOWN_KEYS)
            message = (
                f"{key!r} is not a key; the config key is {hint!r} "
                "(keys are case-sensitive)."
                if hint is not None
                else f"unknown key {key!r}."
            )
            issues.append(ValidationIssue("ERROR", message, key))
    for key in REQUIRED_KEYS:
        if data.get(key) in (None, "", []):
            issues.append(
                ValidationIssue(
                    "ERROR", f"required key {key!r} is missing or empty.", key
                )
            )
    version = data.get("config_version")
    if version != 3:
        issues.append(
            ValidationIssue(
                "ERROR",
                "config_version must be 3. The single deployment: block was replaced by "
                "identity_and_discovery:, rights_and_access: and provenance_and_processing: "
                "(the conversion page's groups); run `seagliderOG1 init` to regenerate.",
                "config_version",
            )
        )
    if "deployment" in data:
        issues.append(
            ValidationIssue(
                "ERROR",
                "deployment: is no longer a key; its globals moved to "
                "identity_and_discovery:, rights_and_access: and "
                "provenance_and_processing:. Run `seagliderOG1 init` to regenerate.",
                "deployment",
            )
        )

    from seagliderOG1 import vocabularies

    valid_modes = tuple(vocabularies.MODE_SUFFIX)
    mode = data.get("mode")
    if mode is not None and mode not in valid_modes:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"mode must be one of {list(valid_modes)}, not {mode!r}.",
                "mode",
            )
        )
    if "repair" in data and not isinstance(data["repair"], bool):
        issues.append(
            ValidationIssue("ERROR", "repair must be true or false.", "repair")
        )
    if "report" in data and not isinstance(data["report"], bool):
        issues.append(
            ValidationIssue("ERROR", "report must be true or false.", "report")
        )
    if not _is_placeholder(data.get("local_config")):
        issues.append(
            ValidationIssue(
                "ERROR",
                f"local_config is not read by seagliderOG1 {_package_version()}; a "
                "non-null value would be silently ignored, so remove it (set null) or "
                "upgrade to a version that supports it.",
                "local_config",
            )
        )

    dives = data.get("dives")
    if dives is not None and not _is_dive_pair(dives):
        issues.append(
            ValidationIssue(
                "ERROR", "dives must be null or [first, last] integers.", "dives"
            )
        )
    keep = data.get("keep_variables")
    if keep is not None and not isinstance(keep, list):
        issues.append(
            ValidationIssue(
                "ERROR", "keep_variables must be null or a list.", "keep_variables"
            )
        )
    if (
        "global_attributes" in data
        and data["global_attributes"] is not None
        and not isinstance(data["global_attributes"], dict)
    ):
        issues.append(
            ValidationIssue(
                "ERROR", "global_attributes must be a mapping.", "global_attributes"
            )
        )

    issues.extend(_validate_sensors(data.get("sensors")))
    issues.extend(_validate_global_attributes(data.get("global_attributes")))
    issues.extend(_validate_global_sections(data))
    issues.extend(_validate_highly_desirable(data))
    issues.extend(_validate_platform(data.get("platform")))
    issues.extend(_validate_people(data.get("contributors"), "contributors", "PI"))
    issues.extend(
        _validate_people(data.get("institutions"), "institutions", "Operator")
    )
    issues.extend(_validate_raw_dir(data, base_dir, strict))
    return issues


def check(
    path: str | os.PathLike,
    *,
    strict: bool = False,
    raw_dir_override: str | None = None,
) -> list[ValidationIssue]:
    """Validate a mission configuration file, returning its issues without raising.

    Parameters
    ----------
    path : str or os.PathLike
        Path to the ``mission.yaml`` file.
    strict : bool, optional
        When True, also require every dive in the ``dives`` range to be present.
        Default is False.
    raw_dir_override : str or None, optional
        A command-line ``--raw-dir`` that replaces the config's ``raw_dir`` for
        validation, so an override is checked rather than the stale config value.

    Returns
    -------
    list of ValidationIssue
        All problems found, ERROR and WARNING; empty when the config is valid.

    """
    config_path = pathlib.Path(path)
    try:
        written = _read_yaml(config_path)
    except ValueError as exc:
        return [ValidationIssue("ERROR", str(exc), None)]
    return _validate(
        written, config_path.parent, strict=strict, raw_dir_override=raw_dir_override
    )


def load(config: str | os.PathLike | Mapping[str, object]) -> dict:
    """Load and validate a mission configuration, returning it with resolved paths.

    Parameters
    ----------
    config : str or os.PathLike or Mapping
        A path to a ``mission.yaml`` file, or an already-loaded mapping.

    Returns
    -------
    dict
        The configuration with the file's own keys (the three global-attribute
        sections left unmerged; ``config_version`` and ``local_config`` kept, so the
        returned mapping round-trips back through :func:`load`), ``raw_dir`` and
        ``output_dir`` resolved to absolute paths.

    Raises
    ------
    MissionError
        If the configuration has one or more validation errors, or (for a mapping) a
        relative ``raw_dir`` / ``output_dir`` with no base directory to resolve against.

    """
    if isinstance(config, Mapping):
        written: dict = dict(config)
        base_dir: pathlib.Path | None = None
    else:
        config_path = pathlib.Path(config)
        try:
            written = _read_yaml(config_path)
        except ValueError as exc:
            raise MissionError(
                str(exc), [ValidationIssue("ERROR", str(exc), None)]
            ) from exc
        base_dir = config_path.parent

    try:
        data = _normalise(written)
    except ValueError as exc:
        raise MissionError(
            str(exc), [ValidationIssue("ERROR", str(exc), None)]
        ) from exc

    resolved_base = base_dir if base_dir is not None else pathlib.Path.cwd()
    for key in _PATH_KEYS:
        value = data.get(key)
        if value in (None, ""):
            continue
        candidate = pathlib.Path(str(value))
        if base_dir is None and not candidate.is_absolute():
            msg = (
                f"{key} {value!r} is relative but the configuration has no base "
                "directory; give an absolute path or load from a file."
            )
            raise MissionError(msg)
        data[key] = str((resolved_base / candidate).resolve())

    issues = _validate(written, resolved_base, strict=False, raw_dir_override=None)
    errors = [issue for issue in issues if issue.level == "ERROR"]
    if errors:
        summary = "; ".join(
            f"{issue.key}: {issue.message}" if issue.key else issue.message
            for issue in errors
        )
        raise MissionError(
            f"mission configuration has {len(errors)} error(s): {summary}", issues
        )
    for issue in issues:
        if issue.level == "WARNING":
            logger.warning("%s: %s", issue.key or "config", issue.message)

    # config_version and local_config are kept so that load() round-trips: a dict from
    # load() is re-validatable by load()/process()/convert(mission=...). They are file
    # keys the converter ignores, not consumed-and-dropped.
    return data


def select_missions(root: str | os.PathLike, select: str | None = None) -> list:
    """Return the missions under ``root`` to convert.

    Parameters
    ----------
    root : str or os.PathLike
        A basestation directory: a single mission directory (``p*.nc`` inside) or a
        root of ``SN/DATE`` mission directories.
    select : str or None, optional
        For a root, a glob over each mission's ``SN/DATE`` path (``*/*`` selects every
        mission). Ignored for a single mission directory; required for a root.

    Returns
    -------
    list
        The selected missions, as returned by ``readers.discover_missions``.

    Raises
    ------
    ValueError
        If ``select`` is given for a single mission directory, if a root is given with
        no ``select``, or if ``select`` matches no mission under the root.

    """
    import fnmatch

    from seagliderOG1 import readers

    root_path = pathlib.Path(root)
    missions = readers.discover_missions(str(root_path))
    if not readers.is_root(missions):
        if select is not None:
            msg = (
                "select applies to a root of SN/DATE missions, not a single "
                "mission directory."
            )
            raise ValueError(msg)
        return missions
    if not select:
        msg = "source is a root of missions; select with '*/*' or a SN/DATE glob."
        raise ValueError(msg)
    selected = [
        mission
        for mission in missions
        if fnmatch.fnmatch(
            str(pathlib.Path(mission.path).relative_to(root_path)), select
        )
    ]
    if not selected:
        msg = f"select {select!r} matched no missions under {root_path}."
        raise ValueError(msg)
    return selected
