"""Mission-configuration template and issue printing for the CLI verbs.

The mission-configuration schema (known keys, loader, validator) lives in
:mod:`seagliderOG1.mission`. This module holds the two terminal concerns the
schema does not need: the commented ``mission.yaml`` template that ``init``
writes, and the printing of validation issues that ``validate`` and ``process``
do. Both read the schema tables (:func:`~seagliderOG1.mission.global_rows`,
:func:`~seagliderOG1.mission.platform_rows`) from :mod:`seagliderOG1.mission`.
"""

from seagliderOG1.mission import (
    ValidationIssue,
    global_rows,
    platform_rows,
)


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
    :func:`seagliderOG1.mission.global_rows`, so the template cannot drift from the
    manual-sourced table. ``license`` and ``acknowledgment`` are ACDD globals with no
    OG1 tier and are marked ``(optional)``. The section names are the conversion page's
    convention groups, so a user filling a key sees the page group it lands in.

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


def _platform_template_lines(plat: dict[str, object]) -> list[str]:
    """Build the ``platform:`` block, destination comments from ``platform_rows``.

    Each line's comment says where the key goes — ``-> variable`` for an UPPER platform
    field, ``-> attribute on <VARIABLE>`` for a lower ``_vocabulary`` key — read from
    :func:`seagliderOG1.mission.platform_rows` (which reads
    ``vocabularies.PLATFORM_FIELDS``) so the template cannot drift from the code.

    Parameters
    ----------
    plat : dict of str to object
        Platform values to render (template defaults merged with any overrides). The two
        ``_vocabulary`` keys are not platform fields, so they are absent and render null.

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
        value = _scalar(plat[key]) if key in plat else "null"
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
        '  #   institution: "University of Hamburg"   (a key above goes under its own block)',
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
