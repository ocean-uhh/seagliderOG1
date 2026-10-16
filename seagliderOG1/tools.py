"""User-facing utilities for Seaglider-to-OG1 conversion.

Sensor metadata extraction, variable-name mapping, QC-flag conversion, dtype
coercion, profile and phase numbering, time encoding, and dataset merging.
"""

import logging

import gsw
import numpy as np
import pandas as pd
import xarray as xr

from seagliderOG1 import vocabularies

_log = logging.getLogger(__name__)

__all__ = [
    "calc_Z",
    "assign_phase",
    "assign_profile_number",
    "add_dive_number",
    "convert_units_var",
    "reformat_units_var",
    "reformat_units_str",
    "convert_qc_flags",
    "encode_times_og1",
    "split_by_unique_dims",
]


# Variables measured directly by the CTD.

# Variables calculated using CTD measurements.

# Alternative names used for the same physical instrument.


def add_dive_number(ds: xr.Dataset, dive_number: int | None = None) -> xr.Dataset:
    """Add dive number as a variable to the dataset. Assumes present in the basestation attributes.

    Parameters
    ----------
    ds
        The dataset to which the dive number will be added.
    dive_number, optional
        The dive number to add. If None, extracts from dataset attributes.

    Returns
    -------
    xarray.Dataset
        The dataset with the dive number added.

    """
    if dive_number is None:
        dive_number = ds.attrs.get("dive_number", np.nan)

    dive_var = xr.DataArray(
        np.full(ds.sizes["N_MEASUREMENTS"], dive_number),
        dims=["N_MEASUREMENTS"],
        attrs={
            "long_name": "dive number",
            "units": "1",
        },
    )
    return ds.assign(DIVE_NUMBER=dive_var)


def assign_profile_number(ds: xr.Dataset, ds1: xr.Dataset) -> xr.Dataset:
    """Assign profile numbers to measurements based on dive phases (down/up casts).

    This function separates each dive into two profiles: descent (down cast) and
    ascent (up cast) phases. The dive is split at the maximum pressure point,
    with the descent phase getting the dive number and ascent getting dive + 0.5.
    Profile numbers are then calculated as 2 * DIVE_NUMBER - 1.

    Parameters
    ----------
    ds
        The dataset to add profile numbers to.
    ds1
        Dataset containing dive number information in attributes.

    Returns
    -------
    xarray.Dataset
        Dataset with 'DIVE_NUMBER' and 'PROFILE_NUMBER' variables added.

    Notes
    -----
    - Requires pressure variable (PRES)
    """
    dive_number = ds1.attrs["dive_number"]
    ds = add_dive_number(ds, dive_number)

    fill_value = -9999
    profile_numbers = np.full(ds.sizes["N_MEASUREMENTS"], fill_value, dtype=int)

    if profile_numbers.size and not np.isnan(dive_number):
        pmax_index = int(np.nanargmax(ds["PRES"].values))

        profile_numbers[: pmax_index + 1] = 2 * dive_number - 1
        profile_numbers[pmax_index + 1 :] = 2 * dive_number

    ds = ds.assign(
        PROFILE_NUMBER=xr.DataArray(
            profile_numbers,
            dims=["N_MEASUREMENTS"],
        )
    )
    ds["PROFILE_NUMBER"].encoding["_FillValue"] = fill_value

    return ds


def assign_phase(ds: xr.Dataset) -> xr.Dataset:
    """Add 'PHASE' and 'PHASE_QC' variables indicating the phase of each measurement.

    The phase is determined from the pressure readings ('PRES') for each unique
    dive number ('dive_num').

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset containing 'dive_num' and 'PRES' variables.

    Returns
    -------
    xarray.Dataset
        The dataset with additional 'PHASE' and 'PHASE_QC' variables, where:

        - 'PHASE' indicates the phase of each measurement:
            - Phase 2 up to and including the maximum pressure point.
            - Phase 1 after the maximum pressure point.
        - 'PHASE_QC' is an additional variable with no QC applied.

    Notes
    -----
    In this formulation, we are only separating into dives and climbs based on
    when the glider is at the maximum depth. Future work needs to separate out
    the other phases and generate a PHASE_QC:
    https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md
    """
    # Determine the correct keystring for divenum
    if "dive_number" in ds.variables:
        divenum_str = "dive_number"
    elif "divenum" in ds.variables:
        divenum_str = "divenum"
    elif "dive_num" in ds.variables:
        divenum_str = "dive_num"
    elif "DIVE_NUMBER" in ds.variables:
        divenum_str = "DIVE_NUMBER"
    else:
        raise ValueError("No valid dive number variable found in the dataset.")
    # Initialize the new variable with the same dimensions as dive_num
    ds["PHASE"] = (["N_MEASUREMENTS"], np.full(ds.sizes["N_MEASUREMENTS"], np.nan))
    # Initialize the new variable PHASE_QC with the same dimensions as dive_num
    ds["PHASE_QC"] = (
        ["N_MEASUREMENTS"],
        np.zeros(ds.sizes["N_MEASUREMENTS"], dtype=int),
    )

    # Iterate over each unique dive_num
    for dive in np.unique(ds[divenum_str]):
        # Get the indices for the current dive
        dive_indices = np.where(ds[divenum_str] == dive)[0]
        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]

        # Find the index of the maximum pressure between start_index and end_index
        pmax = np.nanmax(ds["PRES"][start_index : end_index + 1].values)

        # Find the index where PRES attains the value pmax between start_index and end_index
        pmax_index = start_index + np.argmax(
            ds["PRES"][start_index : end_index + 1].values == pmax
        )

        # Assign phase 2 to all values up to and including the point where pmax is reached
        ds["PHASE"][start_index : pmax_index + 1] = 2

        # Assign phase 1 to all values after pmax is reached
        ds["PHASE"][pmax_index + 1 : end_index + 1] = 1

        # Assign phase 3 to the time at the beginning of the dive, between the first valid TIME_GPS and the second valid TIME_GPS
        valid_time_gps_indices = np.where(
            ~np.isnan(ds["TIME_GPS"][start_index : end_index + 1].values)
        )[0]
        if len(valid_time_gps_indices) >= 2:
            first_valid_index = start_index + valid_time_gps_indices[0]
            second_valid_index = start_index + valid_time_gps_indices[1]
            ds["PHASE"][first_valid_index : second_valid_index + 1] = 3

    return ds


##-----------------------------------------------------------------------------------------------------------
## Calculations for new variables
##-----------------------------------------------------------------------------------------------------------
def calc_Z(ds: xr.Dataset) -> xr.Dataset:
    """Calculate the depth (Z position) of the glider using the gsw library to convert pressure to depth.

    Parameters
    ----------
    ds
        The input dataset containing 'PRES', 'LATITUDE', and 'LONGITUDE' variables.

    Returns
    -------
    xarray.Dataset
        The dataset with an additional 'DEPTH' variable.

    """
    # Ensure the required variables are present
    if "PRES" not in ds.variables or "LATITUDE" not in ds.variables:
        raise ValueError("Dataset must contain 'PRES' and 'LATITUDE' variables.")

    # Convert pressure to depth using gsw (pressure in dbar, latitude in degrees)
    depth = gsw.z_from_p(
        ds["PRES"], ds["LATITUDE"]
    ).compute()  # Compute to handle dask arrays

    # Add depth to dataset
    ds["DEPTH_Z"] = (["N_MEASUREMENTS"], depth.data)
    # Assign the calculated depth to a new variable in the dataset

    ds["DEPTH_Z"].attrs = {
        "units": "meters",
        "positive": "up",
        "standard_name": "depth",
        "comment": "Depth calculated from pressure using gsw library, positive up.",
    }

    return ds


def split_by_unique_dims(ds: xr.Dataset) -> dict:
    """Split an xarray dataset into datasets grouped by each variable's dimension set.

    Parameters
    ----------
    ds
        The input xarray dataset containing various variables.

    Returns
    -------
    dict
        A dictionary mapping dimension tuples to datasets, each with variables sharing the same set of dimensions.

    """
    # Dictionary to hold datasets with unique dimension sets
    unique_dims_datasets = {}
    # Iterate over the variables in the dataset
    for var_name, var_data in ds.data_vars.items():
        # Get the dimensions of the variable
        dims = tuple(var_data.sizes)

        # If this dimension set is not in the dictionary, create a new dataset
        if dims not in unique_dims_datasets:
            unique_dims_datasets[dims] = xr.Dataset()

        # Add the variable to the corresponding dataset
        unique_dims_datasets[dims][var_name] = var_data

    # Convert the dictionary values to a dictionary of datasets
    return dict(unique_dims_datasets)


def reformat_units_var(
    ds: xr.Dataset, var_name: str, unit_format: dict = vocabularies.unit_str_format
) -> str:
    """Rename units in the dataset based on the provided dictionary for OG1.

    Parameters
    ----------
    ds
        The input dataset containing variables with units to be renamed.
    var_name
        The name of the variable whose units should be reformatted.
    unit_format, optional
        A dictionary mapping old unit strings to new formatted unit strings.

    Returns
    -------
    str
        The reformatted unit string.

    """
    """
    Renames units in the dataset based on the provided dictionary for OG1.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing variables with units to be renamed.
    unit_format (dict): A dictionary mapping old unit strings to new formatted unit strings.

    Returns
    -------
    xarray.Dataset: The dataset with renamed units.
    """
    old_unit = ds[var_name].attrs["units"]
    return unit_format.get(old_unit, old_unit)


def reformat_units_str(
    old_unit: str, unit_format: dict = vocabularies.unit_str_format
) -> str:
    """Reformat a unit string based on the provided unit format dictionary.

    Parameters
    ----------
    old_unit
        The original unit string to reformat.
    unit_format, optional
        A dictionary mapping old unit strings to new formatted unit strings.

    Returns
    -------
    str
        The reformatted unit string, or the original if no mapping exists.

    """
    new_unit = unit_format.get(old_unit, old_unit)
    return new_unit.strip()  # .casefold()


def convert_units_var(
    var_values: np.ndarray,
    current_unit: str,
    new_unit: str,
    unit1_to_unit2: dict = vocabularies.unit1_to_unit2,
) -> tuple[np.ndarray, str]:
    """Convert variable values from their current unit to a requested unit.

    Unit strings are normalized with :func:`reformat_units_str` before they
    are compared or used to look up conversion information.

    If the normalized units are identical, the values are returned unchanged.
    If no conversion is available, the original values and current unit are
    returned, and an optional warning is logged.

    Parameters
    ----------
    var_values
        Values to convert.
    current_unit
        Unit currently associated with ``var_values``.
    new_unit
        Requested output unit.
    unit1_to_unit2
        Mapping of conversion keys, such as ``"cm/s_to_m/s"``, to conversion
        information. Each entry must contain a ``"factor"`` value.

    Returns
    -------
    converted_values
        Converted values, or the original values if conversion is unnecessary
        or unavailable.
    output_unit
        Normalized output unit. This is the current unit when conversion is
        unavailable.
    """
    current_unit = reformat_units_str(current_unit)
    requested_unit = reformat_units_str(new_unit)

    # No conversion is needed when the normalized units are identical.
    if current_unit == requested_unit:
        return var_values, current_unit

    conversion_key = f"{current_unit}_to_{requested_unit}"
    conversion = unit1_to_unit2.get(conversion_key)

    if conversion is not None:
        converted_values = var_values * conversion["factor"]
        return converted_values, requested_unit

    _log.warning(
        "No conversion information found for %r to %r",
        current_unit,
        requested_unit,
    )

    return var_values, current_unit


def convert_qc_flags(dsa: xr.Dataset, qc_name: str) -> xr.Dataset:
    """Convert QC flag variables to proper integer format and update attributes.

    This function converts QC flag variables from string format to int8,
    handles NaN values appropriately, removes ``QC_`` prefixes from flag meanings,
    and adds proper metadata including long_name and standard_name.

    Parameters
    ----------
    dsa
        The dataset containing QC flag variables.
    qc_name
        The name of the QC flag variable to process.

    Returns
    -------
    xarray.Dataset
        Dataset with converted QC flag variable and updated attributes.

    Notes
    -----
    Must be called after the main variable has been assigned its OG1 long_name.

    """
    # Must be called *after* var_name has OG1 long_name
    var_name = qc_name[:-3]
    if qc_name in list(dsa):
        # For scalar log qc's that might change over the mission are stored as json, don't convert to int8
        if (
            qc_name in dsa.variables
            and dsa[qc_name].attrs.get("serialization") == "json"
        ):
            return dsa
        # Seaglider default type was a string.  Convert to int8 and take care of NaNs
        # dsa[qc_name].values = dsa[qc_name].values.astype("int8")
        values = dsa[qc_name].values
        # Convert byte strings to regular strings (if necessary)
        if values.dtype.type is np.bytes_:
            values = values.astype(str)

        # Use pandas to handle NaNs safely
        original_shape = np.asarray(values).shape
        values = pd.to_numeric(
            np.asarray(values).reshape(-1),
            errors="coerce",
        ).reshape(original_shape)  # Convert strings to numbers, NaNs stay NaNs
        # Assign back to dataset
        dsa[qc_name].values = values
        ### Set the nan values to 6 (unsampled flag) and convert to int8
        ### Before it had just set all values to 0, which is no change flag
        ### Alternative could be to set to 9 (missing value)
        dsa[qc_name].values = dsa[qc_name].fillna(6).astype("int8")
        # A flag variable has no missing value (6 = unsampled is itself a flag), so drop
        # any inherited float _FillValue that would be invalid on the int8 result.
        # Clear both encoding and attrs: set_best_dtype skips QC, so nothing else removes
        # a _FillValue left in attrs, and xarray rejects _FillValue in attrs on write.
        dsa[qc_name].encoding.pop("_FillValue", None)
        dsa[qc_name].attrs.pop("_FillValue", None)
        # Seaglider default flag_meanings were prefixed with 'QC_'. Remove this prefix.
        if "flag_meaning" in dsa[qc_name].attrs:
            flag_meaning = dsa[qc_name].attrs["flag_meaning"]
            dsa[qc_name].attrs["flag_meaning"] = flag_meaning.replace("QC_", "")
        # The parent variable may be absent: an orphan QC, or a numbered name like
        # 'TEMP_QC2' whose 'TEMP_' parent does not exist (qc_name[:-3] strips only the
        # '_QC' suffix). Guard before dereferencing dsa[var_name].
        parent_present = var_name in dsa.variables
        # Add a long_name attribute to the QC variable
        dsa[qc_name].attrs["long_name"] = (
            (dsa[var_name].attrs.get("long_name", "") + " quality flag")
            if parent_present
            else "quality flag"
        )
        dsa[qc_name].attrs["standard_name"] = "status_flag"
        # Mention the QC variable in the parent's attributes, when the parent exists.
        if parent_present:
            dsa[var_name].attrs["ancillary_variables"] = qc_name
    return dsa


# Variables that are semantically integer and are stored as the smallest signed integer
# that holds their range. Named explicitly: a float variable that happens to be
# integer-valued in one deployment is not an integer variable.


# OG1 canonical serialisation for time variables (CF seconds since the epoch, UTC).
# Used by the time encoders here and by writers.save_dataset; keep in sync with the time
# variable units declared in config/OG1_vocab_attrs.yaml.
OG1_TIME_UNITS = "seconds since 1970-01-01T00:00:00Z"
OG1_TIME_CALENDAR = "gregorian"


def encode_times_og1(ds: xr.Dataset) -> xr.Dataset:
    """Encode time variables according to OG1 format specifications.

    Parameters
    ----------
    ds
        Dataset containing time variables to encode.

    Returns
    -------
    xarray.Dataset
        Dataset with OG1-formatted time variables.

    """
    for var_name in ds.variables:
        if "axis" in ds[var_name].attrs:
            ds[var_name].attrs.pop("axis")
        if "time" in var_name.lower():
            for drop_attr in ["units", "calendar", "dtype"]:
                if drop_attr in ds[var_name].attrs:
                    ds[var_name].attrs.pop(drop_attr)
                if drop_attr in ds[var_name].encoding:
                    ds[var_name].encoding.pop(drop_attr)
            if var_name.lower() == "time":
                ds[var_name].attrs["units"] = OG1_TIME_UNITS
                ds[var_name].attrs["calendar"] = OG1_TIME_CALENDAR
    return ds


# ===============================================================================
# Unused functions
# ===============================================================================
