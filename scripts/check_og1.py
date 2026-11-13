"""Run the OG1 compliance checker on a file and compare its findings with the known list.

Usage::

    python scripts/check_og1.py FILE.nc tests/data/og1_known_findings.txt [--update]

Runs ``compliance-checker --test og:1.0`` (cc-plugin-og) and collects every message as
``<check> | <message>``. Exits 1 when a message is not in the known list (a new finding),
and prints the known findings that no longer occur, so the list can shrink as fixes land.
``--update`` rewrites the list from this run instead.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile


def findings(nc: pathlib.Path) -> list[str]:
    """Return the checker's messages for one file, sorted."""
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "og1.json"
        # The checker exits non-zero when anything fails; the JSON report is what we read.
        subprocess.run(
            [
                "compliance-checker",
                "--test",
                "og:1.0",
                "-f",
                "json",
                "-o",
                str(out),
                str(nc),
            ],
            check=False,
        )
        report = json.loads(out.read_text(encoding="utf-8"))["og:1.0"]
    return sorted(
        f"{check['name']} | {msg}"
        for check in report["all_priorities"]
        for msg in check["msgs"]
    )


def main() -> int:
    """Compare (or with --update, rewrite) the known findings; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("nc", type=pathlib.Path)
    parser.add_argument("known", type=pathlib.Path)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    found = findings(args.nc)
    if args.update:
        header = (
            [
                line
                for line in args.known.read_text(encoding="utf-8").splitlines()
                if line.startswith("#")
            ]
            if args.known.exists()
            else []
        )
        args.known.write_text("\n".join(header + found) + "\n", encoding="utf-8")
        print(f"wrote {len(found)} findings to {args.known}")
        return 0

    known = {
        line
        for line in args.known.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    new = [f for f in found if f not in known]
    gone = sorted(known - set(found))
    print(
        f"{len(found)} findings: {len(found) - len(new)} known, {len(new)} new; "
        f"{len(gone)} known findings no longer occur"
    )
    for f in new:
        print("NEW  ", f)
    for f in gone:
        print("GONE ", f)
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
