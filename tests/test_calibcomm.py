"""Calibration-comment parsing, tested against a table of real comments.

``tests/data/calibcomm_answers.csv`` holds every ``sg_cal_calibcomm*`` string from the dev
pack and the repository's own sample files, with the serial and calibration date each one
means (read from the string, or ruled by the maintainer where the string is ambiguous) and the
date of the mission's first sample. The table is the test: a new comment format is a new row.
"""

import csv
import datetime
import pathlib

import pytest

from seagliderOG1._pipeline import parse_calibcomm

ANSWERS = pathlib.Path(__file__).parent / "data" / "calibcomm_answers.csv"
ROWS = list(csv.DictReader(ANSWERS.open(encoding="utf-8")))


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


def test_six_digits_decided_by_first_sample():
    """251114: yymmdd (2025) would postdate a 2015 dive, so ddmmyy is read."""
    info = parse_calibcomm("SN: 0135  CAL: 251114", datetime.date(2015, 8, 15))
    assert (info.calibration_date, info.date_rule) == ("2014-11-25", "ddmmyy")
    assert "yymmdd reading 2025-11-14 is outside the window" in info.note


def test_six_digits_without_first_sample_is_unk():
    """Without a first sample both readings of 251114 are dates, so the date is UNK."""
    info = parse_calibcomm("SN: 0135  CAL: 251114")
    assert info.calibration_date == "UNK"
    assert info.note.startswith("ambiguous")


def test_postdated_single_reading_is_kept():
    """A date with one reading is kept even when after the first sample (flagged later)."""
    info = parse_calibcomm(
        "Legato s/n 238007, calibration 27 Feb 2025", datetime.date(2025, 1, 1)
    )
    assert info.calibration_date == "2025-02-27"


def test_two_digit_year_takes_century_nearest_first_sample():
    """'12 Aug 01' is 2001 for a 2003 dive and 1901 is never chosen."""
    info = parse_calibcomm(
        "SBE 43F s/n 25281-1 calibration 12 Aug 01", datetime.date(2003, 10, 2)
    )
    assert info.calibration_date == "2001-08-12"


@pytest.mark.parametrize("text", [None, "", "  \x00\x00"])
def test_empty_comment(text):
    """No comment: serial and date UNK, never a fabricated 0000."""
    info = parse_calibcomm(text)
    assert (info.serial, info.calibration_date, info.original) == ("UNK", "UNK", "")


def test_sn_inside_a_word_is_not_a_label():
    """'sn' must stand alone: the word 'snapshot' does not start a serial."""
    info = parse_calibcomm("snapshot 12 calibration 04FEB08")
    assert info.serial_rule != "label"


# --- The parse in the sensor records (real sg271 and sg005 files) -----------------------

SG271 = (
    pathlib.Path(__file__).resolve().parent.parent / "seagliderOG1" / "data" / "sg271"
)
SG005 = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005"


def _open(folder):
    import xarray as xr

    return [xr.open_dataset(p, engine="netcdf4") for p in sorted(folder.glob("p*.nc"))]


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


def test_first_sample_is_the_earliest_start_time():
    """sg005 dives 1-5 start on 2008-06-06 and 2008-06-07; the first sample is the 6th."""
    from seagliderOG1 import _pipeline

    assert _pipeline._first_sample(_open(SG005)) == datetime.date(2008, 6, 6)


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
