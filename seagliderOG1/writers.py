import logging
from numbers import Number

import numpy as np
import xarray as xr

_log = logging.getLogger(__name__)


def save_dataset(ds: xr.Dataset, output_file: str = "../test.nc") -> None:
    """Attempts to save the dataset to a NetCDF file.

    If a TypeError occurs due to invalid attribute values, converts the invalid
    attributes to strings and retries the save operation.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to be saved.
    output_file : str, optional
        The path to the output NetCDF file. Defaults to '../test.nc'.

    Returns
    -------
    bool
        True if the dataset was saved successfully, False otherwise.

    Notes
    -----
    Based on: https://github.com/pydata/xarray/issues/3743

    """
    valid_types = (str, Number, np.ndarray, np.number, list, tuple)

    for varname in ds.variables:
        var = ds[varname]
        if np.issubdtype(var.dtype, np.datetime64):
            for key in ["units", "calendar"]:
                if key in var.attrs:
                    value = var.attrs.pop(key)
                    var.encoding[key] = value
                    _log.info(
                        f"Moved '{key}' from attrs to encoding for variable '{varname}'."
                    )

    try:
        ds.to_netcdf(output_file, format="NETCDF4")
        return True

    except TypeError as e:
        _log.error(f"TypeError saving dataset: {e.__class__.__name__}: {e}")

        for varname, variable in ds.variables.items():
            for k, v in variable.attrs.items():
                if not isinstance(v, valid_types) or isinstance(v, bool):
                    _log.warning(
                        f"For variable '{varname}': Converting attribute '{k}' with value '{v}' to string."
                    )
                    variable.attrs[k] = str(v)

        try:
            ds.to_netcdf(output_file, format="NETCDF4")
            return True

        except Exception as e:
            _log.error(f"Failed to save dataset: {e}")
            datetime_vars = [
                var for var in ds.variables if ds[var].dtype == "datetime64[ns]"
            ]
            _log.warning(f"Variables with dtype datetime64[ns]: {datetime_vars}")
            float_attrs = [
                attr for attr in ds.attrs if isinstance(ds.attrs[attr], float)
            ]
            _log.warning(f"Attributes with dtype float64: {float_attrs}")
            return False
