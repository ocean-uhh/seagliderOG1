import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import numpy as np
import xarray as xr
import gsw
from datetime import datetime
import os
from seagliderOG1 import vocabularies
from seagliderOG1 import readers, writers, utilities, tools
from seagliderOG1 import convertOG1


def test_process_dataset():
    
    ds1 = readers.load_sample_dataset()

    # test split_ds
    split_ds = tools.split_by_unique_dims(ds1)

    key_dims = list(split_ds.keys())
    key_dims.sort()
    assert key_dims == [(), ('gc_event',), ('gc_state',), ('gps_info',), ('sg_data_point',)]

    ds = split_ds[('sg_data_point',)]
    gps_info = split_ds[('gps_info',)]

    sg_cal, dc_log, dc_other = convertOG1.extract_variables(split_ds[()])
    tmp = dc_log.log_GPS.values.tobytes().decode('utf-8')

    assert sg_cal['mass'].values > 70 and sg_cal['mass'].values < 80
    assert tmp == '$GPS,060910,142637,1831.076,-6558.818,31,1.1,34,-12.7'

    # Check initial variables are reformatted
    dsa = convertOG1.standardise_OG10(ds)
    varlist = list(dsa.data_vars)
    coordlist = list(dsa.coords)
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

    ds_new = convertOG1.add_gps_info_to_dataset(dsa, gps_info)
    assert 'LATITUDE_GPS' in list(ds_new.variables)
    assert 'LONGITUDE_GPS' in list(ds_new.variables)

    ds_new = tools.assign_profile_number(ds_new, ds1)
    assert 'PROFILE_NUMBER' in list(ds_new.variables)
    assert ds_new['PROFILE_NUMBER'].values.max() == 2*ds1.attrs['dive_number']

    

