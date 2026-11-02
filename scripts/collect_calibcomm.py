"""Print every calibration comment in a folder of basestation files as CSV rows.

One row per ``sg_cal_calibcomm*`` variable per file, with the file's first-sample date and
basestation version: the columns ``tests/data/calibcomm_answers.csv`` starts from. The
expected serial and date columns are filled by hand.

Usage::

    python scripts/collect_calibcomm.py FOLDER > rows.csv
"""

import argparse
import csv
import datetime
import pathlib
import sys

import xarray as xr


def calibcomm_rows(folder: pathlib.Path) -> list[dict[str, str]]:
    """Return one row per calibration comment in the ``p*.nc`` files of ``folder``.

    Parameters
    ----------
    folder : pathlib.Path
        Folder of basestation dive files.

    Returns
    -------
    list of dict of str to str
        ``{"file", "first_sample", "base_station_version", "variable", "string"}`` rows,
        sorted by file then variable. ``first_sample`` is the ISO date of the
        ``start_time`` global (empty when the file has none).

    """
    rows = []
    for path in sorted(folder.glob("p*.nc")):
        with xr.open_dataset(path, engine="netcdf4") as ds:
            start = ds.attrs.get("start_time")
            first_sample = (
                datetime.datetime.fromtimestamp(float(start), datetime.UTC)
                .date()
                .isoformat()
                if start is not None
                else ""
            )
            for name in sorted(str(v) for v in ds.variables):
                if not name.startswith("sg_cal_calibcomm"):
                    continue
                value = ds[name].values.item()
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                rows.append(
                    {
                        "file": path.name,
                        "first_sample": first_sample,
                        "base_station_version": str(
                            ds.attrs.get("base_station_version", "")
                        ),
                        "variable": name,
                        "string": str(value).rstrip("\x00").strip(),
                    }
                )
    return rows


def main() -> None:
    """Write the rows for the folder given on the command line to standard output."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=pathlib.Path, help="folder of p*.nc files")
    args = parser.parse_args()
    rows = calibcomm_rows(args.folder)
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "file",
            "first_sample",
            "base_station_version",
            "variable",
            "string",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
