import logging
import os
from numbers import Number

import numpy as np
import xarray as xr

_log = logging.getLogger(__name__)


def save_dataset(
    ds: xr.Dataset,
    output_file: str = "../test.nc",
    overwrite: bool = False,
) -> bool:
    """Save an xarray Dataset to a NetCDF file.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset to save.
    output_file : str, optional
        Output NetCDF file.
    overwrite : bool, optional
        If True, an existing file will be deleted and replaced.
        If False, a FileExistsError is raised when the file exists.

    Returns
    -------
    bool
        True if the dataset was saved successfully, False otherwise.
    """

    # Handle existing file
    if os.path.exists(output_file):
        if overwrite:
            print(f"Removing existing file: {output_file}")
            os.remove(output_file)
        else:
            raise FileExistsError(
                f"Output file '{output_file}' already exists. "
                "Use overwrite=True to replace it."
            )

    valid_types = (str, Number, np.ndarray, np.number, list, tuple)

    for varname in ds.variables:
        var = ds[varname]
        if np.issubdtype(var.dtype, np.datetime64):
            for key in ["units", "calendar"]:
                if key in var.attrs:
                    value = var.attrs.pop(key)
                    var.encoding[key] = value
                    print(
                        f"Moved '{key}' from attrs to encoding for variable '{varname}'."
                    )

    try:
        time_vars = [
            name
            for name in list(ds.data_vars) + list(ds.coords)
            if np.issubdtype(ds[name].dtype, np.datetime64)
        ]

        encoding = {
            name: {
                "units": "seconds since 1970-01-01 00:00:00",
                "calendar": "standard",
                "dtype": "float64",
            }
            for name in time_vars
        }

        ds.to_netcdf(output_file, encoding=encoding, format="NETCDF4")
        print(f"Dataset successfully saved to {output_file}")
        return True

    except TypeError as e:
        _log.error(f"TypeError saving dataset: {e.__class__.__name__}: {e}")

        for varname, variable in ds.variables.items():
            for k, v in variable.attrs.items():
                if not isinstance(v, valid_types) or isinstance(v, bool):
                    _log.warning(
                        f"For variable '{varname}': "
                        f"Converting attribute '{k}' with value '{v}' to string."
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
