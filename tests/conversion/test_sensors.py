"""Sensors: the SENSOR_* records, the calibration-comment parser, and the sensors: block of
mission.yaml.

Data: tests/data/calibcomm_answers.csv (the parser's answer table), the sg271 sample, the
sg005 demo; one test needs the dev pack.
"""

import csv
import datetime
import pathlib

import pandas as pd
import pytest
import xarray as xr

from seagliderOG1 import _convert, _pipeline, readers, vocabularies
from seagliderOG1._pipeline import parse_calibcomm

script_dir = pathlib.Path(__file__).parent.parent.absolute()
parent_dir = script_dir.parents[0]
_SG005 = parent_dir / "data/demo_sg005"
ANSWERS = pathlib.Path(__file__).parent.parent / "data" / "calibcomm_answers.csv"
ROWS = list(csv.DictReader(ANSWERS.open(encoding="utf-8")))
SG271 = (
    pathlib.Path(__file__).parent.resolve().parent.parent
    / "seagliderOG1"
    / "data"
    / "sg271"
)
SG005 = pathlib.Path(__file__).parent.resolve().parent.parent / "data" / "demo_sg005"


def _open(folder):
    import xarray as xr

    return [xr.open_dataset(p, engine="netcdf4") for p in sorted(folder.glob("p*.nc"))]


# --- Sensor records -----------------------------------------------------------------------


def test_add_sensor_skips_unmapped_variables():
    """A mapping row whose OG1_name is None is skipped, not looked up as 'None'."""
    ds = xr.Dataset({"TEMP": ("N_MEASUREMENTS", [1.0, 2.0])})
    sensor_dict = {
        "sbe41": {
            "sensor_type": "CTD",
            "sensor_serial_number": "245201",
            "sensor_model": "Sea-Bird SBE 41 CTD",
        }
    }
    og1_mapping = pd.DataFrame(
        [
            {"OG1_name": "TEMP", "instrument": "sbe41"},
            {"OG1_name": None, "instrument": "sbe41"},
        ]
    )

    result = _pipeline.add_sensor_to_dataset(ds, sensor_dict, og1_mapping)

    assert result["TEMP"].attrs["sensor"] == "SENSOR_CTD_245201"
    assert "SENSOR_CTD_245201" in result.variables


def test_add_sensor_skips_instrument_absent_from_sensor_dict():
    """A mapping row naming an instrument not in sensor_dict is skipped, not looked up."""
    ds = xr.Dataset(
        {
            "TEMP": ("N_MEASUREMENTS", [1.0, 2.0]),
            "PRES2": ("N_MEASUREMENTS", [3.0, 4.0]),
        }
    )
    sensor_dict = {
        "sbe41": {
            "sensor_type": "CTD",
            "sensor_serial_number": "245201",
            "sensor_model": "Sea-Bird SBE 41 CTD",
        }
    }
    # gather_sensor_info omits 'magnetometer', but the mapping still names it.
    og1_mapping = pd.DataFrame(
        [
            {"OG1_name": "TEMP", "instrument": "sbe41"},
            {"OG1_name": "PRES2", "instrument": "magnetometer"},
        ]
    )

    result = _pipeline.add_sensor_to_dataset(ds, sensor_dict, og1_mapping)

    assert result["TEMP"].attrs["sensor"] == "SENSOR_CTD_245201"
    assert "sensor" not in result["PRES2"].attrs


def test_add_sensor_skips_instrument_without_catalogue_entry():
    """An instrument present in sensor_dict but with no sensor_type (unknown key) is skipped."""
    ds = xr.Dataset(
        {
            "TEMP": ("N_MEASUREMENTS", [1.0, 2.0]),
            "PRES2": ("N_MEASUREMENTS", [3.0, 4.0]),
        }
    )
    # 'wlbb2f' has no catalogue entry, so gather_sensor_info leaves it as {} (no
    # sensor_type); a mapping row still names it. It must be skipped, not looked up.
    sensor_dict = {
        "sbe41": {
            "sensor_type": "CTD",
            "sensor_serial_number": "245201",
            "sensor_model": "Sea-Bird SBE 41 CTD",
        },
        "wlbb2f": {},
    }
    og1_mapping = pd.DataFrame(
        [
            {"OG1_name": "TEMP", "instrument": "sbe41"},
            {"OG1_name": "PRES2", "instrument": "wlbb2f"},
        ]
    )

    result = _pipeline.add_sensor_to_dataset(ds, sensor_dict, og1_mapping)

    assert result["TEMP"].attrs["sensor"] == "SENSOR_CTD_245201"
    assert "sensor" not in result["PRES2"].attrs  # no KeyError, no sensor attr


def test_sensor_keys_are_not_variable_names(sg005_og1: pathlib.Path) -> None:
    """Sensor keys look up sensor metadata; they never rename a variable."""
    with xr.open_dataset(sg005_og1, engine="netcdf4", decode_timedelta=False) as ds:
        assert [name for name in ds.variables if " " in str(name)] == []
        for key in ("sbe41", "sbe43", "wlbb2f"):
            assert key in ds.variables, key
            assert ds[key].attrs["original_name"] == key
        # The lookup still works: the SENSOR_* variables carry the catalogue entry.
        sensors = {
            str(n): ds[n].attrs for n in ds.variables if str(n).startswith("SENSOR_")
        }
    assert sensors
    assert all(attrs.get("long_name") for attrs in sensors.values())
    assert not set(vocabularies.sensor_names) & set(vocabularies.standard_names)


def test_unknown_sensor_key_is_skipped_not_fatal() -> None:
    """A sensor key with no catalogue entry warns and gets no SENSOR_ variable."""
    datasets = readers.read_mission(str(_SG005), 1, 1)
    datasets[0].attrs["instrument"] = f"{datasets[0].attrs['instrument']} xyzsensor"
    ds = _convert.convert(datasets)
    assert not [name for name in ds.variables if "XYZ" in str(name).upper()]
    assert [name for name in ds.variables if str(name).startswith("SENSOR_CTD_")]


def test_sensors_config_corrects_a_basestation_sensor_record() -> None:
    """demo_sg005: a corrected wlbb2f serial names the sensor; the comment keeps the old one."""
    import pytest

    datasets = readers.read_mission(str(_SG005), 1, 1)
    ds = _convert.convert(
        datasets,
        sensors={"wlbb2f": {"serial_number": "1234", "calibration_date": "2008-02-01"}},
    )
    assert "SENSOR_FLUOROMETER_0000" not in ds.variables
    sensor = ds["SENSOR_FLUOROMETER_1234"]
    assert sensor.attrs["sensor_serial_number"] == "1234"
    assert sensor.attrs["sensor_calibration_date"] == "2008-02-01"
    assert "(basestation calibration comment: UNK)" in sensor.attrs["comment"]
    users = [v for v in ds.variables if ds[v].attrs.get("sensor") == sensor.name]
    assert "FLUOCHLA" in users
    with pytest.raises(ValueError, match="sensor keys .* are .*'wlbb2f'"):
        _convert.convert(datasets, sensors={"tridente": {"serial_number": "1"}})
    with pytest.raises(ValueError, match="unknown field 'serial'"):
        _convert.convert(datasets, sensors={"wlbb2f": {"serial": "1"}})


# --- Calibration comments: the answer table -----------------------------------------------


@pytest.mark.parametrize(
    "row", ROWS, ids=[f"{r['file']}:{r['variable']}" for r in ROWS]
)
def test_answer_table(row):
    """Every comment in the table parses to its expected serial, date and rules."""
    info = parse_calibcomm(
        row["string"], datetime.date.fromisoformat(row["first_sample"])
    )
    dates = "; ".join(f"{name}: {iso}" for name, iso in info.dates.items())
    assert (info.serial, info.calibration_date, dates) == (
        row["expected_serial"],
        row["expected_date"],
        row["expected_dates"],
    )
    assert (info.serial_rule, info.date_rule) == (row["serial_rule"], row["date_rule"])
    assert info.original == row["string"]


def test_table_covers_every_rule():
    """The table exercises each serial rule but 'none' and the date rules seen in the pack."""
    serial_rules = {r["serial_rule"] for r in ROWS}
    assert serial_rules == {"label", "SBE#-tc", "tc-only", "SBE-token", "bare-token"}
    date_rules = {r["date_rule"] for r in ROWS}
    assert {"rbr-iso", "ddMonyy", "dd Mon yy", "dd-Mon-yy", "mm/dd/yy"} <= date_rules
    assert {"ddmmyyyy", "ddmmyy", "none"} <= date_rules


def test_dev_pack_records_match_the_table(dev_data):
    """Every dev-pack file: each sensor's comment is read as the answer table says."""
    import xarray as xr

    from seagliderOG1 import _pipeline

    expected = {(r["file"], r["variable"]): r for r in ROWS}
    checked = 0
    for path in sorted(dev_data.glob("p*.nc")):
        with xr.open_dataset(path, engine="netcdf4") as ds:
            sensors = _pipeline.gather_sensor_info([ds])
        for metadata in sensors.values():
            record = metadata[_pipeline.CALIBCOMM_RECORD_KEY]
            row = expected.get((path.name, record["source_variable"]))
            if row is None:
                continue
            assert (
                metadata["sensor_serial_number"],
                metadata["sensor_calibration_date"],
                metadata["original_calibcomm"],
            ) == (row["expected_serial"], row["expected_date"], row["string"]), (
                path.name
            )
            checked += 1
    assert checked, f"no dev-pack file in {dev_data} matched the answer table"


# --- Calibration comments: dates ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "rule"),
    [
        ("calibration 12.05.2012", "2012-05-12", "dd.mm.yy"),
        ("calibration 12-05-2012", "2012-05-12", "dd-mm-yy"),
        ("calibration 05.25.2012", "2012-05-25", "mm.dd.yy"),
        ("calibration 12/05/2012", "2012-12-05", "mm/dd/yy"),
    ],
)
def test_numeric_dates_by_separator(text, expected, rule):
    """Both readings fit: dots and dashes read day-first, slashes month-first."""
    info = parse_calibcomm(text, datetime.date(2013, 1, 1))
    assert (info.calibration_date, info.date_rule) == (expected, rule)


def test_year_first_and_month_word_first_dates():
    """yyyy-mm-dd, yyyy/mm/dd and 'May 12, 2012' each have one reading."""
    first = datetime.date(2013, 1, 1)
    for text, rule in (
        ("SBE s/n 0112 calibration 2012-05-12", "yyyy-mm-dd"),
        ("SBE s/n 0112 calibration 2012/05/12", "yyyy/mm/dd"),
        ("SBE s/n 0112 calibration May 12, 2012", "Mon dd, yyyy"),
    ):
        info = parse_calibcomm(text, first)
        assert (info.calibration_date, info.date_rule) == ("2012-05-12", rule), text


def test_rbr_fractional_seconds():
    """An RBR channel time with fractional seconds is kept."""
    info = parse_calibcomm(
        "RBRcoda serialnum:1 temp15:2025-02-26T13:58:29.000Z doxy24:2025-03-20T11:45:16Z"
    )
    assert info.dates == {"temp15": "2025-02-26", "doxy24": "2025-03-20"}


@pytest.mark.parametrize(
    ("text", "serial", "expected"),
    [
        ("SBE 43F cal SN 1234 04FEB08", "1234", "2008-02-04"),
        ("Optode 4330 calibrated s/n 1234 on 12 Aug 2011", "1234", "2011-08-12"),
        ("cal 12 Aug 2011 recal due 2013-08-12", "UNK", "2011-08-12"),
        ("calibration 3/5/12 next 2014-05-03", "UNK", "2012-03-05"),
        ("SBE 43 cal rev 2.1.08", "43", "UNK"),
        ("cal sn-1234 3/5/12", "1234", "2012-03-05"),
    ],
)
def test_date_directly_follows_the_keyword(text, serial, expected):
    """The date is the first thing after the keyword, a serial label and 'on' aside."""
    info = parse_calibcomm(text, datetime.date(2015, 1, 1))
    assert (info.serial, info.calibration_date) == (serial, expected)


def test_date_after_a_serial_label_is_not_the_serial():
    """'calibration sn 2012-05-12': the date is a date, not the serial."""
    info = parse_calibcomm("calibration sn 2012-05-12", datetime.date(2013, 1, 1))
    assert (info.serial, info.calibration_date) == ("UNK", "2012-05-12")


def test_ambiguous_slash_date_reads_month_first():
    """9/10/08 before a November dive fits both ways; the month-first reading wins."""
    info = parse_calibcomm(
        "SBE s/n 19, calibration 9/10/08", datetime.date(2008, 11, 8)
    )
    assert info.calibration_date == "2008-09-10"
    assert "read mm/dd/yy" in info.note


def test_impossible_month_first_swaps_to_day_first():
    """28/4/08 cannot be month-first, so it is read day-first, with a note."""
    info = parse_calibcomm(
        "SBE s/n 0015 calibration 28/4/08", datetime.date(2008, 8, 1)
    )
    assert (info.calibration_date, info.date_rule) == ("2008-04-28", "dd/mm/yy")
    assert info.note == "month-first impossible; read day-first"


def test_impossible_slash_date_rule_label():
    """31/04/2012 is no date either way: UNK, labelled with both readings."""
    info = parse_calibcomm("sn 1234 calibrated 31/04/2012", datetime.date(2013, 1, 1))
    assert (info.calibration_date, info.date_rule) == ("UNK", "mm/dd/yy or dd/mm/yy")


def test_six_digits_decided_by_first_sample():
    """251114: yymmdd puts the year in 1925, outside the window, so ddmmyy is read."""
    info = parse_calibcomm("SN: 0135  CAL: 251114", datetime.date(2015, 8, 15))
    assert (info.calibration_date, info.date_rule) == ("2014-11-25", "ddmmyy")
    assert "yymmdd reading 1925-11-14 is outside the window" in info.note


def test_six_digits_without_first_sample_is_unk():
    """Without a first sample both readings of 251114 are dates, so the date is UNK."""
    info = parse_calibcomm("SN: 0135  CAL: 251114")
    assert info.calibration_date == "UNK"
    assert info.note.startswith("ambiguous")


def test_two_digit_year_takes_century_nearest_first_sample():
    """'12 Aug 01' is 2001 for a 2003 dive and 1901 is never chosen."""
    info = parse_calibcomm(
        "SBE 43F s/n 25281-1 calibration 12 Aug 01", datetime.date(2003, 10, 2)
    )
    assert info.calibration_date == "2001-08-12"


def test_two_digit_year_not_after_first_sample():
    """'cal 12 Aug 10' for a 2065 mission is 2010, not 2110."""
    info = parse_calibcomm("cal 12 Aug 10", datetime.date(2065, 1, 1))
    assert info.calibration_date == "2010-08-12"


def test_first_sample_on_29_february():
    """A first sample on 29 February: the window starts on 28 February 30 years earlier."""
    from seagliderOG1 import _pipeline

    info = parse_calibcomm(
        "SBE s/n 0021 calibration 9/10/08", datetime.date(2024, 2, 29)
    )
    assert info.calibration_date == "2008-09-10"
    record = {"checks": []}
    metadata = {
        "sensor_calibration_date": "1990-01-01",
        _pipeline.CALIBCOMM_RECORD_KEY: record,
    }
    _pipeline._check_calibration_date("x", metadata, datetime.date(2024, 2, 29))
    assert record["checks"] == [
        "calibration date 1990-01-01 is more than 30 years before the first sample "
        "2024-02-29"
    ]
    assert "more than 30 years" in metadata["comment"]


def test_postdated_single_reading_is_kept():
    """A date with one reading is kept even when after the first sample (flagged later)."""
    info = parse_calibcomm(
        "Legato s/n 238007, calibration 27 Feb 2025", datetime.date(2025, 1, 1)
    )
    assert info.calibration_date == "2025-02-27"


def test_convention_choice_is_warned_and_recorded(caplog):
    """sg005 with dive 1-5 CTD dates written 3/4/08: both readings fit; warned, checked."""
    from seagliderOG1 import _pipeline

    datasets = _open(SG005)
    for ds in datasets:
        ds["sg_cal_calibcomm"] = ds["sg_cal_calibcomm"].copy(
            data=b"SBE 24520-1 calibration 3/4/08"
        )
    with caplog.at_level("WARNING"):
        ctd = _pipeline.gather_sensor_info(datasets)["sbe41"]
    record = ctd[_pipeline.CALIBCOMM_RECORD_KEY]
    assert ctd["sensor_calibration_date"] == "2008-03-04"
    assert record["checks"][0].startswith("date chosen by convention")
    assert (record["window_years"], record["first_sample"]) == (30, "2008-06-06")
    assert any("has two readings" in r.message for r in caplog.records)


# --- Calibration comments: serial numbers -------------------------------------------------


def test_serial_after_the_keyword_is_not_read_as_a_date():
    """Digits after a serial label are a serial, not a date."""
    info = parse_calibcomm(
        "SBE 41 calibration date unknown s/n 251114", datetime.date(2015, 8, 15)
    )
    assert (info.serial, info.calibration_date) == ("251114", "UNK")


def test_sn_inside_a_word_is_not_a_label():
    """'sn' must stand alone: the word 'snapshot' does not start a serial."""
    info = parse_calibcomm("snapshot 12 calibration 04FEB08")
    assert info.serial_rule != "label"


@pytest.mark.parametrize("text", [None, "", "  \x00\x00"])
def test_empty_comment(text):
    """No comment: serial and date UNK, never a fabricated 0000."""
    info = parse_calibcomm(text)
    assert (info.serial, info.calibration_date, info.original) == ("UNK", "UNK", "")


# --- Calibration comments in the sensor records -------------------------------------------


def test_sg271_records_keep_the_comment_and_every_channel_date():
    """RBR comments: the latest channel date, every channel date, the comment as read."""
    from seagliderOG1 import _pipeline

    sensors = _pipeline.gather_sensor_info(_open(SG271))
    tridente = sensors["tridentebb700chla470fdom365"]
    assert tridente["sensor_calibration_date"] == "2025-03-11"
    assert tridente["sensor_calibration_dates"] == (
        "backscatter_00: 2025-02-26; chlorophyll_00: 2025-03-11; fdom_00: 2025-03-11"
    )
    assert tridente["original_calibcomm"].startswith("RBRtridente serialnum:237790 ")
    record = tridente[_pipeline.CALIBCOMM_RECORD_KEY]
    assert record["source_variable"] == "sg_cal_calibcomm_tridentebb700chla470fdom365"
    assert (record["serial_rule"], record["date_rule"]) == ("label", "rbr-iso")
    assert "sensor_calibration_dates" not in sensors["legato"]


def test_sg005_output_carries_the_parse(sg005_og1):
    """The OG1 file: serial with its dash, original_calibcomm, the parse global."""
    import json

    import xarray as xr

    with xr.open_dataset(sg005_og1, engine="netcdf4") as ds:
        ctd = ds["SENSOR_CTD_24520-1"]
        assert ctd.attrs["original_calibcomm"] == "SBE 24520-1 calibration 04FEB08"
        assert ctd.attrs["sensor_calibration_date"] == "2008-02-04"
        assert "original_calibcomm" not in ds["SENSOR_FLUOROMETER_UNK"].attrs
        ledger = json.loads(ds.attrs["conversion_sensor_calibration"])
    assert ledger["SENSOR_CTD_24520-1"]["source_variable"] == "sg_cal_calibcomm"
    assert ledger["SENSOR_CTD_24520-1"]["serial_rule"] == "SBE-token"
    assert ledger["SENSOR_FLUOROMETER_UNK"]["note"] == (
        "no calibration comment for this sensor"
    )


def test_first_sample_is_the_earliest_start_time():
    """sg005 dives 1-5 start on 2008-06-06 and 2008-06-07; the first sample is the 6th."""
    from seagliderOG1 import _pipeline

    assert _pipeline._first_sample(_open(SG005)) == datetime.date(2008, 6, 6)


def test_calibration_after_first_sample_is_kept_and_flagged(caplog):
    """sg271 with the Legato comment edited to a date after the first dive (2026-03-02)."""
    from seagliderOG1 import _pipeline

    datasets = _open(SG271)
    for ds in datasets:
        ds["sg_cal_calibcomm"] = ds["sg_cal_calibcomm"].copy(
            data=b"Legato s/n 238007, calibration 27 Mar 2026"
        )
    with caplog.at_level("WARNING"):
        sensors = _pipeline.gather_sensor_info(datasets)
    legato = sensors["legato"]
    assert legato["sensor_calibration_date"] == "2026-03-27"
    assert legato["comment"] == (
        "Calibration date 2026-03-27 is after the first sample 2026-03-02 "
        "(see original_calibcomm)."
    )
    assert legato[_pipeline.CALIBCOMM_RECORD_KEY]["checks"] == [
        "calibration date 2026-03-27 is after the first sample 2026-03-02"
    ]
    assert any("is after the first sample" in r.message for r in caplog.records)


def test_date_taken_from_a_later_dive(caplog):
    """sg005 with dive 1's CTD comment cut to the serial: the date comes from dive 2."""
    from seagliderOG1 import _pipeline

    datasets = _open(SG005)
    datasets[0]["sg_cal_calibcomm"] = datasets[0]["sg_cal_calibcomm"].copy(
        data=b"SBE 24520-1"
    )
    with caplog.at_level("WARNING"):
        sensors = _pipeline.gather_sensor_info(datasets)
    ctd = sensors["sbe41"]
    assert (ctd["sensor_serial_number"], ctd["sensor_calibration_date"]) == (
        "24520-1",
        "2008-02-04",
    )
    assert ctd["original_calibcomm"] == "SBE 24520-1"
    assert "read from the comment in input file 2" in ctd["comment"]
    record = ctd[_pipeline.CALIBCOMM_RECORD_KEY]
    assert record["date_rule"] == "ddMonyy"
    assert record["filled_from"]["sensor_calibration_date"]["source_file_index"] == 2
    assert record["note"].startswith("first comment: no calibration keyword")
    assert not [r for r in caplog.records if "Conflicting" in r.message]


def test_serial_taken_from_a_later_dive():
    """sg005 with dive 1's CTD comment cut to the date: the serial comes from dive 2."""
    from seagliderOG1 import _pipeline

    datasets = _open(SG005)
    datasets[0]["sg_cal_calibcomm"] = datasets[0]["sg_cal_calibcomm"].copy(
        data=b"calibration 04FEB08"
    )
    ctd = _pipeline.gather_sensor_info(datasets)["sbe41"]
    assert (ctd["sensor_serial_number"], ctd["sensor_calibration_date"]) == (
        "24520-1",
        "2008-02-04",
    )
    record = ctd[_pipeline.CALIBCOMM_RECORD_KEY]
    assert record["serial_rule"] == "SBE-token"
    assert record["filled_from"]["sensor_serial_number"]["source_file_index"] == 2
    assert record["note"] == (
        "sensor_serial_number from input file 2: 'SBE 24520-1 calibration 04FEB08'"
    )


def test_no_fill_from_a_comment_with_another_serial():
    """A later comment naming a different serial does not lend its date."""
    from seagliderOG1 import _pipeline

    datasets = _open(SG005)
    datasets[0]["sg_cal_calibcomm"] = datasets[0]["sg_cal_calibcomm"].copy(
        data=b"SBE 24520-1"
    )
    for ds in datasets[1:]:
        ds["sg_cal_calibcomm"] = ds["sg_cal_calibcomm"].copy(
            data=b"SBE 99999 calibration 04FEB08"
        )
    ctd = _pipeline.gather_sensor_info(datasets)["sbe41"]
    assert (ctd["sensor_serial_number"], ctd["sensor_calibration_date"]) == (
        "24520-1",
        "UNK",
    )
    assert "filled_from" not in ctd[_pipeline.CALIBCOMM_RECORD_KEY]


def test_shared_serial_is_warned_and_recorded(caplog):
    """sg271's coda and tridente comments carry one serial: one WARNING, both records."""
    from seagliderOG1 import _pipeline

    with caplog.at_level("WARNING"):
        sensors = _pipeline.gather_sensor_info(_open(SG271))
    shared = [r for r in caplog.records if "share serial number 237790" in r.message]
    assert len(shared) == 1
    for key in ("codaTODO", "tridentebb700chla470fdom365"):
        checks = sensors[key][_pipeline.CALIBCOMM_RECORD_KEY]["checks"]
        assert any("serial 237790 shared with" in c for c in checks)


def test_two_sensors_with_one_name_are_both_written(caplog):
    """Two fluorometers with no serial: both written, the second suffixed, one warning."""
    from seagliderOG1 import _pipeline

    sensors = {
        "a": {"sensor_type": "fluorometer", "sensor_serial_number": "UNK"},
        "b": {"sensor_type": "fluorometer", "sensor_serial_number": "UNK"},
    }
    with caplog.at_level("WARNING"):
        names = _pipeline._sensor_variable_names(sensors)
    assert names == {"a": "SENSOR_FLUOROMETER_UNK", "b": "SENSOR_FLUOROMETER_UNK_b"}
    assert any(
        "would both be SENSOR_FLUOROMETER_UNK" in r.message for r in caplog.records
    )


def test_repeated_rbr_channel_keeps_latest_and_says_so():
    """A channel named twice keeps its latest date and the note names the dropped one."""
    info = parse_calibcomm(
        "RBRcoda serialnum:1 temp:2025-02-26T13:58:29Z temp:2025-03-20T11:45:16Z"
    )
    assert info.dates == {"temp": "2025-03-20"}
    assert "dropped: temp 2025-02-26" in info.note


def test_override_keeps_original_calibcomm_and_clears_shared_serial(caplog):
    """The sg271 mission correction (tridente 237998) replaces the serial, not the source."""
    from seagliderOG1 import _pipeline

    with caplog.at_level("WARNING"):
        sensors = _pipeline.gather_sensor_info(
            _open(SG271),
            overrides={"tridentebb700chla470fdom365": {"serial_number": "237998"}},
        )
    tridente = sensors["tridentebb700chla470fdom365"]
    assert tridente["sensor_serial_number"] == "237998"
    assert "serialnum:237790" in tridente["original_calibcomm"]
    record = tridente[_pipeline.CALIBCOMM_RECORD_KEY]
    assert record["overridden"] == ["sensor_serial_number"]
    assert not [r for r in caplog.records if "share serial number" in r.message]


def test_non_iso_override_is_refused():
    """A sensors: calibration_date that is not YYYY-MM-DD stops the conversion."""
    from seagliderOG1 import _pipeline

    with pytest.raises(ValueError, match="not an ISO date"):
        _pipeline.gather_sensor_info(
            _open(SG005), overrides={"sbe41": {"calibration_date": "04/02/2008"}}
        )
