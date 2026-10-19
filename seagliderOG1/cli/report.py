"""The ``report`` verb: write the HTML conversion page for an OG1 file.

The page goes beside the file by default; ``-o DIR`` puts it directly in DIR and
``--report-dir ROOT`` in ``ROOT/<id>/`` (the family's two output flags), so pages can
live apart from the archived data. The sidecar stays beside the ``.nc``: the page reads
it from there.
"""

import argparse
import pathlib
import sys


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``report`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``report`` subparser.

    """
    parser = subparsers.add_parser(
        "report",
        help="write the HTML conversion page for an OG1 file",
        description=(
            "Write <id>_conversion.html for an OG1 file written by seagliderOG1: "
            "beside the file, in -o DIR, or in --report-dir ROOT/<id>/."
        ),
        epilog=(
            "examples:\n"
            "  seagliderOG1 report out/<id>.nc                       beside the file\n"
            "  seagliderOG1 report out/<id>.nc -o pages/             into pages/\n"
            "  seagliderOG1 report out/<id>.nc --report-dir site/    into site/<id>/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "files", nargs="+", type=pathlib.Path, help="OG1 netCDF file(s)"
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "-o", "--output-dir", metavar="DIR", help="write the page(s) directly into DIR"
    )
    where.add_argument(
        "--report-dir", metavar="ROOT", help="write each page into ROOT/<id>/"
    )
    parser.add_argument("--title", metavar="TEXT", help="title for the page")
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing page"
    )
    parser.set_defaults(func=run)
    return parser


def page_target(
    nc_path: pathlib.Path,
    output_dir: str | None = None,
    report_dir: str | None = None,
) -> pathlib.Path:
    """Return where the conversion page for ``nc_path`` is written.

    Parameters
    ----------
    nc_path : pathlib.Path
        The OG1 file.
    output_dir : str or None, optional
        ``-o DIR``: the page goes directly into DIR.
    report_dir : str or None, optional
        ``--report-dir ROOT``: the page goes into ``ROOT/<stem>/``.

    Returns
    -------
    pathlib.Path
        ``<stem>_conversion.html`` beside the file, in DIR, or in ``ROOT/<stem>/``.

    """
    from seagliderOG1 import writers

    name = writers.conversion_path(nc_path, ".html").name
    if report_dir:
        return pathlib.Path(report_dir) / nc_path.stem / name
    if output_dir:
        return pathlib.Path(output_dir) / name
    return nc_path.with_name(name)


def write_page(
    nc_path: pathlib.Path,
    target: pathlib.Path,
    *,
    title: str | None = None,
    force: bool = False,
) -> str | None:
    """Render and write one conversion page; return an error message or None.

    Parameters
    ----------
    nc_path : pathlib.Path
        The OG1 file.
    target : pathlib.Path
        Where the page goes (from :func:`page_target`).
    title : str or None, optional
        Page title; the file name by default.
    force : bool, optional
        Overwrite an existing page. Default is False.

    Returns
    -------
    str or None
        None when written, else the reason it was not (one line, for stderr).

    """
    from seagliderOG1.exceptions import MetadataError
    from seagliderOG1.reports.conversion import render_conversion

    if not nc_path.is_file():
        return f"file not found: {nc_path}"
    if target.exists() and not force:
        return f"{target} exists; use --force to overwrite"
    try:
        html = render_conversion(nc_path, title=title, verify=True)
    except (MetadataError, OSError, ValueError) as exc:
        return f"{nc_path}: {type(exc).__name__}: {exc}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    except OSError as exc:
        return f"could not write {target}: {exc}"
    return None


def run(args: argparse.Namespace) -> int:
    """Write the conversion page for each file.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``files``, ``output_dir``, ``report_dir``, ``title``,
        ``force``.

    Returns
    -------
    int
        0 when every page is written, 1 when any is not (the others are still
        written).

    """
    failed = 0
    for nc_path in args.files:
        target = page_target(nc_path, args.output_dir, args.report_dir)
        error = write_page(nc_path, target, title=args.title, force=args.force)
        if error:
            print(f"error: {error}", file=sys.stderr)
            failed += 1
            continue
        print(f"wrote {target}")
    return 1 if failed else 0
