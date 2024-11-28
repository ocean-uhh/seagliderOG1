# Based on https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/utilities/utilities.py
import re
import numpy as np
import pandas as pd
import logging
import subprocess
import datetime
import xarray as xr
#from votoutils.upload.sync_functions import sync_script_dir

_log = logging.getLogger(__name__)


def _validate_coords(ds1):
    """
    Validates and assigns coordinates to the given xarray Dataset.
    Parameters:
    ds1 (xarray.Dataset): The dataset to validate and assign coordinates to. 
                          It is expected to have an 'id' attribute and may contain 
                          'longitude', 'latitude', 'ctd_time', and 'ctd_depth' variables.
    Returns:
    xarray.Dataset: The validated dataset with necessary coordinates assigned. 
                    If 'ctd_time' variable is missing, an empty dataset is returned.
    Notes:
    - If 'longitude' or 'latitude' coordinates are missing, they are added as NaNs with the length of 'sg_data_point'.
    - If 'ctd_time' variable exists but 'ctd_time' or 'ctd_depth' coordinates are missing, they are assigned from the variable.
    - If 'ctd_time' variable is missing, an empty dataset is returned.
    - Prints messages indicating the actions taken for missing coordinates or variables.

    Based on: https://github.com/pydata/xarray/issues/3743
    """

    id = ds1.attrs['id']
    if 'longitude' not in ds1.coords:
        ds1 = ds1.assign_coords(longitude=("sg_data_point", [float('nan')] * ds1.dims['sg_data_point']))
        print(f'{id}: No coord longitude - adding as NaNs to length of sg_data_point')
    if 'latitude' not in ds1.coords:
        ds1 = ds1.assign_coords(latitude=("sg_data_point", [float('nan')] * ds1.dims['sg_data_point']))
        print(f'{id}: No coord latitude - adding as NaNs to length of sg_data_point')
    if 'ctd_time' in ds1.variables:
        if 'ctd_time' not in ds1.coords:
            ds1 = ds1.assign_coords(ctd_time=("sg_data_point", ds1['ctd_time'].values))
            print(f'{id}: No coord ctd_time, but exists as variable - assigning coord from variable')
        if 'ctd_depth' not in ds1.coords:
            ds1 = ds1.assign_coords(ctd_depth=("sg_data_point", ds1['ctd_depth'].values))
            print(f'{id}: No coord ctd_depth, but exists as variable - assigning coord from variable')
    else:
        print(f'{id}: !!! No variable ctd_time - returning an empty dataset')

        ds1 = xr.Dataset()
    return ds1


def _validate_dims(ds):
    dim_name = list(ds.dims)[0] # Should be 'N_MEASUREMENTS' for OG1
    if dim_name != 'N_MEASUREMENTS':
        raise ValueError(f"Dimension name '{dim_name}' is not 'N_MEASUREMENTS'.")
    

def _parse_calibcomm(calibcomm):
    if 'calibration' in calibcomm.values.item().decode('utf-8'):

        cal_date = calibcomm.values.item().decode('utf-8')
        print(cal_date)
        cal_date = cal_date.split('calibration')[-1].strip()
        cal_date = cal_date.replace(' ', '')
        print(cal_date)
        cal_date_YYYYmmDD = datetime.datetime.strptime(cal_date, '%d%b%y').strftime('%Y%m%d')
    else:   
        cal_date_YYYYmmDD = 'Unknown'
    if 's/n' in calibcomm.values.item().decode('utf-8'):
        serial_match = re.search(r's/n\s*(\d+)', calibcomm.values.item().decode('utf-8'))
        serial_number = serial_match.group(0).replace('s/n  ', '').strip()
    else:
        serial_number = 'Unknown'
    print(serial_number)

    return cal_date_YYYYmmDD, serial_number

def _clean_anc_vars_list(ancillary_variables_str):
    ancillary_variables_str = re.sub(r"(\w)(sg_cal)", r"\1 \2", ancillary_variables_str)
    ancilliary_vars_list = ancillary_variables_str.split()
    ancilliary_vars_list = [var.replace('sg_cal_', '') for var in ancilliary_vars_list]
    return ancilliary_vars_list

def _assign_calval(sg_cal, anc_var_list):
    calval = {}
    for anc_var in anc_var_list:
        var_value = sg_cal[anc_var].values.item()
        calval[anc_var] = var_value
    return calval