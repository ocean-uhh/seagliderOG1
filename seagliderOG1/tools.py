"""User-facing utilities for Seaglider-to-OG1 conversion.

Sensor metadata extraction, variable-name mapping, QC-flag conversion, dtype
coercion, profile and phase numbering, time encoding, and dataset merging.
"""

import logging

import gsw
import numpy as np
import pandas as pd
import xarray as xr

from seagliderOG1 import _phase, vocabularies

_log = logging.getLogger(__name__)

__all__ = [
    "add_depth",
    "add_phase",
    "add_profiles",
    "add_dive_number",
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
        attrs=dict(vocabularies.vocab_attrs["dive_number"]),
    )
    return ds.assign(dive_number=dive_var)


def add_phase(ds: xr.Dataset) -> xr.Dataset:
    """Add ``PHASE`` and ``PHASE_QC``: what the glider was doing at each sample.

    ``PHASE`` takes the OG1 phase vocabulary ids (``phase_vocabulary``): 1 ascent,
    2 descent, 3 surfacing, 5 inflection, 0 unknown. Per dive it comes from the glider's
    state table (``gc_state_state``) where the file has one, otherwise from the
    guidance-and-control events (the apogee is the event that moves the VBD to zero),
    otherwise from pressure alone (descent to the pressure maximum, ascent after). GPS
    fixes are surfacing. ``phase_calculation_method`` says which signal assigned which
    dives. No quality control is applied: ``PHASE_QC`` is 0 throughout.

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset on ``N_MEASUREMENTS`` with ``TIME``, ``PRES``, a dive-number variable
        (``dive_number``, ``divenum``, ``dive_num``, or ``DIVE_NUMBER`` in files from before 0.3.0) and, where the
        basestation wrote them, ``TIME_GPS``, ``gc_state_state``, ``gc_vbd_ctl`` and
        ``gc_end_secs``.

    Returns
    -------
    xarray.Dataset
        ``ds`` with ``PHASE`` (int8, ``_FillValue`` 0) and ``PHASE_QC`` (int8, all 0).

    Raises
    ------
    ValueError
        If ``ds`` has no dive-number variable.

    Notes
    -----
    The phase vocabulary:
    https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md
    """
    phase, methods = _phase.assign(ds)
    attrs = dict(vocabularies.vocab_attrs["PHASE"])
    attrs["flag_values"] = np.array(list(_phase.PHASE_NAMES), "int8")
    attrs["flag_meanings"] = " ".join(_phase.PHASE_NAMES.values())
    attrs["phase_calculation_method"] = _phase.method_text(methods)
    attrs["phase_calculation_method_vocabulary"] = ""
    attrs["ancillary_variables"] = "PHASE_QC"
    ds["PHASE"] = (["N_MEASUREMENTS"], phase, attrs)
    ds["PHASE"].encoding["_FillValue"] = np.int8(0)
    ds["PHASE_QC"] = (
        ["N_MEASUREMENTS"],
        np.zeros(phase.size, dtype="int8"),
        dict(_phase.PHASE_QC_ATTRS),
    )
    return ds


def add_profiles(ds: xr.Dataset) -> xr.Dataset:
    """Add ``PROFILE_NUMBER``, ``PROFILE_DIRECTION`` and ``SEGMENT_NUMBER`` from ``PHASE``.

    As the OG1 format defines them: a profile is a run of descent (2) or ascent (1) rows,
    numbered from 1 in time order, with ``PROFILE_NUMBER`` -9999 (its ``_FillValue``) on
    every other row; ``PROFILE_DIRECTION`` is 1 descending, -1 ascending, 0 otherwise
    (``_FillValue`` 0); ``SEGMENT_NUMBER`` starts at 1 and increments each time the glider
    enters surfacing (3).

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset on ``N_MEASUREMENTS``, sorted by ``TIME``, with ``PHASE``.

    Returns
    -------
    xarray.Dataset
        ``ds`` with the three variables.
    """
    phase = np.nan_to_num(np.asarray(ds["PHASE"].values, dtype=float)).astype("int8")
    number, direction, segment = _phase.profiles(phase)
    for name, values, attrs, fill in (
        ("PROFILE_NUMBER", number, _phase.PROFILE_NUMBER_ATTRS, _phase.NUMBER_FILL),
        ("PROFILE_DIRECTION", direction, _phase.PROFILE_DIRECTION_ATTRS, 0),
        ("SEGMENT_NUMBER", segment, _phase.SEGMENT_NUMBER_ATTRS, _phase.NUMBER_FILL),
    ):
        # The OG1 attributes from the configuration (long_name, units, vocabulary), then the
        # OG1 calculation-method text.
        ds[name] = (
            ["N_MEASUREMENTS"],
            values,
            {**vocabularies.vocab_attrs.get(name, {}), **attrs},
        )
        ds[name].encoding["_FillValue"] = values.dtype.type(fill)
    return ds


##-----------------------------------------------------------------------------------------------------------
## Calculations for new variables
##-----------------------------------------------------------------------------------------------------------
def add_depth(ds: xr.Dataset) -> xr.Dataset:
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
        "units": "m",
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
    # Group the variables first and build each dataset once: adding variables one at a
    # time re-aligns the growing dataset on every assignment (quadratic in the number
    # of variables, about a second per basestation dive).
    groups: dict[tuple, dict[str, xr.DataArray]] = {}
    for var_name, var_data in ds.data_vars.items():
        groups.setdefault(tuple(var_data.sizes), {})[var_name] = var_data
    return {dims: xr.Dataset(variables) for dims, variables in groups.items()}


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
        parent_long_name = (
            dsa[var_name].attrs.get("long_name", "") if parent_present else ""
        )
        dsa[qc_name].attrs["long_name"] = f"{parent_long_name} quality flag".strip()
        dsa[qc_name].attrs["standard_name"] = "status_flag"
        # Mention the QC variable in the parent's attributes, when the parent exists.
        if parent_present:
            dsa[var_name].attrs["ancillary_variables"] = qc_name
    return dsa


# Variables that are semantically integer and are stored as the smallest signed integer
# that holds their range. Named explicitly: a float variable that happens to be
# integer-valued in one deployment is not an integer variable.


# OG1 canonical serialisation for time variables (CF seconds since the epoch, UTC).
# Used by the time encoders here and by writers.write; keep in sync with the time
# variable units declared in config/OG1_variable_attributes.yaml.
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
        # Only real datetime variables are CF-time encoded: their units and calendar
        # belong in encoding and are written there, so any stray attrs are dropped. A
        # numeric duration such as DELTA_TIME_S merely has "time" in its name and must
        # keep its unit attribute (seconds), so the name is not used to select here.
        if np.issubdtype(ds[var_name].dtype, np.datetime64):
            for drop_attr in ["units", "calendar", "dtype"]:
                if drop_attr in ds[var_name].attrs:
                    ds[var_name].attrs.pop(drop_attr)
                if drop_attr in ds[var_name].encoding:
                    ds[var_name].encoding.pop(drop_attr)
            if var_name.lower() == "time":
                ds[var_name].attrs["units"] = OG1_TIME_UNITS
                ds[var_name].attrs["calendar"] = OG1_TIME_CALENDAR
    return ds
