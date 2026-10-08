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
        0 when valid, 1 when any ERROR is found, 2 when the file is missing.

    """
    path = pathlib.Path(args.config)
    if not path.is_file():
        print(f"error: config not found: {path}", file=sys.stderr)
        return 2

    issues = _mission.validate_config(path, strict=args.strict)
    for issue in issues:
        where = f" [{issue.key}]" if issue.key else ""
        stream = sys.stderr if issue.level == "ERROR" else sys.stdout
        print(f"{issue.level}{where}: {issue.message}", file=stream)

    errors = [i for i in issues if i.level == "ERROR"]
    if errors:
        print(f"{len(errors)} error(s); configuration invalid.", file=sys.stderr)
        return 1
    print(f"{path} is valid.")
    return 0
