import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import vocabularies  # noqa: E402  # import after sys.path bootstrap


def test_dims_rename_dict():
    assert vocabularies.dims_rename_dict == {"sg_data_point": "N_MEASUREMENTS"}


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
    # Set in OG1_var_names.yaml
    # OG1 variables are all caps and here: https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html
    for var in og1_varlist:
        assert var in vocabularies.standard_names.values()


def test_vocab_attrs():
    # Set in OG1_vocab_attrs.yaml
    # OG1 variables are all caps and here: https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html
    assert vocabularies.vocab_attrs["WMO_IDENTIFIER"]["long_name"] == "wmo id"


def test_sensor_vocabs():
    # Set in OG1_sensor_attrs.yaml
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
        "OG1_vocab_attrs.yaml",
        "OG1_var_names.yaml",
        "OG1_sensor_attrs.yaml",
        "OG1_global_attrs.yaml",
    ):
        walk(yaml.safe_load((vocabularies.CONFIG_DIR / name).read_text()), name)
    assert not offenders, offenders
