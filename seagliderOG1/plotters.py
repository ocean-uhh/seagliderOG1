import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt

def plot_profile_depth(data):
    """
    Plots the profile depth (ctd_depth) as a function of time (ctd_time).
    Reduces the total number of points to be less than 100,000.
    
    Parameters:
    data (pd.DataFrame or xr.Dataset): The input data containing 'ctd_depth' and 'ctd_time'.
    """
    if isinstance(data, pd.DataFrame):
        ctd_time = data['ctd_time']
        ctd_depth = data['ctd_depth']
    elif isinstance(data, xr.Dataset):
        ctd_time = data['ctd_time'].values
        ctd_depth = data['ctd_depth'].values
    else:
        raise TypeError("Input data must be a pandas DataFrame or xarray Dataset")
    
    # Reduce the number of points
    if len(ctd_time) > 100000:
        indices = np.linspace(0, len(ctd_time) - 1, 100000).astype(int)
        ctd_time = ctd_time[indices]
        ctd_depth = ctd_depth[indices]
    
    plt.figure(figsize=(10, 6))
    plt.plot(ctd_time, ctd_depth, label='Profile Depth')
    plt.ylabel('Depth')
    plt.title('Profile Depth as a Function of Time')
    plt.legend()
    plt.grid(True)

    # Set y-axis limits to be tight around the data plotted to the nearest 10 meters
    y_min = np.floor(ctd_depth.min() / 10) * 10
    y_max = np.ceil(ctd_depth.max() / 10) * 10
    plt.ylim([y_min, y_max])
    plt.gca().invert_yaxis()

    plt.gca().xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%b-%d'))

    # Add the year or year range to the xlabel
    start_year = pd.to_datetime(ctd_time.min()).year
    end_year = pd.to_datetime(ctd_time.max()).year
    if start_year == end_year:
        plt.xlabel(f'Time ({start_year})')
    else:
        plt.xlabel(f'Time ({start_year}-{end_year})')

    plt.show()

def show_variables(file):
    """
    Processes a list of files, extracts variable information from a selected file, 
    and returns a styled DataFrame with details about the variables.
    Parameters:
    files (list): A list of file paths to be processed.
    Returns:
    pandas.io.formats.style.Styler: A styled DataFrame containing the following columns:
        - dims: The dimension of the variable (or "string" if it is a string type).
        - name: The name of the variable.
        - units: The units of the variable (if available).
        - comment: Any additional comments about the variable (if available).
    Notes:
    - The function selects the middle file from the processed list of files to extract variable information.
    - The DataFrame is sorted by dimensions and variable names.
    - The DataFrame is styled for better readability.
    
    This is based on glidertools (https://github.com/GliderToolsCommunity/), glidertools/load/seaglider.py
    """
    from pandas import DataFrame
    from netCDF4 import Dataset

    print("information is based on file: {}".format(file))

    variables = Dataset(file).variables
    info = {}
    for i, key in enumerate(variables):
        var = variables[key]
        info[i] = {
            "name": key,
            "dims": var.dimensions[0] if len(var.dimensions) == 1 else "string",
            "units": "" if not hasattr(var, "units") else var.units,
            "comment": "" if not hasattr(var, "comment") else var.comment,
        }

    vars = DataFrame(info).T

    dim = vars.dims
    dim[dim.str.startswith("str")] = "string"
    vars["dims"] = dim

    vars = (
        vars.sort_values(["dims", "name"])
        .reset_index(drop=True)
        .loc[:, ["dims", "name", "units", "comment"]]
        .set_index("name")
        .style
    )

    return vars

def show_attributes(file):
    from pandas import DataFrame
    from netCDF4 import Dataset

    print("information is based on file: {}".format(file))

    rootgrp = Dataset(file, "r", format="NETCDF4")
    info = {}

    for i, key in enumerate(rootgrp.ncattrs()):
        info[i] = {
            "Attribute": key,
            "Value": getattr(rootgrp, key)
        }

    attrs = DataFrame(info).T

#    attrs = (
#        attrs.sort_values(["Index"])
#        .reset_index(drop=True)
#        .loc[:, ["Attribute", "Value"]]
#        .set_index("Attribute")
#        .style
#    )

    return attrs