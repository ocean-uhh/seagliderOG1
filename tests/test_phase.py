"""PHASE from the state table, the G&C events, GPS and pressure, on real dives."""

import pathlib
import shutil

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, _phase, _pipeline, tools

DATA = pathlib.Path(__file__).resolve().parent.parent
SG271 = DATA / "seagliderOG1" / "data" / "sg271"
SG005 = DATA / "data" / "demo_sg005"

#: The order the Seaglider runs its phases in, per dive file.
ORDER = (3, 2, 5, 1, 3)


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory) -> xr.Dataset:
    """Return sg271 dives 1-3 (basestation 3.0.6, state table) converted to OG1."""
    out = _convert._convert_mission(SG271, tmp_path_factory.mktemp("sg271_phase"))
    return xr.load_dataset(out)


@pytest.fixture(scope="module")
def sg005(tmp_path_factory: pytest.TempPathFactory) -> xr.Dataset:
    """Return sg005 dives 1-5 (basestation 2.8, G&C events, no state table) as OG1."""
    out = _convert._convert_mission(SG005, tmp_path_factory.mktemp("sg005_phase"))
    return xr.load_dataset(out)


def _runs(phase: np.ndarray) -> list[int]:
    """Return the phase ids of ``phase``'s runs, in order."""
    return [int(phase[0])] + [
        int(b) for a, b in zip(phase[:-1], phase[1:], strict=True) if a != b
    ]


def _is_in_order(runs: list[int]) -> bool:
    """Return True when ``runs`` follows ORDER without going back."""
    position = 0
    for run in runs:
        while position < len(ORDER) and ORDER[position] != run:
            position += 1
        if position == len(ORDER):
            return False
    return True


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_every_dive_runs_surface_descent_inflexion_ascent_surface(mission, request):
    """Per dive the phases follow 3 2 5 1 3, each once (sg271 dive 1 stops at the apogee)."""
    ds = request.getfixturevalue(mission)
    dive = ds["DIVE_NUMBER"].values
    for number in np.unique(dive):
        runs = _runs(ds["PHASE"].values[dive == number])
        assert _is_in_order(runs), (number, runs)
        assert len(runs) == len(set(runs)) or runs.count(3) == 2, (number, runs)
        assert 0 not in runs


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_one_inflexion_run_holds_the_pressure_maximum(mission, request):
    """Each dive has exactly one inflexion run, and the deepest sample is in it."""
    ds = request.getfixturevalue(mission)
    dive = ds["DIVE_NUMBER"].values
    for number in np.unique(dive):
        rows = dive == number
        phase = ds["PHASE"].values[rows]
        assert _runs(phase).count(_phase.INFLEXION) == 1
        pres = ds["PRES"].values[rows]
        assert phase[np.nanargmax(pres)] == _phase.INFLEXION


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_gps_fixes_are_surfacing_and_good(mission, request):
    """Every row at a GPS fix time is 3 with PHASE_QC 1; no CTD sample deeper than 1 dbar is 3."""
    ds = request.getfixturevalue(mission)
    fixes = ds["TIME_GPS"].values[~np.isnat(ds["TIME_GPS"].values)]
    at_fix = np.isin(ds["TIME"].values, fixes)
    assert at_fix.sum() >= 3 * np.unique(ds["DIVE_NUMBER"].values).size
    assert (ds["PHASE"].values[at_fix] == _phase.SURFACING).all()
    assert (ds["PHASE_QC"].values[at_fix] == _phase.QC_STATE).all()
    deep = ds["PRES"].values > 1
    assert not (ds["PHASE"].values[deep] == _phase.SURFACING).any()


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_descent_sinks_and_ascent_rises(mission, request):
    """Median dP/dt is positive on descent rows and negative on ascent rows."""
    ds = request.getfixturevalue(mission)
    keep = np.isfinite(ds["PRES"].values)
    t = ds["TIME"].values[keep].astype("datetime64[ns]").astype("int64") / 1e9
    dpdt = np.gradient(ds["PRES"].values[keep], t)
    phase = ds["PHASE"].values[keep]
    assert np.nanmedian(dpdt[phase == _phase.DESCENT]) > 0.05
    assert np.nanmedian(dpdt[phase == _phase.ASCENT]) < -0.05


def test_state_table_assigns_sg271_and_events_assign_sg005(sg271, sg005):
    """sg271 rows are flagged 1 (state table); sg005's CTD rows 2 (G&C events)."""
    assert set(np.unique(sg271["PHASE_QC"].values)) == {_phase.QC_STATE}
    sample = ~np.isin(
        sg005["TIME"].values,
        sg005["TIME_GPS"].values[~np.isnat(sg005["TIME_GPS"].values)],
    )
    assert set(np.unique(sg005["PHASE_QC"].values[sample])) == {_phase.QC_EVENTS}
    assert sg271["PHASE"].dtype == np.int8
    assert sg271["PHASE_QC"].attrs["flag_meanings"].split()[0] == "good"
    assert sg271["PHASE"].attrs["ancillary_variables"] == "PHASE_QC"


def test_inflexion_covers_both_apogee_cycles(sg271):
    """The inflexion starts at state 4 and ends with the G&C event after the VBD-zero one."""
    dive = sg271["DIVE_NUMBER"].values == 2
    time = sg271["TIME"].values[dive]
    phase = sg271["PHASE"].values[dive]
    state = sg271["gc_state_state"].values[dive]
    begin_apogee = time[state == 4][0]
    begin_climb = time[state == 2][0]
    inflexion = time[phase == _phase.INFLEXION]
    assert inflexion.min() >= begin_apogee
    assert inflexion.max() > begin_climb


def test_ascent_starts_where_the_apogee_cycles_end(sg271):
    """sg271 dive 2: every non-GPS row after the second apogee G&C cycle and before the
    surface coast ends is ascent; every row from begin dive to begin apogee is descent."""
    dive = sg271["DIVE_NUMBER"].values == 2
    time = sg271["TIME"].values[dive]
    phase = sg271["PHASE"].values[dive]
    state = sg271["gc_state_state"].values[dive]
    vbd = sg271["gc_vbd_ctl"].values[dive]
    end = sg271["gc_end_secs"].values[dive]
    cycle_two_end = end[np.isfinite(vbd)][
        np.flatnonzero(vbd[np.isfinite(vbd)] == 0)[0] + 1
    ]
    end_coast = time[state == 9][0]
    climb = (time > cycle_two_end) & (time < end_coast)
    assert climb.sum() > 1000
    assert (phase[climb] == _phase.ASCENT).all()
    begin_dive, begin_apogee = time[state == 0][0], time[state == 4][0]
    descent = (time >= begin_dive) & (time < begin_apogee)
    assert (phase[descent] == _phase.DESCENT).all()


def test_states_written_at_the_same_second_keep_file_order(sg271):
    """End apogee and begin climb at one time: the climb still follows the apogee."""
    ds = sg271.copy(deep=True)
    dive = ds["DIVE_NUMBER"].values == 2
    state = ds["gc_state_state"].values
    time = ds["TIME"].values.copy()
    end_apogee = np.flatnonzero(dive & (state == 5))[0]
    begin_climb = np.flatnonzero(dive & (state == 2))[0]
    time[begin_climb] = time[end_apogee]
    ds = ds.assign_coords(TIME=("N_MEASUREMENTS", time))
    phase, _, _ = _phase.assign(ds)
    np.testing.assert_array_equal(phase[dive], sg271["PHASE"].values[dive])


def test_without_gc_events_pressure_decides(sg005):
    """sg005 with its G&C events removed: no inflexion, PHASE_QC 8 on CTD rows."""
    ds = sg005.drop_vars("gc_vbd_ctl")
    phase, qc, methods = _phase.assign(ds)
    assert methods["pressure"] and not methods["events"]
    assert _phase.INFLEXION not in phase
    gps = np.isin(
        ds["TIME"].values, ds["TIME_GPS"].values[~np.isnat(ds["TIME_GPS"].values)]
    )
    assert set(np.unique(qc[~gps])) == {_phase.QC_PRESSURE}
    assert (phase[gps] == _phase.SURFACING).all()


def test_unknown_state_code_is_phase_0_with_a_warning(sg271, caplog):
    """A state code with no meaning here leaves its rows 0 (QC 9) and names the code."""
    ds = sg271.copy()
    state = ds["gc_state_state"].values.copy()
    state[state == 2] = 42
    ds["gc_state_state"] = ("N_MEASUREMENTS", state)
    with caplog.at_level("WARNING", logger="seagliderOG1._phase"):
        phase, qc, _ = _phase.assign(ds)
    assert (phase == _phase.UNKNOWN).any()
    assert (qc[phase == _phase.UNKNOWN] == _phase.QC_MISSING).all()
    assert any("[42]" in r.message for r in caplog.records)


def test_add_phase_keeps_its_public_shape(sg271):
    """tools.add_phase on an OG1 dataset rewrites PHASE and PHASE_QC in place."""
    ds = tools.add_phase(sg271.drop_vars(["PHASE", "PHASE_QC"]))
    np.testing.assert_array_equal(ds["PHASE"].values, sg271["PHASE"].values)
    with pytest.raises(ValueError, match="dive number"):
        tools.add_phase(sg271.drop_vars("DIVE_NUMBER"))


def test_state_codes_in_the_samples_are_all_known(sg271):
    """Every state code sg271 writes has a meaning in GC_STATE_CODES."""
    codes = sg271["gc_state_state"].values
    assert set(codes[np.isfinite(codes)].astype(int)) <= set(_phase.GC_STATE_CODES)


def test_elapsed_state_seconds_become_times(tmp_path):
    """gc_state_secs written as seconds from the dive start (basestation 2.10) are shifted."""
    source = tmp_path / "p2710002.nc"
    shutil.copy(SG271 / "p2710002.nc", source)
    with xr.open_dataset(source, decode_times=False) as raw:
        raw = raw.load()
    absolute = raw["gc_state_secs"].values.copy()
    raw["gc_state_secs"] = (
        raw["gc_state_secs"].dims,
        absolute - float(raw.attrs["start_time"]),
        raw["gc_state_secs"].attrs,
    )
    fixed = _pipeline._absolute_state_times(raw)
    np.testing.assert_allclose(fixed["gc_state_secs"].values, absolute)
    # Already absolute: unchanged.
    again = _pipeline._absolute_state_times(fixed)
    np.testing.assert_array_equal(again["gc_state_secs"].values, absolute)


def test_basestation_2_10_dives_convert_with_their_own_dates(dev_data, tmp_path):
    """sg033 and dg042 (basestation 2.10) no longer start in 1970, and run 3 2 5 1 3."""
    for name, file in (("sg033", "p0330001_20100903.nc"), ("dg042", "p0420001.nc")):
        raw = tmp_path / f"raw_{name}"
        raw.mkdir()
        shutil.copy(dev_data / file, raw / file)
        out = _convert._convert_mission(raw, tmp_path / name)
        assert "1970" not in out.name
        with xr.open_dataset(out) as ds:
            assert ds["TIME"].values.min() > np.datetime64("2000-01-01")
            assert _runs(ds["PHASE"].values) == list(ORDER)
