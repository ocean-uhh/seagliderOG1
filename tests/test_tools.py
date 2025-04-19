import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import numpy as np
import xarray as xr
import gsw
from seagliderOG1 import tools


def test_convert_units_var():

    test_pairs = {
        # 'var_name': ('current_units', 'new_units', 'current_value', 'converted_value')
        "velo1": ("cm/s", "m/s", 100, 1.0),
        "velo2": ("m/s", "cm/s", 1.0, 100),
        "velo3": ("cm s-1", "m s-1", 100, 1.0),
        "conduct1": ("S/m", "mS/cm", 10, 1.0),
        "conduct2": ("mS/cm", "S/m", 1.0, 10),
        "pres1": ("dbar", "Pa", 1, 10000),
        "pres2": ("Pa", "dbar", 10000, 1),
        "pres3": ("dbar", "kPa", 1, 10),
        "dist1": ("m", "cm", 1, 100),
        "dist2": ("m", "km", 1000, 1.0),
        "dist3": ("cm", "m", 100, 1.0),
        "dist4": ("km", "m", 1, 1000),
        "density1": ("g m-3", "kg m-3", 1000, 1),
        "density2": ("kg m-3", "g m-3", 1, 1000),
        "temp": ("degrees_Celcius", "Celcius", 1, 1),
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
