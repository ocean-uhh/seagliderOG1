"""The v0.0.2 deprecation shims: tier A/B names warn and delegate, tier C names raise.

Every warning here is caught with ``pytest.warns(SeagliderDeprecationWarning)``, so the
suite-wide ``error::...SeagliderDeprecationWarning`` gate (which proves the package never
calls its own shims) does not turn these into errors.
"""

import pathlib
import sys

import pytest
import xarray as xr

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import seagliderOG1 as sg  # noqa: E402
from seagliderOG1 import contributors, plotters, readers, tools, writers  # noqa: E402
from seagliderOG1._deprecated import (  # noqa: E402
    SeagliderDeprecationWarning,
    convert_to_OG1,
)

DATA_DIR = parent_dir / "data" / "demo_sg005"


# --- tier A: renames warn once (new spelling + version) and delegate ---------


@pytest.mark.parametrize(
    ("call", "new_name"),
    [
        (
            lambda: readers.profnum_from_filename("p0050001_20080606.nc"),
            "profile_number_from_filename",
        ),
        (
            lambda: readers.glider_sn_from_filename("p0050001_20080606.nc"),
            "serial_from_filename",
        ),
        (lambda: contributors.normalize_role("PI"), "canonical_role"),
        (lambda: contributors.normalize_orcid(None), "canonical_orcid"),
    ],
)
def test_tier_a_warns_naming_the_new_name_and_version(call, new_name):
    """A renamed name warns once, names its 0.1.0 spelling and the 0.3.0 removal."""
    with pytest.warns(SeagliderDeprecationWarning) as record:
        call()
    assert len(record) == 1
    message = str(record[0].message)
    assert new_name in message
    assert "0.3.0" in message


def test_tier_a_delegates_to_the_new_function():
    """The shim returns what the new function returns."""
    with pytest.warns(SeagliderDeprecationWarning):
        old = readers.profnum_from_filename("p0050001_20080606.nc")
    assert old == readers.profile_number_from_filename("p0050001_20080606.nc")


def test_load_basestation_files_delegates_to_read_mission():
    """The old loader returns the same datasets as read_mission."""
    with pytest.warns(SeagliderDeprecationWarning):
        old = readers.load_basestation_files(str(DATA_DIR), 1, 1)
    new = readers.read_mission(str(DATA_DIR), 1, 1)
    assert len(old) == len(new) == 1


# --- tier B: adapters delegate, reshape, warn --------------------------------


def test_convert_to_OG1_returns_the_old_tuple_and_wraps_a_single_dataset():
    """convert_to_OG1 wraps a single Dataset as [ds] and returns (ds, var_list)."""
    ds = readers.read_file(str(DATA_DIR))
    with pytest.warns(SeagliderDeprecationWarning):
        result, var_list = convert_to_OG1(ds)
    assert isinstance(result, xr.Dataset)
    # v0.0.2's var_list is the INPUT basestation variable names (coords included), not the
    # OG1 output names — compare against the inputs so a regression to data_vars fails here.
    assert set(var_list) == {str(v) for v in ds.variables}
    assert set(var_list) != set(map(str, result.data_vars))


def test_convert_to_OG1_translates_the_contrib_dict():
    """The flat contrib_to_append dict maps to a contributors record end to end."""
    ds = readers.read_file(str(DATA_DIR))
    with pytest.warns(SeagliderDeprecationWarning):
        out, _ = convert_to_OG1(
            ds,
            contrib_to_append={
                "contributor_name": "Jane Doe",
                "contributor_role": "PI",
            },
        )
    assert "Jane Doe" in out.attrs["contributor_name"]


def test_split_contrib_to_append_comma_splits_and_refuses_the_ambiguous():
    """Comma-joined names split and pair positionally; partial/unknown/mismatch raise, never drop."""
    from seagliderOG1._deprecated import _split_contrib_to_append

    contributors, _ = _split_contrib_to_append(
        {"contributor_name": "Ann, Bob", "contributor_role": "PI, Owner"}
    )
    assert contributors == [
        {"name": "Ann", "role": "PI"},
        {"name": "Bob", "role": "Owner"},
    ]
    for bad in (
        {"nonsense": "x"},  # unknown key
        {"contributor_role": "PI"},  # value without a name
        {
            "contributor_name": "A, B",
            "contributor_role": "PI, Owner, X",
        },  # count mismatch
    ):
        with pytest.raises(ValueError, match="cannot be mapped"):
            _split_contrib_to_append(bad)


def test_save_dataset_requires_a_path_and_writes(
    tmp_path: pathlib.Path, sg005_og1: pathlib.Path
):
    """save_dataset no longer defaults the path; given one, it writes and returns True."""
    ds = xr.open_dataset(sg005_og1, engine="netcdf4", decode_timedelta=False)
    out = tmp_path / "out.nc"
    with pytest.warns(SeagliderDeprecationWarning):
        assert writers.save_dataset(ds, out) is True
    assert out.is_file()
    with (
        pytest.warns(SeagliderDeprecationWarning),
        pytest.raises(TypeError, match="output_file"),
    ):
        writers.save_dataset(ds)


def test_load_sample_dataset_is_removed():
    """load_sample_dataset is tier C: the online registry is gone, so access raises."""
    with pytest.raises(AttributeError, match="registry was removed"):
        _ = readers.load_sample_dataset


def test_show_contents_accepts_a_path_with_a_warning(sg005_og1: pathlib.Path):
    """A str/Path argument to show_* is opened (warns); a Dataset passes through silently."""
    with pytest.warns(SeagliderDeprecationWarning):
        table = plotters.show_contents(str(sg005_og1))
    assert table is not None
    ds = xr.open_dataset(sg005_og1, engine="netcdf4", decode_timedelta=False)
    plotters.show_contents(ds)  # no warning (would error under the gate if it warned)


# --- tier C: removed names raise at attribute access -------------------------


@pytest.mark.parametrize(
    ("module", "name", "needle"),
    [
        (tools, "OG1_name_mapping", "inspect --conversion"),
        (tools, "print_OG1_mapping_summary", "inspect --conversion"),
        (tools, "gather_sensor_info", "pipeline internal"),
        (tools, "set_best_dtype", "pipeline internal"),
        (sg.vocabularies, "load_default_contributors", "mission.yaml"),
        (sg.vocabularies, "contrib_to_append", "mission.yaml"),
    ],
)
def test_tier_c_raises_with_the_migration_message(module, name, needle):
    """A removed name raises AttributeError naming why and what to use instead."""
    with pytest.raises(AttributeError) as exc:
        getattr(module, name)
    message = str(exc.value)
    assert "removed in seagliderOG1 0.1.0" in message
    assert needle in message


def test_convertOG1_imports_silently_and_removed_names_raise():
    """Importing convertOG1 is silent (so -W error can import it); removed names raise."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", SeagliderDeprecationWarning)
        from seagliderOG1 import convertOG1  # no import-time warning
    with pytest.raises(AttributeError, match="mission.yaml"):
        _ = convertOG1.process_and_save_data
    with pytest.raises(AttributeError, match="internal to seagliderOG1.convert"):
        _ = convertOG1.standardise_OG10


def test_a_genuinely_missing_name_still_raises_plainly():
    """__getattr__ only rewrites the removed names; anything else is a normal AttributeError."""
    with pytest.raises(AttributeError, match="has no attribute"):
        _ = tools.not_a_real_name
