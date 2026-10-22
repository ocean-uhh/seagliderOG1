"""The ``list`` verb: print a seagliderOG1 registry as a table.

Prints a curated registry, not a raw config file: the W08 contributor roles, the EDMO
institution registry, the missions discovered under a root directory, and what an OG1
file expects — the global attributes and their tiers, the ``platform:`` keys, the OG1
variables the package writes, and the sensor catalogue. Each is read from the table the
converter itself uses, so a listing cannot drift from the code.
"""

import argparse
import difflib
import pathlib
import sys

_REGISTRIES = {
    "roles": "contributor roles (W08) — contributors[].role",
    "institutions": "the EDMO institution registry — institutions[].name / id",
    "missions": "the SN/DATE missions under a directory (give the path)",
    "globals": "OG1 global attributes: tier, source, where mission.yaml sets them",
    "platform": "the mission.yaml platform: keys and where each is written",
    "variables": "OG1 variables the package writes (give a NAME for one in full)",
    "sensors": "the sensor catalogue (NERC L22) the converter matches against",
}

_EPILOG = """
Examples:
  seagliderOG1 list                          # the registries
  seagliderOG1 list globals                  # every OG1 global with its tier
  seagliderOG1 list platform                 # the platform: keys in mission.yaml
  seagliderOG1 list variables --search temp  # filter by any column
  seagliderOG1 list variables TEMP           # one variable's attributes in full
  seagliderOG1 list missions /data/005       # missions under a root
"""


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``list`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``list`` subparser.

    """
    parser = subparsers.add_parser(
        "list",
        help="print a registry: roles, institutions, missions, globals, platform, "
        "variables, sensors",
        description="Print a seagliderOG1 registry as a table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument(
        "registry",
        nargs="?",
        choices=tuple(_REGISTRIES),
        default=None,
        help="which registry to print; omit to see the registry names",
    )
    parser.add_argument(
        "target",
        nargs="?",
        metavar="PATH|NAME",
        default=None,
        help="root or mission directory for 'missions'; a variable name for 'variables'",
    )
    parser.add_argument(
        "--search",
        metavar="TEXT",
        default=None,
        help="case-insensitive filter across every column",
    )
    parser.set_defaults(func=run)
    return parser


def _matches(search: str | None, row: dict[str, str]) -> bool:
    """Return True when ``search`` is absent or a case-insensitive substring of a field.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.
    row : dict of str to str
        One table row.

    Returns
    -------
    bool
        Whether the row is kept.

    """
    return search is None or any(search.lower() in str(v).lower() for v in row.values())


def _print_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> None:
    """Print ``rows`` as plain aligned columns under a header and a dashed rule.

    Parameters
    ----------
    rows : list of dict of str to str
        The rows to print.
    columns : list of tuple of (str, str)
        ``(key, header)`` per column, in order.

    """
    if not rows:
        print("  (none)")
        return
    widths = {
        key: max(len(header), *(len(str(r.get(key, ""))) for r in rows))
        for key, header in columns
    }
    print("  ".join(h.ljust(widths[k]) for k, h in columns).rstrip())
    print("  ".join("-" * widths[k] for k, _ in columns))
    for r in rows:
        print(
            "  ".join(str(r.get(k, "")).ljust(widths[k]) for k, _ in columns).rstrip()
        )


def _plural(n: int, noun: str) -> str:
    """Return ``"1 mission"`` / ``"3 missions"``.

    Parameters
    ----------
    n : int
        The count.
    noun : str
        The singular noun.

    Returns
    -------
    str
        The count and the noun, pluralised with a trailing ``s`` when ``n != 1``.

    """
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _count_by(rows: list[dict[str, str]], key: str) -> str:
    """Return ``"a (n), b (m)"`` counts of ``key`` across ``rows``, in first-seen order.

    Parameters
    ----------
    rows : list of dict of str to str
        The rows to count.
    key : str
        The column to count by.

    Returns
    -------
    str
        The counts, or ``"none"`` when there are no rows.

    """
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[key]] = counts.get(r[key], 0) + 1
    return ", ".join(f"{k} ({n})" for k, n in counts.items()) or "none"


def _list_roles(search: str | None) -> int:
    """Print the W08 contributor roles.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0.

    """
    from seagliderOG1 import vocabularies

    rows = [
        {"role": label, "uri": uri}
        for label, uri in vocabularies.ROLE_VOCABULARY.items()
        if _matches(search, {"role": label, "uri": uri})
    ]
    _print_table(rows, [("role", "Role"), ("uri", "Term URI")])
    print(
        f"\n{_plural(len(rows), 'W08 role')}. Use the Role label in contributors[].role."
    )
    return 0


def _list_institutions(search: str | None) -> int:
    """Print the EDMO institution registry.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0.

    """
    from seagliderOG1 import contributors

    institutions = contributors.institution_registry()
    rows = [
        {"code": str(code), "name": institutions[code].get("standard_name", "")}
        for code in sorted(
            institutions, key=lambda c: institutions[c].get("standard_name", "")
        )
    ]
    rows = [r for r in rows if _matches(search, r)]
    _print_table(rows, [("code", "EDMO"), ("name", "Name")])
    print(
        f"\n{_plural(len(rows), 'institution')} (config/institution_registry.yaml). "
        "institutions[].name resolves against the Name column."
    )
    return 0


def _list_missions(target: str | None, search: str | None) -> int:
    """Print the missions discovered under a root or mission directory.

    Parameters
    ----------
    target : str or None
        The directory to search.
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0 on success, 1 when the directory is unreadable, 2 when no path is given.

    """
    if target is None:
        print(
            "error: 'list missions' needs a root or mission directory", file=sys.stderr
        )
        return 2
    from seagliderOG1 import readers

    try:
        missions = readers.discover_missions(str(pathlib.Path(target)))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rows = [
        {
            "mission": f"{m.sn:03d}/{m.date}" if m.date else str(m.sn),
            "dives": str(len(m.dives)),
            "first": str(min(m.dives)) if m.dives else "",
            "last": str(max(m.dives)) if m.dives else "",
            "path": m.path,
        }
        for m in missions
    ]
    rows = [r for r in rows if _matches(search, r)]
    _print_table(
        rows,
        [
            ("mission", "Mission"),
            ("dives", "Dives"),
            ("first", "First"),
            ("last", "Last"),
            ("path", "Path"),
        ],
    )
    print(f"\n{_plural(len(rows), 'mission')} under {target}.")
    return 0


def _list_globals(search: str | None) -> int:
    """Print every OG1 global the package knows, with its tier, source and home.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0.

    """
    from seagliderOG1 import mission

    rows = [r for r in mission.global_rows() if _matches(search, r)]
    _print_table(
        rows,
        [
            ("name", "Name"),
            ("tier", "Tier"),
            ("source", "Source"),
            ("set_in", "Set in"),
        ],
    )
    print(f"\nTiers: {_count_by(rows, 'tier')}.")
    print(
        "Source: derived = computed from the data; constant = fixed by the package; "
        "config = from mission.yaml (the 'Set in' block)."
    )
    return 0


def _list_platform(search: str | None) -> int:
    """Print the ``platform:`` keys of mission.yaml and where each is written.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0.

    """
    from seagliderOG1 import mission

    rows = [r for r in mission.platform_rows() if _matches(search, r)]
    _print_table(
        rows,
        [
            ("key", "Key"),
            ("requirement", "Requirement"),
            ("destination", "Written as"),
            ("from_file", "From file"),
        ],
    )
    print(f"\nRequirement: {_count_by(rows, 'requirement')}.")
    print(
        "Set these under platform: in mission.yaml; 'init --raw-dir DIR' fills the "
        "'From file' ones from the first basestation file."
    )
    return 0


def _variable_sources() -> dict[str, list[str]]:
    """Return OG1 variable name -> the basestation names that map to it.

    Returns
    -------
    dict of str to list of str
        Basestation names per OG1 name, in file order.

    """
    from seagliderOG1 import vocabularies

    sources: dict[str, list[str]] = {}
    for basestation, og1 in vocabularies.standard_names.items():
        sources.setdefault(og1, []).append(basestation)
    return sources


def _list_variables(target: str | None, search: str | None) -> int:
    """Print the OG1 variables the package writes, or one variable in full.

    Parameters
    ----------
    target : str or None
        A variable name to print in full, or None for the table.
    search : str or None
        The ``--search`` text (table only).

    Returns
    -------
    int
        0, or 1 when ``target`` names no known variable.

    """
    from seagliderOG1 import vocabularies

    attrs = vocabularies.vocab_attrs
    sources = _variable_sources()

    if target is not None:
        if target not in attrs:
            close = difflib.get_close_matches(target, list(attrs), n=3)
            hint = f"; did you mean {', '.join(close)}?" if close else ""
            print(f"error: no OG1 variable {target!r}{hint}", file=sys.stderr)
            return 1
        print(target)
        width = max(len(k) for k in attrs[target])
        for key, value in attrs[target].items():
            print(f"  {key.ljust(width)}  {value}")
        names = ", ".join(sources.get(target, [])) or "(none — derived or config)"
        print(f"\nBasestation names: {names}")
        return 0

    rows = [
        {
            "name": name,
            "units": str(entry.get("units", "")),
            "from": ", ".join(sources.get(name, [])),
            "long_name": str(entry.get("long_name", "")).strip(),
        }
        for name, entry in attrs.items()
    ]
    rows = [r for r in rows if _matches(search, r)]
    _print_table(
        rows,
        [
            ("name", "Name"),
            ("units", "Units"),
            ("from", "From (basestation)"),
            ("long_name", "Long name"),
        ],
    )
    print(f"\n{_plural(len(rows), 'variable')} (config/OG1_variable_attributes.yaml).")
    unlisted = sorted(n for n in sources if n not in attrs)
    if unlisted and search is None:
        print(
            "Mapped from basestation names but with no attribute entry: "
            f"{', '.join(unlisted)}."
        )
    return 0


def _list_sensors(search: str | None) -> int:
    """Print the sensor catalogue the converter matches instruments against.

    Parameters
    ----------
    search : str or None
        The ``--search`` text.

    Returns
    -------
    int
        0.

    """
    from seagliderOG1 import vocabularies

    rows = [
        {
            "key": key,
            "type": str(entry.get("sensor_type", "")),
            "maker": str(entry.get("sensor_maker", "")),
            "l22": str(entry.get("sensor_model_vocabulary", ""))
            .rstrip("/")
            .split("/")[-1],
        }
        for key, entry in vocabularies.sensor_vocabs.items()
    ]
    rows = [r for r in rows if _matches(search, r)]
    _print_table(
        rows, [("key", "Sensor"), ("type", "Type"), ("maker", "Maker"), ("l22", "L22")]
    )
    print(
        f"\n{_plural(len(rows), 'sensor')} (config/OG1_sensor_attributes.yaml, from NERC L22: "
        "https://vocab.nerc.ac.uk/collection/L22/current/)."
    )
    return 0


def run(args: argparse.Namespace) -> int:
    """Print the chosen registry, or the registry names when none is given.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``registry``, ``target`` and ``search``.

    Returns
    -------
    int
        0 on success; 1 when a missions directory is unreadable or a variable name is
        unknown; 2 when an argument is missing or given to a registry that takes none.

    """
    if args.registry is None:
        print("seagliderOG1 registries (use `seagliderOG1 list <name>`):")
        width = max(len(name) for name in _REGISTRIES)
        for name, text in _REGISTRIES.items():
            print(f"  {name.ljust(width)}  {text}")
        return 0

    if args.target is not None and args.registry not in ("missions", "variables"):
        print(
            f"error: 'list {args.registry}' takes no PATH|NAME argument",
            file=sys.stderr,
        )
        return 2

    if args.registry == "missions":
        return _list_missions(args.target, args.search)
    if args.registry == "variables":
        return _list_variables(args.target, args.search)
    listers = {
        "roles": _list_roles,
        "institutions": _list_institutions,
        "globals": _list_globals,
        "platform": _list_platform,
        "sensors": _list_sensors,
    }
    return listers[args.registry](args.search)
