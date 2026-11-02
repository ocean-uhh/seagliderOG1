"""Draw the figures that show how ``PHASE`` is assigned.

Converts the bundled samples (sg271, basestation 3.0.6; sg005, basestation 2.8) and
writes PNGs to ``docs/source/_static/phase/``:

- ``dive_<id>.png`` - one dive on a shared time axis: pressure with the commanded depths,
  pitch, the state table or G&C events, and the assigned PHASE with the old rule beside it;
- ``fractions.png`` - per dive, the share of samples in each phase and the phase order;
- ``pitch_dpdt.png`` - pitch against dP/dt, colored by phase.

Run by the docs Makefile (``make phase``). With ``--dev-out <folder>`` and
``SEAGLIDEROG1_DEV_DATA`` set, the same figures with the dev-pack dives added go to that
folder, not to the docs.
"""

from __future__ import annotations

import argparse
import json
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
from matplotlib.patches import Patch

from seagliderOG1 import _convert, _phase
from seagliderOG1.reports._vendored import design_tokens

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "source" / "_static" / "phase"

#: OG1 phase id -> (label, color). Fixed order and color on every figure.
PHASES = {
    0: ("unknown", "#bbbbbb"),
    1: ("ascent", "#0072b2"),
    2: ("descent", "#e69f00"),
    3: ("surfacing", "#009e73"),
    4: ("parking", "#cc79a7"),
    5: ("inflexion", "#d55e00"),
    7: ("transition", "#f0e442"),
}

#: Basestation state code -> short label for the state-table panel.
STATE_LABELS = {code: name for code, (name, _) in _phase.GC_STATE_CODES.items()}


def convert(raw: pathlib.Path, work: pathlib.Path) -> xr.Dataset:
    """Return the OG1 dataset converted from the dive files in ``raw``."""
    work.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = _convert._convert_mission(raw, work)
    return xr.load_dataset(out)


def old_rule(ds: xr.Dataset) -> np.ndarray:
    """Return PHASE as the converter assigned it before: 2 to the pressure maximum, 1 after."""
    dive = ds["DIVE_NUMBER"].values
    pres = ds["PRES"].values
    out = np.zeros(dive.size, dtype="int8")
    for number in np.unique(dive[np.isfinite(dive)]):
        rows = np.where(dive == number)[0]
        p = np.where(np.isfinite(pres[rows]), pres[rows], -np.inf)
        imax = int(np.argmax(p))
        out[rows[: imax + 1]] = 2
        out[rows[imax + 1 :]] = 1
    return out


def _band(ax: plt.Axes, t: np.ndarray, phase: np.ndarray, y0: float, y1: float) -> None:
    """Draw ``phase`` as colored spans between y0 and y1 on a time axis."""
    if t.size == 0:
        return
    edges = np.r_[0, np.flatnonzero(np.diff(phase)) + 1, t.size]
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        right = t[b] if b < t.size else t[-1]
        ax.axvspan(t[a], right, ymin=y0, ymax=y1, color=PHASES[int(phase[a])][1], lw=0)


def _minutes(ds: xr.Dataset, rows: np.ndarray, t0: np.datetime64) -> np.ndarray:
    return (ds["TIME"].values[rows] - t0) / np.timedelta64(1, "s") / 60.0


def _command(ds: xr.Dataset, name: str, dive: int) -> float | None:
    """Return the value of the command ``name`` on ``dive``, or None.

    Per-dive scalars are written as JSON ``{"dives": [...], "values": [...]}``.
    """
    if name not in ds.variables:
        return None
    raw = ds[name].values
    if raw.dtype.kind in "US" or raw.dtype == object:
        record = json.loads(str(raw.item() if raw.ndim == 0 else raw.flat[0]))
        lookup = dict(zip(record["dives"], record["values"], strict=True))
        value = lookup.get(dive)
        return None if value is None else float(value)
    values = np.asarray(raw, dtype=float).ravel()
    values = values[np.isfinite(values)]
    return float(values[0]) if values.size else None


def draw_dive(ds: xr.Dataset, dive: int, title: str, width_in: float) -> plt.Figure:
    """Draw one dive: pressure, pitch, the G&C record, and PHASE new and old."""
    rows = np.where(ds["DIVE_NUMBER"].values == dive)[0]
    t0 = ds["TIME"].values[rows].min()
    t = _minutes(ds, rows, t0)
    fig, axes = plt.subplots(
        4,
        1,
        sharex=True,
        figsize=(width_in, width_in * 0.9),
        gridspec_kw={"height_ratios": [3, 1.6, 1.6, 0.9]},
        layout="constrained",
    )
    ax_p, ax_pitch, ax_gc, ax_ph = axes
    phase = ds["PHASE"].values[rows]
    old = old_rule(ds)[rows]
    pres = ds["PRES"].values[rows]
    ok = np.isfinite(pres)
    colors = [PHASES[int(v)][1] for v in phase[ok]]
    ax_p.plot(t[ok], pres[ok], color="0.6", lw=0.6, zorder=1)
    ax_p.scatter(t[ok], pres[ok], c=colors, s=4, lw=0, zorder=2)
    ax_p.invert_yaxis()
    ax_p.set_ylabel("PRES (dbar)")
    for name, style, side in (
        ("log_D_FLARE", ":", 0.0),
        ("log_D_TGT", "--", 1.0),
        ("log_D_SURF", "-.", 1.0),
    ):
        value = _command(ds, name, dive)
        if value is not None:
            ax_p.axhline(value, color="0.3", ls=style, lw=0.7)
            ax_p.annotate(
                name.removeprefix("log_") + " (command)",
                (side, value),
                xycoords=("axes fraction", "data"),
                ha="left" if side == 0.0 else "right",
                va="top",
                fontsize=design_tokens.ANNOT_FS - 1,
                color="0.3",
            )
    if "PITCH" in ds.variables:
        pitch = ds["PITCH"].values[rows]
        okp = np.isfinite(pitch)
        ax_pitch.plot(t[okp], pitch[okp], color="0.2", lw=0.8)
        ax_pitch.axhline(0, color="0.7", lw=0.5)
    ax_pitch.set_ylabel("PITCH (°)")
    _draw_gc(ax_gc, ds, rows, t)
    _band(ax_ph, t, phase, 0.52, 1.0)
    _band(ax_ph, t, old, 0.0, 0.48)
    ax_ph.set_yticks([0.75, 0.25], ["new", "old"])
    ax_ph.set_ylim(0, 1)
    ax_ph.set_ylabel("PHASE")
    ax_ph.set_xlabel("minutes from the first row of the dive file")
    gps = ds["TIME_GPS"].values[rows] if "TIME_GPS" in ds.variables else None
    if gps is not None:
        fixes = np.unique(gps[~np.isnat(gps)])
        for fix in (fixes - t0) / np.timedelta64(1, "s") / 60.0:
            for ax in axes:
                ax.axvline(fix, color=PHASES[3][1], lw=0.9, ls="-", alpha=0.8)
    changed = int((phase != old).sum())
    used = [k for k in PHASES if k in set(phase.tolist()) | set(old.tolist())]
    handles = [Patch(color=PHASES[k][1], label=f"{k} {PHASES[k][0]}") for k in used]
    fig.legend(
        handles=handles, loc="outside lower center", ncol=len(handles), frameon=False
    )
    fig.suptitle(f"{title} — {changed} of {rows.size} rows change phase")
    return fig


def _draw_gc(ax: plt.Axes, ds: xr.Dataset, rows: np.ndarray, t: np.ndarray) -> None:
    """Draw the state table as a step line, or the G&C VBD commands without one."""
    if (
        "gc_state_state" in ds.variables
        and np.isfinite(ds["gc_state_state"].values[rows]).any()
    ):
        code = ds["gc_state_state"].values[rows]
        keep = np.isfinite(code)
        tt, cc = t[keep], code[keep].astype(int)
        order = sorted({int(c) for c in cc})
        level = {c: i for i, c in enumerate(order)}
        ax.step(tt, [level[c] for c in cc], where="post", color="0.2", lw=0.9)
        ax.plot(tt, [level[c] for c in cc], "o", color="0.2", ms=3)
        ax.set_yticks(
            range(len(order)), [f"{c} {STATE_LABELS.get(c, '?')}" for c in order]
        )
        ax.tick_params(axis="y", labelsize=design_tokens.ANNOT_FS - 2)
        ax.set_ylabel("state")
    elif "gc_vbd_ctl" in ds.variables:
        vbd = ds["gc_vbd_ctl"].values[rows]
        keep = np.isfinite(vbd)
        end = ds["gc_end_secs"].values[rows][keep]
        start = ds["TIME"].values[rows][keep]
        t0 = ds["TIME"].values[rows].min()
        for a, b, v in zip(start, end, vbd[keep], strict=True):
            x0 = (a - t0) / np.timedelta64(1, "s") / 60.0
            x1 = (b - t0) / np.timedelta64(1, "s") / 60.0
            ax.plot([x0, x1], [v, v], color="0.2", lw=2.5, solid_capstyle="butt")
        ax.axhline(0, color="0.7", lw=0.5)
        ax.set_ylabel("G&C VBD\n(cm³)")
    if "gc_vbd_ctl" in ds.variables:
        start = ds["TIME"].values[rows][np.isfinite(ds["gc_vbd_ctl"].values[rows])]
        t0 = ds["TIME"].values[rows].min()
        for a in (start - t0) / np.timedelta64(1, "s") / 60.0:
            ax.axvline(a, color="0.5", lw=0.4, ls=":")


def draw_fractions(missions: dict[str, xr.Dataset], width_in: float) -> plt.Figure:
    """Draw per-dive phase shares (stacked bars) with the run order written above."""
    labels, shares, orders = [], [], []
    for name, ds in missions.items():
        dive = ds["DIVE_NUMBER"].values
        for number in np.unique(dive[np.isfinite(dive)]):
            phase = ds["PHASE"].values[dive == number]
            labels.append(f"{name}\n{int(number)}")
            shares.append([np.mean(phase == k) for k in PHASES])
            runs = [int(phase[0])] + [
                int(b) for a, b in zip(phase[:-1], phase[1:], strict=True) if a != b
            ]
            orders.append("".join(str(r) for r in runs))
    shares = np.array(shares)
    fig, ax = plt.subplots(figsize=(width_in, width_in * 0.45), layout="constrained")
    bottom = np.zeros(len(labels))
    for j, k in enumerate(PHASES):
        if shares[:, j].any():
            ax.bar(
                labels,
                shares[:, j],
                bottom=bottom,
                color=PHASES[k][1],
                label=f"{k} {PHASES[k][0]}",
            )
        bottom += shares[:, j]
    for x, text in enumerate(orders):
        ax.text(x, 1.02, text, ha="center", fontsize=design_tokens.ANNOT_FS - 2)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("share of the dive's rows")
    ax.tick_params(axis="x", labelsize=design_tokens.ANNOT_FS - 1)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
    return fig


def _pitch_at(ds: xr.Dataset, rows: np.ndarray) -> np.ndarray:
    """Return PITCH at ``rows``, interpolated in time within each dive.

    Basestation 3 writes pitch on the engineering time base and pressure on the CTD's, so
    the two are rarely on the same row.
    """
    t = ds["TIME"].values.astype("datetime64[ns]").astype("int64") / 1e9
    pitch = ds["PITCH"].values.astype(float)
    dive = ds["DIVE_NUMBER"].values
    out = np.full(t.size, np.nan)
    for number in np.unique(dive[np.isfinite(dive)]):
        here = dive == number
        known = here & np.isfinite(pitch)
        if known.sum() > 1:
            out[here] = np.interp(t[here], t[known], pitch[known], np.nan, np.nan)
    return out[rows]


def draw_pitch_dpdt(missions: dict[str, xr.Dataset], width_in: float) -> plt.Figure:
    """Draw pitch against dP/dt, one panel per mission, colored by phase."""
    fig, axes = plt.subplots(
        1,
        len(missions),
        figsize=(width_in, width_in * 0.42),
        sharey=True,
        layout="constrained",
    )
    for ax, (name, ds) in zip(np.atleast_1d(axes), missions.items(), strict=True):
        keep = np.isfinite(ds["PRES"].values)
        t = ds["TIME"].values[keep].astype("datetime64[ns]").astype("int64") / 1e9
        p = ds["PRES"].values[keep]
        dive = ds["DIVE_NUMBER"].values[keep]
        dpdt = np.gradient(p, t)
        dpdt[np.r_[True, np.diff(dive) != 0]] = np.nan
        pitch = _pitch_at(ds, keep)
        phase = ds["PHASE"].values[keep]
        for k in PHASES:
            sel = phase == k
            if sel.any():
                ax.scatter(
                    dpdt[sel],
                    pitch[sel],
                    s=3,
                    lw=0,
                    color=PHASES[k][1],
                    label=f"{k} {PHASES[k][0]}",
                )
        ax.axvline(0, color="0.7", lw=0.5)
        ax.axhline(0, color="0.7", lw=0.5)
        ax.set_xlim(-0.5, 0.5)
        ax.set_title(name)
        ax.set_xlabel("dP/dt (dbar/s)")
    np.atleast_1d(axes)[0].set_ylabel("PITCH (°)")
    np.atleast_1d(axes)[-1].legend(
        loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, markerscale=3
    )
    return fig


#: Dev-pack dives drawn only with ``--dev-out`` (never into the docs: the dev pack holds
#: data shared privately).
DEV_DIVES = {
    "sg033": (
        "p0330001_20100903.nc",
        "sg033 2010-09-03 (basestation 2.10, state table)",
    ),
    "dg042": ("p0420001.nc", "dg042 2022-07-18 (basestation 2.10, Deepglider)"),
    "sg537": ("p5370001.nc", "sg537 dive 1 (basestation 2.8, G&C events only)"),
}


def _write_all(missions: dict[str, xr.Dataset], dives: dict, out: pathlib.Path) -> None:
    """Write the per-dive, fractions and pitch figures for ``missions`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    width = design_tokens.W_FULL
    for name, ds in missions.items():
        number, note = dives[name]
        fig = draw_dive(ds, number, note, width)
        fig.savefig(out / f"dive_{name}.png")
        plt.close(fig)
    fig = draw_fractions(missions, width)
    fig.savefig(out / "fractions.png")
    plt.close(fig)
    fig = draw_pitch_dpdt(missions, width)
    fig.savefig(out / "pitch_dpdt.png")
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    """Convert the samples and write the phase figures.

    Parameters
    ----------
    argv : list of str, optional
        ``["--dev-out", <folder>]`` also draws the dev-pack dives (``SEAGLIDEROG1_DEV_DATA``)
        into that folder, for review outside the docs.
    """
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--dev-out", type=pathlib.Path, default=None)
    opts = args.parse_args(argv)
    logging.disable(logging.WARNING)
    plt.style.use(design_tokens.MPLSTYLE_PATH)
    work = pathlib.Path(tempfile.mkdtemp())
    bundled = {
        "sg271": (REPO / "seagliderOG1" / "data" / "sg271", 3, SG271_NOTE),
        "sg005": (REPO / "data" / "demo_sg005", 1, SG005_NOTE),
    }
    missions = {
        name: convert(raw, work / name) for name, (raw, _, _) in bundled.items()
    }
    dives = {name: (number, note) for name, (_, number, note) in bundled.items()}
    _write_all(missions, dives, OUT)
    print(f"wrote {sorted(p.name for p in OUT.glob('*.png'))}")
    dev = os.environ.get("SEAGLIDEROG1_DEV_DATA")
    if opts.dev_out and dev:
        for name, (file, note) in DEV_DIVES.items():
            source = pathlib.Path(dev) / file
            if source.exists():
                folder = work / f"raw_{name}"
                folder.mkdir()
                shutil.copy(source, folder / file)
                missions[name] = convert(folder, work / name)
                dives[name] = (1, note)
        _write_all(missions, dives, opts.dev_out)
        print(f"wrote {sorted(p.name for p in opts.dev_out.glob('*.png'))}")
    shutil.rmtree(work, ignore_errors=True)


SG271_NOTE = "sg271 dive 3 (basestation 3.0.6, state table)"
SG005_NOTE = "sg005 dive 1 (basestation 2.8, G&C events only)"


if __name__ == "__main__":
    main()
