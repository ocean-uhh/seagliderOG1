"""Command-line interface for seagliderOG1.

Defines the ``seagliderOG1`` command as a top-level argument parser with one
subcommand per verb. Each verb lives in its own module exposing
``build_parser(subparsers)`` and ``run(args) -> int``. Building the parser (and
therefore ``--help``) must not import xarray or matplotlib, so verb modules
import those inside ``run`` rather than at module load.
"""

import argparse
from collections.abc import Sequence

from seagliderOG1.cli import init as init_cmd
from seagliderOG1.cli import validate as validate_cmd

_EPILOG = """\
typical workflow:
  seagliderOG1 init --from /data/005/20080606 -o sg005.yaml   template from the first file
  seagliderOG1 validate sg005.yaml                            config, source, dive range
  seagliderOG1 process  sg005.yaml                            -> <output_dir>/<OG1 id>.nc
"""


def _version() -> str:
    """Return the installed package version, or ``"unknown"`` if undetermined.

    Returns
    -------
    str
        The distribution version string.

    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("seagliderOG1")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every verb subparser attached.

    Returns
    -------
    argparse.ArgumentParser
        The configured parser. Each subparser sets ``func`` to its ``run``.

    """
    parser = argparse.ArgumentParser(
        prog="seagliderOG1",
        description="Convert Seaglider basestation files to OG1 format.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", required=True
    )
    for module in (init_cmd, validate_cmd):
        module.build_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected verb.

    Parameters
    ----------
    argv : sequence of str or None, optional
        Argument list to parse. Defaults to ``sys.argv[1:]`` when None.

    Returns
    -------
    int
        Process exit code: 0 on success, 1 on a handled error, 2 on a usage error.

    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
