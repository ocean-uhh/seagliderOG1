"""Figures of how ``PHASE`` was assigned, for the conversion page and the docs.

Three figures: one dive on a shared time axis (:func:`draw_phase_dive`), the share of
each dive's rows in each phase over the mission (:func:`draw_phase_fractions`), and pitch
against the rate of pressure change for one dive (:func:`draw_phase_pitch_dpdt`).
:func:`middle_dive` picks the dive to show. Each draw function fixes only the aspect
ratio; its height follows ``width_in``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

from seagliderOG1 import _phase
from seagliderOG1.reports._vendored.design_tokens import ANNOT_FS, W_FULL

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

#: OG1 phase id -> color. Fixed on every figure.
PHASE_COLORS: dict[int, str] = {
    0: "#bbbbbb",
    1: "#0072b2",
    2: "#e69f00",
    3: "#009e73",
    4: "#cc79a7",
    5: "#d55e00",
    6: "#56b4e9",
    7: "#f0e442",
}

#: More dives than this and the run order is not written above the bars.
_MAX_ORDER_LABELS = 30


def _label(phase: int) -> str:
    return f"{phase} {_phase.PHASE_NAMES[phase]}"


def _phase_values(ds: xr.Dataset) -> np.ndarray:
    """Return PHASE as int8, 0 where the file masks it (``_FillValue`` 0)."""
    values = np.asarray(ds["PHASE"].values, dtype=float)
    return np.where(np.isfinite(values), values, 0).astype("int8")


def _runs(phase: np.ndarray) -> list[int]:
    """Return the phase ids of ``phase``'s runs, in order."""
    if phase.size == 0:
        return []
    keep = np.r_[True, phase[1:] != phase[:-1]]
    return [int(v) for v in phase[keep]]


def middle_dive(ds: xr.Dataset) -> int | None:
    """Return the complete dive nearest the middle of the mission, or None.

    A dive is complete when its phases include descent, inflection and ascent. With none
    complete, the middle dive is returned.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``PHASE`` and ``DIVE_NUMBER``.

    Returns
    -------
    int or None
        The dive number, or None when the dataset has no dives.
    """
    if "PHASE" not in ds.variables or "DIVE_NUMBER" not in ds.variables:
        return None
    dive = np.asarray(ds["DIVE_NUMBER"].values, dtype=float)
    numbers = np.unique(dive[np.isfinite(dive)])
    if numbers.size == 0:
        return None
    phase = _phase_values(ds)
    wanted = {_phase.DESCENT, _phase.INFLECTION, _phase.ASCENT}
    complete = [n for n in numbers if wanted <= set(phase[dive == n].tolist())]
    pool = np.array(complete) if complete else numbers
    middle = np.median(numbers)
    return int(pool[np.argmin(np.abs(pool - middle))])


def _minutes(times: np.ndarray, t0: np.datetime64) -> np.ndarray:
    return (times - t0) / np.timedelta64(1, "s") / 60.0


def _band(ax: Axes, t: np.ndarray, phase: np.ndarray, y0: float, y1: float) -> None:
    """Draw ``phase`` as colored spans between y0 and y1, each to the next row."""
    if t.size == 0:
        return
    edges = np.r_[0, np.flatnonzero(np.diff(phase)) + 1, t.size]
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        right = t[b] if b < t.size else t[-1]
        ax.axvspan(
            t[a], right, ymin=y0, ymax=y1, color=PHASE_COLORS[int(phase[a])], lw=0
        )


def _pitch_at(ds: xr.Dataset, rows: np.ndarray) -> np.ndarray:
    """Return PITCH at ``rows`` (indices), interpolated in time within each dive.

    Basestation 3 writes pitch on the engineering time base and pressure on the CTD's, so
    the two are rarely on the same row.
    """
    if "PITCH" not in ds.variables:
        return np.full(rows.size, np.nan)
    t = ds["TIME"].values.astype("datetime64[ns]").astype("int64") / 1e9
    pitch = np.asarray(ds["PITCH"].values, dtype=float)
    dive = np.asarray(ds["DIVE_NUMBER"].values, dtype=float)
    out = np.full(rows.size, np.nan)
    for number in np.unique(dive[rows][np.isfinite(dive[rows])]):
        here = dive == number
        known = here & np.isfinite(pitch)
        sel = dive[rows] == number
        if known.sum() > 1:
            out[sel] = np.interp(t[rows][sel], t[known], pitch[known], np.nan, np.nan)
    return out


def _draw_gc(ax: Axes, ds: xr.Dataset, rows: np.ndarray, t0: np.datetime64) -> None:
    """Draw the state table as a step line, or the G&C VBD settings without one."""
    times = ds["TIME"].values[rows]
    state = (
        np.asarray(ds["gc_state_state"].values[rows], dtype=float)
        if "gc_state_state" in ds.variables
        else np.full(rows.size, np.nan)
    )
    vbd = (
        np.asarray(ds["gc_vbd_ctl"].values[rows], dtype=float)
        if "gc_vbd_ctl" in ds.variables
        else np.full(rows.size, np.nan)
    )
    if np.isfinite(state).any():
        keep = np.isfinite(state)
        order = np.argsort(times[keep], kind="stable")
        tt = _minutes(times[keep][order], t0)
        cc = state[keep][order].astype(int)
        levels = sorted(set(cc.tolist()))
        level = [levels.index(c) for c in cc]
        ax.step(tt, level, where="post", color="0.2", lw=0.9)
        ax.plot(tt, level, "o", color="0.2", ms=3)
        names = {c: n for c, (n, _) in _phase.GC_STATE_CODES.items()}
        ax.set_yticks(range(len(levels)), [f"{c} {names.get(c, '?')}" for c in levels])
        ax.tick_params(axis="y", labelsize=ANNOT_FS - 2)
        ax.set_ylabel("state")
    elif np.isfinite(vbd).any() and "gc_end_secs" in ds.variables:
        keep = np.isfinite(vbd)
        ends = ds["gc_end_secs"].values[rows][keep]
        for a, b, v in zip(
            _minutes(times[keep], t0), _minutes(ends, t0), vbd[keep], strict=True
        ):
            ax.plot([a, b], [v, v], color="0.2", lw=2.5, solid_capstyle="butt")
        ax.axhline(0, color="0.7", lw=0.5)
        ax.set_ylabel("G&C VBD\n(cm³)")
    else:
        ax.text(
            0.5,
            0.5,
            "no state table or G&C events in this file",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=ANNOT_FS,
            color="0.4",
        )
        ax.set_yticks([])
    for a in _minutes(times[np.isfinite(vbd)], t0):
        ax.axvline(a, color="0.5", lw=0.4, ls=":")


def draw_phase_dive(
    ds: xr.Dataset,
    dive: int,
    *,
    old: np.ndarray | None = None,
    width_in: float = W_FULL,
) -> Figure | None:
    """Draw one dive: pressure, pitch, the glider's G&C record, and PHASE.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``TIME``, ``PRES``, ``PHASE`` and ``DIVE_NUMBER``; ``PITCH``,
        ``TIME_GPS``, ``gc_state_state``, ``gc_vbd_ctl`` and the ``log_D_*`` commands are
        drawn when present.
    dive : int
        The dive number to draw.
    old : numpy.ndarray, optional
        Another PHASE for every row of ``ds`` (for example an earlier rule), drawn as a
        second band below the first.
    width_in : float, optional
        Figure width in inches; the height follows.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when the dive has no rows.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    rows = np.flatnonzero(np.asarray(ds["DIVE_NUMBER"].values, dtype=float) == dive)
    if rows.size == 0:
        return None
    times = ds["TIME"].values[rows]
    t0 = times.min()
    t = _minutes(times, t0)
    phase = _phase_values(ds)[rows]
    fig, axes = plt.subplots(
        4,
        1,
        sharex=True,
        figsize=(width_in, width_in * 0.9),
        gridspec_kw={"height_ratios": [3, 1.6, 1.6, 0.9 if old is not None else 0.5]},
        layout="constrained",
    )
    ax_p, ax_pitch, ax_gc, ax_ph = axes
    pres = np.asarray(ds["PRES"].values[rows], dtype=float)
    ok = np.isfinite(pres)
    ax_p.plot(t[ok], pres[ok], color="0.6", lw=0.6, zorder=1)
    ax_p.scatter(
        t[ok], pres[ok], c=[PHASE_COLORS[int(v)] for v in phase[ok]], s=4, lw=0
    )
    ax_p.invert_yaxis()
    ax_p.set_ylabel("PRES (dbar)")
    for name, style, side in (
        ("log_D_FLARE", ":", 0.0),
        ("log_D_TGT", "--", 1.0),
        ("log_D_SURF", "-.", 1.0),
    ):
        value = _phase.command(ds, name, dive, rows)
        if value is not None:
            ax_p.axhline(value, color="0.3", ls=style, lw=0.7)
            ax_p.annotate(
                name.removeprefix("log_") + " (command)",
                (side, value),
                xycoords=("axes fraction", "data"),
                ha="left" if side == 0.0 else "right",
                va="top",
                fontsize=ANNOT_FS - 1,
                color="0.3",
            )
    if "PITCH" in ds.variables:
        pitch = np.asarray(ds["PITCH"].values[rows], dtype=float)
        okp = np.isfinite(pitch)
        ax_pitch.plot(t[okp], pitch[okp], color="0.2", lw=0.8)
        ax_pitch.axhline(0, color="0.7", lw=0.5)
    ax_pitch.set_ylabel("PITCH (°)")
    _draw_gc(ax_gc, ds, rows, t0)
    if old is None:
        _band(ax_ph, t, phase, 0.0, 1.0)
        ax_ph.set_yticks([])
    else:
        _band(ax_ph, t, phase, 0.52, 1.0)
        _band(ax_ph, t, old[rows], 0.0, 0.48)
        ax_ph.set_yticks([0.75, 0.25], ["new", "old"])
    ax_ph.set_ylim(0, 1)
    ax_ph.set_ylabel("PHASE")
    ax_ph.set_xlabel("minutes from the first row of the dive")
    if "TIME_GPS" in ds.variables:
        gps = ds["TIME_GPS"].values[rows]
        for fix in _minutes(np.unique(gps[~np.isnat(gps)]), t0):
            for ax in axes:
                ax.axvline(fix, color=PHASE_COLORS[3], lw=0.9, alpha=0.8)
    shown = set(phase.tolist()) | (
        set(old[rows].tolist()) if old is not None else set()
    )
    handles = [
        Patch(color=PHASE_COLORS[k], label=_label(k))
        for k in _phase.PHASE_NAMES
        if k in shown
    ]
    fig.legend(handles=handles, loc="outside lower center", ncol=len(handles))
    return fig


def draw_phase_fractions(ds: xr.Dataset, *, width_in: float = W_FULL) -> Figure | None:
    """Draw each dive's share of rows in each phase, stacked, with the run order on top.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``PHASE`` and ``DIVE_NUMBER``.
    width_in : float, optional
        Figure width in inches; the height follows.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when the dataset has no dives.
    """
    import matplotlib.pyplot as plt

    dive = np.asarray(ds["DIVE_NUMBER"].values, dtype=float)
    numbers = np.unique(dive[np.isfinite(dive)])
    if numbers.size == 0:
        return None
    phase = _phase_values(ds)
    ids = list(_phase.PHASE_NAMES)
    shares = np.array([[np.mean(phase[dive == n] == k) for k in ids] for n in numbers])
    fig, ax = plt.subplots(figsize=(width_in, width_in * 0.4), layout="constrained")
    x = np.arange(numbers.size)
    bottom = np.zeros(numbers.size)
    for j, k in enumerate(ids):
        if shares[:, j].any():
            ax.bar(
                x,
                shares[:, j],
                bottom=bottom,
                width=0.8 if numbers.size <= _MAX_ORDER_LABELS else 1.0,
                color=PHASE_COLORS[k],
                label=_label(k),
            )
        bottom += shares[:, j]
    if numbers.size <= _MAX_ORDER_LABELS:
        for i, n in enumerate(numbers):
            text = "".join(str(r) for r in _runs(phase[dive == n]))
            ax.text(i, 1.02, text, ha="center", fontsize=ANNOT_FS - 2)
        ax.set_xticks(x, [str(int(n)) for n in numbers])
        ax.set_ylim(0, 1.12)
    else:
        step = max(1, numbers.size // 12)
        ax.set_xticks(x[::step], [str(int(n)) for n in numbers[::step]])
        ax.set_ylim(0, 1)
    ax.set_xlabel("dive")
    ax.set_ylabel("share of the dive's rows")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
    return fig


def draw_phase_pitch_dpdt(
    panels: list[tuple[str, xr.Dataset, int | None]], *, width_in: float = W_FULL
) -> Figure | None:
    """Draw pitch against dP/dt, colored by phase, one panel per (title, dataset, dive).

    Parameters
    ----------
    panels : list of (str, xarray.Dataset, int or None)
        Panel title, dataset, and the dive to draw (None for every dive).
    width_in : float, optional
        Figure width in inches; the height follows.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when no panel has pressure and pitch.
    """
    import matplotlib.pyplot as plt

    usable = [p for p in panels if {"PRES", "PITCH", "PHASE"} <= set(p[1].variables)]
    if not usable:
        return None
    aspect = 0.42 if len(usable) > 1 else 0.75
    fig, axes = plt.subplots(
        1,
        len(usable),
        figsize=(width_in, width_in * aspect),
        sharey=True,
        squeeze=False,
        layout="constrained",
    )
    for ax, (title, ds, dive) in zip(axes[0], usable, strict=True):
        dives = np.asarray(ds["DIVE_NUMBER"].values, dtype=float)
        pres = np.asarray(ds["PRES"].values, dtype=float)
        keep = np.isfinite(pres) & (dives == dive if dive is not None else True)
        rows = np.flatnonzero(keep)
        t = ds["TIME"].values[rows].astype("datetime64[ns]").astype("int64") / 1e9
        if rows.size < 3:
            continue
        dpdt = np.gradient(pres[rows], t)
        dpdt[np.r_[True, np.diff(dives[rows]) != 0]] = np.nan
        pitch = _pitch_at(ds, rows)
        phase = _phase_values(ds)[rows]
        for k in _phase.PHASE_NAMES:
            sel = phase == k
            if sel.any():
                ax.scatter(
                    dpdt[sel],
                    pitch[sel],
                    s=4,
                    lw=0,
                    color=PHASE_COLORS[k],
                    label=_label(k),
                )
        ax.axvline(0, color="0.7", lw=0.5)
        ax.axhline(0, color="0.7", lw=0.5)
        ax.set_xlim(-0.5, 0.5)
        ax.set_title(title)
        ax.set_xlabel("dP/dt (dbar/s)")
    axes[0][0].set_ylabel("PITCH (°)")
    axes[0][-1].legend(
        loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, markerscale=3
    )
    return fig
