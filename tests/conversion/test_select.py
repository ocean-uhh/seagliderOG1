"""Choosing which variables reach the file: keep_variables and drop_variables, and their
record in the conversion ledger.

Data: small hand-built datasets.
"""

import pathlib

import xarray as xr

from seagliderOG1 import _convert, readers

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]


# --- keep_variables -----------------------------------------------------------------------


def test_keep_variables_retains_mandatory_and_qc():
    """keep_variables keeps the ask plus every mandatory var and the kept var's _QC."""
    import warnings

    ds = xr.Dataset(
        {
            "TEMP": ("N", [1.0, 2.0]),
            "TEMP_QC": ("N", [1, 1]),
            "PSAL": ("N", [3.0, 4.0]),
            "GLIDE_SPEED": ("N", [0.1, 0.2]),
            "PLATFORM_SERIAL_NUMBER": ((), "sg005"),
            "WMO_IDENTIFIER": ((), "UNK"),
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = _convert.keep_variables(ds, ["TEMP"])
    assert "TEMP" in out.variables and "TEMP_QC" in out.variables  # ask + its QC
    assert "PLATFORM_SERIAL_NUMBER" in out.variables  # mandatory family
    assert "WMO_IDENTIFIER" in out.variables  # mandatory
    assert "PSAL" not in out.variables and "GLIDE_SPEED" not in out.variables  # dropped
    assert any("dropped" in str(w.message) for w in caught)


def test_keep_variables_records_dropped_in_ledger():
    """keep_variables writes dropped names to conversion_dropped_variables, adding across calls."""
    import json
    import warnings

    ds = xr.Dataset(
        {
            "TEMP": ("N", [1.0, 2.0]),
            "PSAL": ("N", [3.0, 4.0]),
            "GLIDE_SPEED": ("N", [0.1, 0.2]),
            "PLATFORM_SERIAL_NUMBER": ((), "sg005"),
        }
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        first = _convert.keep_variables(ds, ["TEMP", "PSAL"])  # drops GLIDE_SPEED
        second = _convert.keep_variables(first, ["TEMP"])  # then drops PSAL
    assert set(json.loads(first.attrs["conversion_dropped_variables"])) == {
        "GLIDE_SPEED"
    }
    # The second call adds to the list rather than replacing it.
    assert set(json.loads(second.attrs["conversion_dropped_variables"])) == {
        "GLIDE_SPEED",
        "PSAL",
    }


def test_keep_variables_keeps_source_ledger_complete():
    """On a converted file, keep_variables lists conversion_dropped_variables under derived."""
    import json
    import warnings

    ds = _convert.convert(
        readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        subset = _convert.keep_variables(ds, ["TEMP"])
    sources = json.loads(subset.attrs["conversion_attribute_sources"])
    assert "conversion_dropped_variables" in sources["derived"]
    # Still categorised exactly once across all categories.
    everywhere = [name for names in sources.values() for name in names]
    assert everywhere.count("conversion_dropped_variables") == 1


# --- drop_variables -----------------------------------------------------------------------


def test_drop_variables_removes_named_and_qc_protects_mandatory():
    """drop_variables removes the ask and its _QC, matches original_name, keeps mandatory."""
    import warnings

    ds = xr.Dataset(
        {
            "TEMP": ("N", [1.0, 2.0]),
            "TEMP_QC": ("N", [1, 1]),
            "gsw_sigma0": ("N", [27.0, 27.1]),
            "GLIDE_SPEED": ("N", [0.1, 0.2]),
            "TIME": ("N", [0.0, 1.0]),
        }
    )
    ds["GLIDE_SPEED"].attrs["original_name"] = "horz_speed"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = _convert.drop_variables(ds, ["gsw_sigma0", "horz_speed", "TEMP", "TIME"])
    assert "gsw_sigma0" not in out.variables  # by OG1 name
    assert "GLIDE_SPEED" not in out.variables  # by basestation original_name
    assert (
        "TEMP" not in out.variables and "TEMP_QC" not in out.variables
    )  # ask + its QC
    assert "TIME" in out.variables  # mandatory, never dropped
    assert any("mandatory" in str(w.message) for w in caught)


def test_drop_variables_records_dropped_in_ledger():
    """drop_variables writes removed names to conversion_dropped_variables."""
    import json
    import warnings

    ds = xr.Dataset({"gsw_sigma0": ("N", [27.0]), "TEMP": ("N", [1.0])})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = _convert.drop_variables(ds, ["gsw_sigma0"])
    assert "gsw_sigma0" not in out.variables
    assert set(json.loads(out.attrs["conversion_dropped_variables"])) == {"gsw_sigma0"}
