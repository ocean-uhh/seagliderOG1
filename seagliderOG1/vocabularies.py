"""Vocabularies and mappings for OG1 format conversion.

This module defines the vocabulary mappings, unit conversions, and attribute
configurations used to convert Seaglider basestation files to OG1 format.
It loads YAML configuration files and defines various dictionaries used
throughout the conversion process.

Key Components:

- Variable name mappings from basestation to OG1 format
- Unit conversion factors and formatting rules
- Global attribute definitions and ordering
- Variables to include/exclude during conversion
- Dimension renaming mappings

Configuration Files:

- OG1_variable_names.yaml: Variable name mappings
- OG1_unit_corrections.yaml: Basestation units labels that are wrong for the values
- OG1_sensor_names.yaml: Sensor keys to OG1_sensor_attributes.yaml titles
- OG1_variable_attributes.yaml: Variable attribute vocabularies
- OG1_sensor_attributes.yaml: Sensor attribute definitions
- OG1_global_attributes.yaml: Global attribute configurations

Notes
-----
This module is primarily data-driven and loads most configuration from YAML files
in the config/ directory. The YAML-based approach allows easy modification of
OG1 format requirements without code changes.

"""

import pathlib
from collections.abc import Callable
from typing import NamedTuple

import yaml

from seagliderOG1.reports._vendored import units as _units

__all__ = ["PlatformField", "platform_from_file"]

# Set the directory for yaml files as package directory + 'config/'
script_dir = pathlib.Path(__file__).parent.absolute()
CONFIG_DIR: pathlib.Path = script_dir / "config"
# Backward-compatible alias: contributors.py reads vocabularies.config_dir.
config_dir = CONFIG_DIR

# Dimension renaming: maps basestation dimension names to OG1 standard names
DIMENSION_RENAMES = {"sg_data_point": "N_MEASUREMENTS"}

# NERC W08 "SensorML Contact Section Terms": the controlled vocabulary the OG1 spec
# cites for contributor_role and contributing_institutions_role (fetched from
# vocab.nerc.ac.uk 2026-10-08). The seven preferred labels and their term URIs.
_W08 = "http://vocab.nerc.ac.uk/collection/W08/current/"
ROLE_VOCABULARY = {
    "Manufacturer": _W08 + "CONT0001/",
    "Owner": _W08 + "CONT0002/",
    "Operator": _W08 + "CONT0003/",
    "PI": _W08 + "CONT0004/",
    "Technical Coordinator": _W08 + "CONT0005/",
    "Data scientist": _W08 + "CONT0006/",
    "Service Provider": _W08 + "CONT0007/",
}

# Attested spelling variants seen in real files, mapped to the preferred W08 label.
# Add an alias only when it appears in a real file (basestation files and the sp041
# example both write PI as "Principal investigator" with the CONT0004 URI).
ROLE_ALIASES = {
    "principal investigator": "PI",
}

# OG1 data-mode -> filename/id suffix. Mode affects only the id (and filename);
# nothing else is written. Ref: OceanGliders OG-format-user-manual, "File naming
# convention".
MODE_SUFFIX = {"delayed": "delayed", "realtime": "R"}

# Strings that mean "nothing was supplied" when a config or global-attribute value is
# read: None renders as these, and they are the placeholders the old attr_mandatory
# fill used to write. One definition so the converter and validate agree on what counts
# as unset (a value here is never written to the output, and validate treats it as null).
PLACEHOLDER_VALUES = frozenset({"", "None", "null", "null@null.com"})

# The one sentence a draft output carries in its ``draft`` global (shared by the
# converter, which writes it, and the report, which reads it to mark the page a draft).
DRAFT_NOTE = "converted without a mission config; not an OG1 file"


def is_placeholder(value: object) -> bool:
    """Return True for a null or placeholder value, so every path agrees on "unset".

    The one definition behind the converter's ``_is_empty`` and the validator's
    ``_is_placeholder``: None, or a string that is empty or one of
    :data:`PLACEHOLDER_VALUES` (``""``, ``"None"``, ``"null"``, ``"null@null.com"``). A
    value this returns True for is never written to the output and is treated as null by
    ``validate``.

    Parameters
    ----------
    value : object
        The value to test.

    Returns
    -------
    bool
        True when the value counts as unset.

    """
    return value is None or (
        isinstance(value, str) and value.strip() in PLACEHOLDER_VALUES
    )


# OG1 deployment-identity globals the mission config sets through the structured
# deployment: block (one key per global). Ordered as the OG1 manual's global-attribute
# table lists them (the order the `required:` block carries): mandatory, then highly
# desirable, then suggested; `license` and `acknowledgment` are ACDD globals with no
# OG1-table position and trail the tiered ones.
#
# The user-set global attributes, grouped by the conversion page's convention group.
# Each yaml section slug is this schema's own contract; it is NOT derived from the vendored
# page label (ctdcast owns those). tests/test_reports.py asserts every key groups under the
# matching page label. program/program_vocabulary/network are deliberately absent: they are
# per-platform facts a local-config overlay supplies, not per-mission text
# (notes/2026-10-21-platform-registry.md); until the registry lands they are set, if needed,
# through global_attributes:.
CONFIG_GLOBAL_SECTIONS = {
    "identity_and_discovery": (
        "id",
        "naming_authority",
        "site",
        "site_vocabulary",
        "data_url",
        "project",
    ),
    "rights_and_access": (
        "doi",
        "license",
        "acknowledgment",
    ),
    "provenance_and_processing": ("comment",),
}

# Flat union of the section keys, in section then template order. The single list read by
# convert.to_og1 (precedence, collision checks) and the validate deployment check; the init
# template reads CONFIG_GLOBAL_SECTIONS directly (each key's tier from REQUIRED_GLOBALS).
DEPLOYMENT_GLOBALS = tuple(
    key for keys in CONFIG_GLOBAL_SECTIONS.values() for key in keys
)

# Each sectioned global mapped to the slug of the section that sets it. The one inverse of
# CONFIG_GLOBAL_SECTIONS: read by validate (wrong-section and collision messages), the
# converter's collision/override messages, and the init template, so "which section owns
# this key" has a single definition.
CONFIG_GLOBAL_HOME = {
    key: slug for slug, keys in CONFIG_GLOBAL_SECTIONS.items() for key in keys
}


# Globals the converter computes from the data (or at conversion time). A mission config
# may not set them: convert.to_og1 refuses them in global_attributes, and validate says so first.
DERIVED_GLOBALS = frozenset(
    {
        "time_coverage_start",
        "time_coverage_end",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_vertical_min",
        "geospatial_vertical_max",
        "geospatial_bounds",
        "geospatial_vertical_positive",
        "time_coverage_duration",
        "date_created",
        "start_date",
        "tracking_id",
    }
)


# Fields a mission config's sensors: block may correct, keyed by the basestation sensor key
# (a name in the instrument global), mapped to the sensor attribute each one sets. Read by
# the converter (_pipeline.gather_sensor_info) and by validate.
SENSOR_OVERRIDE_FIELDS = {
    "serial_number": "sensor_serial_number",
    "calibration_date": "sensor_calibration_date",
}


def _version(prefix: str) -> Callable[[object], str]:
    """Return a formatter that writes a version attribute after ``prefix``.

    Older basestation files store the versions as numbers (``66.03``, ``2.8``), newer
    ones as strings (``"3.0.6"``); a number is written compactly, a string as is — so
    ``"2.10"`` stays ``2.10`` and is not read as the number 2.1.

    Parameters
    ----------
    prefix : str
        Text before the version, e.g. ``"basestation v"``.

    Returns
    -------
    callable
        ``value -> str``.

    """

    def format_version(value: object) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if isinstance(value, str):
            return f"{prefix}{value.strip()}"
        return f"{prefix}{float(value):g}"

    return format_version


class PlatformField(NamedTuple):
    """How one OG1 platform field is sourced and written.

    Parameters
    ----------
    source : str or None
        Basestation global attribute the value derives from, or None when the
        field is config-only (no file fallback).
    formatter : callable or None
        Applied to the file value before use; None when there is no file source.
    required : bool
        When True, a null in the mission config is a validate ERROR rather than a
        silent default written into the output.
    kind : str
        How ``to_og1`` writes an unset field: ``"serial"`` names the
        output and raises when absent, ``"string"`` warns and writes ``"UNK"``,
        ``"numeric"`` is omitted, ``"optional_string"`` is omitted silently (an
        optional platform variable the user may leave null).

    """

    source: str | None
    formatter: Callable[[object], str] | None
    required: bool
    kind: str


# The OG1 platform fields, in template order. This one table is the single source
# for four views that used to be maintained separately: the init template defaults
# and the validate required-field check (both in cli/_mission.py), to_og1's
# string-field resolution, and the file->field derivation in platform_from_file.
PLATFORM_FIELDS: dict[str, PlatformField] = {
    "PLATFORM_SERIAL_NUMBER": PlatformField(
        "platform_id", lambda value: str(value).lower(), True, "serial"
    ),
    "PLATFORM_MODEL": PlatformField(None, None, True, "string"),
    "PLATFORM_DEPTH_RATING": PlatformField(None, None, True, "numeric"),
    "PLATFORM_MAKER": PlatformField(None, None, True, "string"),
    "GLIDER_FIRMWARE_VERSION": PlatformField(
        "seaglider_software_version",
        _version("seaglider "),
        False,
        "string",
    ),
    "LANDSTATION_VERSION": PlatformField(
        "base_station_version",
        _version("basestation v"),
        False,
        "string",
    ),
    "WMO_IDENTIFIER": PlatformField("wmo_identifier", str, False, "string"),
    # Optional platform variables (OG1 manual, platform-variables table). Config-only,
    # written only when the user supplies a value; the four with a controlled
    # vocabulary carry its default URL as a <field>_vocabulary attribute (see
    # OPTIONAL_PLATFORM_VARS in convert.py). PLATFORM_MAKER's vocabulary is the
    # platform_maker_vocabulary attribute, handled alongside platform_model_vocabulary.
    "PLATFORM_NAME": PlatformField(None, None, False, "optional_string"),
    "TELECOM_TYPE": PlatformField(None, None, False, "optional_string"),
    "TRACKING_SYSTEM": PlatformField(None, None, False, "optional_string"),
    "BATTERY_TYPE": PlatformField(None, None, False, "optional_string"),
    "BATTERY_PACK": PlatformField(None, None, False, "optional_string"),
}


def platform_from_file(attrs: dict) -> dict:
    """Derive OG1 platform fields from a basestation file's global attributes.

    Parameters
    ----------
    attrs : dict
        The first basestation file's global attributes.

    Returns
    -------
    dict
        The OG1 platform fields derivable from the file (only those whose source
        attribute is present).

    """
    derived = {}
    for field, spec in PLATFORM_FIELDS.items():
        if spec.source is not None and spec.source in attrs:
            derived[field] = spec.formatter(attrs[spec.source])
    return derived


# Raw instrument count channels (WET Labs ECO pucks and similar): the basestation writes
# them without units. They are counts, converted to physical units only with calibration
# coefficients the file does not carry, so they keep their basestation names (not an OG1
# backscatter or fluorescence name) and are labelled with RAW_COUNT_UNITS — the spelling
# the package already writes on ROLL_CTL / PITCH_CTL.
RAW_COUNT_SUFFIXES = ("redCount", "blueCount", "fluorCount", "redRef", "blueRef")
RAW_COUNT_UNITS = "counts"

# The package units view over the vendored family tables (reports/_vendored/units.py). One table
# resolves a reader spelling to the OG1 variable's canonical spelling and the factor to reach it.
# Each row below is a spelling the bundled samples carry that the family default does not already
# cover, with its source. Built eagerly at import by choice: a bad row (a factor that disagrees
# with the family) raises on `import seagliderOG1` loudly, caught by the import-under-`-W error`
# test, rather than failing one conversion quietly. The `g/m^3` density mislabel is NOT here -- it
# is the OG1_unit_corrections.yaml label correction, applied before resolution.
UNITS = _units.merge_tables(
    _units.DEFAULT_TABLES,
    aliases={
        "m s-1": {
            "cm/s": 0.01,
            "cm s-1": 0.01,
        },  # 1 cm/s = 0.01 m/s; sg005/sg271 velocities
        "degree_Celsius": {"degrees_Celsius": 1.0},  # sg005/sg271 temperature
        "seconds": {
            "s": 1.0,
            "secs": 1.0,
        },  # sg271 delta_time_s; basestation log parameters
        "mg m-3": {"micrograms/liter": 1.0},  # sg005 wlbb2f chla; 1 ug/L = 1 mg/m3
        "cm3": {"cc": 1.0},  # basestation eng_vbdCC; 1 cc = 1 cm3
        "kg m-3": {
            "kg/m^3": 1.0
        },  # sg271 correctly-labelled sigma_theta / density family
    },
)


def unit_factor(u_from: str, u_to: str) -> float | None:
    """Return the multiplier converting ``u_from`` into ``u_to``, or None when unrelated.

    Both spellings are resolved through :data:`UNITS`; when they share a canonical, the ratio
    of their factors converts ``u_from`` values into ``u_to``. Units the view cannot relate (a
    different canonical, an unresolvable spelling, or a degenerate zero factor) return None — no
    conversion is invented. The one place the canonical compare and the factor ratio live, so the
    converter shim and the conversion page cannot drift.

    Parameters
    ----------
    u_from : str
        The units the values are in.
    u_to : str
        The units to convert them to.

    Returns
    -------
    float or None
        The multiplier, or None when the two spellings are not relatable.

    """
    try:
        canon_from, factor_from = _units.resolve_units(u_from, tables=UNITS)
        canon_to, factor_to = _units.resolve_units(u_to, tables=UNITS)
    except _units.UnitsError:
        return None
    if canon_from != canon_to or factor_to == 0:
        return None
    return factor_from / factor_to


# Variables to exclude from OG1 output. Empty: every basestation variable is retained. The
# names below were dropped before; kept commented out until the list is removed.
VARIABLES_TO_DROP = [
    # "dissolved_oxygen_sat",
    # "depth",
    # "eng_depth",
    # "eng_elaps_t",
    # "eng_elaps_t_0000",
    # "eng_rec",
    # "eng_GC_state",
    # "latitude_gsm",
    # "longitude_gsm",
    # "sound_velocity",
    # "eng_sbect_condFreq",
    # "eng_sbect_tempFreq",
    # "glide_angle_gsm",
    # "horz_speed_gsm",
    # "north_displacement_gsm",
    # "east_displacement_gsm",
    # "polar_heading",
    # "speed_gsm",
    # "vert_speed_gsm",
    # "dive_num_cast",
    # "density",
    # "gsw_sigma3",
    # "gsw_sigma4",
    # "theta",
    # "time",
]

# Variables to keep unchanged during conversion (currently empty)
VARIABLES_AS_IS = []

# --------------------------------
# Variables + variable attributes
# --------------------------------
# Variable name mappings: basestation variable name -> OG1 standard name
# Based on https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/utilities/vocabularies.py
with (CONFIG_DIR / "OG1_variable_names.yaml").open() as file:
    standard_names = yaml.safe_load(file)

# Basestation units labels that are wrong for the magnitude the variable holds,
# keyed by the basestation (origin) variable name and guarded by the label as
# written. Applied before unit conversion; see OG1_unit_corrections.yaml and the
# range pass in _convert.apply_og1_vocabulary.
with (CONFIG_DIR / "OG1_unit_corrections.yaml").open() as file:
    basestation_unit_corrections = yaml.safe_load(file) or {}

# Basestation variables OG1 has no home for, or names for a different quantity, recommended
# for drop_variables on the conversion page (the default is to keep everything). Keyed by the
# basestation variable name, with the reason shown in the recommendation.
DROP_RECOMMENDATIONS = {
    "gsw_sigma0": (
        "the density anomaly (sigma0 = potential density - 1000); OG1 POTDENS0 is full "
        "potential density, which is derived separately, so gsw_sigma0 has no OG1 home."
    ),
    "sbe43_dissolved_oxygen": (
        "per-mass oxygen (micromoles/kg); OG1 DOXY is per volume (mmol m-3), a different "
        "quantity that needs density to derive, so this is not mapped to DOXY."
    ),
    "dissolved_oxygen_sat": (
        "a per-mass saturation concentration (micromoles/kg); OG1 OXYSAT is percent "
        "saturation, a different quantity, so this is not mapped to OXYSAT."
    ),
}

# Variable attribute vocabularies for OG1 format
# Reference: http://vocab.nerc.ac.uk/scheme/OG1/current/
with (CONFIG_DIR / "OG1_variable_attributes.yaml").open() as file:
    vocab_attrs = yaml.safe_load(file)

# Sensor attribute vocabularies for OG1 format
# Reference: http://vocab.nerc.ac.uk/scheme/OG_SENSORS/current/
with (CONFIG_DIR / "OG1_sensor_attributes.yaml").open() as file:
    sensor_vocabs = yaml.safe_load(file)

# Sensor keys from the basestation `instrument` global -> sensor_vocabs titles. A
# lookup only, kept apart from standard_names so it is never applied as a rename.
with (CONFIG_DIR / "OG1_sensor_names.yaml").open() as file:
    sensor_names = yaml.safe_load(file)


# ACDD 1.3 global attributes by level, for the conversion page's conventions box.
# Transcribed from the IOOS compliance checker (``compliance-checker`` 6.1.0,
# ``compliance_checker/acdd.py``, ``ACDD1_3Check``: the base lists plus the 1.3 extensions),
# which implements https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery_1-3.
# Presence only: the checker also tests some values (ISO dates, geospatial_bounds), which
# the page does not.
ACDD_1_3_HIGHLY_RECOMMENDED: tuple[str, ...] = (
    "title",
    "keywords",
    "summary",
    "Conventions",
)
ACDD_1_3_RECOMMENDED: tuple[str, ...] = (
    "id",
    "naming_authority",
    "history",
    "comment",
    "date_created",
    "creator_name",
    "creator_url",
    "creator_email",
    "institution",
    "project",
    "processing_level",
    "geospatial_bounds",
    "geospatial_lat_min",
    "geospatial_lat_max",
    "geospatial_lon_min",
    "geospatial_lon_max",
    "geospatial_vertical_min",
    "geospatial_vertical_max",
    "time_coverage_start",
    "time_coverage_end",
    "time_coverage_duration",
    "time_coverage_resolution",
    "standard_name_vocabulary",
    "license",
    "geospatial_vertical_positive",
    "geospatial_bounds_crs",
    "geospatial_bounds_vertical_crs",
    "publisher_name",
    "publisher_url",
    "publisher_email",
    "source",
)


# Variables and the dimension an OG1 file must carry to pass the OceanGliders format check.
# Transcribed from the upstream checker (``ioos/cc-plugin-og``,
# ``cc_plugin_og/checker.py`` ``check_mandatory_variables`` / ``check_dimensions``); the
# conversion page's "OG1 required" tier reads this. Nothing yet checks it against the installed
# checker: re-transcribe when cc-plugin-og changes (a CI step running cc-plugin-og is where
# that comparison belongs).
OG1_REQUIRED_VARS: tuple[str, ...] = (
    "LATITUDE_GPS",
    "LONGITUDE_GPS",
    "TIME_GPS",
    "LATITUDE",
    "LONGITUDE",
    "TIME",
    "DEPTH",
    "TRAJECTORY",
    "PLATFORM_MODEL",
    "WMO_IDENTIFIER",
    "PLATFORM_SERIAL_NUMBER",
    "DEPLOYMENT_TIME",
    "DEPLOYMENT_LATITUDE",
    "DEPLOYMENT_LONGITUDE",
)
OG1_REQUIRED_DIMS: tuple[str, ...] = ("N_MEASUREMENTS",)

# Variables the project proposes to canonise but the upstream OG1 vocabulary has not adopted
# yet. The conversion page lifts these out of the carried-through tier into a named candidate
# group, shown present/absent like the required tier, so "what a flight model needs" and "what
# we hope to agree as OG1 parameters" are visible on the page. This is the project's editorial
# list: edit it as the data-format group agrees candidates, and remove a name once it appears in
# OG1_variable_attributes.yaml upstream. Seeded from demo_sg005 (2026-10-19); the membership is
# a proposal to prune, not a standard — the flight-model inputs in particular are a first guess.
OG1_CANDIDATE_VARS: dict[str, str] = {
    # Flight-model outputs: the glider-flight-model products proposed as agreed OG1 parameters.
    "vert_speed_gsm": "flight model — output",
    "horz_speed_gsm": "flight model — output",
    "speed_gsm": "flight model — output",
    "glide_angle_gsm": "flight model — output",
    "latitude_gsm": "flight model — output",
    "longitude_gsm": "flight model — output",
    "north_displacement_gsm": "flight model — output",
    "east_displacement_gsm": "flight model — output",
    "flight_avg_speed_east_gsm": "flight model — output",
    "flight_avg_speed_north_gsm": "flight model — output",
    "depth_avg_curr_east_gsm": "flight model — output",
    "depth_avg_curr_north_gsm": "flight model — output",
    "surface_curr_east": "flight model — output",
    "surface_curr_north": "flight model — output",
    # Measured inputs a flight model consumes (control channels present in demo_sg005).
    "gc_pitch_ctl": "flight model — input",
    "gc_roll_ad": "flight model — input",
    "gc_vbd_ctl": "flight model — input",
}


# --------------------------------
# Global Attributes
# --------------------------------


# Preferred order for global attributes in OG1 files
ATTRIBUTE_ORDER = [
    "title",  # OceanGliders trajectory file
    "id",  # sg015_20040920T000000_delayed
    "platform",  # sub-surface gliders
    "platform_vocabulary",  # https://vocab.nerc.ac.uk/collection/L06/current/27
    "PLATFORM_SERIAL_NUMBER",  # sg015 --> This should be a variable, not an attribute
    "naming_authority",  # edu.washington.apl
    "institution",  # University of washington
    "internal_mission_identifier",  # p0150003_20040924
    "geospatial_lat_min",  # decimal degree
    "geospatial_lat_max",  # decimal degree
    "geospatial_lon_min",  # decimal degree
    "geospatial_lon_max",  # decimal degree
    "geospatial_vertical_min",  # meter depth
    "geospatial_vertical_max",  # meter depth
    "time_coverage_start",  # YYYYmmddTTHHMMss
    "time_coverage_end",  # YYYYmmddTTHHMMss
    "site",  # MOOSE_T00
    "site_vocabulary",  # to be defined
    "program",  # MOOSE glider program
    "program_vocabulary",  # to be defined
    "project",  # SAMBA
    "network",  # Southern California Coastal Ocean Observing System (SCCOOS)
    "contributor_name",  # Firstname Lastname, Firstname Lastname
    "contributor_role",  # Principal Investigator, Operator
    "contributor_role_vocabulary",  # http://vocab.nerc.ac.uk/collection/W08/current/
    "contributor_email",  # name@name.com, name@name.com
    "contributor_id",  # ORCID, ORCID
    "contributing_institutions",  # University of Washington, University of Washington
    "contributing_institutions_vocabulary",  # https://edmo.seadatanet.org/report/544, https://ror.org/012tb2g32
    "contributing_institutions_role",  # PI, Operator
    "contributing_institutions_role_vocabulary",  # https://vocab.nerc.ac.uk/collection/W08/current/
    "uri",  # other universal resource identifiers separated by commas
    "data_url",  # url link to where OG1.0 file is hosted
    "doi",  # data doi for OG1
    "rtqc_method",  # No QC applied
    "rtqc_method_doi",  # n/a
    "web_link",  # url for information rleated to glider mission, multiple urls separated by comma
    "comment",  # miscellaneous information
    "start_date",  # datetime of glider deployment YYYYmmddTHHMMss
    "date_created",  # date of creation of this dataset YYYYmmddTHHMMss
    "featureType",  # trajectory
    "Conventions",  # CF-1.10, ACDD-1.3, OG-1.0
    "date_modified",  # date of last modification of this dataset YYYYmmddTHHMMss
]

# Global attribute configuration for OG1 conversion
# Defines which attributes to keep, rename, or add during conversion
# Compatible with base_station_version 2.8, nodc_template_version_v0.9
with (CONFIG_DIR / "OG1_global_attributes.yaml").open() as file:
    global_attrs = yaml.safe_load(file)

# OG1 global-attribute requirement tiers, keyed "mandatory" / "highly_desirable" /
# "suggested"; each maps an attribute name to its filling source ("derived",
# "constant" or "config"). Transcribed from the OG1 manual (see the file header).
REQUIRED_GLOBALS: dict[str, dict[str, str]] = global_attrs["required"]


# --- deprecated v0.0.2 names (removed in 0.3.0; see seagliderOG1._deprecated) ----------
from seagliderOG1 import _deprecated  # noqa: E402  # shim follows the definitions above

_deprecated.install_removed(
    globals(),
    {
        **dict.fromkeys(
            ("load_default_contributors", "contrib_to_append"),
            "contributors come from the mission.yaml contributors: block now.",
        ),
        **dict.fromkeys(
            ("unit_str_format", "unit1_to_unit2", "preferred_units"),
            "units resolve through vocabularies.UNITS (one view over the vendored "
            "family tables) now.",
        ),
    },
)
