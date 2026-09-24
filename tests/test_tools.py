import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import numpy as np
import xarray as xr
import pandas as pd
import gsw
from seagliderOG1 import tools, readers, convertOG1


def test_convert_units_var():

    test_pairs = {
        # 'var_name': ('current_units', 'new_units', 'current_value', 'converted_value')
        "velo1": ("cm/s", "m/s", 100, 1.0),
        "velo2": ("m/s", "cm/s", 1.0, 100),
        "velo3": ("cm s-1", "m s-1", 100, 1.0),
        "conduct1": ("S/m", "mS/cm", 1.0, 10),
        "conduct2": ("mS/cm", "S/m", 10, 1.0),
        "pres1": ("dbar", "Pa", 1, 10000),
        "pres2": ("Pa", "dbar", 10000, 1),
        "pres3": ("dbar", "kPa", 1, 10),
        "dist1": ("m", "cm", 1, 100),
        "dist2": ("m", "km", 1000, 1.0),
        "dist3": ("cm", "m", 100, 1.0),
        "dist4": ("km", "m", 1, 1000),
        "density1": ("g m-3", "kg m-3", 1000, 1),
        "density2": ("kg m-3", "g m-3", 1, 1000),
        "temp": ("degrees_Celsius", "Celsius", 1, 1),
    }
    for _, (current_units, new_units, current_value, new_value) in test_pairs.items():
        converted_values, _ = tools.convert_units_var(
            current_value, current_units, new_units
        )
        assert converted_values == new_value


def test_calc_z():
    pressure_values = np.arange(10, 10000, 10)
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "PRES": ("N_MEASUREMENTS", pressure_values),
        },
        coords={
            "LATITUDE": ("N_MEASUREMENTS", 30 + 0 * pressure_values),
        },
    )
    depth = gsw.z_from_p(dataset["PRES"], dataset["LATITUDE"]).values
    depth_z = tools.calc_Z(dataset)["DEPTH_Z"].values

    assert np.array_equal(depth, depth_z)


def test_add_hdm_parameters():
    source = str(parent_dir / "data/demo_sg005")
    print("Testing load_basestation_files with source:", source)
    start_profile = 1
    end_profile = 5
    datasets = readers.load_basestation_files(source, start_profile, end_profile)
    hdm_parameters = tools.extract_hdm_parameters(datasets)
    ds_OG1, vars = convertOG1.convert_to_OG1(datasets)
    ds_OG1 = tools.add_hdm_parameters(ds_OG1, hdm_parameters)
    ### check if the hdm parameters are added to the dataset and have the expected values
    for param in hdm_parameters:
        assert param in ds_OG1


def test_find_best_dtype_named_integers() -> None:
    """Named integer variables map to their fixed integer type."""
    da = xr.DataArray(np.arange(5.0))
    assert tools.find_best_dtype("PHASE", da) == np.int8
    assert tools.find_best_dtype("PROFILE_NUMBER", da) == np.int16
    assert tools.find_best_dtype("VBD_MIN_CNTS", da) == np.int16


def test_find_best_dtype_qc_and_latlon() -> None:
    """QC variables become int8 (case-insensitive); lat/lon stay double."""
    da = xr.DataArray(np.arange(3.0))
    assert tools.find_best_dtype("TEMP_QC", da) == np.int8
    assert tools.find_best_dtype("temp_qc", da) == np.int8
    assert tools.find_best_dtype("LATITUDE", da) == np.double
    assert tools.find_best_dtype("LONGITUDE_GPS", da) == np.double


def test_find_best_dtype_raw_not_truncated() -> None:
    """A float variable whose name ends in 'raw' is not cast to int (clause removed)."""
    da = xr.DataArray(np.array([1.5, 2.5, 3.5]))
    assert tools.find_best_dtype("optics_raw", da) == np.float32


def test_find_best_dtype_float64_to_float32() -> None:
    """Generic float64 variables downcast to float32."""
    assert tools.find_best_dtype("TEMP", xr.DataArray(np.arange(3.0))) == np.float32


def test_set_best_dtype_preserves_existing_fill_value() -> None:
    """An existing _FillValue sentinel is kept, not overwritten by the bit-width default."""
    da = xr.DataArray(
        np.array([1, 3, -9999], dtype="int64"), dims="x", name="PROFILE_NUMBER"
    )
    da.encoding["_FillValue"] = -9999
    ds = tools.set_best_dtype(xr.Dataset({"PROFILE_NUMBER": da}))
    assert ds["PROFILE_NUMBER"].dtype == np.int16
    assert ds["PROFILE_NUMBER"].encoding["_FillValue"] == -9999
    assert "_FillValue" not in ds["PROFILE_NUMBER"].attrs


def test_set_best_dtype_skips_qc() -> None:
    """QC flags are left to convert_qc_flags; set_best_dtype adds no bit-width fill."""
    qc = xr.DataArray(np.array([1, 2, 6], dtype="int8"), dims="x", name="TEMP_QC")
    ds = tools.set_best_dtype(xr.Dataset({"TEMP_QC": qc}))
    assert ds["TEMP_QC"].dtype == np.int8
    assert "_FillValue" not in ds["TEMP_QC"].encoding


def test_set_best_dtype_scalar_integer() -> None:
    """A scalar integer variable coerces without a 0-d indexing error."""
    ds = xr.Dataset({"VBD_MIN_CNTS": xr.DataArray(np.float64(500.0))})
    out = tools.set_best_dtype(ds)
    assert out["VBD_MIN_CNTS"].dtype == np.int16


def test_set_best_dtype_restores_depth_coord() -> None:
    """DEPTH coerces to float32 and remains a coordinate."""
    ds = xr.Dataset(
        {"DEPTH": xr.DataArray(np.arange(4.0), dims="x", name="DEPTH")}
    ).set_coords("DEPTH")
    out = tools.set_best_dtype(ds)
    assert out["DEPTH"].dtype == np.float32
    assert "DEPTH" in out.coords


def test_OG1_name_mapping_sample_dataset():
    ds1 = readers.load_sample_dataset()
    split_ds = tools.split_by_unique_dims(ds1)

    assert set(split_ds) == {
        (),
        ("gc_event",),
        ("gps_info",),
        ("sg_data_point",),
    }

    ds = split_ds[("sg_data_point",)]

    mapping = tools.OG1_name_mapping(
        ds=ds,
        ds1_base=ds1,
        ctd_dim="sg_data_point",
    )

    expected_columns = [
        "original_name",
        "OG1_name",
        "instrument",
        "instrument_type",
        "original_dimension",
    ]
    assert list(mapping.columns) == expected_columns

    # There must be exactly one mapping row for every input variable.
    expected_variables = set(ds.data_vars) | set(ds.coords)
    assert set(mapping["original_name"]) == expected_variables
    assert mapping["original_name"].is_unique

    # Index by original name so the assertions do not depend on row order.
    actual = mapping.set_index("original_name")

    expected_og1_names = {
        "temperature_raw": "TEMP_RAW",
        "temperature": "TEMP",
        "conductivity_raw": "CNDC_RAW",
        "conductivity": "CNDC",
        "ctd_time": "TIME",
        "ctd_depth": "DEPTH",
        "temperature_raw_qc": "TEMP_RAW_QC",
        "temperature_qc": "TEMP_QC",
        "conductivity_raw_qc": "CNDC_RAW_QC",
        "conductivity_qc": "CNDC_QC",
        "vert_speed": "GLIDER_VERT_VELO_MODEL",
        "time": "TIME2",
        "theta": "THETA",
        "speed": "GLIDE_SPEED",
        "sound_velocity": "SOUND_VELOCITY",
        "sigma_theta": "SIGTHETA",
        "sigma_t": "SIGMA_T",
        "sbe43_results_time": "TIME_DOXY",
        "sbe43_dissolved_oxygen": "DOXY",
        "salinity_raw": "PSAL_RAW",
        "salinity": "PSAL",
        "pressure": "PRES",
        "north_displacement": "NORTH_DISPLACEMENT",
        "horz_speed": "GLIDER_HORZ_VELO_MODEL",
        "glide_angle": "GLIDE_ANGLE",
        "eng_wlbb2f_redRef": "BBP700_REF",
        "eng_wlbb2f_redCount": "BBP700",
        "eng_wlbb2f_fluorCount": "FLUOCHLA",
        "eng_wlbb2f_blueRef": "BBP470_REF",
        "eng_wlbb2f_blueCount": "BBP470",
        "eng_wlbb2f_VFtemp": "BBP_VFTEMP",
        "eng_vbdCC": "VBD_CC",
        "eng_tempFreq": "TEMP_FREQ",
        "eng_sbe43_O2Freq": "O2_FREQ",
        "eng_rollCtl": "ROLL_CTL",
        "eng_rollAng": "ROLL",
        "eng_pitchCtl": "PITCH_CTL",
        "eng_pitchAng": "PITCH",
        "eng_head": "HEADING",
        "eng_depth": "DEPTH2",
        "eng_condFreq": "COND_FREQ",
        "east_displacement": "EAST_DISPLACEMENT",
        "dissolved_oxygen_sat": "OXYSAT",
        "depth": "DEPTH3",
        "buoyancy": "BUOYANCY",
        "longitude": "LONGITUDE",
        "latitude": "LATITUDE",
        "speed_qc": "GLIDE_SPEED_QC",
        "sbe43_dissolved_oxygen_qc": "DOXY_QC",
        "salinity_raw_qc": "PSAL_RAW_QC",
        "salinity_qc": "PSAL_QC",
    }

    unmapped_variables = {
        "vert_speed_gsm",
        "speed_gsm",
        "north_displacement_gsm",
        "longitude_gsm",
        "latitude_gsm",
        "horz_speed_gsm",
        "glide_angle_gsm",
        "eng_elaps_t_0000",
        "eng_elaps_t",
        "east_displacement_gsm",
        "density",
    }

    assert set(actual.index) == set(expected_og1_names) | unmapped_variables

    for original_name, expected_og1_name in expected_og1_names.items():
        assert actual.at[original_name, "OG1_name"] == expected_og1_name

    for original_name in unmapped_variables:
        assert pd.isna(actual.at[original_name, "OG1_name"])

    expected_instruments = {
        "sbe41": {
            "temperature_raw",
            "temperature",
            "conductivity_raw",
            "conductivity",
            "ctd_time",
            "ctd_depth",
            "temperature_raw_qc",
            "temperature_qc",
            "conductivity_raw_qc",
            "conductivity_qc",
            "eng_tempFreq",
            "eng_condFreq",
        },
        "sbe43": {
            "sbe43_results_time",
            "sbe43_dissolved_oxygen",
            "sbe43_dissolved_oxygen_qc",
            "eng_sbe43_O2Freq",
        },
        "wlbb2f": {
            "eng_wlbb2f_redRef",
            "eng_wlbb2f_redCount",
            "eng_wlbb2f_fluorCount",
            "eng_wlbb2f_blueRef",
            "eng_wlbb2f_blueCount",
            "eng_wlbb2f_VFtemp",
        },
    }

    for instrument, variable_names in expected_instruments.items():
        assert set(actual.index[actual["instrument"].eq(instrument)]) == variable_names

    variables_without_instrument = expected_variables - set().union(
        *expected_instruments.values()
    )
    assert actual.loc[list(variables_without_instrument), "instrument"].isna().all()

    # All sample variables originate on the SG data-point dimension.
    assert actual["original_dimension"].eq("sg_data_point").all()

    # Instrument type must agree for every row assigned to the same instrument.
    for instrument in expected_instruments:
        instrument_types = (
            actual.loc[actual["instrument"].eq(instrument), "instrument_type"]
            .dropna()
            .unique()
        )
        assert len(instrument_types) <= 1
