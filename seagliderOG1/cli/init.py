"""The ``init`` verb: write a commented mission.yaml template.

``init [dest]`` follows ctdcast's shape: ``dest`` is a directory (``mission.yaml`` is
written inside it) or a ``.yaml`` file name; default the current directory.
``--raw-dir PATH`` reads the first basestation file in PATH (or PATH itself, one file)
and fills the platform block and ``raw_dir`` from it; without it they are left null.
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
        "init",
        help="write a commented mission.yaml template",
        description=(
            "Write a commented mission.yaml. dest is a directory (mission.yaml is "
            "written inside) or a .yaml file name; default the current directory."
        ),
        epilog=(
            "examples:\n"
            "  seagliderOG1 init                                  ./mission.yaml\n"
            "  seagliderOG1 init outputs/ --raw-dir /data/005/    outputs/mission.yaml\n"
            "  seagliderOG1 init sg005.yaml --raw-dir /data/005/  that file"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default=".",
        help="directory (mission.yaml inside) or a .yaml file name (default: .)",
    )
    parser.add_argument(
        "--raw-dir",
        metavar="PATH",
        help=(
            "basestation directory, or one pSSSDDDD*.nc file in it, to fill raw_dir "
            "and the platform block from"
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing file"
    )
    parser.set_defaults(func=run)
    return parser


def _platform_from_file(source: str) -> dict[str, object]:
    """Read platform fields from a basestation file, or the first one in ``source``.

    Parameters
    ----------
    source : str
        One basestation ``pSSSDDDD*.nc`` file, or a directory (or URL) holding them.

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
    import xarray as xr

    from seagliderOG1 import readers, vocabularies

    if pathlib.Path(source).is_file():
        if not readers.validate_filename(pathlib.Path(source).name):
            msg = f"{source} is not a basestation file (pSSSDDDD*.nc)"
            raise ValueError(msg)
        path = pathlib.Path(source)
    else:
        names = [f for f in readers.list_files(source) if readers.validate_filename(f)]
        if not names:
            msg = f"no basestation files (pSSSDDDD*.nc) in {source}"
            raise ValueError(msg)
        path = pathlib.Path(source) / names[0]
    ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
    try:
        # The one file->field mapping lives in vocabularies, shared with the converter.
        return vocabularies.platform_from_file(ds.attrs)
    finally:
        ds.close()


def _config_target(dest: str) -> pathlib.Path:
    """Return the file ``init`` writes for ``dest``.

    Parameters
    ----------
    dest : str
        A directory (existing, or a path not ending in ``.yaml``/``.yml``) or a
        ``.yaml`` file name.

    Returns
    -------
    pathlib.Path
        ``dest/mission.yaml`` for a directory, else ``dest``.

    """
    path = pathlib.Path(dest)
    if path.suffix.lower() in (".yaml", ".yml") and not path.is_dir():
        return path
    return path / "mission.yaml"


def run(args: argparse.Namespace) -> int:
    """Write the mission template to the file ``args.dest`` names.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``dest``, ``raw_dir``, ``force``.

    Returns
    -------
    int
        0 on success, 1 on a handled error.

    """
    out = _config_target(args.dest)
    if out.exists() and not args.force:
        print(f"error: {out} exists; use --force to overwrite.", file=sys.stderr)
        return 1

    platform: dict[str, object] = {}
    raw_dir: str | None = None
    if args.raw_dir:
        try:
            platform = _platform_from_file(args.raw_dir)
        except (FileNotFoundError, ValueError, OSError, KeyError) as exc:
            print(
                f"error: could not read platform from {args.raw_dir}: {exc}",
                file=sys.stderr,
            )
            return 1
        # raw_dir: is the directory of files to convert, also when given one file.
        raw_path = pathlib.Path(args.raw_dir).resolve()
        raw_dir = str(raw_path.parent if raw_path.is_file() else raw_path)

    # Always UTF-8: the template carries non-ASCII glyphs (the "→" destination
    # markers) and may hold non-ASCII values (e.g. an accented platform model or
    # institution name), and mission.yaml is read back with encoding="utf-8", so a
    # non-UTF-8 OS locale must not decide the on-disk encoding.
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            _mission.render_template(platform, raw_dir=raw_dir), encoding="utf-8"
        )
    except OSError as exc:
        print(f"error: could not write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0
