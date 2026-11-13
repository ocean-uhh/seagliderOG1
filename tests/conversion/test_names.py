"""Basestation names to OG1 names: which variable becomes which, what keeps its own name,
and the provenance attributes every variable carries.

Data: the sg005 demo conversion, the sg271 sample, and the name-mapping table.
"""

import pathlib

import numpy as np
import pandas as pd
import xarray as xr

from seagliderOG1 import _convert, _pipeline, readers, vocabularies

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]


# --- The name mapping ---------------------------------------------------------------------


def test_og1_name_mapping_sample_dataset():
    ds1 = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)[0]

    mapping, time_variables = _pipeline.og1_name_mapping([ds1])

    expected_columns = [
        "original_name",
        "OG1_name",
        "instrument",
        "instrument_type",
        "original_dimension",
        "has_og1_attributes",
    ]
    assert list(mapping.columns) == expected_columns
    assert mapping["original_name"].is_unique

    # Time associations are returned separately.
    assert "time" in time_variables["sg_data_point"]
    assert "log_gps_time" in time_variables["gps_info"]
    assert "gc_st_secs" in time_variables["gc_event"]

    for dimension, names in time_variables.items():
        assert dimension in ds1.dims
        assert names
        assert len(names) == len(set(names))
        assert set(names).issubset(ds1.variables)

    # All input variables are retained except individual time variables,
    # which are replaced by the single synthetic time row.
    time_names = {name for names in time_variables.values() for name in names}
    expected_variables = (set(ds1.variables) - time_names) | {"time"}

    assert set(mapping["original_name"]) == expected_variables

    # Index by original name so assertions do not depend on row order.
    actual = mapping.set_index("original_name")

    assert actual.loc["time", "OG1_name"] == "TIME"
    assert actual.loc["time", "original_dimension"] == ""

    for name in expected_variables - {"time"}:
        assert actual.loc[name, "original_dimension"] == ", ".join(ds1[name].dims)

    # Vocabulary availability is reported independently of variable retention.
    for row in mapping.itertuples(index=False):
        expected = (
            bool(vocabularies.vocab_attrs.get(row.OG1_name, {}))
            if pd.notna(row.OG1_name)
            else False
        )
        assert bool(row.has_og1_attributes) == expected


def test_name_mapping_returns_the_mapping_table():
    """name_mapping returns the basestation->OG1 table; a bare Dataset is rejected."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    mapping = _convert.name_mapping(datasets)
    assert list(mapping.columns) == [
        "original_name",
        "OG1_name",
        "instrument",
        "instrument_type",
        "original_dimension",
        "has_og1_attributes",
    ]
    assert len(mapping) > 0
    assert "TIME" in set(mapping["OG1_name"])

    try:
        _convert.name_mapping(datasets[0])
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for a bare Dataset")


# --- Provenance on every variable ---------------------------------------------------------


def test_original_name_on_every_basestation_variable():
    """Each renamed or passed-through variable records its basestation name; derived ones are listed."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    derived = set(json.loads(ds.attrs["conversion_derived_variables"]))
    for name in ds.variables:
        named = "original_name" in ds[name].attrs
        # A variable is either a basestation variable (named) or a listed derived one,
        # never both and never neither — so a missing original_name is always a bug.
        assert named != (name in derived), name
    # Renaming actually happened (original_name differs from the OG1 name) ...
    renamed = [
        n for n in ds.variables if ds[n].attrs.get("original_name") not in (None, n)
    ]
    assert renamed
    # ... and the pre-0.1.0 attribute spelling is gone.
    assert all("original_variable_name" not in ds[n].attrs for n in ds.variables)


def test_built_variables_carry_their_provenance_and_names(
    sg005_og1: pathlib.Path,
) -> None:
    """Converter-built variables keep their vocabulary long_name and source dimension."""
    with xr.open_dataset(sg005_og1, engine="netcdf4", decode_timedelta=False) as ds:
        for name in ("LATITUDE_GPS", "LONGITUDE_GPS", "TIME_GPS"):
            assert ds[name].attrs["original_dimension"] == "gps_info", name
            # Derived: the ledger names its sources, so no original_name.
            assert "original_name" not in ds[name].attrs
        for name in ("LATITUDE_GPS", "TIME_GPS", "PHASE", "PROFILE_NUMBER"):
            assert (
                ds[name].attrs["long_name"]
                == vocabularies.vocab_attrs[name]["long_name"]
            )
        assert ds["PHASE_QC"].attrs["long_name"] == (
            f"{vocabularies.vocab_attrs['PHASE']['long_name']} quality flag"
        )
        assert ds["PROFILE_NUMBER"].encoding["_FillValue"] == -9999


def test_basestation_comment_is_kept_not_renamed():
    """A basestation comment is carried to the output unchanged, not folded into history."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    datasets[0].attrs["comment"] = "deployed off the shelf break"
    ds = _convert.convert(datasets)
    assert ds.attrs.get("comment") == "deployed off the shelf break"
    assert "deployed off the shelf break" not in ds.attrs["history"]


def test_formerly_dropped_variables_reach_the_file():
    """Variables the package drop list used to remove are now in the output, by original_name."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    written = {ds[v].attrs.get("original_name"): v for v in ds.variables}
    assert vocabularies.VARIABLES_TO_DROP == []
    assert written["density"] == "density"  # passed through
    assert written["theta"] == "THETA"  # renamed by OG1_variable_names.yaml
    # dissolved_oxygen_sat is per-mass micromoles/kg, a different quantity from OXYSAT's percent:
    # no longer mapped, it passes through under its own name (recommended for drop).
    assert written["dissolved_oxygen_sat"] == "dissolved_oxygen_sat"
    # depth and eng_depth also map to DEPTH, which ctd_depth holds; they are numbered.
    assert written["ctd_depth"] == "DEPTH"
    assert {written["depth"], written["eng_depth"]} == {"DEPTH_2", "DEPTH_3"}


# --- Variables that keep their own names --------------------------------------------------


def test_raw_count_channels_keep_their_names_and_are_counts():
    """WET Labs counts are not written as BBP700/BBP470; counts get units 'counts'."""
    ds = _convert.convert(
        readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    )
    assert "BBP700" not in ds and "BBP470" not in ds
    for name in ("eng_wlbb2f_redCount", "eng_wlbb2f_blueCount"):
        assert ds[name].attrs["units"] == "counts", name
        assert ds[name].attrs["original_name"] == name
    assert ds["FLUOCHLA"].attrs["units"] == "counts"  # mapped, still a raw count
    assert ds["BBP700_REF"].attrs["units"] == "counts"


def test_tridente_bb700_keeps_its_name_and_units():
    """A Tridente bb700 (a volume scattering function) is not mapped to BBP700.

    Synthetic, for the name mapping only (no basestation-3 file is in the test data): the
    chla470 channel beside it shows the instrument-prefix stripping still runs, so bb700 is
    unmapped because the config no longer names it, not because the prefix went unseen.
    """
    dim = "tridentebb700chla470fdom365_data_point"
    units = "meter^-1 steradian^-1"
    ds = xr.Dataset(
        {
            "tridentebb700chla470fdom365_bb700": (
                dim,
                np.array([1e-3, 2e-3]),
                {"units": units},
            ),
            "tridentebb700chla470fdom365_chla470": (dim, np.array([0.1, 0.2])),
        },
        attrs={"instrument": "tridentebb700chla470fdom365", "dive_number": 1},
    )
    mapping, _ = _pipeline.og1_name_mapping([ds])
    og1 = dict(zip(mapping["original_name"], mapping["OG1_name"], strict=True))
    assert (
        og1["tridentebb700chla470fdom365_chla470"] == "CHLA"
    )  # prefix stripping is live
    assert pd.isna(og1["tridentebb700chla470fdom365_bb700"])  # passes through by name
    # Its stated units are kept: the counts label applies only to unit-less raw counts.
    assert not _convert._is_raw_count(
        "tridentebb700chla470fdom365_bb700", {"units": units}
    )
    # The three uncalibrated sources unmapped here stay unmapped (computed backscatter
    # names such as particulate_backscatter may still map to BBP700).
    for raw in ("bb700", "redCount", "blueCount"):
        assert raw not in vocabularies.standard_names, raw


def test_is_raw_count_needs_the_suffix_and_no_units():
    """Pure logic: a stated unit is never overwritten."""
    assert _convert._is_raw_count("eng_wlbb2f_redCount", {})
    assert not _convert._is_raw_count("eng_wlbb2f_redCount", {"units": "m-1"})
    assert not _convert._is_raw_count("eng_rollCtl", {})
