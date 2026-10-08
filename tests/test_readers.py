import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import readers


def test_validate_filename():
    """Test the validate_filename function from the readers module.
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
    The test asserts that the validate_filename function returns True for valid
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
            readers.validate_filename(filename) is True
        ), f"Expected True for {filename}"

    for filename in invalid_filenames:
        assert (
            readers.validate_filename(filename) is False
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
    source = str(parent_dir / "data/demo_sg005")
    print("Testing load_basestation_files with source:", source)
    start_profile = 1
    end_profile = 5
    datasets = readers.load_basestation_files(source, start_profile, end_profile)
    assert len(datasets) == 5, "Unexpected number of datasets loaded"
    assert datasets[-1].dive_number == 5, "Unexpected profile number for last dataset"
    assert (
        datasets[0].latitude.values.mean() > 61
        and datasets[0].latitude.values.mean() < 62
    ), "Unexpected latitude range for first dataset"


def test_discover_missions_single_dir():
    """A directory of basestation files is discovered as one mission."""
    source = str(parent_dir / "data/demo_sg005")
    missions = readers.discover_missions(source)
    assert len(missions) == 1
    assert missions[0].sn == 5
    assert missions[0].date is None
    assert missions[0].dives == [1, 2, 3, 4, 5]


def test_discover_missions_root(tmp_path):
    """A root of SN/DATE directories yields one mission per date directory."""
    source = parent_dir / "data/demo_sg005"
    names = [f.name for f in source.iterdir() if readers.validate_filename(f.name)]
    for date in ("20080606", "20080607"):
        dest = tmp_path / "005" / date
        dest.mkdir(parents=True)
        for name in names:
            (dest / name).write_bytes((source / name).read_bytes())

    missions = readers.discover_missions(str(tmp_path))
    assert len(missions) == 2
    assert {m.date for m in missions} == {"20080606", "20080607"}
    assert all(m.sn == 5 and m.dives == [1, 2, 3, 4, 5] for m in missions)


def test_discover_missions_not_a_directory():
    """A non-directory source raises ValueError."""
    try:
        readers.discover_missions(str(parent_dir / "data/does-not-exist"))
    except ValueError as exc:
        assert "not a directory" in str(exc)
    else:
        msg = "expected ValueError for a missing directory"
        raise AssertionError(msg)


def test_discover_missions_warns_on_sn_mismatch(tmp_path):
    """A SN directory disagreeing with the files warns but trusts the files."""
    import warnings

    source = parent_dir / "data/demo_sg005"
    names = [f.name for f in source.iterdir() if readers.validate_filename(f.name)]
    dest = tmp_path / "999" / "20080606"
    dest.mkdir(parents=True)
    for name in names:
        (dest / name).write_bytes((source / name).read_bytes())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        missions = readers.discover_missions(str(tmp_path))

    assert len(missions) == 1
    assert missions[0].sn == 5  # from the files, not the "999" directory
    assert any("disagrees" in str(w.message) for w in caught)


def test_load_first_basestation_file():
    """Test the load_first_basestation_file function from the readers module.
    This test checks the loading of the first dataset from either an online source
    or a local directory. It uses a sample dataset and the expected result after
    loading the dataset. The test asserts that the load_first_basestation_file
    function returns the correct dataset, providing an appropriate error message
    if the assertion fails.
    """
    source = str(parent_dir / "data/demo_sg005")
    dataset = readers.load_first_basestation_file(source)
    assert dataset.dive_number == 1, "Unexpected profile number for first dataset"
    assert (
        dataset.latitude.values.mean() > 61 and dataset.latitude.values.mean() < 62
    ), "Unexpected latitude range for first dataset"
    assert (
        len(dataset.longitude) == 53
    ), "Unexpected number of longitude values for first dataset"
