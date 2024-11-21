import numpy as np
import pandas as pd
import xarray as xr
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.colors as mcolors
from seagliderOG1 import vocabularies
import gsw
import logging
from datetime import datetime

_log = logging.getLogger(__name__)

def find_best_dtype(var_name, da):
    input_dtype = da.dtype.type
    if "latitude" in var_name.lower() or "longitude" in var_name.lower():
        return np.double
    if var_name[-2:].lower() == "qc":
        return np.int8
    if "time" in var_name.lower():
        return input_dtype
    if var_name[-3:] == "raw" or "int" in str(input_dtype):
        if np.nanmax(da.values) < 2**16 / 2:
            return np.int16
        elif np.nanmax(da.values) < 2**32 / 2:
            return np.int32
    if input_dtype == np.float64:
        return np.float32
    return input_dtype

def set_best_dtype(ds):
    bytes_in = ds.nbytes
    for var_name in list(ds):
        da = ds[var_name]
        input_dtype = da.dtype.type
        new_dtype = find_best_dtype(var_name, da)
        for att in ["valid_min", "valid_max"]:
            if att in da.attrs.keys():
                da.attrs[att] = np.array(da.attrs[att]).astype(new_dtype)
        if new_dtype == input_dtype:
            continue
        _log.debug(f"{var_name} input dtype {input_dtype} change to {new_dtype}")
        da_new = da.astype(new_dtype)
        ds = ds.drop_vars(var_name)
        if "int" in str(new_dtype):
            fill_val = set_fill_value(new_dtype)
            da_new[np.isnan(da)] = fill_val
            da_new.encoding["_FillValue"] = fill_val
        ds[var_name] = da_new
    bytes_out = ds.nbytes
    _log.info(
        f"Space saved by dtype downgrade: {int(100 * (bytes_in - bytes_out) / bytes_in)} %",
    )
    return ds

def set_best_dtype_value(value, var_name):
    """
    Determines the best data type for a single value based on its variable name and converts it.

    Parameters
    ----------
    value : any
        The input value to convert.

    Returns
    -------
    converted_value : any
        The value converted to the best data type.
    """
    input_dtype = type(value)
    new_dtype = find_best_dtype(var_name, xr.DataArray(value))
    
    if new_dtype == input_dtype:
        return value
    
    converted_value = np.array(value).astype(new_dtype)
    
    if "int" in str(new_dtype) and np.isnan(value):
        fill_val = set_fill_value(new_dtype)
        converted_value = fill_val
    
    return converted_value

variables_sensors = {
    "CNDC": "CTD",
    "DOXY": "dissolved gas sensors",
    "PRES": "CTD",
    "PSAL": "CTD",
    "TEMP": "CTD",
    "BBP700": "fluorometers",
    "CHLA": "fluorometers",
    "PRES_ADCP": "ADVs and turbulence probes",
}

def add_sensors(ds, dsa):
    attrs = ds.attrs
    sensors = []
    for key, var in attrs.items():
        if not isinstance(var, str):
            continue
        if "{" not in var:
            continue
        if isinstance(eval(var), dict):
            sensors.append(key)

    sensor_name_type = {}
    for instr in sensors:
        if instr in ["altimeter"]:
            continue
        attr_dict = eval(attrs[instr])
        if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
            _log.error(f"sensor {attr_dict['make_model']} not found")
            continue
        var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]
        if "serial" in attr_dict.keys():
            var_dict["serial_number"] = str(attr_dict["serial"])
            var_dict["long_name"] += f":{str(attr_dict['serial'])}"
        for var_name in ["calibration_date", "calibration_parameters"]:
            if var_name in attr_dict.keys():
                var_dict[var_name] = str(attr_dict[var_name])
        da = xr.DataArray(attrs=var_dict)
        sensor_var_name = f"sensor_{var_dict['sensor_type']}_{var_dict['serial_number']}".upper().replace(
            " ",
            "_",
        )
        dsa[sensor_var_name] = da
        sensor_name_type[var_dict["sensor_type"]] = sensor_var_name

    for key, var in attrs.copy().items():
        if not isinstance(var, str):
            continue
        if "{" not in var:
            continue
        if isinstance(eval(var), dict):
            attrs.pop(key)
    ds.attrs = attrs

    for key, sensor_type in variables_sensors.items():
        if key in dsa.variables:
            instr_key = sensor_name_type[sensor_type]
            dsa[key].attrs["sensor"] = instr_key

    return ds, dsa

def split_by_unique_dims(ds):
    """
    Splits an xarray dataset into multiple datasets based on the unique set of dimensions of the variables.

    Parameters:
    ds (xarray.Dataset): The input xarray dataset containing various variables.

    Returns:
    tuple: A tuple containing xarray datasets, each with variables sharing the same set of dimensions.
    """
    # Dictionary to hold datasets with unique dimension sets
    unique_dims_datasets = {}

    # Iterate over the variables in the dataset
    for var_name, var_data in ds.data_vars.items():
        # Get the dimensions of the variable
        dims = tuple(var_data.dims)
        
        # If this dimension set is not in the dictionary, create a new dataset
        if dims not in unique_dims_datasets:
            unique_dims_datasets[dims] = xr.Dataset()
        
        # Add the variable to the corresponding dataset
        unique_dims_datasets[dims][var_name] = var_data

    # Convert the dictionary values to a dictionary of datasets
    return {dims: dataset for dims, dataset in unique_dims_datasets.items()}

def assign_profile_number(ds, divenum_str = 'divenum'):
    # Remove the variable dive_num_cast if it exists
    if 'dive_num_cast' in ds.variables:
        ds = ds.drop_vars('dive_num_cast')
    # Initialize the new variable with the same dimensions as dive_num
    ds['dive_num_cast'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))

    # Iterate over each unique dive_num
    for dive in np.unique(ds[divenum_str]):
        # Get the indices for the current dive
        dive_indices = np.where(ds[divenum_str] == dive)[0]
        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]
        
        # Find the index of the maximum pressure between start_index and end_index
        pmax = np.nanmax(ds['PRES'][start_index:end_index + 1].values) 
        # Find the index where PRES attains the value pmax between start_index and end_index
        pmax_index = start_index + np.argmax(ds['PRES'][start_index:end_index + 1].values == pmax)
        
        # Assign dive_num to all values up to and including the point where pmax is reached
        ds['dive_num_cast'][start_index:pmax_index + 1] = dive

        # Assign dive_num + 0.5 to all values after pmax is reached
        ds['dive_num_cast'][pmax_index + 1:end_index + 1] = dive + 0.5

        # Remove the variable PROFILE_NUMBER if it exists
        if 'PROFILE_NUMBER' in ds.variables:
            ds = ds.drop_vars('PROFILE_NUMBER')
        # Assign PROFILE_NUMBER as 2 * dive_num_cast - 1
        ds['PROFILE_NUMBER'] = 2 * ds['dive_num_cast'] - 1
    return ds

def add_dive_number(ds, dive_number):
    """
    Add dive number as a variable to the dataset.

    Parameters:
    ds (xarray.Dataset): The dataset to which the dive number will be added.

    Returns:
    xarray.Dataset: The dataset with the dive number added.
    """
    if dive_number==None:
        dive_number = ds.attrs.get('dive_number', np.nan)
    return ds.assign(divenum=('N_MEASUREMENTS', [dive_number] * ds.dims['N_MEASUREMENTS']))

def assign_phase(ds):
    """
    This function adds new variables 'PHASE' and 'PHASE_QC' to the dataset `ds`, which indicate the phase of each measurement. The phase is determined based on the pressure readings ('PRES') for each unique dive number ('dive_num').
    
    Note: In this formulation, we are only separating into dives and climbs based on when the glider is at the maximum depth. Future work needs to separate out the other phases: https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md and generate a PHASE_QC.
    Assigns phase values to the dataset based on pressure readings.
        
    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing 'dive_num' and 'PRES' variables.
    
    Returns
    -------
    xarray.Dataset: The dataset with an additional 'PHASE' variable, where:
    xarray.Dataset: The dataset with additional 'PHASE' and 'PHASE_QC' variables, where:
        - 'PHASE' indicates the phase of each measurement:
            - Phase 2 is assigned to measurements up to and including the maximum pressure point.
            - Phase 1 is assigned to measurements after the maximum pressure point.
        - 'PHASE_QC' is an additional variable with no QC applied.
        
    Note: In this formulation, we are only separating into dives and climbs based on when the glider is at the maximum depth.  Future work needs to separate out the other phases: https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md and generate a PHASE_QC
    """
    # Determine the correct keystring for divenum
    if 'dive_number' in ds.variables:
        divenum_str = 'dive_number'
    elif 'divenum' in ds.variables:
        divenum_str = 'divenum'
    elif 'dive_num' in ds.variables:
        divenum_str = 'dive_num'
    else:
        raise ValueError("No valid dive number variable found in the dataset.")
    # Initialize the new variable with the same dimensions as dive_num
    ds['PHASE'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))
    # Initialize the new variable PHASE_QC with the same dimensions as dive_num
    ds['PHASE_QC'] = (['N_MEASUREMENTS'], np.zeros(ds.dims['N_MEASUREMENTS'], dtype=int))

    # Iterate over each unique dive_num
    for dive in np.unique(ds[divenum_str]):
        # Get the indices for the current dive
        dive_indices = np.where(ds[divenum_str] == dive)[0]
        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]
        
        # Find the index of the maximum pressure between start_index and end_index
        pmax = np.nanmax(ds['PRES'][start_index:end_index + 1].values) 

        # Find the index where PRES attains the value pmax between start_index and end_index
        pmax_index = start_index + np.argmax(ds['PRES'][start_index:end_index + 1].values == pmax)
        
        # Assign phase 2 to all values up to and including the point where pmax is reached
        ds['PHASE'][start_index:pmax_index + 1] = 2

        # Assign phase 1 to all values after pmax is reached
        ds['PHASE'][pmax_index + 1:end_index + 1] = 1

        # Assign phase 3 to the time at the beginning of the dive, between the first valid TIME_GPS and the second valid TIME_GPS
        valid_time_gps_indices = np.where(~np.isnan(ds['TIME_GPS'][start_index:end_index + 1].values))[0]
        if len(valid_time_gps_indices) >= 2:
            first_valid_index = start_index + valid_time_gps_indices[0]
            second_valid_index = start_index + valid_time_gps_indices[1]
            ds['PHASE'][first_valid_index:second_valid_index + 1] = 3

    return ds

##----------------------------------------------------------------------------------------------------------------------------
## Calculations for new variables
##----------------------------------------------------------------------------------------------------------------------------
def calc_Z(ds):
    """
    Calculate the depth (Z position) of the glider using the gsw library to convert pressure to depth.
    
    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing 'PRES', 'LATITUDE', and 'LONGITUDE' variables.
    
    Returns
    -------
    xarray.Dataset: The dataset with an additional 'DEPTH' variable.
    """
    # Ensure the required variables are present
    if 'PRES' not in ds.variables or 'LATITUDE' not in ds.variables or 'LONGITUDE' not in ds.variables:
        raise ValueError("Dataset must contain 'PRES', 'LATITUDE', and 'LONGITUDE' variables.")

    # Initialize the new variable with the same dimensions as dive_num
    ds['DEPTH_Z'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))

    # Calculate depth using gsw
    depth = gsw.z_from_p(ds['PRES'], ds['LATITUDE'])
    ds['DEPTH_Z'] = depth

    # Assign the calculated depth to a new variable in the dataset
    ds['DEPTH_Z'].attrs = {
        "units": "meters",
        "positive": "up",
        "standard_name": "depth",
        "comment": "Depth calculated from pressure using gsw library, positive up.",
    }
    
    return ds

def convert_velocity_units(ds, var_name):
    """
    Convert the units of the specified variable to m/s if they are in cm/s.
    
    Parameters:
    ds (xarray.Dataset): The dataset containing the variable.
    var_name (str): The name of the variable to check and convert.
    
    Returns:
    xarray.Dataset: The dataset with the converted variable.
    """
    if var_name in ds.variables:
        # Pass through all other attributes as is
        for attr_name, attr_value in ds[var_name].attrs.items():
            if attr_name != 'units':
                ds[var_name].attrs[attr_name] = attr_value
            elif attr_name == 'units':
                if ds[var_name].attrs['units'] == 'cm/s':  
                    ds[var_name].values = ds[var_name].values / 100.0
                    ds[var_name].attrs['units'] = 'm/s'
                    print(f"Converted {var_name} to m/s")
                else:
                    print(f"{var_name} is already in m/s or units attribute is missing")
        
    else:
        print(f"{var_name} not found in the dataset")
    return ds

def convert_units(ds, preferred_units=vocabularies.preferred_units, unit_conversion=vocabularies.unit_conversion):
    """
    Convert the units of variables in an xarray Dataset to preferred units.  This is useful, for instance, to convert cm/s to m/s.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset containing variables to convert.
    preferred_units (list): A list of strings representing the preferred units.
    unit_conversion (dict): A dictionary mapping current units to conversion information.
    Each key is a unit string, and each value is a dictionary with:
        - 'factor': The factor to multiply the variable by to convert it.
        - 'units_name': The new unit name after conversion.

    Returns
    -------
    xarray.Dataset: The dataset with converted units.
    """

    for var in ds.variables:
        current_unit = ds[var].attrs.get('units')
        if current_unit in unit_conversion:
            conversion_info = unit_conversion[current_unit]
            new_unit = conversion_info['units_name']
            if new_unit in preferred_units:
                conversion_factor = conversion_info['factor']
                ds[var] = ds[var] * conversion_factor
                ds[var].attrs['units'] = new_unit

    return ds

