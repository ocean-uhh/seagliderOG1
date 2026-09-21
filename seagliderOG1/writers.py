"""Write OG1 datasets to compressed NetCDF files."""

import logging
from numbers import Number

import numpy as np
import xarray as xr

_log = logging.getLogger(__name__)


def save_dataset(ds: xr.Dataset, output_file: str = "../test.nc") -> bool:
    """Attempts to save the dataset to a NetCDF file with lossless compression.

    Every non-scalar numeric variable, coordinates included, is written with zlib
    at level 4 and the shuffle filter. If a TypeError occurs due to invalid
    attribute values, converts the invalid attributes to strings and retries the
    save. The input dataset is copied first, so the caller's dataset is not
    modified.

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
    ds = ds.copy()
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

    time_vars = [
        name
        for name in list(ds.data_vars) + list(ds.coords)
        if np.issubdtype(ds[name].dtype, np.datetime64)
    ]
    encoding = _compression_encoding(ds, time_vars)

    def _write() -> None:
        ds.to_netcdf(output_file, encoding=encoding, format="NETCDF4", engine="netcdf4")

    try:
        _write()
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
            _write()
        except Exception as e:  # noqa: BLE001  # I/O boundary: last-ditch save attempt
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
        else:
            return True
    else:
        return True


def _compression_encoding(ds: xr.Dataset, time_vars: list[str]) -> dict[str, dict]:
    """Build a per-variable NetCDF encoding with lossless zlib compression.

    Applies zlib at level 4 and the shuffle filter to every non-scalar numeric
    variable, coordinates included, and layers the OG1 time encoding on top for
    datetime variables. String and scalar variables are left uncompressed: the
    HDF5 zlib filter does not apply to variable-length strings and cannot chunk a
    scalar.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to be written.
    time_vars : list of str
        Names of datetime variables to encode as float64 seconds since 1970-01-01.

    Returns
    -------
    dict of str to dict
        Mapping of variable name to its encoding dictionary.

    """
    compression = {"zlib": True, "complevel": 4, "shuffle": True}
    time_encoding = {
        "units": "seconds since 1970-01-01 00:00:00",
        "calendar": "standard",
        "dtype": "float64",
    }
    encoding: dict[str, dict] = {}
    for name in ds.variables:
        var = ds[name]
        enc: dict = {}
        if var.ndim > 0 and var.dtype.kind not in ("U", "S", "O"):
            enc.update(compression)
        if name in time_vars:
            enc.update(time_encoding)
        if enc:
            encoding[name] = enc
    return encoding
