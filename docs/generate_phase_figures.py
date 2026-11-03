"""Draw the figures on the docs page *How the phase is assigned*.

Converts the bundled samples (sg271, basestation 3.0.6; sg005, basestation 2.8) and writes
PNGs to ``docs/source/_static/phase/`` with the figure functions the conversion page uses
(:mod:`seagliderOG1.reports.phase`):

- ``dive_<id>.png`` - one dive: pressure with the commanded depths, pitch, the state table
  or G&C events, and PHASE with the pre-0.3.0 rule below it;
- ``fractions_<id>.png`` - every dive's share of rows in each phase;
- ``pitch_dpdt.png`` - pitch against dP/dt for both samples, colored by phase.

Run by the docs Makefile (``make phase``). With ``--dev-out <folder>`` and
``SEAGLIDEROG1_DEV_DATA`` set, the dive figures of the dev-pack dives are drawn into that
folder as well, never into the docs (the dev pack holds data shared privately).
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import shutil
import tempfile
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from seagliderOG1 import _convert
from seagliderOG1.reports import phase
from seagliderOG1.reports._vendored import design_tokens

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "source" / "_static" / "phase"

#: Bundled samples: name -> (raw folder, dive to draw).
BUNDLED = {
    "sg271": (REPO / "seagliderOG1" / "data" / "sg271", 3),
    "sg005": (REPO / "data" / "demo_sg005", 1),
}

#: Dev-pack dives drawn only with ``--dev-out``.
DEV_DIVES = {
    "sg033": "p0330001_20100903.nc",
    "dg042": "p0420001.nc",
    "sg537": "p5370001.nc",
}


def convert(raw: pathlib.Path, work: pathlib.Path) -> xr.Dataset:
    """Return the OG1 dataset converted from the dive files in ``raw``."""
    work.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = _convert._convert_mission(raw, work)
    return xr.load_dataset(out)


def old_rule(ds: xr.Dataset) -> np.ndarray:
    """Return PHASE as converters before 0.3.0 assigned it: 2 to the pressure maximum, 1 after."""
    dive = ds["dive_number"].values
    pres = ds["PRES"].values
    out = np.zeros(dive.size, dtype="int8")
    for number in np.unique(dive[np.isfinite(dive)]):
        rows = np.where(dive == number)[0]
        p = np.where(np.isfinite(pres[rows]), pres[rows], -np.inf)
        imax = int(np.argmax(p))
        out[rows[: imax + 1]] = 2
        out[rows[imax + 1 :]] = 1
    return out


def _save(fig: plt.Figure | None, path: pathlib.Path) -> None:
    if fig is not None:
        fig.savefig(path)
        plt.close(fig)


def _draw(missions: dict[str, tuple[xr.Dataset, int]], out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    width = design_tokens.W_FULL
    for name, (ds, dive) in missions.items():
        _save(
            phase.draw_phase_dive(ds, dive, old=old_rule(ds), width_in=width),
            out / f"dive_{name}.png",
        )
        _save(
            phase.draw_phase_fractions(ds, width_in=design_tokens.W_THREE_FIFTHS),
            out / f"fractions_{name}.png",
        )


def main(argv: list[str] | None = None) -> None:
    """Convert the samples and write the phase figures."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dev-out", type=pathlib.Path, default=None)
    opts = parser.parse_args(argv)
    logging.disable(logging.WARNING)
    plt.style.use(design_tokens.MPLSTYLE_PATH)
    work = pathlib.Path(tempfile.mkdtemp())
    try:
        missions = {
            name: (convert(raw, work / name), dive)
            for name, (raw, dive) in BUNDLED.items()
        }
        _draw(missions, OUT)
        _save(
            phase.draw_phase_pitch_dpdt(
                [(name, ds, None) for name, (ds, _) in missions.items()],
                width_in=design_tokens.W_FULL,
            ),
            OUT / "pitch_dpdt.png",
        )
        print(f"wrote {sorted(p.name for p in OUT.glob('*.png'))}")
        dev = os.environ.get("SEAGLIDEROG1_DEV_DATA")
        if opts.dev_out and dev:
            extra = {}
            for name, file in DEV_DIVES.items():
                source = pathlib.Path(dev) / file
                if source.exists():
                    folder = work / f"raw_{name}"
                    folder.mkdir()
                    shutil.copy(source, folder / file)
                    extra[name] = (convert(folder, work / name), 1)
            _draw(extra, opts.dev_out)
            print(f"wrote {sorted(p.name for p in opts.dev_out.glob('*.png'))}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
