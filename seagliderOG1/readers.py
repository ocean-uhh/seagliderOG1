import xarray as xr
import os
from bs4 import BeautifulSoup
import requests
import numpy as np
from importlib_resources import files
import pooch
import re

# readers.py: Will only read files.  Not manipulate them.
#
# Comment 2024 Oct 30: I needed an initial file list to create the registry
# This is impractical for expansion, so may need to move away from pooch.
# This was necessary to get an initial file list
# mylist = fetchers.list_files_in_https_server(server)
# fetchers.create_pooch_registry_from_directory("/Users/eddifying/Dropbox/data/sg015-ncei-download/")
# Example usage
#directory_path = "/Users/eddifying/Dropbox/data/sg015-ncei-snippet"
#pooch_registry = create_pooch_registry_from_directory(directory_path)
#print(pooch_registry)

# Information on creating a registry file: https://www.fatiando.org/pooch/latest/registry-files.html
# But instead of pkg_resources (https://setuptools.pypa.io/en/latest/pkg_resources.html#)
# we should use importlib.resources
# Here's how to use importlib.resources (https://importlib-resources.readthedocs.io/en/latest/using.html)
server = "https://www.dropbox.com/scl/fo/dhinr4hvpk05zcecqyz2x/ADTqIuEpWHCxeZDspCiTN68?rlkey=bt9qheandzbucca5zhf5v9j7a&dl=0"
server = "https://www.ncei.noaa.gov/data/oceans/glider/seaglider/uw/015/20040924/"
data_source_og = pooch.create(
    path=pooch.os_cache("seagliderOG1"),
    base_url=server,
    registry=None,
)
registry_file = files('seagliderOG1').joinpath('seaglider_registry.txt')
data_source_og.load_registry(registry_file)


def load_sample_dataset(dataset_name="p0150500_20050213.nc"):
    if dataset_name in data_source_og.registry.keys():
        file_path = data_source_og.fetch(dataset_name)
        return xr.open_dataset(file_path)
    else:
        msg = f"Requested sample dataset {dataset_name} not known"
        raise ValueError(msg)

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

def list_files(source, registry_loc="seagliderOG1", registry_name="seaglider_registry.txt"):
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
        # Create a Pooch object to manage the remote files
        data_source_online = pooch.create(
            path=pooch.os_cache(registry_loc),
            base_url=source,
            registry=None,
        )
        registry_file = files(registry_loc).joinpath(registry_name)
        data_source_og.load_registry(registry_file)

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

def create_pooch_registry_from_directory(directory):
    """
    Create a Pooch registry from files in a specified directory.

    Parameters:
    directory (str): The path to the directory containing the files.

    Returns:
    dict: A dictionary representing the Pooch registry with filenames as keys and their SHA256 hashes as values.
    """
    registry = {}
    files = os.listdir(directory)

    for file in files:
        if file.endswith(".nc"):
            file_path = os.path.join(directory, file)
            sha256_hash = pooch.file_hash(file_path, alg="sha256")
            registry[file] = f"sha256:{sha256_hash}"

    return registry

