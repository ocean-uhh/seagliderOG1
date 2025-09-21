import logging
import re

import gsw
import numpy as np
import pandas as pd
import xarray as xr

from seagliderOG1 import utilities, vocabularies

_log = logging.getLogger(__name__)

variables_sensors = {
    "CNDC": "CTD",
    "DOXY": "dissolved gas sensors",
    "PRES": "CTD",
    "PSAL": "CTD",
    "TEMP": "CTD",
    "BBP700": "fluorometers",
    "CHLA": "fluorometers",
    "PRES_ADCP": "ADVs and turbulence probes",
}


# EFW 2025-01-01: This could be improved
# Sensor information is contained in the basestation file as a variable (e.g., 'wlbb2f') or
# in the sg_cal strings, e.g. calibcomm_oxygen or calibcomm_optode contains 'SBE 43F' or 'Optode 4330F'
# Using this, and the presence of calibration coefficients (e.g., optode_FoilCoefA1), we can make
# a guess as to the sensor type
def gather_sensor_info(
    ds_other: xr.Dataset, ds_sgcal: xr.Dataset, firstrun: bool = False
) -> xr.Dataset:
    """Gathers sensor information from the provided datasets and organizes it into a new dataset.

    Parameters
    ----------
    ds_other
        The dataset containing sensor data.
    ds_sgcal
        The dataset containing calibration data.
    firstrun, optional
        A flag indicating if this is the first run. Default is False.

    Returns
    -------
    xarray.Dataset
        A dataset containing the gathered sensor information.

    Notes
    -----
    - The function looks for specific sensor names in the `ds_other` dataset and adds them to a new dataset `ds_sensor`.
    - If 'aanderaa4330_instrument_dissolved_oxygen' is present in `ds_other`, it is renamed to 'aa4330'.
    - If 'Pcor' is present in `ds_sgcal`, an additional sensor 'sbe43' is created based on 'sbe41' with specific attributes.
    - If 'optode_FoilCoefA1' is present in `ds_sgcal`, an additional sensor 'aa4831' is created based on 'sbe41' with specific attributes.
    - The function sets appropriate attributes for the sensors 'aa4330', 'aa4831', and 'sbe43' if they are present.
    """
    # Gather sensors
    sensor_names = ["wlbb2f", "sbe41", "aa4330", "aa4381", "aa4330f", "aa4381f"]

    ds_sensor = xr.Dataset()
    if "aanderaa4330_instrument_dissolved_oxygen" in ds_other.variables:
        ds_other["aa4330"] = ds_other["aanderaa4330_instrument_dissolved_oxygen"]
    for sensor in sensor_names:
        if sensor in ds_other:
            ds_sensor[sensor] = ds_other[sensor]

    if "Pcor" in ds_sgcal:
        ds_sensor["sbe43"] = ds_sensor["sbe41"]
        ds_sensor["sbe43"].attrs["long_name"] = "Sea-Bird SBE 43F Oxygen Sensor"
        ds_sensor["sbe43"].attrs[
            "ancillary_variables"
        ] = "sg_cal_Pcor sg_cal_Foffset sg_cal_A sg_cal_B sg_cal_C sg_cal_E sg_cal_Soc"

    aanderaa_ancillary = "optode_FoilCoefA1 optode_FoilCoefA2	optode_FoilCoefA3 optode_FoilCoefA4	optode_FoilCoefA5 optode_FoilCoefA6 optode_FoilCoefA7 optode_FoilCoefA8 optode_FoilCoefA9 optode_FoilCoefA10 optode_FoilCoefA11	optode_FoilCoefA12 optode_FoilCoefA13 optode_FoilCoefB1	optode_FoilCoefB2 optode_FoilCoefB3	optode_FoilCoefB4 optode_FoilCoefB5	 optode_FoilCoefB6 optode_PhaseCoef0 optode_PhaseCoef1 optode_PhaseCoef2 optode_PhaseCoef3 optode_ConcCoef0 optode_ConcCoef1 optode_SVU_enabled optode_TempCoef0 optode_TempCoef1 optode_TempCoef2 optode_TempCoef3 optode_TempCoef4 optode_TempCoef5"
    if "optode_FoilCoefA1" in ds_sgcal:
        ds_sensor["aa4831"] = ds_sensor["sbe41"]
        ds_sensor["aa4831"].attrs["long_name"] = "Aanderaa 4831F Oxygen Sensor"
        ds_sensor["aa4831"].attrs["ancillary_variables"] = aanderaa_ancillary
    if "aa4330" in ds_sensor.variables:
        ds_sensor["aa4330"].attrs["long_name"] = "Aanderaa 4330 Oxygen Sensor"
        ds_sensor["aa4330"].attrs["ancillary_variables"] = aanderaa_ancillary


def add_sensor_to_dataset(
    dsa: xr.Dataset, ds: xr.Dataset, sg_cal: xr.Dataset, firstrun: bool = False
) -> xr.Dataset:
    """Add sensor information to the dataset based on instrument data and calibration parameters.

    This function processes different types of seaglider sensors including CTD (sbe41),
    oxygen sensors (sbe43, aa4381, aa4330), and optical sensors (wlbb2f). For each sensor,
    it extracts calibration information, parses serial numbers and calibration dates,
    and creates sensor variables with appropriate attributes and metadata.

    Parameters
    ----------
    dsa
        The target dataset to add sensor information to.
    ds
        Dataset containing instrument/sensor data with attributes.
    sg_cal
        Dataset containing calibration information and calibcomm strings.
    firstrun, optional
        Whether to enable detailed logging for debugging. Default is False.

    Returns
    -------
    xarray.Dataset
        The updated dataset with sensor variables and metadata added.

    Notes
    -----
    - Handles CTD sensors by parsing calibcomm strings for serial numbers and dates
    - Processes oxygen sensors using calibcomm_oxygen or calibcomm_optode information
    - Creates sensor variable names in format: 'SENSOR_{type}_{serial}'
    - Skips altimeter sensors as they are not processed in current implementation
    - For wlbb2f sensors, calibration parsing is commented out pending data availability

    """
    if ds is None:
        return dsa
    sensors = list(ds)
    sensor_name_type = {}
    for instr in sensors:
        if firstrun:
            _log.info(instr)
        if instr in ["altimeter"]:
            continue
        attr_dict = ds[instr].attrs
        # Code to parse details from sg_cal and calibcomm into the attributes for CTD
        if instr == "sbe41":
            if attr_dict["make_model"] == "unpumped Seabird SBE41":
                attr_dict["make_model"] = "Seabird unpumped CTD"
            if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
                _log.error(f"sensor {attr_dict['make_model']} not found")
            var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]

            calstr = sg_cal["calibcomm"].values.item().decode("utf-8")
            if firstrun:
                _log.info(f"sg_cal_calibcomm: {calstr}")
                print(f"sg_cal_calibcomm: {calstr}")

            cal_date, serial_number = utilities._parse_calibcomm(calstr, firstrun)
            var_dict["serial_number"] = serial_number
            var_dict["long_name"] += f":{serial_number}"
            var_dict["calibration_date"] = cal_date

            if "ancillary_variables" in attr_dict.keys():
                ancilliary_vars = attr_dict["ancillary_variables"]
                anc_var_list = utilities._clean_anc_vars_list(
                    attr_dict["ancillary_variables"]
                )
                calvals = utilities._assign_calval(sg_cal, anc_var_list)
                var_dict["calibration_parameters"] = calvals
            da = xr.DataArray(attrs=var_dict)
            if serial_number is not None:
                sensor_var_name = (
                    f"sensor_{var_dict['sensor_type']}_{serial_number}".upper().replace(
                        " ",
                        "_",
                    )
                )
            else:
                sensor_var_name = f"sensor_{var_dict['sensor_type']}".upper().replace(
                    " ",
                    "_",
                )
            dsa[sensor_var_name] = da
            sensor_name_type[var_dict["sensor_type"]] = sensor_var_name

        # Handle oxygen sensor
        optode_flag = False
        if instr == "sbe43":
            attr_dict["make_model"] = "Seabird SBE43F"
            if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
                _log.error(f"sensor {attr_dict['make_model']} not found")
            var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]
            optode_flag = True
        if instr == "aa4381":
            attr_dict["make_model"] = "Aanderaa 4381"
            if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
                _log.error(f"sensor {attr_dict['make_model']} not found")
            var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]
            optode_flag = True
        if instr == "aa4330":
            attr_dict["make_model"] = "Aanderaa 4330"
            if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
                _log.error(f"sensor {attr_dict['make_model']} not found")
            var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]
            optode_flag = True

        if optode_flag:
            if "calibcomm_oxygen" in sg_cal:
                calstr = sg_cal["calibcomm_oxygen"].values.item().decode("utf-8")
                if firstrun:
                    _log.info(f"sg_cal_calibcomm_oxygen: {calstr}")
                    print(f"sg_cal_calibcomm_oxygen: {calstr}")

                cal_date, serial_number = utilities._parse_calibcomm(calstr, firstrun)
            elif "calibcomm_optode" in sg_cal:
                calstr = sg_cal["calibcomm_optode"].values.item().decode("utf-8")
                if firstrun:
                    _log.info(f"sg_cal_calibcomm_optode: {calstr}")
                    print(f"sg_cal_calibcomm_optode: {calstr}")

                cal_date, serial_number = utilities._parse_calibcomm(calstr, firstrun)
            var_dict["serial_number"] = serial_number
            var_dict["long_name"] += f":{serial_number}"
            var_dict["calibration_date"] = cal_date

            # All the sg_cal_optode_*
            if "ancillary_variables" in attr_dict.keys():
                ancilliary_vars = attr_dict["ancillary_variables"]
                anc_var_list = utilities._clean_anc_vars_list(
                    attr_dict["ancillary_variables"]
                )
                calvals = utilities._assign_calval(sg_cal, anc_var_list)
                var_dict["calibration_parameters"] = calvals

            da = xr.DataArray(attrs=var_dict)
            if serial_number is not None:
                sensor_var_name = (
                    f"sensor_{var_dict['sensor_type']}_{serial_number}".upper().replace(
                        " ",
                        "_",
                    )
                )
            else:
                sensor_var_name = f"sensor_{var_dict['sensor_type']}".upper().replace(
                    " ",
                    "_",
                )
            dsa[sensor_var_name] = da
            sensor_name_type[var_dict["sensor_type"]] = sensor_var_name

        if instr == "wlbb2f":
            if attr_dict["make_model"] == "Wetlabs backscatter fluorescence puck":
                attr_dict["make_model"] = "Wetlabs BB2FL-VMT"
            if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
                _log.error(f"sensor {attr_dict['make_model']} not found")
            var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]

            #   Not in sample dataset - see whether more recent files have calibration information
            #        cal_date, serial_number = utilities._parse_calibcomm(sg_cal['calibcomm'])
            #        if serial_number is not None:
            #            var_dict["serial_number"] = serial_number
            #            var_dict["long_name"] += f":{serial_number}"
            #        if cal_date is not None:
            #            var_dict["calibration_date"] = cal_date
            serial_number = None

            da = xr.DataArray(attrs=var_dict)
            if serial_number:
                sensor_var_name = (
                    f"sensor_{var_dict['sensor_type']}_{serial_number}".upper().replace(
                        " ",
                        "_",
                    )
                )
            else:
                sensor_var_name = f"sensor_{var_dict['sensor_type']}".upper().replace(
                    " ",
                    "_",
                )
            dsa[sensor_var_name] = da
            sensor_name_type[var_dict["sensor_type"]] = sensor_var_name

            if "ancillary_variables" in attr_dict.keys():
                ancilliary_vars = attr_dict["ancillary_variables"]
                anc_var_list = utilities._clean_anc_vars_list(
                    attr_dict["ancillary_variables"]
                )
                calvals = utilities._assign_calval(sg_cal, anc_var_list)
                var_dict["calibration_parameters"] = calvals
            da = xr.DataArray(attrs=var_dict)
            if serial_number is not None:
                sensor_var_name = (
                    f"sensor_{var_dict['sensor_type']}_{serial_number}".upper().replace(
                        " ",
                        "_",
                    )
                )
            else:
                sensor_var_name = f"sensor_{var_dict['sensor_type']}".upper().replace(
                    " ",
                    "_",
                )
            if firstrun:
                _log.info("Adding sensor:", sensor_var_name)
            dsa[sensor_var_name] = da
            sensor_name_type[var_dict["sensor_type"]] = sensor_var_name
    return dsa


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
    if dive_number == None:
        dive_number = ds.attrs.get("dive_number", np.nan)
    return ds.assign(
        divenum=("N_MEASUREMENTS", [dive_number] * ds.dims["N_MEASUREMENTS"])
    )


def assign_profile_number(ds: xr.Dataset, ds1: xr.Dataset) -> xr.Dataset:
    """Assign profile numbers to measurements based on dive phases (down/up casts).

    This function separates each dive into two profiles: descent (down cast) and
    ascent (up cast) phases. The dive is split at the maximum pressure point,
    with the descent phase getting the dive number and ascent getting dive + 0.5.
    Profile numbers are then calculated as 2 * dive_num_cast - 1.

    Parameters
    ----------
    ds
        The dataset to add profile numbers to.
    ds1
        Dataset containing dive number information in attributes.

    Returns
    -------
    xarray.Dataset
        Dataset with 'dive_num_cast' and 'PROFILE_NUMBER' variables added.

    Notes
    -----
    - Requires pressure variable (PRES, ctd_pressure, Pressure, or pres)
    - Down cast: dive_num_cast = dive number
    - Up cast: dive_num_cast = dive number + 0.5
    - Profile numbers: descent = 2*dive-1, ascent = 2*dive

    """
    # Remove the variable dive_num_cast if it exists
    if "dive_num_cast" in ds.variables:
        ds = ds.drop_vars("dive_num_cast")

    # Initialize the new variable with the same dimensions as dive_num
    ds["dive_num_cast"] = (
        ["N_MEASUREMENTS"],
        np.full(ds.dims["N_MEASUREMENTS"], np.nan),
    )

    ds = add_dive_number(ds, ds1.attrs["dive_number"])

    # Iterate over each unique dive_num
    for dive in np.unique(ds["divenum"]):
        # Get the indices for the current dive
        dive_indices = np.where(ds["divenum"] == dive)[0]
        if len(dive_indices) == 0:
            continue  # Skip if no indices found

        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]

        # Check for possible pressure variable names in ds, then ds1
        possible_press_names = ["PRES", "ctd_pressure", "Pressure", "pres"]
        press_var = next(
            (var for var in possible_press_names if var in ds.variables), None
        )

        if press_var is None:
            press_var = next(
                (var for var in possible_press_names if var in ds1.variables), None
            )

        if press_var is None:
            raise ValueError(
                "No valid pressure variable (PRES or pressure) found in ds or ds1"
            )

        # Get pressure values from the correct dataset
        pressure_data = ds[press_var] if press_var in ds.variables else ds1[press_var]

        # Find the maximum pressure value between start_index and end_index
        pmax = np.nanmax(pressure_data[start_index : end_index + 1].values)

        # Find the index where PRES attains pmax
        pmax_index = start_index + np.argmax(
            pressure_data[start_index : end_index + 1].values == pmax
        )

        # Assign dive_num to all values up to and including pmax
        ds["dive_num_cast"][start_index : pmax_index + 1] = dive

        # Assign dive_num + 0.5 to values after pmax
        ds["dive_num_cast"][pmax_index + 1 : end_index + 1] = dive + 0.5

        # Remove PROFILE_NUMBER if it exists
        if "PROFILE_NUMBER" in ds.variables:
            ds = ds.drop_vars("PROFILE_NUMBER")

        # Assign PROFILE_NUMBER
        ds["PROFILE_NUMBER"] = 2 * ds["dive_num_cast"] - 1

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
    else:
        raise ValueError("No valid dive number variable found in the dataset.")
    # Initialize the new variable with the same dimensions as dive_num
    ds["PHASE"] = (["N_MEASUREMENTS"], np.full(ds.dims["N_MEASUREMENTS"], np.nan))
    # Initialize the new variable PHASE_QC with the same dimensions as dive_num
    ds["PHASE_QC"] = (
        ["N_MEASUREMENTS"],
        np.zeros(ds.dims["N_MEASUREMENTS"], dtype=int),
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


def get_sg_attrs(ds: xr.Dataset) -> dict:
    """Extract seaglider attributes and calibration information into a dictionary.

    Parameters
    ----------
    ds
        Dataset containing seaglider attributes and calibration data.

    Returns
    -------
    dict
        Dictionary containing seaglider variables and their attributes.

    """
    id = ds.attrs["id"]
    sg_cal, _, _ = extract_variables(ds)
    sg_vars_dict = {}
    for var, data in sg_cal.items():
        sg_vars_dict[var] = {attr: data.attrs.get(attr, "") for attr in data.attrs}
    return sg_vars_dict


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
        dims = tuple(var_data.dims)

        # If this dimension set is not in the dictionary, create a new dataset
        if dims not in unique_dims_datasets:
            unique_dims_datasets[dims] = xr.Dataset()

        # Add the variable to the corresponding dataset
        unique_dims_datasets[dims][var_name] = var_data

    # Convert the dictionary values to a dictionary of datasets
    return {dims: dataset for dims, dataset in unique_dims_datasets.items()}


def convert_units(ds: xr.Dataset) -> xr.Dataset:
    """Convert the units of variables in an xarray Dataset to preferred units.

    This is useful, for instance, to convert cm/s to m/s based on vocabulary
    specifications.

    Parameters
    ----------
    ds
        The dataset containing variables to convert.

    Returns
    -------
    xarray.Dataset
        The dataset with converted units.

    """
    """
    Convert the units of variables in an xarray Dataset to preferred units.  This is useful, for instance, to convert cm/s to m/s.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset containing variables to convert.

    Returns
    -------
    xarray.Dataset: The dataset with converted units.
    """

    for var in ds.variables:
        var_values = ds[var].values
        orig_unit = ds[var].attrs.get("units")
        if "units" in vocabularies.vocab_attrs[OG1_name]:
            new_unit = vocabularies.vocab_attrs[OG1_name].get("units")
            if orig_unit != new_unit:

                var_values, new_unit = convert_units_var(
                    var_values, orig_unit, new_unit
                )

                ds[var].values = var_values
                ds[var].attrs["units"] = new_unit

    return ds


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
    return new_unit


def convert_units_var(
    var_values: np.ndarray,
    current_unit: str,
    new_unit: str,
    unit1_to_unit2: dict = vocabularies.unit1_to_unit2,
    firstrun: bool = False,
) -> tuple[np.ndarray, str]:
    """Convert the units of variables in an xarray Dataset to preferred units.  This is useful, for instance, to convert cm/s to m/s.

    Parameters
    ----------
    ds (xarray.Dataset): The dataset containing variables to convert.
    preferred_units (list): A list of strings representing the preferred units.
    unit1_to_unit2 (dict): A dictionary mapping current units to conversion information.
    Each key is a unit string, and each value is a dictionary with:
        - 'factor': The factor to multiply the variable by to convert it.
        - 'units_name': The new unit name after conversion.

    Returns
    -------
    xarray.Dataset: The dataset with converted units.

    """
    current_unit = reformat_units_str(current_unit)
    new_unit = reformat_units_str(new_unit)

    u1_to_u2 = current_unit + "_to_" + new_unit
    if u1_to_u2 in unit1_to_unit2.keys():
        conversion_factor = unit1_to_unit2[u1_to_u2]["factor"]
        new_values = var_values * conversion_factor
    else:
        new_values = var_values
        new_unit = current_unit
        if firstrun:
            _log.warning(
                f"No conversion information found for {current_unit} to {new_unit}"
            )
    #        raise ValueError(f"No conversion information found for {current_unit} to {new_unit}")
    return new_values, new_unit


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
        values = pd.to_numeric(
            values, errors="coerce"
        )  # Convert strings to numbers, NaNs stay NaNs
        # Assign back to dataset
        dsa[qc_name].values = values
        dsa[qc_name].values = dsa[qc_name].values.astype("int8")
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
    - QC variables use int8
    - Time variables keep original dtype
    - Integer variables are downsized based on value range
    - Float64 variables are converted to float32

    """
    input_dtype = da.dtype.type
    if "latitude" in var_name.lower() or "longitude" in var_name.lower():
        return np.double
    if var_name[-2:].lower() == "qc":
        return np.int8
    if "time" in var_name.lower():
        return input_dtype
    if var_name[-3:] == "raw" or "int" in str(input_dtype):
        if np.nanmax(da.values) < 2**16 / 2:
            return np.int16
        elif np.nanmax(da.values) < 2**32 / 2:
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
    for var_name in list(ds):
        da = ds[var_name]
        input_dtype = da.dtype.type
        new_dtype = find_best_dtype(var_name, da)
        for att in ["valid_min", "valid_max"]:
            if att in da.attrs.keys():
                da.attrs[att] = np.array(da.attrs[att]).astype(new_dtype)
        if new_dtype == input_dtype:
            continue
        _log.debug(f"{var_name} input dtype {input_dtype} change to {new_dtype}")
        da_new = da.astype(new_dtype)
        ds = ds.drop_vars(var_name)
        if "int" in str(new_dtype):
            fill_val = set_fill_value(new_dtype)
            da_new[np.isnan(da)] = fill_val
            da_new.encoding["_FillValue"] = fill_val
        ds[var_name] = da_new
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
    ds["time"].encoding["units"] = "seconds since 1970-01-01T00:00:00Z"
    for var_name in list(ds):
        if "time" in var_name.lower() and not var_name == "time":
            for drop_attr in ["units", "calendar", "dtype"]:
                if drop_attr in ds[var_name].attrs.keys():
                    ds[var_name].attrs.pop(drop_attr)
            ds[var_name].encoding["units"] = "seconds since 1970-01-01T00:00:00Z"
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
                ds[var_name].attrs["units"] = "seconds since 1970-01-01T00:00:00Z"
                ds[var_name].attrs["calendar"] = "gregorian"
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
    vars1 = {var: ds[var] for var in ds.variables if dim1 in ds[var].dims}
    vars2 = {var: ds[var] for var in ds.variables if dim2 in ds[var].dims}

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
                (new_ds1.dims[dim1],)
                if dim1 in new_ds1.dims
                else (len(new_ds1["time"]),)
            )
            new_ds1[coord] = xr.DataArray(np.full(new_shape, np.nan), dims=dim1)
            new_ds1 = new_ds1.set_coords(coord)
        if coord not in new_ds2:
            new_shape = (
                (new_ds2.dims[dim1],)
                if dim1 in new_ds2.dims
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
        var for var in ds.variables if dim1 in ds[var].dims or dim2 in ds[var].dims
    ]
    cleaned_ds = ds.drop_vars(vars_to_drop, errors="ignore")
    merged_ds = merge_parts_of_dataset(ds, dim1=dim1, dim2=dim2)
    # Merge the cleaned dataset with the merged dataset
    updated_ds = xr.merge([cleaned_ds, merged_ds], combine_attrs="drop_conflicts")

    return updated_ds


# ===============================================================================
# Unused functions
# ===============================================================================
