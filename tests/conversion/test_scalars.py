"""One-value basestation variables: stored as scalars when they agree across dives, as
per-dive JSON when they change.

Data: the sg005 demo conversion. The refusal tests take the scalar pass's real inputs from
a conversion of dive 1 and edit the name mapping (two names made equal, a name pointed at
TEMP, a line repeated); the last reads dives 1 and 2 and makes dive 2's ``log_MASS`` an array.
"""

import pathlib

import pandas as pd
import pytest

from seagliderOG1 import _convert, _pipeline, readers, vocabularies

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]


# --- Scalar parameters --------------------------------------------------------------------


def test_add_scalar_parameters():
    """Every input scalar survives conversion into the public output.

    Unit coverage of the scalar pass itself (constant value vs per-dive JSON encoding) belongs
    with ``add_scalar_parameters`` once it becomes a private pipeline function; this test asserts
    only what a user observes from the public converter — that no scalar is dropped.
    """
    source = str(parent_dir / "data/demo_sg005")
    datasets = readers.read_mission(source, 1, 5)

    expected_names = {
        name
        for dataset in datasets
        for name, variable in dataset.variables.items()
        if variable.ndim == 0
    }
    assert expected_names

    ds_og1 = _convert.convert(datasets)

    # Each retained scalar carries its source name in ``original_name``, so retention is
    # observable regardless of the OG1 rename applied to the variable.
    retained = {
        ds_og1[name].attrs.get("original_name")
        for name in ds_og1.variables
        if ds_og1[name].ndim == 0
    }
    assert expected_names <= retained


def test_scalar_parameters_storage_and_dimension():
    """Scalars declare storage_type and carry no empty original_dimension; per-dive JSON decodes."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    # No variable carries an empty original_dimension placeholder (it is omitted instead).
    assert all(ds[v].attrs.get("original_dimension", "x") != "" for v in ds.variables)
    # Both scalar cases declare their storage, so the ledger view infers nothing.
    per_dive = [
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "per_dive_scalar"
    ]
    constants = [
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "constant_scalar"
    ]
    assert per_dive and constants
    # A per-dive JSON scalar decodes to the converted dive numbers.
    payload = json.loads(str(ds[per_dive[0]].values))
    assert sorted(payload["dives"]) == [1, 2]
    assert len(payload["values"]) == len(payload["dives"])


def test_vbd_min_cnts_has_one_source():
    """VBD_MIN_CNTS is the calibration constant; the dive-log value keeps its own name."""
    ds = _convert.convert(
        readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    )
    assert ds["VBD_MIN_CNTS"].attrs["original_name"] == "sg_cal_vbd_min_cnts"
    assert ds["log_VBD_MIN"].attrs["original_name"] == "log_VBD_MIN"
    assert not [v for v in ds.variables if str(v).startswith("VBD_MIN_CNTS_")]


# --- Refusals: two scalars under one name -------------------------------------------------


@pytest.fixture(scope="module")
def scalar_pass_inputs():
    """Return what ``add_scalar_parameters`` was given in a conversion of sg005 dive 1:
    the dataset before the scalars are added, the extracted scalars, and the name mapping."""
    captured = {}
    original = _pipeline.add_scalar_parameters

    def recording(ds_og1, extracted, og1_mapping):
        captured["inputs"] = (ds_og1.copy(), extracted, og1_mapping.copy())
        return original(ds_og1, extracted, og1_mapping)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_pipeline, "add_scalar_parameters", recording)
        _convert.convert(
            readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
        )
    return captured["inputs"]


def test_two_scalars_mapped_to_one_name_are_refused(scalar_pass_inputs):
    """Two basestation scalars given the same output name raise; neither overwrites the other."""
    ds, extracted, mapping = scalar_pass_inputs
    mapping = mapping.copy()
    pair = mapping["original_name"].isin(["log_MASS", "sg_cal_mass"])
    assert pair.sum() == 2
    mapping.loc[pair, "OG1_name"] = "GLIDER_MASS"
    with pytest.raises(ValueError, match="both map to 'GLIDER_MASS'"):
        _pipeline.add_scalar_parameters(ds, extracted, mapping)


def test_scalar_does_not_replace_another_variable(scalar_pass_inputs, monkeypatch):
    """A scalar whose vocabulary name is already taken by a variable from another source
    raises, and does not replace it."""
    ds, extracted, mapping = scalar_pass_inputs
    assert ds["TEMP"].attrs["original_name"] == "temperature"
    mapping = mapping[mapping["original_name"] != "log_MASS"]
    monkeypatch.setitem(vocabularies.standard_names, "log_MASS", "TEMP")
    with pytest.raises(ValueError, match="'TEMP' already exists"):
        _pipeline.add_scalar_parameters(ds, extracted, mapping)


def test_mapping_with_a_repeated_basestation_name_is_refused(scalar_pass_inputs):
    """The name mapping must list each basestation variable once."""
    ds, extracted, mapping = scalar_pass_inputs
    doubled = pd.concat([mapping, mapping.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique original names"):
        _pipeline.add_scalar_parameters(ds, extracted, doubled)


def test_scalar_in_one_dive_and_array_in_another_is_refused():
    """A variable that is one value in dive 1 and an array in dive 2 raises."""
    first, second = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    second = second.assign(log_MASS=second["log_MASS"].expand_dims("n"))
    with pytest.raises(ValueError, match="'log_MASS' is scalar in one dataset"):
        _pipeline.extract_scalar_parameters([first, second])
