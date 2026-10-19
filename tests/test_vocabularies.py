import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import vocabularies  # noqa: E402  # import after sys.path bootstrap


def test_dimension_renames():
    assert vocabularies.DIMENSION_RENAMES == {"sg_data_point": "N_MEASUREMENTS"}


def test_preferred_units():
    assert vocabularies.preferred_units == ["m s-1", "dbar", "S m-1"]


def test_unit_str_format():
    assert vocabularies.unit_str_format["m/s"] == "m s-1"
    assert vocabularies.unit_str_format["cm/s"] == "cm s-1"
    assert vocabularies.unit_str_format["S/m"] == "S m-1"
    assert vocabularies.unit_str_format["mS/cm"] == "mS cm-1"
    assert vocabularies.unit_str_format["meters"] == "m"
    assert vocabularies.unit_str_format["degrees_Celsius"] == "degree_Celsius"
    assert vocabularies.unit_str_format["degreesCelsius"] == "degree_Celsius"
    assert vocabularies.unit_str_format["g/m^3"] == "g m-3"
    assert vocabularies.unit_str_format["kg/m^3"] == "kg m-3"


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
