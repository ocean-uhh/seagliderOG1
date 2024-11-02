import pooch
import xarray as xr
import os
from bs4 import BeautifulSoup
import requests
import numpy as np

# readers.py: Will only read files.  Not manipulate them.
#
# Comment 2024 Oct 30: I needed an initial file list to create the registry
# This is impractical for expansion, so may need to move away from pooch.
# This was necessary to get an initial file list
# mylist = fetchers.list_files_in_https_server(server)
# fetchers.create_pooch_registry_from_directory("/Users/eddifying/Dropbox/data/sg015-ncei-download/")

def load_sample_dataset(dataset_name="p0150500_20050213.nc"):
    if dataset_name in data_source_og.registry.keys():
        file_path = data_source_og.fetch(dataset_name)
        return xr.open_dataset(file_path)
    else:
        msg = f"Requested sample dataset {dataset_name} not known"
        raise ValueError(msg)

def filter_files_by_profile(file_list, start_profile=None, end_profile=None):
    """
    Filter a list of files based on the start_profile and end_profile.

    Parameters:
    file_list (list): List of filenames to filter.
    start_profile (int, optional): The starting profile number to filter files. Defaults to None.
    end_profile (int, optional): The ending profile number to filter files. Defaults to None.

    Returns:
    list: A list of filtered filenames.
    """
    filtered_files = []

    for file in file_list:
        if file.endswith(".nc"):
            profile_number = int(file.split("_")[0][4:])
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

def read_basestation(source, start_profile=None, end_profile=None):
    """
    Load datasets from either an online source or a local directory, optionally filtering by profile range.

    Parameters:
    source (str): The URL to the directory containing the NetCDF files or the path to the local directory.
    start_profile (int, optional): The starting profile number to filter files. Defaults to None.
    end_profile (int, optional): The ending profile number to filter files. Defaults to None.

    Returns:
    A list of xarray.Dataset objects loaded from the filtered NetCDF files.
    """
    if source.startswith("http://") or source.startswith("https://"):
        # Create a Pooch object to manage the remote files
        data_source_online = pooch.create(
            path=pooch.os_cache("seagliderOG1_online"),
            base_url=source,
            registry=None,
        )

        # List all files in the URL directory
        file_list = list_files_in_https_server(source)
    elif os.path.isdir(source):
        file_list = os.listdir(source)
    else:
        raise ValueError("Source must be a valid URL or directory path.")

    filtered_files = filter_files_by_profile(file_list, start_profile, end_profile)
    
    datasets = []

    for file in filtered_files:
        if source.startswith("http://") or source.startswith("https://"):
            ds = load_sample_dataset(file)
        else:
            ds = xr.open_dataset(os.path.join(source, file))
        
        datasets.append(ds)

    return datasets

def list_files_in_https_server(url):
    """
    List files in an HTTPS server directory using BeautifulSoup and requests.

    Parameters:
    url (str): The URL to the directory containing the files.

    Returns:
    list: A list of filenames found in the directory.
    """
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad status codes

    soup = BeautifulSoup(response.text, "html.parser")
    files = []

    for link in soup.find_all("a"):
        href = link.get("href")
        if href and href.endswith(".nc"):
            files.append(href)

    return files

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

