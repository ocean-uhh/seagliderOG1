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
        "source",
        "output_dir",
        "mode",
        "dives",
        "repair",
        "keep_variables",
        "platform",
        "global_attributes",
        "contributors",
        "institutions",
    }
)
REQUIRED_KEYS = ("source",)
VALID_MODES = ("realtime", "delayed")

PLATFORM_DEFAULTS: dict[str, object] = {
    "PLATFORM_SERIAL_NUMBER": None,
    "PLATFORM_MODEL": None,
    "PLATFORM_DEPTH_RATING": None,
    "PLATFORM_MAKER": None,
    "GLIDER_FIRMWARE_VERSION": None,
    "LANDSTATION_VERSION": None,
    "WMO_IDENTIFIER": None,
}

# Platform fields a mission config must fill (or supply via ``init --from``): a null
# here is a validate ERROR rather than a silent default written into the output.
REQUIRED_PLATFORM_FIELDS = (
    "PLATFORM_SERIAL_NUMBER",
    "PLATFORM_MODEL",
    "PLATFORM_MAKER",
    "PLATFORM_DEPTH_RATING",
)


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
        The parsed configuration.

    """
    return yaml.safe_load(config_path.read_text())


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


def render_template(
    platform: dict[str, object] | None = None, source: str | None = None
) -> str:
    """Return ``mission.yaml`` text with the given platform block and guidance.

    Parameters
    ----------
    platform : dict of str to object or None, optional
        Platform values to merge over :data:`PLATFORM_DEFAULTS`. None uses the
        defaults unchanged.
    source : str or None, optional
        Value for the ``source`` key. None leaves it as ``null`` for the user to
        fill; ``init --from DIR`` passes DIR so the template validates as written.

    Returns
    -------
    str
        The full commented YAML document.

    """
    plat = {**PLATFORM_DEFAULTS, **(platform or {})}
    lines = [
        "# seagliderOG1 mission configuration.",
        "# Paths are resolved relative to this file. Edit the values, then:",
        "#   seagliderOG1 validate this_file.yaml",
        "#   seagliderOG1 process  this_file.yaml",
        "",
        "config_version: 1",
        "",
        f"source: {_scalar(source)}            # mission dir (p*.nc inside) or a root of SN/DATE dirs",
        "output_dir: ./          # where OG1 files are written",
        "mode: delayed           # realtime | delayed",
        "dives: null             # [first, last] dive numbers; null = all files present",
        "repair: false           # run scan_and_repair on the basestation files (writes the source tree)",
        "keep_variables: null    # optional list of science variables to keep; null = all",
        "",
        "platform:               # 'init --from' fills these; fill any null before validate",
        f"  PLATFORM_SERIAL_NUMBER: {_scalar(plat['PLATFORM_SERIAL_NUMBER'])}   # from platform_id; a serial or a local nickname",
        f"  PLATFORM_MODEL: {_scalar(plat['PLATFORM_MODEL'])}   # e.g. University of Washington Seaglider M1 glider",
        "  platform_model_vocabulary: null   # e.g. https://vocab.nerc.ac.uk/collection/B76/current/B7600024/ (NERC B76; B7600024 = Seaglider)",
        f"  PLATFORM_DEPTH_RATING: {_scalar(plat['PLATFORM_DEPTH_RATING'])}   # e.g. 1000 (metres)",
        f"  PLATFORM_MAKER: {_scalar(plat['PLATFORM_MAKER'])}   # e.g. University of Washington School of Oceanography",
        f"  GLIDER_FIRMWARE_VERSION: {_scalar(plat['GLIDER_FIRMWARE_VERSION'])}   # from seaglider_software_version",
        f"  LANDSTATION_VERSION: {_scalar(plat['LANDSTATION_VERSION'])}   # from base_station_version",
        f"  WMO_IDENTIFIER: {_scalar(plat['WMO_IDENTIFIER'])}   # from wmo_identifier",
        "",
        "global_attributes:      # written verbatim into the OG1 file; add any OG1 global here",
        "  project: null         # (tier: suggested)",
        "  program: null         # (tier: suggested)",
        "  title: null           # (tier: suggested)",
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
    normalized = contributors.normalize_role(role)
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


def _validate_source(
    data: dict[str, object], config_path: pathlib.Path, strict: bool
) -> list[ValidationIssue]:
    """Check that ``source`` exists, holds basestation files, and spans ``dives``.

    Parameters
    ----------
    data : dict of str to object
        The parsed configuration.
    config_path : pathlib.Path
        Path to the configuration file; ``source`` resolves relative to its parent.
    strict : bool
        When True, every dive in the ``dives`` range must be present (no gaps).

    Returns
    -------
    list of ValidationIssue
        Problems found with the source directory or the dive range.

    """
    source = data.get("source")
    if source in (None, ""):
        return []
    src = (config_path.parent / str(source)).resolve()
    if not src.exists():
        return [ValidationIssue("ERROR", f"source not found: {src}", "source")]

    from seagliderOG1 import readers

    try:
        missions = readers.discover_missions(str(src))
    except ValueError as exc:
        return [ValidationIssue("ERROR", f"source unreadable: {exc}", "source")]
    if not missions:
        return [
            ValidationIssue(
                "ERROR",
                "no basestation files (pSSSDDDD*.nc) under source "
                "(a mission directory, or a root of SN/DATE directories).",
                "source",
            )
        ]

    dives = data.get("dives")
    if not (
        isinstance(dives, list)
        and len(dives) == 2
        and all(isinstance(d, int) for d in dives)
    ):
        return []
    # The dive-range check applies to a single mission directory; under a root the
    # range is per mission and is not validated here.
    single = [mission for mission in missions if mission.date is None]
    if not single:
        return []
    present = single[0].dives
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
    issues: list[ValidationIssue] = []
    for field in REQUIRED_PLATFORM_FIELDS:
        if platform.get(field) in (None, "", "None"):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    f"platform.{field} is null; fill it (see the template '# e.g.' "
                    "comments) or run 'init --from DIR'.",
                    f"platform.{field}",
                )
            )
    return issues


def validate_config(
    config_path: pathlib.Path,
    strict: bool = False,
    source_override: str | None = None,
) -> list[ValidationIssue]:
    """Validate a mission configuration file.

    Parameters
    ----------
    config_path : pathlib.Path
        Path to the ``mission.yaml`` file.
    strict : bool, optional
        When True, also require every dive in the ``dives`` range to be present.
        Default is False.
    source_override : str or None, optional
        A command-line ``--source`` that replaces the config's ``source`` for
        validation, so an override is checked rather than the stale config value.

    Returns
    -------
    list of ValidationIssue
        All problems found, ERROR and WARNING; empty when the config is valid.

    """
    data = yaml.safe_load(config_path.read_text())
    if not isinstance(data, dict):
        return [ValidationIssue("ERROR", "configuration root is not a mapping.", None)]
    if source_override is not None:
        data = {**data, "source": source_override}

    issues: list[ValidationIssue] = []
    for key in data:
        if key not in KNOWN_KEYS:
            issues.append(ValidationIssue("ERROR", f"unknown key {key!r}.", key))
    for key in REQUIRED_KEYS:
        if data.get(key) in (None, "", []):
            issues.append(
                ValidationIssue(
                    "ERROR", f"required key {key!r} is missing or empty.", key
                )
            )
    if "config_version" not in data:
        issues.append(
            ValidationIssue(
                "WARNING", "no config_version; assuming 1.", "config_version"
            )
        )

    mode = data.get("mode")
    if mode is not None and mode not in VALID_MODES:
        issues.append(
            ValidationIssue(
                "ERROR",
                f"mode must be one of {list(VALID_MODES)}, not {mode!r}.",
                "mode",
            )
        )
    if "repair" in data and not isinstance(data["repair"], bool):
        issues.append(
            ValidationIssue("ERROR", "repair must be true or false.", "repair")
        )

    dives = data.get("dives")
    if dives is not None and not (
        isinstance(dives, list)
        and len(dives) == 2
        and all(isinstance(d, int) for d in dives)
    ):
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

    issues.extend(_validate_platform(data.get("platform")))
    issues.extend(_validate_people(data.get("contributors"), "contributors", "PI"))
    issues.extend(
        _validate_people(data.get("institutions"), "institutions", "Operator")
    )
    issues.extend(_validate_source(data, config_path, strict))
    return issues
