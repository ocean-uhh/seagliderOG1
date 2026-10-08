"""Tests for seagliderOG1.contributors: aligned comma-list parse/format."""

from seagliderOG1 import contributors


def test_format_contributors_preserves_aligned_empties():
    """Three people with a gap keep equal comma counts across every attribute."""
    people = [
        {
            "name": "Ann Low",
            "email": "ann@x.org",
            "orcid": "0000-0001-0000-0001",
            "role": "PI",
        },
        {"name": "Bo Mid", "email": None, "orcid": None, "role": "Operator"},
        {"name": "Cy Top", "email": "cy@z.org", "orcid": None, "role": "Operator"},
    ]
    attrs = contributors.format_contributors(people)
    for value in attrs.values():
        assert len(contributors.split_aligned(value)) == 3
    assert attrs["contributor_email"] == "ann@x.org, , cy@z.org"
    assert (
        attrs["contributor_role"] == "PI, Operator, Operator"
    )  # two Operators stay two


def test_format_contributors_orcid_and_role_vocabulary():
    """Bare ORCID becomes a URL; PI resolves a term URI; others the collection URL."""
    people = [
        {"name": "Ann", "orcid": "0000-0001-0000-0001", "role": "PI"},
        {"name": "Bo", "orcid": None, "role": "Data scientist"},
    ]
    attrs = contributors.format_contributors(people)
    ids = contributors.split_aligned(attrs["contributor_id"])
    assert ids == ["https://orcid.org/0000-0001-0000-0001", ""]
    vocabs = contributors.split_aligned(attrs["contributor_role_vocabulary"])
    assert vocabs[0] == "http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/"
    assert vocabs[1] == "http://vocab.nerc.ac.uk/collection/W08/current/"


def test_format_contributors_empty():
    """No people yields no attributes."""
    assert contributors.format_contributors([]) == {}


def test_parse_then_format_round_trips_names_and_roles():
    """Parsing aligned attributes and reformatting reproduces names and roles."""
    attrs = {
        "contributor_name": "Ann, Bo, Cy",
        "contributor_email": "ann@x.org, , cy@z.org",
        "contributor_role": "PI, Operator, Operator",
    }
    people = contributors.parse_contributors(attrs)
    assert [p["name"] for p in people] == ["Ann", "Bo", "Cy"]
    out = contributors.format_contributors(people)
    assert out["contributor_name"] == "Ann, Bo, Cy"
    assert out["contributor_role"] == "PI, Operator, Operator"
    assert out["contributor_email"] == "ann@x.org, , cy@z.org"


def test_parse_contributors_drops_trailing_empty_slot():
    """A trailing comma (extra empty slot) does not create an extra person."""
    attrs = {"contributor_name": "Ann, Bo, ", "contributor_role": "PI, Operator, "}
    people = contributors.parse_contributors(attrs)
    assert len(people) == 2


def test_parse_contributors_creators_first():
    """Creators are parsed before contributors."""
    attrs = {"creator_name": "Ann", "contributor_name": "Bo"}
    people = contributors.parse_contributors(attrs)
    assert [p["name"] for p in people] == ["Ann", "Bo"]


def test_institutions_format_and_parse():
    """Institutions format and parse as their own aligned list."""
    institutions = [
        {
            "name": "Uni Hamburg",
            "role": "operating agency",
            "id": "https://edmo.seadatanet.org/report/1156",
        },
        {"name": "Second Inst", "role": "funder", "id": None},
    ]
    attrs = contributors.format_institutions(institutions)
    assert attrs["contributing_institutions"] == "Uni Hamburg, Second Inst"
    assert contributors.split_aligned(
        attrs["contributing_institutions_vocabulary"]
    ) == [
        "https://edmo.seadatanet.org/report/1156",
        "",
    ]
    roundtrip = contributors.parse_institutions(attrs)
    assert [i["name"] for i in roundtrip] == ["Uni Hamburg", "Second Inst"]
