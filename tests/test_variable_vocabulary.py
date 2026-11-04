"""The variable attributes' vocabulary links and CF standard names are valid.

Checked offline against the copies in ``tests/data/vocabularies/`` (written by
``scripts/fetch_vocabularies.py``): every ``vocabulary`` names a current term of the NERC OG1
collection, or of P01 where OG1 has none, and every ``standard_name`` is a current entry of
the CF standard-name table.
"""

import pathlib
import re

import netCDF4
import pytest
import yaml

from seagliderOG1 import _convert, vocabularies

TESTS = pathlib.Path(__file__).parent
VOCAB = TESTS / "data" / "vocabularies"
DATA = TESTS.parent / "data" / "demo_sg005"
LINK = re.compile(
    r"^http://vocab\.nerc\.ac\.uk/collection/(?P<collection>OG1|P01)/current/(?P<term>[^/]+)/$"
)


def _load(name: str) -> dict:
    return yaml.safe_load((VOCAB / name).read_text(encoding="utf-8"))


def _entries() -> dict[str, dict]:
    return {k: v for k, v in vocabularies.vocab_attrs.items() if isinstance(v, dict)}


def test_no_uri_attribute_remains():
    """OG1 names the attribute ``vocabulary``; the old ``uri`` key is gone."""
    assert not [name for name, attrs in _entries().items() if "uri" in attrs]


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


def test_p01_only_where_og1_has_no_term():
    """A P01 link is used only when no OG1 term carries the same label."""
    og1_labels = {t["label"].lower() for t in _load("og1_terms.yaml")["terms"].values()}
    p01 = _load("p01_terms.yaml")["terms"]
    shadowed = [
        code for code, term in p01.items() if term["label"].lower() in og1_labels
    ]
    assert not shadowed


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


def test_every_standard_name_is_a_current_cf_name():
    """Each ``standard_name`` is an entry (not an alias) of the cached CF table."""
    names = _load("cf_standard_names.yaml")["names"]
    unknown = {
        name: attrs["standard_name"]
        for name, attrs in _entries().items()
        if attrs.get("standard_name") and attrs["standard_name"] not in names
    }
    assert not unknown


def test_converted_file_carries_vocabulary(tmp_path):
    """The attribute reaches the written file under its OG1 name."""
    path = _convert._convert_mission(str(DATA), tmp_path, dives=(1, 1))
    with netCDF4.Dataset(path) as nc:
        temp = nc["TEMP"]
        assert temp.vocabulary == "http://vocab.nerc.ac.uk/collection/OG1/current/TEMP/"
        assert "uri" not in temp.ncattrs()
