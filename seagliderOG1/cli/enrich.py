"""The ``enrich`` verb: set metadata on a written OG1 file without converting again.

For what exists only after the file is written (a DOI assigned on publication) or a
corrected config value. Edits the **netCDF file's** global attributes in place
(:func:`seagliderOG1.enrich`); the mission config is read, never changed.
"""

import argparse
import pathlib
import sys


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``enrich`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``enrich`` subparser.

    """
    parser = subparsers.add_parser(
        "enrich",
        help="set metadata (e.g. a DOI) on a written OG1 file",
        description=(
            "Set global attributes on a written OG1 file, without converting again. "
            "Changes the netCDF file (not the config): sets date_modified, adds a "
            "history line and a new tracking_id, keeps date_created, and rebinds the "
            "conversion record beside it."
        ),
        epilog=(
            "examples:\n"
            "  seagliderOG1 enrich out/<id>.nc --doi 10.5281/zenodo.123\n"
            "  seagliderOG1 enrich out/<id>.nc mission.yaml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", type=pathlib.Path, help="the OG1 netCDF file")
    parser.add_argument(
        "config",
        nargs="?",
        type=pathlib.Path,
        help="mission.yaml whose global-attribute sections and global_attributes: are applied",
    )
    parser.add_argument("--doi", metavar="DOI", help="set the doi global")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Apply the config's global-attribute sections / global_attributes and ``--doi`` to the file.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``file``, ``config``, ``doi``.

    Returns
    -------
    int
        0 on success, 1 on a handled error, 2 when nothing is given to set.

    """
    from seagliderOG1 import writers

    if args.config is None and args.doi is None:
        print("error: give a mission.yaml, --doi, or both.", file=sys.stderr)
        return 2
    try:
        path = writers.enrich(args.file, mission=args.config, doi=args.doi)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"enriched {path}")
    return 0
