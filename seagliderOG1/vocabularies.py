"""Vocabularies and mappings for OG1 format conversion.

This module defines the vocabulary mappings, unit conversions, and attribute
configurations used to convert Seaglider basestation files to OG1 format.
It loads YAML configuration files and defines various dictionaries used
throughout the conversion process.

Key Components:
- Variable name mappings from basestation to OG1 format
- Unit conversion factors and formatting rules
- Global attribute definitions and ordering
- Variables to include/exclude during conversion
- Dimension renaming mappings

Configuration Files:
- OG1_var_names.yaml: Variable name mappings
- OG1_vocab_attrs.yaml: Variable attribute vocabularies
- OG1_sensor_attrs.yaml: Sensor attribute definitions
- OG1_global_attrs.yaml: Global attribute configurations
- OG1_author.yaml: Example contributor information, loaded on demand via
  :func:`load_default_contributors` (never at import)

Notes
-----
This module is primarily data-driven and loads most configuration from YAML files
in the config/ directory. The YAML-based approach allows easy modification of
OG1 format requirements without code changes.

"""

import os
import pathlib
import warnings

import yaml

# Set the directory for yaml files as package directory + 'config/'
script_dir = pathlib.Path(__file__).parent.absolute()
config_dir = os.path.join(script_dir, "config/")

# Dimension renaming: maps basestation dimension names to OG1 standard names
dims_rename_dict = {"sg_data_point": "N_MEASUREMENTS"}

# NERC W08 "SensorML Contact Section Terms": the controlled vocabulary the OG1 spec
# cites for contributor_role and contributing_institutions_role (fetched from
# vocab.nerc.ac.uk 2026-10-08). The seven preferred labels and their term URIs.
_W08 = "http://vocab.nerc.ac.uk/collection/W08/current/"
ROLE_VOCABULARY = {
    "Manufacturer": _W08 + "CONT0001/",
    "Owner": _W08 + "CONT0002/",
    "Operator": _W08 + "CONT0003/",
    "PI": _W08 + "CONT0004/",
    "Technical Coordinator": _W08 + "CONT0005/",
    "Data scientist": _W08 + "CONT0006/",
    "Service Provider": _W08 + "CONT0007/",
}

# Attested spelling variants seen in real files, mapped to the preferred W08 label.
# Add an alias only when it appears in a real file (basestation files and the sp041
# example both write PI as "Principal investigator" with the CONT0004 URI).
ROLE_ALIASES = {
    "principal investigator": "PI",
}

# Preferred units for OG1 format - conversion will be attempted if mapping exists
preferred_units = ["m s-1", "dbar", "S m-1"]

# Unit string standardization: maps various unit representations to preferred format
unit_str_format = {
    "m/s": "m s-1",
    "cm/s": "cm s-1",
    "S/m": "S m-1",
    "mS/cm": "mS cm-1",
    "meters": "m",
    "degrees_Celsius": "Celsius",
    "degreesCelsius": "Celsius",
    "g/m^3": "g m-3",
    "kg/m^3": "kg m-3",
    "g/kg": "g kg-1",
    "seconds": "s",
}

# Unit conversion definitions: each entry defines source unit, target unit, and conversion factor
unit1_to_unit2 = {
    "cm s-1_to_m s-1": {"current_unit": "cm s-1", "new_unit": "m s-1", "factor": 0.01},
    "cm/s_to_m/s": {"current_unit": "cm/s", "new_unit": "m/s", "factor": 0.01},
    "m/s_to_cm/s": {"current_unit": "m/s", "new_unit": "cm/s", "factor": 100},
    "m s-1_to_cm s-1": {"current_unit": "m s-1", "new_unit": "cm s-1", "factor": 100},
    "S/m_to_mS/cm": {"current_unit": "S/m", "new_unit": "mS/cm", "factor": 10},
    "S m-1_to_mS cm-1": {"current_unit": "S m-1", "new_unit": "mS cm-1", "factor": 10},
    "mS/cm_to_S/m": {"current_unit": "mS/cm", "new_unit": "S/m", "factor": 0.1},
    "mS cm-1_to_S m-1": {"current_unit": "mS cm-1", "new_unit": "S m-1", "factor": 0.1},
    "dbar_to_Pa": {"current_unit": "dbar", "new_unit": "Pa", "factor": 10000},
    "Pa_to_dbar": {"current_unit": "Pa", "new_unit": "dbar", "factor": 0.0001},
    "dbar_to_kPa": {"current_unit": "dbar", "new_unit": "kPa", "factor": 10},
    "degreesCelsius_to_Celsius": {
        "current_unit": "degreesCelsius",
        "new_unit": "Celsius",
        "factor": 1,
    },
    "Celsius_to_degreesCelsius": {
        "current_unit": "Celsius",
        "new_unit": "degreesCelsius",
        "factor": 1,
    },
    "m_to_cm": {"current_unit": "m", "new_unit": "cm", "factor": 100},
    "m_to_km": {"current_unit": "m", "new_unit": "km", "factor": 0.001},
    "cm_to_m": {"current_unit": "cm", "new_unit": "m", "factor": 0.01},
    "km_to_m": {"current_unit": "km", "new_unit": "m", "factor": 1000},
    "g/m^3_to_kg/m^3": {"current_unit": "g/m^3", "new_unit": "kg/m^3", "factor": 0.001},
    "g m-3_to_kg m-3": {"current_unit": "g m-3", "new_unit": "kg m-3", "factor": 0.001},
    "kg/m^3_to_g/m^3": {"current_unit": "kg/m^3", "new_unit": "g/m^3", "factor": 1000},
    "kg m-3_to_g m-3": {"current_unit": "kg m-3", "new_unit": "g m-3", "factor": 1000},
    "micrograms/liter_to_mg m-3": {
        "current_unit": "micrograms/liter",
        "new_unit": "mg m-3",
        "factor": 1.0,
    },
}

# Variables to exclude from OG1 output (derived variables, duplicates, etc.)
vars_to_remove = [
    "dissolved_oxygen_sat",
    "depth",
    "eng_depth",
    "eng_elaps_t",
    "eng_elaps_t_0000",
    "eng_rec",
    "eng_GC_state",
    "latitude_gsm",
    "longitude_gsm",
    "sound_velocity",
    "eng_sbect_condFreq",
    "eng_sbect_tempFreq",
    "glide_angle_gsm",
    "horz_speed_gsm",
    "north_displacement_gsm",
    "east_displacement_gsm",
    "polar_heading",
    "speed_gsm",
    "vert_speed_gsm",
    "dive_num_cast",
    "density",
    "gsw_sigma3",
    "gsw_sigma4",
    "theta",
    # "time",
]

# Variables to keep unchanged during conversion (currently empty)
vars_as_is = []

# --------------------------------
# Variables + variable attributes
# --------------------------------
# Variable name mappings: basestation variable name -> OG1 standard name
# Based on https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/utilities/vocabularies.py
with open(config_dir + "OG1_var_names.yaml", "r") as file:
    standard_names = yaml.safe_load(file)

# Variable attribute vocabularies for OG1 format
# Reference: http://vocab.nerc.ac.uk/scheme/OG1/current/
with open(config_dir + "OG1_vocab_attrs.yaml", "r") as file:
    vocab_attrs = yaml.safe_load(file)

# Sensor attribute vocabularies for OG1 format
# Reference: http://vocab.nerc.ac.uk/scheme/OG_SENSORS/current/
with open(config_dir + "OG1_sensor_attrs.yaml", "r") as file:
    sensor_vocabs = yaml.safe_load(file)


# --------------------------------
# Global Attributes
# --------------------------------


def load_default_contributors() -> dict[str, str]:
    """Load the example contributor block from ``config/OG1_author.yaml``.

    Not loaded at import: a converted file gains contributor details only when a
    caller passes them to :func:`seagliderOG1.convertOG1.convert_to_OG1`. The
    file is an editable example, not a default identity written into every output.

    Returns
    -------
    dict of str
        Contributor attributes read from ``OG1_author.yaml``.

    """
    with open(config_dir + "OG1_author.yaml", "r") as file:
        return yaml.safe_load(file)


def __getattr__(name: str) -> object:
    """Resolve the deprecated module attribute ``contrib_to_append`` lazily.

    Preserves ``vocabularies.contrib_to_append`` for existing callers (it returns
    :func:`load_default_contributors`) while no longer loading the file at import.

    Parameters
    ----------
    name : str
        The attribute being accessed.

    Returns
    -------
    object
        The example contributor block when ``name`` is ``"contrib_to_append"``.

    Raises
    ------
    AttributeError
        For any other attribute name.

    """
    if name == "contrib_to_append":
        warnings.warn(
            "vocabularies.contrib_to_append is deprecated and no longer loaded at import; "
            "call vocabularies.load_default_contributors() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return load_default_contributors()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


# Preferred order for global attributes in OG1 files
order_of_attr = [
    "title",  # OceanGliders trajectory file
    "id",  # sg015_20040920T000000_delayed
    "platform",  # sub-surface gliders
    "platform_vocabulary",  # https://vocab.nerc.ac.uk/collection/L06/current/27
    "PLATFORM_SERIAL_NUMBER",  # sg015 --> This should be a variable, not an attribute
    "naming_authority",  # edu.washington.apl
    "institution",  # University of washington
    "internal_mission_identifier",  # p0150003_20040924
    "geospatial_lat_min",  # decimal degree
    "geospatial_lat_max",  # decimal degree
    "geospatial_lon_min",  # decimal degree
    "geospatial_lon_max",  # decimal degree
    "geospatial_vertical_min",  # meter depth
    "geospatial_vertical_max",  # meter depth
    "time_coverage_start",  # YYYYmmddTTHHMMss
    "time_coverage_end",  # YYYYmmddTTHHMMss
    "site",  # MOOSE_T00
    "site_vocabulary",  # to be defined
    "program",  # MOOSE glider program
    "program_vocabulary",  # to be defined
    "project",  # SAMBA
    "network",  # Southern California Coastal Ocean Observing System (SCCOOS)
    "contributor_name",  # Firstname Lastname, Firstname Lastname
    "contributor_role",  # Principal Investigator, Operator
    "contributor_role_vocabulary",  # http://vocab.nerc.ac.uk/collection/W08/current/
    "contributor_email",  # name@name.com, name@name.com
    "contributor_id",  # ORCID, ORCID
    "contributing_institutions",  # University of Washington, University of Washington
    "contributing_institutions_vocabulary",  # https://edmo.seadatanet.org/report/544, https://ror.org/012tb2g32
    "contributing_institutions_role",  # PI, Operator
    "contributing_institutions_role_vocabulary",  # https://vocab.nerc.ac.uk/collection/W08/current/
    "uri",  # other universal resource identifiers separated by commas
    "data_url",  # url link to where OG1.0 file is hosted
    "doi",  # data doi for OG1
    "rtqc_method",  # No QC applied
    "rtqc_method_doi",  # n/a
    "web_link",  # url for information rleated to glider mission, multiple urls separated by comma
    "comment",  # miscellaneous information
    "start_date",  # datetime of glider deployment YYYYmmddTHHMMss
    "date_created",  # date of creation of this dataset YYYYmmddTHHMMss
    "featureType",  # trajectory
    "Conventions",  # CF-1.10,OG-1.0
    "date_modified",  # date of last modification of this dataset YYYYmmddTHHMMss
]

# Global attribute configuration for OG1 conversion
# Defines which attributes to keep, rename, or add during conversion
# Compatible with base_station_version 2.8, nodc_template_version_v0.9
with open(config_dir + "OG1_global_attrs.yaml", "r") as file:
    global_attrs = yaml.safe_load(file)
