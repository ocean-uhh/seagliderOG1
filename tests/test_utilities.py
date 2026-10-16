import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import numpy as np  # noqa: E402  # import after sys.path bootstrap
import xarray as xr  # noqa: E402  # import after sys.path bootstrap

from seagliderOG1 import _pipeline  # noqa: E402  # import after sys.path bootstrap

rng = np.random.default_rng(0)


def test_validate_coords():
    """Test function for the `_pipeline._validate_coords` function.
    This function creates a dummy xarray dataset with coordinates N_MEASUREMENTS.
    It then validates the coordinates using the `_validate_coords` function.
    Asserts:
        - The coordinates are validated correctly.
    """
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("sg_data_point", rng.random(10)),
            "ctd_depth": ("sg_data_point", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )
    dataset.attrs["id"] = "testID"

    # Validate coordinates using the _validate_coords function
    ds1 = _pipeline._validate_coords(dataset)
    assert "ctd_time" in ds1.coords
    assert "ctd_depth" in ds1.coords
    assert "latitude" in ds1.coords
    assert len(ds1.coords["longitude"]) == ds1.dims["sg_data_point"]


def test_validate_dims():
    """Test function for the `_pipeline._validate_dims` function.
    This function creates a dummy xarray dataset with dimensions N_MEASUREMENTS.
    It then validates the dimensions using the `_validate_dims` function.
    Asserts:
        - The dimensions are validated correctly.
    """
    # Create a dummy xarray dataset with dimensions N_MEASUREMENTS
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("N_MEASUREMENTS", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )
    # Validate dimensions using the _validate_dims function
    valid = _pipeline._validate_dims(dataset)

    assert valid is True

    # Create a dummy xarray dataset with incorrect dimensions
    dataset_invalid = xr.Dataset(
        {
            "ctd_time": ("INVALID_DIM", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )

    # Validate dimensions using the _validate_dims function
    valid_invalid = _pipeline._validate_dims(dataset_invalid)

    assert valid_invalid is False


def test_clean_time_string():
    """Test function for the `_pipeline._clean_time_string` function.
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
        cleaned_tstring = _pipeline._clean_time_string(tstring)

        assert cleaned_tstring == tstring1
