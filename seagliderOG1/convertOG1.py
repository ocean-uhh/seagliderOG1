"""Convert Seaglider basestation files to OG1 format.

This module provides the core functionality for converting Seaglider basestation
NetCDF files into OG1 (Ocean Gliders 1) format. It handles data processing,
variable renaming, attribute assignments, and dataset standardization.
"""

import logging
import os
import warnings
from collections.abc import Mapping, Sequence
from datetime import datetime

import numpy as np
import xarray as xr
import pandas as pd
from tqdm import tqdm

from seagliderOG1 import contributors, readers, tools, utilities, vocabularies, writers

_log = logging.getLogger(__name__)

# Global attributes the converter derives from the data; the mission config may
# not set these (a collision is an error, not a silent override either way).
_DERIVED_GLOBALS = frozenset(
    {
        "id",
        "time_coverage_start",
        "time_coverage_end",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_vertical_min",
        "geospatial_vertical_max",
        "date_created",
        "start_date",
    }
)

# OG1 id / filename data-mode suffixes. Per the OG1 format manual's file-naming
# convention (id = <platform_serial>_<start_date>_<data_mode>): "R" for near
# real time, "delayed" for delayed mode. The manual defines no separate data-mode
# attribute, so mode affects only the id (and filename); nothing else is written.
# Ref: OceanGliders OG-format-user-manual, OG_Format "File naming convention".
_MODE_SUFFIX = {"delayed": "delayed", "realtime": "R"}

# String platform fields, resolved in order config -> file -> "UNK". The file-derived
# values come from vocabularies.platform_from_file (the one file->field table).
_PLATFORM_STRING_FIELDS = (
    "PLATFORM_MODEL",
    "PLATFORM_MAKER",
    "GLIDER_FIRMWARE_VERSION",
    "LANDSTATION_VERSION",
    "WMO_IDENTIFIER",
)


def _resolve_platform(
    first_ds: xr.Dataset, platform: dict[str, object] | None
) -> dict[str, object]:
    """Resolve OG1 platform fields from the config and the first basestation file.

    Config values override file-derived ones. ``PLATFORM_SERIAL_NUMBER`` is the
    mission identity (it names the output file and OG1 id): if neither the config
    nor the file supplies it, raise. String fields fall back to ``"UNK"`` with a
    warning; the numeric ``PLATFORM_DEPTH_RATING`` is omitted when absent rather
    than written as a string.

    Parameters
    ----------
    first_ds : xarray.Dataset
        The first basestation dataset, read for ``platform_id`` and
        ``wmo_identifier``.
    platform : dict of str to object or None
        The mission config's ``platform`` block; values override the file.

    Returns
    -------
    dict of str to object
        Resolved platform fields to write. ``PLATFORM_DEPTH_RATING`` and
        ``platform_model_vocabulary`` are present only when supplied.

    Raises
    ------
    ValueError
        If ``PLATFORM_SERIAL_NUMBER`` cannot be determined.

    """
    platform = platform or {}
    file_values = vocabularies.platform_from_file(first_ds.attrs)

    def config_or(field: str) -> object | None:
        value = platform.get(field)
        if value in (None, "", "None"):
            value = file_values.get(field)
        return None if value in (None, "", "None") else value

    serial = config_or("PLATFORM_SERIAL_NUMBER")
    if serial is None:
        msg = (
            "PLATFORM_SERIAL_NUMBER could not be determined: the basestation file "
            "has no platform_id and the mission config does not set "
            "platform.PLATFORM_SERIAL_NUMBER. It names the output file and OG1 id, "
            "so set it in the config (a serial number or a local nickname per OG1)."
        )
        raise ValueError(msg)

    resolved: dict[str, object] = {"PLATFORM_SERIAL_NUMBER": serial}

    for field in _PLATFORM_STRING_FIELDS:
        value = config_or(field)
        if value is None:
            from_file = field in vocabularies.PLATFORM_FROM_FILE
            warnings.warn(
                f"{field} not set in the mission config (platform.{field})"
                + (" or the basestation file" if from_file else "")
                + "; writing 'UNK'.",
                stacklevel=3,
            )
            value = "UNK"
        resolved[field] = value

    depth = platform.get("PLATFORM_DEPTH_RATING")
    if depth not in (None, "", "None"):
        resolved["PLATFORM_DEPTH_RATING"] = depth
    else:
        warnings.warn(
            "PLATFORM_DEPTH_RATING not set in the mission config "
            "(platform.PLATFORM_DEPTH_RATING); it is numeric, so the variable is "
            "omitted rather than written as 'UNK'.",
            stacklevel=3,
        )

    model_vocab = platform.get("platform_model_vocabulary")
    if model_vocab not in (None, "", "None"):
        resolved["platform_model_vocabulary"] = model_vocab

    return resolved


# OG1-mandatory variables that keep_variables must never drop (plus the PLATFORM_*,
# SENSOR_* and DEPLOYMENT_* families, matched by prefix below).
_MANDATORY_OG1_VARS = frozenset(
    {
        "TIME",
        "LATITUDE",
        "LONGITUDE",
        "DEPTH",
        "TRAJECTORY",
        "WMO_IDENTIFIER",
        "PROFILE_NUMBER",
        "PHASE",
    }
)
_MANDATORY_OG1_PREFIXES = ("PLATFORM_", "SENSOR_", "DEPLOYMENT_")


def apply_keep_variables(ds: xr.Dataset, keep: list[str]) -> xr.Dataset:
    """Subset the dataset to a science-variable allow-list, keeping OG1 essentials.

    The requested ``keep`` names are retained, plus every OG1-mandatory variable
    and the ``_QC`` companion of every kept variable. Dropped science variables are
    warned. Coordinates are retained by xarray.

    Parameters
    ----------
    ds : xarray.Dataset
        The converted OG1 dataset.
    keep : list of str
        Science variables the user asked to keep.

    Returns
    -------
    xarray.Dataset
        The subset dataset; every OG1-mandatory variable present in ``ds`` survives.

    """
    requested = set(keep)
    kept = set()
    for name in ds.data_vars:
        mandatory = name in _MANDATORY_OG1_VARS or name.startswith(
            _MANDATORY_OG1_PREFIXES
        )
        qc_parent = name[:-3] if name.endswith("_QC") else None
        if (
            name in requested
            or mandatory
            or (qc_parent is not None and qc_parent in requested)
        ):
            kept.add(name)
    dropped = sorted(name for name in ds.data_vars if name not in kept)
    if dropped:
        warnings.warn(
            f"keep_variables dropped science variables: {dropped}", stacklevel=2
        )
    return ds[sorted(kept)]


def convert_to_OG1(
    list_of_datasets: list[xr.Dataset] | xr.Dataset,
    *,
    contributors: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
    platform: dict[str, object] | None = None,
    global_attributes: dict[str, object] | None = None,
    mode: str = "delayed",
) -> tuple[xr.Dataset, list[str]]:
    """Convert Seaglider basestation datasets to OG1 format.
    Processes a list of xarray datasets or a single xarray dataset, converts them to OG1 format,
    concatenates the datasets, sorts by time, and applies attributes. Main conversion function that
    processes basestation datasets, applies OG1 standardization, concatenates multiple datasets,
    and adds global attributes.

    Parameters
    ----------
    list_of_datasets : list of xarray.Dataset or xarray.Dataset
        A list of xarray datasets or a single xarray dataset in basestation format.
    contributors : sequence of dict, optional
        Contributor records (``name``, ``role`` and optional ``email``, ``orcid``)
        merged with those already on the files. When None, contributors come from
        the files' own attributes; no package default is applied. Default is None.
    institutions : sequence of dict, optional
        Institution records (``name``, ``role`` and optional ``id``) merged with
        those on the files and resolved against the EDMO registry. Default is None.
    platform : dict of str to object, optional
        Platform fields from the mission config (``PLATFORM_SERIAL_NUMBER``,
        ``PLATFORM_MODEL``, ``PLATFORM_MAKER``, ``PLATFORM_DEPTH_RATING``,
        ``GLIDER_FIRMWARE_VERSION``, ``LANDSTATION_VERSION``, ``WMO_IDENTIFIER``,
        ``platform_model_vocabulary``). Config values override file-derived ones.
        Default is None.
    global_attributes : dict of str to object, optional
        Global attributes written verbatim into the output (nulls skipped). A key
        that collides with a converter-derived global raises. Default is None.
    mode : str, optional
        Data mode, ``"delayed"`` (default) or ``"realtime"``. Sets the ``id``
        suffix (``delayed`` or ``R``) and so the output filename, per the OG1
        manual, which defines no separate data-mode attribute. Default is "delayed".

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        A tuple containing:
        - ds_og1 (xarray.Dataset): The concatenated and processed dataset in OG1 format.
        - varlist (list of str): A list of variable names from the input datasets.

    """
    if isinstance(contributors, Mapping):
        msg = (
            "convert_to_OG1(contributors=...) is now a list of records "
            "[{'name': ..., 'role': ..., 'email': ..., 'orcid': ...}], not a dict "
            "of OG1 attributes. See CHANGELOG."
        )
        raise TypeError(msg)

    global_attributes = global_attributes or {}
    collisions = _DERIVED_GLOBALS.intersection(global_attributes)
    if collisions:
        msg = (
            "global_attributes may not set converter-derived keys: "
            f"{sorted(collisions)}. Remove them from the mission config."
        )
        raise ValueError(msg)

    if mode not in _MODE_SUFFIX:
        msg = f"mode must be one of {sorted(_MODE_SUFFIX)}, not {mode!r}."
        raise ValueError(msg)

    print(f"Start converting {len(list_of_datasets)} raw datasets to OG1 format ...")

    if not isinstance(list_of_datasets, list):
        list_of_datasets = [list_of_datasets]

    processed_datasets = []
    firstrun = False

    varlist = []
    # This would be faster if we concatenated the basestation files first, and then processed them.
    # But we need to process them first to get the dive number, assign GPS (could be after), ?

    # Find dimensions to merge across all datasets
    ctd_dim, dims_to_merge, all_dims = tools._get_merge_dimensions(list_of_datasets)

    # Create a mapping from original variable names to OG1 variable names for all variables across the datasets
    OG1_mapping = tools.OG1_name_mapping(list_of_datasets, ctd_dim, dims_to_merge)

    # print the sumary of variables assigned or not assigned to the dataset
    tools.print_OG1_mapping_summary(OG1_mapping, ctd_dim, dims_to_merge, all_dims)

    for ds1_base in tqdm(list_of_datasets, desc="Processing datasets", unit="dataset"):
        varlist = list(set(varlist + list(ds1_base.variables)))
        ds_new, attr_warnings = process_dataset(
            ds1_base, OG1_mapping, dims_to_merge=dims_to_merge, firstrun=firstrun
        )
        if ds_new:
            processed_datasets.append(ds_new)
            firstrun = False
        else:
            _log.warning(
                f"Dataset for dive number {ds1_base.attrs['dive_number']} is empty or invalid."
            )

    if not processed_datasets:
        raise ValueError(
            "No valid datasets were processed. Check the input datasets "
            "and the warnings from coordinate validation."
        )

    ds_og1 = xr.concat(processed_datasets, dim="N_MEASUREMENTS")
    ds_og1 = ds_og1.sortby("TIME")

    # Add sensor information to the dataset - can be done on the concatenated data
    # -----------------------------------------------------------------------------
    sensor_dict = tools.gather_sensor_info(list_of_datasets)
    # delete old sensor attribute if it exists and add new one
    for var in ds_og1.data_vars:
        if "sensor" in ds_og1[var].attrs:
            del ds_og1[var].attrs["sensor"]
    ds_og1 = tools.add_sensor_to_dataset(ds_og1, sensor_dict, OG1_mapping)

    # Apply attributes
    ordered_attributes = update_dataset_attributes(
        list_of_datasets[0], people=contributors, institutions=institutions
    )
    for key, value in ordered_attributes.items():
        if value is None:
            warnings.warn(
                f"{key} is missing; writing an empty string. Set it in the mission "
                "config to populate it.",
                stacklevel=2,
            )
            value = ""
        ds_og1.attrs[key] = value

    ### Add information needed/used for hydrodynamic (flight) model (hdm)
    hdm_parameters = tools.extract_hdm_parameters(list_of_datasets)
    ds_og1 = tools.add_hdm_parameters(ds_og1, hdm_parameters)

    # Resolve platform fields from the config and the first file (no silent
    # fallbacks: missing serial raises, other strings warn + "UNK", the numeric
    # depth rating is omitted rather than written as a string).
    platform_fields = _resolve_platform(list_of_datasets[0], platform)
    platform_serial_number = platform_fields["PLATFORM_SERIAL_NUMBER"]

    ds_og1["PLATFORM_SERIAL_NUMBER"] = platform_serial_number
    ds_og1["PLATFORM_SERIAL_NUMBER"].attrs["long_name"] = "glider serial number"

    # ---- Added some more mandatory variables from OG1 ----
    ds_og1["PLATFORM_MODEL"] = platform_fields["PLATFORM_MODEL"]
    ds_og1["PLATFORM_MODEL"].attrs["long_name"] = "model of the glider"
    if "platform_model_vocabulary" in platform_fields:
        ds_og1["PLATFORM_MODEL"].attrs["platform_model_vocabulary"] = platform_fields[
            "platform_model_vocabulary"
        ]

    ds_og1["PLATFORM_MAKER"] = platform_fields["PLATFORM_MAKER"]
    ds_og1["PLATFORM_MAKER"].attrs["long_name"] = "glider manufacturer"

    if "PLATFORM_DEPTH_RATING" in platform_fields:
        ds_og1["PLATFORM_DEPTH_RATING"] = platform_fields["PLATFORM_DEPTH_RATING"]
        ds_og1["PLATFORM_DEPTH_RATING"].attrs["long_name"] = "maximum rated depth"

    ds_og1["GLIDER_FIRMWARE_VERSION"] = platform_fields["GLIDER_FIRMWARE_VERSION"]
    ds_og1["GLIDER_FIRMWARE_VERSION"].attrs["long_name"] = "glider firmware version"

    ds_og1["LANDSTATION_VERSION"] = platform_fields["LANDSTATION_VERSION"]
    ds_og1["LANDSTATION_VERSION"].attrs["long_name"] = "version of the landstation"

    ds_og1["WMO_IDENTIFIER"] = platform_fields["WMO_IDENTIFIER"]
    ds_og1["WMO_IDENTIFIER"].attrs["long_name"] = "wmo id"

    # Trajectory
    ds_og1["TRAJECTORY"] = (
        ds_og1["PLATFORM_SERIAL_NUMBER"] + "_" + ds_og1.attrs["start_date"]
    )
    ds_og1["TRAJECTORY"].attrs["long_name"] = "trajectory name"
    ds_og1["TRAJECTORY"].attrs["cf_role"] = "trajectory_id"

    ds_og1["DEPLOYMENT_LATITUDE"] = xr.DataArray(
        ds_og1.LATITUDE.values[~np.isnan(ds_og1.LATITUDE)][0],
        attrs={"long_name": "latitude of deployment"},
    )
    ds_og1["DEPLOYMENT_LONGITUDE"] = xr.DataArray(
        ds_og1.LONGITUDE.values[~np.isnan(ds_og1.LONGITUDE)][0],
        attrs={"long_name": "longitude of deployment"},
    )
    ds_og1["DEPLOYMENT_TIME"] = xr.DataArray(
        ds_og1.TIME.values[~np.isnan(ds_og1.TIME)][0],
        attrs={"long_name": "time of deployment"},
    )

    # Remove attributes from TIME_GPS
    if "TIME_GPS" in ds_og1.variables:
        ds_og1["TIME_GPS"].attrs = {}
    # ---- -------------------------------------------- ----

    # Update time_coverage attributes
    # EFW note: 2025-01-31
    # CHECK LOGIC HERE: Should we be using the first and last time from the first and last dive?
    # Or is time_coverage_start from the base station file a better time to use?
    # Or is there an earlier TIME_GPS timestamp?
    tstart_in_numpy_datetime64 = ds_og1["TIME"][0]
    tend_in_numpy_datetime64 = ds_og1["TIME"][-1]
    tstart_str = utilities._clean_time_string(
        np.datetime_as_string(tstart_in_numpy_datetime64, unit="s")
    )
    tend_str = utilities._clean_time_string(
        np.datetime_as_string(tend_in_numpy_datetime64, unit="s")
    )
    _log.info("Start of mission from TIME[0]: " + tstart_str)
    _log.info("End of mission from TIME[-1]: " + tend_str)
    ds_og1.attrs["time_coverage_start"] = (
        tstart_str  # ds_og1.TIME[0].values.strftime('%Y%m%dT%H%M%S')
    )
    ds_og1.attrs["time_coverage_end"] = (
        tend_str  # ds_og1.TIME[-1].values.strftime('%Y%m%dT%H%M%S')
    )
    ds_og1.attrs["date_created"] = utilities._clean_time_string(
        ds_og1.attrs["date_created"]
    )

    # Update geospatial attributes
    lat_min = ds_og1.LATITUDE.min().values
    lat_max = ds_og1.LATITUDE.max().values
    lon_min = ds_og1.LONGITUDE.min().values
    lon_max = ds_og1.LONGITUDE.max().values
    ds_og1.attrs["geospatial_lat_min"] = lat_min
    ds_og1.attrs["geospatial_lat_max"] = lat_max
    ds_og1.attrs["geospatial_lon_min"] = lon_min
    ds_og1.attrs["geospatial_lon_max"] = lon_max
    depth_min = ds_og1.DEPTH.min().values
    depth_max = ds_og1.DEPTH.max().values
    ds_og1.attrs["geospatial_vertical_min"] = depth_min
    ds_og1.attrs["geospatial_vertical_max"] = depth_max

    # Construct the unique identifier attribute. The data-mode suffix (delayed/R)
    # is the only place OG1 records data mode; there is no data-mode attribute.
    id = f"{platform_serial_number}_{ds_og1.start_date}_{_MODE_SUFFIX[mode]}"
    ds_og1.attrs["id"] = id

    # Write config global attributes verbatim (nulls skipped). Collisions with
    # converter-derived keys were already rejected at the top of this function.
    for key, value in global_attributes.items():
        if value is not None:
            ds_og1.attrs[key] = value

    # Re-fix QC flags the concat re-promoted to float, then optimise dtypes once on the
    # fully-assembled dataset (coordinates and post-concat variables included).
    for qc_name in [v for v in ds_og1.variables if v[-2:].lower() == "qc"]:
        if qc_name[:-3] in ds_og1.variables:
            ds_og1 = tools.convert_qc_flags(ds_og1, qc_name)
    ds_og1 = tools.set_best_dtype(ds_og1)

    return ds_og1, OG1_mapping


_log = logging.getLogger(__name__)


def process_dataset(
    ds1_base: xr.Dataset,
    OG1_mapping: pd.DataFrame,
    dims_to_merge: list[str],
    firstrun: bool = False,
) -> tuple[
    xr.Dataset,  # Processed dataset with renamed variables, assigned attributes, and additional information
    list[str],  # List of warnings related to attribute assignments
    pd.DataFrame,  # Dataset containing variables starting with 'sg_cal'
]:
    """Processes a dataset by performing a series of transformations and extractions.

    Parameters
    ----------
    ds1_base : xarray.Dataset
        The input dataset from a basestation file, containing various attributes and variables.
    dims_to_merge : list[str]
        List of dimensions to merge.
    firstrun : bool, optional
        Indicates whether this is the first run of the processing pipeline. Default is False.

    Returns
    -------
    tuple
        A tuple containing:
        - ds_new (xarray.Dataset): The processed dataset with renamed variables, assigned attributes,
          converted units, and additional information such as GPS info and dive number.
        - attr_warnings (list[str]): A list of warnings related to attribute assignments.
        - OG1_mapping (pd.DataFrame): A DataFrame containing the mapping of original variable names to OG1 variable names.

    Notes
    -----
    - The function performs the following steps:
        1. Handles and splits the inputs:
            - Extracts the dive number from the attributes.
            - Splits the dataset by unique dimensions.
            - Extracts the gps_info from the split dataset.
            - Extracts variables starting with 'sg_cal' (originally from sg_calib_constants.m).
        2. Renames the dataset dimensions, coordinates, and variables according to OG1:
            - Extracts and renames dimensions for 'sg_data_point' (N_MEASUREMENTS).
            - Renames variables according to the OG1 vocabulary.
            - Assigns variable attributes according to OG1 and logs warnings for conflicts.
            - Converts units in the dataset (e.g., cm/s to m/s) where possible.
            - Converts QC flags to int8.
        3. Adds new variables:
            - Adds GPS info as LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS (increasing the length of N_MEASUREMENTS).
            - Adds the divenum as a variable of length N_MEASUREMENTS.
            - Adds the PROFILE_NUMBER (odd for dives, even for ascents).
            - Adds the PHASE of the dive (1 for ascent, 2 for descent, 3 for between the first two surface points).
            - Adds the DEPTH_Z with positive up.
        4. Returns the processed dataset, attribute warnings, and categorized datasets.

    - The function sorts the dataset by TIME and may exhibit undesired behavior if there are not two surface GPS fixes before a dive.

    """
    # Check if the dataset has 'LONGITUDE' as a coordinate
    ds1_base = utilities._validate_coords(ds1_base)
    if ds1_base is None or len(ds1_base.variables) == 0:
        return (
            xr.Dataset(),
            [],
        )
    # Split the dataset by unique dimensions
    split_ds = tools.split_by_unique_dims(ds1_base)
    # only consider dimensions from dims_to_merge that are present in the dataset
    dims_to_merge = [dim for dim in dims_to_merge if dim in ds1_base.sizes]
    merged_ds = tools.merge_datasets_along_time(split_ds, dims_to_merge, firstrun)
    # Rename variables and attributes to OG1 vocabulary
    # -------------------------------------------------------------------
    # Use variables with dimension 'sg_data_point'
    # Must be after split_ds
    # map the original variable names to the OG1 variable names, and get the instrument type for each variable

    ds_new = standardise_OG10(merged_ds, OG1_mapping, firstrun)

    # Add new variables to the dataset (GPS, DIVE_NUMBER, PROFILE_NUMBER, PHASE)
    # -----------------------------------------------------------------------
    # Add the gps_info to the dataset
    # Must be after split_by_unique_dims and after rename_dimensions
    ds_gps = split_ds[("gps_info",)]
    ds_new = add_gps_info_to_dataset(ds_new, ds_gps)
    # Add the profile number (odd for dives, even for get_sgscents)
    ds_new = tools.assign_profile_number(ds_new, ds1_base)
    # Assign the phase of the dive (must be after adding divenum)
    ds_new = tools.assign_phase(ds_new)
    # Assign DEPTH_Z to the dataset where positive is up.
    ds_new = tools.calc_Z(ds_new)

    vars_to_remove = vocabularies.vars_to_remove
    vars_present_to_remove = [var for var in vars_to_remove if var in ds_new.variables]

    # Drop them
    ds_new = ds_new.drop_vars(vars_present_to_remove)
    if firstrun and vars_present_to_remove:
        _log.warning(f"Variables removed from dataset: {vars_present_to_remove}")
    elif firstrun:
        _log.info("No variables needed to be removed from the dataset.")

    attr_warnings: list[str] = []
    return ds_new, attr_warnings


def standardise_OG10(
    ds: xr.Dataset,
    og1_mapping: pd.DataFrame,
    firstrun: bool = False,
    unit_format: dict[str, str] = vocabularies.unit_str_format,
) -> xr.Dataset:
    """
    Standardize the dataset to OG1 format by renaming dimensions, variables, and assigning attributes.

    Applies OG1 vocabulary for variable names, units, and attributes.
    Performs unit conversions and QC flag standardization.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset to be standardized.
    firstrun : bool, optional
        Indicates whether this is the first run of the standardization process. Default is False.
    unit_format : dict of str, optional
        A dictionary mapping unit strings to their standardized format.
        Default is vocabularies.unit_str_format.

    Returns
    -------
    xarray.Dataset
        The standardized dataset in OG1 format.

    """
    dsa = xr.Dataset(attrs=ds.attrs.copy())
    newdim = vocabularies.dims_rename_dict["sg_data_point"]

    name_lookup = og1_mapping.set_index("original_name")["OG1_name"]

    unassigned_variables = []
    variables_without_og1_attributes = []

    for original_name in list(ds.data_vars) + list(ds.coords):
        # QC variables are handled with their corresponding root variable.
        if original_name.lower().endswith("_qc"):
            continue

        og1_name = name_lookup.get(original_name)

        # Only variables without a mapped OG1 name are skipped.
        if og1_name is None or pd.isna(og1_name):
            unassigned_variables.append(original_name)
            continue

        og1_name = str(og1_name)
        variable_values = ds[original_name].values

        # Use OG1 attributes when available. Otherwise, start without them.
        attributes = vocabularies.vocab_attrs.get(
            og1_name,
            {},
        ).copy()

        if not attributes:
            variables_without_og1_attributes.append(og1_name)

        # Convert units only when both source and target units are known.
        if "units" in ds[original_name].attrs and "units" in attributes:
            original_unit = tools.reformat_units_var(
                ds,
                original_name,
                unit_format,
            )
            target_unit = attributes["units"]

            if original_unit != target_unit:
                variable_values, converted_unit = tools.convert_units_var(
                    variable_values,
                    original_unit,
                    target_unit,
                    vocabularies.unit1_to_unit2,
                    firstrun,
                )
                attributes["units"] = converted_unit

        dsa[og1_name] = (
            [newdim],
            variable_values,
            attributes,
        )

        # Retain source attributes not supplied by the OG1 vocabulary.
        for attribute, value in ds[original_name].attrs.items():
            dsa[og1_name].attrs.setdefault(attribute, value)

        # Add the associated QC variable when present.
        original_qc_name = f"{original_name}_qc"
        og1_qc_name = f"{og1_name}_QC"

        if original_qc_name in ds.variables:
            dsa[og1_qc_name] = (
                [newdim],
                ds[original_qc_name].values,
                ds[original_qc_name].attrs.copy(),
            )

            dsa = tools.convert_qc_flags(
                dsa,
                og1_qc_name,
            )

    if firstrun:
        if unassigned_variables:
            _log.warning(
                "Variables without an assigned OG1 name: %s",
                sorted(set(unassigned_variables)),
            )
        else:
            _log.info("All variables have an assigned OG1 name.")

        if variables_without_og1_attributes:
            _log.warning(
                "OG1 variables without vocabulary attributes: %s",
                sorted(set(variables_without_og1_attributes)),
            )

    coordinate_names = [
        name
        for name in ("LONGITUDE", "LATITUDE", "DEPTH", "TIME")
        if name in dsa.variables
    ]

    if coordinate_names:
        dsa = dsa.set_coords(coordinate_names)

    dsa = tools.encode_times_og1(dsa)
    # dtype optimisation is deferred to convert_to_OG1, once on the concatenated dataset:
    # running it per dive lets the concat re-promote int8 QC flags back to float.
    return dsa


def extract_variables(ds: xr.Dataset) -> tuple[xr.Dataset, xr.Dataset, xr.Dataset]:
    """Split variables from the basestation file that have no dimensions into categorized datasets.

    This function further processes the variables from the basestation file that had no dimensions.
    It categorizes them based on their prefixes or characteristics into three groups:
    variables from `sg_calib_constants`, log files, and other mission/dive-specific values.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset. This function is designed to work on variables from the basestation
        file that had no dimensions, typically after being processed by `split_by_unique_dims`.

    Returns
    -------
    tuple of (xarray.Dataset, xarray.Dataset, xarray.Dataset)
        A tuple containing three xarray Datasets:
        - sg_cal : xarray.Dataset
            Dataset containing variables starting with 'sg_cal_' (originally from `sg_calib_constants.m`).
            The variables are renamed to remove the 'sg_cal_' prefix, so they can be accessed directly
            (e.g., `sg_cal.hd_a`).
        - dc_log : xarray.Dataset
            Dataset containing variables starting with 'log_'. These variables are typically from log files.
        - dc_other : xarray.Dataset
            Dataset containing other mission/dive-specific values. This includes depth-averaged currents
            and other variables like `magnetic_variation`.

    """
    sg_cal_vars = {var: ds[var] for var in ds.variables if var.startswith("sg_cal")}
    divecycle_other = {
        var: ds[var] for var in ds.variables if not var.startswith("sg_cal")
    }
    dc_log_vars = {var: ds[var] for var in divecycle_other if var.startswith("log_")}
    divecycle_other = {
        var: data for var, data in divecycle_other.items() if not var.startswith("log_")
    }

    # Create a new dataset with these variables, renaming to remove the leading 'sg_cal_'
    sg_cal = xr.Dataset(
        {var.replace("sg_cal_", ""): data for var, data in sg_cal_vars.items()}
    )
    dc_other = xr.Dataset(divecycle_other)
    dc_log = xr.Dataset(dc_log_vars)

    return sg_cal, dc_log, dc_other


def add_gps_info_to_dataset(ds: xr.Dataset, gps_ds: xr.Dataset) -> xr.Dataset:
    """Add GPS information (LATITUDE_GPS, LONGITUDE_GPS, TIME_GPS) to the dataset.

    The GPS values will be included within the N_MEASUREMENTS dimension, with non-NaN values
    only when GPS information is available. The dataset will be sorted by TIME.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset with renamed dimensions and variables, representing the main data.
    gps_ds : xarray.Dataset
        The dataset containing GPS information, typically extracted from the original
        basestation dataset.

    Returns
    -------
    xarray.Dataset
        The updated dataset with added GPS information. This includes values for
        LATITUDE_GPS, LONGITUDE_GPS, and TIME_GPS only when GPS information is available.

    Notes
    -----
    - The dataset is sorted by TIME (or ctd_time from the original basestation dataset).
    - If the data are not sorted by time, there may be unintended consequences.
    - The function assumes that the GPS dataset contains variables `log_gps_lon`,
      `log_gps_lat`, and `log_gps_time` for longitude, latitude, and time respectively.
    - The function uses the `sg_data_point` dimension as defined in the OG1 vocabulary.

    """
    # Set new dimension name
    newdim = vocabularies.dims_rename_dict["sg_data_point"]

    # Create a new dataset with GPS information
    gps_ds = xr.Dataset(
        {
            "LONGITUDE": ([newdim], gps_ds["log_gps_lon"].values),
        },
        coords={
            "LATITUDE": ([newdim], gps_ds["log_gps_lat"].values),
            "TIME": ([newdim], gps_ds["log_gps_time"].values),
            "DEPTH": ([newdim], np.full(len(gps_ds["log_gps_lat"]), 0)),
        },
    )
    gps_ds = gps_ds.set_coords("LONGITUDE")

    gps_ds["LATITUDE_GPS"] = (
        [newdim],
        gps_ds.LATITUDE.values,
        vocabularies.vocab_attrs["LATITUDE_GPS"],
        {"dtype": ds["LATITUDE"].dtype},
    )
    gps_ds["LONGITUDE_GPS"] = (
        [newdim],
        gps_ds.LONGITUDE.values,
        vocabularies.vocab_attrs["LONGITUDE_GPS"],
        {"dtype": ds["LONGITUDE"].dtype},
    )
    gps_ds["TIME_GPS"] = (
        [newdim],
        gps_ds.TIME.values,
        vocabularies.vocab_attrs["TIME_GPS"],
        {"dtype": ds["TIME"].dtype},
    )

    # Concatenate ds and gps_ds
    datasets = []
    datasets.append(ds)
    datasets.append(gps_ds)
    ds_new = xr.concat(datasets, dim=newdim, data_vars="all")
    ds_new = ds_new.sortby("TIME")

    return ds_new


##-----------------------------------------------------------------------------------------
## Editing attributes
##-----------------------------------------------------------------------------------------
def update_dataset_attributes(
    ds: xr.Dataset,
    people: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
) -> dict[str, str]:
    """Update the attributes of the dataset based on the provided attribute input.

    Processes contributor information, time attributes, and applies OG1
    global attribute vocabulary in the correct order.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset whose attributes need to be updated.
    people : sequence of dict, optional
        Config contributor records to merge with the dataset's own. Default is None.
    institutions : sequence of dict, optional
        Config institution records to merge with the dataset's own. Default is None.

    Returns
    -------
    dict
        A dictionary of ordered attributes with updated values.

    """
    attr_as_is = vocabularies.global_attrs["attr_as_is"]
    attr_to_add = vocabularies.global_attrs["attr_to_add"]
    attr_to_rename = vocabularies.global_attrs["attr_to_rename"]
    order_of_attr = vocabularies.order_of_attr
    mandatory_attr = vocabularies.global_attrs["attr_mandatory"]

    # Extract creators and contributors and institution, then reformulate strings
    contrib_attrs = get_contributors(ds, people=people, institutions=institutions)

    # Extract time attributes and reformat basic time strings
    time_attrs = get_time_attributes(ds)

    # Rename some
    renamed_attrs = extract_attr_to_rename(ds, attr_to_rename)

    # Attributes to keep
    keep_attrs = extract_attr_to_keep(ds, attr_as_is)

    # Combine all attributes
    new_attributes = {
        **attr_to_add,
        **contrib_attrs,
        **time_attrs,
        **renamed_attrs,
        **keep_attrs,
        **attr_to_add,
    }

    # Add mandatory attributes if they are not already present
    for attr in mandatory_attr:
        if attr not in new_attributes:
            new_attributes[attr] = mandatory_attr[attr]

    # Reorder attributes according to vocabularies.order_of_attr
    ordered_attributes = {
        attr: new_attributes[attr] for attr in order_of_attr if attr in new_attributes
    }

    # Add any remaining attributes that were not in the order_of_attr list
    for attr in new_attributes:
        if attr not in ordered_attributes:
            ordered_attributes[attr] = new_attributes[attr]

    return ordered_attributes


def get_contributors(
    ds: xr.Dataset,
    people: Sequence[dict] | None = None,
    institutions: Sequence[dict] | None = None,
) -> dict[str, str]:
    """Build OG1 contributor and institution attributes.

    Contributors and institutions already on the dataset (``creator_*``,
    ``contributor_*`` and the basestation ``institution`` string) are parsed into
    records, the mission config's ``people`` and ``institutions`` are appended,
    duplicates are consolidated on (name, role) with empty-role fill-in,
    institutions are resolved against the EDMO registry, and everything is
    formatted once into aligned comma-separated lists. No role or EDMO id is ever
    invented; gaps are warned.

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset carrying the source contributor/institution attributes.
    people : sequence of dict, optional
        Config contributor records (``name``, ``role`` and optional ``email``,
        ``orcid``). Default is None.
    institutions : sequence of dict, optional
        Config institution records (``name``, ``role`` and optional ``id``).
        Default is None.

    Returns
    -------
    dict of str to str
        The ``contributor_*`` and ``contributing_institutions*`` attributes.

    """
    config_people = [
        {
            "name": person.get("name", ""),
            "email": person.get("email", "") or "",
            "id": contributors.normalize_orcid(person.get("orcid")),
            "role": person.get("role", "") or "",
        }
        for person in (people or [])
    ]
    merged_people = contributors.consolidate(
        contributors.parse_contributors(ds.attrs) + config_people
    )
    for person in merged_people:
        if not (person.get("role") or ""):
            warnings.warn(
                f"no role for contributor {person.get('name')!r}; set one in the "
                "mission config (contributors: - name: ... role: ...).",
                stacklevel=2,
            )
    if not any(
        contributors.normalize_role(person.get("role")) == "PI"
        for person in merged_people
    ):
        warnings.warn(
            "no contributor has the role PI; OG1 requires a principal investigator.",
            stacklevel=2,
        )

    file_institutions = contributors.parse_institutions(ds.attrs)
    if "institution" in ds.attrs:
        file_institutions = [
            {"name": ds.attrs["institution"], "role": "", "id": ""},
            *file_institutions,
        ]
    config_institutions = [
        {
            "name": institution.get("name", ""),
            "role": institution.get("role", "") or "",
            "id": institution.get("id"),
        }
        for institution in (institutions or [])
    ]
    merged_institutions = contributors.consolidate(
        contributors.enrich_institutions(file_institutions + config_institutions)
    )
    if not any(
        contributors.normalize_role(institution.get("role")) == "Operator"
        for institution in merged_institutions
    ):
        warnings.warn(
            "no institution has the role Operator; OG1 requires an operating "
            "institution.",
            stacklevel=2,
        )

    attributes_dict: dict[str, str] = {}
    attributes_dict.update(contributors.format_contributors(merged_people))
    attributes_dict.update(contributors.format_institutions(merged_institutions))
    return attributes_dict


def get_time_attributes(ds: xr.Dataset) -> dict[str, str]:
    """Extract and clean time-related attributes from the dataset.

    Converts various time formats to OG1-standard YYYYMMDDTHHMMSS format
    and adds date_modified timestamp.

    Parameters
    ----------
    ds : xarray.Dataset
        The input dataset containing various attributes.

    Returns
    -------
    dict
        A dictionary containing cleaned time-related attributes.

    """
    time_attrs = {}
    time_attr_list = [
        "time_coverage_start",
        "time_coverage_end",
        "date_created",
        "start_time",
    ]
    for attr in time_attr_list:
        if attr in ds.attrs:
            val1 = ds.attrs[attr]
            if isinstance(val1, (int, float)):
                val1 = datetime.utcfromtimestamp(val1).strftime("%Y%m%dT%H%M%S")
            if isinstance(val1, str) and ("-" in val1 or ":" in val1):
                val1 = utilities._clean_time_string(val1)
            time_attrs[attr] = val1
    time_attrs["date_modified"] = datetime.now().strftime("%Y%m%dT%H%M%S")

    # Handle start_date attribute
    if "start_time" in time_attrs:
        time_attrs["start_date"] = time_attrs.pop("start_time")
    if "start_date" not in time_attrs:
        time_attrs["start_date"] = time_attrs["time_coverage_start"]

    return time_attrs


def extract_attr_to_keep(
    ds1: xr.Dataset, attr_as_is: list[str] = vocabularies.global_attrs["attr_as_is"]
) -> dict[str, str]:
    """Extract attributes to retain unchanged.

    Parameters
    ----------
    ds1 : xarray.Dataset
        Source dataset.
    attr_as_is : list
        Attribute names to retain without modification.

    Returns
    -------
    dict
        Retained attributes.

    """
    retained_attrs = {}

    # Retain attributes based on attr_as_is
    for attr in attr_as_is:
        if attr in ds1.attrs:
            retained_attrs[attr] = ds1.attrs[attr]

    return retained_attrs


def extract_attr_to_rename(
    ds1: xr.Dataset,
    attr_to_rename: dict[str, str] = vocabularies.global_attrs["attr_to_rename"],
) -> dict[str, str]:
    """Extract and rename attributes according to OG1 vocabulary.

    Parameters
    ----------
    ds1 : xarray.Dataset
        Source dataset.
    attr_to_rename : dict
        Mapping of new_name: old_name for attribute renaming.

    Returns
    -------
    dict
        Renamed attributes.

    """
    renamed_attrs = {}
    # Rename attributes based on values_to_rename
    for new_attr, old_attr in attr_to_rename.items():
        if old_attr in ds1.attrs:
            renamed_attrs[new_attr] = ds1.attrs[old_attr]

    return renamed_attrs


def process_and_save_data(
    input_location: str,
    save: bool = False,
    output_dir: str = ".",
    run_quietly: bool = True,
) -> xr.Dataset:
    """Process and save data from the specified input location.

    This function loads and concatenates datasets from the server, converts them to OG1 format,
    and saves the resulting dataset to a NetCDF file. If the file already exists, the function
    will prompt the user to decide whether to overwrite it or not.

    Parameters
    ----------
    input_location : str
        The location of the input data to be processed.
    save : bool, optional
        Whether to save the processed dataset to a file. Default is False.
    output_dir : str, optional
        The directory where the output file will be saved. Default is '.'.
    run_quietly : bool, optional
        If True, suppresses user prompts and assumes 'no' for overwriting files. Default is True.

    Returns
    -------
    xarray.Dataset
        The processed dataset.

    """
    # Load and concatenate all datasets from the server
    ds1_base = readers.load_first_basestation_file(input_location)

    # Convert the list of datasets to OG1
    ds1_og1, varlist = convert_to_OG1(ds1_base)
    output_file = os.path.join(output_dir, ds1_og1.attrs["id"] + ".nc")

    # Check if the file exists and delete it if it does
    if os.path.exists(output_file):
        if run_quietly:
            user_input = "no"
        else:
            user_input = input(
                f"File {output_file} already exists. Do you want to re-run and overwrite it? (yes/no): "
            )

        if user_input.lower() != "yes":
            print(f"File {output_file} already exists. Exiting the process.")
            _log.warning(f"File {output_file} already exists. Exiting the process.")
            ds_all = xr.open_dataset(output_file)
            return ds_all
        elif user_input.lower() == "yes":
            list_datasets = readers.load_basestation_files(input_location)
            ds_all, varlist = convert_to_OG1(list_datasets)
            os.remove(output_file)
            if save:
                writers.save_dataset(ds_all, output_file)
    else:
        print("Running the directory:", input_location)
        _log.info(f"Running the directory: {input_location}")
        list_datasets = readers.load_basestation_files(input_location)
        ds_all, varlist = convert_to_OG1(list_datasets)
        output_file = os.path.join(output_dir, ds_all.attrs["id"] + ".nc")
        if save:
            writers.save_dataset(ds_all, output_file)

        _log.info("===================================================")
        _log.info("input_var: Variables in original basestation files:")
        for varname in sorted(varlist):
            _log.info(f"{varname}")

        _log.info("=========================================")
        _log.info("output_var: Variables in OG1 format file:")
        for varname in sorted(ds_all.variables):
            _log.info(f"{varname}")

    return ds_all
