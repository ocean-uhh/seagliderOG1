import numpy as np
import xarray as xr
from seagliderOG1 import vocabularies
from seagliderOG1 import attr_input
import gsw
import logging
from datetime import datetime
from numbers import Number
#import importlib
#importlib.reload(vocabularies)

_log = logging.getLogger(__name__)


def save_dataset(ds, output_file='../test.nc'):
    """
    Attempts to save the dataset to a NetCDF file. If a TypeError occurs due to invalid attribute values,
    it converts the invalid attributes to strings and retries the save operation.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset to be saved.
    output_file (str): The path to the output NetCDF file. Defaults to 'test.nc'.

    Returns
    -------
    bool: True if the dataset was saved successfully, False otherwise.

    Based on: https://github.com/pydata/xarray/issues/3743
    """
    valid_types = (str, int, float, np.float32, np.float64, np.int32, np.int64)
    valid_types = (str, Number, np.ndarray, np.number, list, tuple)
    try:
        ds.to_netcdf(output_file, format='NETCDF4')
        return True
    except TypeError as e:
        print(e.__class__.__name__, e)
        for variable in ds.variables.values():
            for k, v in variable.attrs.items():
                if not isinstance(v, valid_types) or isinstance(v, bool):
                    variable.attrs[k] = str(v)
        try:
            ds.to_netcdf(output_file, format='NETCDF4')
            return True
        except Exception as e:
            print("Failed to save dataset:", e)
            datetime_vars = [var for var in ds_new.variables if ds_new[var].dtype == 'datetime64[ns]']
            print("Variables with dtype datetime64[ns]:", datetime_vars)
            float_attrs = [attr for attr in ds_new.attrs if isinstance(ds_new.attrs[attr], float)]
            print("Attributes with dtype float64:", float_attrs)
            return False


def convert_to_OG1(datasets, contrib_to_append=None):
    """
    Processes a list of xarray datasets or a single xarray dataset, converts them to OG1 format,
    concatenates the datasets, sorts by time, and applies attributes.

    Parameters
    ----------
    datasets (list or xarray.Dataset): A list of xarray datasets or a single xarray dataset in basestation format.
    contrib_to_append (dict, optional): Dictionary containing additional contributor information to append.

    Returns
    -------
    xarray.Dataset: The concatenated and processed dataset.
    """
    if not isinstance(datasets, list):
        datasets = [datasets]

    processed_datasets = []
    for ds in datasets:
        ds_new, attr_warnings, sg_cal, dc_other, dc_log = convert_to_OG1_dataset(ds, contrib_to_append)
        if ds_new:
            processed_datasets.append(ds_new)
        else:
            print(f"Warning: Dataset for dive number {ds.attrs['dive_number']} is empty or invalid.")

    concatenated_ds = xr.concat(processed_datasets, dim='N_MEASUREMENTS')
    concatenated_ds = concatenated_ds.sortby('TIME')

    # Apply attributes
    ordered_attributes = update_dataset_attributes(datasets[0], contrib_to_append)
    for key, value in ordered_attributes.items():
        concatenated_ds.attrs[key] = value

    # Construct the platform serial number
    PLATFORM_SERIAL_NUMBER = 'sg' + concatenated_ds.attrs['id'][1:4]
    concatenated_ds['PLATFORM_SERIAL_NUMBER'] = PLATFORM_SERIAL_NUMBER
    concatenated_ds['PLATFORM_SERIAL_NUMBER'].attrs['long_name'] = "glider serial number"

    # Construct the unique identifier attribute
    id = f"{PLATFORM_SERIAL_NUMBER}_{concatenated_ds.start_date}_delayed"
    concatenated_ds.attrs['id'] = id

    return concatenated_ds

def convert_to_OG1_dataset(ds1, contrib_to_append=None):
    """
    Converts the dataset and updates its attributes.

    Parameters
    ----------
    ds1 (xarray.Dataset): The input dataset to be processed.
    contrib_to_append (dict): Dictionary containing additional contributor information to append.

    Returns
    -------
    tuple: A tuple containing:
        - ds_new (xarray.Dataset): The processed dataset.
        - attr_warnings (list): A list of warnings related to attribute assignments.
        - sg_cal (xarray.Dataset): A dataset containing variables starting with 'sg_cal'.
        - dc_other (xarray.Dataset): A dataset containing other variables not categorized under 'sg_cal' or 'dc_log'.
        - dc_log (xarray.Dataset): A dataset containing variables starting with 'log_'.
        - ordered_attributes (dict): The dataset with updated attributes.
    """
    # Convert the dataset and output also variables not included
    ds_new, attr_warnings, sg_cal, dc_other, dc_log = process_dataset(ds1)

    return ds_new, attr_warnings, sg_cal, dc_other, dc_log

def process_dataset(ds1):
    """
    Processes a dataset by performing a series of transformations and extractions.

    Parameter
    ---------
        ds1 (xarray.Dataset): The input dataset containing various attributes and variables.

    Returns
    -------
    tuple: A tuple containing:
        - ds_new (xarray.Dataset): The processed dataset with renamed variables, assigned attributes, 
            converted units, and additional information such as GPS info and dive number.
        - attr_warnings (list): A list of warnings related to attribute assignments.
        - sg_cal (xarray.Dataset): A dataset containing variables starting with 'sg_cal'.
        - dc_other (xarray.Dataset): A dataset containing other variables not categorized under 'sg_cal' or 'dc_log'.
    Steps:
        1. Handle and split the inputs
            - Extract the dive number from the attributes   
            - Split the dataset by unique dimensions.
            - Extract the gps_info from the split dataset.
            - Extract variables starting with 'sg_cal'.  These are originally from sg_calib_constants.m.
        2. Rename the dataset dimensions, coordinates and variables according to OG1
            - Extract and rename dimensions for 'sg_data_point'. These will be the N_MEASUREMENTS.
            - Rename variables according to the OG1 vocabulary.
            - Assign variable attributes according to OG1.  Pass back warnings where there were conflicts.
            - Convert units in the dataset (e.g., cm/s to m/s) where possible.
        3. Add new variables
            - Add GPS info as LATITUDE_GPS, LONGITUDE_GPS and TIME_GPS (increase length of N_MEASUREMENTS)
            - Add the divenum as a variable of length N_MEASUREMENTS
            - Add the PROFILE_NUMBER (odd for dives, even for ascents)
            - Add the PHASE of the dive (1 for ascent, 2 for descent, 3 for between the first two surface points)
            - Add the DEPTH_Z with positive up
        4. Return the new dataset, the attribute warnings, the sg_cal dataset, and the dc_other dataset.
    Note
    ----
    Possibility of undesired behaviour:
        - It sorts by TIME
        - If there are not two surface GPS fixes before a dive, it may inadvertantly turn the whole thing to a dive.
    Checking for valid coordinates: https://github.com/pydata/xarray/issues/3743
    """

    # Check if the dataset has 'LONGITUDE' as a coordinate
    ds1 = utilities._validate_coordinates(ds1)
    if ds1 is None or len(ds1.variables) == 0:
        return xr.Dataset(), [], xr.Dataset(), xr.Dataset(), xr.Dataset()

    # Handle and split the inputs.
    #--------------------------------
    # Extract the dive number from the attributes
    divenum = ds1.attrs['dive_number']
    # Split the dataset by unique dimensions
    split_ds = split_by_unique_dims(ds1)
    # Extract the gps_info from the split dataset
    gps_info = split_ds[('gps_info',)]
    # Extract variables starting with 'sg_cal'
    # These will be needed to set attributes for the xarray dataset
    sg_cal, dc_log, dc_other = extract_variables(split_ds[()])

    # Rename variables and attributes, and convert units where necessary
    #-------------------------------------------------------------------
    # Extract the dataset for 'sg_data_point'
    # Must be after split_ds
    renamed_ds = rename_dimensions(split_ds[('sg_data_point',)])
    # Rename variables according to the OG1 vocabulary
    # Must be after rename_dimensions
    renamed_ds = rename_variables(renamed_ds)
    # Assign attributes to the variables
    # Must be ater rename_variables
    renamed_ds, attr_warnings = assign_variable_attributes(renamed_ds)
    # Convert units in renamed_ds (especially cm/s to m/s)
    renamed_ds = convert_units(renamed_ds)

    # Add new variables to the dataset (GPS, divenum, PROFILE_NUMBER, PHASE)
    #-----------------------------------------------------------------------
    # Add the gps_info to the dataset
    # Must be after split_by_unique_dims and after rename_dimensions
    ds_new = add_gps_info_to_dataset(renamed_ds, gps_info)
    # Add the variable divenum.  Assumes present in the attributes of the original dataset
    ds_new = add_dive_number(ds_new, divenum)
    # Add the profile number (odd for dives, even for ascents)
    # Must be run after adding divenum
    ds_new = assign_profile_number(ds_new, 'divenum')
    # Assign the phase of the dive (must be after adding divenum)
    ds_new = assign_phase(ds_new)
    # Assign DEPTH_Z to the dataset where positive is up.
    ds_new = calc_Z(ds_new)

    # Remove variables matching vocabularies.vars_to_remove and also 'TIME_GPS'
    vars_to_remove = vocabularies.vars_to_remove + ['TIME_GPS']
    ds_new = ds_new.drop_vars([var for var in vars_to_remove if var in ds_new.variables])

    return ds_new, attr_warnings, sg_cal, dc_other, dc_log

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

def extract_variables(ds):
    """
    Further splits the variables from the basestation file that had no dimensions.  Extracts them according to whether they were originally from sg_calib_constants, or were from log files, or were other mission/dive specific values.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset.  Runs after split_by_unique_dims, and designed to work on the variables from the basestation file that had no dimensions.

    Returns
    -------
    tuple: A tuple containing three xarray Datasets:
        - sg_cal (xarray.Dataset): Dataset with variables starting with 'sg_cal_', (originally from sg_calib_constants.m). Renamed to remove the prefix, so can be accessed with sg_cal.hd_a.
        - dc_log (xarray.Dataset): Dataset with variables starting with 'log_'. From log files.
        - dc_other (xarray.Dataset): Other mission/dive specific values. Includes depth-averaged currents but also things like magnetic_variation
    """

    sg_cal_vars = {var: ds[var] for var in ds.variables if var.startswith('sg_cal')}
    divecycle_other = {var: ds[var] for var in ds.variables if not var.startswith('sg_cal')}
    dc_log_vars = {var: ds[var] for var in divecycle_other if var.startswith('log_')}
    divecycle_other = {var: data for var, data in divecycle_other.items() if not var.startswith('log_')}

    # Create a new dataset with these variables, renaming to remove the leading 'sg_cal_'
    sg_cal = xr.Dataset({var.replace('sg_cal_', ''): data for var, data in sg_cal_vars.items()})
    dc_other = xr.Dataset(divecycle_other)
    dc_log = xr.Dataset(dc_log_vars)

    return sg_cal,  dc_log, dc_other

def rename_dimensions(ds, rename_dict=vocabularies.dims_rename_dict):
    """
    Rename dimensions of an xarray Dataset based on a provided dictionary for OG1 vocabulary.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset whose dimensions are to be renamed.
    rename_dict (dict, optional): A dictionary where keys are the current dimension names 
                                  and values are the new dimension names. Defaults to 
                                  vocabularies.dims_rename_dict.

    Returns
    -------
    xarray.Dataset: A new dataset with renamed dimensions.
    
    Raises:
    Warning: If no variables with dimensions matching any key in rename_dict are found.
    """
    # Check if there are any variables with dimensions matching 'sg_data_point'
    matching_vars = [var for var in ds.variables if any(dim in ds[var].dims for dim in rename_dict.keys())]
    if not matching_vars:
        _log.warning("No variables with dimensions matching any key in rename_dict found.")
    dims_to_rename = {dim: rename_dict[dim] for dim in ds.dims if dim in rename_dict}
    return ds.rename_dims(dims_to_rename)

def rename_variables(ds, rename_dict=vocabularies.standard_names):
    """
    Renames variables in the dataset based on the provided dictionary for OG1.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing variables to be renamed.
    rename_dict (dict): A dictionary where keys are the old variable names and values are the new variable names.

    Returns
    -------
    xarray.Dataset: The dataset with renamed variables.
    """
    for old_name, new_name in rename_dict.items():
        suffixes = ['', '_qc', '_raw', '_raw_qc']
        variants = [old_name + suffix for suffix in suffixes]
        variants_new = [new_name + suffix.upper() for suffix in suffixes]
        for variant in variants:
            new_name1 = variants_new[variants.index(variant)]
            if new_name1 in ds.variables:
                print(f"Warning: Variable '{new_name1}' already exists in the dataset.")
            elif variant in ds.variables:
                ds = ds.rename({variant: new_name1})
            elif variant in ds.variables:
                ds = ds.rename({variant: new_name1})
    return ds

def assign_variable_attributes(ds, vocab_attrs=vocabularies.vocab_attrs, unit_format=vocabularies.unit_str_format):
    """
    Assigns variable attributes to a dataset where they are missing and reformats units according to the provided unit_format.
    Attributes that already exist in the dataset are not changed, except for unit reformatting.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset to which attributes will be assigned.
    vocab_attrs (dict): A dictionary containing the vocabulary attributes to be assigned to the dataset variables.
    unit_str_format (dict): A dictionary mapping old unit strings to new formatted unit strings.

    Returns
    -------
    xarray.Dataset: The dataset with updated attributes.
    attr_warnings (set): A set containing warning messages for attribute mismatches.
    """
    attr_warnings = set()
    for var in ds.variables:
        if var in vocab_attrs:
            for attr, new_value in vocab_attrs[var].items():
                if attr in ds[var].attrs:
                    old_value = ds[var].attrs[attr]
                    if old_value in unit_format:
                        ds[var].attrs[attr] = unit_format[old_value]
                    old_value = ds[var].attrs[attr]
                    if old_value != new_value:
                        warning_msg = f"Warning: Variable '{var}' attribute '{attr}' mismatch: Old value: {old_value}, New value: {new_value}"
#                        print(warning_msg)
                        attr_warnings.add(warning_msg)
                else:
                    ds[var].attrs[attr] = new_value
    return ds, attr_warnings
                    
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

def add_gps_info_to_dataset(ds, gps_ds):
    """
    Add LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS to the dataset.  The values will be present within the N_MEASUREMENTS but with non-Nan values only when the GPS information is available.  The dataset will be sorted by TIME.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset with renamed dimensions and variables.
    gps_ds (xarray.Dataset): The dataset with gps_info from split_ds

    Returns
    -------
    xarray.Dataset: The new dataset with added GPS information. This only includes values for LATITUDE_GPS, LONGITUDE_GPS, TIME_GPS when the GPS information is available.

    Note
    ----
    This also sorts by ctd_time (from original basestation dataset) or TIME from ds.  If the data are not sorted by time, there may be unintended consequences.
    """
    # Create a new dataset with GPS information
    gps_ds = xr.Dataset(
        {
            'LONGITUDE': (['N_MEASUREMENTS'], gps_ds['log_gps_lon'].values),
        },
        coords={
            'LATITUDE': (['N_MEASUREMENTS'], gps_ds['log_gps_lat'].values),
            'TIME': (['N_MEASUREMENTS'], gps_ds['log_gps_time'].values),
            'DEPTH': (['N_MEASUREMENTS'], np.full(len(gps_ds['log_gps_lat']), 0))
        }
    )
    # Make DEPTH a coordinate
    gps_ds = gps_ds.set_coords('LONGITUDE')

    # Add the variables LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS to the dataset
    gps_ds['LATITUDE_GPS'] = (['N_MEASUREMENTS'], gps_ds.LATITUDE.values, {'dtype': gps_ds['LATITUDE'].dtype})
    gps_ds['LONGITUDE_GPS'] = (['N_MEASUREMENTS'], gps_ds.LONGITUDE.values, {'dtype': gps_ds['LONGITUDE'].dtype})
    gps_ds['TIME_GPS'] = (['N_MEASUREMENTS'], gps_ds.TIME.values, {'dtype': gps_ds['TIME'].dtype})

    # Concatenate ds and gps_ds
    datasets = []
    datasets.append(ds)
    datasets.append(gps_ds)
    ds_new = xr.concat(datasets, dim='N_MEASUREMENTS')
    ds_new = ds_new.sortby('TIME')

    return ds_new

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

##-----------------------------------------------------------------------------------------
## Editing attributes
##-----------------------------------------------------------------------------------------
def update_dataset_attributes(ds, contrib_to_append):
    """
    Updates the attributes of the dataset based on the provided attribute input.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset whose attributes need to be updated.
    attr_input (module): A module containing attribute configurations such as attr_as_is, attr_to_add, attr_to_rename, and order_of_attr.

    Returns
    -------
    xarray.Dataset: The dataset with updated attributes.
    """
    attr_as_is = attr_input.attr_as_is
    attr_to_add = attr_input.attr_to_add
    attr_to_rename = attr_input.attr_to_rename
    order_of_attr = attr_input.order_of_attr

    # Extract creators and contributors and institution, then reformulate strings
    contrib_attrs = get_contributors(ds, contrib_to_append)

    # Extract time attributes and reformat basic time strings
    time_attrs = get_time_attributes(ds)

    # Rename some
    renamed_attrs = extract_attr_to_rename(ds, attr_to_rename)

    # Attributes to keep
    keep_attrs = extract_attr_to_keep(ds, attr_as_is)

    # Combine all attributes
    new_attributes = {**attr_to_add, **contrib_attrs, **time_attrs, **renamed_attrs, **keep_attrs, **attr_to_add}

    # Reorder attributes according to attr_input.order_of_attr
    ordered_attributes = {attr: new_attributes[attr] for attr in order_of_attr if attr in new_attributes}

    # Add any remaining attributes that were not in the order_of_attr list
    for attr in new_attributes:
        if attr not in ordered_attributes:
            ordered_attributes[attr] = new_attributes[attr]

    return ordered_attributes

def get_contributors(ds, values_to_append=None):
    # Function to create or append to a list
    def create_or_append_list(existing_list, new_item):
        if new_item not in existing_list:
            new_item = new_item.replace(',','-')
            existing_list.append(new_item)
        return existing_list

    def list_to_comma_separated_string(lst):
            """
            Convert a list of strings to a single string with values separated by commas.
            Replace any commas present in list elements with hyphens.

            Parameters:
            lst (list): List of strings.

            Returns:
            str: Comma-separated string with commas in elements replaced by hyphens.
            """
            return ', '.join([item for item in lst])
    
    new_attributes = ds.attrs

    # Parse the original attributes into lists
    if 'creator_name' in new_attributes:
        names = create_or_append_list([], new_attributes['creator_name'])
        emails = create_or_append_list([], new_attributes.get('creator_email', ""))
        roles = create_or_append_list([], new_attributes.get('creator_role', "PI"))
        roles_vocab = create_or_append_list([], new_attributes.get('creator_role_vocabulary', "http://vocab.nerc.ac.uk/search_nvs/W08"))
        if 'contributor_name' in new_attributes:
            names = create_or_append_list(names, new_attributes['contributor_name'])
            emails = create_or_append_list(emails, new_attributes.get('contributor_email', ""))
            roles = create_or_append_list(roles, new_attributes.get('contributor_role', "PI"))
            roles_vocab = create_or_append_list(roles_vocab, new_attributes.get('contributor_role_vocabulary', "http://vocab.nerc.ac.uk/search_nvs/W08"))
    elif 'contributor_name' in new_attributes:
        names = create_or_append_list([], new_attributes['contributor_name'])
        emails = create_or_append_list([], new_attributes.get('contributor_email', ""))
        roles = create_or_append_list([], new_attributes.get('contributor_role', "PI"))
        roles_vocab = create_or_append_list([], new_attributes.get('contributor_role_vocabulary', "http://vocab.nerc.ac.uk/search_nvs/W08"))
    if 'contributing_institutions' in new_attributes:
        insts = create_or_append_list([], new_attributes.get('contributing_institutions', ''))
        inst_roles = create_or_append_list([], new_attributes.get('contributing_institutions_role', 'Operator'))
        inst_vocab = create_or_append_list([], new_attributes.get('contributing_institutions_vocabulary', 'https://edmo.seadatanet.org/report/1434'))
        inst_roles_vocab = create_or_append_list([], new_attributes.get('contributing_institutions_role_vocabulary', 'http://vocab.nerc.ac.uk/collection/W08/current/'))
    elif 'institution' in new_attributes:
        insts = create_or_append_list([], new_attributes['institution'])
        inst_roles = create_or_append_list([], new_attributes.get('contributing_institutions_role', 'PI'))
        inst_vocab = create_or_append_list([], new_attributes.get('contributing_institutions_vocabulary', 'https://edmo.seadatanet.org/report/1434'))
        inst_roles_vocab = create_or_append_list([], new_attributes.get('contributing_institutions_role_vocabulary', 'http://vocab.nerc.ac.uk/collection/W08/current/'))

    # Rename specific institution if it matches criteria
    for i, inst in enumerate(insts):
        if all(keyword in inst for keyword in ['Oceanography', 'University', 'Washington']):
            insts[i] = 'University of Washington - School of Oceanography'

    # Pad the lists if they are shorter than names
    max_length = len(names)
    emails += [''] * (max_length - len(emails))
    roles += [''] * (max_length - len(roles))
    roles_vocab += [''] * (max_length - len(roles_vocab))
    insts += [''] * (max_length - len(insts))
    inst_roles += [''] * (max_length - len(inst_roles))
    inst_vocab += [''] * (max_length - len(inst_vocab))
    inst_roles_vocab += [''] * (max_length - len(inst_roles_vocab))

    # Append new values to the lists
    if values_to_append is not None:
        for key, value in values_to_append.items():
            if key == 'contributor_name':
                names = create_or_append_list(names, value)
            elif key == 'contributor_email':
                emails = create_or_append_list(emails, value)
            elif key == 'contributor_role':
                roles = create_or_append_list(roles, value)
            elif key == 'contributor_role_vocabulary':
                roles_vocab = create_or_append_list(roles_vocab, value)
            elif key == 'contributing_institutions':
                insts = create_or_append_list(insts, value)
            elif key == 'contributing_institutions_role':
                inst_roles = create_or_append_list(inst_roles, value)
            elif key == 'contributing_institutions_vocabulary':
                inst_vocab = create_or_append_list(inst_vocab, value)
            elif key == 'contributing_institutions_role_vocabulary':
                inst_roles_vocab = create_or_append_list(inst_roles_vocab, value)

    # Turn the lists into comma-separated strings
    names_str = list_to_comma_separated_string(names)
    emails_str = list_to_comma_separated_string(emails)
    roles_str = list_to_comma_separated_string(roles)
    roles_vocab_str = list_to_comma_separated_string(roles_vocab)

    insts_str = list_to_comma_separated_string(insts)
    inst_roles_str = list_to_comma_separated_string(inst_roles)
    inst_vocab_str = list_to_comma_separated_string(inst_vocab)
    inst_roles_vocab_str = list_to_comma_separated_string(inst_roles_vocab)

    # Create a dictionary for return
    attributes_dict = {
        "contributor_name": names_str,
        "contributor_email": emails_str,
        "contributor_role": roles_str,
        "contributor_role_vocabulary": roles_vocab_str,
        "contributing_institutions": insts_str,
        "contributing_institutions_role": inst_roles_str,
        "contributing_institutions_vocabulary": inst_vocab_str,
        "contributing_institutions_role_vocabulary": inst_roles_vocab_str,
    }

    return attributes_dict


def get_time_attributes(ds):
    """
    Extracts and cleans time-related attributes from the dataset.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing various attributes.

    Returns
    -------
    dict: A dictionary containing cleaned time-related attributes.
    """
    def clean_time_string(time_str):
        return time_str.replace('_', '').replace(':', '').rstrip('Z').replace('-', '')

    time_attrs = {}
    time_attr_list = ['time_coverage_start', 'time_coverage_end', 'date_created', 'start_time']
    for attr in time_attr_list:
        if attr in ds.attrs:
            val1 = ds.attrs[attr]
            if isinstance(val1, (int, float)):
                val1 = datetime.utcfromtimestamp(val1).strftime('%Y%m%dT%H%M%S')
            if isinstance(val1, str) and ('-' in val1 or ':' in val1):
                val1 = clean_time_string(val1)
            time_attrs[attr] = val1
    time_attrs['date_modified'] = datetime.now().strftime('%Y%m%dT%H%M%S')

    # Get start_date in there
    if 'start_time' in time_attrs:
        time_attrs['start_date'] = time_attrs.pop('start_time')
    if 'start_date' not in time_attrs:
        time_attrs['start_date'] = time_attrs['time_coverage_start']
    return time_attrs

def extract_attr_to_keep(ds1, attr_as_is=attr_input.attr_as_is):
    retained_attrs = {}

    # Retain attributes based on attr_as_is
    for attr in attr_as_is:
        if attr in ds1.attrs:
            retained_attrs[attr] = ds1.attrs[attr]

    return retained_attrs

def extract_attr_to_rename(ds1, attr_to_rename=attr_input.attr_to_rename):
    renamed_attrs = {}
    # Rename attributes based on values_to_rename
    for new_attr, old_attr in attr_to_rename.items():
        if old_attr in ds1.attrs:
            renamed_attrs[new_attr] = ds1.attrs[old_attr]
    
    return renamed_attrs


