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
  seagliderOG1 inspect sg005_20080606_delayed.nc --conversion what the conversion did
"""


def _conversion_text(ds: object) -> str | None:
    """Return the conversion ledger as text, or None if the file predates the ledger.

    Reads only the ledger globals an OG1 file carries (``conversion_dimensions``,
    ``conversion_derived_variables``, ``conversion_dropped_variables``,
    ``conversion_attribute_sources``, ``history``) — nothing from conversion-time state.

    Parameters
    ----------
    ds : object
        An open ``xarray.Dataset`` for an OG1 file.

    Returns
    -------
    str or None
        The multi-section text, or None when ``conversion_dimensions`` is absent (the
        file predates the conversion ledger).

    """
    import json

    if "conversion_dimensions" not in ds.attrs:
        return None

    out = ["Dimensions", f"  {'dimension':22s} {'fate':9s} {'n':>3s}  variables"]
    dims = json.loads(ds.attrs["conversion_dimensions"])
    for dim in sorted(dims):
        info = dims[dim]
        out.append(
            f"  {dim:22s} {info['fate']:9s} {len(info['variables']):>3d}  "
            f"{', '.join(info['variables'])}"
        )

    derived = set(json.loads(ds.attrs.get("conversion_derived_variables", "[]")))
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

    scalar_params = [
        name
        for name in sorted(ds.variables)
        if ds[name].attrs.get("storage_type") in ("constant_scalar", "per_dive_scalar")
    ]
    if scalar_params:
        out += [
            "",
            "Scalar parameters (name  original_name  storage  dives  missing  units)",
        ]
        for name in scalar_params:
            attrs = ds[name].attrs
            if attrs.get("storage_type") == "per_dive_scalar":
                values = json.loads(str(ds[name].values)).get("values", [])
                storage = "per-dive JSON"
                dives = str(len(values))
                missing = str(sum(value is None for value in values))
            else:
                storage, dives, missing = "constant", "-", "-"
            out.append(
                f"  {name:28s} {str(attrs.get('original_name', '')):24s} "
                f"{storage:13s} {dives:>5s} {missing:>7s}  {attrs.get('units', '')}"
            )

    dropped = json.loads(ds.attrs.get("conversion_dropped_variables", "[]"))
    out += [
        "",
        "Dropped variables",
        "  " + (", ".join(dropped) if dropped else "(none)"),
    ]

    out += ["", "Global attributes by source"]
    sources = json.loads(ds.attrs["conversion_attribute_sources"])
    for category in sorted(sources):
        out.append(f"  {category}: {', '.join(sources[category])}")

    out += ["", "History"]
    out += [f"  {line}" for line in str(ds.attrs.get("history", "")).splitlines()]

    return "\n".join(out)


def _parameter_text(ds: object, name: str) -> str | None:
    """Return one per-dive JSON scalar decoded to a dive/value table, or None.

    Parameters
    ----------
    ds : object
        An open ``xarray.Dataset`` for an OG1 file.
    name : str
        The variable to decode.

    Returns
    -------
    str or None
        The dive/value table, or None when ``name`` is absent or is not a per-dive
        JSON scalar.

    """
    import json

    if name not in ds.variables:
        return None
    attrs = ds[name].attrs
    if attrs.get("storage_type") != "per_dive_scalar":
        return None

    payload = json.loads(str(ds[name].values))
    units = attrs.get("units", "")
    out = [
        f"{name} (per-dive JSON scalar; original_name "
        f"{attrs.get('original_name', name)})",
        f"  {'dive':>6s}  value" + (f" ({units})" if units else ""),
    ]
    for dive, value in zip(payload["dives"], payload["values"], strict=True):
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
    view.add_argument(
        "--conversion",
        action="store_true",
        help="show what the conversion recorded (dimensions, variables, dropped, sources)",
    )
    parser.add_argument(
        "--parameter",
        metavar="NAME",
        help="decode one per-dive JSON scalar to a dive/value table",
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

    if args.parameter:
        try:
            text = _parameter_text(ds, args.parameter)
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
            text = _conversion_text(ds)
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
        if args.output:
            print(
                "[report] extra not installed; the conversion HTML page needs it — "
                "printed the text instead",
                file=sys.stderr,
            )
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
    # The HTML inventory page (-o/--title) comes from glidertest via the [report]
    # extra; until then, say so when those flags are given rather than ignoring them.
    if args.output or args.title:
        print(
            "[report] extra not installed; printed the text table instead — "
            "pip install 'seagliderOG1[report]' for the HTML inventory page",
            file=sys.stderr,
        )
    return 0
