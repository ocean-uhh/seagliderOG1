"""TEOS-10 variables the converter adds when the basestation does not write them."""

import json
import pathlib

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, _pipeline

SG271 = (
    pathlib.Path(__file__).resolve().parent.parent / "seagliderOG1" / "data" / "sg271"
)


@pytest.fixture(scope="module")
def sg271_og1(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Return an OG1 file converted from sg271 dives 1-3 (basestation 3.0.6)."""
    return _convert._convert_mission(SG271, tmp_path_factory.mktemp("sg271_og1"))


def test_potdens0_matches_the_basestation_sigma0(sg271_og1):
    """sg271 writes gsw_sigma0: POTDENS0 - 1000 equals it within 0.001 kg m-3."""
    with xr.open_dataset(sg271_og1, engine="netcdf4") as ds:
        potdens0 = ds["POTDENS0"].values.astype(float)
        sigma0 = ds["gsw_sigma0"].values.astype(float)
        mask = np.isfinite(potdens0) & np.isfinite(sigma0)
        assert mask.sum() > 1000
        assert np.abs(potdens0[mask] - 1000 - sigma0[mask]).max() < 1e-3
        # The basestation's own SA and CT pass through under their names, not as SA/CT.
        assert not {"SA", "CT"} & set(ds.variables)
        assert ds["absolute_salinity"].attrs["original_name"] == "absolute_salinity"
        assert "conservative_temperature" in ds.variables
        assert ds["POTDENS0"].attrs["sources"] == "PSAL TEMP PRES LONGITUDE LATITUDE"


def test_sg005_gets_potdens0_and_no_sa_or_ct(sg005_og1):
    """sg005 writes no density: POTDENS0 is added, in range, NaN where PSAL is NaN; the SA and
    CT computed on the way are not written."""
    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        assert not {"SA", "CT"} & set(ds.variables)
        assert "original_name" not in ds["POTDENS0"].attrs
        assert "gsw" in ds["POTDENS0"].attrs["comment"]
        assert "neither written to the file" in ds["POTDENS0"].attrs["comment"]
        potdens0 = ds["POTDENS0"].values
        assert np.nanmin(potdens0) > 1020 and np.nanmax(potdens0) < 1030
        assert (np.isnan(potdens0) == np.isnan(ds["PSAL"].values)).all()
        ledger = json.loads(ds.attrs["conversion_derived_variables"])
    assert ledger["POTDENS0"] == [
        "latitude",
        "longitude",
        "pressure",
        "salinity",
        "temperature",
    ]


def test_psal_from_conductivity_only_when_absent(sg005_og1):
    """With PSAL removed, it is recomputed from CNDC and says so; POTDENS0 follows from it."""
    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        ds = ds.load()
    original = ds["PSAL"].values.astype(float)
    ds = ds.drop_vars(["PSAL", "POTDENS0"])
    ds = _pipeline.add_teos10_variables(ds)
    assert "SP_from_C" in ds["PSAL"].attrs["comment"]
    assert "no thermal-inertia correction" in ds["PSAL"].attrs["comment"]
    assert "POTDENS0" in ds.variables
    assert not {"SA", "CT"} & set(ds.variables)
    import gsw

    expected = gsw.SP_from_C(
        *(ds[v].values.astype(float) for v in ("CNDC", "TEMP", "PRES"))
    )
    np.testing.assert_allclose(ds["PSAL"].values, expected, rtol=0, atol=1e-6)
    # Against the basestation's corrected salinity, within the thermal-inertia correction.
    mask = np.isfinite(original) & np.isfinite(ds["PSAL"].values)
    assert np.abs(ds["PSAL"].values[mask] - original[mask]).max() < 0.05


def test_missing_input_skips_with_info(sg005_og1, caplog):
    """Without LATITUDE no POTDENS0, and an INFO line says why."""
    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        ds = ds.load()
    ds = ds.drop_vars(["POTDENS0", "LATITUDE"])
    with caplog.at_level("INFO", logger="seagliderOG1._pipeline"):
        ds = _pipeline.add_teos10_variables(ds)
    assert "POTDENS0" not in ds.variables
    assert any(
        "POTDENS0 not derived: LATITUDE missing" in r.message for r in caplog.records
    )


def test_unexpected_units_are_refused(sg005_og1, caplog):
    """CNDC in S m-1 (not mS cm-1) is not fed to gsw; a WARNING names it."""
    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        ds = ds.load()
    ds = ds.drop_vars(["PSAL", "POTDENS0"])
    ds["CNDC"].attrs["units"] = "S m-1"
    with caplog.at_level("WARNING", logger="seagliderOG1._pipeline"):
        ds = _pipeline.add_teos10_variables(ds)
    assert "PSAL" not in ds.variables
    assert any(
        "CNDC ('S m-1', expected 'mS cm-1')" in r.message for r in caplog.records
    )


@pytest.mark.parametrize(("name", "units"), [("TEMP", "K"), ("PRES", "Pa")])
def test_inputs_in_other_units_are_refused(sg271_og1, caplog, name, units):
    """sg271's TEMP or PRES relabelled to other units: no POTDENS0, a WARNING names it."""
    with xr.open_dataset(sg271_og1, engine="netcdf4") as ds:
        ds = ds.load()
    ds = ds.drop_vars("POTDENS0")
    ds[name].attrs["units"] = units
    with caplog.at_level("WARNING", logger="seagliderOG1._pipeline"):
        ds = _pipeline.add_teos10_variables(ds)
    assert "POTDENS0" not in ds.variables
    assert any(f"{name} ('{units}'" in r.message for r in caplog.records)
