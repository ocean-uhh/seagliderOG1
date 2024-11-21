import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import readers


def test_demo_datasets():
#    for remote_ds_name in readers.data_source_og.registry.keys():
    ds = readers.load_sample_dataset(dataset_name="p0150500_20050213.nc")