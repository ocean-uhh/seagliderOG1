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
    }
)
REQUIRED_KEYS = ("source", "contributors")
VALID_MODES = ("realtime", "delayed")

PLATFORM_DEFAULTS: dict[str, object] = {
    "PLATFORM_SERIAL_NUMBER": None,
    "PLATFORM_MODEL": "University of Washington Seaglider M1 glider",
    "PLATFORM_DEPTH_RATING": 1000,
    "PLATFORM_MAKER": "University of Washington School of Oceanography",
    "GLIDER_FIRMWARE_VERSION": None,
    "LANDSTATION_VERSION": None,
    "WMO_IDENTIFIER": None,
}


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
        "repair: false           # repair basestation time metadata before loading",
        "keep_variables: null    # optional list of variables to keep; null = all",
        "",
        "platform:               # filled from the first file by 'init --from'; edit as needed",
        f"  PLATFORM_SERIAL_NUMBER: {_scalar(plat['PLATFORM_SERIAL_NUMBER'])}   # from platform_id",
        f"  PLATFORM_MODEL: {_scalar(plat['PLATFORM_MODEL'])}",
        f"  PLATFORM_DEPTH_RATING: {_scalar(plat['PLATFORM_DEPTH_RATING'])}",
        f"  PLATFORM_MAKER: {_scalar(plat['PLATFORM_MAKER'])}",
        f"  GLIDER_FIRMWARE_VERSION: {_scalar(plat['GLIDER_FIRMWARE_VERSION'])}   # from seaglider_software_version",
        f"  LANDSTATION_VERSION: {_scalar(plat['LANDSTATION_VERSION'])}   # from base_station_version",
        f"  WMO_IDENTIFIER: {_scalar(plat['WMO_IDENTIFIER'])}   # from wmo_identifier",
        "",
        "global_attributes:      # written verbatim into the OG1 file; add any OG1 global here",
        "  project: null         # (tier: suggested)",
        "  program: null         # (tier: suggested)",
        "  title: null           # (tier: suggested)",
        "",
        "contributors:           # people credited in the OG1 file; replace this example",
        "  - name: Jane Doe",
        "    email: jane@example.org",
        "    orcid: null",
        "    roles: [PI]",
        "    institution: null",
        "",
    ]
    return "\n".join(lines)


def _validate_contributors(contributors: object) -> list[ValidationIssue]:
    """Check the ``contributors`` block shape.

    Parameters
    ----------
    contributors : object
        The value of the ``contributors`` key.

    Returns
    -------
    list of ValidationIssue
        Problems found; empty if the block is well formed (or absent, which the
        required-key check handles separately).

    """
    if contributors in (None, [], ""):
        return []
    if not isinstance(contributors, list):
        return [
            ValidationIssue("ERROR", "contributors must be a list.", "contributors")
        ]
    issues: list[ValidationIssue] = []
    for index, entry in enumerate(contributors):
        where = f"contributors[{index}]"
        if not isinstance(entry, dict):
            issues.append(
                ValidationIssue("ERROR", f"{where} must be a mapping.", where)
            )
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(
                ValidationIssue("ERROR", f"{where} needs a non-empty name.", where)
            )
        roles = entry.get("roles")
        if roles is not None and not isinstance(roles, list):
            issues.append(
                ValidationIssue("ERROR", f"{where}.roles must be a list.", where)
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

    # PR2's public readers.discover_missions will replace this private access.
    is_basestation = readers._validate_filename  # noqa: SLF001
    try:
        names = [f for f in readers.list_files(str(src)) if is_basestation(f)]
    except ValueError as exc:
        return [ValidationIssue("ERROR", f"source unreadable: {exc}", "source")]
    if not names:
        return [
            ValidationIssue(
                "ERROR",
                "no basestation files (pSSSDDDD*.nc) directly in source "
                "(root-of-missions discovery arrives with 'process').",
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
    dive_number = readers._profnum_from_filename  # noqa: SLF001
    present = sorted(dive_number(f) for f in names)
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


def validate_config(
    config_path: pathlib.Path, strict: bool = False
) -> list[ValidationIssue]:
    """Validate a mission configuration file.

    Parameters
    ----------
    config_path : pathlib.Path
        Path to the ``mission.yaml`` file.
    strict : bool, optional
        When True, also require every dive in the ``dives`` range to be present.
        Default is False.

    Returns
    -------
    list of ValidationIssue
        All problems found, ERROR and WARNING; empty when the config is valid.

    """
    data = yaml.safe_load(config_path.read_text())
    if not isinstance(data, dict):
        return [ValidationIssue("ERROR", "configuration root is not a mapping.", None)]

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
    for key in ("platform", "global_attributes"):
        if key in data and data[key] is not None and not isinstance(data[key], dict):
            issues.append(ValidationIssue("ERROR", f"{key} must be a mapping.", key))

    issues.extend(_validate_contributors(data.get("contributors")))
    issues.extend(_validate_source(data, config_path, strict))
    return issues
