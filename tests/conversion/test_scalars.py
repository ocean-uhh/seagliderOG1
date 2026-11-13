"""One-value basestation variables: stored as scalars when they agree across dives, as
per-dive JSON when they change.

Data: the sg005 demo conversion.
"""

import pathlib

from seagliderOG1 import _convert, readers

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
