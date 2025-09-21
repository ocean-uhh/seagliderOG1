import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import utilities
import xarray as xr
import numpy as np


def test_validate_coords():
    """Test function for the `utilities._validate_coords` function.
    This function creates a dummy xarray dataset with coordinates N_MEASUREMENTS.
    It then validates the coordinates using the `_validate_coords` function.
    Asserts:
        - The coordinates are validated correctly.
    """
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("sg_data_point", np.random.rand(10)),
            "ctd_depth": ("sg_data_point", np.random.rand(10)),
        },
        coords={"longitude": np.random.rand(10), "latitude": np.random.rand(10)},
    )
    dataset.attrs["id"] = "testID"

    # Validate coordinates using the _validate_coords function
    ds1 = utilities._validate_coords(dataset)
    assert "ctd_time" in ds1.coords
    assert "ctd_depth" in ds1.coords
    assert "latitude" in ds1.coords
    assert len(ds1.coords["longitude"]) == ds1.dims["sg_data_point"]


def test_validate_dims():
    """Test function for the `utilities._validate_dims` function.
    This function creates a dummy xarray dataset with dimensions N_MEASUREMENTS.
    It then validates the dimensions using the `_validate_dims` function.
    Asserts:
        - The dimensions are validated correctly.
    """
    # Create a dummy xarray dataset with dimensions N_MEASUREMENTS
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("N_MEASUREMENTS", np.random.rand(10)),
        },
        coords={"longitude": np.random.rand(10), "latitude": np.random.rand(10)},
    )
    # Validate dimensions using the _validate_dims function
    valid = utilities._validate_dims(dataset)

    assert valid is True

    # Create a dummy xarray dataset with incorrect dimensions
    dataset_invalid = xr.Dataset(
        {
            "ctd_time": ("INVALID_DIM", np.random.rand(10)),
        },
        coords={"longitude": np.random.rand(10), "latitude": np.random.rand(10)},
    )

    # Validate dimensions using the _validate_dims function
    valid_invalid = utilities._validate_dims(dataset_invalid)

    assert valid_invalid is False


def test_clean_time_string():
    """Test function for the `utilities._clean_time_string` function.
    This function defines a set of test strings with expected cleaned strings.
    It then iterates over these test strings, cleans them using the `_clean_time_string` function,
    and asserts that the cleaned strings match the expected values.
    Test strings and their expected results:
        - "2018-01-01T00:00:00Z": "20180101T000000"
        - "2018-01-01T00:00:00": "20180101T000000"
        - "2018-01-01_00:00:00": "20180101T000000"
        - "2018-01-01_00:00:00Z": "20180101T000000"
    Asserts:
        - The cleaned string matches the expected cleaned string.
    """
    test_strings = {
        "2018-01-01T00:00:00Z": "20180101T000000",
        "2018-01-01T00:00:00": "20180101T000000",
        "2018-01-01_00:00:00": "20180101000000",
        "2018-01-01_00:00:00Z": "20180101000000",
    }

    for tstring, tstring1 in test_strings.items():
        cleaned_tstring = utilities._clean_time_string(tstring)

        assert cleaned_tstring == tstring1


def test_clean_anc_vars():
    def test_clean_anc_vars():
        """Test function for the `utilities._clean_anc_vars_list` function.
        This function defines a set of test strings with expected cleaned lists.
        It then iterates over these test strings, cleans them using the `_clean_anc_vars_list` function,
        and asserts that the cleaned lists match the expected values.
        Test strings and their expected results:
            - "sg_cal_t_j sg_cal_t_k": ["t_j", "t_k"]
            - "sg_cal_Pcor sg_cal_Foffset": ["Pcor", "Foffset"]
        Asserts:
            - The cleaned list matches the expected cleaned list.
        """
        test_strings = {
            "sg_cal_t_j sg_cal_t_h sg_cal_t_i": ["t_j", "t_h", "t_i"],
            "sg_cal_A sg_cal_Pcor sg_cal_Foffset": ["A", "Pcor", "Foffset"],
            "c_g c_h c_i": ["c_g", "c_h", "c_i"],
        }

        for anc_vars_str, expected_list in test_strings.items():
            cleaned_list = utilities._clean_anc_vars_list(anc_vars_str)

            assert cleaned_list == expected_list


def test_parse_calibcomm():
    """Test function for the `utilities._parse_calibcomm` function.
    This function defines a set of test strings with expected calibration dates and serial numbers.
    It then iterates over these test strings, parses them using the `_parse_calibcomm` function,
    and asserts that the parsed results match the expected values.
    Test strings and their expected results:
        - "SBE s/n 0112 calibration 20apr09": ('20090420', '0112')
        - "SBE#29613t1/c1 calibration 7 Sep 02": ('20020907', '29613')
        - "SBE t12/c12 calibration 30DEC03": ('20031230', 'Unknown')
        - "SBE s/n 19, calibration 9/10/08": ('20080910', '19')
        - "SBE 0015 calibration 4/28/08": ('20080428', '0015')
        - "SBE 24520-1 calibration 04FEB08": ('20080204', '24520-1')
        - "SBE 0021 calibration 15sep08": ('20080915', '0021')
        - "SBE s/n 0025, calibration 10 june 08": ('20080610', '0025')
    Asserts:
        - The parsed calibration date matches the expected calibration date.
        - The parsed serial number matches the expected serial number.
    """
    test_strings = {
        "SBE s/n 0112 calibration 20apr09": ("20090420", "0112"),
        "SBE#29613t1/c1 calibration 7 Sep 02": ("20020907", "29613t1c1"),
        "SBE t12/c12 calibration 30DEC03": ("20031230", "t12c12"),
        "SBE s/n 19, calibration 9/10/08": ("20080910", "19"),
        "SBE 0015 calibration 4/28/08": ("20080428", "0015"),
        "SBE 24520-1 calibration 04FEB08": ("20080204", "24520-1"),
        "SBE 0021 calibration 15sep08": ("20080915", "0021"),
        "SBE s/n 0025, calibration 10 june 08": ("20080610", "0025"),
        "Optode 4330F S/N 182 foil batch 2808F calibrated 09may09": (
            "20090509",
            "182 foil batch 2808F",
        ),
        "SBE 43F s/n 25281-1 calibration 12 Aug 01": ("20010812", "25281-1"),
        "SBE 43F s/n 041 calibration 22JAN04": ("20040122", "041"),
        "SBE 43 s/n F0012 calibration 27 Aug 02": ("20020827", "F0012"),
        "0061": ("Unknown", "0061"),
        "SBE 43F s/n 029 calibration 07May07": ("20070507", "029"),
    }
    for calstring, (caldate1, serialnum1) in test_strings.items():
        caldate, serialnum = utilities._parse_calibcomm(calstring, firstrun=False)

        assert caldate == caldate1
        assert serialnum == serialnum1
