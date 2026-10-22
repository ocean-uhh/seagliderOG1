"""The ``draft`` verb: look at a mission's basestation files with no config.

Runs the real converter with no mission config and writes, into ``-o DIR``:
``<id>_draft.nc``, ``<id>_draft_conversion.html`` (the conversion page in draft form,
with the basestation's own global attributes), ``<id>_draft_conversion.json`` (the
conversion record) and ``<id>_draft_mission.yaml`` (an ``init`` template with the values the
draft could work out from every dive filled in). None of it is an OG1 file: every name
ends ``_draft``, the netCDF carries a ``draft`` global and no ``OG-1.0`` in
``Conventions``.
"""

import argparse
import pathlib
import sys

from seagliderOG1.cli import _mission


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``draft`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``draft`` subparser.

    """
    parser = subparsers.add_parser(
        "draft",
        help="convert with no config to see what the basestation files hold (not OG1)",
        description=(
            "Convert one mission with no mission config and write a draft netCDF, its "
            "conversion page and a proposed mission.yaml. Nothing written is an OG1 "
            "file: every name ends _draft."
        ),
        epilog=(
            "example:\n"
            "  seagliderOG1 draft --raw-dir /data/005/20080606 -o drafts/\n"
            "  then: seagliderOG1 init sg005.yaml --raw-dir /data/005/20080606, or edit\n"
            "  drafts/<id>_draft_mission.yaml, validate it and process it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--raw-dir",
        required=True,
        metavar="DIR",
        help="one mission directory of basestation files (pSSSDDDD*.nc)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        metavar="DIR",
        help="where the draft files go (default: .)",
    )
    parser.add_argument(
        "--dives",
        nargs=2,
        type=int,
        metavar=("FIRST", "LAST"),
        help="dive range to convert (default: every file)",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing draft files"
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace) -> int:
    """Write the draft netCDF, its page and a proposed mission.yaml.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: ``raw_dir``, ``output_dir``, ``dives``, ``force``.

    Returns
    -------
    int
        0 on success, 1 on a handled error.

    """
    import json

    from seagliderOG1 import _convert, writers
    from seagliderOG1.reports import _record

    raw_dir = pathlib.Path(args.raw_dir)
    if not raw_dir.is_dir():
        print(f"error: --raw-dir is not a directory: {raw_dir}", file=sys.stderr)
        return 1
    try:
        path = _convert._convert_mission(
            raw_dir,
            args.output_dir,
            dives=tuple(args.dives) if args.dives else None,
            overwrite=args.force,
            report=True,
            draft=True,
        )
    except FileExistsError as exc:
        print(
            f"error: {exc.filename} exists; use --force to overwrite", file=sys.stderr
        )
        return 1
    # One mission's conversion error is reported on one line, as process does.
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED {raw_dir}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    # The proposal: what init writes, plus the dive range the draft read and the
    # platform fields the converter derived from the files (from the sidecar).
    # the converter refused to start if it already existed (without --force). The
    # derived id goes in a comment, not in identity_and_discovery.id: a fixed id would go
    # stale if dives change.
    sidecar_path = writers.conversion_path(path, ".json")
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"error: could not read {sidecar_path}: {exc}", file=sys.stderr)
        return 1
    dives = sidecar["presence"]["dives"]
    platform = sidecar.get("platform_from_file")
    if platform is None:
        print(
            "warning: the conversion record has no platform_from_file; the proposed "
            "platform: block is all null.",
            file=sys.stderr,
        )
    proposal = writers.proposal_path(path)
    header = (
        f"# Proposed by seagliderOG1 draft from {len(dives)} dive files. With these dives "
        f"the derived id is\n# {path.stem.removesuffix('_draft')} (leave "
        "identity_and_discovery.id null to keep it derived).\n"
    )
    template = _mission.render_template(
        platform, raw_dir=str(raw_dir.resolve()), dives=[dives[0], dives[-1]]
    )
    try:
        proposal.write_text(header + template, encoding="utf-8")
    except OSError as exc:
        print(f"error: could not write {proposal}: {exc}", file=sys.stderr)
        return 1

    for written in (
        path,
        writers.conversion_path(path, ".html"),
        sidecar_path,
        proposal,
    ):
        print(f"wrote {written}")
    summary = _record.presence_summary(sidecar["presence"])
    if summary:
        print(f"  {path.stem}: {summary}")
    return 0
