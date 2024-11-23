import yaml
import pathlib
import os

# Set the directory for yaml files as the root directory + 'config/'
script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
rootdir = parent_dir
config_dir = os.path.join(rootdir, 'config/')

# Dimension renaming
dims_rename_dict = {'sg_data_point': 'N_MEASUREMENTS'}

# Specify the preferred units, and it will convert if the conversion is available in unit_conversion
preferred_units = ['m s-1', 'dbar', 'S m-1']

# String formats for units.  The key is the original, the value is the desired format
unit_str_format = {
    'm/s': 'm s-1',
    'cm/s': 'cm s-1',
    'S/m': 'S m-1',
    'meters': 'm',
    'degrees_Celsius': 'Celsius',
    'g/m^3': 'g m-3',
}



# Various conversions from the key to units_name with the multiplicative conversion factor
unit_conversion = {
    'cm/s': {'units_name': 'm/s', 'factor': 0.01},
    'cm s-1': {'units_name': 'm s-1', 'factor': 0.01},
    'm/s': {'units_name': 'cm/s', 'factor': 100},
    'm s-1': {'units_name': 'cm s-1', 'factor': 100},
    'S/m': {'units_name': 'mS/cm', 'factor': 0.1},
    'S m-1': {'units_name': 'mS cm-1', 'factor': 0.1},
    'mS/cm': {'units_name': 'S/m', 'factor': 10},
    'mS cm-1': {'units_name': 'S m-1', 'factor': 10},
    'dbar': {'units_name': 'Pa', 'factor': 10000},
    'Pa': {'units_name': 'dbar', 'factor': 0.0001},
    'dbar': {'units_name': 'kPa', 'factor': 10},
    'degrees_Celsius': {'units_name': 'Celsius', 'factor': 1},
    'Celsius': {'units_name': 'degrees_Celsius', 'factor': 1},
    'm': {'units_name': 'cm', 'factor': 100},
    'm': {'units_name': 'km', 'factor': 0.001},
    'cm': {'units_name': 'm', 'factor': 0.01},
    'km': {'units_name': 'm', 'factor': 1000},
    'g m-3': {'units_name': 'kg m-3', 'factor': 0.001},
    'kg m-3': {'units_name': 'g m-3', 'factor': 1000},
}

# Based on https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/utilities/vocabularies.py
# Key is the basestation variable name, value is the OG1 standard name
with open(config_dir + 'OG1_var_names.yaml', 'r') as file:
    standard_names = yaml.safe_load(file)

vars_to_remove = [
    'dissolved_oxygen_sat',
    'depth', 
    'eng_depth',
    'eng_elaps_t',
    'eng_elaps_t_0000',
    'latitude_gsm',
    'longitude_gsm',
    'sound_velocity',
    'theta',
    'time',
    'eng_sbect_condFreq',
    'eng_sbect_tempFreq',
    'glide_angle_gsm',
    'horz_speed_gsm',
    'north_displacement_gsm',
    'east_displacement_gsm',
    'speed_gsm',
    'vert_speed_gsm',
    'dive_num_cast',
    'density'
]

vars_as_is = []

# Various vocabularies for OG1: http://vocab.nerc.ac.uk/scheme/OG1/current/
with open(config_dir + 'OG1_vocab_attrs.yaml', 'r') as file:
    vocab_attrs = yaml.safe_load(file)

# Various sensor vocabularies for OG1: http://vocab.nerc.ac.uk/scheme/OG_SENSORS/current/
with open(config_dir + 'OG1_sensor_attrs.yaml', 'r') as file:
    sensor_vocabs = yaml.safe_load(file)


#--------------------------------
# Attributes
#--------------------------------
with open(config_dir + 'OG1_author.yaml', 'r') as file:
    contrib_to_append = yaml.safe_load(file)

order_of_attr = [
    'title', # OceanGliders trajectory file
    'id', # sg015_20040920T000000_delayed
    'platform', # sub-surface gliders
    'platform_vocabulary', # https://vocab.nerc.ac.uk/collection/L06/current/27
    'PLATFORM_SERIAL_NUMBER', # sg015
    'naming_authority', # edu.washington.apl
    'institution', # University of washington
    'internal_mission_identifier', # p0150003_20040924
    'geospatial_lat_min', # decimal degree
    'geospatial_lat_max', # decimal degree
    'geospatial_lon_min', # decimal degree
    'geospatial_lon_max', # decimal degree
    'geospatial_vertical_min', # meter depth
    'geospatial_vertical_max', # meter depth
    'time_coverage_start', # YYYYmmddTTHHMMss
    'time_coverage_end', # YYYYmmddTTHHMMss
    'site', # MOOSE_T00
    'site_vocabulary', # to be defined
    'program', # MOOSE glider program
    'program_vocabulary', # to be defined
    'project', # SAMBA
    'network', # Southern California Coastal Ocean Observing System (SCCOOS)
    'contributor_name', # Firstname Lastname, Firstname Lastname
    'contributor_role', # Principal Investigator, Operator
    'contributor_role_vocabulary', # http://vocab.nerc.ac.uk/collection/W08/current/
    'contributor_email', # name@name.com, name@name.com
    'contributor_id', # ORCID, ORCID
    'contributor_role_vocabular', # http://vocab.nerc.ac.uk/search_nvs/W08/
    'contributing_institutions', # University of Washington, University of Washington
    'contributing_institutions_vocabulary', # https://edmo.seadatanet.org/report/544, https://ror.org/012tb2g32
    'contributing_institutions_role', # PI, Operator
    'contributing_institutions_role_vocabulary', # https://vocab.nerc.ac.uk/collection/W08/current/
    'uri', # other universal resource identifiers separated by commas
    'data_url', #url link to where OG1.0 file is hosted
    'doi', # data doi for OG1
    'rtqc_method', # No QC applied
    'rtqc_method_doi', # n/a
    'web_link', # url for information rleated to glider mission, multiple urls separated by comma
    'comment', # miscellaneous information
    'start_date', # datetime of glider deployment YYYYmmddTHHMMss
    'date_created', # date of creation of this dataset YYYYmmddTHHMMss
    'featureType', #trajectory
    'Conventions', # CF-1.10,OG-1.0
    'date_modified', # date of last modification of this dataset YYYYmmddTHHMMss
]

# Attributes to convert sg015 Labrador Sea to OG1
# base_station_version 2.8
# nodc_template_version_v0.9

with open(config_dir + 'OG1_global_attrs.yaml', 'r') as file:
    global_attrs = yaml.safe_load(file)

