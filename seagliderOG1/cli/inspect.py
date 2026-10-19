"""The ``inspect`` verb: the inventory of one netCDF file.

Prints a text inventory (useful at sea, no browser). ``inspect --conversion`` prints the
conversion ledger; the HTML conversion page is the ``report`` verb's. Works on a basestation
or an OG1 file.
"""

import argparse
import pathlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xarray as xr

_EPILOG = """\
Examples:
  seagliderOG1 inspect sg005_20080606_delayed.nc              variables as a table
  seagliderOG1 inspect sg005_20080606_delayed.nc --attrs      global attributes
  seagliderOG1 inspect p0050001.nc --by-dimension sg_data_point
  seagliderOG1 inspect sg005_20080606_delayed.nc --conversion what the conversion did
"""


def _scalar_row(name: str, entry: dict) -> str:
    """Return one Scalar-parameters table row from a ``conversion_ledger`` entry.

    Parameters
    ----------
    name : str
        The scalar variable name.
    entry : dict
        Its ``conversion_ledger`` ``scalar_parameters`` entry.

    Returns
    -------
    str
        The formatted row (name, original_name, storage, dives, missing, units).

    """
    if entry["storage"] == "per_dive_scalar":
        values = entry["values"]
        storage, dives, missing = (
            "per-dive JSON",
            str(len(values)),
            str(sum(value is None for value in values)),
        )
    else:
        storage, dives, missing = "constant", "-", "-"
    return (
        f"  {name:28s} {str(entry.get('original_name') or ''):24s} "
        f"{storage:13s} {dives:>5s} {missing:>7s}  {entry['units']}"
    )


def _conversion_text(ds: "xr.Dataset", show_all: bool = False) -> str | None:
    """Return the conversion ledger as text, or None if the file predates the ledger.

    Reads the parsed ledger from :func:`seagliderOG1.convert.conversion_ledger` (the
    same accessor the HTML page uses) plus each variable's own attributes — nothing
    from conversion-time state.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset for an OG1 file.
    show_all : bool, optional
        List the constant scalars in full as well as the per-dive ones. Default is
        False (constants are summarised as a count).

    Returns
    -------
    str or None
        The multi-section text, or None when ``conversion_dimensions`` is absent (the
        file predates the conversion ledger).

    """
    from seagliderOG1 import convert

    if "conversion_dimensions" not in ds.attrs:
        return None
    ledger = convert.conversion_ledger(ds)

    out = ["Dimensions", f"  {'dimension':22s} {'fate':9s} {'n':>3s}  variables"]
    for dim in sorted(ledger["dimensions"]):
        info = ledger["dimensions"][dim]
        out.append(
            f"  {dim:22s} {info['fate']:9s} {len(info['variables']):>3d}  "
            f"{', '.join(info['variables'])}"
        )

    derived = set(ledger["derived"])
    out += ["", "Variables (OG1 name  origin  [original_dimension]  units)"]
    for name in sorted(ds.variables):
        attrs = ds[name].attrs
        original_name = attrs.get("original_name")
        if name in derived:
            origin = "(derived)"
        elif original_name == name:
            origin = "(unmapped)"
        else:
            origin = f"<- {original_name}"
        dimension = attrs.get("original_dimension", "")
        marker = (
            " [per-dive JSON]" if attrs.get("storage_type") == "per_dive_scalar" else ""
        )
        out.append(
            f"  {name:28s} {origin:26s} "
            f"{('[' + dimension + ']') if dimension else '':18s} "
            f"{attrs.get('units', '')}{marker}"
        )

    scalars = ledger["scalar_parameters"]
    per_dive = sorted(
        n for n, e in scalars.items() if e["storage"] == "per_dive_scalar"
    )
    constants = sorted(
        n for n, e in scalars.items() if e["storage"] == "constant_scalar"
    )
    if scalars:
        out += [
            "",
            "Scalar parameters (name  original_name  storage  dives  missing  units)",
        ]
        # The per-dive scalars are the thing to check; list them in full. Constants are
        # sg_cal and friends — summarise as a count unless --all asked for them.
        out += [_scalar_row(n, scalars[n]) for n in per_dive]
        if show_all:
            out += [_scalar_row(n, scalars[n]) for n in constants]
        elif constants:
            out.append(
                f"  {len(constants)} constant scalars (storage_type: constant_scalar) "
                "— inspect --conversion --all to list"
            )

    dropped = ledger["dropped"]
    out += [
        "",
        "Dropped variables",
        "  " + (", ".join(dropped) if dropped else "(none)"),
    ]

    out += ["", "Global attributes by source"]
    for category in sorted(ledger["attribute_sources"]):
        out.append(f"  {category}: {', '.join(ledger['attribute_sources'][category])}")

    out += ["", "History"]
    out += [f"  {line}" for line in ledger["history"].splitlines()]

    return "\n".join(out)


def _parameter_text(ds: "xr.Dataset", name: str) -> str | None:
    """Return one per-dive JSON scalar decoded to a dive/value table, or None.

    Parameters
    ----------
    ds : xarray.Dataset
        An open dataset for an OG1 file.
    name : str
        The variable to decode.

    Returns
    -------
    str or None
        The dive/value table, or None when ``name`` is absent or is not a per-dive
        JSON scalar.

    Raises
    ------
    MetadataError
        If ``name`` is a per-dive scalar whose value is not valid per-dive JSON.

    """
    from seagliderOG1 import convert

    if (
        name not in ds.variables
        or ds[name].attrs.get("storage_type") != "per_dive_scalar"
    ):
        return None

    entry = convert.conversion_ledger(ds)["scalar_parameters"][name]
    units = entry["units"]
    out = [
        f"{name} (per-dive JSON scalar; original_name "
        f"{entry.get('original_name') or name})",
        f"  {'dive':>6s}  value" + (f" ({units})" if units else ""),
    ]
    for dive, value in zip(entry["dives"], entry["values"], strict=True):
        out.append(f"  {dive:>6}  {'null' if value is None else value}")
    return "\n".join(out)


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
            "Show the inventory of one basestation or OG1 netCDF file as a text table. "
            "With --conversion, print the conversion ledger; with --conversion -o, write "
            "the HTML conversion page."
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
    view.add_argument(
        "--conversion",
        action="store_true",
        help="show what the conversion recorded (dimensions, variables, dropped, sources)",
    )
    view.add_argument(
        "--parameter",
        metavar="NAME",
        help="decode one per-dive JSON scalar to a dive/value table",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="with --conversion, list the constant scalars in full (not just a count)",
    )
    # The HTML page moved to the report verb; these stay, hidden, to say so.
    parser.add_argument("-o", "--output", help=argparse.SUPPRESS)
    parser.add_argument("--title", help=argparse.SUPPRESS)
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Print a text inventory of a netCDF file.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``file``, ``attrs``, ``variables``, ``by_dimension``,
        ``conversion``, ``parameter``, ``all``; ``output`` / ``title`` only to point at
        ``report``.

    Returns
    -------
    int
        0 on success, 1 when the file is missing.

    """
    import xarray as xr

    from seagliderOG1 import plotters
    from seagliderOG1.exceptions import MetadataError

    if args.output or args.title:
        print(
            "error: inspect prints text only; the HTML conversion page is written by "
            f"'seagliderOG1 report {args.file} [-o DIR]'.",
            file=sys.stderr,
        )
        return 2

    if not args.file.is_file():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 1

    ds = xr.open_dataset(str(args.file), engine="netcdf4", decode_timedelta=False)

    if args.parameter:
        try:
            text = _parameter_text(ds, args.parameter)
        except MetadataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            ds.close()
        if text is None:
            print(
                f"error: {args.parameter} is not a per-dive JSON scalar in {args.file}",
                file=sys.stderr,
            )
            return 1
        print(text)
        return 0

    if args.conversion:
        try:
            text = _conversion_text(ds, show_all=args.all)
        except MetadataError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            ds.close()
        if text is None:
            print(
                f"error: {args.file} has no conversion ledger (no "
                "'conversion_dimensions' global); it predates the ledger.",
                file=sys.stderr,
            )
            return 1
        print(text)
        return 0

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
    return 0
