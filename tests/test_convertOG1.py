import pathlib
import sys

import netCDF4
import numpy as np
import xarray as xr

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import convertOG1, readers, tools, writers


def test_resolve_platform_serial_from_file():
    """Serial comes from platform_id; string fields fall back to UNK; depth omitted."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    resolved = convertOG1._resolve_platform(ds, None)
    assert resolved["PLATFORM_SERIAL_NUMBER"] == "sg005"
    assert resolved["PLATFORM_MODEL"] == "UNK"
    assert resolved["WMO_IDENTIFIER"] == "UNK"
    assert "PLATFORM_DEPTH_RATING" not in resolved  # numeric: omitted, never "UNK"
    assert "platform_model_vocabulary" not in resolved


def test_resolve_platform_config_overrides_and_numeric_depth():
    """Config values override the file; numeric depth and model vocab are written."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {
        "PLATFORM_SERIAL_NUMBER": "orca",
        "PLATFORM_MODEL": "Slocum G3",
        "PLATFORM_DEPTH_RATING": 1000,
        "platform_model_vocabulary": "http://vocab.example/model",
    }
    resolved = convertOG1._resolve_platform(ds, platform)
    assert resolved["PLATFORM_SERIAL_NUMBER"] == "orca"
    assert resolved["PLATFORM_MODEL"] == "Slocum G3"
    assert resolved["PLATFORM_DEPTH_RATING"] == 1000
    assert resolved["platform_model_vocabulary"] == "http://vocab.example/model"


def test_resolve_platform_missing_serial_raises():
    """No platform_id and no config serial is a hard error (it names the output)."""
    try:
        convertOG1._resolve_platform(xr.Dataset(), None)
    except ValueError as exc:
        assert "PLATFORM_SERIAL_NUMBER" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing serial")


def test_global_attributes_collision_raises():
    """A global_attributes key that collides with a derived global is an error."""
    try:
        convertOG1.convert_to_OG1([], global_attributes={"id": "x"})
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected ValueError for derived-global collision")


def test_process_dataset():

    ds1 = readers.load_sample_dataset()

    # test split_ds
    split_ds = tools.split_by_unique_dims(ds1)

    key_dims = list(split_ds.keys())
    key_dims.sort()
    assert key_dims == [(), ("gc_event",), ("gps_info",), ("sg_data_point",)]

    ds = split_ds[("sg_data_point",)]
    gps_info = split_ds[("gps_info",)]

    sg_cal, dc_log, dc_other = convertOG1.extract_variables(split_ds[()])
    tmp = dc_log.log_GPS.values.tobytes().decode("utf-8")

    assert sg_cal["mass"].values > 50 and sg_cal["mass"].values < 60
    assert tmp == "$GPS,060608,183207,6124.849,-816.741,13,1.8,12,-8.8"

    ctd_dim, merge_dims, all_dims = tools._get_merge_dimensions([ds1])

    # create og1_mapping for standardise_OG10
    OG1_mapping = tools.OG1_name_mapping(
        [ds1], ctd_dim=ctd_dim, dims_to_merge=merge_dims
    )

    # Check initial variables are reformatted
    dsa = convertOG1.standardise_OG10(ds, og1_mapping=OG1_mapping)
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

    ds_new = convertOG1.add_gps_info_to_dataset(dsa, gps_info)
    assert "LATITUDE_GPS" in list(ds_new.variables)
    assert "LONGITUDE_GPS" in list(ds_new.variables)

    ds_new = tools.assign_profile_number(ds_new, ds1)
    assert "PROFILE_NUMBER" in list(ds_new.variables)
    assert ds_new["PROFILE_NUMBER"].values.max() == 2 * ds1.attrs["dive_number"]

    ds_new = tools.calc_Z(ds_new)
    meanZ = ds_new["DEPTH_Z"].mean().item()
    meanZpos = ds_new["DEPTH"].mean().item()
    assert abs(meanZ + meanZpos) < 10


def test_output_dtypes_end_to_end(tmp_path: pathlib.Path) -> None:
    """Multi-dive conversion then write yields the intended on-disk dtypes and fills.

    Exercises the concat path: QC flags must be int8 in the written file (they were
    re-promoted to float when set_best_dtype ran per dive), and PROFILE_NUMBER keeps its
    -9999 fill through both set_best_dtype and the compression writer.
    """
    source = str(parent_dir / "data/demo_sg005")
    datasets = readers.load_basestation_files(source, 1, 5)
    ds, _ = convertOG1.convert_to_OG1(datasets)
    out = tmp_path / "out.nc"

    assert writers.save_dataset(ds, str(out)) is True

    with netCDF4.Dataset(out) as nc:
        assert nc.variables["TEMP_QC"].dtype == np.dtype("int8")
        assert nc.variables["PSAL_QC"].dtype == np.dtype("int8")
        assert nc.variables["PHASE"].dtype == np.dtype("int8")
        profile = nc.variables["PROFILE_NUMBER"]
        assert profile.dtype == np.dtype("int16")
        assert profile.getncattr("_FillValue") == -9999
        assert nc.variables["DEPTH"].dtype == np.dtype("float32")
        assert nc.variables["LATITUDE"].dtype == np.dtype("float64")
