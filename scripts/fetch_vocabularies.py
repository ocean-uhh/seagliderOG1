"""Write the offline copies of the vocabularies the variable attributes are checked against.

Three files under ``tests/data/vocabularies/``, read by ``tests/test_variable_vocabulary.py``
so the check never needs the network:

``og1_terms.yaml``
    Every term of the NERC OG1 collection (id -> preferred label, with deprecated terms
    marked), from the NERC Vocabulary Server SPARQL endpoint.
``p01_terms.yaml``
    The P01 terms that ``OG1_variable_attributes.yaml`` points at (code -> preferred label).
``cf_standard_names.yaml``
    The CF standard-name table: version, and each name with its canonical units.

Usage::

    python scripts/fetch_vocabularies.py
"""

import datetime
import json
import pathlib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "data" / "vocabularies"
ATTRS = ROOT / "seagliderOG1" / "config" / "OG1_variable_attributes.yaml"

NVS = "http://vocab.nerc.ac.uk/collection/"
SPARQL = "https://vocab.nerc.ac.uk/sparql/sparql"
CF_TABLE = (
    "https://cfconventions.org/Data/cf-standard-names/current/src/"
    "cf-standard-name-table.xml"
)


def _get(url: str, accept: str | None = None) -> bytes:
    """Return the body of ``url``.

    Parameters
    ----------
    url : str
        The address to read.
    accept : str or None, optional
        An ``Accept`` header value.

    Returns
    -------
    bytes
        The response body.

    """
    request = urllib.request.Request(url, headers={"Accept": accept} if accept else {})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def collection_terms(collection: str) -> dict[str, dict[str, object]]:
    """Return every current term of an NVS collection as ``{id: {label, deprecated}}``.

    Parameters
    ----------
    collection : str
        The collection id, e.g. ``"OG1"``.

    Returns
    -------
    dict of str to dict
        Term id (the last path segment of its URI) to its preferred label and whether NVS
        marks it deprecated.

    """
    query = f"""
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        SELECT ?c ?label ?deprecated WHERE {{
          <{NVS}{collection}/current/> skos:member ?c .
          ?c skos:prefLabel ?label .
          OPTIONAL {{ ?c owl:deprecated ?deprecated }}
        }}"""
    url = f"{SPARQL}?{urllib.parse.urlencode({'query': query})}"
    rows = json.loads(_get(url, "application/sparql-results+json"))["results"][
        "bindings"
    ]
    terms = {}
    for row in rows:
        term = row["c"]["value"].rstrip("/").rsplit("/", 1)[-1]
        terms[term] = {
            "label": row["label"]["value"],
            "deprecated": row.get("deprecated", {}).get("value") == "true",
        }
    return dict(sorted(terms.items()))


def p01_codes_in_use() -> list[str]:
    """Return the P01 codes ``OG1_variable_attributes.yaml`` points at.

    Returns
    -------
    list of str
        Sorted P01 codes.

    """
    attrs = yaml.safe_load(ATTRS.read_text(encoding="utf-8"))
    codes = set()
    for entry in attrs.values():
        link = str((entry or {}).get("vocabulary", ""))
        if "/collection/P01/" in link:
            codes.add(link.rstrip("/").rsplit("/", 1)[-1])
    return sorted(codes)


def p01_terms(codes: list[str]) -> dict[str, dict[str, object]]:
    """Return ``{code: {label, deprecated}}`` for the given P01 codes.

    Parameters
    ----------
    codes : list of str
        P01 codes.

    Returns
    -------
    dict of str to dict
        Each code found in P01, with its preferred label and deprecation.

    """
    terms = {}
    for code in codes:
        url = f"{NVS}P01/current/{code}/?_profile=nvs&_mediatype=application/ld+json"
        graph = json.loads(_get(url))
        nodes = graph.get("@graph", [graph])
        node = next(n for n in nodes if "skos:prefLabel" in n)
        label = node["skos:prefLabel"]
        terms[code] = {
            "label": label.get("@value", label) if isinstance(label, dict) else label,
            "deprecated": str(node.get("owl:deprecated", "false")).lower() == "true",
        }
    return terms


def cf_standard_names() -> tuple[str, dict[str, str]]:
    """Return the CF table version and ``{standard_name: canonical_units}``.

    Aliases (renamed standard names) are not included: a name written to a file must be a
    current entry.

    Returns
    -------
    tuple of (str, dict of str to str)
        The table version and the names with their canonical units.

    """
    root = ET.fromstring(_get(CF_TABLE))
    names = {
        entry.get("id"): (entry.findtext("canonical_units") or "").strip()
        for entry in root.findall("entry")
    }
    return root.findtext("version_number"), dict(sorted(names.items()))


def _write(name: str, header: str, body: dict) -> None:
    """Write ``body`` as YAML under ``OUT`` with a comment header.

    Parameters
    ----------
    name : str
        File name.
    header : str
        Comment lines (without ``#``) placed at the top.
    body : dict
        The content.

    """
    text = "".join(f"# {line}\n" for line in header.splitlines())
    text += yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=1000)
    (OUT / name).write_text(text, encoding="utf-8")


def main() -> None:
    """Fetch the three vocabularies and write them under ``tests/data/vocabularies/``."""
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    _write(
        "og1_terms.yaml",
        f"NERC OG1 collection ({NVS}OG1/current/), fetched {today}.\n"
        "Written by scripts/fetch_vocabularies.py; do not edit by hand.",
        {"fetched": today, "terms": collection_terms("OG1")},
    )
    _write(
        "p01_terms.yaml",
        f"The NERC P01 terms OG1_variable_attributes.yaml points at, fetched {today}.\n"
        "Written by scripts/fetch_vocabularies.py; do not edit by hand.",
        {"fetched": today, "terms": p01_terms(p01_codes_in_use())},
    )
    version, names = cf_standard_names()
    _write(
        "cf_standard_names.yaml",
        f"CF standard-name table version {version} ({CF_TABLE}), fetched {today}.\n"
        "Each name with its canonical units. Written by scripts/fetch_vocabularies.py; do\n"
        "not edit by hand.",
        {"fetched": today, "version": int(version), "names": names},
    )


if __name__ == "__main__":
    main()
