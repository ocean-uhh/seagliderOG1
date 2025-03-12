import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import readers, tools
from seagliderOG1 import convertOG1


def test_process_dataset():
    
    ds1_base = readers.load_sample_dataset()

    # Split the dataset by unique dimensions
    split_ds = tools.split_by_unique_dims(ds1_base)

    key_dims = list(split_ds.keys())
    key_dims.sort()
    # For Rob's Whittard canyon, could include 'magnetometer_data_point'
    assert ('gc_event',) in key_dims
    assert ('sg_data_point',) in key_dims
    assert ('gps_info',) in key_dims

    ds_sgdata = split_ds[('sg_data_point',)]
    ds_gps = split_ds[('gps_info',)]
    ds_sgcal, ds_log, ds_other = convertOG1.extract_variables(split_ds[()])
    assert ds_sgcal['mass'].values > 50 and ds_sgcal['mass'].values < 100
    tmp = ds_log.log_GPS.values.tobytes().decode('utf-8')
    assert tmp[0:4] == '$GPS'

    # Check initial variables are reformatted
    ds_new = convertOG1.standardise_OG10(ds_sgdata)
    varlist = list(ds_new.variables)
    coordlist = list(ds_new.coords)
    combined_list = varlist + coordlist
    combined_list.sort()
    og1_varlist = ['TIME',
                'LATITUDE',
                'LONGITUDE',
                'TEMP',
                'DEPTH',
    ]
    for var in og1_varlist:
        assert var in combined_list

    ds_new = convertOG1.add_gps_info_to_dataset(ds_new, ds_gps)
    assert 'LATITUDE_GPS' in list(ds_new.variables)
    assert 'LONGITUDE_GPS' in list(ds_new.variables)

    ds_new = tools.assign_profile_number(ds_new, ds1_base)
    assert 'PROFILE_NUMBER' in list(ds_new.variables)
    assert ds_new['PROFILE_NUMBER'].values.max() == 2*ds1_base.attrs['dive_number']

    ds_new = tools.calc_Z(ds_new)
    meanZ = ds_new['DEPTH_Z'].mean().item()
    meanZpos = ds_new['DEPTH'].mean().item()
    assert abs(meanZ + meanZpos) < 10 

    ds_sensor = tools.gather_sensor_info(ds_new, ds_other, ds_sgcal)
    ds_new = tools.add_sensor_to_dataset(ds_new, ds_sensor, ds_sgcal)

def test_convert_to_OG1():
    ds1 = readers.load_sample_dataset()

    ds_og1, varlist = convertOG1.convert_to_OG1(ds1)
    assert 'LATITUDE' in list(ds_og1.variables)
    assert 'PLATFORM_SERIAL_NUMBER' in list(ds_og1.variables)
    assert ds_og1.attrs['geospatial_lat_max'] > ds_og1.attrs['geospatial_lat_min']
    