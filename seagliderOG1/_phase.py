"""Assign the OG1 ``PHASE`` from what the Seaglider recorded it did.

Three signals, in order of precedence, per dive:

1. the glider's state table (``gc_state_state``, basestation 2.10 and later): each state
   sets the phase from its time to the next state's;
2. the guidance-and-control (G&C) events (``gc_st_secs``, ``gc_end_secs``, ``gc_vbd_ctl``),
   for files without a state table: the apogee is the G&C event that moves the VBD to
   zero, descent before it, ascent after;
3. pressure, for files with neither: descent up to the pressure maximum, ascent after.

GPS fixes are surfacing (3) in every case. The inflection (5) is the state table's
apogee, from "begin apogee" to "end apogee"; without a state table it is the G&C event
that moves the VBD to zero, which is where those two states fall when both are recorded.
Descent before the last sample shallower than ``$D_FLARE`` (``log_D_FLARE``) is
transition (7): the glider bleeding at the surface before it pitches up to dive. So is
ascent from the end of the apogee to the deepest sample: the glider is pumping and pitching
up but still sinking. That is
the one command used; ``log_D_TGT``, ``log_D_SURF`` and ``log_LOITER_*`` are not. No quality
control is applied: ``PHASE_QC`` is 0 throughout, and ``PHASE``'s
``phase_calculation_method`` says which signal assigned which dives.

The meaning of each state code was read from the data (the order of states within a dive,
their times against pressure and the G&C events), not from a code table; each entry of
:data:`GC_STATE_CODES` names the evidence.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import xarray as xr

_log = logging.getLogger(__name__)

#: OG1 phase vocabulary ids used here.
UNKNOWN, ASCENT, DESCENT, SURFACING, PARKING, INFLECTION = 0, 1, 2, 3, 4, 5
TRANSITION = 7

#: State code -> (state name, OG1 phase from this state until the next).
#: Evidence: sg271 dives 2-3 (basestation 3.0.6) and sg033 2010-09-03 and dg042 2022-07-18
#: (basestation 2.10) read the codes in the same order every dive - 0 1 4 5 2 3 8 9 - with
#: end-of-phase code 1 on state 1 (target depth reached) and 2 on state 3 (surface depth
#: reached), state 4 starting the G&C event that moves the VBD to zero at the target
#: depth, and state 2 starting the event that moves it positive. 14 and 15 appear only on
#: basestation 3.0.6, as the last and first states of a dive file (the surface manoeuvre);
#: basestation 2.10 uses 8 and 9 there instead. Surfacing starts at "begin surface coast"
#: (provisional: the glider is still rising above $D_SURF, and where surfacing should start
#: is not settled).
GC_STATE_CODES: dict[int, tuple[str, int]] = {
    0: ("begin dive", DESCENT),
    1: ("end dive", DESCENT),
    4: ("begin apogee", INFLECTION),
    5: ("end apogee", INFLECTION),
    2: ("begin climb", ASCENT),
    3: ("end climb", ASCENT),
    8: ("begin surface coast", SURFACING),
    9: ("end surface coast", SURFACING),
    14: ("begin surface", SURFACING),
    15: ("end surface", SURFACING),
}

#: OG1 phase vocabulary: id -> name, in id order (``flag_values``/``flag_meanings`` on PHASE).
PHASE_NAMES: dict[int, str] = {
    0: "unknown",
    1: "ascent",
    2: "descent",
    3: "surfacing",
    4: "parking",
    5: "inflection",
    6: "propelled",
    7: "transition",
}

#: Method key -> the words ``phase_calculation_method`` uses for it.
METHOD_TEXT: dict[str, str] = {
    "states": "the glider's state table (gc_state_state)",
    "events": "the guidance-and-control events (gc_vbd_ctl, gc_end_secs)",
    "pressure": "pressure alone (descent to the pressure maximum, ascent after)",
}

#: PHASE_QC attributes, as the OG1 format lists them. No QC is applied: every value is 0.
PHASE_QC_ATTRS = {
    "long_name": "quality flag",
    "standard_name": "status_flag",
    "valid_range": np.array([0, 4], "int8"),
    "flag_values": np.array([0, 1, 2, 3, 4], "int8"),
    "flag_meanings": (
        "no_qc_performed good_data probably_good_data probably_bad_data bad_data"
    ),
}


def method_text(methods: dict[str, list[int]]) -> str:
    """Return ``phase_calculation_method``: which signal assigned which dives.

    Parameters
    ----------
    methods : dict of str to list of int
        Dive numbers by method, as :func:`assign` returns them.

    Returns
    -------
    str
        One clause per method used, then the rules every method shares.
    """
    parts = [
        f"{METHOD_TEXT[key]} on {_dives(methods[key])}"
        for key in ("states", "events", "pressure")
        if methods.get(key)
    ]
    used = "; ".join(parts) if parts else "no dives"
    flare = (
        f" Descent before the last sample above $D_FLARE (log_D_FLARE) is transition "
        f"({_dives(methods['flare'])})."
        if methods.get("flare")
        else ""
    )
    bottom = (
        " Ascent from the end of the apogee to the deepest sample is transition "
        f"({_dives(methods['bottom'])})."
        if methods.get("bottom")
        else ""
    )
    return (
        f"From {used}.{flare}{bottom} Rows at GPS fix times are surfacing; no other command "
        "(log_D_TGT, log_D_SURF, log_LOITER_*) is used."
    )


def _dives(numbers: list[int]) -> str:
    """Return ``"dive 4"`` or ``"dives 1-3, 5"``."""
    return ("dive " if len(set(numbers)) == 1 else "dives ") + _ranges(numbers)


def _ranges(numbers: list[int]) -> str:
    """Return ``"1-3, 5"`` for ``[1, 2, 3, 5]``."""
    numbers = sorted(set(numbers))
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ", ".join(
        str(run[0]) if len(run) == 1 else f"{run[0]}-{run[-1]}" for run in runs
    )


#: Dive-number variable names, in the order they are looked for.
_DIVE_NAMES = ("dive_number", "divenum", "dive_num", "DIVE_NUMBER")

#: Metres past $D_FLARE after which a shallower sample no longer counts as the flare.
_FLARE_MARGIN_M = 10.0

#: |gc_vbd_ctl| (cm3) below which the VBD counts as moved to zero (the apogee event).
_VBD_ZERO = 1.0


def dive_variable(ds: xr.Dataset) -> str:
    """Return the name of the dive-number variable in ``ds``.

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset on ``N_MEASUREMENTS``.

    Returns
    -------
    str
        The first of ``dive_number``, ``divenum``, ``dive_num``, ``DIVE_NUMBER`` present.

    Raises
    ------
    ValueError
        If none is present.
    """
    for name in _DIVE_NAMES:
        if name in ds.variables:
            return name
    raise ValueError("No valid dive number variable found in the dataset.")


def _seconds(values: np.ndarray) -> np.ndarray:
    """Return ``values`` (datetime64 or unix seconds) as float unix seconds, NaN for NaT."""
    values = np.asarray(values)
    if np.issubdtype(values.dtype, np.datetime64):
        out = values.astype("datetime64[ns]").astype("int64") / 1e9
        out[np.isnat(values)] = np.nan
        return out
    return values.astype(float)


def _states(
    ds: xr.Dataset, rows: np.ndarray, time: np.ndarray
) -> list[tuple[float, int]]:
    """Return the dive's state table as (time, code) pairs in time order."""
    if "gc_state_state" not in ds.variables:
        return []
    code = ds["gc_state_state"].values[rows]
    keep = np.isfinite(code)
    t, c = time[keep], code[keep].astype(int)
    # Pairs of states share a second (end dive / begin apogee, …): a stable sort on time
    # keeps them in the order the file wrote them.
    order = np.argsort(t, kind="stable")
    return [(float(t[i]), int(c[i])) for i in order]


def _events(
    ds: xr.Dataset, rows: np.ndarray, time: np.ndarray
) -> list[tuple[float, float, float]]:
    """Return the dive's G&C events as (start, end, vbd_ctl) in time order."""
    if "gc_vbd_ctl" not in ds.variables or "gc_end_secs" not in ds.variables:
        return []
    vbd = ds["gc_vbd_ctl"].values[rows].astype(float)
    end = _seconds(ds["gc_end_secs"].values[rows])
    keep = np.isfinite(vbd) & np.isfinite(end)
    return sorted(zip(time[keep], end[keep], vbd[keep], strict=True))


def _apogee_window(
    events: list[tuple[float, float, float]],
) -> tuple[float, float] | None:
    """Return (start, end) of the apogee G&C event, or None.

    The apogee event is the first that moves the VBD to zero after an event with the VBD
    negative (bled). Where a file has a state table too, "begin apogee" and "end apogee"
    fall at this event's start and end (sg271, sg033, dg042).
    """
    bled = False
    for start, end, vbd in events:
        if vbd < -_VBD_ZERO:
            bled = True
        elif bled and abs(vbd) <= _VBD_ZERO:
            return start, end
    return None


def command(
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
            lookup = dict(zip(record["dives"], record["values"], strict=True))
        except (ValueError, KeyError, TypeError):
            return None
        value = lookup.get(dive)
        return None if value is None else float(value)
    values = raw.astype(float)
    if (
        values.ndim == 1
        and rows is not None
        and values.size == ds.sizes.get("N_MEASUREMENTS")
    ):
        values = values[rows]
    values = values[np.isfinite(values)].ravel()
    return float(values[0]) if values.size else None


def _mark_flare(
    t: np.ndarray, depth: np.ndarray, phase: np.ndarray, d_flare: float | None
) -> bool:
    """Mark descent up to the last time the glider was above ``$D_FLARE`` as transition.

    Before the flare the glider is bleeding at the surface with its nose full down; at
    ``$D_FLARE`` it pitches up to the dive angle. The *last* sample shallower than
    ``$D_FLARE`` before the apogee is used, not the first deeper one: a glider can sink
    past ``$D_FLARE`` and come back above it before the dive proper starts (sg537 dive 1).
    Returns True when any sample was marked.
    """
    if d_flare is None or not np.isfinite(d_flare):
        return False
    descent = phase == DESCENT
    if not descent.any():
        return False
    # Only the descent before the first inflection or ascent sample.
    later = np.flatnonzero(np.isin(phase, (INFLECTION, ASCENT)))
    end = t[later].min() if later.size else np.inf
    # Only before the glider is first well past $D_FLARE, so one bad shallow sample deeper
    # in the dive cannot stretch the transition down the whole descent.
    deep = descent & np.isfinite(depth) & (depth > d_flare + _FLARE_MARGIN_M)
    if deep.any():
        end = min(end, t[deep].min())
    above = descent & (t < end) & np.isfinite(depth) & (depth < d_flare)
    if not above.any():
        return False
    last = t[above].max()
    phase[descent & (t <= last)] = TRANSITION
    return True


def _mark_bottom_transition(t: np.ndarray, pres: np.ndarray, phase: np.ndarray) -> bool:
    """Mark ascent before the pressure maximum as transition.

    After the apogee ends the glider pumps oil and pitches up, but it often keeps sinking
    for a while: its deepest sample falls after "end apogee". Ascent rows up to and
    including the deepest sample are transition. Returns True when any row was marked.
    """
    inflection = phase == INFLECTION
    ok = np.isfinite(pres)
    if not inflection.any() or not ok.any():
        return False
    deepest = t[ok][np.argmax(pres[ok])]
    sel = (phase == ASCENT) & (t > t[inflection].max()) & (t <= deepest)
    if not sel.any():
        return False
    phase[sel] = TRANSITION
    return True


def _assign_from_states(
    t: np.ndarray, states: list[tuple[float, int]], phase: np.ndarray
) -> set[int]:
    """Set phase from the state table; return the codes seen that have no meaning here."""
    unknown: set[int] = set()
    for k, (start, code) in enumerate(states):
        if code not in GC_STATE_CODES:
            unknown.add(code)
            continue
        value = GC_STATE_CODES[code][1]
        # The last state runs to the end of the dive file (a file cut off mid-dive keeps
        # the last state's phase to its end).
        stop = states[k + 1][0] if k + 1 < len(states) else np.inf
        sel = (t >= start) & (t < stop)
        phase[sel] = value
    return unknown


def _assign_from_events(
    t: np.ndarray, window: tuple[float, float], phase: np.ndarray
) -> None:
    """Set descent before the apogee window, inflection in it, ascent after."""
    start, stop = window
    phase[t < start] = DESCENT
    phase[(t >= start) & (t <= stop)] = INFLECTION
    phase[t > stop] = ASCENT


def _assign_from_pressure(pres: np.ndarray, phase: np.ndarray) -> None:
    """Set descent up to and including the pressure maximum, ascent after."""
    if not np.isfinite(pres).any():
        return
    imax = int(np.nanargmax(pres))
    phase[: imax + 1] = DESCENT
    phase[imax + 1 :] = ASCENT


def assign(ds: xr.Dataset) -> tuple[np.ndarray, dict[str, list[int]]]:
    """Return PHASE for every sample of ``ds``, and which method each dive used.

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset on ``N_MEASUREMENTS`` with ``TIME``, ``PRES``, a dive-number variable and,
        when the file has them, ``TIME_GPS``, ``gc_state_state``, ``gc_vbd_ctl`` and
        ``gc_end_secs`` merged onto ``TIME``.

    Returns
    -------
    phase : numpy.ndarray of int8
        The OG1 phase id per sample (0 where no signal claims it).
    methods : dict of str to list of int
        Dive numbers by the method that assigned them: ``"states"``, ``"events"``,
        ``"pressure"``; under ``"flare"`` the dives with a transition before
        ``$D_FLARE``, and under ``"bottom"`` those with a transition between the end of the
        apogee and the pressure maximum.
    """
    n = ds.sizes["N_MEASUREMENTS"]
    phase = np.zeros(n, dtype="int8")
    methods: dict[str, list[int]] = {
        "states": [],
        "events": [],
        "pressure": [],
        "flare": [],
        "bottom": [],
    }
    dive = np.asarray(ds[dive_variable(ds)].values, dtype=float)
    time = _seconds(ds["TIME"].values)
    pres = (
        ds["PRES"].values.astype(float)
        if "PRES" in ds.variables
        else np.full(n, np.nan)
    )
    gps_time = (
        _seconds(ds["TIME_GPS"].values)
        if "TIME_GPS" in ds.variables
        else np.full(n, np.nan)
    )
    depth_all = (
        np.asarray(ds["DEPTH"].values, dtype=float)
        if "DEPTH" in ds.variables
        else np.full(n, np.nan)
    )
    # A GPS fix can reach N_MEASUREMENTS twice (the fix row and the gps_info row at the
    # same time): every row at a fix time is surfacing.
    gps = np.isin(time, gps_time[np.isfinite(gps_time)])
    unknown_codes: set[int] = set()
    for number in np.unique(dive[np.isfinite(dive)]):
        rows = np.where(dive == number)[0]
        t = time[rows]
        p_phase = np.zeros(rows.size, dtype="int8")
        states = _states(ds, rows, t)
        sample = ~gps[rows]
        if states:
            unknown_codes |= _assign_from_states(t, states, p_phase)
            methods["states"].append(int(number))
        elif (window := _apogee_window(_events(ds, rows, t))) is not None:
            sub = p_phase[sample]
            _assign_from_events(t[sample], window, sub)
            p_phase[sample] = sub
            methods["events"].append(int(number))
        else:
            sub = p_phase[sample]
            _assign_from_pressure(pres[rows][sample], sub)
            p_phase[sample] = sub
            methods["pressure"].append(int(number))
        if _mark_bottom_transition(t, pres[rows], p_phase):
            methods["bottom"].append(int(number))
        d_flare = command(ds, "log_D_FLARE", int(number), rows)
        # DEPTH, or PRES (dbar, close to metres near the surface) on a dive without it.
        depth = depth_all[rows] if np.isfinite(depth_all[rows]).any() else pres[rows]
        if _mark_flare(t, depth, p_phase, d_flare):
            methods["flare"].append(int(number))
        p_phase[gps[rows]] = SURFACING
        phase[rows] = p_phase
    if unknown_codes:
        _log.warning(
            "gc_state_state codes %s have no known meaning; their samples are PHASE 0.",
            sorted(unknown_codes),
        )
    return phase, methods
