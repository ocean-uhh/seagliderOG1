import numpy as np
import pandas as pd
import xarray as xr
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.colors as mcolors
from seagliderOG1 import vocabularies
import gsw
#import pandas as pd
#import numpy as np
#import xarray as xr
#from votoutils.utilities.utilities import encode_times_og1, set_best_dtype
#from votoutils.utilities import vocabularies
import logging
from datetime import datetime

_log = logging.getLogger(__name__)

def find_best_dtype(var_name, da):
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

def set_best_dtype(ds):
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
    _log.info(
        f"Space saved by dtype downgrade: {int(100 * (bytes_in - bytes_out) / bytes_in)} %",
    )
    return ds

def set_best_dtype_value(value, var_name):
    """
    Determines the best data type for a single value based on its variable name and converts it.

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

def add_sensors(ds, dsa):
    attrs = ds.attrs
    sensors = []
    for key, var in attrs.items():
        if not isinstance(var, str):
            continue
        if "{" not in var:
            continue
        if isinstance(eval(var), dict):
            sensors.append(key)

    sensor_name_type = {}
    for instr in sensors:
        if instr in ["altimeter"]:
            continue
        attr_dict = eval(attrs[instr])
        if attr_dict["make_model"] not in vocabularies.sensor_vocabs.keys():
            _log.error(f"sensor {attr_dict['make_model']} not found")
            continue
        var_dict = vocabularies.sensor_vocabs[attr_dict["make_model"]]
        if "serial" in attr_dict.keys():
            var_dict["serial_number"] = str(attr_dict["serial"])
            var_dict["long_name"] += f":{str(attr_dict['serial'])}"
        for var_name in ["calibration_date", "calibration_parameters"]:
            if var_name in attr_dict.keys():
                var_dict[var_name] = str(attr_dict[var_name])
        da = xr.DataArray(attrs=var_dict)
        sensor_var_name = f"sensor_{var_dict['sensor_type']}_{var_dict['serial_number']}".upper().replace(
            " ",
            "_",
        )
        dsa[sensor_var_name] = da
        sensor_name_type[var_dict["sensor_type"]] = sensor_var_name

    for key, var in attrs.copy().items():
        if not isinstance(var, str):
            continue
        if "{" not in var:
            continue
        if isinstance(eval(var), dict):
            attrs.pop(key)
    ds.attrs = attrs

    for key, sensor_type in variables_sensors.items():
        if key in dsa.variables:
            instr_key = sensor_name_type[sensor_type]
            dsa[key].attrs["sensor"] = instr_key

    return ds, dsa



def convert_to_og1(ds, num_vals=None):
    """
    Converts a given dataset to the OG1 format, applying specific variable names, units, and attributes as per the OG1 vocabulary and standards.

    This function is based on an example by Jen Seva (https://github.com/OceanGlidersCommunity/OG-format-user-manual/pull/136/files) and uses variable names from the OG1 vocabulary (https://vocab.nerc.ac.uk/collection/OG1/current/) and units from collection P07 (http://vocab.nerc.ac.uk/collection/P07/current/).

    The function processes the dataset, including handling quality control variables, setting coordinates, adding GPS information, and assigning various metadata attributes. It also adds sensor information and encodes times in the OG1 format.

    Parameters
    ----------
    :ds: xarray.Dataset
        The input dataset to convert.
    :num_vals: int, optional
        An optional argument to subset the input dataset to the first num_vals values. Default is None, which means no subsetting.
    Return
    ------
    dsa (xarray.Dataset) -    The converted dataset in OG1 format.
    
    Based on example by Jen Seva https://github.com/OceanGlidersCommunity/OG-format-user-manual/pull/136/files
    Using variable names from OG1 vocab https://vocab.nerc.ac.uk/collection/OG1/current/
    Using units from collection P07 http://vocab.nerc.ac.uk/collection/P07/current/
    e.g. mass_concentration_of_chlorophyll_a_in_sea_water from https://vocab.nerc.ac.uk/collection/P07/current/CF14N7/
    """
    dsa = xr.Dataset()
    for var_name in list(ds) + list(ds.coords):
        if "_QC" in var_name:
            continue
        dsa[var_name] = (
            "N_MEASUREMENTS",
            ds[var_name].values[:num_vals],
            ds[var_name].attrs,
        )
        qc_name = f"{var_name}_QC"
        if qc_name in list(ds):
            dsa[qc_name] = (
                "N_MEASUREMENTS",
                ds[qc_name].values[:num_vals].astype("int8"),
                ds[qc_name].attrs,
            )
            dsa[qc_name].attrs["long_name"] = (
                f'{dsa[var_name].attrs["long_name"]} Quality Flag'
            )
            dsa[qc_name].attrs["standard_name"] = "status_flag"
            dsa[qc_name].attrs["flag_values"] = np.array((1, 2, 3, 4, 9)).astype("int8")
            dsa[qc_name].attrs["flag_meanings"] = "GOOD UNKNOWN SUSPECT FAIL MISSING"
            dsa[var_name].attrs["ancillary_variables"] = qc_name
    if "time" in str(dsa.TIME.dtype):
        var_name = "TIME"
        dsa[var_name].values = dsa[var_name].values.astype(float)
        if np.nanmean(dsa[var_name].values) > 1e12:
            dsa[var_name].values = dsa[var_name].values / 1e9
    dsa = dsa.set_coords(("TIME", "LATITUDE", "LONGITUDE", "DEPTH"))
    for vname in ["LATITUDE", "LONGITUDE", "TIME"]:
        dsa[f"{vname}_GPS"] = dsa[vname].copy()
        dsa[f"{vname}_GPS"].values[dsa["nav_state"].values != 119] = np.nan
        dsa[f"{vname}_GPS"].attrs["long_name"] = f"{vname.lower()} of each GPS location"
    dsa["LATITUDE_GPS"].attrs["URI"] = (
        "https://vocab.nerc.ac.uk/collection/OG1/current/LAT_GPS/"
    )
    dsa["LONGITUDE_GPS"].attrs["URI"] = (
        "https://vocab.nerc.ac.uk/collection/OG1/current/LON_GPS/"
    )
    seaex_phase = dsa["nav_state"].values
    standard_phase = np.zeros(len(seaex_phase)).astype(int)
    standard_phase[seaex_phase == 115] = 3
    standard_phase[seaex_phase == 116] = 3
    standard_phase[seaex_phase == 119] = 3
    standard_phase[seaex_phase == 110] = 5
    standard_phase[seaex_phase == 118] = 5
    standard_phase[seaex_phase == 100] = 2
    standard_phase[seaex_phase == 117] = 1
    standard_phase[seaex_phase == 123] = 4
    standard_phase[seaex_phase == 124] = 4
    dsa["PHASE"] = xr.DataArray(
        standard_phase,
        coords=dsa["LATITUDE"].coords,
        attrs={
            "long_name": "behavior of the glider at sea",
            "phase_vocabulary": "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md",
        },
    )
    ds, dsa = add_sensors(ds, dsa)
    attrs = ds.attrs
    ts = pd.to_datetime(ds.time_coverage_start).strftime("%Y%m%dT%H%M")
    if "delayed" in ds.attrs["dataset_id"]:
        postscript = "delayed"
    else:
        postscript = "R"
    attrs["id"] = f"sea{str(attrs['glider_serial']).zfill(3)}_{ts}_{postscript}"
    attrs["title"] = "OceanGliders example file for SeaExplorer data"
    attrs["platform"] = "sub-surface gliders"
    attrs["platform_vocabulary"] = "https://vocab.nerc.ac.uk/collection/L06/current/27/"
    attrs["contributor_email"] = (
        "callum.rollo@voiceoftheocean.org, louise.biddle@voiceoftheocean.org, , , , , , "
    )
    attrs["contributor_role_vocabulary"] = "https://vocab.nerc.ac.uk/collection/W08/"
    attrs["contributor_role"] = (
        "Data scientist, PI, Operator, Operator, Operator, Operator, Operator, Operator,"
    )
    attrs["contributing_institutions"] = "Voice of the Ocean Foundation"
    attrs["contributing_institutions_role"] = "Operator"
    attrs["contributing_institutions_role_vocabulary"] = (
        "https://vocab.nerc.ac.uk/collection/W08/current/"
    )
    attrs["date_modified"] = attrs["date_created"]
    attrs["agency"] = "Voice of the Ocean"
    attrs["agency_role"] = "contact point"
    attrs["agency_role_vocabulary"] = "https://vocab.nerc.ac.uk/collection/C86/current/"
    attrs["data_url"] = (
        f"https://erddap.observations.voiceoftheocean.org/erddap/tabledap/{attrs['dataset_id']}"
    )
    attrs["rtqc_method"] = "IOOS QC QARTOD https://github.com/ioos/ioos_qc"
    attrs["rtqc_method_doi"] = "None"
    attrs["featureType"] = "trajectory"
    attrs["Conventions"] = "CF-1.10, OG-1.0"
    if num_vals:
        attrs["comment"] = (
            f"Dataset for demonstration purposes only. Original dataset truncated to {num_vals} values for the sake of simplicity"
        )
    attrs["start_date"] = attrs["time_coverage_start"]
    dsa.attrs = attrs
    dsa["TRAJECTORY"] = xr.DataArray(
        ds.attrs["id"],
        attrs={"cf_role": "trajectory_id", "long_name": "trajectory name"},
    )
    dsa["WMO_IDENTIFIER"] = xr.DataArray(
        ds.attrs["wmo_id"],
        attrs={"long_name": "wmo id"},
    )
    dsa["PLATFORM_MODEL"] = xr.DataArray(
        ds.attrs["glider_model"],
        attrs={
            "long_name": "model of the glider",
            "platform_model_vocabulary": "None",
        },
    )
    dsa["PLATFORM_SERIAL_NUMBER"] = xr.DataArray(
        f"sea{ds.attrs['glider_serial'].zfill(3)}",
        attrs={"long_name": "glider serial number"},
    )
    dsa["DEPLOYMENT_TIME"] = np.nanmin(dsa.TIME.values)
    dsa["DEPLOYMENT_TIME"].attrs = {
        "long_name": "date of deployment",
        "standard_name": "time",
        "units": "seconds since 1970-01-01T00:00:00Z",
        "calendar": "gregorian",
    }
    dsa["DEPLOYMENT_LATITUDE"] = dsa.LATITUDE.values[0]
    dsa["DEPLOYMENT_LATITUDE"].attrs = {"long_name": "latitude of deployment"}
    dsa["DEPLOYMENT_LONGITUDE"] = dsa.LONGITUDE.values[0]
    dsa["DEPLOYMENT_LONGITUDE"].attrs = {"long_name": "longitude of deployment"}
    dsa = encode_times_og1(dsa)
#    dsa = set_best_dtype(dsa)
    return dsa

def standardise_og10(ds):
    """
    Standardizes the given xarray Dataset according to predefined vocabularies.

    This function processes the input Dataset `ds` by renaming variables based on
    a predefined vocabulary and adding quality control (QC) variables where applicable.
    It also ensures that the attributes of the original variables are preserved and
    assigns the best data types to the resulting Dataset.

    Parameters
    ----------
    ds (xarray.Dataset): The input Dataset to be standardized.

    Returns
    -------
    xarray.Dataset: A new Dataset with standardized variable names and attributes.

    Notes
    -----
    - Variables with "qc" in their names are skipped.
    - If a variable name is found in the predefined vocabulary, it is renamed and
      its attributes are updated accordingly.
    - QC variables are added with the suffix "_QC" and linked to their corresponding
      variables via the "ancillary_variables" attribute.
    - Variables not found in the vocabulary are added as-is, and a log message is
      generated for those not in `vars_as_is`.

    Raises:
    - Any exceptions raised by the `set_best_dtype` function.
    """
    dsa = xr.Dataset()
    dsa.attrs = ds.attrs

    ds_renamed = ds.rename_dims(vocabularies.dims_rename_dict)
#    ds_renamed = ds_renamed.rename_vars(vocabularies.coords_rename_dict)
#    ds_renamed = ds_renamed.rename_vars(vocabularies.vars_rename_dict)
    vars_to_keep = set(vocabularies.vars_rename_dict.values())

    # Rename dimensions based on the vocabularies.dims_rename_dict
    for dim_name, size in ds_renamed.dims.items():
        if dim_name not in dsa.dims:
            dsa = dsa.assign_coords({dim_name: np.arange(size)})
    # Rename coordinates based on the vocabularies.coords_rename_dict
    for coord_name in ds_renamed.dims.items():
        if coord_name in vocabularies.coords_rename_dict:
            new_coord_name = vocabularies.coords_rename_dict[coord_name]
            dsa = dsa.rename({coord_name: new_coord_name})

    for var_name in list(ds) + list(ds.coords):
        if "qc" in var_name:
            continue
        if var_name in vocabularies.standard_names.keys():
            print(var_name)
            name = vocabularies.standard_names[var_name]
            dsa[name] = ("time", ds[var_name].values, vocabularies.vocab_attrs[name])
            for key, val in ds[var_name].attrs.items():
                if key not in dsa[name].attrs.keys():
                    dsa[name].attrs[key] = val
            qc_name = f"{var_name}_qc"
            if qc_name in list(ds):
                dsa[f"{name}_QC"] = ("time", ds[qc_name].values, ds[qc_name].attrs)
                dsa[name].attrs["ancillary_variables"] = f"{name}_QC"
        else:
#           Note: this differs from the original standardise_og10 function
#            dsa[var_name] = ("time", ds[var_name].values, ds[var_name].attrs)
            if var_name not in vars_as_is:
                _log.error(f"variable {var_name} not translated.")
                
    # dsa = set_best_dtype(dsa) - this changes data types - skipping for now
    return dsa

##----------------------------------------------------------------------------------------------------------------------------
## Editing variables
##----------------------------------------------------------------------------------------------------------------------------
vars_as_is = [
    "altimeter",
    "nav_resource",
    "angular_cmd",
    "angular_pos",
    "ballast_cmd",
    "ballast_pos",
    "dead_reckoning",
    "declination",
    "desired_heading",
    "dive_num",
    "internal_pressure",
    "internal_temperature",
    "linear_cmd",
    "linear_pos",
    "security_level",
    "voltage",
    "distance_over_ground",
#    "ad2cp_beam1_cell_number1",
#    "ad2cp_beam2_cell_number1",
#    "ad2cp_beam3_cell_number1",
#    "ad2cp_beam4_cell_number1",
#    "vertical_distance_to_seafloor",
#    "profile_direction",
    "profile_num",
    "nav_state",
]

def create_renamed_dataset(ds):
    from seagliderOG1 import vocabularies

    # Apply renaming using the dictionaries
    ds_renamed = ds.rename_dims(vocabularies.dims_rename_dict)
    ds_renamed = ds_renamed.rename_vars(vocabularies.coords_rename_dict)
    ds_renamed = ds_renamed.rename_vars(vocabularies.vars_rename_dict)

    # Remove variables not in vars_rename_dict().values
    vars_to_keep = set(vocabularies.vars_rename_dict.values())
    ds_renamed = ds_renamed[vars_to_keep]

    # Check if PROFILE_NUMBER is present as a variable
    if 'PROFILE_NUMBER' not in ds_renamed.variables:
        ds_renamed = assign_profile_number(ds_renamed)
    if 'PHASE' not in ds_renamed.variables:
        ds_renamed = assign_phase(ds_renamed)

    # Cycle through the variables within ds_renamed and ds_renamed.coords
    for name in list(ds_renamed):
        if name in vocabularies.standard_names.values():
            for key, val in vocabularies.vocab_attrs[name].items():
                if key not in ds_renamed[name].attrs.keys():
                    ds_renamed[name].attrs[key] = val

    # Update the attributes time_coverage_start and time_coverage_end
    time_coverage_start = pd.to_datetime(ds_renamed.TIME.values[0]).strftime("%Y%m%dT%H%M%S")
    time_coverage_end = pd.to_datetime(ds_renamed.TIME.values[-1]).strftime("%Y%m%dT%H%M%S")
    ds_renamed.attrs["time_coverage_start"] = time_coverage_start
    ds_renamed.attrs["time_coverage_end"] = time_coverage_end

    # Update the attribute date_created to today's date
    ds_renamed.attrs["date_created"] = datetime.utcnow().strftime('%Y%m%dT%H%M%S')

    # Check whether time_coverage_start is before start_date.  If so, then update start_date
    if time_coverage_start < ds_renamed.attrs["start_date"]:
        ds_renamed.attrs["start_date"] = time_coverage_start

    return ds_renamed

##----------------------------------------------------------------------------------------------------------------------------
## Editing attributes
##----------------------------------------------------------------------------------------------------------------------------
def generate_attributes(ds_all):
    """
    Generate a dictionary of attributes to add and change for a dataset.

    Parameters:
    ds_all (object): An object containing various metadata attributes of the dataset.

    Returns:
    tuple: A tuple containing two dictionaries:
        - attr_to_add (dict): Attributes to add to the dataset.
        - attr_to_change (dict): Attributes to change in the dataset.

    The dictionaries contain the following keys:
    attr_to_add:
        - title: Title of the dataset.
        - platform: Platform type.
        - platform_vocabulary: URL to the platform vocabulary.
        - id: Unique identifier for the dataset.
        - contributor_email: Email of the contributor.
        - contributor_role_vocabulary: URL to the contributor role vocabulary.
        - contributing_institutions: Name of the contributing institutions.
        - contributing_institutions_vocabulary: URL to the contributing institutions vocabulary.
        - contributing_institutions_role: Role of the contributing institutions.
        - contributing_institutions_role_vocabulary: URL to the contributing institutions role vocabulary.
        - uri: Unique resource identifier.
        - uri_comment: Comment about the URI.
        - web_link: Web link to the dataset.
        - start_date: Start date of the dataset.
        - featureType: Feature type of the dataset.
        - landstation_version: Version of the land station.
        - glider_firmware_version: Version of the glider firmware.
        - rtqc_method: Real-time quality control method.
        - rtqc_method_doi: DOI for the RTQC method.
        - doi: DOI of the dataset.
        - data_url: URL to the data.
        - comment: History comment.

    attr_to_change:
        - time_coverage_start: Start time of the dataset coverage.
        - time_coverage_end: End time of the dataset coverage.
        - Conventions: Conventions followed by the dataset.
        - date_created: Creation date of the dataset.
        - date_modified: Modification date of the dataset.
        - contributor_name: Name of the contributor.
        - contributor_role: Role of the contributor.
    """

    title = "OceanGliders trajectory file"
    platform = "sub-surface gliders"
    platform_vocabulary = "https://vocab.nerc.ac.uk/collection/L06/current/27/"

    time_str = ds_all.time_coverage_start.replace('_', '').replace(':', '').rstrip('Z').rstrip('Z').replace('-','')
    id = ds_all.platform_id + '_' + time_str + '_delayed'
    time_coverage_start = time_str
    time_coverage_end = ds_all.time_coverage_end.replace('_', '').replace(':', '').rstrip('Z').replace('-','')

    site = ds_all.summary
    contributor_name = ds_all.creator_name + ', ' + ds_all.contributor_name
    contributor_email = ds_all.creator_email
    contributor_role = "PI, " + ds_all.contributor_role
    contributor_role_vocabulary = "http://vocab.nerc.ac.uk/search_nvs/W08/"
    contributing_institutions = "University of Washington - School of Oceanography, University of Hamburg - Institute of Oceanography"
    contributing_institutions_vocabulary = 'https://edmo.seadatanet.org/report/1434, https://edmo.seadatanet.org/report/1156'
    contributing_institutions_role = "Operator, Data scientist"
    contributing_institutions_role_vocabulary = "http://vocab.nerc.ac.uk/collection/W08/current/"
    uri = ds_all.uuid
    uri_comment = "UUID"
    web_link = "https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.nodc:0111844"
    comment = "history: " + ds_all.history
    start_date = time_coverage_start
    date_created = ds_all.date_created.replace('_', '').replace(':', '').rstrip('Z').rstrip('Z').replace('-','')
    date_modified = datetime.now().strftime('%Y%m%dT%H%M%S')
    featureType = "trajectory"
    Conventions = "CF-1.10,OG-1.0"
    landstation_version = ds_all.base_station_version + ds_all.base_station_micro_version
    glider_firmware_version = ds_all.seaglider_software_version
    rtqc_method = "No QC applied"
    rtqc_method_doi = "n/a"
    doi = "none yet"
    data_url = ""

    attr_to_add = {
        "title": title,
        "platform": platform, 
        "platform_vocabulary": platform_vocabulary,
        "id": id,
        "contributor_email": contributor_email,
        "contributor_role_vocabulary": contributor_role_vocabulary,
        "contributing_institutions": contributing_institutions,
        "contributing_institutions_vocabulary": contributing_institutions_vocabulary,
        "contributing_institutions_role": contributing_institutions_role,
        "contributing_institutions_role_vocabulary": contributing_institutions_role_vocabulary,
        "uri": uri,
        "uri_comment": uri_comment,
        "web_link": web_link,
        "comment": comment,
        "start_date": start_date,
        "featureType": featureType,
        "landstation_version": landstation_version,
        "glider_firmware_version": glider_firmware_version,
        "rtqc_method": rtqc_method,
        "rtqc_method_doi": rtqc_method_doi,
        "doi": doi,
        "data_url": data_url,
    }

    attr_to_change = {
        "time_coverage_start": time_coverage_start,
        "time_coverage_end": time_coverage_end,
        "Conventions": Conventions,
        "date_created": date_created,
        "date_modified": date_modified,
        "contributor_name": contributor_name,
        "contributor_role": contributor_role,
    }

    attr_as_is = [
        "naming_authority",
        "institution",
        "project",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_vertical_min",
        "geospatial_vertical_max",
        "license",
        "keywords",
        "keywords_vocabulary",
        "file_version",
        "acknowledgment",
        "date_created",
        "disclaimer",
    ]


    # After changing attributes
    attr_to_remove = [
        "summary",
        "history",
        "time_coverage_resolution",
        "geospatial_lat_units",
        "geospatial_lon units",
        "geospatial_vertical_units",
        "geospatial_vertical_positive",
        "geospatial_vertical_resolution",
        "geospatial_lat_resolution",
        "geospatial_lon_resolution",
        "creator_name",
        "creator_email",
        "Metadata_Conventions",
    ]


    return attr_to_add, attr_as_is, attr_to_change, attr_to_remove


def modify_attributes(ds, attr_to_add, attr_as_is, attr_to_change, attr_to_remove):

    # Define the order of attributes
    ordered_attributes = [
        "title", "platform", "platform_vocabulary", "id", "naming_authority", 
        "institution", "geospatial_lat_min", "geospatial_lat_max", 
        "geospatial_lon_min", "geospatial_lon_max", "geospatial_vertical_min", 
        "geospatial_vertical_max", "time_coverage_start", "time_coverage_end", 
        "site", "project", "contributor_name", "contributor_email", 
        "contributor_role", "contributor_role_vocabulary", "uri", "data_url", 
        "doi", "rtqc_method", "rtqc_method_doi", "web_link", "comment", 
        "start_date", "date_created", "featureType", "Conventions"
    ]
    # Retain specified attributes
    new_attrs = {key: ds.attrs[key] for key in attr_as_is if key in ds.attrs}

    # Change specified attributes
    for key, value in attr_to_change.items():
        new_attrs[key] = value

    # Add new attributes
    for key, value in attr_to_add.items():
        if key not in new_attrs:
            new_attrs[key] = value

    # Remove specified attributes
    for key in attr_to_remove:
        if key in new_attrs:
            del new_attrs[key]

    ds.attrs = new_attrs

    # Add the rest of the attributes that are present in the dataset but not in the ordered list
    for attr in ds.attrs:
        if attr not in ordered_attributes:
            ordered_attributes.append(attr)

    # Reorder the attributes in ds_new_att according to ordered_attributes
    new_attrs = {attr: ds.attrs[attr] for attr in ordered_attributes if attr in ds.attrs}
    for attr in ds.attrs:
        if attr not in new_attrs:
            new_attrs[attr] = ds.attrs[attr]

    ds.attrs = new_attrs
    return ds

if __name__ == "__main__":
    dsn = xr.open_dataset(
        "/data/data_l0_pyglider/nrt/SEA76/M19/timeseries/mission_timeseries.nc",
    )
    dsn = standardise_og10(dsn)
    dsn = convert_to_og1(dsn)
    dsn.to_netcdf("new.nc")

##----------------------------------------------------------------------------------------------------------------------------
## Calculations for new variables
##----------------------------------------------------------------------------------------------------------------------------
def calc_Z(ds):
    """
    Calculate the depth (Z position) of the glider using the gsw library to convert pressure to depth.
    
    Parameters
    ----------
    ds (xarray.Dataset): The input dataset containing 'PRES', 'LATITUDE', and 'LONGITUDE' variables.
    
    Returns
    -------
    xarray.Dataset: The dataset with an additional 'DEPTH' variable.
    """
    # Ensure the required variables are present
    if 'PRES' not in ds.variables or 'LATITUDE' not in ds.variables or 'LONGITUDE' not in ds.variables:
        raise ValueError("Dataset must contain 'PRES', 'LATITUDE', and 'LONGITUDE' variables.")

    # Initialize the new variable with the same dimensions as dive_num
    ds['DEPTH_Z'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))

    # Calculate depth using gsw
    depth = gsw.z_from_p(ds['PRES'], ds['LATITUDE'])
    ds['DEPTH_Z'] = depth

    # Assign the calculated depth to a new variable in the dataset
    ds['DEPTH_Z'].attrs = {
        "units": "meters",
        "positive": "up",
        "standard_name": "depth",
        "comment": "Depth calculated from pressure using gsw library, positive up.",
    }
    
    return ds

def convert_velocity_units(ds, var_name):
    """
    Convert the units of the specified variable to m/s if they are in cm/s.
    
    Parameters:
    ds (xarray.Dataset): The dataset containing the variable.
    var_name (str): The name of the variable to check and convert.
    
    Returns:
    xarray.Dataset: The dataset with the converted variable.
    """
    if var_name in ds.variables:
        # Pass through all other attributes as is
        for attr_name, attr_value in ds[var_name].attrs.items():
            if attr_name != 'units':
                ds[var_name].attrs[attr_name] = attr_value
            elif attr_name == 'units':
                if ds[var_name].attrs['units'] == 'cm/s':  
                    ds[var_name].values = ds[var_name].values / 100.0
                    ds[var_name].attrs['units'] = 'm/s'
                    print(f"Converted {var_name} to m/s")
                else:
                    print(f"{var_name} is already in m/s or units attribute is missing")
        
    else:
        print(f"{var_name} not found in the dataset")
    return ds

def assign_profile_number(ds):
    # Remove the variable dive_num_cast if it exists
    if 'dive_num_cast' in ds.variables:
        ds = ds.drop_vars('dive_num_cast')
    # Initialize the new variable with the same dimensions as dive_num
    ds['dive_num_cast'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))

    # Iterate over each unique dive_num
    for dive in np.unique(ds['dive_num']):
        # Get the indices for the current dive
        dive_indices = np.where(ds['dive_num'] == dive)[0]
        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]
        
        # Find the index of the maximum pressure between start_index and end_index
        pmax = np.max(ds['PRES'][start_index:end_index + 1].values) 

        # Find the index where PRES attains the value pmax between start_index and end_index
        pmax_index = start_index + np.argmax(ds['PRES'][start_index:end_index + 1].values == pmax)
        
        # Assign dive_num to all values up to and including the point where pmax is reached
        ds['dive_num_cast'][start_index:pmax_index + 1] = dive

        # Assign dive_num + 0.5 to all values after pmax is reached
        ds['dive_num_cast'][pmax_index + 1:end_index + 1] = dive + 0.5

        # Remove the variable PROFILE_NUMBER if it exists
        if 'PROFILE_NUMBER' in ds.variables:
            ds = ds.drop_vars('PROFILE_NUMBER')
        # Assign PROFILE_NUMBER as 2 * dive_num_cast - 1
        ds['PROFILE_NUMBER'] = 2 * ds['dive_num_cast'] - 1
    return ds

def assign_phase(ds):
    """
    This function adds new variables 'PHASE' and 'PHASE_QC' to the dataset `ds`, which indicate the phase of each measurement. The phase is determined based on the pressure readings ('PRES') for each unique dive number ('dive_num').
    
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

    # Initialize the new variable with the same dimensions as dive_num
    ds['PHASE'] = (['N_MEASUREMENTS'], np.full(ds.dims['N_MEASUREMENTS'], np.nan))
    # Initialize the new variable PHASE_QC with the same dimensions as dive_num
    ds['PHASE_QC'] = (['N_MEASUREMENTS'], np.zeros(ds.dims['N_MEASUREMENTS'], dtype=int))

    # Iterate over each unique dive_num
    for dive in np.unique(ds['dive_num']):
        # Get the indices for the current dive
        dive_indices = np.where(ds['dive_num'] == dive)[0]
        # Find the start and end index for the current dive
        start_index = dive_indices[0]
        end_index = dive_indices[-1]
        
        # Find the index of the maximum pressure between start_index and end_index
        pmax = np.max(ds['PRES'][start_index:end_index + 1].values) 

        # Find the index where PRES attains the value pmax between start_index and end_index
        pmax_index = start_index + np.argmax(ds['PRES'][start_index:end_index + 1].values == pmax)
        
        # Assign phase 2 to all values up to and including the point where pmax is reached
        ds['PHASE'][start_index:pmax_index + 1] = 2

        # Assign phase 1 to all values after pmax is reached
        ds['PHASE'][pmax_index + 1:end_index + 1] = 1

    return ds

