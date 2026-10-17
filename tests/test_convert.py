import pathlib
import sys

import netCDF4
import numpy as np
import xarray as xr

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import (  # noqa: E402  # import after sys.path bootstrap
    _pipeline,
    convert,
    readers,
    tools,
    writers,
)


def test_resolve_platform_serial_from_file():
    """Serial comes from platform_id; string fields fall back to UNK; depth omitted."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    resolved = convert._resolve_platform(ds, None)
    assert resolved["PLATFORM_SERIAL_NUMBER"] == "sg005"
    assert resolved["PLATFORM_MODEL"] == "UNK"
    assert resolved["WMO_IDENTIFIER"] == "UNK"
    assert "PLATFORM_DEPTH_RATING" not in resolved  # numeric: omitted, never "UNK"
    assert "platform_model_vocabulary" not in resolved


def test_resolve_platform_config_overrides_and_numeric_depth():
    """Config values override the file; numeric depth and model vocab are written."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {
        "PLATFORM_SERIAL_NUMBER": "orca",
        "PLATFORM_MODEL": "Slocum G3",
        "PLATFORM_DEPTH_RATING": 1000,
        "platform_model_vocabulary": "http://vocab.example/model",
    }
    resolved = convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_SERIAL_NUMBER"] == "orca"
    assert resolved["PLATFORM_MODEL"] == "Slocum G3"
    assert resolved["PLATFORM_DEPTH_RATING"] == 1000
    assert resolved["platform_model_vocabulary"] == "http://vocab.example/model"


def test_resolve_platform_missing_serial_raises():
    """No platform_id and no config serial is a hard error (it names the output)."""
    try:
        convert._resolve_platform(xr.Dataset(), None)
    except ValueError as exc:
        assert "PLATFORM_SERIAL_NUMBER" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing serial")


def test_get_contributors_demo_sg005_real_attrs():
    """demo_sg005: role-less creator kept + warned; PI alias; institution -> EDMO 1434."""
    import warnings

    ds = xr.Dataset(
        attrs={
            "creator_name": "Charlie Eriksen",
            "creator_email": "eriksen@uw.edu",
            "contributor_name": "Peter Rhines",
            "contributor_role": "Principal investigator",
            "institution": (
                "School of Oceanography\nUniversity of Washington\n"
                "Seattle, WA 98195-5351"
            ),
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        attrs = convert.get_contributors(ds)
    assert attrs["contributor_name"] == "Charlie Eriksen, Peter Rhines"
    assert attrs["contributor_role"] == ", PI"  # Eriksen role-less; Rhines normalised
    assert attrs["contributor_email"] == "eriksen@uw.edu, "
    assert (
        attrs["contributing_institutions"]
        == "University of Washington (School of Oceanography)"
    )
    assert (
        attrs["contributing_institutions_vocabulary"]
        == "https://edmo.seadatanet.org/report/1434"
    )
    assert any("no role for contributor" in str(w.message) for w in caught)


def test_get_contributors_config_fills_creator_role():
    """A config person matching the role-less creator gives one slot, email filled."""
    ds = xr.Dataset(
        attrs={"creator_name": "Charlie Eriksen", "creator_email": "eriksen@uw.edu"}
    )
    attrs = convert.get_contributors(
        ds, people=[{"name": "Charlie Eriksen", "role": "PI"}]
    )
    assert attrs["contributor_name"] == "Charlie Eriksen"
    assert attrs["contributor_role"] == "PI"
    assert attrs["contributor_email"] == "eriksen@uw.edu"


def test_global_attributes_collision_raises():
    """A global_attributes key that collides with a derived global is an error."""
    try:
        convert.to_og1([], global_attributes={"id": "x"})
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected ValueError for derived-global collision")


def test_start_date_global_attribute_collision_raises():
    """start_date is converter-derived (names id/TRAJECTORY); a config override is rejected."""
    try:
        convert.to_og1([], global_attributes={"start_date": "20080606T000000"})
    except ValueError as exc:
        assert "start_date" in str(exc)
    else:
        raise AssertionError("expected ValueError for start_date collision")


def test_to_og1_options_are_keyword_only():
    """A positional second argument is rejected; options must be keyword."""
    try:
        convert.to_og1([], {})
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for a positional option")


def test_name_mapping_returns_the_mapping_table():
    """name_mapping returns the basestation->OG1 table; a bare Dataset is rejected."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    mapping = convert.name_mapping(datasets)
    assert list(mapping.columns) == [
        "original_name",
        "OG1_name",
        "instrument",
        "instrument_type",
        "original_dimension",
        "has_og1_attributes",
    ]
    assert len(mapping) > 0
    assert "TIME" in set(mapping["OG1_name"])

    try:
        convert.name_mapping(datasets[0])
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError for a bare Dataset")


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
        out = convert.keep_variables(ds, ["TEMP"])
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
        first = convert.keep_variables(ds, ["TEMP", "PSAL"])  # drops GLIDE_SPEED
        second = convert.keep_variables(first, ["TEMP"])  # then drops PSAL
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

    ds = convert.to_og1(readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        subset = convert.keep_variables(ds, ["TEMP"])
    sources = json.loads(subset.attrs["conversion_attribute_sources"])
    assert "conversion_dropped_variables" in sources["derived"]
    # Still categorised exactly once across all categories.
    everywhere = [name for names in sources.values() for name in names]
    assert everywhere.count("conversion_dropped_variables") == 1


def test_process_dataset():

    ds1 = readers.load_sample_basestation()

    # test split_ds
    split_ds = tools.split_by_unique_dims(ds1)

    key_dims = list(split_ds.keys())
    key_dims.sort()
    assert key_dims == [(), ("gc_event",), ("gps_info",), ("sg_data_point",)]

    gps_info = split_ds[("gps_info",)]

    sg_cal, dc_log, dc_other = convert.extract_variables(split_ds[()])
    tmp = dc_log.log_GPS.values.tobytes().decode("utf-8")

    assert sg_cal["mass"].values > 50 and sg_cal["mass"].values < 60
    assert tmp == "$GPS,060608,183207,6124.849,-816.741,13,1.8,12,-8.8"

    ctd_dim, merge_dims, all_dims = _pipeline._get_merge_dimensions([ds1])

    # create og1_mapping for standardise_og1
    og1_mapping, time_variables = _pipeline.og1_name_mapping([ds1])

    merged_ds = _pipeline.merge_datasets_along_time(split_ds, time_variables)

    # Check initial variables are reformatted
    dsa = convert.standardise_og1(merged_ds, og1_mapping=og1_mapping)
    varlist = list(dsa.data_vars)
    coordlist = list(dsa.coords)
    combined_list = varlist + coordlist
    combined_list.sort()
    og1_varlist = [
        "TIME",
        "LATITUDE",
        "LONGITUDE",
        "TEMP",
        "DEPTH",
    ]
    for var in og1_varlist:
        assert var in combined_list

    ds_new = convert.add_gps_info_to_dataset(dsa, gps_info)
    assert "LATITUDE_GPS" in list(ds_new.variables)
    assert "LONGITUDE_GPS" in list(ds_new.variables)

    ds_new = tools.add_profile_number(ds_new, ds1)
    assert "PROFILE_NUMBER" in list(ds_new.variables)
    assert ds_new["PROFILE_NUMBER"].values.max() == 2 * ds1.attrs["dive_number"]

    ds_new = tools.add_depth(ds_new)
    meanZ = ds_new["DEPTH_Z"].mean().item()
    meanZpos = ds_new["DEPTH"].mean().item()
    assert abs(meanZ + meanZpos) < 10


def test_output_dtypes_end_to_end(tmp_path: pathlib.Path) -> None:
    """Multi-dive conversion then write yields the intended on-disk dtypes and fills.

    Exercises the concat path: QC flags must be int8 in the written file (they were
    re-promoted to float when set_best_dtype ran per dive), and PROFILE_NUMBER keeps its
    -9999 fill through both set_best_dtype and the compression writer.
    """
    source = str(parent_dir / "data/demo_sg005")
    datasets = readers.read_mission(source, 1, 5)
    ds = convert.to_og1(datasets)
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


def test_check_required_globals_raises_on_missing_mandatory():
    """A missing mandatory global raises MetadataError naming the gap."""
    from seagliderOG1 import vocabularies

    attrs = dict.fromkeys(vocabularies.REQUIRED_GLOBALS["mandatory"], "x")
    del attrs["id"]
    try:
        convert._check_required_globals(attrs)
    except convert.MetadataError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected MetadataError for a missing mandatory global")


def test_check_required_globals_treats_placeholder_as_unset():
    """An empty string or the literal 'null@null.com' counts as missing."""
    from seagliderOG1 import vocabularies

    attrs = dict.fromkeys(vocabularies.REQUIRED_GLOBALS["mandatory"], "x")
    attrs["title"] = ""
    attrs["Conventions"] = "null"
    try:
        convert._check_required_globals(attrs)
    except convert.MetadataError as exc:
        assert "title" in str(exc) and "Conventions" in str(exc)
    else:
        raise AssertionError("expected MetadataError for placeholder globals")


def test_converted_globals_carry_no_placeholder():
    """Conversion never writes '', 'null' or 'null@null.com' into a global attribute."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    placeholders = {"", "null", "null@null.com", "None"}
    offenders = {
        key: value
        for key, value in ds.attrs.items()
        if isinstance(value, str) and value.strip() in placeholders
    }
    assert offenders == {}, offenders
    # The misspelt placeholder key is gone; featureType/Conventions match the manual.
    assert "contributer_email" not in ds.attrs
    assert ds.attrs["featureType"] == "trajectory"
    assert ds.attrs["Conventions"] == "CF-1.10, ACDD-1.3, OG-1.0"
    assert ds.attrs["date_created"]  # mandatory, always present and non-empty


def test_deployment_globals_are_written():
    """deployment: block values become globals; a null deployment key is skipped."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = convert.to_og1(
        datasets,
        deployment={
            "program": "MOOSE",
            "license": "CC-BY-4.0",
            "doi": "https://doi.org/10.0000/x",
            "network": None,
        },
    )
    assert ds.attrs["program"] == "MOOSE"
    assert ds.attrs["license"] == "CC-BY-4.0"
    assert ds.attrs["doi"] == "https://doi.org/10.0000/x"
    assert "network" not in ds.attrs  # null deployment key is skipped


def test_deployment_id_overrides_derived_with_warning():
    """deployment.id replaces the derived id and warns, naming both values."""
    import warnings

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ds = convert.to_og1(datasets, deployment={"id": "my_custom_id"})
    assert ds.attrs["id"] == "my_custom_id"
    assert any("deployment.id overrides" in str(w.message) for w in caught)


def test_global_attributes_refuses_a_deployment_key():
    """A global_attributes key with a structured home in deployment: is an error."""
    try:
        convert.to_og1([], global_attributes={"program": "x"})
    except ValueError as exc:
        assert "program" in str(exc) and "deployment" in str(exc)
    else:
        raise AssertionError("expected ValueError for a deployment key in globals")


def test_global_attributes_null_reserved_key_is_tolerated():
    """A legacy v1 template listing reserved keys as null still converts (nulls skipped)."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    # project/program have a deployment home, date_created is derived; all null -> no collision.
    ds = convert.to_og1(
        datasets,
        global_attributes={"project": None, "program": None, "date_created": None},
    )
    assert "conversion_attribute_sources" in ds.attrs  # converted, did not raise


def test_deployment_unknown_key_raises():
    """An unknown deployment: key is rejected, naming the key."""
    try:
        convert.to_og1([], deployment={"nonsense": "x"})
    except ValueError as exc:
        assert "nonsense" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown deployment key")


def test_literal_null_platform_value_is_treated_as_unset():
    """A literal 'null'/'null@null.com' string counts as unset, like None (one rule)."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {"PLATFORM_MODEL": "null", "PLATFORM_NAME": "null@null.com"}
    resolved = convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_MODEL"] == "UNK"  # "null" is unset -> UNK, not literal
    assert "PLATFORM_NAME" not in resolved  # optional, unset -> omitted
    assert convert._is_empty("null") and convert._is_empty("null@null.com")


def test_resolve_platform_optional_fields_omitted_when_null():
    """Optional platform variables are absent from the resolved dict when unset."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    resolved = convert._resolve_platform(ds, None)
    for field in convert.OPTIONAL_PLATFORM_VARS:
        assert field not in resolved
    assert "platform_maker_vocabulary" not in resolved


def test_resolve_platform_optional_fields_written_when_set():
    """A supplied optional platform field (and the maker vocabulary) is resolved."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {
        "PLATFORM_NAME": "Orca",
        "TELECOM_TYPE": "Iridium",
        "platform_maker_vocabulary": "http://vocab.example/maker",
    }
    resolved = convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_NAME"] == "Orca"
    assert resolved["TELECOM_TYPE"] == "Iridium"
    assert resolved["platform_maker_vocabulary"] == "http://vocab.example/maker"
    assert "BATTERY_TYPE" not in resolved  # still unset


def test_optional_platform_variables_written_with_long_name_and_vocab():
    """Set optional platform fields become variables with long_name and vocabulary."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = convert.to_og1(
        datasets,
        platform={
            "PLATFORM_SERIAL_NUMBER": "sg005",
            "PLATFORM_MODEL": "M1",
            "PLATFORM_MAKER": "University of Washington",
            "PLATFORM_NAME": "Orca",
            "TELECOM_TYPE": "Iridium",
            "platform_maker_vocabulary": "http://vocab.example/maker",
        },
    )
    assert str(ds["PLATFORM_NAME"].values) == "Orca"
    assert ds["PLATFORM_NAME"].attrs["long_name"] == "Local or nickname of the glider"
    assert str(ds["TELECOM_TYPE"].values) == "Iridium"
    assert "telecom_type.md" in ds["TELECOM_TYPE"].attrs["telecom_type_vocabulary"]
    assert "BATTERY_TYPE" not in ds.variables  # unset -> not written
    assert (
        ds["PLATFORM_MAKER"].attrs["platform_maker_vocabulary"]
        == "http://vocab.example/maker"
    )


def test_conversion_attribute_sources_ledger():
    """Every written global is in exactly one ledger category; an override shows up."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = convert.to_og1(datasets, deployment={"program": "MOOSE", "id": "custom_id"})
    ledger = json.loads(ds.attrs["conversion_attribute_sources"])
    written = [k for k in ds.attrs if k != "conversion_attribute_sources"]
    categorised = [name for names in ledger.values() for name in names]
    assert sorted(categorised) == sorted(written)  # covers every written global
    assert len(categorised) == len(set(categorised))  # each in exactly one category
    assert "id" in ledger["overridden"]  # deployment.id replaced the derived id
    assert "contributor_name" in ledger["mixed"]  # config/file blend, not guessed
    assert "title" in ledger["package"]
    assert "start_date" in ledger["derived"]


def test_original_name_on_every_basestation_variable():
    """Each renamed or passed-through variable records its basestation name; derived ones are listed."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    derived = set(json.loads(ds.attrs["conversion_derived_variables"]))
    for name in ds.variables:
        named = "original_name" in ds[name].attrs
        # A variable is either a basestation variable (named) or a listed derived one,
        # never both and never neither — so a missing original_name is always a bug.
        assert named != (name in derived), name
    # Renaming actually happened (original_name differs from the OG1 name) ...
    renamed = [
        n for n in ds.variables if ds[n].attrs.get("original_name") not in (None, n)
    ]
    assert renamed
    # ... and the pre-0.1.0 attribute spelling is gone.
    assert all("original_variable_name" not in ds[n].attrs for n in ds.variables)


def test_conversion_dimensions_ledger():
    """conversion_dimensions records each dimension's fate and the variables it carried."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    dims = json.loads(ds.attrs["conversion_dimensions"])
    # The CTD dimension is the backbone that becomes N_MEASUREMENTS.
    assert dims["sg_data_point"]["fate"] == "backbone"
    # gps_info is merged (its fixes are placed on the backbone by a dedicated path),
    # not skipped, and its basestation variables are named.
    assert dims["gps_info"]["fate"] == "merged"
    assert "log_gps_lat" in dims["gps_info"]["variables"]
    # A skipped dimension leaves nothing in the file, so its variables are recorded here.
    skipped = {d: info for d, info in dims.items() if info["fate"] == "skipped"}
    assert skipped
    assert all(info["variables"] for info in skipped.values())


def test_basestation_comment_is_kept_not_renamed():
    """A basestation comment is carried to the output unchanged, not folded into history."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    datasets[0].attrs["comment"] = "deployed off the shelf break"
    ds = convert.to_og1(datasets)
    assert ds.attrs.get("comment") == "deployed off the shelf break"
    assert "deployed off the shelf break" not in ds.attrs["history"]


def test_history_is_one_provenance_line():
    """to_og1 writes history as a single conversion provenance line, not the basestation log."""
    import re

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    base = datasets[0].attrs["history"].strip()
    ds = convert.to_og1(datasets)
    history = ds.attrs["history"].strip()
    # Exactly one line, and not the multi-line basestation per-dive QC log.
    assert "\n" not in history
    assert history != base
    # Its shape is asserted, never its timestamp value (not reproducible).
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 seagliderOG1 \S+: "
        r"basestation to OG1 \(to_og1\)$",
        history,
    )


def test_scalar_parameters_storage_and_dimension():
    """Scalars declare storage_type and carry no empty original_dimension; per-dive JSON decodes."""
    import json

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    # No variable carries an empty original_dimension placeholder (it is omitted instead).
    assert all(ds[v].attrs.get("original_dimension", "x") != "" for v in ds.variables)
    # Both scalar cases declare their storage, so the ledger view infers nothing.
    per_dive = [
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "per_dive_scalar"
    ]
    constants = [
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "constant_scalar"
    ]
    assert per_dive and constants
    # A per-dive JSON scalar decodes to the converted dive numbers.
    payload = json.loads(str(ds[per_dive[0]].values))
    assert sorted(payload["dives"]) == [1, 2]
    assert len(payload["values"]) == len(payload["dives"])


def test_conversion_ledger_parses_the_file():
    """conversion_ledger returns the parsed ledger; a pre-ledger file raises MetadataError."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ledger = convert.conversion_ledger(convert.to_og1(datasets))
    assert set(ledger) == {
        "dimensions",
        "derived",
        "dropped",
        "removed",
        "input_variable_count",
        "attribute_sources",
        "history",
        "scalar_parameters",
    }
    assert ledger["dimensions"]["sg_data_point"]["fate"] == "backbone"
    # derived is a map {name: [source basestation names]}; removed is the drop list.
    assert isinstance(ledger["derived"], dict)
    assert ledger["input_variable_count"] > 0
    assert "density" in ledger["removed"]  # a VARIABLES_TO_DROP member present in sg005
    # Derived variables record their basestation sources: every merged dimension's time
    # variable folds into the shared TIME axis; TIME_GPS records the GPS clock separately.
    assert set(ledger["derived"]["TIME"]) == {
        "ctd_time",
        "time",
        "gc_st_secs",
        "log_gps_time",
    }
    assert ledger["derived"]["TIME_GPS"] == ["log_gps_time"]
    per_dive = [
        name
        for name, entry in ledger["scalar_parameters"].items()
        if entry["storage"] == "per_dive_scalar"
    ]
    assert per_dive
    assert sorted(ledger["scalar_parameters"][per_dive[0]]["dives"]) == [1, 2]
    try:
        convert.conversion_ledger(readers.load_sample_basestation())
    except convert.MetadataError:
        pass
    else:
        raise AssertionError("expected MetadataError on a pre-ledger file")


def test_reconciliation_fates_sum_to_input_count():
    """Every basestation variable has exactly one fate; the six buckets sum to the input count."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    inputs = {str(v) for ds in datasets for v in ds.variables}
    ds = convert.to_og1(datasets)
    ledger = convert.conversion_ledger(ds)
    renamed = {
        str(ds[n].attrs["original_name"])
        for n in ds.variables
        if ds[n].attrs.get("original_name") not in (None, n)
    }
    passed = {str(n) for n in ds.variables if ds[n].attrs.get("original_name") == n}
    consumed = {s for sources in ledger["derived"].values() for s in sources}
    removed = set(ledger["removed"])
    dropped = set(ledger["dropped"])
    skipped = {
        v
        for info in ledger["dimensions"].values()
        if info["fate"] == "skipped"
        for v in info["variables"]
    }
    # One fate per name, resolved in the same priority order as the reconciliation page.
    seen: set[str] = set()
    total = 0
    for names in (renamed, passed, consumed, removed, dropped, skipped):
        total += len(names - seen)
        seen |= names
    assert total == ledger["input_variable_count"] == len(inputs)
    # gc_event is merged (its variables reach the output), so its time variable feeds the
    # shared TIME axis; it is consumed, not skipped.
    assert "gc_st_secs" in consumed and "gc_st_secs" not in skipped


def test_dimension_fate_agrees_with_output_variables():
    """A dimension's fate is read from the output: merged iff a variable survives on it."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    dims = convert.conversion_ledger(ds)["dimensions"]
    in_output = {
        str(ds[n].attrs["original_dimension"])
        for n in ds.variables
        if "original_dimension" in ds[n].attrs
    }
    for dim, info in dims.items():
        if info["fate"] in ("backbone", "merged"):
            assert dim in in_output, (
                f"{dim} is {info['fate']} but no output variable carries it"
            )
        else:
            assert dim not in in_output, (
                f"{dim} is skipped but a variable survived on it"
            )
    # gc_event in demo_sg005 is merged by this rule (its gc_* variables reach the axis).
    assert dims["gc_event"]["fate"] == "merged"


def test_derived_sources_stamp_never_reaches_the_file(tmp_path: pathlib.Path) -> None:
    """The transient _derived_sources attr is consumed into the ledger, not written to disk."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = convert.to_og1(datasets)
    assert not [
        n for n in ds.variables if _pipeline.DERIVED_SOURCES_ATTR in ds[n].attrs
    ]
    out = tmp_path / "og1.nc"
    writers.write(ds, str(out), overwrite=True)
    reopened = xr.open_dataset(str(out), engine="netcdf4", decode_timedelta=False)
    try:
        leaked = [
            n
            for n in reopened.variables
            if _pipeline.DERIVED_SOURCES_ATTR in reopened[n].attrs
        ]
    finally:
        reopened.close()
    assert not leaked


def test_start_date_is_earliest_time_regardless_of_input_order():
    """start_date/id/TRAJECTORY come from the earliest TIME, not the input order."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 3)
    forward = convert.to_og1(datasets)
    reverse = convert.to_og1(list(reversed(datasets)))
    # start_date is the deployment time and agrees with the first measurement time.
    assert forward.attrs["start_date"] == forward.attrs["time_coverage_start"]
    # The identity globals are stable under a permutation of the input.
    assert reverse.attrs["start_date"] == forward.attrs["start_date"]
    assert reverse.attrs["id"] == forward.attrs["id"]
    assert str(reverse["TRAJECTORY"].values) == str(forward["TRAJECTORY"].values)
