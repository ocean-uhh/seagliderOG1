"""Reading basestation dive files: finding missions, the file names, and the per-dive
coordinate checks before the merge.

Data: the sg005 demo dives; the per-dive checks use small hand-built datasets. The repair
tests copy two sg005 dives and label one text variable of the first as a time, the defect
the repair exists for (no bundled file has it).
"""

import pathlib
import shutil

import netCDF4
import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _pipeline, readers

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]
rng = np.random.default_rng(0)


# --- Finding and reading dive files -------------------------------------------------------


def test_read_file():
    """Test the read_file function from the readers module.
    This test checks the loading of the first dataset from either an online source
    or a local directory. It uses a sample dataset and the expected result after
    loading the dataset. The test asserts that the read_file
    function returns the correct dataset, providing an appropriate error message
    if the assertion fails.
    """
    source = str(parent_dir / "data/demo_sg005")
    dataset = readers.read_file(source)
    assert dataset.dive_number == 1, "Unexpected profile number for first dataset"
    assert (
        dataset.latitude.values.mean() > 61 and dataset.latitude.values.mean() < 62
    ), "Unexpected latitude range for first dataset"
    assert len(dataset.longitude) == 53, (
        "Unexpected number of longitude values for first dataset"
    )


def test_read_mission():
    """Test the read_mission function from the readers module.
    This test checks the loading of datasets from either an online source or a local
    directory, optionally filtering by profile range. It uses a sample dataset and
    the expected result after loading the dataset. The test asserts that the read_mission
    function returns the correct dataset, providing an appropriate error message if the
    assertion fails.
    """
    source = str(parent_dir / "data/demo_sg005")
    print("Testing read_mission with source:", source)
    start_profile = 1
    end_profile = 5
    datasets = readers.read_mission(source, start_profile, end_profile)
    assert len(datasets) == 5, "Unexpected number of datasets loaded"
    assert datasets[-1].dive_number == 5, "Unexpected profile number for last dataset"
    assert (
        datasets[0].latitude.values.mean() > 61
        and datasets[0].latitude.values.mean() < 62
    ), "Unexpected latitude range for first dataset"


def test_readers_accept_a_path() -> None:
    """A pathlib.Path source reads the same files as its string."""
    source = (
        pathlib.Path(__file__).parent.resolve().parent.parent / "data" / "demo_sg005"
    )
    assert readers.list_files(source) == readers.list_files(str(source))
    assert len(readers.read_mission(source, 1, 2)) == 2


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
        assert readers.validate_filename(filename) is True, (
            f"Expected True for {filename}"
        )

    for filename in invalid_filenames:
        assert readers.validate_filename(filename) is False, (
            f"Expected False for {filename}"
        )


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


def test_read_mission_repair_is_opt_in(monkeypatch):
    """repair_files runs only when repair=True; the source tree is untouched otherwise."""
    calls = []
    monkeypatch.setattr(readers, "repair_files", lambda *a, **k: calls.append(a))
    source = str(parent_dir / "data/demo_sg005")
    readers.read_mission(source, 1, 1)
    assert calls == []
    readers.read_mission(source, 1, 1, repair=True)
    assert len(calls) == 1


# --- Repairing files with a text variable labelled as a time ------------------------------


def _mislabelled_folder(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Copy sg005 dives 1 and 2; give dive 1's text variable ``wlbb2f`` time units.

    Returns the folder and the path of the edited dive-1 file. Dive 2 is left as it is.
    """
    folder = tmp_path / "raw"
    folder.mkdir()
    names = sorted(f.name for f in (parent_dir / "data/demo_sg005").glob("p*.nc"))[:2]
    for name in names:
        shutil.copy2(parent_dir / "data/demo_sg005" / name, folder / name)
    with netCDF4.Dataset(folder / names[0], "a") as nc:
        nc["wlbb2f"].setncattr("units", "seconds since 1970-1-1 00:00:00")
    return folder, folder / names[0]


def test_text_variable_labelled_as_time_stops_the_read(tmp_path):
    """Without the repair, a file with a text variable labelled as a time cannot be opened."""
    _folder, bad = _mislabelled_folder(tmp_path)
    with pytest.raises(ValueError, match="unable to decode time units"):
        xr.open_dataset(bad, engine="netcdf4", decode_timedelta=False)


def test_repair_fixes_only_the_file_that_needs_it(tmp_path):
    """repair_files removes the time label from the text variable, keeps the original as a
    backup, logs what it did, and leaves the good file untouched. The repaired file reads
    back with the same values and attributes; it is rewritten, so it is not the same on disk
    (the rewrite adds fill-value attributes, for one)."""
    folder, bad = _mislabelled_folder(tmp_path)
    good = next(f for f in folder.glob("p*.nc") if f != bad)
    bad_before, good_before = bad.read_bytes(), good.read_bytes()
    with xr.open_dataset(bad, engine="netcdf4", decode_times=False) as ds:
        before = ds.load()

    readers.repair_files(str(folder))

    fixes = folder / "metadata_fixes"
    assert (fixes / f"{bad.stem}_original.nc").read_bytes() == bad_before
    assert not (fixes / f"{good.stem}_original.nc").exists()
    assert good.read_bytes() == good_before
    log = (fixes / "repair_log.txt").read_text()
    assert bad.name in log and "['wlbb2f']" in log and good.name not in log

    with xr.open_dataset(bad, engine="netcdf4", decode_times=False) as ds:
        after = ds.load()
    assert "units" not in after["wlbb2f"].attrs
    np.testing.assert_array_equal(after["wlbb2f"].values, before["wlbb2f"].values)
    # As read back: every other variable, its attributes and the global attributes agree.
    xr.testing.assert_identical(after.drop_vars("wlbb2f"), before.drop_vars("wlbb2f"))
    # No leftover temporary file beside the dives.
    assert sorted(f.name for f in folder.glob("*.nc")) == sorted([bad.name, good.name])


def test_repair_leaves_good_files_alone(tmp_path):
    """A folder of readable files: nothing is rewritten, backed up or logged."""
    folder = tmp_path / "raw"
    folder.mkdir()
    src = sorted((parent_dir / "data/demo_sg005").glob("p*.nc"))[0]
    shutil.copy2(src, folder / src.name)
    readers.repair_files(str(folder))
    assert (folder / src.name).read_bytes() == src.read_bytes()
    assert list((folder / "metadata_fixes").glob("*")) == []


def test_read_mission_with_repair_reads_the_mislabelled_file(tmp_path):
    """read_mission(repair=True) repairs first, so both dives are read."""
    folder, _bad = _mislabelled_folder(tmp_path)
    datasets = readers.read_mission(str(folder), 1, 2, repair=True)
    assert [int(ds.attrs["dive_number"]) for ds in datasets] == [1, 2]


# --- Per-dive coordinate and time checks --------------------------------------------------


def test_validate_coords():
    """Test function for the `_pipeline._validate_coords` function.
    This function creates a dummy xarray dataset with coordinates N_MEASUREMENTS.
    It then validates the coordinates using the `_validate_coords` function.
    Asserts:
        - The coordinates are validated correctly.
    """
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("sg_data_point", rng.random(10)),
            "ctd_depth": ("sg_data_point", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )
    dataset.attrs["id"] = "testID"

    # Validate coordinates using the _validate_coords function
    ds1 = _pipeline._validate_coords(dataset)
    assert "ctd_time" in ds1.coords
    assert "ctd_depth" in ds1.coords
    assert "latitude" in ds1.coords
    assert len(ds1.coords["longitude"]) == ds1.dims["sg_data_point"]


def test_validate_dims():
    """Test function for the `_pipeline._validate_dims` function.
    This function creates a dummy xarray dataset with dimensions N_MEASUREMENTS.
    It then validates the dimensions using the `_validate_dims` function.
    Asserts:
        - The dimensions are validated correctly.
    """
    # Create a dummy xarray dataset with dimensions N_MEASUREMENTS
    # Create a dummy xarray dataset with correct coordinates
    dataset = xr.Dataset(
        {
            "ctd_time": ("N_MEASUREMENTS", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )
    # Validate dimensions using the _validate_dims function
    valid = _pipeline._validate_dims(dataset)

    assert valid is True

    # Create a dummy xarray dataset with incorrect dimensions
    dataset_invalid = xr.Dataset(
        {
            "ctd_time": ("INVALID_DIM", rng.random(10)),
        },
        coords={"longitude": rng.random(10), "latitude": rng.random(10)},
    )

    # Validate dimensions using the _validate_dims function
    valid_invalid = _pipeline._validate_dims(dataset_invalid)

    assert valid_invalid is False


def test_clean_time_string():
    """Test function for the `_pipeline._clean_time_string` function.
    This function defines a set of test strings with expected cleaned strings.
    It then iterates over these test strings, cleans them using the `_clean_time_string` function,
    and asserts that the cleaned strings match the expected values.
    Test strings and their expected results:
        - "2018-01-01T00:00:00Z": "20180101T000000"
        - "2018-01-01T00:00:00": "20180101T000000"
        - "2018-01-01_00:00:00": "20180101T000000"
        - "2018-01-01_00:00:00Z": "20180101T000000"
    Asserts:
        - The cleaned string matches the expected cleaned string.
    """
    test_strings = {
        "2018-01-01T00:00:00Z": "20180101T000000",
        "2018-01-01T00:00:00": "20180101T000000",
        "2018-01-01_00:00:00": "20180101000000",
        "2018-01-01_00:00:00Z": "20180101000000",
    }

    for tstring, tstring1 in test_strings.items():
        cleaned_tstring = _pipeline._clean_time_string(tstring)

        assert cleaned_tstring == tstring1
