"""The phase page of the report, and its figures (also drawn on the docs page).

Three figures: one dive on a shared time axis (:func:`draw_phase_dive`), the share of
each dive's rows in each phase over the mission (:func:`draw_phase_fractions`), and pitch
against the rate of pressure change for one dive (:func:`draw_phase_pitch_dpdt`).
:func:`write_phase_page` writes ``<stem>_phase.html`` beside the conversion page.
:func:`middle_dive` picks the dive to show. Each draw function fixes only the aspect
ratio; its height follows ``width_in``.
"""

from __future__ import annotations

import json
from pathlib import Path
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

#: Fewer dives than this are drawn in this many slots, so the bars keep their width.
_MIN_SLOTS = 6

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
        An OG1 dataset with ``PHASE`` and ``dive_number``.

    Returns
    -------
    int or None
        The dive number, or None when the dataset has no dives.
    """
    if "PHASE" not in ds.variables or "dive_number" not in ds.variables:
        return None
    dive = np.asarray(ds["dive_number"].values, dtype=float)
    numbers = np.unique(dive[np.isfinite(dive)])
    if numbers.size == 0:
        return None
    complete = [n for n in numbers if is_complete(ds, int(n))]
    pool = np.array(complete) if complete else numbers
    middle = np.median(numbers)
    return int(pool[np.argmin(np.abs(pool - middle))])


def is_complete(ds: xr.Dataset, dive: int) -> bool:
    """Return True when ``dive`` has descent, inflection and ascent rows.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``PHASE`` and ``dive_number``.
    dive : int
        The dive number.

    Returns
    -------
    bool
        Whether the dive's phases include 2, 5 and 1.
    """
    rows = np.asarray(ds["dive_number"].values, dtype=float) == dive
    present = set(_phase_values(ds)[rows].tolist())
    return {_phase.DESCENT, _phase.INFLECTION, _phase.ASCENT} <= present


def _minutes(times: np.ndarray, t0: np.datetime64) -> np.ndarray:
    return (times - t0) / np.timedelta64(1, "s") / 60.0


def _command(
    ds: xr.Dataset, name: str, dive: int, rows: np.ndarray | None = None
) -> float | None:
    """Return the value of the piloting command ``name`` on ``dive``, or None.

    A command the same on every dive is a scalar; one that changes is written as JSON
    ``{"dives": [...], "values": [...]}``; inside the converter, before the dives are
    joined, it can sit on ``N_MEASUREMENTS`` (``rows`` picks the dive's rows).

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset that may hold ``name``.
    name : str
        The command, for example ``log_D_FLARE``.
    dive : int
        The dive number.
    rows : numpy.ndarray, optional
        The dive's row indices, for a command on ``N_MEASUREMENTS``.

    Returns
    -------
    float or None
        The value, or None when ``ds`` does not record it for that dive.
    """
    if name not in ds.variables:
        return None
    raw = np.asarray(ds[name].values)
    if raw.dtype.kind in "USO":
        try:
            record = json.loads(str(raw.item() if raw.ndim == 0 else raw.flat[0]))
            lookup = {
                int(d): v
                for d, v in zip(record["dives"], record["values"], strict=True)
            }
        except (ValueError, KeyError, TypeError):
            return None
        value = lookup.get(dive)
        return None if value is None else float(value)
    values = raw.astype(float)
    if values.ndim == 1:
        # Only an array on N_MEASUREMENTS can be read for one dive (by its rows); any
        # other array does not say which value is which dive's.
        if rows is None or values.size != ds.sizes.get("N_MEASUREMENTS"):
            return None
        values = values[rows]
    elif values.ndim > 1:
        return None
    values = values[np.isfinite(values)].ravel()
    return float(values[0]) if values.size else None


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
    dive = np.asarray(ds["dive_number"].values, dtype=float)
    out = np.full(rows.size, np.nan)
    for number in np.unique(dive[rows][np.isfinite(dive[rows])]):
        here = dive == number
        known = here & np.isfinite(pitch)
        sel = dive[rows] == number
        if known.sum() > 1:
            out[sel] = np.interp(t[rows][sel], t[known], pitch[known], np.nan, np.nan)
    return out


def _column(ds: xr.Dataset, name: str, rows: np.ndarray) -> np.ndarray:
    """Return ``name`` at ``rows`` as floats, all NaN when ``ds`` lacks it."""
    if name not in ds.variables:
        return np.full(rows.size, np.nan)
    return np.asarray(ds[name].values[rows], dtype=float)


def _event_lines(ax: Axes, ds: xr.Dataset, rows: np.ndarray, t0: np.datetime64) -> None:
    """Draw a dotted line at the start of each G&C event."""
    starts = ds["TIME"].values[rows][np.isfinite(_column(ds, "gc_vbd_ctl", rows))]
    for a in _minutes(starts, t0):
        ax.axvline(a, color="0.5", lw=0.4, ls=":")


def _draw_vbd(ax: Axes, ds: xr.Dataset, rows: np.ndarray, t0: np.datetime64) -> None:
    """Draw each G&C event's VBD setting as a bar from its start to its end."""
    vbd = _column(ds, "gc_vbd_ctl", rows)
    keep = np.isfinite(vbd)
    ends = ds["gc_end_secs"].values[rows][keep]
    for a, b, v in zip(
        _minutes(ds["TIME"].values[rows][keep], t0),
        _minutes(ends, t0),
        vbd[keep],
        strict=True,
    ):
        ax.plot([a, b], [v, v], color="0.2", lw=2.5, solid_capstyle="butt")
    ax.axhline(0, color="0.7", lw=0.5)
    ax.set_ylabel("G&C VBD\n(cm³)")
    _event_lines(ax, ds, rows, t0)


def _draw_states(ax: Axes, ds: xr.Dataset, rows: np.ndarray, t0: np.datetime64) -> None:
    """Draw the glider's state table (gc_state_state) as a step line."""
    state = _column(ds, "gc_state_state", rows)
    keep = np.isfinite(state)
    times = ds["TIME"].values[rows][keep]
    order = np.argsort(times, kind="stable")
    tt = _minutes(times[order], t0)
    cc = state[keep][order].astype(int)
    levels = sorted(set(cc.tolist()))
    level = [levels.index(c) for c in cc]
    ax.step(tt, level, where="post", color="0.2", lw=0.9)
    ax.plot(tt, level, "o", color="0.2", ms=3)
    names = _phase.GC_STATE_NAMES
    ax.set_yticks(range(len(levels)), [f"{c} {names.get(c, '?')}" for c in levels])
    ax.tick_params(axis="y", labelsize=ANNOT_FS - 2)
    ax.set_ylabel("gc_state_state")
    _event_lines(ax, ds, rows, t0)


def pick_dives(ds: xr.Dataset) -> list[int]:
    """Return up to three dives to draw: one near the start, middle and end of the mission.

    The first is dive 2 when the mission has it, else dive 1 (the first dives are often
    shallow test dives, which is the point of showing one). The second is drawn from the
    middle third of the dives and the third from the last third, at random but the same on
    every run (the generator is seeded with the number of dives). A dive is not repeated.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``dive_number``.

    Returns
    -------
    list of int
        The dive numbers, in order.
    """
    dive = np.asarray(ds["dive_number"].values, dtype=float)
    numbers = [int(n) for n in np.unique(dive[np.isfinite(dive)])]
    if not numbers:
        return []
    picked = [numbers[1] if len(numbers) > 1 else numbers[0]]
    rng = np.random.default_rng(len(numbers))
    third = len(numbers) / 3
    for start, stop in ((third, 2 * third), (2 * third, len(numbers))):
        pool = [n for n in numbers[int(start) : int(np.ceil(stop))] if n not in picked]
        if pool:
            picked.append(int(rng.choice(pool)))
    return sorted(set(picked))


def draw_phase_dive(
    ds: xr.Dataset,
    dive: int,
    *,
    old: np.ndarray | None = None,
    width_in: float = W_FULL,
) -> Figure | None:
    """Draw one dive: pressure, pitch, the G&C events' VBD, the state table, and PHASE.

    The VBD and state-table panels are drawn when the file has them (basestation 2.8 has
    no state table).

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``TIME``, ``PRES``, ``PHASE`` and ``dive_number``; ``PITCH``,
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

    rows = np.flatnonzero(np.asarray(ds["dive_number"].values, dtype=float) == dive)
    if rows.size == 0:
        return None
    times = ds["TIME"].values[rows]
    t0 = times.min()
    t = _minutes(times, t0)
    phase = _phase_values(ds)[rows]
    has_events = (
        np.isfinite(_column(ds, "gc_vbd_ctl", rows)).any()
        and "gc_end_secs" in ds.variables
    )
    has_states = bool(np.isfinite(_column(ds, "gc_state_state", rows)).any())
    ratios = [3, 1.4] + [1.2] * int(has_events) + [1.6] * int(has_states)
    ratios.append(0.9 if old is not None else 0.5)
    fig, axes = plt.subplots(
        len(ratios),
        1,
        sharex=True,
        figsize=(width_in, 0.7 * width_in * (0.55 + 0.12 * len(ratios))),
        gridspec_kw={"height_ratios": ratios},
        layout="constrained",
    )
    ax_p, ax_pitch, ax_ph = axes[0], axes[1], axes[-1]
    panel = 2
    if has_events:
        _draw_vbd(axes[panel], ds, rows, t0)
        panel += 1
    if has_states:
        _draw_states(axes[panel], ds, rows, t0)
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
        value = _command(ds, name, dive, rows)
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
    """Draw each dive's share of rows in each phase, with its depth and duration below.

    Top: stacked bars of each phase's share of the dive's rows. Bottom, shorter: the dive's maximum pressure
    (bars, left axis) and duration from first to last row (dots, right axis), so a share can
    be read against how deep and how long the dive was. Fewer than six dives are drawn in
    six slots, so the bars keep a sensible width.

    Parameters
    ----------
    ds : xarray.Dataset
        An OG1 dataset with ``PHASE``, ``dive_number``, ``TIME`` and ``PRES``.
    width_in : float, optional
        Figure width in inches; the height follows.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when the dataset has no dives.
    """
    import matplotlib.pyplot as plt

    dive = np.asarray(ds["dive_number"].values, dtype=float)
    numbers = np.unique(dive[np.isfinite(dive)])
    if numbers.size == 0:
        return None
    phase = _phase_values(ds)
    ids = list(_phase.PHASE_NAMES)
    # Counts per (dive, phase) in one pass: index of each row's dive, times the ids.
    finite = np.isfinite(dive)
    dive_index = np.searchsorted(numbers, dive[finite])
    counts = np.bincount(
        dive_index * len(ids) + phase[finite].astype(int),
        minlength=numbers.size * len(ids),
    ).reshape(numbers.size, len(ids))
    shares = counts / counts.sum(axis=1, keepdims=True)
    pres = np.asarray(ds["PRES"].values, dtype=float)
    seconds = ds["TIME"].values.astype("datetime64[ns]").astype("int64") / 1e9
    max_pres = np.full(numbers.size, np.nan)
    minutes = np.full(numbers.size, np.nan)
    for i, n in enumerate(numbers):
        here = dive == n
        if np.isfinite(pres[here]).any():
            max_pres[i] = np.nanmax(pres[here])
        minutes[i] = (seconds[here].max() - seconds[here].min()) / 60.0
    fig, (ax, ax_depth) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(width_in, width_in * 0.55),
        gridspec_kw={"height_ratios": [3, 1.2]},
        layout="constrained",
    )
    x = np.arange(numbers.size)
    few = numbers.size <= _MAX_ORDER_LABELS
    bottom = np.zeros(numbers.size)
    for j, k in enumerate(ids):
        if shares[:, j].any():
            ax.bar(
                x,
                shares[:, j],
                bottom=bottom,
                width=0.8 if few else 1.0,
                color=PHASE_COLORS[k],
                label=_label(k),
            )
        bottom += shares[:, j]
    ax.set_ylim(0, 1)
    ax.set_ylabel("share of the dive's rows")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
    ax_depth.bar(x, max_pres, width=0.8 if few else 1.0, color="0.75")
    ax_depth.invert_yaxis()
    ax_depth.set_ylabel("max PRES\n(dbar)")
    ax_time = ax_depth.twinx()
    ax_time.plot(x, minutes, "o", color="0.15", ms=4 if few else 2)
    ax_time.set_ylabel("duration\n(min)")
    ax_time.set_ylim(0, np.nanmax(minutes) * 1.15 if np.isfinite(minutes).any() else 1)
    if few:
        ax_depth.set_xticks(x, [str(int(n)) for n in numbers])
    else:
        step = max(1, numbers.size // 12)
        ax_depth.set_xticks(x[::step], [str(int(n)) for n in numbers[::step]])
    slots = max(numbers.size, _MIN_SLOTS)
    ax_depth.set_xlim(-0.6, slots - 0.4)
    ax_depth.set_xlabel("dive")
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
        dives = np.asarray(ds["dive_number"].values, dtype=float)
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


#: Variables the phase page's figures and table read (plus the ``log_D_*`` commands).
_PAGE_VARIABLES = frozenset(
    {
        "PHASE",
        "dive_number",
        "TIME",
        "PRES",
        "DEPTH",
        "PITCH",
        "TIME_GPS",
        "gc_state_state",
        "gc_vbd_ctl",
        "gc_end_secs",
    }
)

#: The docs page that states the algorithm.
DOCS_URL = "https://ocean-uhh.github.io/seagliderOG1/phase.html"


def _load_for_page(path: str | Path) -> xr.Dataset | None:
    """Return the variables the phase page reads, loaded; None without PHASE."""
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        if "PHASE" not in ds.variables or "dive_number" not in ds.variables:
            return None
        names = [
            name
            for name in ds.variables
            if (name in _PAGE_VARIABLES or name.startswith("log_D_"))
            and name not in ds.coords
        ]
        return ds[names].load()


def _phase_rows(ds: xr.Dataset) -> list[dict[str, object]]:
    """Return one row per OG1 phase id: rows, share and dives it appears in."""
    phase = _phase_values(ds)
    dive = np.asarray(ds["dive_number"].values, dtype=float)
    total = phase.size
    rows = []
    for k, name in _phase.PHASE_NAMES.items():
        here = phase == k
        dives = np.unique(dive[here & np.isfinite(dive)])
        rows.append(
            {
                "id": k,
                "name": name,
                "color": PHASE_COLORS[k],
                "rows": f"{int(here.sum()):,}",
                "share": f"{100 * here.sum() / total:.1f}" if total else "—",
                "dives": f"{dives.size:,}",
            }
        )
    return rows


#: Every variable the assignment reads: (name, how it is used). The page lists each with
#: whether this file has it.
INPUT_VARIABLES: tuple[tuple[str, str], ...] = (
    ("dive_number", "groups rows into dives"),
    ("TIME", "orders rows; compared with state and G&C event times"),
    ("gc_state_state", "step 1a: the state table, when the file has one"),
    (
        "gc_state_eop_code",
        "check only: why each state ended (Seaglider state table, below)",
    ),
    (
        "gc_vbd_ctl",
        "step 1b: the G&C event that moves the VBD to zero is the inflection",
    ),
    ("gc_end_secs", "step 1b: where that G&C event ends"),
    ("PRES", "step 1c: the pressure maximum, when there are no G&C events"),
    ("TIME_GPS", "step 2: rows at GPS fix times are surfacing"),
    ("PITCH", "check only: drawn, and plotted against dP/dt"),
    ("log_D_FLARE", "check only: drawn as a dashed line"),
    ("log_D_TGT", "check only: drawn as a dashed line"),
    ("log_D_SURF", "check only: drawn as a dashed line"),
)


def _input_rows(path: str | Path) -> list[dict[str, str]]:
    """Return the input variables with whether the file at ``path`` has them."""
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        present = set(ds.variables)
    return [
        {"name": name, "use": use, "present": "yes" if name in present else "no"}
        for name, use in INPUT_VARIABLES
    ]


def _state_rows(path: str | Path) -> list[dict[str, object]]:
    """Return one row per begin/end pair of Seaglider states: names, PHASE, counts, endings.

    Every state code the basestation numbers appears in one pair. The PHASE is the one the
    OG1 phase translation table gives the transition from the begin state to the end state;
    a pair that table does not list changes nothing (the phase before it carries on).
    """
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        state = (
            np.asarray(ds["gc_state_state"].values, dtype=float)
            if "gc_state_state" in ds.variables
            else np.array([])
        )
        eop = (
            np.asarray(ds["gc_state_eop_code"].values, dtype=float)
            if "gc_state_eop_code" in ds.variables
            else np.full(state.size, np.nan)
        )
    rows = []
    for begin in range(0, max(_phase.GC_STATE_NAMES) + 1, 2):
        end = begin + 1
        listed = (begin, end) in _phase.GC_TRANSITIONS
        phase = _phase.GC_TRANSITIONS.get((begin, end))
        endings = sorted(
            {int(e) for e in eop[state == end] if np.isfinite(e) and e >= 0}
        )
        rows.append(
            {
                "transition": f"{begin} → {end}",
                "states": (
                    f"{_phase.GC_STATE_NAMES[begin]} → {_phase.GC_STATE_NAMES[end]}"
                ),
                "phase": _label(phase) if listed else "no change",
                "color": PHASE_COLORS[phase] if listed else "transparent",
                "source": "OG1 phase table" if listed else "not in the OG1 table",
                "count": int((state == begin).sum()),
                "eop": ", ".join(
                    _phase.EOP_CODES[e] if e < len(_phase.EOP_CODES) else str(e)
                    for e in endings
                ),
            }
        )
    return rows


def phase_context(path: str | Path) -> dict[str, object] | None:
    """Return the phase page's figures, tables and text, or None when the file has no PHASE.

    The dive figures and the pitch against dP/dt figure show :func:`pick_dives` (one near
    the start, middle and end of the mission); the bars and the counts cover every dive.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file.

    Returns
    -------
    dict or None
        Template context for ``phase.html``.
    """
    from seagliderOG1.reports._vendored import figure_png
    from seagliderOG1.reports._vendored.design_tokens import W_THREE_FIFTHS

    ds = _load_for_page(path)
    if ds is None:
        return None
    dives = pick_dives(ds)
    if not dives:
        return None
    n_dives = int(
        np.unique(ds["dive_number"].values[np.isfinite(ds["dive_number"].values)]).size
    )
    dive_figures = []
    for dive in dives:
        png = figure_png.render_b64(
            draw_phase_dive,
            ds,
            dive,
            width_in=W_FULL,
            source="phase.py:draw_phase_dive",
        )
        dive_figures.append(
            {
                "dive": dive,
                "complete": is_complete(ds, dive),
                "png": png,
                "source": figure_png.source_of(png),
            }
        )
    bars_width = W_THREE_FIFTHS if n_dives <= _MIN_SLOTS else W_FULL
    bars_png = figure_png.render_b64(
        draw_phase_fractions,
        ds,
        width_in=bars_width,
        source="phase.py:draw_phase_fractions",
    )
    scatter_png = figure_png.render_b64(
        draw_phase_pitch_dpdt,
        [(f"dive {dive}", ds, dive) for dive in dives],
        width_in=W_FULL if len(dives) > 1 else W_THREE_FIFTHS,
        optional=True,
        source="phase.py:draw_phase_pitch_dpdt",
    )
    attrs = ds["PHASE"].attrs
    return {
        "dives": dives,
        "dive_figures": dive_figures,
        "n_dives": n_dives,
        "few_dives": n_dives <= _MAX_ORDER_LABELS,
        "method": attrs.get("phase_calculation_method", ""),
        "vocabulary": attrs.get("phase_vocabulary", ""),
        "docs_url": DOCS_URL,
        "pseudocode": PSEUDOCODE,
        "inputs": _input_rows(path),
        "states": _state_rows(path),
        "qc_meanings": _phase.PHASE_QC_ATTRS["flag_meanings"],
        "rows": _phase_rows(ds),
        "bars_png": bars_png,
        "bars_slot": "slot-three-fifths" if bars_width == W_THREE_FIFTHS else "",
        "bars_source": figure_png.source_of(bars_png),
        "scatter_png": scatter_png,
        "scatter_slot": "" if len(dives) > 1 else "slot-three-fifths",
        "scatter_source": figure_png.source_of(scatter_png),
    }


#: The assignment as the code runs it, per dive file, for the phase page.
PSEUDOCODE = """\
for each dive:
    PHASE = 0 (unknown) on every row

    # step 1: from the first signal the file has
    if the dive has a state table (gc_state_state):
        sort states by time (same-second states keep file order)
        each begin state of a transition the OG1 phase translation table names
        (Seaglider column) sets that PHASE from its time until the next named
        begin state:
            0 begin dive    (-> 1 end dive)             2 descent
            2 begin climb   (-> 3 end climb)            1 ascent
            4 begin apogee  (-> 5 end apogee)           5 inflection
            6 begin loiter  (-> 7 end loiter)           4 parking
            10 begin subsurface finish (-> 11 end)      5 inflection
            14 begin surface (-> 15 end surface)        3 surfacing
          not named in the OG1 table, so they change nothing (the phase
          before them carries on):
            8 begin surface coast -> 9 end surface coast
            12 begin recovery     -> 13 end recovery
          a code with no name -> WARNING, changes nothing
        the last named transition runs to the end of the dive file
        rows before the first named begin state: the phase of the first named
          end state (a file opens with 15 end surface -> 3 surfacing)
    elif the dive has G&C events (gc_vbd_ctl, gc_end_secs):
        apogee = the event with VBD at zero after an event with VBD bled (negative);
                 if several, the one nearest the deepest sample
        rows before the apogee event -> 2 descent
        rows in the apogee event     -> 5 inflection
        rows after it                -> 1 ascent
    else:
        rows up to the (last) pressure maximum -> 2 descent, rows after -> 1 ascent

    # step 2: GPS fixes
    rows at a GPS fix time (TIME_GPS) -> 3 surfacing
      (the CTD does not sample at the surface: these are the fix rows only)

    # step 3 (state table only): rows still 0 take the phase of the row before

PHASE_QC = 0 (no QC performed) on every row
No transition (7): the OG1 table gives Seaglider none.
"""


def render_phase(path: str | Path, *, title: str | None = None) -> str | None:
    """Return the phase page for an OG1 file as self-contained HTML, or None without PHASE.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`.
    title : str, optional
        The page title; defaults to the file name.

    Returns
    -------
    str or None
        The rendered page, or None when the file has no ``PHASE``.
    """
    from datetime import UTC, datetime

    from seagliderOG1 import __version__, writers
    from seagliderOG1.reports import design
    from seagliderOG1.reports._env import get_template
    from seagliderOG1.reports.conversion import _page_nav

    context = phase_context(path)
    if context is None:
        return None
    return get_template("phase.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        page_nav=_page_nav(
            current="phase",
            conversion_href=writers.conversion_path(path, ".html").name,
        ),
        p=context,
    )


def write_phase_page(
    nc_path: str | Path, conversion_page: str | Path, *, title: str | None = None
) -> Path | None:
    """Write the phase page beside the conversion page; return it, or None without PHASE.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; the phase page goes in the same folder.
    title : str, optional
        Page title; the file name by default.

    Returns
    -------
    pathlib.Path or None
        The phase page, or None when the file has no ``PHASE``.
    """
    from seagliderOG1 import writers

    html = render_phase(nc_path, title=title)
    if html is None:
        return None
    target = Path(conversion_page).with_name(writers.phase_page_path(nc_path).name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target
