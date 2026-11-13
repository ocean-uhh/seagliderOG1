"""Storage types and fill values: the one post-concat dtype pass, and QC flags.

Data: the sg005 demo conversion and small hand-built arrays.
"""

import pathlib

import netCDF4
import numpy as np
import xarray as xr

from seagliderOG1 import _convert, _pipeline, readers, tools, writers

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]


# --- End to end ---------------------------------------------------------------------------


def test_output_dtypes_end_to_end(tmp_path: pathlib.Path) -> None:
    """Multi-dive conversion then write yields the intended on-disk dtypes and fills.

    Exercises the concat path: QC flags must be int8 in the written file (they were
    re-promoted to float when set_best_dtype ran per dive), and PROFILE_NUMBER keeps its
    -9999 fill through both set_best_dtype and the compression writer.
    """
    source = str(parent_dir / "data/demo_sg005")
    datasets = readers.read_mission(source, 1, 5)
    ds = _convert.convert(datasets)
    out = tmp_path / "out.nc"

    assert writers.write(ds, str(out)) == out

    with netCDF4.Dataset(out) as nc:
        assert nc.variables["TEMP_QC"].dtype == np.dtype("int8")
        assert nc.variables["PSAL_QC"].dtype == np.dtype("int8")
        assert nc.variables["PHASE"].dtype == np.dtype("int8")
        profile = nc.variables["PROFILE_NUMBER"]
        assert profile.dtype == np.dtype("int16")
        assert profile.getncattr("_FillValue") == -9999
        assert nc.variables["DEPTH"].dtype == np.dtype("float32")
        assert nc.variables["LATITUDE"].dtype == np.dtype("float64")


# --- Choosing a dtype ---------------------------------------------------------------------


def test_find_best_dtype_named_integers() -> None:
    """Named integer variables map to their fixed integer type."""
    da = xr.DataArray(np.arange(5.0))
    assert _pipeline.find_best_dtype("PHASE", da) == np.int8
    assert _pipeline.find_best_dtype("PROFILE_NUMBER", da) == np.int16
    assert _pipeline.find_best_dtype("VBD_MIN_CNTS", da) == np.int16


def test_find_best_dtype_qc_and_latlon() -> None:
    """QC variables become int8 (case-insensitive); lat/lon stay double."""
    da = xr.DataArray(np.arange(3.0))
    assert _pipeline.find_best_dtype("TEMP_QC", da) == np.int8
    assert _pipeline.find_best_dtype("temp_qc", da) == np.int8
    assert _pipeline.find_best_dtype("LATITUDE", da) == np.double
    assert _pipeline.find_best_dtype("LONGITUDE_GPS", da) == np.double


def test_find_best_dtype_raw_not_truncated() -> None:
    """A float variable whose name ends in 'raw' is not cast to int (clause removed)."""
    da = xr.DataArray(np.array([1.5, 2.5, 3.5]))
    assert _pipeline.find_best_dtype("optics_raw", da) == np.float32


def test_find_best_dtype_float64_to_float32() -> None:
    """Generic float64 variables downcast to float32."""
    assert _pipeline.find_best_dtype("TEMP", xr.DataArray(np.arange(3.0))) == np.float32


# --- Applying it --------------------------------------------------------------------------


def test_set_best_dtype_preserves_existing_fill_value() -> None:
    """An existing _FillValue sentinel is kept, not overwritten by the bit-width default."""
    da = xr.DataArray(
        np.array([1, 3, -9999], dtype="int64"), dims="x", name="PROFILE_NUMBER"
    )
    da.encoding["_FillValue"] = -9999
    ds = _pipeline.set_best_dtype(xr.Dataset({"PROFILE_NUMBER": da}))
    assert ds["PROFILE_NUMBER"].dtype == np.int16
    assert ds["PROFILE_NUMBER"].encoding["_FillValue"] == -9999
    assert "_FillValue" not in ds["PROFILE_NUMBER"].attrs


def test_set_best_dtype_skips_qc() -> None:
    """QC flags are left to convert_qc_flags; set_best_dtype adds no bit-width fill."""
    qc = xr.DataArray(np.array([1, 2, 6], dtype="int8"), dims="x", name="TEMP_QC")
    ds = _pipeline.set_best_dtype(xr.Dataset({"TEMP_QC": qc}))
    assert ds["TEMP_QC"].dtype == np.int8
    assert "_FillValue" not in ds["TEMP_QC"].encoding


def test_set_best_dtype_scalar_integer() -> None:
    """A scalar integer variable coerces without a 0-d indexing error."""
    ds = xr.Dataset({"VBD_MIN_CNTS": xr.DataArray(np.float64(500.0))})
    out = _pipeline.set_best_dtype(ds)
    assert out["VBD_MIN_CNTS"].dtype == np.int16


def test_set_best_dtype_restores_depth_coord() -> None:
    """DEPTH coerces to float32 and remains a coordinate."""
    ds = xr.Dataset(
        {"DEPTH": xr.DataArray(np.arange(4.0), dims="x", name="DEPTH")}
    ).set_coords("DEPTH")
    out = _pipeline.set_best_dtype(ds)
    assert out["DEPTH"].dtype == np.float32
    assert "DEPTH" in out.coords


# --- QC flags -----------------------------------------------------------------------------


def test_convert_qc_flags_orphan_parent():
    """A QC variable whose parent is absent gets a generic long_name, no KeyError."""
    # 'TEMP_QC2' has no 'TEMP_' parent (qc_name[:-3] strips only the '_QC' suffix).
    dsa = xr.Dataset({"TEMP_QC2": ("N_MEASUREMENTS", ["1", "1", "2"])})

    result = tools.convert_qc_flags(dsa, "TEMP_QC2")

    assert result["TEMP_QC2"].attrs["long_name"] == "quality flag"
    assert result["TEMP_QC2"].attrs["standard_name"] == "status_flag"
    assert result["TEMP_QC2"].dtype == np.int8
