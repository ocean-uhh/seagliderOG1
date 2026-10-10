"""The ``process`` verb: convert basestation missions to OG1 files.

Resolves the source (a mission directory, or a root of ``SN/DATE`` missions selected
with ``--all``/``--mission``), converts each with the mission config's contributors,
institutions, platform and global attributes, and writes ``<output_dir>/<id>.nc``.
Each mission is attempted independently; one failure does not stop the run.
"""

import argparse
import fnmatch
import pathlib
import sys

from seagliderOG1.cli import _mission


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach the ``process`` subparser.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The subparser registry from the top-level parser.

    Returns
    -------
    argparse.ArgumentParser
        The ``process`` subparser.

    """
    parser = subparsers.add_parser(
        "process", help="convert basestation missions to OG1 files"
    )
    parser.add_argument("config", help="path to mission.yaml")
    parser.add_argument(
        "--source",
        metavar="DIR_OR_ROOT",
        help="override the config source (a mission dir or a root of SN/DATE dirs)",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--all", action="store_true", help="convert every SN/DATE mission under a root"
    )
    selection.add_argument(
        "--mission",
        metavar="GLOB",
        help="select missions by SN/DATE glob, e.g. '103/*'",
    )
    parser.add_argument(
        "-o", "--output-dir", metavar="DIR", help="override the config output_dir"
    )
    parser.add_argument(
        "--mode", choices=("realtime", "delayed"), help="override the config data mode"
    )
    parser.add_argument(
        "--dives",
        nargs=2,
        type=int,
        metavar=("FIRST", "LAST"),
        help="dive range to convert (overrides the config dives)",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="repair basestation time metadata before loading (writes the source tree)",
    )
    existing = parser.add_mutually_exclusive_group()
    existing.add_argument(
        "--force", action="store_true", help="overwrite an existing output file"
    )
    existing.add_argument(
        "--skip-existing",
        action="store_true",
        help="skip a mission whose output file already exists",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="print what would be written; write nothing",
    )
    parser.set_defaults(func=run)
    return parser


def _select_missions(
    missions: list, root: pathlib.Path, args: argparse.Namespace
) -> tuple[list, str | None]:
    """Select missions for a single dir or a root, returning (selected, error).

    Parameters
    ----------
    missions : list
        All missions discovered under ``root``.
    root : pathlib.Path
        The resolved source directory.
    args : argparse.Namespace
        Parsed arguments (``all``, ``mission``).

    Returns
    -------
    tuple of (list, str or None)
        The selected missions and an error message (or None).

    """
    from seagliderOG1 import readers

    if not readers.is_root(missions):
        if args.all or args.mission:
            return [], (
                "--all/--mission apply to a root of SN/DATE missions, not a single "
                "mission directory"
            )
        return missions, None
    glob = "*/*" if args.all else args.mission
    if not glob:
        return [], "source is a root of missions; select with --all or --mission GLOB"
    selected = [
        mission
        for mission in missions
        if fnmatch.fnmatch(str(pathlib.Path(mission.path).relative_to(root)), glob)
    ]
    if not selected:
        return [], f"--mission {glob!r} matched no missions under {root}"
    return selected, None


def run(args: argparse.Namespace) -> int:
    """Convert the selected missions and report a per-mission summary.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        0 when all selected missions convert, 1 on any failure, a resolution error,
        or a missing config file. Exit 2 is reserved for argparse-level usage errors
        (see the CLI family convention).

    """
    from seagliderOG1 import convertOG1, readers, writers

    config_path = pathlib.Path(args.config)
    if not config_path.is_file():
        print(f"error: config not found: {config_path}", file=sys.stderr)
        return 1

    # Validate the effective source (the --source override, if any), not the stale
    # config value, so an override can rescue a config whose own source is missing.
    issues = _mission.validate_config(config_path, source_override=args.source)
    if _mission.report_issues(issues):
        print("configuration invalid; not converting.", file=sys.stderr)
        return 1

    config = _mission.load_config(config_path)
    base = config_path.parent
    source = args.source if args.source else config.get("source")
    source_path = (base / str(source)).resolve()
    output_dir = (
        pathlib.Path(args.output_dir)
        if args.output_dir
        else (base / str(config.get("output_dir", "."))).resolve()
    )
    mode = args.mode or config.get("mode") or "delayed"
    config_dives = config.get("dives")
    dives = tuple(args.dives) if args.dives else config_dives
    first, last = (dives[0], dives[1]) if dives else (None, None)
    repair = bool(args.repair or config.get("repair", False))
    keep_variables = config.get("keep_variables")

    try:
        missions = readers.discover_missions(str(source_path))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not missions:
        print(
            f"error: no basestation missions found under {source_path}", file=sys.stderr
        )
        return 1

    selected, error = _select_missions(missions, source_path, args)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Plan: resolve mission -> dive range -> output target, purely. -n stops here.
    if args.dry_run:
        for mission in selected:
            lo = (
                first
                if first is not None
                else (min(mission.dives) if mission.dives else "?")
            )
            hi = (
                last
                if last is not None
                else (max(mission.dives) if mission.dives else "?")
            )
            print(f"{mission.path} dives [{lo}, {hi}] -> {output_dir}/<id>.nc")
        print(f"{len(selected)} would convert, 0 skipped, 0 failed")
        return 0

    # Act: the exists/--force/--skip-existing checks belong here, not in the plan.
    converted = skipped = failed = 0
    for mission in selected:
        try:
            datasets = readers.load_basestation_files(
                mission.path, first, last, repair=repair
            )
            ds, _ = convertOG1.convert_to_OG1(
                datasets,
                contributors=config.get("contributors"),
                institutions=config.get("institutions"),
                platform=config.get("platform"),
                global_attributes=config.get("global_attributes"),
                mode=mode,
            )
            if keep_variables:
                ds = convertOG1.apply_keep_variables(ds, keep_variables)
            out_path = output_dir / f"{ds.attrs['id']}.nc"
            if out_path.exists():
                if args.skip_existing:
                    print(f"skip (exists): {out_path}")
                    skipped += 1
                    continue
                if not args.force:
                    print(
                        f"error: {out_path} exists; use --force or --skip-existing",
                        file=sys.stderr,
                    )
                    failed += 1
                    continue
            output_dir.mkdir(parents=True, exist_ok=True)
            if not writers.save_dataset(ds, str(out_path), overwrite=args.force):
                print(
                    f"FAILED {mission.path}: save_dataset could not write {out_path}",
                    file=sys.stderr,
                )
                failed += 1
                continue
            print(f"wrote {out_path}")
            converted += 1
        # One mission's failure is reported and the run continues to the next.
        except Exception as exc:  # noqa: BLE001
            print(
                f"FAILED {mission.path}: {type(exc).__name__}: {exc}", file=sys.stderr
            )
            failed += 1

    print(f"{converted} converted, {skipped} skipped, {failed} failed")
    return 1 if failed else 0
