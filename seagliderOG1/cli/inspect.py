"""The ``inspect`` verb: the inventory of one netCDF file.

Family-wide ``inspect`` writes a self-contained HTML inventory page for one file. Here
the HTML page comes from glidertest through the ``seagliderOG1[report]`` extra; until
that extra exists, ``inspect`` prints a text table (useful at sea, no browser) and notes
on stderr that the HTML page needs the extra. Works on a basestation or an OG1 file.
"""

import argparse
import pathlib
import sys

_EPILOG = """\
Examples:
  seagliderOG1 inspect sg005_20080606_delayed.nc              variables as a table
  seagliderOG1 inspect sg005_20080606_delayed.nc --attrs      global attributes
  seagliderOG1 inspect p0050001.nc --by-dimension sg_data_point
"""


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``inspect`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``inspect`` subparser.

    """
    parser = subparsers.add_parser(
        "inspect",
        help="show the inventory of one netCDF file",
        description=(
            "Show the inventory of one basestation or OG1 netCDF file. Writes an HTML "
            "inventory page with the seagliderOG1[report] extra; otherwise prints a "
            "text table."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "file", type=pathlib.Path, help="path to a basestation or OG1 netCDF file"
    )
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--attrs", action="store_true", help="show global attributes")
    view.add_argument(
        "--variables", action="store_true", help="show variables (the default)"
    )
    view.add_argument(
        "--by-dimension", metavar="DIM", help="show only variables on dimension DIM"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="HTML",
        help="write the HTML inventory page to this path",
    )
    parser.add_argument("--title", metavar="TEXT", help="title for the inventory page")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Print the file inventory as a text table (HTML page pending the report extra).

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``file``, ``attrs``, ``variables``, ``by_dimension``,
        ``output`` and ``title``.

    Returns
    -------
    int
        0 on success, 1 when the file is missing.

    """
    import xarray as xr

    from seagliderOG1 import plotters

    if not args.file.is_file():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 1

    ds = xr.open_dataset(str(args.file), engine="netcdf4", decode_timedelta=False)
    try:
        if args.attrs:
            table = plotters.show_attributes(ds)
        elif args.by_dimension:
            table = plotters.show_variables_by_dimension(ds, args.by_dimension)
        else:
            table = plotters.show_variables(ds)
    finally:
        ds.close()

    # plotters returns a pandas Styler for variable tables; render its frame.
    frame = getattr(table, "data", table)
    print(frame.to_string())
    # The HTML inventory page (-o/--title) comes from glidertest via the [report]
    # extra; until then, say so when those flags are given rather than ignoring them.
    if args.output or args.title:
        print(
            "[report] extra not installed; printed the text table instead — "
            "pip install 'seagliderOG1[report]' for the HTML inventory page",
            file=sys.stderr,
        )
    return 0
