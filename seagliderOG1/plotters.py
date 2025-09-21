"""Plotting and visualization functions for Seaglider data.

This module provides functions for plotting and inspecting Seaglider datasets,
including variable summaries, attribute displays, and depth profile visualizations.
"""

import numpy as np
import pandas as pd
import xarray as xr
from pandas import DataFrame

import matplotlib.pyplot as plt


##------------------------------------------------------------------------------------
## Views of the ds or nc file
##------------------------------------------------------------------------------------
def show_contents(data: str | xr.Dataset, content_type: str = "variables") -> pd.DataFrame:
    """Show contents of an xarray Dataset or a netCDF file.
    
    Wrapper function to display either variables or attributes from the dataset.

    Parameters
    ----------
    data : str or xarray.Dataset
        The input data, either a file path to a netCDF file or an xarray Dataset.
    content_type : str, optional
        The type of content to show, either 'variables' (or 'vars') or 'attributes' (or 'attrs').
        Default is 'variables'.

    Returns
    -------
    pandas.DataFrame
        A DataFrame with details about the variables or attributes.
        
    Raises
    ------
    TypeError
        If input data is not a file path or xarray Dataset.
    ValueError
        If content_type is not 'variables', 'vars', 'attributes', or 'attrs'.

    """
    if content_type in ["variables", "vars"]:
        if isinstance(data, str):
            return show_variables(data)
        elif isinstance(data, xr.Dataset):
            return show_variables(data)
        else:
            raise TypeError("Input data must be a file path (str) or an xarray Dataset")
    elif content_type in ["attributes", "attrs"]:
        if isinstance(data, str):
            return show_attributes(data)
        elif isinstance(data, xr.Dataset):
            return show_attributes(data)
        else:
            raise TypeError("Attributes can only be shown for netCDF files (str)")
    else:
        raise ValueError(
            "content_type must be either 'variables' (or 'vars') or 'attributes' (or 'attrs')"
        )


def show_variables(data: str | xr.Dataset) -> pd.DataFrame:
    """Process an xarray Dataset or netCDF file and extract variable information.
    
    Creates a styled DataFrame with comprehensive details about all variables
    in the dataset, including dimensions, units, comments, and data types.

    Parameters
    ----------
    data : str or xarray.Dataset
        The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns
    -------
    pandas.io.formats.style.Styler
        A styled DataFrame containing the following columns:
        - dims: The dimension of the variable (or "string" if it is a string type).
        - name: The name of the variable.
        - units: The units of the variable (if available).
        - comment: Any additional comments about the variable (if available).
        - standard_name: CF standard name (if available).
        - dtype: Data type of the variable.
        
    Raises
    ------
    TypeError
        If input data is not a file path or xarray Dataset.

    """
    from pandas import DataFrame
    from netCDF4 import Dataset

    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        dataset = Dataset(data)
        variables = dataset.variables
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        variables = data.variables
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")

    info = {}
    for i, key in enumerate(variables):
        var = variables[key]
        if isinstance(data, str):
            dims = var.dimensions[0] if len(var.dimensions) == 1 else "string"
            units = "" if not hasattr(var, "units") else var.units
            comment = "" if not hasattr(var, "comment") else var.comment
        else:
            dims = var.dims[0] if len(var.dims) == 1 else "string"
            units = var.attrs.get("units", "")
            comment = var.attrs.get("comment", "")

        info[i] = {
            "name": key,
            "dims": dims,
            "units": units,
            "comment": comment,
            "standard_name": var.attrs.get("standard_name", ""),
            "dtype": str(var.dtype) if isinstance(data, str) else str(var.data.dtype),
        }

    vars = DataFrame(info).T

    dim = vars.dims
    dim[dim.str.startswith("str")] = "string"
    vars["dims"] = dim

    vars = (
        vars.sort_values(["dims", "name"])
        .reset_index(drop=True)
        .loc[:, ["dims", "name", "units", "comment", "standard_name", "dtype"]]
        .set_index("name")
        .style
    )

    return vars


def show_attributes(data: str | xr.Dataset) -> pd.DataFrame:
    """Process an xarray Dataset or netCDF file and extract global attribute information.
    
    Creates a DataFrame with comprehensive details about all global attributes
    in the dataset, including their values and data types.

    Parameters
    ----------
    data : str or xarray.Dataset
        The input data, either a file path to a netCDF file or an xarray Dataset.

    Returns
    -------
    pandas.DataFrame
        A DataFrame containing the following columns:
        - Attribute: The name of the attribute.
        - Value: The value of the attribute.
        - DType: The data type of the attribute value.
        
    Raises
    ------
    TypeError
        If input data is not a file path or xarray Dataset.

    """
    from pandas import DataFrame
    from netCDF4 import Dataset

    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        rootgrp = Dataset(data, "r", format="NETCDF4")
        attributes = rootgrp.ncattrs()
        get_attr = lambda key: getattr(rootgrp, key)
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        attributes = data.attrs.keys()
        get_attr = lambda key: data.attrs[key]
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")

    info = {}
    for i, key in enumerate(attributes):
        dtype = type(get_attr(key)).__name__
        info[i] = {"Attribute": key, "Value": get_attr(key), "DType": dtype}

    attrs = DataFrame(info).T

    return attrs


def show_variables_by_dimension(data: str | xr.Dataset, dimension_name: str = "trajectory") -> pd.DataFrame:
    """Process dataset and extract variables filtered by a specific dimension.
    
    Creates a styled DataFrame showing only variables that have the specified
    dimension, useful for examining variables of a particular type.

    Parameters
    ----------
    data : str or xarray.Dataset
        The input data, either a file path to a netCDF file or an xarray Dataset.
    dimension_name : str, optional
        The name of the dimension to filter variables by. Default is "trajectory".

    Returns
    -------
    pandas.io.formats.style.Styler
        A styled DataFrame containing the following columns:
        - dims: The dimension of the variable (or "string" if it is a string type).
        - name: The name of the variable.
        - units: The units of the variable (if available).
        - comment: Any additional comments about the variable (if available).
        
    Raises
    ------
    TypeError
        If input data is not a file path or xarray Dataset.
    """
    if isinstance(data, str):
        print("information is based on file: {}".format(data))
        dataset = Dataset(data)
        variables = dataset.variables
    elif isinstance(data, xr.Dataset):
        print("information is based on xarray Dataset")
        variables = data.variables
    else:
        raise TypeError("Input data must be a file path (str) or an xarray Dataset")

    info = {}
    for i, key in enumerate(variables):
        var = variables[key]
        if isinstance(data, str):
            dims = var.dimensions[0] if len(var.dimensions) == 1 else "string"
            units = "" if not hasattr(var, "units") else var.units
            comment = "" if not hasattr(var, "comment") else var.comment
        else:
            dims = var.dims[0] if len(var.dims) == 1 else "string"
            units = var.attrs.get("units", "")
            comment = var.attrs.get("comment", "")

        if dims == dimension_name:
            info[i] = {
                "name": key,
                "dims": dims,
                "units": units,
                "comment": comment,
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


##----------------------------------------------------------------------------
## Sawtooth plots
##----------------------------------------------------------------------------
def plot_profile_depth(data: pd.DataFrame | xr.Dataset) -> None:
    """Plot profile depth as a function of time.
    
    Creates a time series plot of depth data with automatic point reduction
    for large datasets and proper axis formatting.

    Parameters
    ----------
    data : pandas.DataFrame or xarray.Dataset
        The input data containing depth and time variables. Should contain either
        'ctd_depth'/'ctd_time' or 'DEPTH'/'TIME' variables.
        
    Notes
    -----
    - Automatically reduces the total number of points to less than 100,000 for performance.
    - Inverts y-axis to show depth increasing downward.
    - Formats x-axis with month-day labels and adds year information.
    - Sets tight y-axis limits rounded to nearest 10 meters.
    
    Raises
    ------
    TypeError
        If input data is not a pandas DataFrame or xarray Dataset.
    KeyError
        If required time or depth variables are not found in the dataset.

    """
    if isinstance(data, pd.DataFrame):
        ctd_time = data["ctd_time"]
        ctd_depth = data["ctd_depth"]
    elif isinstance(data, xr.Dataset):
        if "ctd_time" in data.variables:
            ctd_time = data["ctd_time"].values
        elif "TIME" in data.variables:
            ctd_time = data["TIME"].values
        else:
            raise KeyError("Neither 'ctd_time' nor 'TIME' found in the dataset")

        if "ctd_depth" in data.variables:
            ctd_depth = data["ctd_depth"].values
        elif "DEPTH" in data.variables:
            ctd_depth = data["DEPTH"].values
        else:
            raise KeyError("Neither 'ctd_depth' nor 'DEPTH' found in the dataset")
    else:
        raise TypeError("Input data must be a pandas DataFrame or xarray Dataset")

    # Reduce the number of points
    if len(ctd_time) > 100000:
        indices = np.linspace(0, len(ctd_time) - 1, 100000).astype(int)
        ctd_time = ctd_time[indices]
        ctd_depth = ctd_depth[indices]

    plt.figure(figsize=(10, 6))
    plt.plot(ctd_time, ctd_depth, label="Profile Depth")
    plt.ylabel("Depth")
    plt.title("Profile Depth as a Function of Time")
    plt.legend()
    plt.grid(True)

    # Set y-axis limits to be tight around the data plotted to the nearest 10 meters
    y_min = np.floor(ctd_depth.min() / 10) * 10
    y_max = np.ceil(ctd_depth.max() / 10) * 10
    plt.ylim([y_min, y_max])
    plt.gca().invert_yaxis()

    plt.gca().xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%b-%d"))

    # Add the year or year range to the xlabel
    start_year = pd.to_datetime(ctd_time.min()).year
    end_year = pd.to_datetime(ctd_time.max()).year
    if start_year == end_year:
        plt.xlabel(f"Time ({start_year})")
    else:
        plt.xlabel(f"Time ({start_year}-{end_year})")

    plt.show()


def plot_depth_colored(data: pd.DataFrame | xr.Dataset, color_by: str | None = None, start_dive: int | None = None, end_dive: int | None = None) -> None:
    """Plot depth as a function of time with optional coloring and dive filtering.
    
    Creates a depth time series plot with optional color coding by another variable
    and filtering by dive number range.

    Parameters
    ----------
    data : pandas.DataFrame or xarray.Dataset
        The input data containing depth, time, and dive number variables.
        Should contain 'ctd_depth'/'DEPTH', 'ctd_time'/'TIME', and dive number variables.
    color_by : str, optional
        The variable name to color the plot by. If None, uses a simple line plot.
    start_dive : int, optional
        The starting dive number to filter the data. If None, no filtering applied.
    end_dive : int, optional
        The ending dive number to filter the data. If None, no filtering applied.
        
    Notes
    -----
    - Accepts dive number variables: 'dive_number', 'divenum', or 'dive_num'.
    - Uses scatter plot with colorbar when color_by is specified.
    - Inverts y-axis and formats time axis similar to plot_profile_depth.
    
    Raises
    ------
    TypeError
        If input data is not a pandas DataFrame or xarray Dataset.
    ValueError
        If no valid dive number variable is found in the dataset.

    """
    # Filter data by dive number if specified
    if "dive_number" in data.variables:
        divenum_str = "dive_number"
    elif "divenum" in data.variables:
        divenum_str = "divenum"
    elif "dive_num" in data.variables:
        divenum_str = "dive_num"
    else:
        raise ValueError("No valid dive number variable found in the dataset.")

    if start_dive is not None and end_dive is not None:
        if isinstance(data, pd.DataFrame):
            data = data[
                (data[divenum_str] >= start_dive) & (data[divenum_str] <= end_dive)
            ]
        elif isinstance(data, xr.Dataset):
            data = data.where(
                (data[divenum_str] >= start_dive) & (data[divenum_str] <= end_dive),
                drop=True,
            )
        else:
            raise TypeError("Input data must be a pandas DataFrame or xarray Dataset")

    # Identify vectors to be plotted
    if "ctd_time" in data:
        x_axis = data["ctd_time"]
    else:
        x_axis = data["TIME"]

    if "ctd_depth" in data:
        y_axis = data["ctd_depth"]
    else:
        y_axis = data["DEPTH"]

    if isinstance(data, pd.DataFrame):
        ctd_time = x_axis
        ctd_depth = y_axis
        color_data = data[color_by] if color_by else None
    elif isinstance(data, xr.Dataset):
        ctd_time = x_axis.values
        ctd_depth = y_axis.values
        color_data = data[color_by].values if color_by else None
    else:
        raise TypeError("Input data must be a pandas DataFrame or xarray Dataset")

    plt.figure(figsize=(10, 6))
    if color_data is not None:
        sc = plt.scatter(
            ctd_time, ctd_depth, c=color_data, cmap="viridis", label="Profile Depth"
        )
        plt.colorbar(sc, label=color_by)
    else:
        plt.plot(ctd_time, ctd_depth, "k", label="Profile Depth")

    plt.ylabel("Depth")
    plt.title("Depth as a Function of Time")
    plt.legend()
    plt.grid(True)

    # Set y-axis limits to be tight around the data plotted to the nearest 10 meters
    y_min = np.floor(ctd_depth.min() / 10) * 10
    y_max = np.ceil(ctd_depth.max() / 10) * 10
    plt.ylim([y_min, y_max])
    plt.gca().invert_yaxis()

    plt.gca().xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%b-%d"))

    # Add the year or year range to the xlabel
    start_year = pd.to_datetime(ctd_time.min()).year
    end_year = pd.to_datetime(ctd_time.max()).year
    if start_year == end_year:
        plt.xlabel(f"Time ({start_year})")
    else:
        plt.xlabel(f"Time ({start_year}-{end_year})")

    plt.show()


def plot_ctd_depth_vs_time(ds: xr.Dataset, start_traj: int | None = None, end_traj: int | None = None) -> None:
    """Plot CTD depth vs time with GPS fix highlighting.
    
    Creates a depth time series plot with special highlighting of points where
    GPS latitude data is available (non-NaN), useful for identifying surface intervals.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset containing 'ctd_time', 'ctd_depth', and 'gps_lat' variables.
    start_traj : int, optional
        The starting trajectory number to filter the data. If None, no filtering applied.
    end_traj : int, optional
        The ending trajectory number to filter the data. If None, no filtering applied.
        
    Notes
    -----
    - Plots CTD depth as black dots for all data points.
    - Overlays red circles at points where GPS latitude is non-NaN.
    - Inverts y-axis to show depth increasing downward.
    - Filters data by trajectory range if specified.

    """
    # Filter data by trajectory number if specified
    if start_traj is not None and end_traj is not None:
        ds = ds.where(
            (ds["trajectory"] >= start_traj) & (ds["trajectory"] <= end_traj), drop=True
        )

    plt.figure(figsize=(10, 6))

    # Plot ctd_depth against ctd_time using a black line
    plt.plot(ds["ctd_time"], ds["ctd_depth"], "k.", label="CTD Depth")

    # Plot ctd_depth against ctd_time where gps_lat is non NaN, with a colored red circle
    non_nan_indices = ~np.isnan(ds["gps_lat"])
    plt.plot(
        ds["ctd_time"][non_nan_indices],
        ds["ctd_depth"][non_nan_indices],
        "ro",
        label="GPS Lat Non-NaN",
    )

    plt.xlabel("CTD Time")
    plt.ylabel("CTD Depth")
    plt.legend()
    plt.title("CTD Depth vs Time")
    plt.gca().invert_yaxis()  # Invert y-axis to have depth increasing downwards
    plt.show()
