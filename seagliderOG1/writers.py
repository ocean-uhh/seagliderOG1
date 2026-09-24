"""Write OG1 datasets to compressed NetCDF files."""

import logging
import os
from numbers import Number

import numpy as np
import xarray as xr

from seagliderOG1 import tools

_log = logging.getLogger(__name__)

# OG1 serialisation for datetime variables: float64 seconds using the canonical OG1 time
# units (defined once in tools), so the written file matches encode_times_og1 instead of
# silently overriding it.
_TIME_ENCODING = {
    "units": tools.OG1_TIME_UNITS,
    "calendar": tools.OG1_TIME_CALENDAR,
    "dtype": "float64",
}


# Encoding entries that carry data semantics (missing-value sentinel, packing) and
# must be kept when an explicit compression encoding replaces a variable's encoding.
_PRESERVE_ENCODING = ("_FillValue", "missing_value", "scale_factor", "add_offset")


def save_dataset(
    ds: xr.Dataset,
    output_file: str = "../test.nc",
    overwrite: bool = False,
) -> bool:
    """Attempts to save the dataset to a NetCDF file with lossless compression.

    Every non-scalar numeric variable, coordinates included, is written with zlib
    at level 4 and the shuffle filter. If a TypeError occurs due to invalid
    attribute values, converts the invalid attributes to strings and retries the
    save. The input dataset is copied first, so the caller's dataset is not
    modified.

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
    ds = ds.copy()

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

    encoding = _compression_encoding(ds)
    for name, var in ds.variables.items():
        if np.issubdtype(var.dtype, np.datetime64):
            # Drop units/calendar from attrs so they cannot conflict with the
            # explicit time encoding applied on write.
            var.attrs.pop("units", None)
            var.attrs.pop("calendar", None)
            encoding.setdefault(name, {}).update(_TIME_ENCODING)

    def _write() -> None:
        ds.to_netcdf(output_file, encoding=encoding, format="NETCDF4", engine="netcdf4")
        print(f"Dataset successfully saved to {output_file}")

    try:
        _write()
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
    return True


def _compression_encoding(ds: xr.Dataset) -> dict[str, dict]:
    """Build a per-variable zlib encoding for the compressible variables.

    Returns zlib-at-level-4 plus the shuffle filter for every non-scalar numeric
    variable, coordinates included. String and scalar variables are omitted: the
    HDF5 zlib filter does not apply to variable-length strings and cannot chunk a
    scalar. Because an explicit encoding replaces a variable's own encoding on
    write, any existing semantic entries (`_FillValue`, packing) are carried over
    so a missing-value sentinel is not written as an ordinary value.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to be written.

    Returns
    -------
    dict of str to dict
        Mapping of variable name to its compression encoding.

    """
    compression = {"zlib": True, "complevel": 4, "shuffle": True}
    encoding: dict[str, dict] = {}
    for name, var in ds.variables.items():
        if var.ndim > 0 and var.dtype.kind not in ("U", "S", "O"):
            enc = {k: var.encoding[k] for k in _PRESERVE_ENCODING if k in var.encoding}
            enc.update(compression)
            encoding[name] = enc
    return encoding
