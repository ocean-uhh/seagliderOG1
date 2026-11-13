"""The OG1 vocabulary tables in config/ and the vocabulary links written on each variable,
checked against the cached NERC and CF term lists in tests/data/vocabularies/.

Data: the package tables, the cached vocabularies, the sg005 demo conversion.
"""

import pathlib
import re

import netCDF4
import pytest
import yaml

from seagliderOG1 import _convert, vocabularies

TESTS = pathlib.Path(__file__).parent.parent
VOCAB = TESTS / "data" / "vocabularies"
DATA = TESTS.parent / "data" / "demo_sg005"
LINK = re.compile(
    r"^http://vocab\.nerc\.ac\.uk/collection/(?P<collection>OG1|P01)/current/(?P<term>[^/]+)/$"
)


def _load(name: str) -> dict:
    return yaml.safe_load((VOCAB / name).read_text(encoding="utf-8"))


def _entries() -> dict[str, dict]:
    return {k: v for k, v in vocabularies.vocab_attrs.items() if isinstance(v, dict)}


# --- The package tables -------------------------------------------------------------------


def test_dimension_renames():
    assert vocabularies.DIMENSION_RENAMES == {"sg_data_point": "N_MEASUREMENTS"}


def test_var_names():
    og1_varlist = [
        "TIME",
        "LATITUDE",
        "LONGITUDE",
        "LATITUDE_GPS",
        "TEMP",
        "DEPTH",
        "TIME_GPS",
        "LONGITUDE_GPS",
        "TRAJECTORY",
        "PLATFORM_MODEL",
        "PLATFORM_SERIAL_NUMBER",
    ]
    # Set in OG1_variable_names.yaml
    # OG1 variables are all caps and here: https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html
    for var in og1_varlist:
        assert var in vocabularies.standard_names.values()


def test_vocab_attrs():
    # Set in OG1_variable_attributes.yaml
    # OG1 variables are all caps and here: https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html
    assert vocabularies.vocab_attrs["WMO_IDENTIFIER"]["long_name"] == "wmo id"


def test_sensor_vocabs():
    # Set in OG1_sensor_attributes.yaml
    # Sensor vocabularies from here: http://vocab.nerc.ac.uk/scheme/OG_SENSORS/current/
    # and https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html
    assert (
        vocabularies.sensor_vocabs["Seabird unpumped CTD"]["long_name"]
        == "Sea-Bird CT Sail CTD"
    )
    assert (
        vocabularies.sensor_vocabs["Seabird unpumped CTD"]["sensor_maker"]
        == "Sea-Bird Scientific"
    )
    assert (
        vocabularies.sensor_vocabs["Seabird SBE43F"]["long_name"] == "Sea-Bird SBE 43F"
    )


def test_vocabulary_strings_have_no_edge_whitespace():
    """No vocabulary string starts or ends with whitespace (written verbatim to output)."""
    import yaml

    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str) and node != node.strip():
            offenders.append(f"{path}: {node!r}")

    for name in (
        "OG1_variable_attributes.yaml",
        "OG1_variable_names.yaml",
        "OG1_sensor_names.yaml",
        "OG1_sensor_attributes.yaml",
        "OG1_global_attributes.yaml",
    ):
        walk(
            yaml.safe_load(
                (vocabularies.CONFIG_DIR / name).read_text(encoding="utf-8")
            ),
            name,
        )
    assert not offenders, offenders


def test_platform_from_file_versions_as_numbers_or_dotted_strings():
    """Old basestation files store versions as numbers, newer ones as "3.0.6" (pure logic)."""
    old = vocabularies.platform_from_file(
        {"seaglider_software_version": 66.03, "base_station_version": 2.8}
    )
    assert old["GLIDER_FIRMWARE_VERSION"] == "seaglider 66.03"
    assert old["LANDSTATION_VERSION"] == "basestation v2.8"
    new = vocabularies.platform_from_file(
        {"seaglider_software_version": "67.00", "base_station_version": "3.0.6"}
    )
    # A string is written as is: "67.00" and "2.10" are not shortened as numbers would be.
    assert new["GLIDER_FIRMWARE_VERSION"] == "seaglider 67.00"
    assert new["LANDSTATION_VERSION"] == "basestation v3.0.6"
    two_part = vocabularies.platform_from_file({"base_station_version": "2.10"})
    assert two_part["LANDSTATION_VERSION"] == "basestation v2.10"


# --- Vocabulary links on the variables ----------------------------------------------------


def test_converted_file_carries_vocabulary(tmp_path):
    """The attribute reaches the written file under its OG1 name."""
    path = _convert._convert_mission(str(DATA), tmp_path, dives=(1, 1))
    with netCDF4.Dataset(path) as nc:
        temp = nc["TEMP"]
        assert temp.vocabulary == "http://vocab.nerc.ac.uk/collection/OG1/current/TEMP/"
        assert "uri" not in temp.ncattrs()


def test_every_vocabulary_link_is_a_current_term():
    """Each link has the canonical form and names a current, non-deprecated term."""
    terms = {
        "OG1": _load("og1_terms.yaml")["terms"],
        "P01": _load("p01_terms.yaml")["terms"],
    }
    problems = []
    for name, attrs in _entries().items():
        link = attrs.get("vocabulary")
        if link is None:
            continue
        match = LINK.match(str(link))
        if not match:
            problems.append(f"{name}: {link} is not an OG1 or P01 term link")
            continue
        term = terms[match["collection"]].get(match["term"])
        if term is None:
            problems.append(f"{name}: {match['term']} is not in {match['collection']}")
        elif term["deprecated"]:
            problems.append(f"{name}: {match['term']} is deprecated")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("variable", "term"),
    [
        ("TEMP_OXYGEN", "TEMPDOXY"),
        ("LATITUDE_GPS", "LAT_GPS"),
        ("LONGITUDE_GPS", "LON_GPS"),
        ("SOUND_VELOCITY", "SOUNDVEL"),
        ("CHLA", "CHLA"),
        ("DOXY", "DOXY"),
        ("TIME", "TIME"),
    ],
)
def test_og1_term_where_og1_has_one(variable, term):
    """Variables OG1 names point at that OG1 term, not a P02 group or a neighbouring term."""
    expected = f"http://vocab.nerc.ac.uk/collection/OG1/current/{term}/"
    assert vocabularies.vocab_attrs[variable]["vocabulary"] == expected


def test_p01_only_where_og1_has_no_term():
    """A P01 link is used only when no OG1 term carries the same label."""
    og1_labels = {t["label"].lower() for t in _load("og1_terms.yaml")["terms"].values()}
    p01 = _load("p01_terms.yaml")["terms"]
    shadowed = [
        code for code, term in p01.items() if term["label"].lower() in og1_labels
    ]
    assert not shadowed


def test_every_standard_name_is_a_current_cf_name():
    """Each ``standard_name`` is an entry (not an alias) of the cached CF table."""
    names = _load("cf_standard_names.yaml")["names"]
    unknown = {
        name: attrs["standard_name"]
        for name, attrs in _entries().items()
        if attrs.get("standard_name") and attrs["standard_name"] not in names
    }
    assert not unknown


def test_coordinates_on_every_measurement_variable(tmp_path):
    """Every variable on N_MEASUREMENTS (``_QC`` included) names OG1's four coordinates,
    blank-separated as CF requires; the coordinates themselves and scalars carry none, and a
    basestation value naming variables the file lacks does not survive."""
    path = _convert._convert_mission(str(DATA), tmp_path, dives=(1, 2))
    coordinates = {"TIME", "LONGITUDE", "LATITUDE", "DEPTH"}
    with netCDF4.Dataset(path) as nc:
        for var in nc.variables.values():
            value = getattr(var, "coordinates", None)
            if var.dimensions == ("N_MEASUREMENTS",) and var.name not in coordinates:
                assert value == "TIME LONGITUDE LATITUDE DEPTH", var.name
            elif var.dimensions == () or var.name in coordinates:
                assert value is None, var.name
        assert nc["TEMP_QC"].coordinates == "TIME LONGITUDE LATITUDE DEPTH"


def test_no_uri_attribute_remains():
    """OG1 names the attribute ``vocabulary``; the old ``uri`` key is gone."""
    assert not [name for name, attrs in _entries().items() if "uri" in attrs]
