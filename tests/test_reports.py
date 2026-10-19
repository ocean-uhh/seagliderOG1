"""Tests for the owned conversion-page builders in ``reports/conversion.py``.

These exercise the owned row builders directly (no HTML render) against a real OG1 dataset
converted from ``data/demo_sg005``, so the reconciliation identity and the per-section row
logic are checked once each.
"""

import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import (  # noqa: E402  # import after sys.path bootstrap
    convert,
    readers,
    vocabularies,
)
from seagliderOG1.reports import conversion  # noqa: E402

DATA = str(parent_dir / "data/demo_sg005")


def _dataset():
    """Return the demo_sg005 OG1 dataset (dives 1-2)."""
    return convert.to_og1(readers.read_mission(DATA, 1, 2))


def test_dimension_rows_variables_sum_to_input_count():
    """The Dimensions table (dimensions + the scalar row) accounts for every input variable."""
    ledger = convert.conversion_ledger(_dataset())
    rows = conversion._dimension_rows(ledger)
    assert sum(r["n"] for r in rows) == ledger["input_variable_count"]
    # The scalar row is present and carries the storage split in its variable list.
    scalar = next(r for r in rows if r["dimension"] == "(scalar)")
    assert scalar["n"] == len(ledger["scalar_parameters"])
    assert "constant" in scalar["variables"] and "per-dive" in scalar["variables"]


def test_derived_rows_input_sources_equal_the_consumed_set():
    """The basestation sources named across derived rows equal the reconciliation consumed set."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows = conversion._derived_rows(ds, ledger)
    # Sources shown on the page that are real basestation inputs (not the "(computed)" rows).
    inputs = {str(v) for d in readers.read_mission(DATA, 1, 2) for v in d.variables}
    shown = {
        token.strip()
        for r in rows
        if r["sources"] != "(computed)"
        for token in str(r["sources"]).split(",")
    }
    consumed = {s for sources in ledger["derived"].values() for s in sources}
    assert shown == consumed
    assert shown <= inputs  # every shown source is a real basestation variable
    # The four time sources are findable (gc_event is merged, so gc_st_secs is among them).
    assert {"ctd_time", "time", "gc_st_secs", "log_gps_time"} <= shown


def _scalar_rows(ds, ledger):
    """Return the scalar rows the page builds (decoded values applied), for the group tests."""
    from seagliderOG1.reports import design
    from seagliderOG1.reports._vendored import nc_tables

    all_scalars, _ = nc_tables.scalars_rows(
        ds, exclude=design.is_sensor, original_name_attrs=design.ORIGINAL_NAME_ATTRS
    )
    rows = [r for r in all_scalars if r["name"] in set(ledger["scalar_parameters"])]
    conversion._apply_decoded_scalar_values(rows, ledger["scalar_parameters"])
    return rows


def test_scalar_groups_partition_and_sum():
    """Each scalar lands in exactly one of the four groups; the counts sum to the total."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows = _scalar_rows(ds, ledger)
    groups = conversion._scalar_groups(rows)
    assert sum(len(g["rows"]) for g in groups) == len(rows)
    # No row appears twice across groups.
    names = [row["name"] for g in groups for row in g["rows"]]
    assert len(names) == len(set(names))
    # The calibration group is named for the basestation block and rendered monospace.
    calib = next(g for g in groups if g["title"] == "sg_calib_constants")
    assert calib["mono"] is True


def test_coverage_computed_matches_the_data_on_demo():
    """Recomputed coverage agrees with the stated geospatial/time globals within tolerance."""
    ds = _dataset()
    computed = conversion._coverage_computed(ds)
    # Every geospatial and time-coverage bound is present and within tolerance (not amber).
    assert {
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "time_coverage_start",
        "time_coverage_end",
    } <= set(computed)
    assert all(not entry["over"] for entry in computed.values())


def test_variable_groups_put_derived_no_dimension_last():
    """The converter-built (no original dimension) group is titled and placed last, all derived."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    groups, _source = conversion._variable_groups_by_original_dimension(ds)
    title, rows = groups[-1]
    assert title == "Derived (no basestation dimension)"
    assert all(row["name"] in ledger["derived"] for row in rows)


def test_time_coverage_span_is_compact_same_day():
    """A same-day span states the date once and drops the seconds."""
    assert (
        conversion._time_coverage_span("20080606T180256", "20080606T203001")
        == "2008-06-06 18:02 → 20:30"
    )
    assert conversion._time_coverage_span(None, "20080606T203001") == ""


def test_global_attribute_groups_are_the_five_conventions_no_other():
    """Globals group into the five vendored conventions; nothing falls to Other on demo."""
    from seagliderOG1.reports import design
    from seagliderOG1.reports._vendored import nc_tables

    ds = _dataset()
    groups, _source = nc_tables.globals_rows(
        ds,
        extras=design.ATTR_GROUP_EXTRAS,
        exclude=["history", "conversion_attribute_sources"],
    )
    titles = [title for title, _rows in groups]
    assert titles == [
        "Identity & discovery",
        "Spatiotemporal coverage",
        "People & institutions",
        "Rights & access",
        "Provenance & processing",
    ]
    assert "Other" not in titles  # every global is placed by meaning


def test_requirement_summary_counts_the_mandatory_tier():
    """The requirement line reports every mandatory global present on demo (not amber)."""
    ds = _dataset()
    text, amber = conversion._requirement_summary(ds)
    assert text.startswith("OG1 requirement: mandatory 9/9 present")
    assert amber is False


def test_masthead_meta_names_platform_not_input_output_counts():
    """The masthead carries the platform/serial; the input → output counts moved to §1."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    meta = dict(conversion._masthead_meta(ds, ledger))
    assert "sg005" in meta["Platform"]
    assert (
        "Inputs → outputs" not in meta
    )  # now the first row of the Before → after table


def test_per_dive_scalar_value_is_decoded_not_json():
    """A per-dive scalar's Value shows decoded per-dive values, not the raw JSON string."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows = _scalar_rows(ds, ledger)
    per_dive = [
        name
        for name, e in ledger["scalar_parameters"].items()
        if e["storage"] == "per_dive_scalar"
    ]
    row = next(r for r in rows if r["name"] == per_dive[0])
    assert row["value"].startswith("dive 1:")
    assert '{"dives"' not in row["value"]  # the raw serialization is not in the cell


def test_fate_histogram_draws_one_bar_per_fate():
    """The fate histogram drawer returns a figure with one bar per fate, or None if empty."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows, _caption = conversion._reconciliation(ds, ledger)
    fig = conversion.draw_fate_histogram(rows[:-1])  # drop the input-total row
    assert fig is not None
    ax = fig.axes[0]
    assert len(ax.patches) == len(rows) - 1  # one bar per fate
    assert conversion.draw_fate_histogram([]) is None


def test_history_rows_are_ordinal_numbered():
    """History rows carry a 1-based ordinal in the first column, in file order."""
    ledger = convert.conversion_ledger(_dataset())
    rows = conversion._history_rows(ledger)
    assert rows  # at least the conversion line
    assert [r[0] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]


def test_page_presence_section_with_and_without_sidecar(tmp_path) -> None:
    """The page shows the pattern table from the sidecar, and says so when it is missing."""
    import pathlib

    from seagliderOG1 import convert, writers

    path = convert.process_mission(
        pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005",
        tmp_path,
    )
    html = conversion.render_conversion(path)
    assert "Presence across dives" in html
    assert "from dive 2" in html and "dive 4 only" in html
    assert "343 variables over 5 dives" in html
    writers.conversion_path(path, ".json").unlink()
    html = conversion.render_conversion(path)
    assert "sidecar not found" in html


def test_presence_strips_one_row_per_pattern() -> None:
    """The strip figure has two panels with one row per contiguous pattern."""
    from seagliderOG1 import convert

    presence = {
        "dives": [1, 2, 3],
        "variables": {
            "a": {"present": [[1, 3]], "valid": [[1, 3]]},
            "b": {"present": [[1, 3]], "valid": [[2, 3]]},
            "c": {"present": [[1, 1], [3, 3]], "valid": [[1, 1], [3, 3]]},
        },
    }
    patterns = convert.presence_patterns(presence)
    present, valid, labels, has_density = conversion._strip_matrix(patterns)
    assert present.shape == valid.shape == (3, 3)
    assert labels[-1].startswith("sporadic and other") and has_density
    assert valid[1].tolist() == [0, 1, 1]  # "from dive 2": present on 1, valid from 2
    fig = conversion.draw_presence_strips(patterns, [1, 2, 3])
    assert fig is not None and len(fig.axes) == 3  # two panels + the density colorbar
    assert conversion.draw_presence_strips([], []) is None


def test_reconciliation_rows_carry_a_meaning() -> None:
    """Every fate row has Meaning text; the basestation-input total row has none."""
    ds = _dataset()
    rows, _caption = conversion._reconciliation(ds, convert.conversion_ledger(ds))
    assert all(row[2] for row in rows[:-1])  # each fate explains itself
    assert rows[-1][2] == ""  # the input-total row carries no meaning


def test_dimension_rows_show_samples_in_from_the_sidecar() -> None:
    """Samples in is the sidecar sum per dimension; "—" for the scalar row and without it."""
    ledger = convert.conversion_ledger(_dataset())
    rows = conversion._dimension_rows(ledger, {"sg_data_point": 2213})
    sg = next(r for r in rows if r["dimension"] == "sg_data_point")
    assert sg["samples_in"] == "2,213"
    assert next(r for r in rows if r["dimension"] == "(scalar)")["samples_in"] == "—"
    assert all(r["samples_in"] == "—" for r in conversion._dimension_rows(ledger))


def test_variable_group_caption_states_the_baseline() -> None:
    """With the sidecar the baseline is exact (k of N); without it the group's best stands in."""
    rows = [{"valid_pct": 90.4}, {"valid_pct": 12.0}]
    exact = conversion._variable_group_caption(
        "sg_data_point", rows, {"sg_data_point": 2213}, 2449
    )
    assert "sg_data_point supplied 2,213 of 2,449 samples (90.4 %)" in exact
    estimate = conversion._variable_group_caption("sg_data_point", rows, {}, 2449)
    assert "at least 90.4 %" in estimate
    derived = conversion._variable_group_caption(
        conversion._NO_DIMENSION_GROUP, rows, {}, 2449
    )
    assert "Converter-built" in derived


def test_og1_required_rows_all_present_on_demo() -> None:
    """The OG1-required tier lists the checker's 14 names + the dimension, all present on demo."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows, caption, incomplete = conversion._og1_required_rows(
        ds, ledger, {"LATITUDE": 91.0}
    )
    assert not incomplete
    assert "14 of 14 variables present" in caption
    names = {r["name"] for r in rows}
    assert {"LATITUDE", "LONGITUDE", "DEPTH", "TIME_GPS"} <= names
    # The required-dimension row carries the same orig_var/orig_dim fields the table reads.
    dim_row = next(r for r in rows if str(r["name"]).startswith("N_MEASUREMENTS"))
    assert dim_row["orig_var"] == "—" and dim_row["orig_dim"] == "—"
    lat = next(r for r in rows if r["name"] == "LATITUDE")
    assert lat["present"] is True
    assert lat["valid"] == "91.0"  # pulled from the passed valid-by-name map
    assert lat["orig_var"] == "latitude"  # basestation source variable
    assert lat["orig_dim"] == "sg_data_point"  # and its original dimension


def test_og1_tiers_partition_every_variable() -> None:
    """Required, candidate, named and carried together account for every variable, no overlap."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    named, carried = conversion._og1_tiers(ds, ledger, {})
    candidate_groups = conversion._og1_candidate_groups(ds, ledger, {})
    all_names = {str(n) for n in ds.variables}
    required = set(vocabularies.OG1_REQUIRED_VARS) & all_names
    candidates_present = {
        r["name"] for g in candidate_groups for r in g["rows"] if r["present"]
    }
    named_names = {r["name"] for r in named}
    carried_names = {n for f in carried for n in str(f["names"]).split(", ")}
    assert required | candidates_present | named_names | carried_names == all_names
    assert not (named_names & carried_names)  # a variable is named or carried, not both
    assert not (
        candidates_present & (named_names | carried_names)
    )  # candidates are lifted out


def test_og1_candidate_groups_from_the_curated_list() -> None:
    """Candidate groups come from OG1_CANDIDATE_VARS and record present/absent per variable."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    groups = conversion._og1_candidate_groups(ds, ledger, {"vert_speed_gsm": 61.0})
    assert {g["label"] for g in groups} == set(vocabularies.OG1_CANDIDATE_VARS.values())
    listed = {r["name"] for g in groups for r in g["rows"]}
    assert listed == set(
        vocabularies.OG1_CANDIDATE_VARS
    )  # every curated name appears once
    out = next(g for g in groups if g["label"] == "flight model — output")
    vspeed = next(r for r in out["rows"] if r["name"] == "vert_speed_gsm")
    assert vspeed["present"] is True
    assert vspeed["valid"] == "61.0"


def test_unit_factor_direct_normalised_and_unrelated() -> None:
    """Same unit is 1.0; a spelling variant resolves via the alias table; unrelated is None."""
    assert conversion._unit_factor("m", "m") == 1.0
    assert conversion._unit_factor("cm", "m") == 0.01  # direct table key
    assert (
        conversion._unit_factor("meters", "cm") == 100.0
    )  # normalised fallback (m_to_cm)
    assert (
        conversion._unit_factor("degrees_north", "cm") is None
    )  # no conversion invented


def test_summary_rows_and_verdict_before_and_after(tmp_path) -> None:
    """The before → after rows read the sidecar; the verdict is all-green on demo."""
    import xarray as xr

    path = convert.process_mission(DATA, tmp_path, dives=(1, 2))
    inputs = convert.conversion_sidecar(path)["inputs"]
    dim_samples = conversion._dimension_samples(inputs)
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        ledger = convert.conversion_ledger(ds)
        requirement_text, amber = conversion._requirement_summary(ds)
        rows = conversion._summary_rows(
            ds, ledger, inputs, dim_samples, path, requirement_text
        )
        recon, _caption = conversion._reconciliation(ds, ledger)
        verdict = conversion._verdict_clauses(recon, ledger, amber)
        rows_no_sidecar = conversion._summary_rows(
            ds, ledger, None, {}, path, requirement_text
        )
        # When the input files disagree on global count, the input cell shows the range.
        mixed = [dict(record) for record in inputs]
        mixed[0]["n_globals"] = 50
        mixed[1]["n_globals"] = 59
        rows_mixed = conversion._summary_rows(
            ds, ledger, mixed, dim_samples, path, requirement_text
        )
        # A legacy (schema-1) sidecar lacks n_globals: the row falls back to "—", not KeyError.
        legacy = [{k: v for k, v in r.items() if k != "n_globals"} for r in inputs]
        rows_legacy = conversion._summary_rows(
            ds, ledger, legacy, dim_samples, path, requirement_text
        )
    by_q = {r["quantity"]: r for r in rows}
    assert by_q["Files"]["input"] == "2" and by_q["Files"]["output"] == "1"
    assert by_q["Variables"]["input"] == f"{ledger['input_variable_count']:,}"
    assert by_q["Dives"]["output"] == "same"
    # Without a sidecar the sidecar-only input cells fall back to "—".
    by_q_no = {r["quantity"]: r for r in rows_no_sidecar}
    assert by_q_no["Files"]["input"] == "—"
    assert by_q_no["Global attributes"]["input"] == "—"
    mixed_globals = {r["quantity"]: r for r in rows_mixed}["Global attributes"]["input"]
    assert mixed_globals == "50–59"
    legacy_globals = {r["quantity"]: r for r in rows_legacy}["Global attributes"][
        "input"
    ]
    assert legacy_globals == "—"
    # Demo converts cleanly: every clause is green and all inputs are accounted for.
    assert not any(c["bad"] for c in verdict)
    assert verdict[0]["text"].endswith("inputs accounted for")


def test_page_section_order_and_scalars_collapsed(tmp_path) -> None:
    """The sections render in the new-user order; the first scalar group is open, rest closed."""
    import re

    path = convert.process_mission(DATA, tmp_path, dives=(1, 2))
    html = conversion.render_conversion(path)
    ids = re.findall(r'<section id="([^"]+)">', html)
    assert ids == [
        "summary",
        "og1",
        "reconciliation",
        "presence",
        "dimensions",
        "derived",
        "dropped",
        "variables",
        "globals",
        "scalars",
    ]
    assert "1. Before → after" in html
    details = re.findall(r'<details class="scalar-group"( open)?>', html)
    assert details and details[0] == " open"
    assert all(flag == "" for flag in details[1:])


def test_presence_strips_follow_file_order_across_a_dive_gap() -> None:
    """Columns are input files: dives 1, 2, 100 take three equal columns labelled by dive."""
    from seagliderOG1 import convert

    presence = {
        "dives": [1, 2, 100],
        "variables": {"a": {"present": [[1, 100]], "valid": [[1, 100]]}},
    }
    fig = conversion.draw_presence_strips(
        convert.presence_patterns(presence), presence["dives"]
    )
    assert len(fig.axes) == 2  # no density row, no colorbar
    lower = fig.axes[1]
    assert lower.get_xlim() == (-0.5, 2.5)
    assert [t.get_text() for t in lower.get_xticklabels()] == ["1", "2", "100"]


def test_verdict_counts_required_variables_and_meanings_name_sections():
    """Mandatory covers variables too; Meaning texts name sections, not numbers."""
    recon = [("Renamed", "1", "x"), ("Basestation inputs", "1", "")]
    ledger = {"dropped": [], "removed": []}
    clause = conversion._verdict_clauses(recon, ledger, False, True)[-1]
    assert clause == {"text": "OG1 mandatory incomplete (variables)", "bad": True}
    clause = conversion._verdict_clauses(recon, ledger, False, False)[-1]
    assert clause == {"text": "OG1 mandatory complete", "bad": False}
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    rows, _caption = conversion._reconciliation(ds, ledger)
    assert not any("§" in meaning for _label, _count, meaning in rows)
