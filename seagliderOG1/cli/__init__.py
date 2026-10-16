"""Command-line interface for seagliderOG1.

Defines the ``seagliderOG1`` command as a top-level argument parser with one
subcommand per verb. Each verb lives in its own module exposing
``build_parser(subparsers)`` and ``run(args) -> int``. Building the parser (and
therefore ``--help``) must not import xarray or matplotlib, so verb modules
import those inside ``run`` rather than at module load.
"""

import argparse
import logging
from collections.abc import Sequence

from seagliderOG1 import __version__
from seagliderOG1.cli import init as init_cmd
from seagliderOG1.cli import inspect as inspect_cmd
from seagliderOG1.cli import list as list_cmd
from seagliderOG1.cli import process as process_cmd
from seagliderOG1.cli import validate as validate_cmd

_EPILOG = """\
typical workflow:
  seagliderOG1 init --from /data/005/20080606 -o sg005.yaml   template from the first file
  seagliderOG1 validate sg005.yaml                            config, source, dive range
  seagliderOG1 process  sg005.yaml                            -> <output_dir>/<OG1 id>.nc
"""


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
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="library diagnostics to stderr: -v for progress (INFO), -vv for debug",
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", required=True
    )
    for module in (init_cmd, validate_cmd, process_cmd, inspect_cmd, list_cmd):
        module.build_parser(subparsers)
    return parser


def _configure_logging(verbose: int) -> None:
    """Route library diagnostics to stderr at a level set by ``-v``.

    Parameters
    ----------
    verbose : int
        Count of ``-v`` flags: 0 leaves the default (``WARNING`` and above), 1
        shows ``INFO`` progress, 2 or more shows ``DEBUG``. Only library
        ``logging`` output is affected; command results stay on stdout via
        ``print``. ``force=True`` so a repeated ``main`` call reconfigures.

    """
    level = logging.WARNING
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", force=True)


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
    _configure_logging(args.verbose)
    return args.func(args)
