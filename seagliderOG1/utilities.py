# Based on https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/utilities/utilities.py
import datetime
import logging
import re

import xarray as xr

# from votoutils.upload.sync_functions import sync_script_dir

_log = logging.getLogger(__name__)


def _validate_coords(ds1: xr.Dataset) -> xr.Dataset:
    """Validates and assigns coordinates to the given xarray Dataset.

    Parameters
    ----------
    ds1
        The dataset to validate and assign coordinates to.
        Expected to have an 'id' attribute and may contain
        'longitude', 'latitude', 'ctd_time', and 'ctd_depth' variables.

    Returns
    -------
    xarray.Dataset
        The validated dataset with necessary coordinates assigned.
        If 'ctd_time' variable is missing, returns an empty dataset.

    Notes
    -----
    - If 'longitude' or 'latitude' coordinates are missing, they are added as NaNs
    - If 'ctd_time' variable exists but coordinates are missing, assigns from variable
    - If 'ctd_time' variable is missing, returns an empty dataset
    - Based on: https://github.com/pydata/xarray/issues/3743

    """
    id = ds1.attrs["id"]
    if "longitude" not in ds1.coords:
        ds1 = ds1.assign_coords(
            longitude=("sg_data_point", [float("nan")] * ds1.dims["sg_data_point"])
        )
        _log.warning(
            f"{id}: No coord longitude - adding as NaNs to length of sg_data_point"
        )
    if "latitude" not in ds1.coords:
        ds1 = ds1.assign_coords(
            latitude=("sg_data_point", [float("nan")] * ds1.dims["sg_data_point"])
        )
        _log.warning(
            f"{id}: No coord latitude - adding as NaNs to length of sg_data_point"
        )
    if "ctd_time" in ds1.variables:
        if "ctd_time" not in ds1.coords:
            ds1 = ds1.assign_coords(ctd_time=("sg_data_point", ds1["ctd_time"].values))
            _log.warning(
                f"{id}: No coord ctd_time, but exists as variable - assigning coord from variable"
            )
        if "ctd_depth" not in ds1.coords:
            ds1 = ds1.assign_coords(
                ctd_depth=("sg_data_point", ds1["ctd_depth"].values)
            )
            _log.warning(
                f"{id}: No coord ctd_depth, but exists as variable - assigning coord from variable"
            )
    else:
        _log.warning(f"{id}: No variable ctd_time - returning an empty dataset")

        ds1 = xr.Dataset()
    return ds1


def _validate_dims(ds: xr.Dataset, expected_dims: str = "N_MEASUREMENTS") -> bool:
    """Validates that the dataset has the expected dimension name.

    Parameters
    ----------
    ds
        The dataset to validate.
    expected_dims, optional
        The expected dimension name. Default is 'N_MEASUREMENTS'.

    Returns
    -------
    bool
        True if dimension name matches expected, False otherwise.

    """
    dim_name = list(ds.dims)[0]  # Should be 'N_MEASUREMENTS' for OG1
    if dim_name != expected_dims:
        _log.error(f"Dimension name '{dim_name}' is not {expected_dims}.")
        return False
    #        raise ValueError(f"Dimension name '{dim_name}' is not {expected_dims}.")
    else:
        return True


def _parse_calibcomm(calstr: str, firstrun: bool = False) -> tuple[str, str]:
    """Parses calibration string to extract calibration date and serial number.

    Parameters
    ----------
    calstr
        The calibration string to parse.
    firstrun, optional
        Whether to log detailed parsing information. Default is False.

    Returns
    -------
    tuple[str, str]
        A tuple containing (calibration_date, serial_number).
        Date format is YYYYMMDD, or 'Unknown' if not found.

    """
    # Parse for calibration date
    cal_date = calstr
    cal_date_before_keyword = cal_date
    cal_date_YYYYmmDD = "Unknown"
    formats = [
        "%d%b%y",
        "%d-%b-%y",
        "%m/%d/%y",
        "%b/%d/%y",
        "%b-%d-%y",
        "%b%d%y",
        "%d%b%y",
        "%d%B%y",
    ]
    for keyword in ["calibration", "calibrated"]:
        if keyword in cal_date:
            cal_date_before_keyword = cal_date.split(keyword)[0].strip()
            cal_date = cal_date.split(keyword)[-1].strip()
            cal_date = cal_date.replace(" ", "")
            for fmt in formats:
                try:
                    cal_date_YYYYmmDD = datetime.datetime.strptime(
                        cal_date, fmt
                    ).strftime("%Y%m%d")
                    break  # Exit the loop if parsing is successful
                except ValueError:
                    continue  # Try the next format if parsing fails
            break  # Exit the outer loop if keyword is found

    if firstrun:
        _log.info(f"     --> produces {cal_date_YYYYmmDD}")

    # Parse for serial number of sensor
    serial_number = "unknown"
    for keyword in ["s/n", "S/N", "SN", "SBE#", "SBE"]:
        if keyword in cal_date_before_keyword:
            serial_match = cal_date_before_keyword.split(keyword)[-1].strip()
            serial_number = (
                serial_match.replace(keyword, "")
                .replace("/", "")
                .replace(",", "")
                .strip()
            )
            break  # Exit the outer loop if keyword is found

    if len(calstr) < 5:
        serial_number = calstr
    if firstrun:
        _log.info(f"     --> produces serial_number {serial_number}")

    return cal_date_YYYYmmDD, serial_number


def _clean_time_string(time_str: str) -> str:
    """Cleans time string by removing common separators and timezone indicators.

    Parameters
    ----------
    time_str
        The time string to clean.

    Returns
    -------
    str
        Cleaned time string with underscores, colons, hyphens, and 'Z' removed.

    """
    return time_str.replace("_", "").replace(":", "").rstrip("Z").replace("-", "")


def _clean_anc_vars_list(ancillary_variables_str: str) -> list[str]:
    """Cleans and splits ancillary variables string into a list.

    Parameters
    ----------
    ancillary_variables_str
        Space or concatenated string of ancillary variable names.

    Returns
    -------
    list[str]
        List of cleaned variable names with 'sg_cal_' prefix removed.

    """
    ancillary_variables_str = re.sub(r"(\w)(sg_cal)", r"\1 \2", ancillary_variables_str)
    ancilliary_vars_list = ancillary_variables_str.split()
    ancilliary_vars_list = [var.replace("sg_cal_", "") for var in ancilliary_vars_list]
    return ancilliary_vars_list


def _assign_calval(sg_cal: xr.Dataset, anc_var_list: list[str]) -> dict:
    """Assigns calibration values from dataset to a dictionary.

    Parameters
    ----------
    sg_cal
        Dataset containing calibration variables.
    anc_var_list
        List of ancillary variable names to extract.

    Returns
    -------
    dict
        Dictionary mapping variable names to their values.
        Missing variables are assigned 'Unknown'.

    """
    calval = {}
    for anc_var in anc_var_list:
        # Check if anc_var exists in sg_cal which was not the case in Robs dataset
        if anc_var in sg_cal:
            var_value = sg_cal[anc_var].values.item()
            calval[anc_var] = var_value
        else:
            calval[anc_var] = "Unknown"
    return calval
