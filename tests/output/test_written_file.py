"""The written OG1 file: one dive end to end, compression, lossless round trip, time
encoding, and enrich (changing globals of a written file).

Data: the sg005 demo and data/demo_single_test.nc.
"""

import json
import pathlib

import netCDF4
import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, _pipeline, readers, tools, writers

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]
SAMPLE = parent_dir / "data" / "demo_single_test.nc"
# Named expectations on the real fixture, so the test does not just restate the
# implementation's own predicate.
COMPRESSED_VARS = ["TEMP", "DEPTH", "LATITUDE", "LONGITUDE", "PSAL", "PROFILE_NUMBER"]
STRING_VAR = "TEMP_QC"
SCALAR_VAR = "PLATFORM_SERIAL_NUMBER"


def _load_sample() -> xr.Dataset:
    """Load a real OG1 output file as a writer fixture."""
    return xr.open_dataset(SAMPLE, engine="netcdf4")


# --- One dive end to end ------------------------------------------------------------------


def test_process_dataset():

    ds1 = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)[0]

    # test split_ds
    split_ds = tools.split_by_unique_dims(ds1)

    key_dims = list(split_ds.keys())
    key_dims.sort()
    assert key_dims == [(), ("gc_event",), ("gps_info",), ("sg_data_point",)]

    gps_info = split_ds[("gps_info",)]

    sg_cal, dc_log, dc_other = _convert.extract_variables(split_ds[()])
    tmp = dc_log.log_GPS.values.tobytes().decode("utf-8")

    assert sg_cal["mass"].values > 50 and sg_cal["mass"].values < 60
    assert tmp == "$GPS,060608,183207,6124.849,-816.741,13,1.8,12,-8.8"

    ctd_dim, merge_dims, all_dims = _pipeline._get_merge_dimensions([ds1])

    # create og1_mapping for apply_og1_vocabulary
    og1_mapping, time_variables = _pipeline.og1_name_mapping([ds1])

    merged_ds = _pipeline.merge_datasets_along_time(split_ds, time_variables)

    # Check initial variables are reformatted
    dsa = _convert.apply_og1_vocabulary(merged_ds, og1_mapping=og1_mapping)
    varlist = list(dsa.data_vars)
    coordlist = list(dsa.coords)
    combined_list = varlist + coordlist
    combined_list.sort()
    og1_varlist = [
        "TIME",
        "LATITUDE",
        "LONGITUDE",
        "TEMP",
        "DEPTH",
    ]
    for var in og1_varlist:
        assert var in combined_list

    ds_new = _convert.add_gps_info_to_dataset(dsa, gps_info)
    assert "LATITUDE_GPS" in list(ds_new.variables)
    assert "LONGITUDE_GPS" in list(ds_new.variables)

    ds_new = tools.add_dive_number(ds_new, ds1.attrs["dive_number"])
    assert (ds_new["dive_number"].values == ds1.attrs["dive_number"]).all()

    ds_new = tools.add_depth(ds_new)
    meanZ = ds_new["DEPTH_Z"].mean().item()
    meanZpos = ds_new["DEPTH"].mean().item()
    assert abs(meanZ + meanZpos) < 10


# --- Writing ------------------------------------------------------------------------------


def test_roundtrip_lossless(tmp_path: pathlib.Path) -> None:
    """Named numeric values are bit-identical after a compressed write/read."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.write(ds, str(out))

    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        for name in COMPRESSED_VARS:
            np.testing.assert_array_equal(
                reloaded[name].values,
                ds[name].values,
                err_msg=f"{name} changed through compression",
            )


def test_compression_applied(tmp_path: pathlib.Path) -> None:
    """Named numeric variables are written with zlib and shuffle on."""
    ds = _load_sample()
    out = tmp_path / "out.nc"

    assert writers.write(ds, str(out)) == out

    with netCDF4.Dataset(out) as nc:
        for name in COMPRESSED_VARS:
            filt = nc.variables[name].filters()
            assert filt["zlib"] is True, f"{name} not zlib-compressed"
            assert filt["shuffle"] is True, f"{name} missing shuffle"
            assert filt["complevel"] == 4, f"{name} wrong complevel"


def test_string_and_scalar_left_uncompressed(tmp_path: pathlib.Path) -> None:
    """A string variable and a scalar variable carry no zlib filter."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.write(ds, str(out))

    with netCDF4.Dataset(out) as nc:
        assert nc.variables[STRING_VAR].filters()["zlib"] is False
        assert nc.variables[SCALAR_VAR].filters()["zlib"] is False


def test_smaller_than_uncompressed(tmp_path: pathlib.Path) -> None:
    """A compressed write is smaller than a plain NETCDF4 write of the same data."""
    ds = _load_sample()
    compressed = tmp_path / "compressed.nc"
    plain = tmp_path / "plain.nc"

    writers.write(ds, str(compressed))
    ds.to_netcdf(plain, format="NETCDF4", engine="netcdf4")

    assert compressed.stat().st_size < plain.stat().st_size


def test_time_encoding_preserved(tmp_path: pathlib.Path) -> None:
    """Datetime variables survive the compressed write and decode back to datetime."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    writers.write(ds, str(out))

    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        assert np.issubdtype(reloaded["TIME"].dtype, np.datetime64)
        np.testing.assert_array_equal(reloaded["TIME"].values, ds["TIME"].values)


def test_time_units_canonical(tmp_path: pathlib.Path) -> None:
    """Written time variables use the canonical OG1 units and calendar, not the old form.

    The writer no longer applies its own divergent units string; it uses the single
    source in tools, so a saved file matches encode_times_og1 (ISO UTC, gregorian).
    """
    times = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]")
    ds = xr.Dataset({"x": ("time", np.arange(3.0))}, coords={"time": ("time", times)})
    out = tmp_path / "out.nc"
    writers.write(ds, str(out))

    assert tools.OG1_TIME_UNITS == "seconds since 1970-01-01T00:00:00Z"
    with netCDF4.Dataset(out) as nc:
        v = nc.variables["time"]
        # xarray normalises the trailing Z to +00:00; both are ISO UTC. The old writer
        # emitted "seconds since 1970-01-01 00:00:00" (space, no zone) with calendar
        # "standard" -- assert the ISO form and gregorian instead.
        assert "1970-01-01T00:00:00" in v.getncattr("units")
        assert v.getncattr("calendar") == "gregorian"
        assert v.dtype == np.dtype("float64")


def test_preserves_integer_fill_value(tmp_path: pathlib.Path) -> None:
    """A compressed integer variable keeps its _FillValue sentinel on disk.

    No real OG1 fixture carries an integer variable with a fill sentinel yet; that
    arrives with the dtype work (QC as int8, PROFILE_NUMBER as int16). This
    synthetic case guards the writer against dropping the sentinel when it does.
    """
    ds = xr.Dataset({"q": ("n", np.array([1, 2, -999, 4], dtype="int16"))})
    ds["q"].encoding["_FillValue"] = np.int16(-999)
    out = tmp_path / "out.nc"

    assert writers.write(ds, str(out)) == out

    with netCDF4.Dataset(out) as nc:
        assert "_FillValue" in nc.variables["q"].ncattrs()
        assert nc.variables["q"].getncattr("_FillValue") == -999
        assert nc.variables["q"].filters()["zlib"] is True


def test_input_dataset_not_mutated(tmp_path: pathlib.Path) -> None:
    """write writes correct time encoding without mutating the caller's dataset."""
    times = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ns]")
    ds = xr.Dataset({"x": ("time", np.arange(3.0))}, coords={"time": ("time", times)})
    ds["time"].attrs["units"] = "days since 2000-01-01"
    ds["time"].attrs["calendar"] = "standard"
    out = tmp_path / "out.nc"

    assert writers.write(ds, str(out)) == out

    # the caller's dataset is untouched
    assert ds["time"].attrs["units"] == "days since 2000-01-01"
    assert ds["time"].attrs["calendar"] == "standard"

    # the file decodes to the correct times
    with xr.open_dataset(out, engine="netcdf4") as reloaded:
        assert np.issubdtype(reloaded["time"].dtype, np.datetime64)
        np.testing.assert_array_equal(reloaded["time"].values, times)


def test_unwritable_attribute_is_refused_by_name(tmp_path: pathlib.Path) -> None:
    """A variable attribute netCDF cannot store is named, not stringified; nothing is lost."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    out.write_text("previous version")
    ds["TEMP"].attrs["bad_attr"] = {"not": "serialisable"}
    ds["TEMP"].attrs["flag"] = True

    with pytest.raises(TypeError, match=r"TEMP:bad_attr \(dict\).*TEMP:flag \(bool\)"):
        writers.write(ds, str(out), overwrite=True)
    # Refused before the existing file is removed.
    assert out.read_text(encoding="utf-8") == "previous version"
    # Containers are checked by element, and a 2-D array (netCDF attrs are scalar or 1-D) is
    # refused before the write rather than failing mid-to_netcdf after the file is removed.
    for value in (
        [True, False],
        np.array([True]),
        ["a", None],
        [{"a": 1}],
        np.zeros((2, 2)),
    ):
        bad = _load_sample()
        bad["TEMP"].attrs["nested"] = value
        with pytest.raises(TypeError, match="TEMP:nested"):
            writers.write(bad, str(out), overwrite=True)
        assert out.read_text(encoding="utf-8") == "previous version"


def test_write_rejects_none_attribute(tmp_path: pathlib.Path) -> None:
    """A None-valued attribute is refused by name, not written as the literal 'None'."""
    ds = xr.Dataset({"x": ("n", [1.0, 2.0])}, attrs={"contributor_name": None})
    try:
        writers.write(ds, str(tmp_path / "out.nc"))
    except ValueError as exc:
        assert "contributor_name" in str(exc)
    else:
        raise AssertionError("expected ValueError for a None attribute")


def test_raises_when_unwriteable(tmp_path: pathlib.Path) -> None:
    """A bad global attribute is refused by name and no file is written."""
    ds = _load_sample()
    out = tmp_path / "out.nc"
    ds.attrs["bad_global"] = {"not": "serialisable"}

    with pytest.raises(TypeError, match=r"global:bad_global \(dict\)"):
        writers.write(ds, str(out))
    assert not out.exists()


# --- Enrich -------------------------------------------------------------------------------


def test_enrich_checks_every_value_before_writing(
    tmp_path: pathlib.Path, sg005_og1_copy: pathlib.Path
) -> None:
    """A refused value or a changed id leaves the file byte-for-byte as it was."""
    path = sg005_og1_copy
    digest = writers.file_sha256(path)
    with pytest.raises(ValueError, match="list cannot be a global attribute"):
        writers.enrich(
            path, doi="10.5281/zenodo.1", global_attributes={"keywords": ["a", "b"]}
        )
    with pytest.raises(ValueError, match="true/false"):
        writers.enrich(path, global_attributes={"flag": True})
    with pytest.raises(ValueError, match="differs from the file's id"):
        writers.enrich(path, deployment={"id": "sg005_other"})
    assert writers.file_sha256(path) == digest


def test_enrich_warns_on_a_replaced_value_and_records_it(
    tmp_path: pathlib.Path,
    sg005_og1_copy: pathlib.Path,
) -> None:
    """Replacing a value warns with both; a date becomes ISO text; the ledger says so."""
    import datetime as dt

    path = sg005_og1_copy
    writers.enrich(path, global_attributes={"program": "MOOSE"})  # new key: no warning
    with pytest.warns(UserWarning, match="enrich replaces program: 'MOOSE' -> 'OSNAP'"):
        writers.enrich(
            path,
            global_attributes={
                "program": "OSNAP",
                "date_issued": dt.date(2026, 10, 19),
            },
        )
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        assert ds.attrs["program"] == "OSNAP"
        assert ds.attrs["date_issued"] == "2026-10-19"
        ledger = json.loads(ds.attrs["conversion_attribute_sources"])
        named = [name for names in ledger.values() for name in names]
        assert sorted(named) == sorted(set(ds.attrs) - {"conversion_attribute_sources"})
    assert ledger["enriched"] == ["date_issued", "program"]
    assert {"date_modified", "tracking_id"} <= set(ledger["derived"])
