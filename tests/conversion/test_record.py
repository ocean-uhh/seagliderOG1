"""The conversion record: the ledgers written into the file (conversion_* globals) and the
<id>_conversion.json sidecar beside it.

Data: the sg005 demo conversion.
"""

import json
import pathlib
import warnings

import netCDF4
import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, _pipeline, readers, writers
from seagliderOG1.reports import _record

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]
_SG005 = parent_dir / "data/demo_sg005"


# --- Ledgers in the file ------------------------------------------------------------------


def test_conversion_ledger_parses_the_file():
    """conversion_ledger returns the parsed ledger; a pre-ledger file raises MetadataError."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ledger = _record.conversion_ledger(_convert.convert(datasets))
    assert set(ledger) == {
        "dimensions",
        "derived",
        "dropped",
        "removed",
        "input_variable_count",
        "attribute_sources",
        "history",
        "scalar_parameters",
    }
    assert ledger["dimensions"]["sg_data_point"]["fate"] == "backbone"
    # derived is a map {name: [source basestation names]}; removed is the drop list, empty
    # now that every basestation variable is retained.
    assert isinstance(ledger["derived"], dict)
    assert ledger["input_variable_count"] > 0
    assert ledger["removed"] == []
    # Derived variables record their basestation sources: every merged dimension's time
    # variable folds into the shared TIME axis; TIME_GPS records the GPS clock separately.
    assert set(ledger["derived"]["TIME"]) == {
        "ctd_time",
        "time",
        "gc_st_secs",
        "log_gps_time",
    }
    assert ledger["derived"]["TIME_GPS"] == ["log_gps_time"]
    per_dive = [
        name
        for name, entry in ledger["scalar_parameters"].items()
        if entry["storage"] == "per_dive_scalar"
    ]
    assert per_dive
    assert sorted(ledger["scalar_parameters"][per_dive[0]]["dives"]) == [1, 2]
    try:
        _record.conversion_ledger(
            readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)[0]
        )
    except _convert.MetadataError:
        pass
    else:
        raise AssertionError("expected MetadataError on a pre-ledger file")


def test_conversion_attribute_sources_ledger():
    """Every written global is in exactly one ledger category; an override shows up."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(
        datasets,
        deployment={"id": "custom_id"},
        global_attributes={"program": "MOOSE"},
    )
    ledger = json.loads(ds.attrs["conversion_attribute_sources"])
    written = [k for k in ds.attrs if k != "conversion_attribute_sources"]
    categorised = [name for names in ledger.values() for name in names]
    assert sorted(categorised) == sorted(written)  # covers every written global
    assert len(categorised) == len(set(categorised))  # each in exactly one category
    assert "id" in ledger["overridden"]  # deployment.id replaced the derived id
    assert "contributor_name" in ledger["mixed"]  # config/file blend, not guessed
    assert "title" in ledger["package"]
    assert "start_date" in ledger["derived"]


def test_conversion_dimensions_ledger():
    """conversion_dimensions records each dimension's fate and the variables it carried."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    dims = json.loads(ds.attrs["conversion_dimensions"])
    # The CTD dimension is the backbone that becomes N_MEASUREMENTS.
    assert dims["sg_data_point"]["fate"] == "backbone"
    # gps_info is merged (its fixes are placed on the backbone by a dedicated path),
    # not skipped, and its basestation variables are named.
    assert dims["gps_info"]["fate"] == "merged"
    assert "log_gps_lat" in dims["gps_info"]["variables"]
    # A skipped dimension leaves nothing in the file, so its variables are recorded here.
    skipped = {d: info for d, info in dims.items() if info["fate"] == "skipped"}
    assert skipped
    assert all(info["variables"] for info in skipped.values())


def test_reconciliation_fates_sum_to_input_count():
    """Every basestation variable has exactly one fate; the six buckets sum to the input count."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    inputs = {str(v) for ds in datasets for v in ds.variables}
    ds = _convert.convert(datasets)
    ledger = _record.conversion_ledger(ds)
    renamed = {
        str(ds[n].attrs["original_name"])
        for n in ds.variables
        if ds[n].attrs.get("original_name") not in (None, n)
    }
    passed = {str(n) for n in ds.variables if ds[n].attrs.get("original_name") == n}
    consumed = {s for sources in ledger["derived"].values() for s in sources}
    removed = set(ledger["removed"])
    dropped = set(ledger["dropped"])
    skipped = {
        v
        for info in ledger["dimensions"].values()
        if info["fate"] == "skipped"
        for v in info["variables"]
    }
    # One fate per name, resolved in the same priority order as the reconciliation page.
    seen: set[str] = set()
    total = 0
    for names in (renamed, passed, consumed, removed, dropped, skipped):
        total += len(names - seen)
        seen |= names
    assert total == ledger["input_variable_count"] == len(inputs)
    # gc_event is merged (its variables reach the output), so its time variable feeds the
    # shared TIME axis; it is consumed, not skipped.
    assert "gc_st_secs" in consumed and "gc_st_secs" not in skipped


def test_dimension_fate_agrees_with_output_variables():
    """A dimension's fate is read from the output: merged iff a variable survives on it."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    dims = _record.conversion_ledger(ds)["dimensions"]
    in_output = {
        str(ds[n].attrs["original_dimension"])
        for n in ds.variables
        if "original_dimension" in ds[n].attrs
    }
    for dim, info in dims.items():
        if info["fate"] in ("backbone", "merged"):
            assert dim in in_output, (
                f"{dim} is {info['fate']} but no output variable carries it"
            )
        else:
            assert dim not in in_output, (
                f"{dim} is skipped but a variable survived on it"
            )
    # gc_event in demo_sg005 is merged by this rule (its gc_* variables reach the axis).
    assert dims["gc_event"]["fate"] == "merged"


def test_derived_sources_stamp_never_reaches_the_file(tmp_path: pathlib.Path) -> None:
    """The transient _derived_sources attr is consumed into the ledger, not written to disk."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    assert not [
        n for n in ds.variables if _pipeline.DERIVED_SOURCES_ATTR in ds[n].attrs
    ]
    out = tmp_path / "og1.nc"
    writers.write(ds, str(out), overwrite=True)
    reopened = xr.open_dataset(str(out), engine="netcdf4", decode_timedelta=False)
    try:
        leaked = [
            n
            for n in reopened.variables
            if _pipeline.DERIVED_SOURCES_ATTR in reopened[n].attrs
        ]
    finally:
        reopened.close()
    assert not leaked


def test_skipped_dimension_warning_names_only_absent_dimensions(caplog):
    """The warning is read from the ledger: on sg005 only 'trajectory' is skipped."""
    import logging

    with caplog.at_level(logging.WARNING, logger="seagliderOG1.convert"):
        _convert.convert(
            readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
        )
    lines = [
        r.getMessage()
        for r in caplog.records
        if "not in the OG1 dataset" in r.getMessage()
    ]
    assert lines == [
        "Dimensions not in the OG1 dataset: ['trajectory']; their variables are not written (see conversion_dimensions)."
    ]


# --- Presence across dives ----------------------------------------------------------------


def test_presence_by_dive_on_sg005() -> None:
    """sg005 shows three patterns: every dive, valid from dive 2, and dive 4 only."""
    presence = _convert._presence_by_dive(readers.read_mission(str(_SG005)))
    assert presence["dives"] == [1, 2, 3, 4, 5]
    current = presence["variables"]["depth_avg_curr_east"]
    assert current == {"present": [[1, 5]], "valid": [[2, 5]]}  # empty until dive 2
    assert presence["variables"]["log_ALTIM_BOTTOM_PING"]["present"] == [[4, 4]]
    labels = [row["label"] for row in _record.presence_patterns(presence)]
    assert labels == ["every dive", "from dive 2", "dive 4 only"]
    assert _record.presence_summary(presence) == (
        "343 variables over 5 dives; 338 on every dive, 5 on some (3 patterns)"
    )


def test_presence_pattern_labels() -> None:
    """The run classifier names every pattern class (pure logic; sg005 lacks until/range)."""
    dives = [1, 2, 3, 4, 5, 7]  # dive 6 missing: runs follow file order, not numbering
    label = _record._run_label
    assert label([[1, 7]], dives) == "every dive"
    assert label([[3, 7]], dives) == "from dive 3"
    assert label([[1, 4]], dives) == "until dive 4"
    assert label([[2, 4]], dives) == "dives 2–4"
    assert label([[5, 5]], dives) == "dive 5 only"
    assert label([[1, 2], [5, 7]], dives) == "sporadic"
    assert label([], dives) == "never"
    assert _convert._dive_runs([True, True, False, True], [1, 2, 3, 4]) == [
        [1, 2],
        [4, 4],
    ]


def test_presence_summary_none_when_dives_agree() -> None:
    """No summary line when every variable has values on every dive."""
    presence = {
        "dives": [1, 2],
        "variables": {"a": {"present": [[1, 2]], "valid": [[1, 2]]}},
    }
    assert _record.presence_summary(presence) is None


def test_presence_counts_blank_text_and_nat_as_no_values() -> None:
    """Validity tests times for NaT and text for blanks, not only floats (pure logic)."""
    nat = np.array(["NaT"], dtype="datetime64[ns]")
    dives = [
        xr.Dataset(
            {
                "t": ("x", nat),
                "s": ("x", np.array(["  "])),
                # object dtype: how netCDF4 variable-length text decodes (None/blank = no value)
                "o": ("x", np.array([None], dtype=object)),
            },
            attrs={"dive_number": 1},
        ),
        xr.Dataset(
            {
                "t": ("x", np.array(["2008-06-06"], dtype="datetime64[ns]")),
                "s": ("x", np.array(["on"])),
                "o": ("x", np.array(["on"], dtype=object)),
            },
            attrs={"dive_number": 2},
        ),
    ]
    variables = _convert._presence_by_dive(dives)["variables"]
    for name in ("t", "s", "o"):
        assert variables[name] == {"present": [[1, 2]], "valid": [[2, 2]]}, name


def test_convert_record_leaves_out_a_rejected_dive() -> None:
    """A dive the converter rejects (no ctd_time) is not recorded as contributing."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 3)
    datasets[1] = datasets[1].drop_vars("ctd_time")
    record: dict = {}
    _convert.convert(datasets, record=record)
    assert record["presence"]["dives"] == [1, 3]
    assert [entry["dive"] for entry in record["inputs"]] == [1, 3]


# --- The sidecar --------------------------------------------------------------------------


def test_process_mission_writes_the_sidecar_bound_to_the_file(
    tmp_path: pathlib.Path,
) -> None:
    """The sidecar sits beside the file, binds by id/date_created, and adds nothing to it."""
    path = _convert._convert_mission(_SG005, tmp_path, dives=(1, 2))
    sidecar = _record.conversion_sidecar(path)
    assert sidecar is not None
    assert [entry["dive"] for entry in sidecar["inputs"]] == [1, 2]
    assert all(entry["path"].startswith("p005") for entry in sidecar["inputs"])
    assert sidecar["presence"]["dives"] == [1, 2]
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        assert sidecar["id"] == ds.attrs["id"]
        assert not [k for k in ds.attrs if "presence" in k or "sidecar" in k]


def test_sidecar_inputs_record_dimension_lengths_and_global_count(
    tmp_path: pathlib.Path,
) -> None:
    """Each input record carries the file's dimension lengths and global-attribute count."""
    datasets = readers.read_mission(str(_SG005), 1, 2)
    path = _convert._convert_mission(_SG005, tmp_path, dives=(1, 2))
    inputs = _record.conversion_sidecar(path)["inputs"]
    by_dive = {entry["dive"]: entry for entry in inputs}
    for ds in datasets:
        entry = by_dive[int(ds.attrs["dive_number"])]
        assert entry["dimensions"] == {str(n): int(v) for n, v in ds.sizes.items()}
        assert entry["dimensions"]["sg_data_point"] > 0
        assert entry["n_globals"] == len(ds.attrs)

    # A sidecar left beside a deleted file is stale: it is replaced, not refused.
    path.unlink()
    assert _convert._convert_mission(_SG005, tmp_path, dives=(1, 1)) == path
    assert _record.conversion_sidecar(path)["presence"]["dives"] == [1]


def test_sidecar_records_tracking_id_and_hash_and_warns_on_change(
    tmp_path: pathlib.Path,
    sg005_og1_copy: pathlib.Path,
) -> None:
    """The sidecar carries the file's tracking_id and SHA-256; a changed file warns."""
    path = sg005_og1_copy
    sidecar = json.loads(
        writers.conversion_path(path, ".json").read_text(encoding="utf-8")
    )
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        assert sidecar["tracking_id"] == ds.attrs["tracking_id"]
        # The writer's tracking_id is in the source ledger, so it names every global.
        ledger = json.loads(ds.attrs["conversion_attribute_sources"])
        assert "tracking_id" in ledger["derived"]
        named = [name for names in ledger.values() for name in names]
        assert sorted(named) == sorted(set(ds.attrs) - {"conversion_attribute_sources"})
    assert sidecar["sha256"] == writers.file_sha256(path)
    with netCDF4.Dataset(path, "a") as nc:
        nc.setncattr("comment", "edited by hand")
    # Hashing reads the whole file, so it runs only when asked (the report verb).
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _record.conversion_sidecar(path) is not None
    with pytest.warns(UserWarning, match="has changed since"):
        assert _record.conversion_sidecar(path, verify=True) is not None


def test_conversion_sidecar_ignores_another_conversion(
    tmp_path: pathlib.Path, sg005_og1_copy: pathlib.Path
) -> None:
    """A sidecar whose tracking_id does not match the file is warned about and ignored."""
    path = sg005_og1_copy
    sidecar_file = writers.conversion_path(path, ".json")
    payload = json.loads(sidecar_file.read_text(encoding="utf-8"))
    payload["tracking_id"] = "not-this-file"
    sidecar_file.write_text(json.dumps(payload))
    with pytest.warns(UserWarning, match="belongs to another conversion"):
        assert _record.conversion_sidecar(path) is None
    # A sidecar written before tracking_id binds by id + date_created, as it did.
    del payload["tracking_id"]
    sidecar_file.write_text(json.dumps(payload))
    assert _record.conversion_sidecar(path) is not None


def test_conversion_sidecar_ignores_an_unreadable_or_foreign_sidecar(
    tmp_path: pathlib.Path,
    sg005_og1_copy: pathlib.Path,
) -> None:
    """A truncated sidecar, or one of another schema, is warned about and ignored."""
    path = sg005_og1_copy
    sidecar_file = writers.conversion_path(path, ".json")
    payload = json.loads(sidecar_file.read_text(encoding="utf-8"))
    sidecar_file.write_text(json.dumps({**payload, "schema": 99}))
    with pytest.warns(UserWarning, match="not a schema-1"):
        assert _record.conversion_sidecar(path) is None
    sidecar_file.write_text('{"schema": 1, "id"')
    with pytest.warns(UserWarning, match="could not be read"):
        assert _record.conversion_sidecar(path) is None
