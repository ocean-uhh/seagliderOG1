"""Tests for the writers module: lossless compression of OG1 output."""

import pathlib
import sys

import netCDF4
import numpy as np
import xarray as xr

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import writers  # noqa: E402  # import needs the path set above

SAMPLE = parent_dir / "data" / "demo_single_test.nc"

# Named expectations on the real fixture, so the test does not just restate the
# implementation's own predicate.
COMPRESSED_VARS = ["TEMP", "DEPTH", "LATITUDE", "LONGITUDE", "PSAL", "PROFILE_NUMBER"]
STRING_VAR = "TEMP_QC"
SCALAR_VAR = "PLATFORM_SERIAL_NUMBER"


def _load_sample() -> xr.Dataset:
    """Load a real OG1 output file as a writer fixture."""
    return xr.open_dataset(SAMPLE, engine="netcdf4")


def test_compression_applied(tmp_path: pathlib.Path) -> None:
    """Named numeric variables are written with zlib and shuffle on."""
    ds = _load_sample()
    out = tmp_path / "out.nc"

    assert writers.save_dataset(ds, str(out)) is True

    with netCDF4.Dataset(out) as nc:
        for name in COMPRESSED_VARS:
            filt = nc.variables[name].filters()
            assert filt["zlib"] is True, f"{name} not zlib-compressed"
            assert filt["shuffle"] is True, f"{name} missing shuffle"
            assert filt["complevel"] == 4, f"{name} wrong complevel"


def test_roundtrip_lossless(tmp_path: pathlib.Path) -> None:
    """Named numeric values are bit-identical after a compressed write/read."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.save_dataset(ds, str(out))

    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        for name in COMPRESSED_VARS:
            np.testing.assert_array_equal(
                reloaded[name].values,
                ds[name].values,
                err_msg=f"{name} changed through compression",
            )


def test_string_and_scalar_left_uncompressed(tmp_path: pathlib.Path) -> None:
    """A string variable and a scalar variable carry no zlib filter."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.save_dataset(ds, str(out))

    with netCDF4.Dataset(out) as nc:
        assert nc.variables[STRING_VAR].filters()["zlib"] is False
        assert nc.variables[SCALAR_VAR].filters()["zlib"] is False


def test_time_encoding_preserved(tmp_path: pathlib.Path) -> None:
    """Datetime variables survive the compressed write and decode back to datetime."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.save_dataset(ds, str(out))

    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        assert np.issubdtype(reloaded["TIME"].dtype, np.datetime64)
        np.testing.assert_array_equal(reloaded["TIME"].values, ds["TIME"].values)


def test_smaller_than_uncompressed(tmp_path: pathlib.Path) -> None:
    """A compressed write is smaller than a plain NETCDF4 write of the same data."""
    ds = _load_sample()
    compressed = tmp_path / "compressed.nc"
    plain = tmp_path / "plain.nc"

    writers.save_dataset(ds, str(compressed))
    ds.to_netcdf(plain, format="NETCDF4", engine="netcdf4")

    assert compressed.stat().st_size < plain.stat().st_size


def test_retry_path_stays_compressed(tmp_path: pathlib.Path) -> None:
    """A bad variable attribute forces the retry path, which still compresses."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    ds["TEMP"].attrs["bad_attr"] = {"not": "serialisable"}

    assert writers.save_dataset(ds, str(out)) is True

    with netCDF4.Dataset(out) as nc:
        assert nc.variables["TEMP"].filters()["zlib"] is True


def test_input_dataset_not_mutated(tmp_path: pathlib.Path) -> None:
    """save_dataset writes correct time encoding without mutating the caller's dataset."""
    times = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]")
    ds = xr.Dataset({"x": ("time", np.arange(3.0))}, coords={"time": ("time", times)})
    ds["time"].attrs["units"] = "days since 2000-01-01"
    ds["time"].attrs["calendar"] = "standard"
    out = tmp_path / "out.nc"

    assert writers.save_dataset(ds, str(out)) is True

    # the caller's dataset is untouched
    assert ds["time"].attrs["units"] == "days since 2000-01-01"
    assert ds["time"].attrs["calendar"] == "standard"

    # the file decodes to the correct times
    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        assert np.issubdtype(reloaded["time"].dtype, np.datetime64)
        np.testing.assert_array_equal(reloaded["time"].values, times)


def test_returns_false_when_unwriteable(tmp_path: pathlib.Path) -> None:
    """A bad global attribute the retry cannot fix makes save_dataset return False."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    # the retry only stringifies variable attrs, so a bad global attr survives both writes
    ds.attrs["bad_global"] = {"not": "serialisable"}

    assert writers.save_dataset(ds, str(out)) is False
