"""Units of the variables kept under their basestation names: conversions, relabels and the
configured attributes, checked against the raw dive files.

Data: the sg271 sample (raw files read directly) and the sg005 demo.
"""

import json
import pathlib

import netCDF4
import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, vocabularies

ROOT = pathlib.Path(__file__).parent.resolve().parents[1]
SG005 = ROOT / "data" / "demo_sg005"
SG271 = ROOT / "seagliderOG1" / "data" / "sg271"


@pytest.fixture(scope="module")
def sg271_file(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return _convert._convert_mission(SG271, tmp_path_factory.mktemp("sg271_units"))


def _raw(name: str) -> np.ndarray:
    first = sorted(SG005.glob("p*.nc"))[0]
    with xr.open_dataset(first, decode_times=False) as ds:
        return ds[name].values.astype(float)


# --- Conversions and relabels against the raw files ---------------------------------------


def test_cm_per_s_is_converted_and_recorded(sg005_og1):
    """sg005's speed_gsm (cm/s) is written in m s-1, values x0.01, with the provenance."""
    with netCDF4.Dataset(sg005_og1) as nc:
        speed = nc["speed_gsm"]
        assert speed.units == "m s-1"
        assert speed.original_units == "cm/s"
        assert "converted from cm/s (x0.01)" in speed.comment
        written = np.sort(speed[:].compressed().astype(float))
        ledger = json.loads(nc.conversion_units)
    raw = _raw("speed_gsm")
    expected = np.sort(raw[np.isfinite(raw)] * 0.01)
    np.testing.assert_allclose(written, expected, rtol=1e-6)
    assert ledger["speed_gsm"] == ["cm/s", "m s-1", 0.01]


def test_mislabelled_glide_angle_gsm_is_relabelled_not_converted(sg005_og1):
    """Basestation 2.8 labels glide_angle_gsm cm/s but writes degrees: relabelled, values kept."""
    with netCDF4.Dataset(sg005_og1) as nc:
        angle = nc["glide_angle_gsm"]
        assert angle.units == "degree"
        assert angle.original_units == "cm/s"
        written = np.sort(angle[:].compressed().astype(float))
        assert "glide_angle_gsm" not in json.loads(nc.conversion_units)
    raw = _raw("glide_angle_gsm")
    np.testing.assert_allclose(written, np.sort(raw[np.isfinite(raw)]), rtol=1e-6)


def test_spelling_only_relabels(sg271_file):
    """sg271's own TEOS-10 and density variables take the canonical spelling, values unchanged."""
    with netCDF4.Dataset(sg271_file) as nc:
        assert nc["absolute_salinity"].units == "g kg-1"
        assert nc["gsw_sigma0"].units == "kg m-3"
        assert nc["conservative_temperature"].units == "degree_Celsius"
        assert "original_units" not in nc["absolute_salinity"].ncattrs()
        assert "absolute_salinity" not in json.loads(nc.conversion_units)


def test_no_known_alias_spelling_survives(sg271_file):
    """Every unit spelling the units table knows as an alias is written canonically, except a
    per-dive scalar stored as text whose values would need converting (left as written)."""
    aliases = {
        a for spellings in vocabularies.UNITS.aliases.values() for a in spellings
    }
    with netCDF4.Dataset(sg271_file) as nc:
        left = {
            v.name
            for v in nc.variables.values()
            if getattr(v, "units", None) in aliases
        }
    assert left <= {"surface_curr_east", "surface_curr_north"}


# --- Configured attributes ----------------------------------------------------------------


def test_profile_variables_carry_their_configured_attributes(sg271_file):
    """PROFILE_NUMBER's vocabulary reaches the file; PROFILE_DIRECTION and SEGMENT_NUMBER are
    in the configuration as OG1 variables."""
    assert {"PROFILE_DIRECTION", "SEGMENT_NUMBER"} <= set(vocabularies.vocab_attrs)
    with netCDF4.Dataset(sg271_file) as nc:
        assert nc["PROFILE_NUMBER"].vocabulary == (
            "http://vocab.nerc.ac.uk/collection/OG1/current/PROFILE_NUMBER/"
        )
        assert nc["PROFILE_DIRECTION"].long_name == "Vertical direction of profile"
        assert nc["SEGMENT_NUMBER"].long_name == (
            "Identifier of numbered segment within the dataset"
        )
