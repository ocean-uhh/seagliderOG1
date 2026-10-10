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


def test_get_contributors_demo_sg005_real_attrs():
    """demo_sg005: role-less creator kept + warned; PI alias; institution -> EDMO 1434."""
    import warnings

    ds = xr.Dataset(
        attrs={
            "creator_name": "Charlie Eriksen",
            "creator_email": "eriksen@uw.edu",
            "contributor_name": "Peter Rhines",
            "contributor_role": "Principal investigator",
            "institution": (
                "School of Oceanography\nUniversity of Washington\n"
                "Seattle, WA 98195-5351"
            ),
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        attrs = convertOG1.get_contributors(ds)
    assert attrs["contributor_name"] == "Charlie Eriksen, Peter Rhines"
    assert attrs["contributor_role"] == ", PI"  # Eriksen role-less; Rhines normalised
    assert attrs["contributor_email"] == "eriksen@uw.edu, "
    assert (
        attrs["contributing_institutions"]
        == "University of Washington (School of Oceanography)"
    )
    assert (
        attrs["contributing_institutions_vocabulary"]
        == "https://edmo.seadatanet.org/report/1434"
    )
    assert any("no role for contributor" in str(w.message) for w in caught)


def test_get_contributors_config_fills_creator_role():
    """A config person matching the role-less creator gives one slot, email filled."""
    ds = xr.Dataset(
        attrs={"creator_name": "Charlie Eriksen", "creator_email": "eriksen@uw.edu"}
    )
    attrs = convertOG1.get_contributors(
        ds, people=[{"name": "Charlie Eriksen", "role": "PI"}]
    )
    assert attrs["contributor_name"] == "Charlie Eriksen"
    assert attrs["contributor_role"] == "PI"
    assert attrs["contributor_email"] == "eriksen@uw.edu"


def test_global_attributes_collision_raises():
    """A global_attributes key that collides with a derived global is an error."""
    try:
        convertOG1.convert_to_OG1([], global_attributes={"id": "x"})
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected ValueError for derived-global collision")


def test_start_date_global_attribute_collision_raises():
    """start_date is converter-derived (names id/TRAJECTORY); a config override is rejected."""
    try:
        convertOG1.convert_to_OG1(
            [], global_attributes={"start_date": "20080606T000000"}
        )
    except ValueError as exc:
        assert "start_date" in str(exc)
    else:
        raise AssertionError("expected ValueError for start_date collision")


def test_apply_keep_variables_retains_mandatory_and_qc():
    """keep_variables keeps the ask plus every mandatory var and the kept var's _QC."""
    import warnings

    ds = xr.Dataset(
        {
            "TEMP": ("N", [1.0, 2.0]),
            "TEMP_QC": ("N", [1, 1]),
            "PSAL": ("N", [3.0, 4.0]),
            "GLIDE_SPEED": ("N", [0.1, 0.2]),
            "PLATFORM_SERIAL_NUMBER": ((), "sg005"),
            "WMO_IDENTIFIER": ((), "UNK"),
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = convertOG1.apply_keep_variables(ds, ["TEMP"])
    assert "TEMP" in out.variables and "TEMP_QC" in out.variables  # ask + its QC
    assert "PLATFORM_SERIAL_NUMBER" in out.variables  # mandatory family
    assert "WMO_IDENTIFIER" in out.variables  # mandatory
    assert "PSAL" not in out.variables and "GLIDE_SPEED" not in out.variables  # dropped
    assert any("dropped" in str(w.message) for w in caught)


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
