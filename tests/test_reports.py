"""Tests for the owned conversion-page builders in ``reports/conversion.py``.

These exercise the owned row builders directly (no HTML render) against a real OG1 dataset
converted from ``data/demo_sg005``, so the reconciliation identity and the per-section row
logic are checked once each.
"""

import pathlib
import sys

import netCDF4
import yaml

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import (  # noqa: E402  # import after sys.path bootstrap
    _convert,
    readers,
    vocabularies,
)
from seagliderOG1.reports import (  # noqa: E402  # import after sys.path bootstrap
    _record,
    conversion,
)

DATA = str(parent_dir / "data/demo_sg005")


def _dataset():
    """Return the demo_sg005 OG1 dataset (dives 1-2)."""
    return _convert.convert(readers.read_mission(DATA, 1, 2))


def test_dimension_rows_variables_sum_to_input_count():
    """The Dimensions table (dimensions + the scalar row) accounts for every input variable."""
    ledger = _record.conversion_ledger(_dataset())
    rows = conversion._dimension_rows(ledger)
    assert sum(r["n"] for r in rows) == ledger["input_variable_count"]
    # The scalar row is present and carries the storage split in its variable list.
    scalar = next(r for r in rows if r["dimension"] == "(scalar)")
    assert scalar["n"] == len(ledger["scalar_parameters"])
    assert "constant" in scalar["variables"] and "per-dive" in scalar["variables"]


def test_derived_rows_input_sources_equal_the_consumed_set():
    """The basestation sources named across derived rows equal the reconciliation consumed set."""
    ds = _dataset()
    ledger = _record.conversion_ledger(ds)
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
    ledger = _record.conversion_ledger(ds)
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
    ledger = _record.conversion_ledger(ds)
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


def test_demo_config_institution_is_one_record_in_people_and_institutions():
    """The demo mission.yaml's Operator merges with the file's institution, grouped right.

    The basestation ``institution`` global is a postal address the registry knows; the
    config name must resolve to the same registry entry, or the file writes two
    institutions (one role-less, one without an EDMO id).
    """
    from seagliderOG1.reports import design
    from seagliderOG1.reports._vendored import nc_tables

    config = yaml.safe_load((pathlib.Path(DATA) / "mission.yaml").read_text())
    ds = _convert.convert(
        readers.read_mission(DATA, 1, 1), institutions=config["institutions"]
    )
    assert ds.attrs["contributing_institutions"] == (
        "University of Washington (School of Oceanography)"
    )
    assert ds.attrs["contributing_institutions_role"] == "Operator"
    assert ds.attrs["contributing_institutions_vocabulary"].endswith("/report/1434")
    groups, _source = nc_tables.globals_rows(
        ds,
        extras=design.ATTR_GROUP_EXTRAS,
        exclude=["history", "conversion_attribute_sources"],
    )
    people = {
        row[0]
        for title, rows in groups
        if title == "People & institutions"
        for row in rows
    }
    assert {
        "contributing_institutions_role",
        "contributing_institutions_role_vocabulary",
    } <= people
    assert "Other" not in [title for title, _rows in groups]


def test_requirement_summary_counts_the_mandatory_tier():
    """The requirement line reports every mandatory global present on demo (not amber)."""
    ds = _dataset()
    text, amber = conversion._requirement_summary(ds)
    assert text.startswith("OG1 requirement: mandatory 9/9 present")
    assert amber is False


def test_masthead_meta_names_platform_not_input_output_counts():
    """The masthead carries the platform/serial; the input → output counts moved to §1."""
    ds = _dataset()
    ledger = _record.conversion_ledger(ds)
    meta = dict(conversion._masthead_meta(ds, ledger))
    assert "sg005" in meta["Platform"]
    assert (
        "Inputs → outputs" not in meta
    )  # now the first row of the Before → after table


def test_per_dive_scalar_value_is_decoded_not_json():
    """A per-dive scalar's Value shows decoded per-dive values, not the raw JSON string."""
    ds = _dataset()
    ledger = _record.conversion_ledger(ds)
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
    ledger = _record.conversion_ledger(ds)
    rows, _caption = conversion._reconciliation(ds, ledger)
    fig = conversion.draw_fate_histogram(rows[:-1])  # drop the input-total row
    assert fig is not None
    ax = fig.axes[0]
    assert len(ax.patches) == len(rows) - 1  # one bar per fate
    assert conversion.draw_fate_histogram([]) is None


def test_history_rows_are_ordinal_numbered():
    """History rows carry a 1-based ordinal in the first column, in file order."""
    ledger = _record.conversion_ledger(_dataset())
    rows = conversion._history_rows(ledger)
    assert rows  # at least the conversion line
    assert [r[0] for r in rows] == [str(i) for i in range(1, len(rows) + 1)]


def test_page_presence_section_with_and_without_sidecar(tmp_path) -> None:
    """The page shows the pattern table from the sidecar, and says so when it is missing."""
    import pathlib

    from seagliderOG1 import _convert, writers

    path = _convert._convert_mission(
        pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005",
        tmp_path,
    )
    html = conversion.render_conversion(path)
    assert "Presence across dives" in html
    assert "from dive 2" in html and "dive 4 only" in html
    assert "343 variables over 5 dives" in html
    writers.conversion_path(path, ".json").unlink()
    html = conversion.render_conversion(path)
    assert "conversion record not found" in html


def test_presence_strips_one_row_per_pattern() -> None:
    """The strip figure has two panels with one row per contiguous pattern."""

    presence = {
        "dives": [1, 2, 3],
        "variables": {
            "a": {"present": [[1, 3]], "valid": [[1, 3]]},
            "b": {"present": [[1, 3]], "valid": [[2, 3]]},
            "c": {"present": [[1, 1], [3, 3]], "valid": [[1, 1], [3, 3]]},
        },
    }
    patterns = _record.presence_patterns(presence)
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
    rows, _caption = conversion._reconciliation(ds, _record.conversion_ledger(ds))
    assert all(row[2] for row in rows[:-1])  # each fate explains itself
    assert rows[-1][2] == ""  # the input-total row carries no meaning


def test_dimension_rows_show_samples_in_from_the_sidecar() -> None:
    """Samples in is the sidecar sum per dimension; "—" for the scalar row and without it."""
    ledger = _record.conversion_ledger(_dataset())
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
    ledger = _record.conversion_ledger(ds)
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
    """Required, candidate, sensor, named and carried account for every variable, no overlap."""
    ds = _dataset()
    ledger = _record.conversion_ledger(ds)
    named, carried = conversion._og1_tiers(ds, ledger, {})
    candidate_groups = conversion._og1_candidate_groups(ds, ledger, {})
    all_names = {str(n) for n in ds.variables}
    required = set(vocabularies.OG1_REQUIRED_VARS) & all_names
    candidates_present = {
        r["name"] for g in candidate_groups for r in g["rows"] if r["present"]
    }
    named_names = {r["name"] for r in named}
    carried_names = {n for f in carried for n in str(f["names"]).split(", ")}
    sensor_names = {r["name"] for r in conversion._og1_sensor_rows(ds)}
    assert (
        required | candidates_present | sensor_names | named_names | carried_names
        == all_names
    )
    assert not (named_names & carried_names)  # a variable is named or carried, not both
    assert not (sensor_names & (named_names | carried_names))  # sensors: own table
    assert not (
        candidates_present & (named_names | carried_names)
    )  # candidates are lifted out


def test_og1_candidate_groups_from_the_curated_list() -> None:
    """Candidate groups come from OG1_CANDIDATE_VARS and record present/absent per variable."""
    ds = _dataset()
    ledger = _record.conversion_ledger(ds)
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

    path = _convert._convert_mission(DATA, tmp_path, dives=(1, 2))
    inputs = _record.conversion_sidecar(path)["inputs"]
    dim_samples = conversion._dimension_samples(inputs)
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        ledger = _record.conversion_ledger(ds)
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

    path = _convert._convert_mission(DATA, tmp_path, dives=(1, 2))
    html = conversion.render_conversion(path)
    ids = re.findall(r'<section id="([^"]+)">', html)
    assert ids == [
        "config-check",  # no platform given: PLATFORM_MODEL etc. are UNK
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

    presence = {
        "dives": [1, 2, 100],
        "variables": {"a": {"present": [[1, 100]], "valid": [[1, 100]]}},
    }
    fig = conversion.draw_presence_strips(
        _record.presence_patterns(presence), presence["dives"]
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
    ledger = _record.conversion_ledger(ds)
    rows, _caption = conversion._reconciliation(ds, ledger)
    assert not any("§" in meaning for _label, _count, meaning in rows)


def test_basestation_rows_flag_values_that_differ_or_are_missing():
    """Pure logic: one row per attribute; amber when it varies or misses some files."""
    found = {
        "platform_id": {"values": ["SG005"], "n_files": 3},
        "dive_number": {"values": ["1", "2", "3"], "n_files": 3},
        "wmo_id": {"values": ["123"], "n_files": 1},
    }
    rows = {r["name"]: r for r in conversion._basestation_rows(found, 3)}
    assert (
        rows["platform_id"]["status"] == "all 3 files"
        and not rows["platform_id"]["bad"]
    )
    assert (
        rows["dive_number"]["distinct"] == ["1", "2", "3"]
        and rows["dive_number"]["bad"]
    )
    assert rows["wmo_id"]["status"] == "1 of 3 files" and rows["wmo_id"]["bad"]
    assert conversion._basestation_rows(None, 3) == []


def test_conventions_check_counts_acdd_and_cf_units():
    """The box reads Conventions and counts ACDD 1.3 globals and CF units on sg005."""
    ds = _dataset()
    box = conversion._conventions_check(ds)
    assert box["claim"] == ds.attrs["Conventions"]
    levels = {level["level"]: level for level in box["acdd"]}
    assert levels["highly recommended"]["total"] == 4
    assert levels["recommended"]["total"] == 31
    assert "summary" in levels["highly recommended"]["missing"]
    assert box["short"]
    for name in box["no_units"]:
        assert "units" not in ds[name].attrs and ds[name].ndim


def test_draft_snippets_fill_only_what_the_files_carry(sg005_og1_copy):
    """Pure logic: dives and file-derived platform fields filled; required ones null."""
    from_file = vocabularies.platform_from_file(
        {"platform_id": "SG005", "base_station_version": "2.8"}
    )
    blocks = conversion._draft_snippets(from_file, [3, 4], "sg005_x_delayed_draft")
    text = "\n".join(block["text"] for block in blocks)
    assert "dives: [3, 4]" in text
    assert "PLATFORM_SERIAL_NUMBER: sg005" in text
    assert "LANDSTATION_VERSION: basestation v2.8" in text
    assert "PLATFORM_MODEL: null" in text  # required, not in the files
    assert "sg005_x_delayed\n" in text and "id: null" in text  # derived id as a comment
    assert conversion._draft_snippets(None, [1], "x") == []
    # An OG1 (non-draft) page gets none, also when some other global is called draft:
    # the page knows a draft by the draft global's value.
    path = sg005_og1_copy
    assert "Suggested mission.yaml lines" not in conversion.render_conversion(path)


def _texts(block):
    """Return the box texts of a config-suggestion block."""
    return [box["text"] for box in block["boxes"]]


def test_config_suggestions_pair_config_with_the_files(sg005_og1):
    """Pure logic on the real sidecar: only the values that differ get a pair."""
    sidecar = _record.conversion_sidecar(sg005_og1)
    assert sidecar["config"] == {
        "dives": [1, 1],
        "platform": {},
        "deployment_id": None,
        "institutions": [],
    }
    assert conversion._config_suggestions(sidecar) == []  # nothing differs
    assert conversion._config_suggestions(None) == []
    edited = {
        **sidecar,
        "config": {
            "dives": [1, 3],
            "platform": {
                "PLATFORM_SERIAL_NUMBER": "sg005",  # agrees with the file
                "PLATFORM_MODEL": "a model",  # config-only field
                "LANDSTATION_VERSION": "basestation v2.9",
            },
        },
    }
    dives, platform = conversion._config_suggestions(edited)
    assert _texts(dives) == ["dives: [1, 3]", "dives: [1, 1]"]
    assert _texts(platform) == [
        "platform:\n  LANDSTATION_VERSION: basestation v2.9",
        "platform:\n  LANDSTATION_VERSION: basestation v2.8",
    ]
    assert platform["note"] == "From the first basestation file."
    # A source global that varies across the files is named in the note.
    edited["basestation_globals"] = {
        **sidecar["basestation_globals"],
        "base_station_version": {"values": ["2.8", "2.9"], "n_files": 2},
    }
    note = conversion._config_suggestions(edited)[1]["note"]
    assert "base_station_version has 2 values (2.8, 2.9)" in note
    # Dives rejected inside the converted span are named; the range is the span.
    edited["presence"] = {**sidecar["presence"], "dives": [1, 2, 4]}
    edited["config"]["dives"] = [1, 5]
    dives = conversion._config_suggestions(edited)[0]
    assert _texts(dives)[1] == "dives: [1, 4]"
    assert dives["note"] == "3 dives converted, 1 to 4; not converted: 3."


def test_config_suggestions_fill_gaps_from_the_file(sg005_og1):
    """The fixture (no platform, no institutions) has UNK and omitted platform fields."""
    import xarray as xr

    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        gaps = conversion._platform_gaps(ds)
        box = conversion._conventions_check(ds)
    assert gaps == {
        "PLATFORM_MODEL": "written as UNK",
        "PLATFORM_DEPTH_RATING": "omitted",
        "PLATFORM_MAKER": "written as UNK",
        "WMO_IDENTIFIER": "written as UNK",
    }
    missing = {n: lv["level"] for lv in box["acdd"] for n in lv["missing"]}
    blocks = conversion._config_suggestions(None, gaps, missing)
    assert [b["title"] for b in blocks] == [
        "Platform not filled",
        "Missing globals",
    ]
    assert "  PLATFORM_DEPTH_RATING: null   # omitted" in _texts(blocks[0])[0]
    texts = {b["label"]: b["text"] for b in blocks[1]["boxes"]}
    assert texts["identity_and_discovery:"] == (
        "identity_and_discovery:\n  naming_authority: null   # ACDD recommended"
    )
    assert texts["provenance_and_processing:"] == (
        "provenance_and_processing:\n  comment: null   # ACDD recommended"
    )
    escape = texts["global_attributes:"]
    # OG1 records people in contributor_*: no creator_* / publisher_* box.
    assert "creator_name" not in escape and "publisher_name" not in escape
    assert "creator_name" in blocks[1]["note"]
    assert "  summary: null   # ACDD highly recommended" in escape
    # Globals the converter supplies itself are named in the note, never boxed.
    assert "geospatial_bounds" not in escape
    assert "standard_name_vocabulary" in blocks[1]["note"]


def test_sensor_rows_list_each_sensor_its_users_and_placeholders(sg005_og1):
    """demo_sg005: three sensors, each with its users; the zero serial/date is amber."""
    import xarray as xr

    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        rows = {r["name"]: r for r in conversion._og1_sensor_rows(ds)}
        ledger = _record.conversion_ledger(ds)
        named, _carried = conversion._og1_tiers(ds, ledger, {})
    assert sorted(rows) == [
        "SENSOR_CTD_245201",
        "SENSOR_FLUOROMETER_0000",
        "SENSOR_OXYGEN_005",
    ]
    ctd = rows["SENSOR_CTD_245201"]
    assert (ctd["type"], ctd["serial"], ctd["calibration"]) == (
        "CTD",
        "245201",
        "2008-02-04",
    )
    assert "TEMP" in ctd["used_by"].split(", ") and not ctd["bad"]
    fluorometer = rows["SENSOR_FLUOROMETER_0000"]
    assert fluorometer["calibration"] == "00-00-0000" and fluorometer["bad"]
    # The sensors are not repeated in the Named by OG1 table.
    assert not [r for r in named if r["name"].startswith("SENSOR_")]
    assert conversion._is_placeholder("") and not conversion._is_placeholder(
        "2008-02-04"
    )


def test_config_suggestions_offer_registry_entries_for_an_unmatched_name():
    """A config name the registry does not match exactly gets entries containing its words."""
    assert conversion._registry_candidates("University of Hamburg Oceanography") == [
        ("3323", "University of Hamburg")
    ]
    assert conversion._registry_candidates("No Such Institute") == []
    sidecar = {
        "config": {
            "institutions": [
                {"name": "University of Hamburg Oceanography", "role": "Operator"}
            ]
        }
    }
    (block,) = conversion._config_suggestions(sidecar)
    assert block["title"] == "Institution not in the registry"
    assert [b["label"] for b in block["boxes"]] == ["EDMO 3323"]
    assert yaml.safe_load(block["boxes"][0]["text"]) == {
        "institutions": [
            {"name": "University of Hamburg", "role": "Operator", "id": None}
        ]
    }


def test_missing_globals_include_what_validate_warns_about():
    """OG1 highly-desirable globals the file lacks join the ACDD ones, labelled by tier."""
    (block,) = conversion._config_suggestions(
        None,
        acdd_missing={"summary": "highly recommended", "doi": "recommended"},
        og1_missing=["doi", "internal_mission_identifier", "program"],
    )
    rights, escape = (b["text"] for b in block["boxes"])
    assert "  doi: null   # OG1 highly desirable; ACDD recommended" in rights
    # program has no section (registry-supplied), so it joins global_attributes.
    assert "  program: null   # OG1 highly desirable" in escape
    assert "  internal_mission_identifier: null   # OG1 highly desirable" in escape
    assert "  summary: null   # ACDD highly recommended" in escape


def test_config_suggestions_offer_the_id_from_dive_1(sg005_og1):
    """A conversion from dive 1 with no deployment.id is offered its derived id to pin."""
    sidecar = _record.conversion_sidecar(sg005_og1)
    (block,) = conversion._config_suggestions(sidecar, og1_id="sg005_x_R")
    assert block["title"] == "Deployment id"
    assert block["boxes"][0]["text"] == "identity_and_discovery:\n  id: sg005_x_R"
    # Not from a later dive (the derived start is not the deployment's), and not when set.
    later = {**sidecar, "presence": {**sidecar["presence"], "dives": [2, 3]}}
    titles = [b["title"] for b in conversion._config_suggestions(later, og1_id="x")]
    assert "Deployment id" not in titles
    pinned = {**sidecar, "config": {**sidecar["config"], "deployment_id": "sg005_x_R"}}
    assert conversion._config_suggestions(pinned, og1_id="sg005_x_R") == []


# The yaml section slugs are this schema's own names, not derived from the vendored page
# labels (which ctdcast owns). This maps each to the page group it must correspond to; a
# vendored relabel or regroup breaks this test, never a user's mission.yaml.
_LABEL_BY_SECTION = {
    "identity_and_discovery": "Identity & discovery",
    "rights_and_access": "Rights & access",
    "provenance_and_processing": "Provenance & processing",
}


def test_config_global_sections_correspond_to_the_page_groups():
    """Every section key groups under its page label; the map is complete (no vacuous pass)."""
    from seagliderOG1 import vocabularies
    from seagliderOG1.reports import design
    from seagliderOG1.reports._vendored import nc_tables

    # (1) the map covers exactly the sections — adding a section cannot silently skip the check.
    assert set(_LABEL_BY_SECTION) == set(vocabularies.CONFIG_GLOBAL_SECTIONS)
    # (2) every label is a real page group (vendored ATTR_GROUPS or the package extras).
    page_labels = {label for label, _ in nc_tables.ATTR_GROUPS} | set(
        design.ATTR_GROUP_EXTRAS
    )
    assert set(_LABEL_BY_SECTION.values()) <= page_labels
    # (3) per-key correspondence, resolved as the report resolves it (vendored then extras).
    group_of: dict[str, str] = {}
    for label, names in nc_tables.ATTR_GROUPS:
        for name in names:
            group_of[name] = label
    for label, names in design.ATTR_GROUP_EXTRAS.items():
        for name in names:
            group_of.setdefault(name, label)
    for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items():
        for key in keys:
            assert group_of.get(key) == _LABEL_BY_SECTION[slug], (slug, key)


def test_basestation_identity_globals_are_not_carried(sg005_og1):
    """sg005's naming_authority, uuid and summary describe the basestation files, not OG1."""
    import xarray as xr

    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        assert "naming_authority" not in ds.attrs  # was edu.washington.apl
        assert "uri" not in ds.attrs  # was dive 1's uuid
        assert "site" not in ds.attrs  # was the basestation summary text
        assert ds.attrs["id"].endswith("_R")  # no mode given: realtime


def test_config_suggestions_pin_registry_institution_ids(sg005_og1):
    """A config institution with no id that the registry matches gets a pinned block."""
    sidecar = _record.conversion_sidecar(sg005_og1)
    sidecar["config"]["institutions"] = [
        {"name": "UW School of Oceanography", "role": "Operator", "id": None},
        {"name": "No Such Institute", "role": "Owner"},
    ]
    (block,) = conversion._config_suggestions(sidecar)
    assert block["title"] == "Institution ids"
    assert yaml.safe_load(_texts(block)[0]) == {
        "institutions": [
            {
                "name": "University of Washington (School of Oceanography)",
                "role": "Operator",
                "id": "https://edmo.seadatanet.org/report/1434",
            },
            {"name": "No Such Institute", "role": "Owner", "id": None},
        ]
    }
    # Nothing in the config resolved: no ids block, but the file's institution (dropped
    # by the converter because the config lists institutions) is offered instead.
    sidecar["config"]["institutions"] = [{"name": "No Such Institute", "role": "Owner"}]
    (block,) = conversion._config_suggestions(sidecar)
    assert block["title"] == "Institution in the basestation files"
    assert "Seattle, WA 98195-5351" in block["note"]
    assert _texts(block) == [
        "institutions:\n"
        "- name: University of Washington (School of Oceanography)\n"
        "  role: null   # set the role\n"
        "  id: https://edmo.seadatanet.org/report/1434"
    ]
    # Without config institutions the converter keeps the file's: nothing to offer.
    sidecar["config"]["institutions"] = []
    assert conversion._config_suggestions(sidecar) == []


def test_config_suggestions_on_the_page(tmp_path):
    """A process_mission run whose dives and platform disagree with the files shows both."""
    path = _convert._convert_mission(
        DATA,
        tmp_path,
        dives=(4, 9),
        platform={"LANDSTATION_VERSION": "basestation v2.9"},
        report=True,
    )
    html = (tmp_path / f"{path.stem}_conversion.html").read_text(encoding="utf-8")
    assert "mission.yaml against the data" in html
    assert "2 dives converted, 4 to 5." in html
    assert ">dives: [4, 9]</textarea>" in html and ">dives: [4, 5]</textarea>" in html
    assert "LANDSTATION_VERSION: basestation v2.8</textarea>" in html
    assert 'data-copy="config-2-2"' in html
    assert "Platform not filled" in html  # the call set no PLATFORM_MODEL
    with netCDF4.Dataset(path, "a") as nc:
        nc.setncattr("draft", "v2 of the cruise report")
    html = conversion.render_conversion(path)
    assert '<span class="masthead-type">conversion</span>' in html


def test_importing_reports_pins_a_headless_backend() -> None:
    """Importing the report layer forces a non-interactive backend, even with none set, so a
    render (CLI, notebook, script or test) never blocks on a GUI window."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"}
    code = (
        "import matplotlib; from seagliderOG1 import reports; "
        "assert matplotlib.get_backend().lower() == 'agg', matplotlib.get_backend()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_fate_figure_labels_are_ascii() -> None:
    """The figure writes "->" (the arrow glyph is missing from common figure fonts)."""
    import matplotlib

    matplotlib.use("Agg")
    fig = conversion.draw_fate_histogram([("Consumed → derived", "3", "")])
    labels = [label.get_text() for label in fig.axes[0].get_yticklabels()]
    assert labels == ["Consumed -> derived"]


def test_presence_strips_place_the_colorbar_beside_the_strips():
    """A sporadic row adds a colorbar in its own column; the render does not warn."""
    import warnings

    from seagliderOG1.reports._vendored import figure_png

    dives = list(range(1, 13))
    variables = {"every": {"present": [[1, 12]], "valid": [[1, 12]]}}
    for i, picks in enumerate(([1, 3, 5, 7], [2, 4, 6], [1, 2, 9, 11], [3, 8])):
        runs = [[d, d] for d in picks]
        variables[f"sporadic{i}"] = {"present": runs, "valid": runs}
    patterns = _record.presence_patterns({"dives": dives, "variables": variables})
    fig = conversion.draw_presence_strips(patterns, dives)
    strips, colorbar = fig.axes[:2], fig.axes[2]
    assert all(colorbar.get_position().x0 > ax.get_position().x1 for ax in strips)
    # The renderer turns a figure warning into a dropped panel (None), so check both.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        png = figure_png.render_b64(
            conversion.draw_presence_strips, patterns, dives, source="test"
        )
    assert png is not None
