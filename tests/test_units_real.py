"""Real-data tests for the basestation units-label corrections.

The density family is written ``g/m^3`` by the basestation while holding kg m-3-
magnitude values; 0.1.0 trusted the label and wrote the values 1000x too small.
These tests convert the two bundled samples (sg271 basestation 3.0.6, sg005
basestation 2.8) and assert the corrected magnitudes, the recorded provenance,
that out-of-range values are left as-is (not silently changed), and the refusal
of an uncorrected mislabel.
"""

import logging
import pathlib
import sys
import warnings

import numpy as np
import pytest

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import (  # noqa: E402  # import after sys.path bootstrap
    UnitsError,
    _convert,
    readers,
    vocabularies,
)

SG005 = str(parent_dir / "data" / "demo_sg005")


def _convert_dive1(mission_dir: str):
    """Read dive 1 of a mission and convert it to OG1, suppressing warnings."""
    dsets = readers.read_mission(mission_dir, 1, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _convert.convert(dsets)


@pytest.fixture(scope="module")
def sg271():
    """The sg271 (basestation 3.0.6) sample, dive 1, converted to OG1."""
    return _convert_dive1(str(readers.SAMPLE_DIR))


@pytest.fixture(scope="module")
def sg005():
    """The sg005 (basestation 2.8) sample, dive 1, converted to OG1."""
    return _convert_dive1(SG005)


def _median(ds, name):
    """Return the median of a variable's finite values."""
    values = np.asarray(ds[name].values, dtype="float64").ravel()
    finite = values[np.isfinite(values)]
    return float(np.median(finite))


def _source_target_pairs():
    """Every (source units, OG1 target units, standard_name) a mapped variable carries.

    Read from both bundled samples, so a new basestation spelling that reaches an OG1
    variable fails the test until an alias row with its source is added to vocabularies.UNITS.
    The density mislabel (g/m^3) is excluded: it is the OG1_unit_corrections.yaml label
    correction, applied before resolution, not an alias.
    """
    import warnings

    corrections = set(vocabularies.basestation_unit_corrections)
    pairs = set()
    for mission_dir in (str(readers.SAMPLE_DIR), SG005):
        dsets = readers.read_mission(mission_dir, 1, 1)
        raw = dsets[0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            og1 = _convert.convert(dsets)
        for name in og1.data_vars:
            origin = str(og1[name].attrs.get("original_name", ""))
            target = vocabularies.vocab_attrs.get(name, {})
            if origin in ("", name) or "units" not in target:
                continue
            if origin not in raw.variables or origin in corrections:
                continue
            source = raw[origin].attrs.get("units")
            if source:
                pairs.add((str(source), target["units"], target.get("standard_name")))
    return sorted(pairs)


@pytest.mark.xfail(
    reason="OXYSAT (micromoles/kg->percent) and DOXY (micromoles/kg->mmol m-3) are "
    "wrong-quantity mappings the view cannot resolve; removed in the mapping-changes commit",
    strict=True,
)
def test_units_view_resolves_every_sample_spelling():
    """vocabularies.UNITS resolves every source spelling the bundled samples carry."""
    from seagliderOG1.reports._vendored import units

    unresolved = []
    for source, target, standard_name in _source_target_pairs():
        try:
            units.resolve_units(
                source, standard_name, tables=vocabularies.UNITS, canonical=target
            )
        except units.UnitsError:
            unresolved.append((source, target))
    assert unresolved == [], f"UNITS does not resolve: {unresolved}"


def test_sg271_density_relabelled_to_kg_m3(sg271):
    """sg271 DENSITY and SIGMA_T are kg m-3-magnitude, not 1000x too small."""
    assert 1020 <= _median(sg271, "DENSITY") <= 1035
    assert 20 <= _median(sg271, "SIGMA_T") <= 35
    for name in ("DENSITY", "SIGMA_T"):
        assert sg271[name].attrs["units"] == "kg m-3"
        assert sg271[name].attrs["original_units"] == "g/m^3"
        assert "corrected to 'kg m-3'" in sg271[name].attrs["comment"]


def test_sg271_sigtheta_already_correct_left_unchanged(sg271):
    """sg271 labels SIGTHETA kg/m^3 already; it keeps its anomaly value, no mark."""
    assert 20 <= _median(sg271, "SIGTHETA") <= 35
    assert "original_units" not in sg271["SIGTHETA"].attrs


def test_sg271_gsw_sigma0_not_mapped_to_potdens0(sg271):
    """gsw_sigma0 is the anomaly; it is not mapped to full-density POTDENS0, but passes through."""
    assert "POTDENS0" not in sg271
    assert "gsw_sigma0" in sg271
    assert 20 <= _median(sg271, "gsw_sigma0") <= 35


def test_passthrough_density_relabelled(sg271):
    """The unmapped, passed-through `density` gets the same label fix; its value is unchanged."""
    assert sg271["density"].attrs["units"] == "kg m-3"
    assert sg271["density"].attrs["original_units"] == "g/m^3"
    assert 1020 <= _median(sg271, "density") <= 1035


def test_no_density_family_left_mislabelled(sg271, sg005):
    """No variable ships labelled g/m^3 after conversion, mapped or passed through."""
    for ds in (sg271, sg005):
        mislabelled = [
            name
            for name in ds.data_vars
            if str(ds[name].attrs.get("units", "")).replace(" ", "")
            in ("g/m^3", "gm-3")
        ]
        assert mislabelled == []


def test_sg005_sigma_t_relabelled(sg005):
    """sg005 (basestation 2.8) SIGMA_T is corrected from g/m^3 to the anomaly."""
    assert 20 <= _median(sg005, "SIGMA_T") <= 35
    assert sg005["SIGMA_T"].attrs["units"] == "kg m-3"
    assert sg005["SIGMA_T"].attrs["original_units"] == "g/m^3"


def test_sg005_sigma_theta_out_of_range_left_as_is(sg005):
    """sg005 stores sigma_theta as full density (~1027); the label is fixed but the value is not
    changed (no auto offset) - it is left as-is to be flagged on the page, not silently altered."""
    assert 1020 <= _median(sg005, "SIGTHETA") <= 1035
    assert sg005["SIGTHETA"].attrs["units"] == "kg m-3"
    assert sg005["SIGTHETA"].attrs["original_units"] == "g/m^3"


def test_uncorrected_mislabel_is_refused(monkeypatch):
    """A g/m^3 density var absent from the corrections table is refused, not shipped a factor off."""
    monkeypatch.setattr(vocabularies, "basestation_unit_corrections", {})
    dsets = readers.read_mission(str(readers.SAMPLE_DIR), 1, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(UnitsError) as excinfo:
            _convert.convert(dsets)
    message = str(excinfo.value)
    assert "DENSITY" in message
    assert "outside the valid range" in message


def test_correction_is_logged_once(monkeypatch, caplog):
    """The label correction is logged, so it is never silent."""
    # The dedup set is session-wide; reset it so this conversion logs afresh.
    monkeypatch.setattr(_convert, "_UNIT_CORRECTED", set())
    with caplog.at_level(logging.WARNING, logger="seagliderOG1._convert"):
        _convert_dive1(str(readers.SAMPLE_DIR))
    messages = [record.getMessage() for record in caplog.records]
    assert any("corrected to 'kg m-3'" in message for message in messages)
