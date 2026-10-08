import logging
import re
from dateutil import parser
from datetime import date

import gsw
import numpy as np
import pandas as pd
import xarray as xr

from seagliderOG1 import vocabularies

_log = logging.getLogger(__name__)


# Variables measured directly by the CTD.
CTD_MEASUREMENT_VARIABLES = {
    "temperature",
    "temperature_raw",
    "conductivity",
    "conductivity_raw",
}

# Variables calculated using CTD measurements.
CTD_CALCULATED_VARIABLES = {
    "theta",
    "salinity",
    "salinity_raw",
    "sound_velocity",
    "sigma_theta",
    "sigma_t",
    "density",
    "density_insitu",
}

# Alternative names used for the same physical instrument.
INSTRUMENT_ALIASES = {
    "sbe41": {"sbe41", "sbect"},
}


def OG1_name_mapping(
    list_of_datasets: list[xr.Dataset],
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Create a mapping from original variable names to OG1 variable names.

    Include every unique variable name from all input datasets, including
    scalars, coordinates, QC variables, and variables without an OG1 mapping.
    The first occurrence of each name supplies its dimensions and attributes.

    Each row contains the original variable name, its OG1 name (None when
    unavailable), associated instrument, instrument type, original dimensions,
    and whether OG1 attributes are available.

    Individual time variables are consolidated into one ``time`` / ``TIME``
    row. Its ``original_dimension`` lists their dimensions and original names.

    QC variables inherit the instrument association of their corresponding
    measurement variable.

    Instrument assignment precedence:

    1. QC variables inherit their parent measurement's instrument.
    2. CTD measurement variables are assigned to the CTD.
    3. When ``ctd_pressure`` exists, calculated hydrographic variables are
       assigned to the CTD.
    4. The variable's ``instrument`` attribute is checked.
    5. Dimensions named ``<instrument>_data_point`` are checked.
    6. The variable name is checked for an instrument name or alias.

    Parameters
    ----------
    list_of_datasets
        Datasets immediately before calling ``standardise_OG10``.
        Instruments are collected from every dataset's global ``instrument``
        attribute, preserving first-seen order.

    Returns
    -------
    pandas.DataFrame
        Columns: ``original_name``, ``OG1_name``, ``instrument``,
        ``instrument_type``, ``original_dimension``, and
        ``has_OG1_attributes``.
    """
    all_sources: dict[str, xr.DataArray] = {}
    all_dimensions: set[str] = set()
    instruments: list[str] = []

    for dataset in list_of_datasets:
        all_dimensions.update(dataset.dims)

        for instrument in dataset.attrs.get("instrument", "").split():
            if instrument not in instruments:
                instruments.append(instrument)

        for variable_name in dataset.variables:
            all_sources.setdefault(variable_name, dataset[variable_name])

    standard_names = vocabularies.standard_names
    sensor_vocabs = vocabularies.sensor_vocabs
    has_ctd_pressure = "ctd_pressure" in all_sources

    def variable_exists(variable_name: str) -> bool:
        """Check whether a variable exists in any input dataset."""
        return variable_name in all_sources

    def get_source(variable_name: str) -> xr.DataArray:
        """Get the first occurrence of a variable across input datasets."""
        return all_sources[variable_name]

    def get_qc_parent_name(variable_name: str) -> str | None:
        """Return the measurement name corresponding to a *_qc variable."""
        if variable_name.lower().endswith("_qc"):
            return variable_name[:-3]

        return None

    def get_instrument_names(instrument: str) -> set[str]:
        """Get the lowercase instrument name and its aliases."""
        return INSTRUMENT_ALIASES.get(
            instrument.lower(),
            {instrument.lower()},
        )

    def get_instrument_type(instrument: str | None) -> str | None:
        """Get an instrument's sensor type from the OG1 vocabulary."""
        if instrument is None:
            return None

        og1_instrument_name = standard_names.get(instrument)

        if og1_instrument_name is None:
            return None

        return sensor_vocabs.get(
            og1_instrument_name,
            {},
        ).get("sensor_type")

    def get_ctd_instrument() -> str | None:
        """Find the instrument identified as the CTD."""
        for instrument in instruments:
            instrument_type = get_instrument_type(instrument)

            if isinstance(instrument_type, str) and instrument_type.upper() == "CTD":
                return instrument

        return None

    ctd_instrument = get_ctd_instrument()

    def is_ctd_associated(variable_name: str) -> bool:
        """Determine whether a variable should be assigned to the CTD."""
        qc_parent = get_qc_parent_name(variable_name)

        if qc_parent is not None and variable_exists(qc_parent):
            return is_ctd_associated(qc_parent)

        lower_name = variable_name.lower()

        return (
            lower_name.startswith("ctd_")
            or lower_name in CTD_MEASUREMENT_VARIABLES
            or (has_ctd_pressure and lower_name in CTD_CALCULATED_VARIABLES)
        )

    def find_instrument(variable_name: str) -> str | None:
        """Find the instrument associated with a variable."""
        source = get_source(variable_name)
        lower_name = variable_name.lower()

        # QC variables inherit their parent measurement's instrument.
        qc_parent = get_qc_parent_name(variable_name)

        if qc_parent is not None and variable_exists(qc_parent):
            return find_instrument(qc_parent)

        dimensions = {dimension.lower() for dimension in source.dims}

        if ctd_instrument is not None and is_ctd_associated(variable_name):
            return ctd_instrument

        # Prefer an explicit instrument attribute.
        variable_instrument = source.attrs.get("instrument")

        if isinstance(variable_instrument, str):
            lower_attribute = variable_instrument.lower()

            for instrument in instruments:
                if lower_attribute in get_instrument_names(instrument):
                    return instrument

        # Match <instrument>_data_point dimensions.
        for instrument in instruments:
            instrument_names = get_instrument_names(instrument)

            if any(f"{name}_data_point" in dimensions for name in instrument_names):
                return instrument

        # Match instrument names embedded in the variable name.
        for instrument in instruments:
            instrument_names = get_instrument_names(instrument)

            if any(
                lower_name.startswith(f"{name}_") or f"_{name}_" in lower_name
                for name in instrument_names
            ):
                return instrument

        return None

    def get_name_candidates(
        variable_name: str,
        instrument: str | None,
    ) -> list[str]:
        """Generate vocabulary candidates by removing prefixes."""
        prefixes = {
            "eng_",
            "instrument_",
            "ctd_",
        }

        if instrument is not None:
            prefixes.update(f"{name}_" for name in get_instrument_names(instrument))

        candidates = [variable_name]

        # Iterate over the growing list to support multiple prefixes,
        # such as eng_<instrument>_<variable>.
        for candidate in candidates:
            for prefix in prefixes:
                if candidate.lower().startswith(prefix):
                    stripped_name = candidate[len(prefix) :]

                    if stripped_name and stripped_name not in candidates:
                        candidates.append(stripped_name)

        return candidates

    def find_direct_og1_name(
        variable_name: str,
        instrument: str | None,
    ) -> str | None:
        """Find an explicit vocabulary match."""
        for candidate in get_name_candidates(variable_name, instrument):
            og1_name = standard_names.get(candidate)

            if og1_name is not None:
                return og1_name

        return None

    def get_og1_base_name(
        variable_name: str,
        instrument: str | None,
    ) -> str | None:
        """Find or derive the OG1 vocabulary name for a variable."""
        # Prefer an explicit entry, including explicit QC entries.
        og1_name = find_direct_og1_name(variable_name, instrument)

        if og1_name is not None:
            return og1_name

        # Otherwise, derive a QC name from its parent measurement.
        qc_parent = get_qc_parent_name(variable_name)

        if qc_parent is not None:
            parent_og1_name = find_direct_og1_name(qc_parent, instrument)

            if parent_og1_name is not None:
                return f"{parent_og1_name}_QC"

        return None

    def variable_sort_key(variable_name: str) -> tuple[bool, bool]:
        """Place CTD measurements first and their QC variables second."""
        is_ctd = is_ctd_associated(variable_name)
        is_qc = get_qc_parent_name(variable_name) is not None

        return (not is_ctd, is_qc)

    # Include every unique variable; retain CTD copies on other dimensions.
    variable_names = list(all_sources)
    variable_names.sort(key=variable_sort_key)

    mapping = []
    og1_name_counts: dict[str, int] = {}

    for original_name in variable_names:
        source = get_source(original_name)
        instrument = find_instrument(original_name)
        base_og1_name = get_og1_base_name(original_name, instrument)

        og1_name = None

        if base_og1_name is not None:
            count = og1_name_counts.get(base_og1_name, 0) + 1
            og1_name_counts[base_og1_name] = count

            og1_name = base_og1_name if count == 1 else f"{base_og1_name}{count}"

        mapping.append(
            {
                "original_name": original_name,
                "OG1_name": og1_name,
                "instrument": instrument,
                "instrument_type": get_instrument_type(instrument),
                "original_dimension": ", ".join(source.dims),
            }
        )

    result = pd.DataFrame(
        mapping,
        columns=[
            "original_name",
            "OG1_name",
            "instrument",
            "instrument_type",
            "original_dimension",
        ],
    )

    # Collect dimensions and their associated time variable names separately.
    time_mask = (
        result["OG1_name"]
        .astype("string")
        .str.fullmatch(
            r"TIME[0-9]*",
            na=False,
        )
    )

    time_variables: dict[str, list[str]] = {}

    def add_time_variable(dimension: str, variable_name: str) -> None:
        """Add a time association without duplicates."""
        names = time_variables.setdefault(dimension, [])
        if variable_name not in names:
            names.append(variable_name)

    for variable_name in result.loc[time_mask, "original_name"]:
        for dimension in get_source(variable_name).dims:
            add_time_variable(dimension, variable_name)

    # Magnetometer measurements share the sg_data_point time variable(s).
    if "magnetometer_data_point" in all_dimensions:
        for variable_name in time_variables.get("sg_data_point", []):
            add_time_variable("magnetometer_data_point", variable_name)

    # Add explicit associations when both dimension and variable exist.
    for dimension, variable_name in {
        "gc_state": "gc_state_secs",
        "gc_event": "gc_st_secs",
        "gps_info": "log_gps_time",
        "auxCompass_data_point": "auxCompass_time",
        "depth_data_point": "depth_time",
    }.items():
        if dimension in all_dimensions and variable_name in all_sources:
            add_time_variable(dimension, variable_name)

    # Remove all associated time variables, including those without an
    # OG1 TIME mapping. Replace any existing "time" row below.
    time_variable_names = {
        variable_name for names in time_variables.values() for variable_name in names
    }

    remove_mask = (
        time_mask
        | result["original_name"].isin(time_variable_names)
        | result["original_name"].eq("time")
    )

    time_row = pd.DataFrame(
        [
            {
                "original_name": "time",
                "OG1_name": "TIME",
                "instrument": float("nan"),
                "instrument_type": float("nan"),
                "original_dimension": "",
            }
        ]
    )

    result = pd.concat(
        [result.loc[~remove_mask], time_row],
        ignore_index=True,
    )

    result["has_OG1_attributes"] = result["OG1_name"].apply(
        lambda name: (
            bool(vocabularies.vocab_attrs.get(name, {})) if pd.notna(name) else False
        )
    )

    return result, time_variables


def gather_sensor_info(list_of_datasets) -> dict:
    """Gathers sensor information from a list of OG1 base datasets.

    Extracts:
      - unique sensor names (from global 'instrument' attributes)
      - technical specs (from OG1_sensor_attrs.yaml vocabularies)
      - serial numbers + calibration dates (from calibcomm variables)

    Checks calibration information across all datasets. Missing information
    is reported once per sensor. Conflicting serial numbers or calibration
    dates are reported, and the first nonempty value is retained.
    Calibration variables not belonging to any listed sensor are reported.

    Parameters
    ----------
    list_of_datasets : iterable of xarray.Dataset
        The raw base datasets containing sensor metadata.

    Returns
    -------
    dict
        Dictionary with one key per sensor, each containing metadata.

    """
    datasets = list(list_of_datasets)

    # -------------------------------------------------------------------------
    # 1. Extract sensor names from the 'instrument' global attributes
    # -------------------------------------------------------------------------
    sensor_dict = {}

    for dataset in datasets:
        instrument = dataset.attrs.get("instrument")
        if instrument and instrument.strip():
            sensor_names = instrument.split()
            # Remove unneeded entries and initialize unique dictionary entries
            for sensor in sensor_names:
                if sensor != "magnetometer":
                    sensor_dict.setdefault(sensor, {})

    if not sensor_dict:
        print(
            "Warning: No sensors found in the combined instrument attributes. "
            "Add sensor names separated by spaces, "
            "for example: ds.attrs['instrument'] = 'sbe41 wlbb2f sbe43'."
        )

    # -------------------------------------------------------------------------
    # 2. Add technical specifications from OG1 vocabularies
    # -------------------------------------------------------------------------
    standard_names = vocabularies.standard_names
    sensor_vocabs = vocabularies.sensor_vocabs

    for sensor in sensor_dict.keys():
        if sensor in standard_names:
            new_name = standard_names[sensor]
            # Copy so calibration metadata does not modify shared vocabularies.
            sensor_dict[sensor] = dict(sensor_vocabs[new_name])
            print(
                f"Adding technical specifications for '{new_name}' "
                f"(sensor key: '{sensor}') from OG1_sensor_attrs.yaml"
            )
        else:
            print(
                f"Warning: Sensor '{sensor}' not found in standard names "
                "vocabulary. No technical specifications added."
            )

    # -------------------------------------------------------------------------
    # 3. Extract calibration information (serial number + calibration dates)
    # -------------------------------------------------------------------------
    # Index all calibcomms once to avoid scanning every dataset for each sensor.
    calibration_records = []
    records_by_name = {}
    for dataset_index, base in enumerate(datasets, start=1):
        for name in base.variables:
            if name.startswith("sg_cal_calibcomm"):
                record_index = len(calibration_records)
                record = (dataset_index, name, base[name])
                calibration_records.append(record)
                records_by_name.setdefault(name, []).append((record_index, record))

    sensor_nums = len(sensor_dict.keys())
    available_calibcomm = sorted(records_by_name)
    if len(available_calibcomm) > sensor_nums:
        print(
            "Warning: More distinct calibration variables found than sensors "
            "listed in the combined instrument attributes!\n"
            f"Calibration variables: {available_calibcomm}\n"
            f"Sensors: {list(sensor_dict)}"
        )

    def is_missing(value):
        return value is None or str(value).strip().lower() in {
            "",
            "none",
            "nan",
            "nat",
            "unknown",
            "n/a",
        }

    matched_records = set()
    for sensor, metadata in sensor_dict.items():
        # --- Determine calibcomm variable names -------------------------------
        del_caps = _del_capital_letters(sensor)
        candidate_names = {
            f"sg_cal_calibcomm_{sensor}",
            f"sg_cal_calibcomm_{del_caps}",
        }
        if metadata.get("sensor_type") == "CTD":
            candidate_names.add("sg_cal_calibcomm")
        elif metadata.get("sensor_type") == "Oxygen":
            candidate_names.update(
                {"sg_cal_calibcomm_optode", "sg_cal_calibcomm_oxygen"}
            )
        elif metadata.get("sensor_maker") == "WET Labs":
            candidate_names.add("sg_cal_calibcomm_wetlabs")

        observations = {"sensor_serial_number": [], "sensor_calibration_date": []}
        found_calibration_text = False
        matching_records = sorted(
            (
                entry
                for name in candidate_names
                for entry in records_by_name.get(name, ())
            ),
            key=lambda entry: entry[0],
        )
        # --- Extract serial number + calibration date --------------------------
        for record_index, (dataset_index, name, variable) in matching_records:
            matched_records.add(record_index)
            raw_value = variable.values.item()
            if isinstance(raw_value, bytes):
                raw_value = raw_value.decode("utf-8", errors="replace")
            if is_missing(raw_value):
                continue
            found_calibration_text = True
            serial_number, cal_info = extract_instrument_info(str(raw_value))
            for field, value in (
                ("sensor_serial_number", serial_number),
                ("sensor_calibration_date", cal_info),
            ):
                if not is_missing(value):
                    observations[field].append((value, dataset_index, name))

        # --- Check for changes across all matching calibcomms -------------------
        missing_fields = []
        for field, entries in observations.items():
            distinct = {}
            for value, dataset_index, name in entries:
                distinct.setdefault(str(value), []).append((dataset_index, name))
            if len(distinct) > 1:
                details = "; ".join(
                    f"{value!r} in {sources}" for value, sources in distinct.items()
                )
                print(f"Error: Conflicting {field} for sensor '{sensor}': {details}")
            if entries:
                metadata[field] = entries[0][0]
            else:
                missing_fields.append(field)

        if missing_fields:
            # Preserve the existing helper's missing-value defaults.
            default_serial, default_calibration = extract_instrument_info(None)
            defaults = {
                "sensor_serial_number": default_serial,
                "sensor_calibration_date": default_calibration,
            }
            for field in missing_fields:
                metadata[field] = defaults[field]
            reason = (
                "No calibration info found"
                if not found_calibration_text
                else f"Incomplete calibration info (missing {', '.join(missing_fields)})"
            )
            print(
                f"Warning: {reason} for sensor '{sensor}'. "
                f"Available calibration variables: {available_calibcomm}"
            )

    # --- Report calibcomms that do not belong to any listed sensor --------------
    unmatched = {}
    for record_index, (dataset_index, name, _) in enumerate(calibration_records):
        if record_index not in matched_records:
            unmatched.setdefault(name, []).append(dataset_index)
    for name, dataset_indices in unmatched.items():
        print(
            f"Warning: Calibration variable '{name}' in datasets "
            f"{dataset_indices} does not belong to any listed sensor."
        )

    return sensor_dict


def add_sensor_to_dataset(
    ds_og1, sensor_dict, OG1_mapping, firstrun=False
) -> xr.Dataset:
    """Adds sensor information from the provided sensor dictionary to the OG1 dataset.

    Parameters
    ----------
    ds_og1 : xarray.Dataset
        The OG1 dataset to which sensor information will be added.
    sensor_dict : dict
        A dictionary containing sensor metadata and associated variables.

    Returns
    -------
    xarray.Dataset
        The updated OG1 dataset with new sensor metadata variables added.

    Notes
    -----
    - Each sensor becomes a new dimensionless variable:
          SENSOR_<SENSOR_TYPE>_<SERIAL>
    - Attributes for each sensor variable are added from sensor_dict.
    - `sensor_info["variables"]` is handled later (point 3).

    """
    # -------------------------------------------------------------------------
    # 1. Create dimensionless sensor variables in the dataset
    # -------------------------------------------------------------------------
    for _, sensor_info in sensor_dict.items():
        # Build sensor variable name
        sensor_type = sensor_info["sensor_type"].upper().replace(" ", "_")
        serial = sensor_info["sensor_serial_number"]
        sensor_var_name = f"SENSOR_{sensor_type}_{serial}"

        # Create the variable (dimensionless DataArray)
        if firstrun:
            print(
                f"Adding sensor '{sensor_info['sensor_model']}' to the OG1 dataset with attributes"
            )
        ds_og1[sensor_var_name] = xr.DataArray(sensor_info["sensor_model"])

        # ---------------------------------------------------------------------
        # 2. Add sensor attributes (except 'variables')
        # ---------------------------------------------------------------------
        for attr, value in sensor_info.items():
            if attr == "variables":
                continue
            ds_og1[sensor_var_name].attrs[attr] = value

    # -------------------------------------------------------------------------
    # 3. Assign 'sensor' attribute to sensor-specific variables
    # -------------------------------------------------------------------------
    for _, mapping in OG1_mapping.iterrows():
        og1_name = str(mapping["OG1_name"])
        instrument = mapping["instrument"]

        # if the instrument is nan, skip this iteration
        if og1_name == "nan" or instrument == "nan" or pd.isna(instrument):
            continue

        sensor_type = sensor_dict[instrument]["sensor_type"].upper().replace(" ", "_")
        serial = sensor_dict[instrument]["sensor_serial_number"]
        ds_og1[og1_name].attrs["sensor"] = f"SENSOR_{sensor_type}_{serial}"

    return ds_og1


def _get_merge_dimensions(
    list_of_datasets: list[xr.Dataset],
) -> tuple[str, list[str]]:
    """Return the CTD dimension and dimensions to merge across all datasets as well as all dimensions present in the datasets"""
    list_of_datasets = list(list_of_datasets)
    dimensions = {
        dimension for dataset in list_of_datasets for dimension in dataset.sizes
    }
    instruments = list(
        dict.fromkeys(
            instrument
            for dataset in list_of_datasets
            for instrument in dataset.attrs.get("instrument", "").split()
        )
    )

    dims_to_merge = ["sg_data_point"]

    for instrument in instruments:
        instrument_dim = f"{instrument}_data_point"

        if instrument_dim in dimensions:
            dims_to_merge.append(instrument_dim)
        elif instrument == "sbe41" and "sbect_data_point" in dimensions:
            dims_to_merge.append("sbect_data_point")

    ctd_dimensions = []
    for dataset in list_of_datasets:
        if "longitude" not in dataset:
            continue

        longitude_dims = dataset["longitude"].dims
        if len(longitude_dims) != 1:
            raise ValueError(
                "Expected longitude to have exactly one dimension, "
                f"got {longitude_dims}."
            )

        ctd_dimensions.append(longitude_dims[0])

    ctd_dimensions = list(dict.fromkeys(ctd_dimensions))

    if not ctd_dimensions:
        raise ValueError("No input dataset contains longitude.")

    if len(ctd_dimensions) > 1:
        raise ValueError(
            "Longitude uses different CTD dimensions across datasets: "
            f"{ctd_dimensions}. A single ctd_dim cannot represent them."
        )

    ctd_dim = ctd_dimensions[0]
    dims_to_merge.append(ctd_dim)

    return ctd_dim, list(dict.fromkeys(dims_to_merge)), list(dict.fromkeys(dimensions))


def print_OG1_mapping_summary(
    OG1_mapping: pd.DataFrame,
    ctd_dim: str,
    merge_dims: list[str],
    all_dims: list[str],
) -> None:
    """Print dimensions, mapped variable counts, and vocabulary gaps."""
    has_og1_name = OG1_mapping["OG1_name"].notna() & OG1_mapping["OG1_name"].ne("")
    time_mask = OG1_mapping["OG1_name"].eq("TIME")

    variables = OG1_mapping.loc[has_og1_name & ~time_mask]

    for entry in OG1_mapping.loc[time_mask, "original_dimension"].explode():
        # Each entry has the format "dimension (original_time_name)".
        dimension, time_name = entry.rsplit(" (", 1)
        time_name = time_name.removesuffix(")")

        variable_count = (
            variables["original_dimension"]
            .apply(lambda dims: dimension in dims.split(", "))
            .sum()
        )

        print(
            f"Adding dimension '{dimension}' with time variable '{time_name}' "
            f"and {variable_count} non-time variables."
        )

    selected_dims = set(merge_dims) | {ctd_dim}
    unused_dims = [dim for dim in all_dims if dim not in selected_dims]

    print(
        f"\nThe following dimensions will not be merged into the new dataset: "
        f"{unused_dims}"
        "\nIf instrument data is missing, make sure its dimension follows the "
        "naming convention '<instrument>_data_point'"
        "\nfrom the ds.attrs['instrument'] list."
    )

    print(
        f"\nTotal: {len(variables)} non-time variables "
        f"+ {int(time_mask.sum())} combined TIME variable."
    )

    unassigned = OG1_mapping.loc[~has_og1_name, "original_name"].tolist()

    print(f"\nVariables without an assigned OG1 name: {unassigned}")

    missing_attrs = OG1_mapping.loc[
        has_og1_name & ~OG1_mapping["has_OG1_attributes"],
        "OG1_name",
    ].tolist()

    if missing_attrs:
        print(f"OG1 variables without vocabulary attributes: {missing_attrs}")


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
    """This function adds new variables 'PHASE' and 'PHASE_QC' to the dataset `ds`, which indicate the phase of each measurement. The phase is determined based on the pressure readings ('PRES') for each unique dive number ('dive_num').

    Note: In this formulation, we are only separating into dives and climbs based on when the glider is at the maximum depth. Future work needs to separate out the other phases: https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md and generate a PHASE_QC.
    Assigns phase values to the dataset based on pressure readings.

    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing 'dive_num' and 'PRES' variables.

    Returns
    -------
    xarray.Dataset: The dataset with an additional 'PHASE' variable, where:
    xarray.Dataset: The dataset with additional 'PHASE' and 'PHASE_QC' variables, where:
        - 'PHASE' indicates the phase of each measurement:
            - Phase 2 is assigned to measurements up to and including the maximum pressure point.
            - Phase 1 is assigned to measurements after the maximum pressure point.
        - 'PHASE_QC' is an additional variable with no QC applied.

    Note: In this formulation, we are only separating into dives and climbs based on when the glider is at the maximum depth.  Future work needs to separate out the other phases: https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md and generate a PHASE_QC

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


def _del_capital_letters(string):
    return "".join([char for char in string if not char.isupper()])


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
    """Splits an xarray dataset into multiple datasets based on the unique set of dimensions of the variables.

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
    return {dims: dataset for dims, dataset in unique_dims_datasets.items()}


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
    if old_unit in unit_format:
        new_unit = unit_format[old_unit]
    else:
        new_unit = old_unit
    return new_unit


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
    if old_unit in unit_format:
        new_unit = unit_format[old_unit]
    else:
        new_unit = old_unit
    return new_unit.strip()  # .casefold()


def convert_units_var(
    var_values: np.ndarray,
    current_unit: str,
    new_unit: str,
    unit1_to_unit2: dict = vocabularies.unit1_to_unit2,
    firstrun: bool = False,
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
    firstrun
        If ``True``, log a warning when no conversion information is found.

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

    if firstrun:
        _log.warning(
            "No conversion information found for %r to %r",
            current_unit,
            requested_unit,
        )

    return var_values, current_unit


def convert_qc_flags(dsa: xr.Dataset, qc_name: str) -> xr.Dataset:
    """Convert QC flag variables to proper integer format and update attributes.

    This function converts QC flag variables from string format to int8,
    handles NaN values appropriately, removes 'QC_' prefixes from flag meanings,
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
        # Add a long_name attribute to the QC variable
        dsa[qc_name].attrs["long_name"] = (
            dsa[var_name].attrs.get("long_name", "") + " quality flag"
        )
        dsa[qc_name].attrs["standard_name"] = "status_flag"
        # Mention the QC variable in the variable attributes
        dsa[var_name].attrs["ancillary_variables"] = qc_name
    return dsa


# Variables that are semantically integer and are stored as the smallest signed integer
# that holds their range. Named explicitly: a float variable that happens to be
# integer-valued in one deployment is not an integer variable.
INTEGER_VARIABLES: dict[str, type] = {
    "PHASE": np.int8,
    "PROFILE_NUMBER": np.int16,
    "DIVE_NUMBER": np.int16,
    "VBD_MIN_CNTS": np.int16,
}


def find_best_dtype(var_name: str, da: xr.DataArray) -> type:
    """Determine the optimal data type for a variable based on its name and values.

    Parameters
    ----------
    var_name
        The name of the variable.
    da
        The data array to analyze.

    Returns
    -------
    type
        The recommended numpy data type.

    Notes
    -----
    - Latitude/longitude variables use double precision
    - QC variables (name ending in ``qc``, case-insensitive) use int8
    - Time variables keep original dtype
    - Named integer variables (``INTEGER_VARIABLES``) use their fixed integer type
    - Already-integer variables are downsized to the smallest type that holds their range
    - Float64 variables are converted to float32

    """
    input_dtype = da.dtype.type
    name = var_name.lower()
    if "latitude" in name or "longitude" in name:
        return np.double
    if var_name[-2:].lower() == "qc":
        return np.int8
    if "time" in name:
        return input_dtype
    if var_name in INTEGER_VARIABLES:
        return INTEGER_VARIABLES[var_name]
    if "int" in str(input_dtype):
        if np.nanmax(da.values) < 2**15:
            return np.int16
        if np.nanmax(da.values) < 2**31:
            return np.int32
    if input_dtype == np.float64:
        return np.float32
    return input_dtype


def set_fill_value(new_dtype: type) -> int:
    """Calculate appropriate fill value for integer data types.

    Parameters
    ----------
    new_dtype
        The target integer data type.

    Returns
    -------
    int
        The fill value calculated as 2^(bits-1) - 1.

    """
    fill_val = 2 ** (int(re.findall(r"\d+", str(new_dtype))[0]) - 1) - 1
    return fill_val


def set_best_dtype(ds: xr.Dataset) -> xr.Dataset:
    """Optimize data types across all variables in the dataset to reduce memory usage.

    Parameters
    ----------
    ds
        The dataset to optimize.

    Returns
    -------
    xarray.Dataset
        Dataset with optimized data types and appropriate fill values.

    """
    bytes_in = ds.nbytes
    coord_names = list(ds.coords)
    for var_name in list(ds.variables):
        if var_name[-2:].lower() == "qc":
            # QC flags are owned by convert_qc_flags (int8, fill 6, no _FillValue);
            # never apply the generic bit-width fill (127) to a flag variable.
            continue
        da = ds[var_name]
        input_dtype = da.dtype.type
        new_dtype = find_best_dtype(var_name, da)
        for att in ["valid_min", "valid_max"]:
            if att in da.attrs.keys():
                da.attrs[att] = np.array(da.attrs[att]).astype(new_dtype)
        if new_dtype == input_dtype:
            continue
        _log.debug(f"{var_name} input dtype {input_dtype} change to {new_dtype}")
        ds = ds.drop_vars(var_name)
        if "int" in str(new_dtype):
            # Respect a sentinel the variable already declares (e.g. PROFILE_NUMBER uses
            # -9999); only derive one from the bit width when none exists.
            existing = da.encoding.get("_FillValue", da.attrs.get("_FillValue"))
            fill_val = (
                int(existing) if existing is not None else set_fill_value(new_dtype)
            )
            # Replace NaN with the fill before casting; np.where handles scalar (0-d) and
            # array variables, and np.isnan is only valid on floating-point source.
            if np.issubdtype(da.dtype, np.floating):
                filled = np.where(np.isnan(da.values), fill_val, da.values)
            else:
                filled = da.values
            da_new = da.copy(data=np.asarray(filled).astype(new_dtype))
            da_new.attrs.pop("_FillValue", None)  # _FillValue lives in encoding only
            da_new.encoding["_FillValue"] = fill_val
        else:
            da_new = da.astype(new_dtype)
        ds[var_name] = da_new
    # drop_vars + reassignment demotes a coordinate to a data variable; restore coords.
    ds = ds.set_coords([c for c in coord_names if c in ds.variables])
    bytes_out = ds.nbytes
    _log.debug(
        f"Space saved by dtype downgrade: {int(100 * (bytes_in - bytes_out) / bytes_in)} %",
    )
    return ds


def set_best_dtype_value(value, var_name: str):
    """Determine the best data type for a single value based on its variable name and convert it.

    Parameters
    ----------
    value : any
        The input value to convert.

    Returns
    -------
    converted_value : any
        The value converted to the best data type.

    """
    input_dtype = type(value)
    new_dtype = find_best_dtype(var_name, xr.DataArray(value))

    if new_dtype == input_dtype:
        return value

    converted_value = np.array(value).astype(new_dtype)

    if "int" in str(new_dtype) and np.isnan(value):
        fill_val = set_fill_value(new_dtype)
        converted_value = fill_val

    return converted_value


# OG1 canonical serialisation for time variables (CF seconds since the epoch, UTC).
# Used by the time encoders here and by writers.save_dataset; keep in sync with the time
# variable units declared in config/OG1_vocab_attrs.yaml.
OG1_TIME_UNITS = "seconds since 1970-01-01T00:00:00Z"
OG1_TIME_CALENDAR = "gregorian"


def encode_times(ds: xr.Dataset) -> xr.Dataset:
    """Encode time variables with standard units and remove problematic attributes.

    Parameters
    ----------
    ds
        Dataset containing time variables to encode.

    Returns
    -------
    xarray.Dataset
        Dataset with properly encoded time variables.

    """
    if "units" in ds.time.attrs.keys():
        ds.time.attrs.pop("units")
    if "calendar" in ds.time.attrs.keys():
        ds.time.attrs.pop("calendar")
    ds["time"].encoding["units"] = OG1_TIME_UNITS
    for var_name in list(ds):
        if "time" in var_name.lower() and not var_name == "time":
            for drop_attr in ["units", "calendar", "dtype"]:
                if drop_attr in ds[var_name].attrs.keys():
                    ds[var_name].attrs.pop(drop_attr)
            ds[var_name].encoding["units"] = OG1_TIME_UNITS
    return ds


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
        if "axis" in ds[var_name].attrs.keys():
            ds[var_name].attrs.pop("axis")
        if "time" in var_name.lower():
            for drop_attr in ["units", "calendar", "dtype"]:
                if drop_attr in ds[var_name].attrs.keys():
                    ds[var_name].attrs.pop(drop_attr)
                if drop_attr in ds[var_name].encoding.keys():
                    ds[var_name].encoding.pop(drop_attr)
            if var_name.lower() == "time":
                ds[var_name].attrs["units"] = OG1_TIME_UNITS
                ds[var_name].attrs["calendar"] = OG1_TIME_CALENDAR
    return ds


def merge_parts_of_dataset(
    ds: xr.Dataset, dim1: str = "sg_data_point", dim2: str = "ctd_data_point"
) -> xr.Dataset:
    """Merges variables from a dataset along two dimensions, ensuring consistency in coordinates.
    The function first separates the dataset into two datasets based on the specified dimensions,
    renames the second dimension to match the first, and then concatenates them along the first dimension.

    Missing time values are filled with NaN, and the final dataset is sorted by time.


    Parameters
    ----------
    ds: xarray.Dataset
        The input dataset containing both dimensions.
    dim1: str
        Primary dimension name (e.g., 'sg_data_point').
    dim2: str
        Secondary dimension name to be merged into dim1 (e.g., 'ctd_data_point').

    Returns
    -------
    merged_ds: xarray.Dataset
        A merged dataset sorted by time.

    Notes
    -----
    Original author: Till Moritz

    """

    def get_time_var(ds, dim):
        """Finds the appropriate time variable based on dimension naming conventions."""
        prefix = dim.split("_data_point")[0]  # Extract prefix
        time_var = "time" if dim == "sg_data_point" else f"{prefix}_time"
        return time_var if time_var in ds.variables else None

    # Extract variables for each dimension
    vars1 = {var: ds[var] for var in ds.variables if dim1 in ds[var].sizes}
    vars2 = {var: ds[var] for var in ds.variables if dim2 in ds[var].sizes}

    # Create separate datasets
    new_ds1, new_ds2 = xr.Dataset(vars1), xr.Dataset(vars2)

    # Rename time variables to 'time' if present
    time_var1, time_var2 = get_time_var(ds, dim1), get_time_var(ds, dim2)
    if time_var1:
        new_ds1 = new_ds1.rename({time_var1: "time"})
    if time_var2:
        new_ds2 = new_ds2.rename({time_var2: "time"})
    # Ensure "time" is a coordinate
    new_ds1 = new_ds1.set_coords("time") if "time" in new_ds1 else new_ds1
    new_ds2 = new_ds2.set_coords("time") if "time" in new_ds2 else new_ds2

    # Rename dim2 to dim1 for consistency
    new_ds2 = new_ds2.rename({dim2: dim1})

    # Add original dimension as attribute
    for new_ds, original_dim in [(new_ds1, dim1), (new_ds2, dim2)]:
        for var in new_ds.variables:
            new_ds[var].attrs["dimension_info"] = f"Original dimension: {original_dim}"

    # Find max size for primary dimension
    max_size = max(new_ds1.sizes.get(dim1, 0), new_ds2.sizes.get(dim1, 0))

    # Pad function to match sizes along dim1
    def pad_ds(ds, max_size):
        ### the dataset makes problems if variables are integers,
        ### so we convert to float before padding and back to int after padding
        for var in ds.variables:
            if "int" in str(ds[var].dtype):
                ds[var] = ds[var].astype(float)

        pad_size = max_size - ds.sizes.get(dim1, 0)
        if pad_size > 0:
            ds = ds.pad({dim1: (0, pad_size)}, constant_values=np.nan)
        return ds

    new_ds1, new_ds2 = pad_ds(new_ds1, max_size), pad_ds(new_ds2, max_size)

    # Get all unique coordinates across both datasets
    all_coords = set(new_ds1.coords) | set(new_ds2.coords)

    # Ensure both datasets contain the same coordinates, filling missing ones with NaN
    for coord in all_coords:
        if coord not in new_ds1:
            new_shape = (
                (new_ds1.sizes[dim1],)
                if dim1 in new_ds1.sizes
                else (len(new_ds1["time"]),)
            )
            new_ds1[coord] = xr.DataArray(np.full(new_shape, np.nan), dims=dim1)
            new_ds1 = new_ds1.set_coords(coord)
        if coord not in new_ds2:
            new_shape = (
                (new_ds2.sizes[dim1],)
                if dim1 in new_ds2.sizes
                else (len(new_ds2["time"]),)
            )
            new_ds2[coord] = xr.DataArray(np.full(new_shape, np.nan), dims=dim1)
            new_ds2 = new_ds2.set_coords(coord)

    # Concatenate along dim1. Missing values will be filled with NaN.
    merged_ds = xr.concat(
        [new_ds1, new_ds2], dim=dim1, join="inner", combine_attrs="drop_conflicts"
    )

    # Sort by time and drop NaT values
    merged_ds = merged_ds.sortby("time").dropna(dim=dim1, subset=["time"])
    return merged_ds


def merge_datasets_along_time(
    split_ds: dict[tuple[str, ...], xr.Dataset],
    time_variables: dict[str, list[str]],
    firstrun: bool = False,
) -> xr.Dataset | None:
    """Merge split datasets onto a shared time axis.

    Merge dimensions listed in ``time_variables``, retaining original
    variable names. Replace individual time variables with ``time``.
    OG1 conversion is handled separately by ``standardise_OG10``.

    Always use ``time`` for ``sg_data_point``. Other dimensions use their
    listed candidates. Time variables must contain datetime64 values and
    match the dimension's length. Shared time sources are attached by
    position and must have matching sample order.

    Keep the first duplicate timestamp unchanged and shift subsequent
    occurrences by 0.5 seconds each. Print adjustments and record their
    source dimension, time variable, and timestamps in ``time`` attributes.
    Retained variables receive original name and dimension attributes.

    Parameters
    ----------
    split_ds : dict[tuple[str, ...], xr.Dataset]
        Split datasets keyed by dimension, e.g. ``("sg_data_point",)``.

    time_variables : dict[str, list[str]]
        Dimensions mapped to candidate time variable names.

    first_run : bool, default False
        Print progress and skipped dimensions. Duplicate timestamp
        adjustments are always printed.

    Returns
    -------
    xarray.Dataset or None
        Chronologically sorted dataset with coordinate
        ``time(N_MEASUREMENTS)`` and no ``N_MEASUREMENTS`` coordinate.
        Return None if no dataset has a usable time source.
    """
    processed_datasets = []
    actually_merged_dims = set()
    all_dims = {dim for key in split_ds for dim in key}
    duplicate_time_descriptions = []

    all_time_names = {name for names in time_variables.values() for name in names}

    # Collect shared time sources before modifying datasets.
    time_sources: dict[str, list[xr.DataArray]] = {}

    for dataset in split_ds.values():
        for name in all_time_names:
            if name in dataset.variables:
                time_sources.setdefault(name, []).append(dataset[name])

    def is_usable_time(source: xr.DataArray, size: int) -> bool:
        """Check that a time source matches the target dimension."""
        return (
            source.ndim == 1
            and source.size == size
            and pd.api.types.is_datetime64_dtype(source.dtype)
        )

    for dim, candidate_names in time_variables.items():
        if (dim,) not in split_ds:
            if firstrun:
                print(f"Skipping '{dim}': not found in split_ds.")
            continue

        ds = split_ds[(dim,)].copy()

        if dim not in ds.dims:
            if firstrun:
                print(f"Skipping '{dim}': dimension not found in dataset.")
            continue

        # Never use ctd_time as a fallback for sg_data_point.
        candidates = (
            ["time"] if dim == "sg_data_point" else list(dict.fromkeys(candidate_names))
        )

        time_var = None
        time_source = None

        for name in candidates:
            # Prefer a time variable on the current dimension.
            if (
                name in ds.variables
                and ds[name].dims == (dim,)
                and is_usable_time(ds[name], ds.sizes[dim])
            ):
                time_var = name
                time_source = ds[name]
                break

            # Shared sources are attached by position.
            for source in time_sources.get(name, []):
                if is_usable_time(source, ds.sizes[dim]):
                    time_var = name
                    time_source = source
                    break

            if time_source is not None:
                break

        if time_source is None:
            if firstrun:
                print(
                    f"Skipping '{dim}': no associated datetime64 time "
                    "variable with a matching length."
                )
            continue

        time_values = time_source.values
        time_attrs = dict(time_source.attrs)

        # Replace individual time variables with the shared time coordinate.
        ds = ds.drop_vars([name for name in all_time_names if name in ds.variables])

        if "time" in ds.variables:
            raise ValueError(
                f"'{dim}' contains a variable named 'time' that was not "
                "identified as a time source."
            )

        # Preserve original names and dimensions without OG1 renaming.
        for name in ds.variables:
            ds[name].attrs["original_dimension"] = dim
            ds[name].attrs["original_variable_name"] = name

        ds = ds.assign_coords(
            time=xr.DataArray(
                time_values,
                dims=(dim,),
                attrs=time_attrs,
            )
        )
        ds = ds.swap_dims({dim: "time"})
        ds = ds.sortby("time")

        # Keep the first occurrence; shift subsequent ones by 0.5 s each.
        original_times = pd.Series(ds["time"].values)

        occurrence = original_times.groupby(
            original_times,
            sort=False,
            dropna=False,
        ).cumcount()

        adjusted_times = original_times + pd.to_timedelta(occurrence * 0.5, unit="s")

        if adjusted_times[adjusted_times.notna()].duplicated().any():
            raise ValueError(
                f"Shifting duplicate timestamps in '{dim}' / '{time_var}' "
                "by 0.5 seconds creates another timestamp collision."
            )

        duplicate_mask = original_times.duplicated(keep=False) & original_times.notna()

        if duplicate_mask.any():
            description = [
                f"Dimension: {dim} with time variable: {time_var} "
                "has duplicate time values.",
                "The following time values occurred multiple times and "
                "have been assigned to the following new timestamps:",
            ]

            for timestamp in original_times[duplicate_mask].drop_duplicates():
                positions = original_times.index[original_times.eq(timestamp)].tolist()

                new_timestamps = [
                    adjusted_times.iloc[position].isoformat() for position in positions
                ]

                description.append(
                    f"  {timestamp.isoformat()} occurred "
                    f"{len(positions)} times.\n"
                    "    Assigned timestamps:\n"
                    + "\n".join(f"      {value}" for value in new_timestamps)
                )

            description_text = "\n".join(description)
            duplicate_time_descriptions.append(description_text)
            # print(description_text)

        ds = ds.assign_coords(
            time=xr.DataArray(
                adjusted_times.to_numpy(),
                dims=("time",),
                attrs=time_attrs,
            )
        )
        ds = ds.sortby("time")

        if firstrun:
            print(
                f"Adding variables with dimension '{dim}' "
                f"and time variable '{time_var}'."
            )

        processed_datasets.append(ds)
        actually_merged_dims.add(dim)

    if not processed_datasets:
        if firstrun:
            print("No datasets processed. Returning None.")
        return None

    merged_ds = xr.merge(processed_datasets, join="outer")
    merged_ds = merged_ds.sortby("time")

    # Keep lowercase time; create only the N_MEASUREMENTS dimension.
    merged_ds = merged_ds.swap_dims({"time": "N_MEASUREMENTS"})

    merged_ds["time"].attrs["duplicate_timestamp_adjustments"] = (
        "\n\n".join(duplicate_time_descriptions)
        if duplicate_time_descriptions
        else "No duplicate time values were found."
    )
    merged_ds["time"].attrs["duplicate_timestamp_adjustment_rule"] = (
        "First occurrence unchanged; subsequent occurrences shifted "
        "forward by 0.5 seconds each. No measurements were discarded."
    )

    if firstrun:
        print("Dimensions not merged: " f"{sorted(all_dims - actually_merged_dims)}")

    return merged_ds


def combine_two_dim_of_dataset(
    ds: xr.Dataset, dim1: str = "sg_data_point", dim2: str = "ctd_data_point"
) -> xr.Dataset:
    """Updates the original dataset by removing variables with dim1 and dim2
    and adding the merged dataset.

    Parameters
    ----------
    ds
        The original dataset.
    dim1, optional
        First dimension to be removed. Default is 'sg_data_point'.
    dim2, optional
        Second dimension to be removed. Default is 'ctd_data_point'.

    Returns
    -------
    xarray.Dataset
        The updated dataset with merged variables.

    """
    # Drop all variables that have dim1 or dim2
    vars_to_drop = [
        var for var in ds.variables if dim1 in ds[var].sizes or dim2 in ds[var].sizes
    ]
    cleaned_ds = ds.drop_vars(vars_to_drop, errors="ignore")
    merged_ds = merge_parts_of_dataset(ds, dim1=dim1, dim2=dim2)
    # Merge the cleaned dataset with the merged dataset
    updated_ds = xr.merge([cleaned_ds, merged_ds], combine_attrs="drop_conflicts")

    return updated_ds


standard_names = vocabularies.standard_names


def extract_scalar_parameters(
    list_datasets: list[xr.Dataset],
) -> dict:
    """Extract all scalar variables from a list of datasets.

    Collect each variable's values across datasets and copy attributes from
    its first occurrence. Mark it constant only when it exists in every
    dataset and has the same value throughout. Record missing occurrences
    and extract dive identifiers for later assignment to measurements.

    Parameters
    ----------
    list_datasets : list[xarray.Dataset]
        Input datasets containing scalar variables and dive identifiers.

    Returns
    -------
    dict
        Parameter values, source attributes, presence and constant flags,
        and dive identifiers.
    """
    names = list(dict.fromkeys(
        name
        for dataset in list_datasets
        for name, variable in dataset.variables.items()
        if variable.ndim == 0
    ))

    parameters = {}

    for name in names:
        values = []
        present = []
        attributes = None

        for dataset in list_datasets:
            if name not in dataset.variables:
                values.append(float("nan"))
                present.append(False)
                continue

            variable = dataset[name]

            if variable.ndim != 0:
                raise ValueError(
                    f"'{name}' is scalar in one dataset but has dimensions "
                    "in another."
                )

            values.append(variable.values[()])
            present.append(True)

            if attributes is None:
                attributes = variable.attrs.copy()

        # Missing occurrences prevent collapsing to a constant.
        constant = (
            all(present)
            and pd.Series(values).nunique(dropna=False) == 1
        )

        parameters[name] = {
            "values": values,
            "present": present,
            "constant": constant,
            "attributes": attributes or {},
        }

    # Extract the identifier used to match each dataset to its measurements.
    dive_numbers = []

    for dataset in list_datasets:
        if "dive_number" in dataset.attrs:
            dive = dataset.attrs["dive_number"]
        elif (
            "dive_number" in dataset.variables
            and dataset["dive_number"].ndim == 0
        ):
            dive = dataset["dive_number"].values[()]
        elif (
            "trajectory" in dataset.variables
            and dataset["trajectory"].ndim == 0
        ):
            dive = dataset["trajectory"].values[()]
        else:
            dive = None

        dive_numbers.append(dive)

    return {
        "parameters": parameters,
        "dive_numbers": dive_numbers,
    }

def add_scalar_parameters(
    ds_og1: xr.Dataset,
    extracted: dict,
    og1_mapping: pd.DataFrame,
) -> tuple[xr.Dataset, pd.DataFrame]:
    """Add extracted scalar parameters and update the OG1 mapping.

    Keep constant parameters scalar. Assign changing or partially missing
    parameters along ``N_MEASUREMENTS`` using ``DIVE_NUMBER``, with missing
    values where unavailable.

    Use existing OG1 mappings or vocabulary names where available; otherwise
    retain original names. Preserve source attributes and units, and add
    ``original_name``. No unit conversions are performed.

    Parameters
    ----------
    ds_og1 : xarray.Dataset
        Output dataset. Changing parameters require
        ``DIVE_NUMBER(N_MEASUREMENTS)``.
    extracted : dict
        Parameters and dive identifiers from ``extract_scalar_parameters``.
    og1_mapping : pandas.DataFrame
        Existing variable mapping with unique original names.

    Returns
    -------
    tuple[xarray.Dataset, pandas.DataFrame]
        Dataset with assigned parameters and the updated mapping.
    """
    result = ds_og1.copy()
    mapping = og1_mapping.copy()
    dive_numbers = extracted["dive_numbers"]

    if mapping["original_name"].duplicated().any():
        raise ValueError("The mapping must have unique original names.")

    used_names = {}

    for original_name, parameter in extracted["parameters"].items():
        row_mask = mapping["original_name"].eq(original_name)

        # Prefer the existing mapping, including any numbered OG1 names.
        if row_mask.any():
            og1_name = mapping.loc[row_mask, "OG1_name"].iloc[0]
        else:
            og1_name = None

        if og1_name is None or pd.isna(og1_name):
            og1_name = vocabularies.standard_names.get(original_name)

        is_mapped = og1_name is not None and pd.notna(og1_name)
        output_name = str(og1_name) if is_mapped else original_name

        if output_name in used_names:
            raise ValueError(
                f"'{original_name}' and '{used_names[output_name]}' "
                f"both map to '{output_name}'."
            )

        used_names[output_name] = original_name

        # Existing versions of this parameter can be replaced.
        if output_name in result.variables:
            known_source = result[output_name].attrs.get(
                "original_name",
                result[output_name].attrs.get("original_variable_name"),
            )

            if (
                output_name != original_name
                and known_source != original_name
                and not row_mask.any()
            ):
                raise ValueError(
                    f"'{output_name}' already exists and cannot safely "
                    f"be replaced by '{original_name}'."
                )

        attributes = parameter["attributes"].copy()
        attributes["original_name"] = original_name

        if parameter["constant"]:
            variable = xr.DataArray(
                parameter["values"][0],
                attrs=attributes,
            )
        else:
            if "DIVE_NUMBER" not in result.variables:
                raise ValueError(
                    f"Changing parameter '{original_name}' requires "
                    "DIVE_NUMBER in the output dataset."
                )

            if result["DIVE_NUMBER"].dims != ("N_MEASUREMENTS",):
                raise ValueError(
                    "DIVE_NUMBER must have dimension N_MEASUREMENTS."
                )

            if any(dive is None or pd.isna(dive) for dive in dive_numbers):
                raise ValueError(
                    "Every input dataset needs a dive identifier "
                    "to assign changing scalar parameters."
                )

            if pd.Index(dive_numbers).has_duplicates:
                raise ValueError(
                    "Input dive identifiers must be unique."
                )

            values_by_dive = pd.Series(
                parameter["values"],
                index=dive_numbers,
            )

            measurement_dives = result["DIVE_NUMBER"].values
            assigned_values = values_by_dive.reindex(
                measurement_dives
            ).to_numpy()

            variable = xr.DataArray(
                assigned_values,
                dims=("N_MEASUREMENTS",),
                attrs=attributes,
            )

        # Remove an old original-name version when the parameter is renamed.
        if output_name != original_name and original_name in result.variables:
            result = result.drop_vars(original_name)

        result[output_name] = variable

        mapping_updates = {
            "OG1_name": output_name if is_mapped else None,
            # The source variable was scalar, regardless of its output shape.
            "original_dimension": "",
            "has_OG1_attributes": (
                bool(vocabularies.vocab_attrs.get(output_name, {}))
                if is_mapped
                else False
            ),
        }

        if row_mask.any():
            for column, value in mapping_updates.items():
                mapping.loc[row_mask, column] = value
        else:
            mapping = pd.concat(
                [
                    mapping,
                    pd.DataFrame([{
                        "original_name": original_name,
                        "instrument": None,
                        "instrument_type": None,
                        **mapping_updates,
                    }]),
                ],
                ignore_index=True,
            )

    return result, mapping


def parse_8_digit_date(date_str):
    """Validates and formats 8-digit strings.
    Prioritizes YYYY-MM-DD, then DD-MM-YYYY based on realistic ranges.
    """
    # Extract only the digits
    d = "".join(re.findall(r"\d", date_str))
    if len(d) != 8:
        return None

    # Try YYYYMMDD (Standard ISO-like)
    # Year: 1900-2099, Month: 01-12, Day: 01-31
    y, m, day = int(d[:4]), int(d[4:6]), int(d[6:])
    if 1900 <= y < date.today().year and 1 <= m <= 12 and 1 <= day <= 31:
        return f"{y:04d}-{m:02d}-{day:02d}"

    # Try DDMMYYYY (European style)
    # Day: 01-31, Month: 01-12, Year: 1900-2099
    day, m, y = int(d[:2]), int(d[2:4]), int(d[4:])
    if 1900 <= y < date.today().year and 1 <= m <= 12 and 1 <= day <= 31:
        return f"{y:04d}-{m:02d}-{day:02d}"

    # Try MMDDYYYY (US style)
    m, day, y = int(d[:2]), int(d[2:4]), int(d[4:])
    if 1900 <= y < date.today().year and 1 <= m <= 12 and 1 <= day <= 31:
        return f"{y:04d}-{m:02d}-{day:02d}"

    return "Format Error"


def extract_instrument_info(input_string):
    if (
        input_string is None
        or not isinstance(input_string, str)
        or input_string.strip() == ""
    ):
        return "0000", "00-00-0000"

    s = input_string.replace(",", " ").replace(";", " ")

    # 1. EXTRACT SERIAL NUMBER (DIGITS ONLY)
    sn_patterns = [
        r"(?i)(?:s/n|sn|serial\s*#|serialnum)[:\s]*([\w-]+)",
        r"(?i)SBE\s+([\d-]+)",
        r"(?i)SN([\d-]+)",
    ]

    raw_sn = ""
    for pattern in sn_patterns:
        match = re.search(pattern, s)
        if match:
            raw_sn = match.group(1)
            break

    # Strip letters and dashes, keeping only the numbers
    if raw_sn:
        serial_number = "".join(re.findall(r"\d+", raw_sn))
    else:
        serial_number = "0000"

    # 2. EXTRACT CALIBRATION DATES
    multi_match = re.findall(r"(\w+):(\d{4}-\d{2}-\d{2}T[\d:]+Z)", s)

    if multi_match:
        cal_info = ", ".join(
            [f"{m[0]}: {parser.parse(m[1]).strftime('%Y-%m-%d')}" for m in multi_match]
        )
    else:
        parts = re.split(r"(?i)cal(?:ibration)?[:\s]*", s)
        if len(parts) > 1:
            date_candidate = parts[1].strip()

            # Handle the specific 8-digit date requirement (29082012 -> 2908-20-12)
            digit_only_date = "".join(re.findall(r"\d", date_candidate))
            if len(digit_only_date) == 8 and "?" not in date_candidate:
                cal_info = parse_8_digit_date(date_candidate)
            elif "?" in date_candidate:
                cal_info = "0000-00-00"
            else:
                try:
                    dt = parser.parse(date_candidate, fuzzy=True, dayfirst=True)
                    cal_info = dt.strftime("%Y-%m-%d")
                except:
                    cal_info = "Format Error"
        else:
            cal_info = "None Found"

    ## if cal_info has unrealistic year, month or day, rearrange so that year is first, then try parsing again
    if cal_info not in ["None Found", "Format Error", "0000-00-00"]:
        try:
            dt = parser.parse(cal_info, fuzzy=True, dayfirst=True)
            if (
                dt.year < 1900
                or dt.year > date.today().year
                or dt.month > 12
                or dt.day > 31
            ):
                # Try parsing with year first
                dt = parser.parse(cal_info, fuzzy=True, yearfirst=True)
                cal_info = dt.strftime("%Y-%m-%d")
        except:
            pass

    return serial_number, cal_info


# ===============================================================================
# Unused functions
# ===============================================================================
