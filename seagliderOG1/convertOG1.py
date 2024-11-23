import numpy as np
import xarray as xr
from seagliderOG1 import vocabularies
from seagliderOG1 import readers, writers, utilities, tools
import gsw
import logging
from datetime import datetime
import os

_log = logging.getLogger(__name__)

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
            - Convert QC flags to int8.
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
    newdim = vocabularies.dims_rename_dict['sg_data_point']

    # Check if the dataset has 'LONGITUDE' as a coordinate
    ds1 = utilities._validate_coords(ds1)
    if ds1 is None or len(ds1.variables) == 0:
        return xr.Dataset(), [], xr.Dataset(), xr.Dataset(), xr.Dataset()

    # Handle and split the inputs.
    #--------------------------------
    # Extract the dive number from the attributes
    divenum = ds1.attrs['dive_number']
    # Split the dataset by unique dimensions
    split_ds = tools.split_by_unique_dims(ds1)
    ds = split_ds[('sg_data_point',)]
    # Extract the gps_info from the split dataset
    gps_info = split_ds[('gps_info',)]
    # Extract variables starting with 'sg_cal'
    # These will be needed to set attributes for the xarray dataset
    sg_cal, dc_log, dc_other = extract_variables(split_ds[()])

    # Repeat the value of dc_other.depth_avg_curr_east to the length of the dataset
    var_keep = ['depth_avg_curr_east', 'depth_avg_curr_north','depth_avg_curr_qc']
    for var in var_keep:
        if var in dc_other:
            v1 = dc_other[var].values
            vector_v = np.full(len(ds['longitude']), v1)
            ds[var] = (['sg_data_point'], vector_v, dc_other[var].attrs)

    # Rename variables and attributes to OG1 vocabulary
    #-------------------------------------------------------------------
    # Use variables with dimension 'sg_data_point'
    # Must be after split_ds
    dsa = standardise_OG10(ds)

    # Add new variables to the dataset (GPS, divenum, PROFILE_NUMBER, PHASE)
    #-----------------------------------------------------------------------
    # Add the gps_info to the dataset
    # Must be after split_by_unique_dims and after rename_dimensions
    ds_new = add_gps_info_to_dataset(dsa, gps_info)
    # Add the variable divenum.  Assumes present in the attributes of the original dataset
    ds_new = tools.add_dive_number(ds_new, divenum)
    # Add the profile number (odd for dives, even for ascents)
    # Must be run after adding divenum
    ds_new = tools.assign_profile_number(ds_new, 'divenum')
    # Assign the phase of the dive (must be after adding divenum)
    ds_new = tools.assign_phase(ds_new)
    # Assign DEPTH_Z to the dataset where positive is up.
    ds_new = tools.calc_Z(ds_new)

    # Gather sensors
    sensor_names = ['wlbb2f', 'sbe41']
    ds_sensor = xr.Dataset()
    for sensor in sensor_names:
        if sensor in dc_other:
            ds_sensor[sensor] = dc_other[sensor]
    ds_new = tools.add_sensor_to_dataset(ds_new, ds_sensor, sg_cal)

    # Remove variables matching vocabularies.vars_to_remove and also 'TIME_GPS'
    vars_to_remove = vocabularies.vars_to_remove + ['TIME_GPS']
    ds_new = ds_new.drop_vars([var for var in vars_to_remove if var in ds_new.variables])
    attr_warnings = ''
    return ds_new, attr_warnings, sg_cal, dc_other, dc_log

def standardise_OG10(ds, unit_format=vocabularies.unit_str_format):
    """
    Standardizes the dataset to OG1 format by renaming dimensions, variables, and assigning attributes.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset to be standardized.

    Returns
    -------
    xarray.Dataset: The standardized dataset.
    """
    dsa = xr.Dataset()
    dsa.attrs = ds.attrs
    suffixes = ['', '_qc', '_raw', '_raw_qc']

    # Set new dimension name
    newdim = vocabularies.dims_rename_dict['sg_data_point']

    # Rename variables according to the OG1 vocabulary
    for orig_varname in list(ds) + list(ds.coords):
        if '_qc' in orig_varname.lower():
            continue
        if orig_varname in vocabularies.standard_names.keys(): 
            OG1_name = vocabularies.standard_names[orig_varname]
            var_values = ds[orig_varname].values
            # Reformat units and convert units if necessary
            if 'units' in ds[orig_varname].attrs:
                orig_unit = tools.reformat_units_var(ds, orig_varname, unit_format)
                if 'units' in vocabularies.vocab_attrs[OG1_name]:
                    new_unit = vocabularies.vocab_attrs[OG1_name].get('units')
                    if orig_unit != new_unit:
                        var_values = tools.convert_units_var(var_values, orig_unit, new_unit)
            dsa[OG1_name] = ([newdim], var_values, vocabularies.vocab_attrs[OG1_name])
            # Pass attributes that aren't in standard OG1 vocab_attrs
            for key, val in ds[orig_varname].attrs.items():
                if key not in dsa[OG1_name].attrs.keys():
                    dsa[OG1_name].attrs[key] = val

            # Add QC variables if they exist
            for suffix in suffixes:
                variant = orig_varname + suffix
                variant_OG1 = OG1_name + suffix.upper()
                if variant in list(ds):
                    dsa[variant_OG1] = ([newdim], ds[variant].values, ds[variant].attrs)
                    # Should only be the root for *_qc variables
                    if '_qc' in variant:
                        # Convert QC flags to int8 and add attributes
                        dsa = tools.convert_qc_flags(dsa, variant_OG1)
        else:
            dsa[orig_varname] = ([newdim], ds[orig_varname].values, ds[orig_varname].attrs)
            if orig_varname not in vocabularies.vars_as_is:
                _log.warning(f"Variable '{orig_varname}' not in OG1 vocabulary.")
                
    # Assign coordinates
    dsa = dsa.set_coords(['LONGITUDE', 'LATITUDE', 'DEPTH', 'TIME'])
    dsa = tools.set_best_dtype(dsa)
    return dsa

# Deprecated.  Now replaced by functionality in standardise_OG10
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



# Deprecated - currently just uses the standard vocabularies.vocab_attrs but could clobber existing attributes
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
    # Set new dimension name
    newdim = vocabularies.dims_rename_dict['sg_data_point']
    # Create a new dataset with GPS information
    gps_ds = xr.Dataset(
        {
            'LONGITUDE': ([newdim], gps_ds['log_gps_lon'].values),
        },
        coords={
            'LATITUDE': ([newdim], gps_ds['log_gps_lat'].values),
            'TIME': ([newdim], gps_ds['log_gps_time'].values),
            'DEPTH': ([newdim], np.full(len(gps_ds['log_gps_lat']), 0))
        }
    )
    gps_ds = gps_ds.set_coords('LONGITUDE')

    gps_ds['LATITUDE_GPS'] = ([newdim], gps_ds.LATITUDE.values, vocabularies.vocab_attrs['LATITUDE_GPS'], {'dtype': ds['LATITUDE'].dtype})
    gps_ds['LONGITUDE_GPS'] = ([newdim], gps_ds.LONGITUDE.values, vocabularies.vocab_attrs['LONGITUDE_GPS'], {'dtype': ds['LONGITUDE'].dtype})
    gps_ds['TIME_GPS'] = ([newdim], gps_ds.TIME.values, vocabularies.vocab_attrs['TIME_GPS'], {'dtype': ds['TIME'].dtype})

    
#    gps_ds['']
    # Add the variables LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS to the dataset
#    gps_ds['LATITUDE_GPS'] = (['N_MEASUREMENTS'], gps_ds.LATITUDE.values, {'dtype': ds['LATITUDE'].dtype})
#    gps_ds['LONGITUDE_GPS'] = (['N_MEASUREMENTS'], gps_ds.LONGITUDE.values, {'dtype': ds['LONGITUDE'].dtype})
#    gps_ds['TIME_GPS'] = (['N_MEASUREMENTS'], gps_ds.TIME.values, {'dtype': ds['TIME'].dtype})

    # Add attributes


    # Concatenate ds and gps_ds
    datasets = []
    datasets.append(ds)
    datasets.append(gps_ds)
    ds_new = xr.concat(datasets, dim=newdim)
    ds_new = ds_new.sortby('TIME')

    return ds_new


##-----------------------------------------------------------------------------------------
## Editing attributes
##-----------------------------------------------------------------------------------------
def update_dataset_attributes(ds, contrib_to_append):
    """
    Updates the attributes of the dataset based on the provided attribute input.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset whose attributes need to be updated.
    vocabularies (module): A module containing attribute configurations such as global_attrs['attr_as_is'], attr_to_add, attr_to_rename, and vocabularies.order_of_attr.

    Returns
    -------
    xarray.Dataset: The dataset with updated attributes.
    """
    attr_as_is = vocabularies.global_attrs['attr_as_is']
    attr_to_add = vocabularies.global_attrs['attr_to_add']
    attr_to_rename = vocabularies.global_attrs['attr_to_rename']
    order_of_attr = vocabularies.order_of_attr

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

    # Reorder attributes according to vocabularies.order_of_attr
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

def extract_attr_to_keep(ds1, attr_as_is=vocabularies.global_attrs['attr_as_is']):
    retained_attrs = {}

    # Retain attributes based on attr_as_is
    for attr in attr_as_is:
        if attr in ds1.attrs:
            retained_attrs[attr] = ds1.attrs[attr]

    return retained_attrs

def extract_attr_to_rename(ds1, attr_to_rename=vocabularies.global_attrs['attr_to_rename']):
    renamed_attrs = {}
    # Rename attributes based on values_to_rename
    for new_attr, old_attr in attr_to_rename.items():
        if old_attr in ds1.attrs:
            renamed_attrs[new_attr] = ds1.attrs[old_attr]
    
    return renamed_attrs


def process_and_save_data(input_location, save=False, output_dir='../data', run_quietly=True):
    """
    Processes and saves data from the specified input location.
    This function loads and concatenates datasets from the server, converts them to OG1 format,
    and saves the resulting dataset to a NetCDF file. If the file already exists, the function
    will prompt the user to decide whether to overwrite it or not.
    
    Parameters:
    input_location (str): The location of the input data to be processed.
    save (bool): Whether to save the processed dataset to a file. Default is False.
    output_dir (str): The directory where the output file will be saved. Default is '../data'.

    Returns:
    xarray.Dataset: The processed dataset.
    """

    # Load and concatenate all datasets from the server
    list_datasets = readers.read_basestation(input_location)
    
    # Convert the list of datasets to OG1
    ds1 = convert_to_OG1(list_datasets[-1])
    output_file = os.path.join(output_dir, ds1.attrs['id'] + '.nc')
    
    # Check if the file exists and delete it if it does
    if os.path.exists(output_file):
        if run_quietly:
            user_input = 'no'
        else:
            user_input = input(f"File {output_file} already exists. Do you want to re-run and overwrite it? (yes/no): ")

        if user_input.lower() != 'yes':
            print(f"File {output_file} already exists. Exiting the process.")
            ds_all = xr.open_dataset(output_file)
            return ds_all
        elif user_input.lower() == 'yes':
            ds_all = convert_to_OG1(list_datasets)
            os.remove(output_file)
            if save:
                writers.save_dataset(ds_all, output_file)
    else:
        print('Running the directory:', input_location)
        ds_all = convert_to_OG1(list_datasets)
        if save:
            writers.save_dataset(ds_all, output_file)

    return ds_all