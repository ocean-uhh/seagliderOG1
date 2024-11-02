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
from seagliderOG1 import attr_input
import gsw
import logging
from datetime import datetime
import importlib
importlib.reload(vocabularies)


_log = logging.getLogger(__name__)

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
    """
    valid_types = (str, int, float, np.float32, np.float64, np.int32, np.int64)
    try:
        ds.to_netcdf(output_file, format='NETCDF4_CLASSIC')
        return True
    except TypeError as e:
        print(e.__class__.__name__, e)
        for variable in ds.variables.values():
            for k, v in variable.attrs.items():
                if not isinstance(v, valid_types) or isinstance(v, bool):
                    variable.attrs[k] = str(v)
        try:
            ds.to_netcdf(output_file, format='NETCDF4_CLASSIC')
            return True
        except Exception as e:
            print("Failed to save dataset:", e)
            datetime_vars = [var for var in ds_new.variables if ds_new[var].dtype == 'datetime64[ns]']
            print("Variables with dtype datetime64[ns]:", datetime_vars)

            return False

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
        - It resorts by TIME
        - If there are not two surface GPS fixes before a dive, it may inadvertantly turn the whole thing to a dive.
    """
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

    # Remove variables time and TIME_GPS
    if 'time' in ds_new.variables:
        ds_new = ds_new.drop_vars('time')
    if 'TIME_GPS' in ds_new.variables:
        ds_new = ds_new.drop_vars('TIME_GPS')

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
                        print(warning_msg)
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
        print(pmax)
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

def get_contributors(ds, values_to_append):
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
#------------------------------------------------------------------------------------------
# Older stuff (may be obsolete)
#------------------------------------------------------------------------------------------


def generate_attributes(ds_all):
    """
    Generate a dictionary of attributes to add and change for a dataset.

    Parameters:
    ds_all (object): An object containing various metadata attributes of the dataset.

    Returns:
    tuple: A tuple containing two dictionaries:
        - attr_to_add (dict): Attributes to add to the dataset.
        - attr_to_change (dict): Attributes to change in the dataset.

    The dictionaries contain the following keys:
    attr_to_add:
        - title: Title of the dataset.
        - platform: Platform type.
        - platform_vocabulary: URL to the platform vocabulary.
        - id: Unique identifier for the dataset.
        - contributor_email: Email of the contributor.
        - contributor_role_vocabulary: URL to the contributor role vocabulary.
        - contributing_institutions: Name of the contributing institutions.
        - contributing_institutions_vocabulary: URL to the contributing institutions vocabulary.
        - contributing_institutions_role: Role of the contributing institutions.
        - contributing_institutions_role_vocabulary: URL to the contributing institutions role vocabulary.
        - uri: Unique resource identifier.
        - uri_comment: Comment about the URI.
        - web_link: Web link to the dataset.
        - start_date: Start date of the dataset.
        - featureType: Feature type of the dataset.
        - landstation_version: Version of the land station.
        - glider_firmware_version: Version of the glider firmware.
        - rtqc_method: Real-time quality control method.
        - rtqc_method_doi: DOI for the RTQC method.
        - doi: DOI of the dataset.
        - data_url: URL to the data.
        - comment: History comment.

    attr_to_change:
        - time_coverage_start: Start time of the dataset coverage.
        - time_coverage_end: End time of the dataset coverage.
        - Conventions: Conventions followed by the dataset.
        - date_created: Creation date of the dataset.
        - date_modified: Modification date of the dataset.
        - contributor_name: Name of the contributor.
        - contributor_role: Role of the contributor.
    """

    title = "OceanGliders trajectory file"
    platform = "sub-surface gliders"
    platform_vocabulary = "https://vocab.nerc.ac.uk/collection/L06/current/27/"

    time_str = ds_all.time_coverage_start.replace('_', '').replace(':', '').rstrip('Z').rstrip('Z').replace('-','')
    id = ds_all.platform_id + '_' + time_str + '_delayed'
    time_coverage_start = time_str
    time_coverage_end = ds_all.time_coverage_end.replace('_', '').replace(':', '').rstrip('Z').replace('-','')

    site = ds_all.summary
    contributor_name = ds_all.creator_name + ', ' + ds_all.contributor_name
    contributor_email = ds_all.creator_email
    contributor_role = "PI, " + ds_all.contributor_role
    contributor_role_vocabulary = "http://vocab.nerc.ac.uk/search_nvs/W08/"
    contributing_institutions = "University of Washington - School of Oceanography, University of Hamburg - Institute of Oceanography"
    contributing_institutions_vocabulary = 'https://edmo.seadatanet.org/report/1434, https://edmo.seadatanet.org/report/1156'
    contributing_institutions_role = "Operator, Data scientist"
    contributing_institutions_role_vocabulary = "http://vocab.nerc.ac.uk/collection/W08/current/"
    uri = ds_all.uuid
    uri_comment = "UUID"
    web_link = "https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.nodc:0111844"
    comment = "history: " + ds_all.history
    start_date = time_coverage_start
    date_created = ds_all.date_created.replace('_', '').replace(':', '').rstrip('Z').rstrip('Z').replace('-','')
    date_modified = datetime.now().strftime('%Y%m%dT%H%M%S')
    featureType = "trajectory"
    Conventions = "CF-1.10,OG-1.0"
    landstation_version = ds_all.base_station_version + ds_all.base_station_micro_version
    glider_firmware_version = ds_all.seaglider_software_version
    rtqc_method = "No QC applied"
    rtqc_method_doi = "n/a"
    doi = "none yet"
    data_url = ""

    attr_to_add = {
        "title": title,
        "platform": platform, 
        "platform_vocabulary": platform_vocabulary,
        "id": id,
        "contributor_email": contributor_email,
        "contributor_role_vocabulary": contributor_role_vocabulary,
        "contributing_institutions": contributing_institutions,
        "contributing_institutions_vocabulary": contributing_institutions_vocabulary,
        "contributing_institutions_role": contributing_institutions_role,
        "contributing_institutions_role_vocabulary": contributing_institutions_role_vocabulary,
        "uri": uri,
        "uri_comment": uri_comment,
        "web_link": web_link,
        "comment": comment,
        "start_date": start_date,
        "featureType": featureType,
        "landstation_version": landstation_version,
        "glider_firmware_version": glider_firmware_version,
        "rtqc_method": rtqc_method,
        "rtqc_method_doi": rtqc_method_doi,
        "doi": doi,
        "data_url": data_url,
    }

    attr_to_change = {
        "time_coverage_start": time_coverage_start,
        "time_coverage_end": time_coverage_end,
        "Conventions": Conventions,
        "date_created": date_created,
        "date_modified": date_modified,
        "contributor_name": contributor_name,
        "contributor_role": contributor_role,
    }

    attr_as_is = [
        "naming_authority",
        "project",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_vertical_min",
        "geospatial_vertical_max",
        "license",
        "keywords",
        "keywords_vocabulary",
        "file_version",
        "acknowledgment",
        "date_created",
        "disclaimer",
    ]


    # After changing attributes
    attr_to_remove = [
        "summary",
        "history",
        "time_coverage_resolution",
        "geospatial_lat_units",
        "geospatial_lon_units",
        "geospatial_vertical_units",
        "geospatial_vertical_positive",
        "geospatial_vertical_resolution",
        "geospatial_lat_resolution",
        "geospatial_lon_resolution",
        "creator_name",
        "creator_email",
        "Metadata_Conventions",
    ]


    return attr_to_add, attr_as_is, attr_to_change, attr_to_remove


def modify_attributes(ds, attr_to_add, attr_as_is, attr_to_change, attr_to_remove):

    # Define the order of attributes
    ordered_attributes = [
        "title", "platform", "platform_vocabulary", "id", "naming_authority", 
        "institution", "geospatial_lat_min", "geospatial_lat_max", 
        "geospatial_lon_min", "geospatial_lon_max", "geospatial_vertical_min", 
        "geospatial_vertical_max", "time_coverage_start", "time_coverage_end", 
        "site", "project", "contributor_name", "contributor_email", 
        "contributor_role", "contributor_role_vocabulary", "uri", "data_url", 
        "doi", "rtqc_method", "rtqc_method_doi", "web_link", "comment", 
        "start_date", "date_created", "featureType", "Conventions"
    ]
    # Retain specified attributes
    new_attrs = {key: ds.attrs[key] for key in attr_as_is if key in ds.attrs}

    # Change specified attributes
    for key, value in attr_to_change.items():
        new_attrs[key] = value

    # Add new attributes
    for key, value in attr_to_add.items():
        if key not in new_attrs:
            new_attrs[key] = value

    # Remove specified attributes
    for key in attr_to_remove:
        if key in new_attrs:
            del new_attrs[key]

    ds.attrs = new_attrs

    # Add the rest of the attributes that are present in the dataset but not in the ordered list
    for attr in ds.attrs:
        if attr not in ordered_attributes:
            ordered_attributes.append(attr)

    # Reorder the attributes in ds_new_att according to ordered_attributes
    new_attrs = {attr: ds.attrs[attr] for attr in ordered_attributes if attr in ds.attrs}
    for attr in ds.attrs:
        if attr not in new_attrs:
            new_attrs[attr] = ds.attrs[attr]

    ds.attrs = new_attrs
    return ds

if __name__ == "__main__":
    dsn = xr.open_dataset(
        "/data/data_l0_pyglider/nrt/SEA76/M19/timeseries/mission_timeseries.nc",
    )
    dsn = standardise_og10(dsn)
    dsn = convert_to_og1(dsn)
    dsn.to_netcdf("new.nc")

def convert_to_og1(ds, num_vals=None):
    """
    Converts a given dataset to the OG1 format, applying specific variable names, units, and attributes as per the OG1 vocabulary and standards.

    This function is based on an example by Jen Seva (https://github.com/OceanGlidersCommunity/OG-format-user-manual/pull/136/files) and uses variable names from the OG1 vocabulary (https://vocab.nerc.ac.uk/collection/OG1/current/) and units from collection P07 (http://vocab.nerc.ac.uk/collection/P07/current/).

    The function processes the dataset, including handling quality control variables, setting coordinates, adding GPS information, and assigning various metadata attributes. It also adds sensor information and encodes times in the OG1 format.

    Parameters
    ----------
    :ds: xarray.Dataset
        The input dataset to convert.
    :num_vals: int, optional
        An optional argument to subset the input dataset to the first num_vals values. Default is None, which means no subsetting.
    Return
    ------
    dsa (xarray.Dataset) -    The converted dataset in OG1 format.
    
    Based on example by Jen Seva https://github.com/OceanGlidersCommunity/OG-format-user-manual/pull/136/files
    Using variable names from OG1 vocab https://vocab.nerc.ac.uk/collection/OG1/current/
    Using units from collection P07 http://vocab.nerc.ac.uk/collection/P07/current/
    e.g. mass_concentration_of_chlorophyll_a_in_sea_water from https://vocab.nerc.ac.uk/collection/P07/current/CF14N7/
    """
    dsa = xr.Dataset()
    for var_name in list(ds) + list(ds.coords):
        if "_QC" in var_name:
            continue
        dsa[var_name] = (
            "N_MEASUREMENTS",
            ds[var_name].values[:num_vals],
            ds[var_name].attrs,
        )
        qc_name = f"{var_name}_QC"
        if qc_name in list(ds):
            dsa[qc_name] = (
                "N_MEASUREMENTS",
                ds[qc_name].values[:num_vals].astype("int8"),
                ds[qc_name].attrs,
            )
            dsa[qc_name].attrs["long_name"] = (
                f'{dsa[var_name].attrs["long_name"]} Quality Flag'
            )
            dsa[qc_name].attrs["standard_name"] = "status_flag"
            dsa[qc_name].attrs["flag_values"] = np.array((1, 2, 3, 4, 9)).astype("int8")
            dsa[qc_name].attrs["flag_meanings"] = "GOOD UNKNOWN SUSPECT FAIL MISSING"
            dsa[var_name].attrs["ancillary_variables"] = qc_name
    if "time" in str(dsa.TIME.dtype):
        var_name = "TIME"
        dsa[var_name].values = dsa[var_name].values.astype(float)
        if np.nanmean(dsa[var_name].values) > 1e12:
            dsa[var_name].values = dsa[var_name].values / 1e9
    dsa = dsa.set_coords(("TIME", "LATITUDE", "LONGITUDE", "DEPTH"))
    for vname in ["LATITUDE", "LONGITUDE", "TIME"]:
        dsa[f"{vname}_GPS"] = dsa[vname].copy()
        dsa[f"{vname}_GPS"].values[dsa["nav_state"].values != 119] = np.nan
        dsa[f"{vname}_GPS"].attrs["long_name"] = f"{vname.lower()} of each GPS location"
    dsa["LATITUDE_GPS"].attrs["URI"] = (
        "https://vocab.nerc.ac.uk/collection/OG1/current/LAT_GPS/"
    )
    dsa["LONGITUDE_GPS"].attrs["URI"] = (
        "https://vocab.nerc.ac.uk/collection/OG1/current/LON_GPS/"
    )
    seaex_phase = dsa["nav_state"].values
    standard_phase = np.zeros(len(seaex_phase)).astype(int)
    standard_phase[seaex_phase == 115] = 3
    standard_phase[seaex_phase == 116] = 3
    standard_phase[seaex_phase == 119] = 3
    standard_phase[seaex_phase == 110] = 5
    standard_phase[seaex_phase == 118] = 5
    standard_phase[seaex_phase == 100] = 2
    standard_phase[seaex_phase == 117] = 1
    standard_phase[seaex_phase == 123] = 4
    standard_phase[seaex_phase == 124] = 4
    dsa["PHASE"] = xr.DataArray(
        standard_phase,
        coords=dsa["LATITUDE"].coords,
        attrs={
            "long_name": "behavior of the glider at sea",
            "phase_vocabulary": "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md",
        },
    )
    ds, dsa = add_sensors(ds, dsa)
    attrs = ds.attrs
    ts = pd.to_datetime(ds.time_coverage_start).strftime("%Y%m%dT%H%M")
    if "delayed" in ds.attrs["dataset_id"]:
        postscript = "delayed"
    else:
        postscript = "R"
    attrs["id"] = f"sea{str(attrs['glider_serial']).zfill(3)}_{ts}_{postscript}"
    attrs["title"] = "OceanGliders example file for SeaExplorer data"
    attrs["platform"] = "sub-surface gliders"
    attrs["platform_vocabulary"] = "https://vocab.nerc.ac.uk/collection/L06/current/27/"
    attrs["contributor_email"] = (
        "callum.rollo@voiceoftheocean.org, louise.biddle@voiceoftheocean.org, , , , , , "
    )
    attrs["contributor_role_vocabulary"] = "https://vocab.nerc.ac.uk/collection/W08/"
    attrs["contributor_role"] = (
        "Data scientist, PI, Operator, Operator, Operator, Operator, Operator, Operator,"
    )
    attrs["contributing_institutions"] = "Voice of the Ocean Foundation"
    attrs["contributing_institutions_role"] = "Operator"
    attrs["contributing_institutions_role_vocabulary"] = (
        "https://vocab.nerc.ac.uk/collection/W08/current/"
    )
    attrs["date_modified"] = attrs["date_created"]
    attrs["agency"] = "Voice of the Ocean"
    attrs["agency_role"] = "contact point"
    attrs["agency_role_vocabulary"] = "https://vocab.nerc.ac.uk/collection/C86/current/"
    attrs["data_url"] = (
        f"https://erddap.observations.voiceoftheocean.org/erddap/tabledap/{attrs['dataset_id']}"
    )
    attrs["rtqc_method"] = "IOOS QC QARTOD https://github.com/ioos/ioos_qc"
    attrs["rtqc_method_doi"] = "None"
    attrs["featureType"] = "trajectory"
    attrs["Conventions"] = "CF-1.10, OG-1.0"
    if num_vals:
        attrs["comment"] = (
            f"Dataset for demonstration purposes only. Original dataset truncated to {num_vals} values for the sake of simplicity"
        )
    attrs["start_date"] = attrs["time_coverage_start"]
    dsa.attrs = attrs
    dsa["TRAJECTORY"] = xr.DataArray(
        ds.attrs["id"],
        attrs={"cf_role": "trajectory_id", "long_name": "trajectory name"},
    )
    dsa["WMO_IDENTIFIER"] = xr.DataArray(
        ds.attrs["wmo_id"],
        attrs={"long_name": "wmo id"},
    )
    dsa["PLATFORM_MODEL"] = xr.DataArray(
        ds.attrs["glider_model"],
        attrs={
            "long_name": "model of the glider",
            "platform_model_vocabulary": "None",
        },
    )
    dsa["PLATFORM_SERIAL_NUMBER"] = xr.DataArray(
        f"sea{ds.attrs['glider_serial'].zfill(3)}",
        attrs={"long_name": "glider serial number"},
    )
    dsa["DEPLOYMENT_TIME"] = np.nanmin(dsa.TIME.values)
    dsa["DEPLOYMENT_TIME"].attrs = {
        "long_name": "date of deployment",
        "standard_name": "time",
        "units": "seconds since 1970-01-01T00:00:00Z",
        "calendar": "gregorian",
    }
    dsa["DEPLOYMENT_LATITUDE"] = dsa.LATITUDE.values[0]
    dsa["DEPLOYMENT_LATITUDE"].attrs = {"long_name": "latitude of deployment"}
    dsa["DEPLOYMENT_LONGITUDE"] = dsa.LONGITUDE.values[0]
    dsa["DEPLOYMENT_LONGITUDE"].attrs = {"long_name": "longitude of deployment"}
    dsa = encode_times_og1(dsa)
#    dsa = set_best_dtype(dsa)
    return dsa

def standardise_og10(ds):
    """
    Standardizes the given xarray Dataset according to predefined vocabularies.

    This function processes the input Dataset `ds` by renaming variables based on
    a predefined vocabulary and adding quality control (QC) variables where applicable.
    It also ensures that the attributes of the original variables are preserved and
    assigns the best data types to the resulting Dataset.

    Parameters
    ----------
    ds (xarray.Dataset): The input Dataset to be standardized.

    Returns
    -------
    xarray.Dataset: A new Dataset with standardized variable names and attributes.

    Notes
    -----
    - Variables with "qc" in their names are skipped.
    - If a variable name is found in the predefined vocabulary, it is renamed and
      its attributes are updated accordingly.
    - QC variables are added with the suffix "_QC" and linked to their corresponding
      variables via the "ancillary_variables" attribute.
    - Variables not found in the vocabulary are added as-is, and a log message is
      generated for those not in `vars_as_is`.

    Raises:
    - Any exceptions raised by the `set_best_dtype` function.
    """
    dsa = xr.Dataset()
    dsa.attrs = ds.attrs

    ds_renamed = ds.rename_dims(vocabularies.dims_rename_dict)
#    ds_renamed = ds_renamed.rename_vars(vocabularies.coords_rename_dict)
#    ds_renamed = ds_renamed.rename_vars(vocabularies.vars_rename_dict)
    vars_to_keep = set(vocabularies.vars_rename_dict.values())

    # Rename dimensions based on the vocabularies.dims_rename_dict
    for dim_name, size in ds_renamed.dims.items():
        if dim_name not in dsa.dims:
            dsa = dsa.assign_coords({dim_name: np.arange(size)})
    # Rename coordinates based on the vocabularies.coords_rename_dict
    for coord_name in ds_renamed.dims.items():
        if coord_name in vocabularies.coords_rename_dict:
            new_coord_name = vocabularies.coords_rename_dict[coord_name]
            dsa = dsa.rename({coord_name: new_coord_name})

    for var_name in list(ds) + list(ds.coords):
        if "qc" in var_name:
            continue
        if var_name in vocabularies.standard_names.keys():
            print(var_name)
            name = vocabularies.standard_names[var_name]
            dsa[name] = ("time", ds[var_name].values, vocabularies.vocab_attrs[name])
            for key, val in ds[var_name].attrs.items():
                if key not in dsa[name].attrs.keys():
                    dsa[name].attrs[key] = val
            qc_name = f"{var_name}_qc"
            if qc_name in list(ds):
                dsa[f"{name}_QC"] = ("time", ds[qc_name].values, ds[qc_name].attrs)
                dsa[name].attrs["ancillary_variables"] = f"{name}_QC"
        else:
#           Note: this differs from the original standardise_og10 function
#            dsa[var_name] = ("time", ds[var_name].values, ds[var_name].attrs)
            if var_name not in vars_as_is:
                _log.error(f"variable {var_name} not translated.")
                
    # dsa = set_best_dtype(dsa) - this changes data types - skipping for now
    return dsa

##-----------------------------------------------------------------------------------------
## Editing variables
##-----------------------------------------------------------------------------------------
vars_as_is = [
    "altimeter",
    "nav_resource",
    "angular_cmd",
    "angular_pos",
    "ballast_cmd",
    "ballast_pos",
    "dead_reckoning",
    "declination",
    "desired_heading",
    "dive_num",
    "internal_pressure",
    "internal_temperature",
    "linear_cmd",
    "linear_pos",
    "security_level",
    "voltage",
    "distance_over_ground",
#    "ad2cp_beam1_cell_number1",
#    "ad2cp_beam2_cell_number1",
#    "ad2cp_beam3_cell_number1",
#    "ad2cp_beam4_cell_number1",
#    "vertical_distance_to_seafloor",
#    "profile_direction",
    "profile_num",
    "nav_state",
]

def create_renamed_dataset(ds):
    from seagliderOG1 import vocabularies

    # Apply renaming using the dictionaries
    ds_renamed = ds.rename_dims(vocabularies.dims_rename_dict)
    ds_renamed = ds_renamed.rename_vars(vocabularies.coords_rename_dict)
    ds_renamed = ds_renamed.rename_vars(vocabularies.vars_rename_dict)

    # Remove variables not in vars_rename_dict().values
    vars_to_keep = set(vocabularies.vars_rename_dict.values())
    ds_renamed = ds_renamed[vars_to_keep]

    # Check if PROFILE_NUMBER is present as a variable
    if 'PROFILE_NUMBER' not in ds_renamed.variables:
        ds_renamed = assign_profile_number(ds_renamed)
    if 'PHASE' not in ds_renamed.variables:
        ds_renamed = assign_phase(ds_renamed)

    # Cycle through the variables within ds_renamed and ds_renamed.coords
    for name in list(ds_renamed):
        if name in vocabularies.standard_names.values():
            for key, val in vocabularies.vocab_attrs[name].items():
                if key not in ds_renamed[name].attrs.keys():
                    ds_renamed[name].attrs[key] = val

    # Update the attributes time_coverage_start and time_coverage_end
    time_coverage_start = pd.to_datetime(ds_renamed.TIME.values[0]).strftime("%Y%m%dT%H%M%S")
    time_coverage_end = pd.to_datetime(ds_renamed.TIME.values[-1]).strftime("%Y%m%dT%H%M%S")
    ds_renamed.attrs["time_coverage_start"] = time_coverage_start
    ds_renamed.attrs["time_coverage_end"] = time_coverage_end

    # Update the attribute date_created to today's date
    ds_renamed.attrs["date_created"] = datetime.utcnow().strftime('%Y%m%dT%H%M%S')

    # Check whether time_coverage_start is before start_date.  If so, then update start_date
    if time_coverage_start < ds_renamed.attrs["start_date"]:
        ds_renamed.attrs["start_date"] = time_coverage_start

    return ds_renamed



##-----------------------------------------------------------------------------------------
## Calculations for new variables
##-----------------------------------------------------------------------------------------



