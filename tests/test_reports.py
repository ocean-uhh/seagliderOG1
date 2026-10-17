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

from seagliderOG1 import convert, readers  # noqa: E402  # import after sys.path bootstrap
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


def test_masthead_meta_names_platform_and_input_output_counts():
    """The masthead metadata carries the platform/serial and the input/output variable counts."""
    ds = _dataset()
    ledger = convert.conversion_ledger(ds)
    meta = dict(conversion._masthead_meta(ds, ledger))
    assert "sg005" in meta["Platform"]
    assert meta["Inputs → outputs"].startswith(f"{ledger['input_variable_count']} → ")


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
