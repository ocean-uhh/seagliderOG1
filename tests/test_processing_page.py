"""The Processing page's steps and the Conversion page's summaries drawn from them.

On the bundled sg271 sample (basestation 3.0.6, dives 1-3).
"""

import pathlib

import pytest
import xarray as xr

from seagliderOG1 import _convert, writers
from seagliderOG1.reports import _index, _record, processing

ROOT = pathlib.Path(__file__).resolve().parents[1]
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271(tmp_path_factory: pytest.TempPathFactory):
    path = _convert._convert_mission(
        SG271, tmp_path_factory.mktemp("sg271_processing"), report=True
    )
    ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
    ledger = _record.conversion_ledger(ds)
    record = _record.conversion_sidecar(path)
    rows = _index.variable_rows(ds, ledger, record)
    steps = processing.processing_steps(ds, ledger, record, rows)
    yield path, ds, record, rows, steps
    ds.close()


def test_steps_are_numbered_in_stage_order(sg271):
    """Steps are numbered 1..n, and the stages appear in the order of STAGES."""
    steps = sg271[4]
    assert [s["number"] for s in steps] == list(range(1, len(steps) + 1))
    order = [key for key, _label in processing.STAGES]
    seen = [s["stage"] for s in steps]
    assert seen == sorted(seen, key=order.index)
    assert set(seen) == set(order)


def test_unrecorded_steps_make_their_stage_amber(sg271):
    """A step the file does not record marks its stage; a stage whose steps are all recorded
    is ok."""
    steps = sg271[4]
    states = {s["key"]: s["state"] for s in processing.stage_states(steps)}
    assert states["store"] == "gap"  # float32 storage is not recorded
    assert states["write"] == "ok"


def test_step_counts_match_the_index(sg271):
    """The conversion and downcast steps count the same variables the index marks."""
    _path, _ds, _record_, rows, steps = sg271
    by_step = {s["step"]: s for s in steps}
    factors = sum(1 for r in rows if r["factor"] not in (None, 1) and r["basestation"])
    assert by_step["convert units"]["variables"].startswith(f"{factors}: ")
    downcast = sum(
        1 for r in rows if any(m["text"] == "float64 → float32" for m in r["marks"])
    )
    assert by_step["storage types"]["variables"].startswith(f"{downcast}: ")


def test_losses_on_sg271(sg271):
    """sg271 loses its trajectory variable, numbers to JSON text and unit spellings; what the
    conversion does not count says so (None)."""
    _path, _ds, record, rows, _steps = sg271
    found = {loss["loss"]: loss for loss in processing.losses(record, rows)}
    assert found["Variables not written"]["examples"] == ["trajectory"]
    assert found["Per-dive numbers stored as JSON text"]["count"] > 0
    assert "log_C_VBD" in found["Per-dive numbers stored as JSON text"]["examples"]
    assert found["Unit spelling replaced (factor 1)"]["count"] > 0
    assert found["Exact-duplicate records dropped"]["count"] is None


def test_flight_panel_flags_json_parameters(sg271):
    """C_VBD is per-dive JSON text, so gliderflightOG1 cannot read it; PITCH it can."""
    flight = {f["basestation"]: f for f in processing.flight_rows(sg271[3])}
    assert flight["log_C_VBD"]["ready"] == "no: JSON text"
    assert flight["eng_pitchAng"]["ready"] == "yes"
    assert flight["eng_pitchAng"]["row"]["name"] == "PITCH"


def test_traced_variable_is_speed(sg271):
    """speed is traced to GLIDE_SPEED, through the rename and the unit conversion."""
    row, trace = processing.traced_variable(sg271[3], sg271[4])
    assert (row["basestation"], row["name"]) == ("speed", "GLIDE_SPEED")
    steps = [t["step"] for t in trace]
    assert steps[:2] == ["rename to OG1", "convert units"]
    assert trace[1]["after"].startswith("m s-1, values ×0.01")


def test_pages_written_and_linked(sg271):
    """The Processing page is written with the report, highlights unrecorded steps, and the
    Conversion page links its stage pills to it."""
    path = sg271[0]
    page = writers.page_path(path, "processing")
    html = page.read_text(encoding="utf-8")
    assert 'id="step-1"' in html and 'class="not-recorded"' in html
    conversion = writers.conversion_path(path, ".html").read_text(encoding="utf-8")
    assert f'href="{page.name}#step-1"' in conversion
    assert '<section id="flight">' in conversion
