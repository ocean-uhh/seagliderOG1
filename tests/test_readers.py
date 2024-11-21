from seagliderOG1 import readers


def test_demo_datasets():
    for remote_ds_name in readers.data_source_og.registry.keys():
        ds = readers.load_sample_dataset(dataset_name=remote_ds_name)