attr_to_var = {
    'landstation_version': 'base_station_version', # append 'basestation v'
    'glider_firmware_version': 'seaglider_software_version', # append 'seaglider v'
}

vocab_attrs = {
    "WMO_IDENTIFIER": {
        "long_name": "wmo id",
    },
    "PLATFORM_MODEL":{
        "long_name": "model of the glider",
        "platform_model_vocabulary": "https://vocab.nerc.ac.uk/collection/B76/current/B7600024/",
    },
    "PLATFORM_SERIAL_NUMBER":{
        "long_name": "glider serial number"
    },
    "PLATFORM_NAME": {
        "long_name": "Local or nickname of the glider",
    },
    "PLATFORM_DEPTH_RATING":{
        "long_name": "depth limit in meters of the glider for this mission",
        "convention": "positive value expected - e.g., 100m depth = 100",
    },
    "ICES_CODE": {
        "long_name": "ICES platform code of the glider ",
        "ices_code_vocabulary": "https://vocab.ices.dk/?codeguid=690d82e2 -b4e2-4e30-9772-7499c66144c6",
    },
    "PLATFORM_MAKER": {
        "long_name": "glider manufacturer",
        "platform_maker_vocabulary": "https://vocab.nerc.ac.uk/collection/B75/current/ORG01077/",
        # University of Washington, School of Oceanography (https://vocab.nerc.ac.uk/collection/B75/current/ORG00142/)
    },
    "DEPLOYMENT_TIME":{
        "long_name": "date of deployment",
        "standard_name": "time",
        "calendar": "gregorian",
        "units": "seconds since 1970-01-01T00:00:00Z",
    },
    "DEPLOYMENT_LATITUDE":{
        "long_name": "latitude of deployment",
        "standard_name": "latitude",
        "units": "degrees_north",
    },
    "DEPLOYMENT_LONGITUDE":{
        "long_name": "longitude of deployment",
        "standard_name": "longitude",
        "units": "degrees_east",
    },
    "GLIDER_FIRMWARE_VERSION": {
        "long_name": "version of the internal glider firmware",
    },
    "LANDSTATION_VERSION":{
        "long_name": "version of the server onshore", # dockserver v3.42"        
    },
    "BATTERY_TYPE":{
        "long_name": "type of the battery", # lithium or lithium primary
        "battery_type_vocabulary": "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/battery_type.md",
    },
    "BATTERY_PACK":{
        "long_name": "battery packaging", # "2X24 12V battery"
    },
    "TELECOM_TYPE": { # iridium
        "long_name": "types of telecommunication systems used by the glider, multiple telecom type are separated by a comma", # iridium or iridium short burst data
        "telecom_type_vocabulary": "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/telecom_type.md"
    },
    "TRACKING_SYSTEM": {# gps
        "long_name": "type of tracking systems used by the glider, multiple tracking system are separated by a comma",
        "tracking_system_vocabulary": "https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/tracking_system.md"
    },
    "SENSOR_type_serialnumber": {
        "long_name": "RBR Legato 3 CTD",
        "sensor_type_vocabulary": "https://vocab.nerc.ac.uk/collection/L05/current/130",
        "sensor_model": "RBR Legato3 CTD",
        "sensor_model_vocabulary": "https://vocab.nerc.ac.uk/collection/L22/current/TOOL1745",
        "sensor_maker": "RBR",
        "sensor_maker_vocabulary": "https://vocab.nerc.ac.uk/collection/L35/current/MAN0049",
        "sensor_serial_number": "12345",
        "sensor_calibration_date": "2021-01-01",
    },



}
