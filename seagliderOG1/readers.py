import xarray as xr
import os
from bs4 import BeautifulSoup
import requests
import numpy as np
from importlib_resources import files
import pooch
import re
# readers.py: Will only read files.  Not manipulate them.

# Use pooch for sample files only.
# For the full dataset, just use BeautifulSoup / requests
server = "https://www.ncei.noaa.gov/data/oceans/glider/seaglider/uw/033/20100903/"
data_source_og = pooch.create(
    path=pooch.os_cache("seagliderOG1"),
    base_url=server,
    registry={
        "p0330001_20100903.nc": "1ee726a4890b5567653fd53501da8887d947946ad63a17df4e5efd2e578fb464",
        "p0330002_20100903.nc": "1c0d6f46904063dbb1e74196bc30bdaf6163e7fbd4cc31c6087eb295688a2cc1",
        "p0330003_20100903.nc": "779bdfb4237b17b1de8ccb5d67ef37ea28b595d918b3a034606e8612615058c3",
        "p0330004_20100904.nc": "f981d482e04bbe5085e2f93d686eedf3a30ca125bd94696648d04b2e37fa2489",
        "p0330005_20100904.nc": "46e921c06b407a458dd4f788b9887ea4b6a51376021190c89e0402b25b0c8f3f",
        "p0330006_20100904.nc": "3ed79ee0757b573f32c7d72ff818b82d9810ebbd640d8a9b0f6829ab1da3b972",
        "p0330007_20100905.nc": "29d83c65ef4649bbc9193bb25eab7a137f92da04912eae21d9fc9860e827281d",
        "p0330008_20100905.nc": "66fa25efb8717275e84f326f3c7bd02251db7763758683c60afc4fb2e3cbb170",
        "p0330009_20100905.nc": "ee5ce7881c74de9d765ae46c6baed4745b0620dd57f7cd7f8b9f1c7f46570836",
        "p0330010_20100905.nc": "fad0d9bb08fc874ffacf8ed1ae25522d48ff9ff8c8f1db82bcaf4e613d6c46e3",
        "p0330011_20100905.nc": "3b3ae89c653651e10b7a8058536d276aae9958e7d4236a4164e05707ef5a8660",
        "p0330012_20100905.nc": "b6318d496ccddd14ede295613a2b4854f0d228c8db996737b5187e73ed226d2a",
        "p0330013_20100906.nc": "efeb37be650368470a6fd7a9cf0cc0b6938ee9eb96b10bde166ef86cda9b6082",
        "p0330014_20100906.nc": "6ab8bea8bc28a1d270de2da3e4cafe9aff4a01a887ebbf7d39bde5980cf585f5",
        "p0330015_20100906.nc": "d22c2bf453601d33e51dc7f3aeecb823fefb532d44b07d45240f5400bc12b464",
        "p0330016_20100906.nc": "404a22da318909c42dcb65fd7315ae1f5542ed8b057faa30c7b21e07f50d67a9",
        "p0330017_20100906.nc": "06df146adee75439cc4f42e27038bec5596705fbe0a93ea53d2d65d94d719504",
        "p0330018_20100906.nc": "3dc2363797adce65c286c5099f0144bb0583b368c84dc24185caba0cad9478a7",
        "p0330019_20100906.nc": "7e37ad465f720ea1f1257830a595677f6d5f85d7391e711d6164ccee8ada5399"
    }
)

# Information on creating a registry file: https://www.fatiando.org/pooch/latest/registry-files.html
# But instead of pkg_resources (https://setuptools.pypa.io/en/latest/pkg_resources.html#)
# we should use importlib.resources
# Here's how to use importlib.resources (https://importlib-resources.readthedocs.io/en/latest/using.html)
def load_sample_dataset(dataset_name="p0330015_20100906.nc"):
    """Download sample datasets for use with seagliderOG1

    Args:
        dataset_name (str, optional): _description_. Defaults to "p0330015_20100906.nc".

    Raises:
        ValueError: If the requests dataset is not known, raises a value error

    Returns:
        xarray.Dataset: Requested sample dataset
    """
    if dataset_name in data_source_og.registry.keys():
        file_path = data_source_og.fetch(dataset_name)
        return xr.open_dataset(file_path)
    else:
        msg = f"Requested sample dataset {dataset_name} not known. Specify one of the following available datasets: {list(data_source_og.registry.keys())}"
        raise KeyError(msg)

def _validate_filename(filename):
    """
    Validates if the given filename matches the expected pattern.
    The expected pattern is a string that starts with 'p', followed by exactly 
    7 digits, and ends with '.nc'.
    Args:
        filename (str): The filename to validate.
    Returns:
        bool: True if the filename matches the pattern, False otherwise.
    """
    # pattern 1: p1234567.nc
    pattern1 = r'^p\d{7}\.nc$'
    # pattern 2: p0420100_20100903.nc
    pattern2 = r'^p\d{7}_\d{8}\.nc$'
    if re.match(pattern1, filename) or re.match(pattern2, filename):
        glider_sn = _glider_sn_from_filename(filename)
        divenum = _profnum_from_filename(filename)
        if int(glider_sn) > 0 and int(divenum) > 0:
            return True
        else:
            return False
    else:
        return False
        
def _profnum_from_filename(filename):
    """
    Extract the profile number from the filename.
    Args:
        filename (str): The filename from which to extract the profile number.
    Returns:
        int: The profile number extracted from the filename.
    """
    return int(filename[4:8])
    
def _glider_sn_from_filename(filename):
    """
    Extract the glider serial number from the filename.
    Args:
        filename (str): The filename from which to extract the glider serial number.
    Returns:
        int: The glider serial number extracted from the filename.
    """
    return int(filename[1:4])

def filter_files_by_profile(file_list, start_profile=None, end_profile=None):
    """
    Filter a list of files based on the start_profile and end_profile.
    Expects filenames of the form pXXXYYYY.nc, where XXX is the seaglider serial number and YYYY the divecycle number, e.g. p0420001.nc for glider 41 and divenum 0001. 
    Note: Does not require file_list to be alphabetical/sorted.

    Parameters:
    file_list (list): List of filenames to filter.
    start_profile (int, optional): The starting profile number to filter files. Defaults to None.
    end_profile (int, optional): The ending profile number to filter files. Defaults to None.

    Returns:
    list: A list of filtered filenames.
    """
    filtered_files = []

    for file in file_list:
        if not _validate_filename(file):
            file_list.remove(file)
            #_log.warning(f"Skipping file {file} as it does not have the expected format.")

#    divenum_values = [int(file[4:8]) for file in file_list]

    # This could be refactored: see divenum_values above, and find values between start_profile and end_profil
    for file in file_list:
        # Extract the profile number from the filename now from the begining
        profile_number = _profnum_from_filename(file)
        if start_profile is not None and end_profile is not None:
            if start_profile <= profile_number <= end_profile:
                filtered_files.append(file)
        elif start_profile is not None:
            if profile_number >= start_profile:
                filtered_files.append(file)
        elif end_profile is not None:
            if profile_number <= end_profile:
                filtered_files.append(file)
        else:
            filtered_files.append(file)

    return filtered_files

def load_first_basestation_file(source):
    """
    Load the first dataset from either an online source or a local directory.

    Parameters:
    source (str): The URL to the directory containing the NetCDF files or the path to the local directory.

    Returns:
    An xarray.Dataset object loaded from the first NetCDF file.
    """
    file_list = list_files(source)
    filename = file_list[0]
    start_profile = _profnum_from_filename(filename)
    datasets = load_basestation_files(source, start_profile, start_profile)
    return datasets[0]

def load_basestation_files(source, start_profile=None, end_profile=None):
    """
    Load datasets from either an online source or a local directory, optionally filtering by profile range.

    Parameters:
    source (str): The URL to the directory containing the NetCDF files or the path to the local directory.
    start_profile (int, optional): The starting profile number to filter files. Defaults to None.
    end_profile (int, optional): The ending profile number to filter files. Defaults to None.

    Returns:
    A list of xarray.Dataset objects loaded from the filtered NetCDF files.
    """
    file_list = list_files(source)
    filtered_files = filter_files_by_profile(file_list, start_profile, end_profile)
    
    datasets = []

    for file in filtered_files:
        if source.startswith("http://") or source.startswith("https://"):
            ds = load_sample_dataset(file)
        else:
            ds = xr.open_dataset(os.path.join(source, file))
        
        datasets.append(ds)

    return datasets

def list_files(source):
    """
    List files from a given source, which can be either a URL or a directory path. For an online source,
    uses BeautifulSoup and requests.

    Parameters:
    source (str): The source from which to list files. It can be a URL (starting with "http://" or "https://")
                  or a local directory path.

    Returns:
    list: A list of filenames available in the specified source, sorted alphabetically
    Raises:
    ValueError: If the source is neither a valid URL nor a directory path.
    """

    if source.startswith("http://") or source.startswith("https://"):
       # List all files in the URL directory
        response = requests.get(source)
        response.raise_for_status()  # Raise an error for bad status codes

        soup = BeautifulSoup(response.text, "html.parser")
        file_list = []

        for link in soup.find_all("a"):
            href = link.get("href")
            if href and href.endswith(".nc"):
                file_list.append(href)
    
    elif os.path.isdir(source):
        file_list = os.listdir(source)
    else:
        raise ValueError("Source must be a valid URL or directory path.")

    # Sort alphabetically
    file_list.sort()

    return file_list


