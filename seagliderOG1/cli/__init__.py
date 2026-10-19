"""Command-line interface for seagliderOG1.

Defines the ``seagliderOG1`` command as a top-level argument parser with one
subcommand per verb. Each verb lives in its own module exposing
``build_parser(subparsers)`` and ``run(args) -> int``. Building the parser (and
therefore ``--help``) must not import xarray or matplotlib, so verb modules
import those inside ``run`` rather than at module load.
"""

import argparse
import logging
import os
from collections.abc import Sequence

from seagliderOG1 import __version__
from seagliderOG1.cli import draft as draft_cmd
from seagliderOG1.cli import enrich as enrich_cmd
from seagliderOG1.cli import init as init_cmd
from seagliderOG1.cli import inspect as inspect_cmd
from seagliderOG1.cli import list as list_cmd
from seagliderOG1.cli import process as process_cmd
from seagliderOG1.cli import report as report_cmd
from seagliderOG1.cli import validate as validate_cmd

_EPILOG = """\
typical workflow:
  seagliderOG1 draft --raw-dir /data/005/20080606             look at the data, no config
  seagliderOG1 init sg005.yaml --raw-dir /data/005/20080606   template from the first file
  seagliderOG1 validate sg005.yaml                            config, raw_dir, dive range
  seagliderOG1 process  sg005.yaml                            -> <output_dir>/<OG1 id>.nc
  seagliderOG1 report   <output_dir>/<OG1 id>.nc              the conversion page
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
    for module in (
        draft_cmd,
        init_cmd,
        validate_cmd,
        process_cmd,
        report_cmd,
        enrich_cmd,
        inspect_cmd,
        list_cmd,
    ):
        module.build_parser(subparsers)
    # Accept -v/--verbose after the verb (``seagliderOG1 process cfg -v``), not only
    # before it; SUPPRESS default so a verb-level -v never clobbers a top-level one.
    for sub in subparsers.choices.values():
        sub.add_argument(
            "-v",
            "--verbose",
            action="count",
            default=argparse.SUPPRESS,
            help=argparse.SUPPRESS,
        )
    return parser


def _configure_logging(verbose: int) -> None:
    """Route the package's own diagnostics to stderr at a level set by ``-v``.

    Parameters
    ----------
    verbose : int
        Count of ``-v`` flags: 0 leaves the ``seagliderOG1`` logger at
        ``WARNING``, 1 shows ``INFO`` progress, 2 or more shows ``DEBUG``. Only
        the package's own ``logging`` output is affected — the root logger (and
        so third-party libraries) is left alone, and command results stay on
        stdout via ``print``.

    """
    level = logging.WARNING
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    logger = logging.getLogger("seagliderOG1")
    logger.setLevel(level)
    # Rebuild the one stderr handler each call so it binds to the current
    # sys.stderr (test capture) and does not accumulate on repeated main() calls.
    for existing in logger.handlers[:]:
        logger.removeHandler(existing)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


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
    # The CLI only ever renders figures to a PNG in the conversion page, never to a
    # screen, so force a non-interactive matplotlib backend: on an interactive shell
    # (macOS defaults to `macosx`) the first figure otherwise blocks on a GUI window.
    # An env var, not matplotlib.use(), so building the parser still imports no
    # matplotlib; setdefault leaves a backend the user set themselves untouched.
    os.environ.setdefault("MPLBACKEND", "Agg")
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return args.func(args)
