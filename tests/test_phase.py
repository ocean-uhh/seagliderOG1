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
#: One basestation-2.10 dive (sg033, 2010-09-03), public at NCEI.
SG033_BS210 = DATA / "tests" / "data" / "sg033_bs210"

#: The order the Seaglider runs its phases in, per dive file.
ORDER = (3, 7, 2, 5, 7, 1, 3)


def _unmasked(path: pathlib.Path) -> xr.Dataset:
    """Load an OG1 file with PHASE as written (int8; 0 is the _FillValue, unknown)."""
    ds = xr.load_dataset(path)
    ds["PHASE"] = ds["PHASE"].fillna(0).astype("int8")
    return ds


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory) -> xr.Dataset:
    """Return sg271 dives 1-3 (basestation 3.0.6, state table) converted to OG1."""
    out = _convert._convert_mission(SG271, tmp_path_factory.mktemp("sg271_phase"))
    return _unmasked(out)


@pytest.fixture(scope="module")
def sg005(tmp_path_factory: pytest.TempPathFactory) -> xr.Dataset:
    """Return sg005 dives 1-5 (basestation 2.8, G&C events, no state table) as OG1."""
    out = _convert._convert_mission(SG005, tmp_path_factory.mktemp("sg005_phase"))
    return _unmasked(out)


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
def test_every_dive_runs_surface_transition_descent_inflection_ascent_surface(
    mission, request
):
    """Per dive the phases follow 3 7 2 5 (7) 1 3 (sg271 dive 1 stops at the apogee)."""
    ds = request.getfixturevalue(mission)
    dive = ds["DIVE_NUMBER"].values
    for number in np.unique(dive):
        runs = _runs(ds["PHASE"].values[dive == number])
        assert _is_in_order(runs), (number, runs)
        assert 0 not in runs


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_one_inflection_run_at_the_bottom_of_the_dive(mission, request):
    """Each dive has one inflection run; the deepest sample is in it or in the G&C event
    that follows (the glider can still sink while it pumps to climb)."""
    ds = request.getfixturevalue(mission)
    dive = ds["DIVE_NUMBER"].values
    for number in np.unique(dive):
        rows = dive == number
        phase = ds["PHASE"].values[rows]
        assert _runs(phase).count(_phase.INFLECTION) == 1
        time = ds["TIME"].values[rows]
        deepest = time[np.nanargmax(ds["PRES"].values[rows])]
        apogee_end = time[phase == _phase.INFLECTION].max()
        vbd = ds["gc_vbd_ctl"].values[rows]
        starts = time[np.isfinite(vbd)]
        ends = ds["gc_end_secs"].values[rows][np.isfinite(vbd)]
        after = ends[starts > apogee_end]
        limit = after.min() if after.size else apogee_end
        assert time[phase == _phase.INFLECTION].min() <= deepest <= limit


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_gps_fixes_are_surfacing(mission, request):
    """Every row at a GPS fix time is 3; no CTD sample deeper than 5 dbar is 3 (surfacing
    starts at the surface coast, above $D_SURF)."""
    ds = request.getfixturevalue(mission)
    fixes = ds["TIME_GPS"].values[~np.isnat(ds["TIME_GPS"].values)]
    at_fix = np.isin(ds["TIME"].values, fixes)
    assert at_fix.sum() >= 3 * np.unique(ds["DIVE_NUMBER"].values).size
    assert (ds["PHASE"].values[at_fix] == _phase.SURFACING).all()
    deep = ds["PRES"].values > 5
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


def test_attributes_follow_og1_and_qc_is_zero(sg271, sg005, tmp_path):
    """PHASE carries the vocabulary and the method; PHASE_QC is 0 (no QC applied)."""
    attrs = sg271["PHASE"].attrs
    assert attrs["phase_vocabulary"].endswith("vocabularyCollection/phase.md")
    assert attrs["flag_meanings"].split() == list(_phase.PHASE_NAMES.values())
    assert list(attrs["flag_values"]) == list(_phase.PHASE_NAMES)
    assert attrs["ancillary_variables"] == "PHASE_QC"
    assert "state table" in attrs["phase_calculation_method"]
    assert "dives 1-3" in attrs["phase_calculation_method"]
    assert "D_FLARE" in attrs["phase_calculation_method"]
    assert attrs["phase_calculation_method_vocabulary"] == ""
    assert "guidance-and-control" in sg005["PHASE"].attrs["phase_calculation_method"]
    for ds in (sg271, sg005):
        assert set(np.unique(ds["PHASE_QC"].values)) == {0}
        assert ds["PHASE_QC"].attrs["flag_meanings"].split()[0] == "no_qc_performed"


def test_phase_is_written_as_byte_with_fill_value_0(tmp_path):
    """On disk PHASE is int8 with _FillValue 0, as the OG1 format lists it."""
    import netCDF4

    out = _convert._convert_mission(SG271, tmp_path, dives=(2, 2))
    with netCDF4.Dataset(out) as nc:
        assert nc["PHASE"].dtype == np.int8
        assert nc["PHASE"].getncattr("_FillValue") == 0
        assert nc["PHASE_QC"].dtype == np.int8


def test_inflection_is_the_state_tables_apogee(sg271):
    """sg271 dive 2: inflection exactly from begin apogee to begin climb."""
    dive = sg271["DIVE_NUMBER"].values == 2
    time = sg271["TIME"].values[dive]
    phase = sg271["PHASE"].values[dive]
    state = sg271["gc_state_state"].values[dive]
    begin_apogee = time[state == 4][0]
    begin_climb = time[state == 2][0]
    window = (time >= begin_apogee) & (time < begin_climb)
    assert (phase[window] == _phase.INFLECTION).all()
    assert (phase[~window] != _phase.INFLECTION).all()


def test_climb_is_transition_to_the_deepest_sample_then_ascent(sg271):
    """sg271 dive 2: from begin climb to the deepest sample is transition, then ascent to
    the start of the surface coast; from begin dive to begin apogee, transition then
    descent."""
    dive = sg271["DIVE_NUMBER"].values == 2
    time = sg271["TIME"].values[dive]
    phase = sg271["PHASE"].values[dive]
    state = sg271["gc_state_state"].values[dive]
    pres = sg271["PRES"].values[dive]
    deepest = time[np.nanargmax(pres)]
    begin_climb = time[state == 2][0]
    assert deepest > begin_climb  # the glider sinks on after the apogee ends
    bottom = (time >= begin_climb) & (time <= deepest)
    assert (phase[bottom] == _phase.TRANSITION).all()
    climb = (time > deepest) & (time < time[state == 8][0])
    assert climb.sum() > 1000
    assert (phase[climb] == _phase.ASCENT).all()
    descent = (time >= time[state == 0][0]) & (time < time[state == 4][0])
    assert set(phase[descent].tolist()) == {_phase.TRANSITION, _phase.DESCENT}
    first_descent = time[descent & (phase == _phase.DESCENT)].min()
    assert (phase[descent & (time >= first_descent)] == _phase.DESCENT).all()


def test_g_and_c_apogee_matches_the_state_table(sg271):
    """With the state table removed, sg271 falls back to its G&C events and gives the same
    PHASE to within a row or two at each boundary (the apogee event spans the two states)."""
    phase, methods = _phase.assign(sg271.drop_vars("gc_state_state"))
    assert methods["events"] == [1, 2, 3]
    # The G&C events cannot see the surface coast (surfacing from the state table, ascent
    # from the events); leave those rows out.
    state_phase = sg271["PHASE"].values
    gps = np.isin(
        sg271["TIME"].values,
        sg271["TIME_GPS"].values[~np.isnat(sg271["TIME_GPS"].values)],
    )
    coast = (state_phase == _phase.SURFACING) & ~gps & (phase == _phase.ASCENT)
    differ = (phase != state_phase) & ~coast
    assert differ.sum() < 0.01 * phase.size


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
    phase, _ = _phase.assign(ds)
    # Only the end-apogee row, now at the begin-climb time, changes (5 -> 7: the climb's
    # start, before the deepest sample, is transition).
    same = dive & (np.arange(dive.size) != end_apogee)
    np.testing.assert_array_equal(phase[same], sg271["PHASE"].values[same])
    assert phase[end_apogee] == _phase.TRANSITION


@pytest.mark.parametrize("mission", ["sg271", "sg005"])
def test_transition_ends_at_the_last_sample_above_d_flare(mission, request):
    """Each dive's transition ends at its last sample shallower than log_D_FLARE before
    the apogee; the next pressure sample is deeper and descent."""
    ds = request.getfixturevalue(mission)
    d_flare = float(ds["log_D_FLARE"].values)
    for number in np.unique(ds["DIVE_NUMBER"].values):
        rows = np.flatnonzero(ds["DIVE_NUMBER"].values == number)
        phase = ds["PHASE"].values[rows]
        time = ds["TIME"].values[rows]
        depth = ds["DEPTH"].values[rows]
        apogee = time[phase == _phase.INFLECTION].min()
        above = (time < apogee) & (depth < d_flare) & ~(phase == _phase.SURFACING)
        last_above = time[above].max()
        start_of_dive = (phase == _phase.TRANSITION) & (time < apogee)
        assert time[start_of_dive].max() == last_above
        after = (time > last_above) & np.isfinite(depth)
        assert phase[after][0] == _phase.DESCENT
        assert depth[after][0] >= d_flare


def test_sg537_transition_runs_to_the_last_rise_above_d_flare(dev_data, tmp_path):
    """sg537 dive 1 sinks past D_FLARE and comes back above it before diving: the
    transition runs to the last sample above D_FLARE, past the first dip."""
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(dev_data / "p5370001.nc", raw / "p5370001.nc")
    ds = _unmasked(_convert._convert_mission(raw, tmp_path / "out"))
    d_flare = float(ds["log_D_FLARE"].values)
    phase, depth = ds["PHASE"].values, ds["DEPTH"].values
    transition = phase == _phase.TRANSITION
    before = ds["TIME"].values < ds["TIME"].values[phase == _phase.INFLECTION].min()
    assert (depth[transition & before] >= d_flare).any()  # the dip is in the transition
    apogee = ds["TIME"].values[phase == _phase.INFLECTION].min()
    end = ds["TIME"].values[transition & (ds["TIME"].values < apogee)].max()
    later = (ds["TIME"].values > end) & np.isfinite(depth) & (phase != _phase.SURFACING)
    assert depth[later][0] >= d_flare


def test_one_bad_shallow_depth_mid_descent_does_not_move_the_flare(sg271):
    """A single 0 m DEPTH reading mid-descent leaves the transition where it was."""
    ds = sg271.copy(deep=True)
    dive = ds["DIVE_NUMBER"].values == 2
    rows = np.flatnonzero(dive & (ds["PHASE"].values == _phase.DESCENT))
    glitch = rows[np.isfinite(ds["DEPTH"].values[rows])][200]
    assert ds["DEPTH"].values[glitch] > 20
    depth = ds["DEPTH"].values.copy()
    depth[glitch] = 0.0
    ds["DEPTH"] = ("N_MEASUREMENTS", depth)
    phase, _ = _phase.assign(ds)
    np.testing.assert_array_equal(phase[dive], sg271["PHASE"].values[dive])


def test_without_depth_pressure_places_the_flare(sg271):
    """Without DEPTH the flare is read against PRES, to within a row of the DEPTH result."""
    phase, methods = _phase.assign(sg271.drop_vars("DEPTH"))
    assert methods["flare"] == [1, 2, 3]
    assert (phase != sg271["PHASE"].values).sum() <= 3


def test_command_reads_a_per_dive_json_record(sg271):
    """log_D_TGT changes between dives, so it is written as JSON; each dive gets its own."""
    raw = str(np.asarray(sg271["log_D_TGT"].values).item())
    assert raw.startswith("{")
    assert _phase.command(sg271, "log_D_TGT", 1) == 45.0
    assert _phase.command(sg271, "log_D_TGT", 3) == 100.0
    assert _phase.command(sg271, "log_D_TGT", 9) is None
    assert _phase.command(sg271, "log_NOT_THERE", 1) is None
    assert _phase.command(sg271, "log_D_FLARE", 2) == 3.0


def test_without_gc_events_pressure_decides(sg005):
    """sg005 with its G&C events removed: no inflection, the method says pressure."""
    ds = sg005.drop_vars("gc_vbd_ctl")
    phase, methods = _phase.assign(ds)
    assert methods["pressure"] and not methods["events"]
    assert _phase.INFLECTION not in phase
    assert "pressure alone" in _phase.method_text(methods)
    gps = np.isin(
        ds["TIME"].values, ds["TIME_GPS"].values[~np.isnat(ds["TIME_GPS"].values)]
    )
    assert (phase[gps] == _phase.SURFACING).all()


def test_unknown_state_code_is_phase_0_with_a_warning(sg271, caplog):
    """A state code with no meaning here leaves its rows 0 and names the code."""
    ds = sg271.copy()
    state = ds["gc_state_state"].values.copy()
    state[state == 2] = 42
    ds["gc_state_state"] = ("N_MEASUREMENTS", state)
    with caplog.at_level("WARNING", logger="seagliderOG1._phase"):
        phase, _ = _phase.assign(ds)
    assert (phase == _phase.UNKNOWN).any()
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


def test_basestation_2_10_dive_converts_with_its_own_date(tmp_path):
    """sg033 2010-09-03 (basestation 2.10, public at NCEI): gc_state_secs are seconds from
    the dive start; the file no longer starts in 1970, and the state table assigns PHASE."""
    out = _convert._convert_mission(SG033_BS210, tmp_path)
    assert "1970" not in out.name
    ds = _unmasked(out)
    assert ds["TIME"].values.min() > np.datetime64("2010-01-01")
    runs = _runs(ds["PHASE"].values)
    assert _is_in_order(runs)
    assert {2, 3, 5, 1, 7} <= set(runs)
    assert "state table" in ds["PHASE"].attrs["phase_calculation_method"]


def test_dg042_converts_with_its_own_date(dev_data, tmp_path):
    """dg042 (basestation 2.10, dev pack) no longer starts in 1970."""
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(dev_data / "p0420001.nc", raw / "p0420001.nc")
    out = _convert._convert_mission(raw, tmp_path / "out")
    assert "1970" not in out.name


def test_pick_dives_takes_one_near_the_start_middle_and_end():
    """Dive 2 first; one from the middle third and one from the last third; stable."""
    import xarray as xr

    from seagliderOG1.reports import phase as page

    ds = xr.Dataset({"DIVE_NUMBER": ("N_MEASUREMENTS", np.repeat(np.arange(1, 31), 4))})
    dives = page.pick_dives(ds)
    assert dives[0] == 2
    assert 11 <= dives[1] <= 20
    assert 21 <= dives[2] <= 30
    assert page.pick_dives(ds) == dives
