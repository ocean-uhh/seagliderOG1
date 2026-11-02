"""Assign the OG1 ``PHASE`` from what the Seaglider recorded it did.

Three signals, in order of precedence, per dive:

1. the glider's state table (``gc_state_state``, basestation 2.10 and later): each state
   sets the phase from its time to the next state's;
2. the guidance-and-control (G&C) events (``gc_st_secs``, ``gc_end_secs``, ``gc_vbd_ctl``),
   for files without a state table: the apogee is the G&C event that moves the VBD to
   zero, descent before it, ascent after;
3. pressure, for files with neither: descent up to the pressure maximum, ascent after.

GPS fixes are surfacing (3) in every case. The apogee (inflexion, 5) spans the two G&C
cycles the Seaglider manual describes: the cycle that moves the VBD to zero and the cycle
that moves pitch and VBD to the climb. Commands (``log_D_*``, ``log_LOITER_*``) are never
used to assign a phase.

The meaning of each state code was read from the data (the order of states within a dive,
their times against pressure and the G&C events), not from a code table; each entry of
:data:`GC_STATE_CODES` names the evidence.
"""

from __future__ import annotations

import logging

import numpy as np
import xarray as xr

_log = logging.getLogger(__name__)

#: OG1 phase vocabulary ids used here.
UNKNOWN, ASCENT, DESCENT, SURFACING, PARKING, INFLEXION = 0, 1, 2, 3, 4, 5

#: State code -> (state name, OG1 phase from this state until the next).
#: Evidence: sg271 dives 2-3 (basestation 3.0.6) and sg033 2010-09-03 and dg042 2022-07-18
#: (basestation 2.10) read the codes in the same order every dive - 0 1 4 5 2 3 8 9 - with
#: end-of-phase code 1 on state 1 (target depth reached) and 2 on state 3 (surface depth
#: reached), state 4 starting the G&C event that moves the VBD to zero at the target
#: depth, and state 2 starting the event that moves it positive. 14 and 15 appear only on
#: basestation 3.0.6, as the last and first states of a dive file (the surface manoeuvre);
#: basestation 2.10 uses 8 and 9 there instead, so an 8 after a 9 is the surface.
GC_STATE_CODES: dict[int, tuple[str, int]] = {
    0: ("begin dive", DESCENT),
    1: ("end dive", DESCENT),
    4: ("begin apogee", INFLEXION),
    5: ("end apogee", INFLEXION),
    2: ("begin climb", ASCENT),
    3: ("end climb", ASCENT),
    8: ("begin surface coast", ASCENT),
    9: ("end surface coast", SURFACING),
    14: ("begin surface", SURFACING),
    15: ("end surface", SURFACING),
}

#: PHASE_QC flag values (OG1 / Argo quality-flag scale) and what each says here.
QC_STATE = 1  # good: from the glider's state table, or a GPS fix
QC_EVENTS = 2  # probably good: from the G&C events, no state table
QC_PRESSURE = 8  # estimated: from pressure alone
QC_MISSING = 9  # missing: PHASE is 0 (unknown)

PHASE_QC_ATTRS = {
    "long_name": "behavior of the glider at sea quality flag",
    "standard_name": "status_flag",
    "flag_values": np.array([QC_STATE, QC_EVENTS, QC_PRESSURE, QC_MISSING], "int8"),
    "flag_meanings": "good probably_good estimated missing_value",
    "comment": (
        "How PHASE was assigned: 1 from the glider's state table (gc_state_state) or a "
        "GPS fix; 2 from the guidance-and-control events (no state table in the file); "
        "8 from pressure alone (descent to the pressure maximum, ascent after); "
        "9 where PHASE is 0 (unknown)."
    ),
}

#: Dive-number variable names, in the order they are looked for.
_DIVE_NAMES = ("dive_number", "divenum", "dive_num", "DIVE_NUMBER")

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
    """Return (start, end) of the two apogee G&C cycles, or None.

    The first cycle is the first event that moves the VBD to zero after an event with the
    VBD negative (bled); the second is the event after it, which moves pitch and VBD to
    the climb. The window runs from the first's start to the second's end.
    """
    bled = False
    for i, (start, end, vbd) in enumerate(events):
        if vbd < -_VBD_ZERO:
            bled = True
        elif bled and abs(vbd) <= _VBD_ZERO:
            stop = events[i + 1][1] if i + 1 < len(events) else end
            return start, stop
    return None


def _assign_from_states(
    t: np.ndarray, states: list[tuple[float, int]], phase: np.ndarray, qc: np.ndarray
) -> set[int]:
    """Set phase from the state table; return the codes seen that have no meaning here."""
    unknown: set[int] = set()
    previous = None
    for k, (start, code) in enumerate(states):
        if code not in GC_STATE_CODES:
            unknown.add(code)
            previous = code
            continue
        value = GC_STATE_CODES[code][1]
        # Basestation 2.10: an 8 straight after a 9 is the surface, not the coast.
        if code == 8 and previous == 9:
            value = SURFACING
        # The last state runs to the end of the dive file (a file cut off mid-dive keeps
        # the last state's phase to its end).
        stop = states[k + 1][0] if k + 1 < len(states) else np.inf
        sel = (t >= start) & (t < stop)
        phase[sel] = value
        qc[sel] = QC_STATE
        previous = code
    return unknown


def _assign_from_events(
    t: np.ndarray, window: tuple[float, float], phase: np.ndarray, qc: np.ndarray
) -> None:
    """Set descent before the apogee window, inflexion in it, ascent after."""
    start, stop = window
    phase[t < start] = DESCENT
    phase[(t >= start) & (t <= stop)] = INFLEXION
    phase[t > stop] = ASCENT
    qc[:] = QC_EVENTS


def _assign_from_pressure(pres: np.ndarray, phase: np.ndarray, qc: np.ndarray) -> None:
    """Set descent up to and including the pressure maximum, ascent after."""
    if not np.isfinite(pres).any():
        return
    imax = int(np.nanargmax(pres))
    phase[: imax + 1] = DESCENT
    phase[imax + 1 :] = ASCENT
    qc[:] = QC_PRESSURE


def _widen_apogee(
    t: np.ndarray, window: tuple[float, float] | None, phase: np.ndarray
) -> None:
    """Mark the two apogee G&C cycles inflexion over what the state table said.

    The state table ends the apogee when the second cycle (pitch and VBD to the climb)
    starts; the glider is still turning through it, and often reaches its pressure maximum
    there.
    """
    if window is None:
        return
    start, stop = window
    phase[(t >= start) & (t <= stop) & (phase != UNKNOWN)] = INFLEXION


def assign(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    """Return PHASE and PHASE_QC for every sample of ``ds``, and which method each dive used.

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
    qc : numpy.ndarray of int8
        The PHASE_QC flag per sample (see :data:`PHASE_QC_ATTRS`).
    methods : dict of str to list of int
        Dive numbers by the method that assigned them: ``"states"``, ``"events"``,
        ``"pressure"``.
    """
    n = ds.sizes["N_MEASUREMENTS"]
    phase = np.zeros(n, dtype="int8")
    qc = np.full(n, QC_MISSING, dtype="int8")
    methods: dict[str, list[int]] = {"states": [], "events": [], "pressure": []}
    dive = ds[dive_variable(ds)].values
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
    # A GPS fix can reach N_MEASUREMENTS twice (the fix row and the gps_info row at the
    # same time): every row at a fix time is surfacing.
    gps = np.isin(time, gps_time[np.isfinite(gps_time)])
    unknown_codes: set[int] = set()
    for number in np.unique(dive[np.isfinite(dive)]):
        rows = np.where(dive == number)[0]
        t = time[rows]
        p_phase = np.zeros(rows.size, dtype="int8")
        p_qc = np.full(rows.size, QC_MISSING, dtype="int8")
        states = _states(ds, rows, t)
        window = _apogee_window(_events(ds, rows, t))
        sample = ~gps[rows]
        if states:
            unknown_codes |= _assign_from_states(t, states, p_phase, p_qc)
            _widen_apogee(t, window, p_phase)
            methods["states"].append(int(number))
        elif window is not None:
            sub_phase = p_phase[sample]
            sub_qc = p_qc[sample]
            _assign_from_events(t[sample], window, sub_phase, sub_qc)
            p_phase[sample], p_qc[sample] = sub_phase, sub_qc
            methods["events"].append(int(number))
        else:
            sub_phase = p_phase[sample]
            sub_qc = p_qc[sample]
            _assign_from_pressure(pres[rows][sample], sub_phase, sub_qc)
            p_phase[sample], p_qc[sample] = sub_phase, sub_qc
            methods["pressure"].append(int(number))
        p_phase[gps[rows]] = SURFACING
        p_qc[gps[rows]] = QC_STATE
        p_qc[p_phase == UNKNOWN] = QC_MISSING
        phase[rows], qc[rows] = p_phase, p_qc
    if unknown_codes:
        _log.warning(
            "gc_state_state codes %s have no known meaning; their samples are PHASE 0.",
            sorted(unknown_codes),
        )
    return phase, qc, methods
