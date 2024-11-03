import pooch
import xarray as xr
import os
from bs4 import BeautifulSoup
import requests
import numpy as np
from seagliderOG1 import readers

# Comment 2024 Oct 30: I needed an initial file list to create the registry
# This is impractical for expansion, so may need to move away from pooch.
# This was necessary to get an initial file list
# mylist = fetchers.list_files_in_https_server(server)
# fetchers.create_pooch_registry_from_directory("/Users/eddifying/Dropbox/data/sg015-ncei-download/")


def load_sample_dataset(dataset_name="p0150500_20050213.nc", pooch_registry=None):
    if dataset_name in pooch_registry.registry.keys():
        file_path = pooch_registry.fetch(dataset_name)
        return xr.open_dataset(file_path)
    else:
        msg = f"Requested sample dataset {dataset_name} not known"
        raise ValueError(msg)
    
def download_dataset(source, start_profile=None, end_profile=None, pooch_registry=None):
    """
    Load datasets from either an online source or a local directory, optionally filtering by profile range.

    Parameters:
    source (str): The URL to the directory containing the NetCDF files or the path to the local directory.
    start_profile (int, optional): The starting profile number to filter files. Defaults to None.
    end_profile (int, optional): The ending profile number to filter files. Defaults to None.

    Returns:
    A list of xarray.Dataset objects loaded from the filtered NetCDF files.
    """
    file_list = list_files_in_https_server(source)
    filtered_files = readers.filter_files_by_profile(file_list, start_profile, end_profile)
    
    for file in filtered_files:
        if source.startswith("http://") or source.startswith("https://"):
            ds = load_sample_dataset(file, pooch_registry)
        else:
            ds = xr.open_dataset(os.path.join(source, file))
        
    return 
    

def add_gps_coordinates(ds):
    # Find the nearest index in sg_data_point corresponding to gps_time
    def find_nearest_index(ds, gps_time):
        time_diff = np.abs(ds['ctd_time'] - gps_time)
        nearest_index = time_diff.argmin().item()
        return nearest_index

    # Create new variables gps_lat and gps_lon with dimensions sg_data_point
    ds['gps_lat'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))
    ds['gps_lon'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))
    ds['gps_time'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))

    # Fill gps_lat and gps_lon with values from log_gps_lat and log_gps_lon at the nearest index
    for gps_time, gps_lat, gps_lon in zip(ds.log_gps_time.values, ds.log_gps_lat.values, ds.log_gps_lon.values):
        nearest_index = find_nearest_index(ds, gps_time)
        ds['gps_lat'][nearest_index] = gps_lat
        ds['gps_lon'][nearest_index] = gps_lon
        ds['gps_time'][nearest_index] = gps_time

    # Add attributes to the new variables
    ds['gps_time'].attrs = ds['log_gps_time'].attrs
    ds['gps_lon'].attrs = ds['log_gps_lon'].attrs
    ds['gps_lat'].attrs = ds['log_gps_lat'].attrs
    return ds

def append_gps_coordinates(ds):
    """
    Append GPS coordinates to the dataset.

    Parameters:
    ds (xarray.Dataset): The input xarray dataset.

    Returns:
    xarray.Dataset: The dataset with appended GPS coordinates.
    """
    # Create new variables TIME, LATITUDE, and LONGITUDE with dimensions sg_data_point
    ds['TIME'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))
    ds['LATITUDE'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))
    ds['LONGITUDE'] = (['sg_data_point'], np.full(ds.dims['sg_data_point'], np.nan))

    # Fill TIME with values from ctd_time and log_gps_time
    ds['TIME'][:] = ds['ctd_time'].values

    # Append log_gps_time values to TIME
    time_length = ds['TIME'].size
    log_gps_time_length = ds['log_gps_time'].size
    new_time_length = time_length + log_gps_time_length

    new_time = np.full(new_time_length, np.nan)
    new_time[:time_length] = ds['TIME'].values
    new_time[time_length:] = ds['log_gps_time'].values

    ds['TIME'] = (['sg_data_point'], new_time)

    # Fill LATITUDE and LONGITUDE with values from log_gps_lat and log_gps_lon
    ds['LATITUDE'][:] = ds['log_gps_lat'].values
    ds['LONGITUDE'][:] = ds['log_gps_lon'].values

    # Add attributes to the new variables
    ds['TIME'].attrs = ds['ctd_time'].attrs
    ds['LATITUDE'].attrs = ds['log_gps_lat'].attrs
    ds['LONGITUDE'].attrs = ds['log_gps_lon'].attrs

    return ds



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



