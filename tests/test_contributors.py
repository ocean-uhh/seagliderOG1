"""Tests for seagliderOG1.contributors: aligned comma-list parse/format."""

from seagliderOG1 import contributors


def test_format_contributors_preserves_aligned_empties() -> None:
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


def test_format_contributors_orcid_and_role_vocabulary() -> None:
    """Bare ORCID becomes a URL; each role resolves to its W08 term URI."""
    people = [
        {"name": "Ann", "orcid": "0000-0001-0000-0001", "role": "PI"},
        {"name": "Bo", "orcid": None, "role": "Data scientist"},
    ]
    attrs = contributors.format_contributors(people)
    ids = contributors.split_aligned(attrs["contributor_id"])
    assert ids == ["https://orcid.org/0000-0001-0000-0001", ""]
    vocabs = contributors.split_aligned(attrs["contributor_role_vocabulary"])
    assert vocabs[0] == "http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/"
    assert vocabs[1] == "http://vocab.nerc.ac.uk/collection/W08/current/CONT0006/"


def test_normalize_role_labels_aliases_and_unknown() -> None:
    """Known labels (any case) and attested aliases normalise; unknown is None."""
    assert contributors.normalize_role("PI") == "PI"
    assert contributors.normalize_role("operator") == "Operator"
    assert contributors.normalize_role("Principal investigator") == "PI"
    assert contributors.normalize_role("principal investigator") == "PI"
    assert contributors.normalize_role("") == ""
    assert contributors.normalize_role("Chief Wrangler") is None


def test_format_contributors_normalises_role_label_and_passes_unknown() -> None:
    """A known role is written as its preferred label; an unknown role passes through."""
    people = [
        {"name": "Ann", "role": "principal investigator"},
        {"name": "Bo", "role": "Chief Wrangler"},
    ]
    attrs = contributors.format_contributors(people)
    assert contributors.split_aligned(attrs["contributor_role"]) == [
        "PI",
        "Chief Wrangler",
    ]
    vocabs = contributors.split_aligned(attrs["contributor_role_vocabulary"])
    assert vocabs == ["http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/", ""]


def test_format_contributors_empty() -> None:
    """No people yields no attributes."""
    assert contributors.format_contributors([]) == {}


def test_parse_then_format_round_trips_names_and_roles() -> None:
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


def test_parse_contributors_drops_trailing_empty_slot() -> None:
    """A trailing comma (extra empty slot) does not create an extra person."""
    attrs = {"contributor_name": "Ann, Bo, ", "contributor_role": "PI, Operator, "}
    people = contributors.parse_contributors(attrs)
    assert len(people) == 2


def test_parse_contributors_creators_first() -> None:
    """Creators are parsed before contributors."""
    attrs = {"creator_name": "Ann", "contributor_name": "Bo"}
    people = contributors.parse_contributors(attrs)
    assert [p["name"] for p in people] == ["Ann", "Bo"]


def test_institutions_format_and_parse() -> None:
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


def test_consolidate_role_less_merges_into_role_bearing() -> None:
    """A role-less creator merges into a same-name record that has a role."""
    records = [
        {"name": "Charlie Eriksen", "email": "eriksen@uw.edu", "role": ""},
        {"name": "Charlie Eriksen", "email": "", "role": "PI"},
    ]
    out = contributors.consolidate(records)
    assert len(out) == 1
    assert out[0]["role"] == "PI"
    assert out[0]["email"] == "eriksen@uw.edu"  # filled from the role-less record


def test_consolidate_merges_role_aliases() -> None:
    """A file's 'Principal investigator' and a config 'PI' are the same role → one slot."""
    records = [
        {"name": "Ann", "email": "ann@x.org", "role": "Principal investigator"},
        {"name": "Ann", "email": "", "role": "PI"},
    ]
    out = contributors.consolidate(records)
    assert len(out) == 1
    assert out[0]["role"] == "PI"
    assert out[0]["email"] == "ann@x.org"


def test_consolidate_keeps_distinct_names_and_roles() -> None:
    """Different names stay; same name with two roles stays two."""
    records = [
        {"name": "Olle", "role": "Operator"},
        {"name": "Aleksandra", "role": "Operator"},
        {"name": "Ann", "role": "PI"},
        {"name": "Ann", "role": "Data scientist"},
    ]
    out = contributors.consolidate(records)
    assert len(out) == 4


def test_enrich_institutions_matches_multiline_basestation_name() -> None:
    """The multi-line basestation institution matches EDMO 1434 to a comma-free name."""
    raw = "School of Oceanography\nUniversity of Washington\nSeattle, WA 98195-5351"
    out = contributors.enrich_institutions([{"name": raw, "role": ""}])
    assert out[0]["name"] == "University of Washington (School of Oceanography)"
    assert out[0]["id"] == "https://edmo.seadatanet.org/report/1434"


def test_enrich_institutions_config_id_wins_and_unknown_warns() -> None:
    """A config id overrides the registry; an unknown name warns with no id."""
    import warnings

    hit = contributors.enrich_institutions(
        [
            {
                "name": "University of Hamburg (IfM)",
                "role": "Operator",
                "id": "https://ror.org/x",
            }
        ]
    )
    assert hit[0]["id"] == "https://ror.org/x"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        miss = contributors.enrich_institutions(
            [{"name": "Nowhere Institute", "role": ""}]
        )
    assert miss[0]["id"] == ""
    assert any("no EDMO id" in str(w.message) for w in caught)
