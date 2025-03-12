import xarray as xr
import os
from bs4 import BeautifulSoup
import requests
import numpy as np
from importlib_resources import files
import pooch
import re


def parse_basestn(ds1_base):
    basestn_varlist = list(ds1_base.variables)
    sensor_presence = sensor_present(basestn_varlist)

    sens_singles, sens_attrs, sens_vars = extract_sensor(ds1_base,sensor_presence)

    sens_calcomm = cal_comm(ds1_base, sensor_presence)

    sensors = {}
    for key, value in sensor_presence.items():
        if value:
            sensor_data = {
                'sensor_name': key,
                'sensor_presence': value,
                'sensor_singletons': sens_singles[key],
                'sensor_attributes': sens_attrs[key],
                'sensor_variables': sens_vars[key],
                'sensor_calcomm': sens_calcomm[key]
            }
        else:
            sensor_data = {
                'sensor_name': key,
                'sensor_presence': value,
            }        

        sensors[key] = sensor_data

    if 'log_COMPASS_USE' in ds1_base.variables and ds1_base['log_COMPASS_USE'].values.item() != 0:
        print('has compass')
        sensors['MAGNETOMETER']['sensor_presence'] = True
    else:
        sensors['MAGNETOMETER']['sensor_presence'] = False
    if 'log_RAFOS_DEVICE' in ds1_base.variables and ds1_base['log_RAFOS_DEVICE'].values.item() != -1:
        print('has rafos')
        sensors['RAFOS']['sensor_presence'] = True
    else:
        sensors['RAFOS']['sensor_presence'] = False
            
    basestn_attrlist = ds1_base.attrs
    sel_attr = check_basestn_attrs(basestn_attrlist)

    return sensors, sel_attr


def sensor_present(basestn_varlist):
    """
    Check the presence of sensors in the provided variable list.
    This function checks if any of the keywords associated with each sensor 
    in the sensor dictionary are present in the provided variable list. 
    It returns a dictionary indicating the presence of each sensor.
    Args:
        varlist (list): A list of variables to check for sensor presence.
    Returns:
        dict: A dictionary with sensor names as keys and boolean values 
              indicating the presence (True) or absence (False) of each sensor.
    """

    sensor_presence = {key: False for key in sensor_dict.keys()}
    for key in sensor_presence.keys():
        keywords = sensor_dict[key]
        for keyword in keywords:
            if any(keyword in item for item in basestn_varlist):
                sensor_presence[key] = True
                break
    return sensor_presence

def extract_sensor(ds1_base, sensor_presence=None):
    """
    Extracts sensor-related information from a dataset.
    Parameters:
    ds1_base (xarray.Dataset): The base dataset from which to extract sensor information.
    sensor_presence (dict, optional): A dictionary indicating the presence of sensors. If None, the function will determine sensor presence based on the dataset variables.
    Returns:
    tuple: A tuple containing two dictionaries:
        - sensor_singletons (dict): A dictionary where keys are sensor names and values are dictionaries of sensor-related variables and their values.
        - sensor_attributes (dict): A dictionary where keys are sensor names and values are dictionaries of sensor-related variables and their attributes.
    """

    basestn_varlist = list(ds1_base.variables)
    if sensor_presence is None:
        sensor_presence = sensor_present(basestn_varlist)
    # Collect together variables that give evidence for the sensor
    sensor_singletons = {key: {} for key in sensor_presence.keys()}
    sensor_attributes = {key: {} for key in sensor_presence.keys()}
    sensor_variables = {key: {} for key in sensor_presence.keys()}
    for key in sensor_presence.keys():
        keywords = sensor_dict[key]
        # Cycle through the possible strings in sensor_dict
        for keyword in keywords:
            # Cycle through all variables in ds1_base
            for item in basestn_varlist:
                # If there is a partial string match
                if keyword in item:
                    val1 = ds1_base[item]
                    dims1 = val1.dims
                    # If it's a singleton
                    if len(dims1)==0:
                        if type(val1.values.item()) is float:
                            val1 = val1.values.item()
                            sensor_singletons[key][item] = val1
                        elif type(val1.values.item()) is int:
                            val1 = val1.values.item()
                            sensor_singletons[key][item] = val1
                        else:
                            val1 = val1.values.item().decode('utf-8')
                            if hasattr(ds1_base[item], 'attrs'):
                                val1 = f"variable with attributes"
                                sensor_attributes[key][item] = f"{ds1_base[item].attrs}"
                            else:
                                sensor_singletons[key][item] = val1
                    else:
                        val1 = f"DataArray of length({dims1[0]})"
                        sensor_variables[key][item] = f"DataArray({dims1[0]})"
    return sensor_singletons, sensor_attributes, sensor_variables

# These were mined manually from files - variable names that may be present in basestation files
datavar_keywords = ['aanderaa4330', 'sbe43', 'wlbb2f', 'wlbb2fl','wlbbfl2', 'aa4330', 'sbect']
datavar_suffix = ['_qc', '_raw', '_raw_qc', '_gsm']
datavar_derived = ['absolute_salinity','conservative_temperature', 'density', 'density_insitu', 'salinity',
                   'sigma_t','sigma_theta','sound_velocity','theta']

# in basestation attributes as `instrument`
sensor_other = ['aa4330', 'sbe43', 'sbe41', 'wlbb2f', 'wlbb2fl', 'wlbbfl2']

# variable names associated with a particular sensor
sensor_dict = {
    'CTD': ['sbe41','sbect','sg_cal_t_g','sg_cal_t_h','sg_cal_t_i','sg_cal_t_j','sg_cal_c_g','sg_cal_c_h','sg_cal_c_i','sg_cal_c_j','SEABIRD_T_G','SEABIRD_T_H','SEABIRD_T_I','SEABIRD_T_J','SEABIRD_C_G','SEABIRD_C_H','SEABIRD_C_I','SEABIRD_C_J','condFreq','tempFreq'],    
    'DISSOLVED_GAS': ['sbe43', 'SBE43','aanderaa4330', 'aa4330','calibcomm_optode','calibcomm_oxygen','Soc','Tcor','Pcor','Foffset','sg_cal_A','sg_cal_B','sg_cal_C','sg_cal_D','sg_cal_E', 'aa4330_tcphase','sg_cal_optode_ConcCoef0','optode'],

    'FLUOROMETER': ['wlbb2f','wlbb2fl','wlbbfl2','WETLabsCalData','calibcomm_wetlabs'],
    'ALTIMETER': ['log_ALTIM','altim'],
    'MAGNETOMETER': ['magnetic_variation','log_COMPASS','magnetometer','eng_mag'],
    'RAFOS': ['log_RAFOS']
}

# variable names containing the calibration information
sensor_calstr = {
    'CTD': ['calibcomm'],
    'DISSOLVED_GAS': ['calibcomm_oxygen', 'calibcomm_optode'],
    'FLUOROMETER': ['calibcomm_wetlabs'],
    'ALTIMETER': ['None'],
    'MAGNETOMETER': ['None'],
    'RAFOS': ['None']
}

def cal_comm(ds1_base,sensor_presence=None):

    basestn_varlist = list(ds1_base.variables)
    if sensor_presence is None:
        sensor_presence = sensor_present(basestn_varlist)

    sens_calcomm = {key: {} for key in sensor_presence.keys()}
    for key in sensor_presence.keys():
        calinfostr = 'Unknown'
        if sensor_presence[key]:
            calstr_names = sensor_calstr[key]
            for var in calstr_names:
                var = 'sg_cal_' + var
                if var in basestn_varlist:
                    calinfostr = f"{ds1_base[var].values.item().decode('utf-8')}"
        
        sens_calcomm[key] = calinfostr
    return sens_calcomm

sgcal_keywords = ['WETLabsCalData_Chlorophyll', 'WETLabsCalData_Scatter_470', 'WETLabsCalData_Scatter_700', 
                  'optode', 't_', 'wlbbfl2_sig460nm', 'wlbbfl2_sig697nm', 'wlbbfl2_sig700nm', 'o_', 'c_', 
                  'A', 'B', 'Boc', 'C', 'E', 'Foffset', 'Pcor', 'Soc', 'Tcor']
cal_strings = ['calibcomm','calibcomm_optode','calibcomm_oxygen','calibcomm_wetlabs']

def check_basestn_attrs(basestn_attrlist):
    """
    Checks and selects attributes from the given list based on predefined basic attributes.
    Args:
        basestn_attrlist (list): A list of attributes to be checked and selected.
    Returns:
        dict: A dictionary containing the selected attributes. The keys are the basic attribute names,
              and the values are dictionaries with the selected keywords and their corresponding values.
    Example:
        basestn_basic_attrs = {
            'attr1': ['keyword1', 'keyword2'],
            'attr2': ['keyword3', 'keyword4']
        }
        basestn_attrlist = {
            'keyword1': 'value1',
            'keyword3': 'value3'
        }
        selected_attr = check_basestn_attrs(basestn_attrlist)
        # selected_attr will be:
        # {
        #     'attr1': {'keyword1': 'value1'},
        #     'attr2': {'keyword3': 'value3'}
        # }
    """
    selected_attr = {key: {} for key in basestn_basic_attrs.keys()}
    for key in basestn_basic_attrs.keys():
        keywords = basestn_basic_attrs[key]
        for keyword in keywords:
            if any(keyword in item for item in basestn_attrlist):
                value1 = basestn_attrlist[keyword]
                if not isinstance(value1, str):
                    value1 = str(value1)
                selected_attr[key][keyword] = value1
                #print(f"{keyword}: {value1}")
    return selected_attr

basestn_basic_attrs = {
    'basestn_vehicle': ['platform_id','platform','source','glider','id','mission'],
    'basestn_project': ['title','project','summary','instrument'],
    'basestn_software': ['base_station_version','base_station_micro_version','seaglider_software_version','file_version','processing_level','quality_control_version','nodc_template_version',    'standard_name_vocabulary',
    'Conventions',    'Metadata_Conventions','featureType','cdm_data_type'],
    'basestn_timing': ['start_time','time_coverage_start','date_created','date_modified','date_issued','uuid'],
    'creator': ['creator_name','creator_email','creator_url','contributor_name','contributor_role','institution','publisher_name','publisher_email','publisher_url','naming_authority']
}
# Work with basestation files only
basestn_ordered_attributes = [
    'platform_id',
    'platform',
    'source',
    'glider',
    'id',
    'mission',
    'base_station_version',
    'base_station_micro_version',
    'seaglider_software_version',
    'nodc_template_version',
    'file_version',
    'processing_level',
    'quality_control_version',
    'standard_name_vocabulary',
    'Conventions',
    'Metadata_Conventions',
    'dive_number',
    'start_time',
    'time_coverage_start',
    'time_coverage_end',
    'date_created',
    'date_modified',
    'date_issued',
    'title',
    'project',
    'summary',
    'instrument',
    'creator_email',
    'creator_name',
    'creator_url',
    'contributor_name',
    'contributor_role',
    'institution',
    'publisher_name',
    'publisher_email',
    'publisher_url',
    'naming_authority',
    'uuid',
    'sea_name',
    'geospatial_lat_max',
    'geospatial_lat_min',
    'geospatial_lat_units',
    'geospatial_lon_max',
    'geospatial_lon_min',
    'geospatial_lon_units',
    'geospatial_vertical_min',
    'geospatial_vertical_max',
    'geospatial_vertical_positive',
    'geospatial_lat_resolution',
    'geospatial_lon_resolution',
    'geospatial_vertical_units',
    'geospatial_vertical_resolution',
    'time_coverage_resolution',
    'references',
    'keywords',
    'keywords_vocabulary',
    'featureType',
    'cdm_data_type',
    'license',
    'history',
    'comment',
    'references',
    'acknowledgment',
    'disclaimer',
]


basestn_varlist = ['aanderaa4330_dissolved_oxygen',
    'aanderaa4330_dissolved_oxygen_qc',
    'aanderaa4330_instrument_dissolved_oxygen',
    'aanderaa4330_results_time',
    'absolute_salinity',
    'buoyancy',
    'conductivity',
    'conductivity_qc',
    'conductivity_raw',
    'conductivity_raw_qc',
    'conservative_temperature',
    'ctd_depth',
    'ctd_pressure',
    'ctd_time',
    'density',
    'density_insitu',
    'depth',
    'dissolved_oxygen_sat',
    'east_displacement',
    'east_displacement_gsm',
    'eng_GC_phase',
    'eng_aa4330_AirSat',
    'eng_aa4330_CalPhase',
    'eng_aa4330_O2',
    'eng_aa4330_TCPhase',
    'eng_aa4330_Temp',
    'eng_condFreq',
    'eng_depth',
    'eng_elaps_t',
    'eng_elaps_t_0000',
    'eng_head',
    'eng_pitchAng',
    'eng_pitchCtl',
    'eng_press_counts',
    'eng_pressure',
    'eng_rec',
    'eng_rollAng',
    'eng_rollCtl',
    'eng_sbe43_O2Freq',
    'eng_sbect_condFreq',
    'eng_sbect_tempFreq',
    'eng_tempFreq',
    'eng_vbdCC',
    'eng_wlbb2f_VFtemp',
    'eng_wlbb2f_blueCount',
    'eng_wlbb2f_blueRef',
    'eng_wlbb2f_fluorCount',
    'eng_wlbb2f_redCount',
    'eng_wlbb2f_redRef',
    'eng_wlbb2fl_BB1ref',
    'eng_wlbb2fl_BB1sig',
    'eng_wlbb2fl_BB2ref',
    'eng_wlbb2fl_BB2sig',
    'eng_wlbb2fl_FL1ref',
    'eng_wlbb2fl_FL1sig',
    'eng_wlbb2fl_temp',
    'eng_wlbbfl2_sig460nm',
    'eng_wlbbfl2_sig695nm',
    'eng_wlbbfl2_sig700nm',
    'eng_wlbbfl2_temp',
    'glide_angle',
    'glide_angle_gsm',
    'horz_speed',
    'horz_speed_gsm',
    'latitude',
    'latitude_gsm',
    'longitude',
    'longitude_gsm',
    'north_displacement',
    'north_displacement_gsm',
    'pressure',
    'salinity',
    'salinity_qc',
    'salinity_raw',
    'salinity_raw_qc',
    'sbe43_dissolved_oxygen',
    'sbe43_dissolved_oxygen_qc',
    'sbe43_results_time',
    'sigma_t',
    'sigma_theta',
    'sound_velocity',
    'speed',
    'speed_gsm',
    'speed_qc',
    'temperature',
    'temperature_qc',
    'temperature_raw',
    'temperature_raw_qc',
    'theta',
    'time',
    'vert_speed',
    'vert_speed_gsm',
    'wlbbfl2_results_time',
    'wlbbfl2_sig460nm_adjusted',
    'wlbbfl2_sig695nm_adjusted',
    'wlbbfl2_sig700nm_adjusted']


basestn_sg_cal = ['A',
    'B',
    'Boc',
    'C',
    'E',
    'Foffset',
    'Pcor',
    'QC_cond_spike_depth',
    'QC_temp_spike_depth',
    'Soc',
    'Tcor',
    'WETLabsCalData_Chlorophyll_calTemperature',
    'WETLabsCalData_Chlorophyll_darkCounts',
    'WETLabsCalData_Chlorophyll_maxOutput',
    'WETLabsCalData_Chlorophyll_resolution',
    'WETLabsCalData_Chlorophyll_scaleFactor',
    'WETLabsCalData_Scatter_470_darkCounts',
    'WETLabsCalData_Scatter_470_resolution',
    'WETLabsCalData_Scatter_470_scaleFactor',
    'WETLabsCalData_Scatter_470_wavelength',
    'WETLabsCalData_Scatter_700_darkCounts',
    'WETLabsCalData_Scatter_700_resolution',
    'WETLabsCalData_Scatter_700_scaleFactor',
    'WETLabsCalData_Scatter_700_wavelength',
    'a',
    'abs_compress',
    'b',
    'c',
    'c_g',
    'c_h',
    'c_i',
    'c_j',
    'calibcomm',
    'calibcomm_optode',
    'calibcomm_oxygen',
    'calibcomm_wetlabs',
    'comm_oxy_type',
    'cond_bias',
    'cpcor',
    'ctcor',
    'hd_a',
    'hd_b',
    'hd_c',
    'hd_s',
    'id_str',
    'mass',
    'mass_comp',
    'mission_title',
    'o_a',
    'o_b',
    'o_c',
    'o_e',
    'optode_ConcCoef0',
    'optode_ConcCoef1',
    'optode_FoilCoefA0',
    'optode_FoilCoefA1',
    'optode_FoilCoefA10',
    'optode_FoilCoefA11',
    'optode_FoilCoefA12',
    'optode_FoilCoefA13',
    'optode_FoilCoefA2',
    'optode_FoilCoefA3',
    'optode_FoilCoefA4',
    'optode_FoilCoefA5',
    'optode_FoilCoefA6',
    'optode_FoilCoefA7',
    'optode_FoilCoefA8',
    'optode_FoilCoefA9',
    'optode_FoilCoefB0',
    'optode_FoilCoefB1',
    'optode_FoilCoefB10',
    'optode_FoilCoefB11',
    'optode_FoilCoefB12',
    'optode_FoilCoefB13',
    'optode_FoilCoefB2',
    'optode_FoilCoefB3',
    'optode_FoilCoefB4',
    'optode_FoilCoefB5',
    'optode_FoilCoefB6',
    'optode_FoilCoefB7',
    'optode_FoilCoefB8',
    'optode_FoilCoefB9',
    'optode_PhaseCoef0',
    'optode_PhaseCoef1',
    'optode_PhaseCoef2',
    'optode_PhaseCoef3',
    'optode_SVUCoef0',
    'optode_SVUCoef1',
    'optode_SVUCoef2',
    'optode_SVUCoef3',
    'optode_SVUCoef4',
    'optode_SVUCoef5',
    'optode_SVUCoef6',
    'optode_SVU_enabled',
    'optode_TempCoef0',
    'optode_TempCoef1',
    'optode_TempCoef2',
    'optode_TempCoef3',
    'optode_TempCoef4',
    'optode_TempCoef5',
    'optode_st_calphase',
    'optode_st_slp',
    'optode_st_temp',
    'pitch_max_cnts',
    'pitch_min_cnts',
    'pitchbias',
    'pump_power_intercept',
    'pump_power_slope',
    'pump_rate_intercept',
    'pump_rate_slope',
    'rho0',
    'roll_max_cnts',
    'roll_min_cnts',
    'sbe_cond_freq_max',
    'sbe_cond_freq_min',
    'sbe_temp_freq_max',
    'sbe_temp_freq_min',
    'sg_configuration',
    't_g',
    't_h',
    't_i',
    't_j',
    'temp_ref',
    'therm_expan',
    'vbd_cnts_per_cc',
    'vbd_max_cnts',
    'vbd_min_cnts',
    'volmax',
    'wlbbfl2_sig460nm_dark_counts',
    'wlbbfl2_sig460nm_max_counts',
    'wlbbfl2_sig460nm_resolution_counts',
    'wlbbfl2_sig460nm_scale_factor',
    'wlbbfl2_sig695nm_dark_counts',
    'wlbbfl2_sig695nm_max_counts',
    'wlbbfl2_sig695nm_resolution_counts',
    'wlbbfl2_sig695nm_scale_factor',
    'wlbbfl2_sig700nm_dark_counts',
    'wlbbfl2_sig700nm_max_counts',
    'wlbbfl2_sig700nm_resolution_counts',
    'wlbbfl2_sig700nm_scale_factor']

basestn_other_var = ['CTD_qc',
    'GPS1_qc',
    'GPS2_qc',
    'GPSE_qc',
    'SBE43_qc',
    'aa4330',
    'aanderaa4330_qc',
    'avg_latitude',
    'depth_avg_curr_east',
    'depth_avg_curr_east_gsm',
    'depth_avg_curr_error',
    'depth_avg_curr_north',
    'depth_avg_curr_north_gsm',
    'depth_avg_curr_qc',
    'directives',
    'flight_avg_speed_east',
    'flight_avg_speed_east_gsm',
    'flight_avg_speed_north',
    'flight_avg_speed_north_gsm',
    'glider',
    'hdm_qc',
    'latlong_qc',
    'magnetic_variation',
    'magnetometer',
    'processing_error',
    'reviewed',
    'sbe41',
    'sbe43',
    'start_of_climb_time',
    'surface_curr_east',
    'surface_curr_error',
    'surface_curr_north',
    'surface_curr_qc',
    'wlbb2f',
    'wlbb2fl',
    'wlbbfl2']

basestn_log_events = ['log_10V_AH',
    'log_24V_AH',
    'log_AD7714Ch0Gain',
    'log_AH0_10V',
    'log_AH0_24V',
    'log_ALTIM_BOTTOM_PING_RANGE',
    'log_ALTIM_BOTTOM_TURN_MARGIN',
    'log_ALTIM_FREQUENCY',
    'log_ALTIM_PING_DELTA',
    'log_ALTIM_PING_DEPTH',
    'log_ALTIM_PULSE',
    'log_ALTIM_SENSITIVITY',
    'log_ALTIM_TOP_MIN_OBSTACLE',
    'log_ALTIM_TOP_PING',
    'log_ALTIM_TOP_PING_RANGE',
    'log_ALTIM_TOP_TURN_MARGIN',
    'log_APOGEE_PITCH',
    'log_CALL_NDIVES',
    'log_CALL_TRIES',
    'log_CALL_WAIT',
    'log_CAPMAXSIZE',
    'log_CAPUPLOAD',
    'log_CAP_FILE_SIZE',
    'log_CF8_MAXERRORS',
    'log_CFSIZE',
    'log_COMM_SEQ',
    'log_COMPASS2_DEVICE',
    'log_COMPASS_DEVICE',
    'log_COMPASS_USE',
    'log_COURSE_BIAS',
    'log_CURRENT',
    'log_C_PITCH',
    'log_C_ROLL_CLIMB',
    'log_C_ROLL_DIVE',
    'log_C_VBD',
    'log_DATA_FILE_SIZE',
    'log_DBDW',
    'log_DEEPGLIDER',
    'log_DEEPGLIDERMB',
    'log_DEVICE1',
    'log_DEVICE2',
    'log_DEVICE3',
    'log_DEVICE4',
    'log_DEVICE5',
    'log_DEVICE6',
    'log_DEVICES',
    'log_DEVICE_MAMPS',
    'log_DEVICE_SECS',
    'log_DIVE',
    'log_D_ABORT',
    'log_D_BOOST',
    'log_D_CALL',
    'log_D_FINISH',
    'log_D_FLARE',
    'log_D_GRID',
    'log_D_NO_BLEED',
    'log_D_OFFGRID',
    'log_D_PITCH',
    'log_D_SAFE',
    'log_D_SURF',
    'log_D_TGT',
    'log_ERRORS',
    'log_ESCAPE_HEADING',
    'log_ESCAPE_HEADING_DELTA',
    'log_ES_PROFILE',
    'log_ES_RECORDABOVE',
    'log_ES_STARTS',
    'log_ES_UPLOADMAX',
    'log_ES_XMITPROFILE',
    'log_FERRY_MAX',
    'log_FG_AHR_10V',
    'log_FG_AHR_10Vo',
    'log_FG_AHR_24V',
    'log_FG_AHR_24Vo',
    'log_FILEMGR',
    'log_FIX_MISSING_TIMEOUT',
    'log_GLIDE_SLOPE',
    'log_GPS',
    'log_GPS1',
    'log_GPS2',
    'log_GPS_DEVICE',
    'log_HD_A',
    'log_HD_B',
    'log_HD_C',
    'log_HEADING',
    'log_HEAD_ERRBAND',
    'log_HEAPDBG',
    'log_HUMID',
    'log_ICE_FREEZE_MARGIN',
    'log_ID',
    'log_INTERNAL_PRESSURE',
    'log_INT_PRESSURE_SLOPE',
    'log_INT_PRESSURE_YINT',
    'log_IRIDIUM_FIX',
    'log_KALMAN_CONTROL',
    'log_KALMAN_USE',
    'log_KALMAN_X',
    'log_KALMAN_Y',
    'log_KERMIT',
    'log_LOGGERDEVICE1',
    'log_LOGGERDEVICE2',
    'log_LOGGERDEVICE3',
    'log_LOGGERDEVICE4',
    'log_LOGGERS',
    'log_MASS',
    'log_MASS_COMP',
    'log_MAXI_10V',
    'log_MAXI_24V',
    'log_MAX_BUOY',
    'log_MEM',
    'log_MHEAD_RNG_PITCHd_Wd',
    'log_MINV_10V',
    'log_MINV_24V',
    'log_MISSION',
    'log_MOTHERBOARD',
    'log_NAV_MODE',
    'log_NOCOMM_ACTION',
    'log_N_DIVES',
    'log_N_FILEKB',
    'log_N_GPS',
    'log_N_NOCOMM',
    'log_N_NOSURFACE',
    'log_PHONE_DEVICE',
    'log_PHONE_SUPPLY',
    'log_PITCH_ADJ_DBAND',
    'log_PITCH_ADJ_GAIN',
    'log_PITCH_AD_RATE',
    'log_PITCH_CNV',
    'log_PITCH_DBAND',
    'log_PITCH_GAIN',
    'log_PITCH_MAX',
    'log_PITCH_MAXERRORS',
    'log_PITCH_MIN',
    'log_PITCH_TIMEOUT',
    'log_PITCH_VBD_SHIFT',
    'log_PITCH_W_DBAND',
    'log_PITCH_W_GAIN',
    'log_PRESSURE_SLOPE',
    'log_PRESSURE_YINT',
    'log_PROTOCOL',
    'log_P_OVSHOOT',
    'log_P_OVSHOOT_WITHG',
    'log_RAFOS_CORR_THRESH',
    'log_RAFOS_DEVICE',
    'log_RAFOS_HIT_WINDOW',
    'log_RAFOS_MMODEM',
    'log_RAFOS_PEAK_OFFSET',
    'log_RELAUNCH',
    'log_RHO',
    'log_ROLL_ADJ_DBAND',
    'log_ROLL_ADJ_GAIN',
    'log_ROLL_AD_RATE',
    'log_ROLL_CNV',
    'log_ROLL_DEG',
    'log_ROLL_MAX',
    'log_ROLL_MAXERRORS',
    'log_ROLL_MIN',
    'log_ROLL_TIMEOUT',
    'log_R_PORT_OVSHOOT',
    'log_R_STBD_OVSHOOT',
    'log_SEABIRD_C_G',
    'log_SEABIRD_C_H',
    'log_SEABIRD_C_I',
    'log_SEABIRD_C_J',
    'log_SEABIRD_C_Z',
    'log_SEABIRD_T_G',
    'log_SEABIRD_T_H',
    'log_SEABIRD_T_I',
    'log_SEABIRD_T_J',
    'log_SENSORS',
    'log_SENSOR_MAMPS',
    'log_SENSOR_SECS',
    'log_SIM_PITCH',
    'log_SIM_W',
    'log_SMARTDEVICE1',
    'log_SMARTDEVICE2',
    'log_SMARTS',
    'log_SM_CC',
    'log_SM_CCo',
    'log_SM_GC',
    'log_SPEED_FACTOR',
    'log_SPEED_LIMITS',
    'log_STOP_T',
    'log_STROBE',
    'log_SURFACE_URGENCY',
    'log_SURFACE_URGENCY_FORCE',
    'log_SURFACE_URGENCY_TRY',
    'log_TCM_PITCH_OFFSET',
    'log_TCM_ROLL_OFFSET',
    'log_TCM_TEMP',
    'log_TGT_AUTO_DEFAULT',
    'log_TGT_DEFAULT_LAT',
    'log_TGT_DEFAULT_LON',
    'log_TGT_LATLONG',
    'log_TGT_NAME',
    'log_TGT_RADIUS',
    'log_TT8_MAMPS',
    'log_T_ABORT',
    'log_T_BOOST',
    'log_T_DIVE',
    'log_T_EPIRB',
    'log_T_GPS',
    'log_T_GPS_ALMANAC',
    'log_T_GPS_CHARGE',
    'log_T_LOITER',
    'log_T_MISSION',
    'log_T_NO_W',
    'log_T_RSLEEP',
    'log_T_SLOITER',
    'log_T_TURN',
    'log_T_TURN_SAMPINT',
    'log_T_WATCHDOG',
    'log_UNCOM_BLEED',
    'log_UPLOAD_DIVES_MAX',
    'log_USE_BATHY',
    'log_USE_ICE',
    'log_VBD_BLEED_AD_RATE',
    'log_VBD_CNV',
    'log_VBD_DBAND',
    'log_VBD_LP_IGNORE',
    'log_VBD_MAX',
    'log_VBD_MAXERRORS',
    'log_VBD_MIN',
    'log_VBD_PUMP_AD_RATE_APOGEE',
    'log_VBD_PUMP_AD_RATE_SURFACE',
    'log_VBD_TIMEOUT',
    'log_W_ADJ_DBAND',
    'log_XPDR_DEVICE',
    'log_XPDR_INHIBIT',
    'log_XPDR_PINGS',
    'log_XPDR_VALID',
    'log__CALLS',
    'log__SM_ANGLEo',
    'log__SM_DEPTHo',
    'log__XMS_NAKs',
    'log__XMS_TOUTs']

