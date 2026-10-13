"""The ``validate`` verb: check a mission.yaml for errors before converting."""

import argparse
import pathlib
import sys

from seagliderOG1.cli import _mission


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``validate`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``validate`` subparser.

    """
    parser = subparsers.add_parser("validate", help="check a mission.yaml for errors")
    parser.add_argument("config", help="path to mission.yaml")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also require every dive in the range to be present (no gaps)",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Validate the configuration and report issues.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``config``, ``strict``.

    Returns
    -------
    int
        0 when valid, 1 when any ERROR is found or the file is missing. Exit 2 is
        reserved for argparse-level usage errors (see the CLI family convention).

    """
    path = pathlib.Path(args.config)
    if not path.is_file():
        print(f"error: config not found: {path}", file=sys.stderr)
        return 1

    issues = _mission.validate_config(path, strict=args.strict)
    if _mission.report_issues(issues):
        print(f"{path} is invalid.", file=sys.stderr)
        return 1
    print(f"{path} is valid.")
    return 0
