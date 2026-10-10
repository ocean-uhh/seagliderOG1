"""The ``list`` verb: print a seagliderOG1 registry.

Prints a curated registry, not a raw config file: the W08 contributor roles, the EDMO
institution registry, or the missions discovered under a root directory.
"""

import argparse
import pathlib
import sys

_REGISTRIES = ("roles", "institutions", "missions")


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
        "list", help="print a registry: roles, institutions, or missions"
    )
    parser.add_argument("registry", choices=_REGISTRIES, help="which registry to print")
    parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        help="root or mission directory (required for 'missions')",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Print the chosen registry, one entry per line.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``registry`` and (for missions) ``path``.

    Returns
    -------
    int
        0 on success, 1 when a missions root is unreadable, 2 when ``missions`` is
        given without a path.

    """
    from seagliderOG1 import vocabularies

    if args.registry == "roles":
        for label, uri in vocabularies.ROLE_VOCABULARY.items():
            print(f"{label}\t{uri}")
        return 0

    if args.registry == "institutions":
        from seagliderOG1 import contributors

        institutions = contributors.registry_institutions()
        for code in sorted(
            institutions, key=lambda c: institutions[c].get("standard_name", "")
        ):
            print(f"{code}\t{institutions[code].get('standard_name', '')}")
        return 0

    # missions
    if args.path is None:
        print(
            "error: 'list missions' needs a root or mission directory", file=sys.stderr
        )
        return 2
    from seagliderOG1 import readers

    try:
        missions = readers.discover_missions(str(args.path))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for mission in missions:
        label = f"{mission.sn:03d}/{mission.date}" if mission.date else str(mission.sn)
        print(f"{label}\t{len(mission.dives)} dives")
    return 0
