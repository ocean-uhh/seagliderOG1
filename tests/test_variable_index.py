"""The variable index: every basestation variable once, input beside output.

On the bundled sg271 sample (basestation 3.0.6, dives 1-3), whose raw files are read here
directly to check what the conversion record says about them.
"""

import collections
import pathlib

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, writers
from seagliderOG1.reports import _index, _record

ROOT = pathlib.Path(__file__).resolve().parents[1]
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory):
    path = _convert._convert_mission(SG271, tmp_path_factory.mktemp("sg271_index"))
    ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
    ledger = _record.conversion_ledger(ds)
    record = _record.conversion_sidecar(path)
    rows = _index.variable_rows(ds, ledger, record)
    yield ds, ledger, record, {r["basestation"] or r["name"]: r for r in rows}, rows
    ds.close()


def test_every_input_once_and_the_fates_add_up(sg271):
    """Each basestation input is one entry, and the entries with a basestation name number
    the recorded input count; none is unattributed."""
    _ds, ledger, record, _by_name, rows = sg271
    inputs = [r["basestation"] for r in rows if r["basestation"]]
    assert len(inputs) == len(set(inputs)) == ledger["input_variable_count"]
    assert set(inputs) == set(record["input_variables"])
    assert "unattributed" not in {r["fate"] for r in rows}


def test_input_record_matches_the_raw_files(sg271):
    """The record's value count and dtype for ``temperature`` are those of the three files."""
    _ds, _ledger, record, _by_name, _rows = sg271
    total = 0
    for path in sorted(SG271.glob("p*.nc")):
        with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as raw:
            total += int(np.isfinite(raw["temperature"].values).sum())
    entry = record["input_variables"]["temperature"]
    assert entry["values"] == total
    assert entry["dtype"] == "float64"
    assert entry["dimensions"] == ["ctd_data_point"]


def test_unit_factor_and_downcast_are_marked(sg271):
    """``speed`` becomes GLIDE_SPEED in m s-1 (x0.01), stored as float32; both are steps."""
    row = sg271[3]["speed"]
    assert (row["name"], row["fate"]) == ("GLIDE_SPEED", "renamed")
    assert (row["units_in"], row["units_out"], row["factor"]) == ("cm/s", "m s-1", 0.01)
    assert row["values_in"] == row["values_out"]
    texts = {m["text"] for m in row["marks"] if m["kind"] == "step"}
    assert texts == {"×0.01", "float64 → float32"}


def test_per_dive_numbers_stored_as_text_are_a_loss(sg271):
    """C_VBD changes between dives, so it is written as JSON text: marked as a loss."""
    row = sg271[3]["log_C_VBD"]
    assert row["dtype_out"] == "text (JSON)"
    assert {"kind": "loss", "text": "numbers → JSON text"} in row["marks"]


def test_qc_flag_count_differs_on_the_shared_axis(sg271):
    """A CTD QC flag is set at every data point of the shared axis, not only the CTD ones,
    so its value count in and out differ (the page highlights this)."""
    ds, _ledger, _record_, by_name, _rows = sg271
    row = by_name["temperature_qc"]
    assert row["values_out"] == ds.sizes["N_MEASUREMENTS"]
    assert row["values_in"] < row["values_out"]


def test_derived_variables_list_inputs_or_say_not_recorded(sg271):
    """POTDENS0 lists its inputs; PHASE's are not in the ledger, so it says so instead."""
    by_name = sg271[3]
    assert by_name["POTDENS0"]["inputs"] == [
        "ctd_pressure",
        "latitude",
        "longitude",
        "salinity",
        "temperature",
    ]
    phase = by_name["PHASE"]
    assert phase["inputs"] is None
    assert {"kind": "gap", "text": "inputs not recorded"} in phase["marks"]
    assert phase["method"]


def test_time_inputs_are_consumed(sg271):
    """Every time variable TIME was built from is consumed, not written."""
    by_name = sg271[3]
    for source in by_name["TIME"]["inputs"]:
        assert by_name[source]["fate"] == "consumed"
        assert by_name[source]["name"] == ""


def test_subsystems(sg271):
    """Flight-model, instrument and prefix subsystems are all used on sg271."""
    counts = collections.Counter(r["subsystem"] for r in sg271[4])
    assert {"flight", "sensors", "GPS", "G&C", "calibration", "log"} <= set(counts)
    assert sg271[3]["legato_temp"]["subsystem"] == "sensors"


def test_without_a_record_the_inputs_are_none(sg271):
    """An older record (no input_variables) leaves the input columns None, not guessed."""
    ds, ledger, _record_, _by_name, _rows = sg271
    rows = _index.variable_rows(ds, ledger, None)
    speed = next(r for r in rows if r["basestation"] == "speed")
    assert speed["units_in"] is None and speed["values_in"] is None


def test_variables_page_lists_every_variable(tmp_path):
    """The page written with the report names every basestation input and links back to the
    conversion page; it is current on its own nav pill."""
    path = _convert._convert_mission(SG271, tmp_path, report=True)
    page = writers.page_path(path, "variables")
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        record = _record.conversion_sidecar(path)
        for name in record["input_variables"]:
            assert f'data-names="{name} ' in html, name
        assert ds.attrs["conversion_input_variable_count"] == len(
            record["input_variables"]
        )
    assert f'href="{writers.conversion_path(path, ".html").name}"' in html
    assert 'title="current page">Variables<' in html
    conversion = writers.conversion_path(path, ".html").read_text(encoding="utf-8")
    assert f'href="{page.name}"' in conversion


def test_text_variables_count_the_same_in_and_out(sg271):
    """Input and output counts use one rule, so a passed-through text variable kept whole
    has equal counts (no false "values differ" highlight)."""
    _ds, _ledger, _record_, _by_name, rows = sg271
    text = [
        r
        for r in rows
        if r["fate"] == "passthrough"
        and r["dtype_out"] == "text"
        and r["storage"] != "per_dive_scalar"
        and r["values_in"] is not None
        and r["dimension"] != "scalar"
    ]
    assert text
    differ = {
        r["basestation"]: (r["values_in"], r["values_out"])
        for r in text
        if r["values_in"] != r["values_out"]
    }
    assert not differ


def test_count_values_on_text_from_a_dive_file():
    """Variable-length text counts each non-blank string; blank and None do not count."""
    with xr.open_dataset(
        sorted(SG271.glob("p*.nc"))[0], engine="netcdf4", decode_timedelta=False
    ) as raw:
        values = raw["sg_cal_calibcomm"].values
    assert _convert.count_values(values) == 1
    mixed = np.array(["a", "", " ", None, b"b"], dtype=object)
    assert _convert.count_values(mixed) == 2


def test_no_adopted_units_mark_without_a_record(sg271):
    """Without the record the input units are unknown, so no units mark is claimed."""
    ds, ledger, _record_, _by_name, _rows = sg271
    rows = _index.variable_rows(ds, ledger, None)
    texts = {m["text"] for r in rows for m in r["marks"]}
    assert "units adopted" not in texts
    assert "unit spelling not kept" not in texts
