import pooch
import xarray as xr

server = "https://www.dropbox.com/scl/fo/dhinr4hvpk05zcecqyz2x/ADTqIuEpWHCxeZDspCiTN68?rlkey=bt9qheandzbucca5zhf5v9j7a&dl=0"
data_source_og = pooch.create(
    path=pooch.os_cache("seagliderOG1"),
    base_url=server,
    registry={
        "p0150500_20050213.nc": "sha256:06bb407e6aff82eccdcd2503910aa36a65942f26",
        "p0150501_20050213.nc": "sha256:7774a73c3e7a1c3900875055d6ef26518de406df",
        "p0150502_20050214.nc": "sha256:7027467b58dae44c6188fa7c1896a29756b37d17",
        "p0150503_20050214.nc": "sha256:2c56cf7619f4b9edc054cc318907823c33eddaf6",
        "p0150504_20050215.nc": "sha256:a79f4a507038efd0c485cf3dd86bf69c475af9f6"
    },
)


def load_sample_dataset(dataset_name="p0150500_20050213.nc"):
    if dataset_name in data_source_og.registry.keys():
        file_path = data_source_og.fetch(dataset_name)
        return xr.open_dataset(file_path)
    else:
        msg = f"Requested sample dataset {dataset_name} not known"
        raise ValueError(msg)
