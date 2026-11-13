"""GPS fixes on the time axis: one data point per fix, fix values from the raw log, and
repeated or shifted fixes.

Data: the sg005 demo; the repeated and shifted fixes need the dev pack
(SEAGLIDEROG1_DEV_DATA) and skip without it.
"""

import pathlib
import shutil

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, _phase, readers

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]


def _sg004_dir(dev_data, tmp_path, *, shift_lon=False):
    """Copy the dev-pack p0040001 (sg004 dive 1) into a one-file folder.

    p0040001 logs its last fix twice at the same second. With ``shift_lon`` the second copy's
    longitude is moved 0.001 deg, so the two fixes differ and the merge must shift the copy
    +0.5 s instead of dropping it. Skips when the file is not in the dev pack.
    """
    src = next(dev_data.glob("p0040001*.nc"), None)
    if src is None:
        pytest.skip("p0040001 not in the dev pack")
    folder = tmp_path / "sg004"
    folder.mkdir()
    if not shift_lon:
        shutil.copy2(src, folder / src.name)
        return folder
    raw = xr.open_dataset(src, decode_times=False, engine="netcdf4")
    times = np.asarray(raw["log_gps_time"].values, dtype="float64")
    values, counts = np.unique(times, return_counts=True)
    repeated = values[counts > 1]
    if repeated.size == 0:
        pytest.skip("p0040001 has no repeated fix time")
    where = np.flatnonzero(times == repeated[0])
    lon = np.asarray(raw["log_gps_lon"].values, dtype="float64").copy()
    lon[where[1]] += 0.001
    raw = raw.assign(
        log_gps_lon=(raw["log_gps_lon"].dims, lon, raw["log_gps_lon"].attrs)
    )
    raw.to_netcdf(folder / src.name, engine="netcdf4")
    return folder


# --- One data point per fix ---------------------------------------------------------------


def test_gps_fix_is_one_data_point_lossless():
    """Each GPS fix is one data point: the OG1 *_GPS variables and the surface position/depth
    sit on the merged gps_info data point, not an appended copy.

    Before the collapse a fix made two data points at the same TIME: a gps_info one carrying
    log_gps_* and an appended one carrying *_GPS. Now they are one, so the (lat & lon)-finite
    data points and the TIME_GPS-finite data points are the same set, and no field is lost.
    Checked over the whole mission (5 dives). TIME must not decrease, but it may still tie at a
    cross-dive boundary fix (the same fix shared by two adjacent dives) -- a separate matter --
    so this does not assert the fixes are tie-free.
    """
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 5)
    ds = _convert.convert(datasets)

    # Engineering fields are kept.
    assert "log_gps_lat" in ds.variables
    assert "log_gps_lon" in ds.variables

    # A fix is a data point with latitude AND longitude finite.
    mask = np.isfinite(ds["log_gps_lat"].values) & np.isfinite(ds["log_gps_lon"].values)
    time_gps_finite = ~np.isnat(ds["TIME_GPS"].values)
    assert mask.any()
    # The collapse invariant: a fix and its OG1 GPS variables are on the SAME data points
    # (disjoint before the collapse, which appended a second copy per fix).
    assert np.array_equal(mask, time_gps_finite)

    # The fix's surface position and depth are filled from the fix.
    assert np.allclose(ds["LATITUDE"].values[mask], ds["log_gps_lat"].values[mask])
    assert np.allclose(ds["LONGITUDE"].values[mask], ds["log_gps_lon"].values[mask])
    assert np.all(ds["DEPTH"].values[mask] == 0)
    # The OG1 GPS variables carry the fix.
    assert np.allclose(ds["LATITUDE_GPS"].values[mask], ds["log_gps_lat"].values[mask])
    assert np.allclose(ds["LONGITUDE_GPS"].values[mask], ds["log_gps_lon"].values[mask])
    # TIME_GPS is the raw fix clock. demo_sg005 has no within-dive duplicate fix time, so no
    # +0.5 s merge shift fires and it equals the data point's TIME; on a file with a repeated
    # fix time, TIME_GPS would read the raw (earlier) time, 0.5 s before TIME.
    assert np.array_equal(ds["TIME_GPS"].values[mask], ds["TIME"].values[mask])

    # TIME never decreases, and no duplicate timestamp sits at a GPS fix: source 1 (append)
    # removed, source 2 (within-dive repeat) dropped in the merge, source 3 (cross-dive
    # boundary) deduplicated at the concat.
    t = ds["TIME"].values.astype("datetime64[ns]").astype("int64")
    assert np.all(np.diff(t) >= 0)
    ties = np.flatnonzero(np.diff(t) == 0)
    assert not any(time_gps_finite[i] or time_gps_finite[i + 1] for i in ties)


# --- Repeated and shifted fixes (dev pack) ------------------------------------------------


def test_exact_repeat_gps_fix_is_one_data_point(dev_data, tmp_path):
    """An exact-repeat fix (p0040001's last fix, logged twice at one second) is dropped in the
    merge, not shifted: one data point per recorded second, no invented +0.5 s, TIME_GPS==TIME.
    """
    folder = _sg004_dir(dev_data, tmp_path)
    ds = _convert.convert(
        readers.read_mission(str(folder), 1, 1),
        platform={"PLATFORM_SERIAL_NUMBER": "sg004"},
    )
    fix = ~np.isnat(ds["TIME_GPS"].values)
    seconds = ds["TIME"].values[fix].astype("datetime64[s]")
    assert fix.sum() == np.unique(seconds).size  # no two fixes share a whole second
    assert (ds["TIME"].values[fix] == ds["TIME_GPS"].values[fix]).all()


def test_shifted_gps_fix_is_still_surfacing(dev_data, tmp_path):
    """A repeated fix that differs in position is shifted +0.5 s (not dropped); TIME_GPS keeps
    the raw time, 0.5 s before TIME, and the shifted fix data point is still PHASE 3. Guards the
    regression where surfacing was matched by TIME==TIME_GPS (which misses a shifted fix).
    """
    folder = _sg004_dir(dev_data, tmp_path, shift_lon=True)
    ds = _convert.convert(
        readers.read_mission(str(folder), 1, 1),
        platform={"PLATFORM_SERIAL_NUMBER": "sg004"},
    )
    fix = ~np.isnat(ds["TIME_GPS"].values)
    shifted = fix & (ds["TIME"].values != ds["TIME_GPS"].values)
    assert shifted.any()
    assert (ds["PHASE"].values[shifted] == _phase.SURFACING).all()
