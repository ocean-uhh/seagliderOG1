"""Mission-configuration schema shared by the ``init`` and ``validate`` verbs.

The mission configuration (``mission.yaml``) lives outside the installed
package so that platform, contributor and global-attribute metadata belong to
the user rather than to seagliderOG1. This module holds the known keys, the
commented template that ``init`` writes, and the checks that ``validate`` runs.
"""

import pathlib
from typing import NamedTuple

import yaml

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


def load_config(config_path: pathlib.Path) -> dict:
    """Load a mission configuration file into a dict.

    Parameters
    ----------
    config_path : pathlib.Path
        Path to the ``mission.yaml`` file.

    Returns
    -------
    dict
        The parsed configuration, with the deprecated ``source`` read as ``raw_dir``.

    Raises
    ------
    ValueError
        If the file's YAML root is not a mapping (a list or scalar), which would
        otherwise pass ``safe_load`` and fail deep in validation or conversion, or if
        ``raw_dir`` and its deprecated name ``source`` are both set.

    """
    return _normalise(_read_yaml(config_path))


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
        # readers.discover_missions' bad-input style and validate_config catches it.
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


def deployment_from_config(config: dict) -> dict:
    """Merge the three global-attribute sections into one ``deployment`` mapping.

    ``convert.to_og1`` / ``process_mission`` take a single ``deployment`` mapping; the
    mission file splits those globals across ``identity_and_discovery:``,
    ``rights_and_access:`` and ``provenance_and_processing:``. This flattens them back at
    the CLI boundary, so the conversion engine is unchanged by the schema's shape.

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


def _package_version() -> str:
    """Return the installed seagliderOG1 version, or a placeholder when unknown."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("seagliderOG1")
    except PackageNotFoundError:
        return "(unknown version)"


def _scalar(value: object) -> str:
    """Render a Python value as a YAML scalar for the template.

    Parameters
    ----------
    value : object
        The value to render.

    Returns
    -------
    str
        A YAML scalar: ``null`` for None, ``true``/``false`` for bools, the
        bare number for ints/floats, and a quoted string where quoting is needed.

    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#") or text != text.strip():
        return repr(text).replace("'", '"')
    return text


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


# Header comment per global-attribute section, printed above its keys in the template.
_SECTION_HEADERS = {
    "identity_and_discovery": "who and where: identity and discovery globals",
    "rights_and_access": "rights and access globals",
    "provenance_and_processing": "provenance globals",
}


def _global_section_lines() -> list[str]:
    """Build the three global-attribute section blocks, tier comments from ``global_rows``.

    One source for the tiers: each key's ``(mandatory)`` / ``(highly desirable)`` /
    ``(suggested)`` comment comes from ``vocabularies.REQUIRED_GLOBALS`` through
    :func:`global_rows`, so the template cannot drift from the manual-sourced table.
    ``license`` and ``acknowledgment`` are ACDD globals with no OG1 tier and are marked
    ``(optional)``. The section names are the conversion page's convention groups, so a
    user filling a key sees the page group it lands in.

    Returns
    -------
    list of str
        One header line per section and one ``key: value`` line per global, blocks in
        :data:`vocabularies.CONFIG_GLOBAL_SECTIONS` order.

    """
    from seagliderOG1 import vocabularies

    rows = {row["name"]: row for row in global_rows()}
    lines: list[str] = []
    for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items():
        if lines:
            lines.append("")
        lines.append(f"{slug}:   # -> global attributes; {_SECTION_HEADERS[slug]}")
        for key in keys:
            hint = rows[key]["note"]
            comment = f"{rows[key]['tier']} -> global attribute" + (
                f"; {hint}" if hint else ""
            )
            lines.append(f"  {key}: null   # {comment}")
    return lines


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


def _platform_template_lines(plat: dict[str, object]) -> list[str]:
    """Build the ``platform:`` block, destination comments from ``platform_rows``.

    Each line's comment says where the key goes — ``-> variable`` for an UPPER platform
    field, ``-> attribute on <VARIABLE>`` for a lower ``_vocabulary`` key — read from
    :func:`platform_rows` (which reads ``vocabularies.PLATFORM_FIELDS``) so the template
    cannot drift from the code.

    Parameters
    ----------
    plat : dict of str to object
        Platform values to render (template defaults merged with any overrides).

    Returns
    -------
    list of str
        The ``platform:`` header line and one line per field.

    """
    lines = [
        "platform:               # 'init --raw-dir' fills these; fill any null before validate"
    ]
    for row in platform_rows():
        key = row["key"]
        value = "null" if key in _PLATFORM_VOCABULARY_PARENTS else _scalar(plat[key])
        comment = f"{row['requirement']} -> {row['destination']}; {row['hint']}"
        lines.append(f"  {key}: {value}   # {comment}")
    return lines


def render_template(
    platform: dict[str, object] | None = None,
    raw_dir: str | None = None,
    dives: list[int] | None = None,
) -> str:
    """Return ``mission.yaml`` text with the given platform block and guidance.

    Parameters
    ----------
    platform : dict of str to object or None, optional
        Platform values to merge over the template defaults (every platform field
        null). None uses the defaults unchanged.
    raw_dir : str or None, optional
        Value for the ``raw_dir`` key. None leaves it as ``null`` for the user to
        fill; ``init --raw-dir DIR`` passes DIR so the template validates as written.
    dives : list of int or None, optional
        ``[first, last]`` for the ``dives`` key; None leaves it null (every file).

    Returns
    -------
    str
        The full commented YAML document.

    """
    from seagliderOG1 import vocabularies

    plat = {**dict.fromkeys(vocabularies.PLATFORM_FIELDS), **(platform or {})}
    lines = [
        "# seagliderOG1 mission configuration.",
        "# UPPER keys become OG1 variables, lower keys become attributes or globals;",
        "# the comment on each line says which. You fill the values.",
        "# Paths are resolved relative to this file. Edit the values, then:",
        "#   seagliderOG1 validate this_file.yaml",
        "#   seagliderOG1 process  this_file.yaml",
        "",
        "config_version: 3",
        "",
        f"raw_dir: {_scalar(raw_dir)}           # basestation files: a mission dir (p*.nc inside) or a root of SN/DATE dirs",
        "output_dir: ./          # where OG1 files are written",
        "mode: realtime          # realtime (id suffix R) | delayed",
        f"dives: {_scalar(dives) if dives else 'null'}             # [first, last] dive numbers; null = all files present",
        "repair: false           # run repair_files on the basestation files (writes the raw_dir tree)",
        "keep_variables: null    # optional list of science variables to keep; null = all",
        "report: false           # also write <id>_conversion.html beside each file",
        "",
        *_platform_template_lines(plat),
        "",
        "local_config: null   # optional path to a directory of local config overrides; read once the feature lands",
        "",
        *_global_section_lines(),
        "",
        "global_attributes: {}   # any other OG1 global, written as given: replace {} with lines",
        '  #   institution: "University of Hamburg (IfM)"   (a key above goes under its own block)',
        "",
        "sensors: {}            # corrections to a basestation sensor record, by its key in the",
        "  # instrument global; fields serial_number, calibration_date. e.g.",
        '  # tridentebb700chla470fdom365: {serial_number: "237998", calibration_date: 2025-03-11}',
        "",
        "contributors:           # one entry per person per role; replace this example",
        "  # role is a W08 term: Manufacturer, Owner, Operator, PI, Technical Coordinator,",
        "  # Data scientist, Service Provider. List a person once per role. At least one PI.",
        "  - name: Jane Doe       # no commas in a name (commas separate people)",
        "    email: jane@example.org",
        "    orcid: null          # bare ORCID or full https://orcid.org/ URL",
        "    role: PI",
        "",
        "institutions:           # at least one with role Operator; resolved via the EDMO registry",
        "  - name: Your Institution",
        "    role: Operator",
        "    id: null             # EDMO/ROR URL; null to resolve by name against the registry",
        "",
    ]
    return "\n".join(lines)


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


def _is_dive_pair(dives: object) -> bool:
    """Return True when ``dives`` is a two-element list of integers."""
    return (
        isinstance(dives, list)
        and len(dives) == 2
        and all(isinstance(d, int) for d in dives)
    )


def report_issues(issues: list[ValidationIssue]) -> bool:
    """Print validation issues (ERRORs to stderr, WARNINGs to stdout) and flag errors.

    Parameters
    ----------
    issues : list of ValidationIssue
        The issues to print.

    Returns
    -------
    bool
        True if any issue is an ERROR.

    """
    import sys

    has_error = False
    for issue in issues:
        where = f" [{issue.key}]" if issue.key else ""
        stream = sys.stderr if issue.level == "ERROR" else sys.stdout
        print(f"{issue.level}{where}: {issue.message}", file=stream)
        has_error = has_error or issue.level == "ERROR"
    return has_error


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


def _validate_raw_dir(
    data: dict[str, object], config_path: pathlib.Path, strict: bool
) -> list[ValidationIssue]:
    """Check that ``raw_dir`` exists, holds basestation files, and spans ``dives``.

    Parameters
    ----------
    data : dict of str to object
        The parsed configuration.
    config_path : pathlib.Path
        Path to the configuration file; ``raw_dir`` resolves relative to its parent.
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
    src = (config_path.parent / str(raw_dir)).resolve()
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


def _is_placeholder(value: object) -> bool:
    """Return True for a null or placeholder config value.

    Matches the converter's unset test (``vocabularies.PLACEHOLDER_VALUES``) so
    ``validate`` and ``to_og1`` agree on what counts as missing — a value the
    converter would drop (``""``, ``"null"``, ``"null@null.com"``) is treated as unset
    here too, not reported as present.

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

    return value is None or (
        isinstance(value, str) and value.strip() in vocabularies.PLACEHOLDER_VALUES
    )


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

    ``process`` refuses both (``convert.to_og1``); this says so before any file is read,
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


def validate_config(
    config_path: pathlib.Path,
    strict: bool = False,
    raw_dir_override: str | None = None,
) -> list[ValidationIssue]:
    """Validate a mission configuration file.

    Parameters
    ----------
    config_path : pathlib.Path
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
    try:
        written = _read_yaml(config_path)
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
    issues.extend(_validate_raw_dir(data, config_path, strict))
    return issues
