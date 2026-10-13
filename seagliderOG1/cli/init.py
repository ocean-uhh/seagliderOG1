"""The ``init`` verb: write a commented mission.yaml template.

``--from DIR`` reads the first basestation file in DIR and fills the platform
block from its attributes; without it, the platform block carries defaults.
"""

import argparse
import pathlib
import sys

from seagliderOG1.cli import _mission


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``init`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``init`` subparser.

    """
    parser = subparsers.add_parser(
        "init", help="write a commented mission.yaml template"
    )
    parser.add_argument(
        "--from",
        dest="from_dir",
        metavar="DIR",
        help="basestation directory to read the platform block from",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="mission.yaml",
        help="output path (default: mission.yaml)",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing file"
    )
    parser.set_defaults(func=run)
    return parser


def _platform_from_file(source: str) -> dict[str, object]:
    """Read platform fields from the first basestation file in ``source``.

    Parameters
    ----------
    source : str
        Directory (or URL) holding basestation ``pSSSDDDD*.nc`` files.

    Returns
    -------
    dict of str to object
        Platform values derived from the file's global attributes; only the
        fields present in the file are included.

    Raises
    ------
    ValueError
        If no basestation file is found in ``source``.

    """
    import os

    import xarray as xr

    from seagliderOG1 import readers, vocabularies

    names = [f for f in readers.list_files(source) if readers.validate_filename(f)]
    if not names:
        msg = f"no basestation files (pSSSDDDD*.nc) in {source}"
        raise ValueError(msg)
    ds = xr.open_dataset(
        os.path.join(source, names[0]), engine="netcdf4", decode_timedelta=False
    )
    try:
        # The one file->field mapping lives in vocabularies, shared with the converter.
        return vocabularies.platform_from_file(ds.attrs)
    finally:
        ds.close()


def run(args: argparse.Namespace) -> int:
    """Write the mission template to ``args.output``.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``from_dir``, ``output``, ``force``.

    Returns
    -------
    int
        0 on success, 1 on a handled error.

    """
    out = pathlib.Path(args.output)
    if out.exists() and not args.force:
        print(f"error: {out} exists; use --force to overwrite.", file=sys.stderr)
        return 1

    platform: dict[str, object] = {}
    source: str | None = None
    if args.from_dir:
        try:
            platform = _platform_from_file(args.from_dir)
        except (FileNotFoundError, ValueError, OSError, KeyError) as exc:
            print(
                f"error: could not read platform from {args.from_dir}: {exc}",
                file=sys.stderr,
            )
            return 1
        source = str(pathlib.Path(args.from_dir).resolve())

    out.write_text(_mission.render_template(platform, source=source))
    print(f"wrote {out}")
    return 0
