"""Mission metadata in the file: platform variables, deployment, contributors and
institutions, global attributes and history.

Data: the sg005 demo and its mission.yaml.
"""

import json
import pathlib

import numpy as np
import pytest
import xarray as xr

from seagliderOG1 import _convert, readers
from seagliderOG1.reports import _record

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]
_SG005 = parent_dir / "data/demo_sg005"


# --- Platform -----------------------------------------------------------------------------


def test_resolve_platform_serial_from_file():
    """Serial comes from platform_id; string fields fall back to UNK; depth omitted."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    resolved = _convert._resolve_platform(ds, None)
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
    resolved = _convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_SERIAL_NUMBER"] == "orca"
    assert resolved["PLATFORM_MODEL"] == "Slocum G3"
    assert resolved["PLATFORM_DEPTH_RATING"] == 1000
    assert resolved["platform_model_vocabulary"] == "http://vocab.example/model"


def test_resolve_platform_optional_fields_written_when_set():
    """A supplied optional platform field (and the maker vocabulary) is resolved."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {
        "PLATFORM_NAME": "Orca",
        "TELECOM_TYPE": "Iridium",
        "platform_maker_vocabulary": "http://vocab.example/maker",
    }
    resolved = _convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_NAME"] == "Orca"
    assert resolved["TELECOM_TYPE"] == "Iridium"
    assert resolved["platform_maker_vocabulary"] == "http://vocab.example/maker"
    assert "BATTERY_TYPE" not in resolved  # still unset


def test_resolve_platform_optional_fields_omitted_when_null():
    """Optional platform variables are absent from the resolved dict when unset."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    resolved = _convert._resolve_platform(ds, None)
    for field in _convert.OPTIONAL_PLATFORM_VARS:
        assert field not in resolved
    assert "platform_maker_vocabulary" not in resolved


def test_optional_platform_variables_written_with_long_name_and_vocab():
    """Set optional platform fields become variables with long_name and vocabulary."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(
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


def test_bundled_example_writes_platform_vocabularies(tmp_path: pathlib.Path) -> None:
    """The sg005 example config's platform vocabulary terms reach the written file."""
    import yaml

    config = yaml.safe_load((_SG005 / "mission.yaml").read_text(encoding="utf-8"))
    path = _convert._convert_mission(
        _SG005,
        tmp_path,
        dives=(1, 1),
        contributors=config["contributors"],
        institutions=config["institutions"],
        platform=config["platform"],
    )
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        assert (
            ds["PLATFORM_MODEL"].attrs["platform_model_vocabulary"]
            == (config["platform"]["platform_model_vocabulary"])
        )
        assert (
            ds["PLATFORM_MAKER"]
            .attrs["platform_maker_vocabulary"]
            .endswith("/B75/current/ORG00142/")
        )


def test_renamed_serial_records_the_basestation_value_in_a_comment():
    """A config serial that renames the basestation platform_id is noted in a comment."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(datasets, platform={"PLATFORM_SERIAL_NUMBER": "orca"})
    assert str(ds["PLATFORM_SERIAL_NUMBER"].values) == "orca"
    assert "sg005" in ds["PLATFORM_SERIAL_NUMBER"].attrs["comment"]


def test_unrenamed_serial_has_no_override_comment():
    """When the config serial matches the basestation value, no override comment is written."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(datasets, platform={"PLATFORM_SERIAL_NUMBER": "sg005"})
    assert "comment" not in ds["PLATFORM_SERIAL_NUMBER"].attrs


def test_literal_null_platform_value_is_treated_as_unset():
    """A literal 'null'/'null@null.com' string counts as unset, like None (one rule)."""
    ds = xr.Dataset(attrs={"platform_id": "SG005"})
    platform = {"PLATFORM_MODEL": "null", "PLATFORM_NAME": "null@null.com"}
    resolved = _convert._resolve_platform(ds, platform)
    assert resolved["PLATFORM_MODEL"] == "UNK"  # "null" is unset -> UNK, not literal
    assert "PLATFORM_NAME" not in resolved  # optional, unset -> omitted
    assert _convert._is_empty("null") and _convert._is_empty("null@null.com")


def test_resolve_platform_missing_serial_raises():
    """No platform_id and no config serial is a hard error (it names the output)."""
    try:
        _convert._resolve_platform(xr.Dataset(), None)
    except ValueError as exc:
        assert "PLATFORM_SERIAL_NUMBER" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing serial")


# --- Deployment ---------------------------------------------------------------------------


def test_deployment_globals_are_written():
    """Global-section values become globals; a null one is skipped; globals elsewhere too."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(
        datasets,
        deployment={
            "license": "CC-BY-4.0",
            "doi": "https://doi.org/10.0000/x",
            "site": None,
        },
        global_attributes={"program": "MOOSE"},
    )
    assert ds.attrs["program"] == "MOOSE"  # program is an ordinary global now
    assert ds.attrs["license"] == "CC-BY-4.0"
    assert ds.attrs["doi"] == "https://doi.org/10.0000/x"
    assert "site" not in ds.attrs  # null section value is skipped


def test_deployment_information_overrides_the_derived_fix() -> None:
    """A deployment_information block sets DEPLOYMENT_* instead of the first in-water fix."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    ds = _convert.convert(
        datasets,
        deployment_information={
            "DEPLOYMENT_TIME": "2008-06-06T00:00:00Z",  # before the first sample (18:06:18)
            "DEPLOYMENT_LATITUDE": -60.0,
            "DEPLOYMENT_LONGITUDE": -8.0,
        },
    )
    assert float(ds["DEPLOYMENT_LATITUDE"]) == -60.0
    assert float(ds["DEPLOYMENT_LONGITUDE"]) == -8.0
    assert (
        np.datetime_as_string(ds["DEPLOYMENT_TIME"].values, unit="s")
        == "2008-06-06T00:00:00"
    )


def test_deployment_id_overrides_derived_with_warning():
    """deployment.id replaces the derived id and warns, naming both values."""
    import warnings

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ds = _convert.convert(datasets, deployment={"id": "my_custom_id"})
    assert ds.attrs["id"] == "my_custom_id"
    assert any("identity_and_discovery.id overrides" in str(w.message) for w in caught)


def test_deployment_time_after_first_sample_warns() -> None:
    """A DEPLOYMENT_TIME later than the first data sample warns (it should precede the data)."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    with pytest.warns(UserWarning, match="after the first data sample"):
        _convert.convert(
            datasets,
            deployment_information={"DEPLOYMENT_TIME": "2008-06-07T00:00:00Z"},
        )


def test_deployment_unknown_key_raises():
    """An unknown deployment: key is rejected, naming the key."""
    try:
        _convert.convert([], deployment={"nonsense": "x"})
    except ValueError as exc:
        assert "nonsense" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown deployment key")


def test_deployment_time_without_timezone_is_refused() -> None:
    """A naive DEPLOYMENT_TIME is refused, not silently assumed UTC."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    with pytest.raises(_convert.MetadataError, match="must carry a timezone"):
        _convert.convert(
            datasets,
            deployment_information={"DEPLOYMENT_TIME": "2008-06-06T00:00:00"},
        )


# --- Contributors and institutions --------------------------------------------------------


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
        attrs = _convert.get_contributors(ds)
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
    attrs = _convert.get_contributors(
        ds, people=[{"name": "Charlie Eriksen", "role": "PI"}]
    )
    assert attrs["contributor_name"] == "Charlie Eriksen"
    assert attrs["contributor_role"] == "PI"
    assert attrs["contributor_email"] == "eriksen@uw.edu"


def test_get_contributors_drops_the_file_institution_with_config_institutions():
    """With config institutions the basestation institution text is not written."""
    ds = xr.Dataset(
        attrs={
            "institution": (
                "School of Oceanography\nUniversity of Washington\n"
                "Seattle, WA 98195-5351"
            )
        }
    )
    attrs = _convert.get_contributors(
        ds, institutions=[{"name": "No Such Institute", "role": "Operator"}]
    )
    assert attrs["contributing_institutions"] == "No Such Institute"
    assert attrs["contributing_institutions_role"] == "Operator"


def test_sidecar_records_the_file_institution_and_its_registry_match(
    sg005_og1: pathlib.Path,
) -> None:
    """demo_sg005's postal-address institution resolves to EDMO 1434 in the sidecar."""
    assert _record.conversion_sidecar(sg005_og1)["institution_from_file"] == {
        "text": "School of Oceanography\nUniversity of Washington\nSeattle, WA 98195-5351",
        "name": "University of Washington (School of Oceanography)",
        "id": "https://edmo.seadatanet.org/report/1434",
    }
    assert _convert._institution_from_file({}) is None
    assert _convert._institution_from_file({"institution": "Nowhere"}) == {
        "text": "Nowhere",
        "name": None,
        "id": None,
    }


# --- Global attributes --------------------------------------------------------------------


def test_derived_acdd_globals_from_the_data():
    """geospatial_bounds, geospatial_vertical_positive and time_coverage_duration are derived."""
    import json
    import re

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
    # Bounding-box polygon, latitude first (EPSG:4326 axis order): corners match the min/max.
    assert ds.attrs["geospatial_bounds"] == (
        "POLYGON (("
        f"{ds.attrs['geospatial_lat_max']:.6f} {ds.attrs['geospatial_lon_min']:.6f}, "
        f"{ds.attrs['geospatial_lat_max']:.6f} {ds.attrs['geospatial_lon_max']:.6f}, "
        f"{ds.attrs['geospatial_lat_min']:.6f} {ds.attrs['geospatial_lon_max']:.6f}, "
        f"{ds.attrs['geospatial_lat_min']:.6f} {ds.attrs['geospatial_lon_min']:.6f}, "
        f"{ds.attrs['geospatial_lat_max']:.6f} {ds.attrs['geospatial_lon_min']:.6f}))"
    )
    # "down" only because DEPTH increases downward (positive mean); the label follows the sign.
    assert np.nanmean(ds.DEPTH.values) > 0
    assert ds.attrs["geospatial_vertical_positive"] == "down"
    # ISO 8601 duration, e.g. P1DT2H3M4.5S.
    assert re.fullmatch(r"P\d+DT\d+H\d+M[\d.]+S", ds.attrs["time_coverage_duration"])
    sources = json.loads(ds.attrs["conversion_attribute_sources"])
    assert {
        "geospatial_bounds",
        "geospatial_vertical_positive",
        "time_coverage_duration",
    } <= set(sources["derived"])


def test_start_date_is_earliest_time_regardless_of_input_order():
    """start_date/id/TRAJECTORY come from the earliest TIME, not the input order."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 3)
    forward = _convert.convert(datasets)
    reverse = _convert.convert(list(reversed(datasets)))
    # start_date is the deployment time and agrees with the first measurement time.
    assert forward.attrs["start_date"] == forward.attrs["time_coverage_start"]
    # The identity globals are stable under a permutation of the input.
    assert reverse.attrs["start_date"] == forward.attrs["start_date"]
    assert reverse.attrs["id"] == forward.attrs["id"]
    assert str(reverse["TRAJECTORY"].values) == str(forward["TRAJECTORY"].values)


def test_date_created_is_the_conversion_time_in_utc(tmp_path: pathlib.Path) -> None:
    """date_created is this file's creation (UTC), not the basestation files' 2014 date."""
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC).replace(microsecond=0)
    path = _convert._convert_mission(_SG005, tmp_path, dives=(1, 1))
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        created = datetime.strptime(ds.attrs["date_created"], "%Y%m%dT%H%M%S")
        assert ds.attrs["date_modified"] == ds.attrs["date_created"]
        ledger = json.loads(ds.attrs["conversion_attribute_sources"])
    created = created.replace(tzinfo=UTC)
    assert start <= created <= datetime.now(UTC) + timedelta(seconds=1)
    assert "date_created" in ledger["derived"]


def test_history_is_one_provenance_line():
    """to_og1 writes history as a single conversion provenance line, not the basestation log."""
    import re

    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    base = datasets[0].attrs["history"].strip()
    ds = _convert.convert(datasets)
    history = ds.attrs["history"].strip()
    # Exactly one line, and not the multi-line basestation per-dive QC log.
    assert "\n" not in history
    assert history != base
    # Its shape is asserted, never its timestamp value (not reproducible).
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 seagliderOG1 \S+: "
        r"basestation to OG1 \(convert\)$",
        history,
    )


def test_converted_globals_carry_no_placeholder():
    """Conversion never writes '', 'null' or 'null@null.com' into a global attribute."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 2)
    ds = _convert.convert(datasets)
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


def test_global_attributes_null_reserved_key_is_tolerated():
    """A legacy v1 template listing reserved keys as null still converts (nulls skipped)."""
    datasets = readers.read_mission(str(parent_dir / "data/demo_sg005"), 1, 1)
    # project/program have a deployment home, date_created is derived; all null -> no collision.
    ds = _convert.convert(
        datasets,
        global_attributes={"project": None, "program": None, "date_created": None},
    )
    assert "conversion_attribute_sources" in ds.attrs  # converted, did not raise


def test_check_required_globals_treats_placeholder_as_unset():
    """An empty string or the literal 'null@null.com' counts as missing."""
    from seagliderOG1 import vocabularies

    attrs = dict.fromkeys(vocabularies.REQUIRED_GLOBALS["mandatory"], "x")
    attrs["title"] = ""
    attrs["Conventions"] = "null"
    try:
        _convert._check_required_globals(attrs)
    except _convert.MetadataError as exc:
        assert "title" in str(exc) and "Conventions" in str(exc)
    else:
        raise AssertionError("expected MetadataError for placeholder globals")


def test_check_required_globals_raises_on_missing_mandatory():
    """A missing mandatory global raises MetadataError naming the gap."""
    from seagliderOG1 import vocabularies

    attrs = dict.fromkeys(vocabularies.REQUIRED_GLOBALS["mandatory"], "x")
    del attrs["id"]
    try:
        _convert._check_required_globals(attrs)
    except _convert.MetadataError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected MetadataError for a missing mandatory global")


def test_global_attributes_collision_raises():
    """A global_attributes key that collides with a derived global is an error."""
    try:
        _convert.convert([], global_attributes={"id": "x"})
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("expected ValueError for derived-global collision")


def test_start_date_global_attribute_collision_raises():
    """start_date is converter-derived (names id/TRAJECTORY); a config override is rejected."""
    try:
        _convert.convert([], global_attributes={"start_date": "20080606T000000"})
    except ValueError as exc:
        assert "start_date" in str(exc)
    else:
        raise AssertionError("expected ValueError for start_date collision")


def test_global_attributes_refuses_a_sectioned_key():
    """A global_attributes key with a structured home in a section is an error, naming it."""
    try:
        _convert.convert([], global_attributes={"doi": "x"})
    except ValueError as exc:
        assert "doi" in str(exc) and "rights_and_access:" in str(exc)
    else:
        raise AssertionError("expected ValueError for a sectioned key in globals")
