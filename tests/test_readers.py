import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import readers


def test_demo_datasets():
    ds = readers.load_sample_dataset(dataset_name="p0330001_20100903.nc")
    assert ds is not None


def test_validate_filename():
    """Test the _validate_filename function from the readers module.
    This test checks the validation of filenames to ensure they meet the expected
    criteria. It uses a list of valid filenames that should pass the validation
    and a list of invalid filenames that should fail the validation.
    Valid filenames:
    - "p1234567.nc"
    - "p7654321.nc"
    Invalid filenames:
    - "p0010000.nc"
    - "p0000001.nc"
    - "p000000.nc"
    - "p12345678.nc"
    - "p123456.nc"
    - "p1234567.txt"
    - "1234567.nc"
    - "pabcdefg.nc"
    The test asserts that the _validate_filename function returns True for valid
    filenames and False for invalid filenames, providing an appropriate error
    message if the assertion fails.
    """
    valid_filenames = ["p1234567.nc", "p7654321.nc", "p0330001_20100903.nc"]
    invalid_filenames = [
        "p0010000.nc",
        "p0000001.nc",
        "p000000.nc",
        "p12345678.nc",
        "p123456.nc",
        "p1234567.txt",
        "1234567.nc",
        "pabcdefg.nc",
        "p0420100_20100903T101010.nc",
    ]

    for filename in valid_filenames:
        assert (
            readers._validate_filename(filename) is True
        ), f"Expected True for {filename}"

    for filename in invalid_filenames:
        assert (
            readers._validate_filename(filename) is False
        ), f"Expected False for {filename}"


def test_filter_filelist_by_profile():
    """Test the filter_files_by_profile function from the readers module.
    This test checks the filtering of filenames based on the start_profile and
    end_profile parameters. It uses a list of filenames to filter and the expected
    result after filtering. The test asserts that the filter_files_by_profile
    function returns the correct list of filtered filenames, providing an appropriate
    error message if the assertion fails.
    """
    file_list = [
        "p7654321.nc",
        "p0010000.nc",
        "p0000001.nc",
        "p000000.nc",
        "p0010001.nc",
        "p0010002.nc",
        "p0010003.nc",
        "p0010004.nc",
        "p0010005.nc",
        "p0010006.nc",
        "p0010007.nc",
        "p0010008.nc",
        "p0010009.nc",
    ]
    start_profile = 5
    end_profile = 20
    expected_result = [
        "p0010005.nc",
        "p0010006.nc",
        "p0010007.nc",
        "p0010008.nc",
        "p0010009.nc",
    ]

    assert (
        readers.filter_files_by_profile(file_list, start_profile, end_profile)
        == expected_result
    ), "Unexpected result for filter_files_by_profile"


def test_load_basestation_files():
    """Test the load_basestation_files function from the readers module.
    This test checks the loading of datasets from either an online source or a local
    directory, optionally filtering by profile range. It uses a sample dataset and
    the expected result after loading the dataset. The test asserts that the load_basestation_files
    function returns the correct dataset, providing an appropriate error message if the
    assertion fails.
    """
    source = "https://www.ncei.noaa.gov/data/oceans/glider/seaglider/uw/033/20100903/"
    start_profile = 5
    end_profile = 10
    datasets = readers.load_basestation_files(source, start_profile, end_profile)
    assert len(datasets) == 6, "Unexpected number of datasets loaded"
    assert datasets[-1].dive_number == 10, "Unexpected profile number for last dataset"
    assert (
        datasets[0].latitude.values.mean() > 18
        and datasets[0].latitude.values.mean() < 19
    ), "Unexpected latitude range for first dataset"


def test_load_first_basestation_file():
    """Test the load_first_basestation_file function from the readers module.
    This test checks the loading of the first dataset from either an online source
    or a local directory. It uses a sample dataset and the expected result after
    loading the dataset. The test asserts that the load_first_basestation_file
    function returns the correct dataset, providing an appropriate error message
    if the assertion fails.
    """
    source = "https://www.ncei.noaa.gov/data/oceans/glider/seaglider/uw/033/20100903/"
    dataset = readers.load_first_basestation_file(source)
    assert dataset.dive_number == 1, "Unexpected profile number for first dataset"
    assert (
        dataset.latitude.values.mean() > 18.5 and dataset.latitude.values.mean() < 18.6
    ), "Unexpected latitude range for first dataset"
    assert (
        len(dataset.longitude) == 130
    ), "Unexpected number of longitude values for first dataset"
