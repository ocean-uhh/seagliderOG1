"""Contributor and institution attributes for OG1, as comma-aligned lists.

OG1 records contributors as parallel comma-separated attributes — ``contributor_name``,
``contributor_email``, ``contributor_id``, ``contributor_role`` and
``contributor_role_vocabulary`` — one slot per person, empty slots preserved so the
lists stay aligned (three people with one email give ``"a@x, , c@z"``). Institutions
are a separate parallel set (``contributing_institutions`` and its ``_role``,
``_vocabulary`` and ``_role_vocabulary``).

This module parses those attributes into records and formats records back, without
dropping interior empties, deduping within a field, or rewriting commas inside a
value. One role per slot: a person with two roles is listed twice.
"""

from collections.abc import Mapping, Sequence

from seagliderOG1 import vocabularies

_ORCID_PREFIX = "https://orcid.org/"

_CONTRIBUTOR_ATTRS = (
    ("name", "contributor_name"),
    ("email", "contributor_email"),
    ("id", "contributor_id"),
    ("role", "contributor_role"),
    ("role_vocabulary", "contributor_role_vocabulary"),
)
_INSTITUTION_ATTRS = (
    ("name", "contributing_institutions"),
    ("role", "contributing_institutions_role"),
    ("id", "contributing_institutions_vocabulary"),
    ("role_vocabulary", "contributing_institutions_role_vocabulary"),
)


def split_aligned(value: object) -> list[str]:
    """Split a comma-separated OG1 attribute into stripped parts, keeping empties.

    Parameters
    ----------
    value : object
        The attribute value (string, or None/empty for an absent attribute).

    Returns
    -------
    list of str
        One stripped element per comma-separated slot; ``[]`` when absent. Interior
        and trailing empties are preserved (``"a, , c"`` becomes ``["a", "", "c"]``).

    """
    if value in (None, ""):
        return []
    return [part.strip() for part in str(value).split(",")]


def normalize_orcid(value: object) -> str:
    """Return an ORCID as a full ``https://orcid.org/…`` URL, or ``""`` when absent.

    Parameters
    ----------
    value : object
        A bare ORCID, a full ORCID URL, or None/empty.

    Returns
    -------
    str
        The normalised URL; an existing ``http`` value is kept; empty stays ``""``.

    """
    if value in (None, "", "None"):
        return ""
    text = str(value)
    if text.startswith("http"):
        return text
    return _ORCID_PREFIX + text


def role_vocabulary(role: str) -> str:
    """Return the vocabulary URL for a contributor role.

    Parameters
    ----------
    role : str
        The role label (e.g. ``"PI"``).

    Returns
    -------
    str
        The known term URI, else the W08 collection URL; ``""`` for an empty role.

    """
    if not role:
        return ""
    return vocabularies.ROLE_VOCABULARY.get(
        role, vocabularies.ROLE_VOCABULARY_COLLECTION
    )


def _records_from(
    attrs: Mapping, fields: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Build aligned records from a mapping of comma-separated OG1 attributes.

    Parameters
    ----------
    attrs : Mapping
        Source attributes.
    fields : sequence of (str, str)
        Pairs of (record key, attribute name).

    Returns
    -------
    list of dict of str to str
        One record per name slot; trailing empty-name slots are dropped.

    """
    columns = {key: split_aligned(attrs.get(attr)) for key, attr in fields}
    names = columns["name"]
    while names and names[-1] == "":
        names.pop()
    records = []
    for index, name in enumerate(names):
        record = {"name": name}
        for key in columns:
            if key != "name":
                column = columns[key]
                record[key] = column[index] if index < len(column) else ""
        records.append(record)
    return records


def parse_contributors(attrs: Mapping) -> list[dict[str, str]]:
    """Parse ``creator_*`` then ``contributor_*`` attributes into person records.

    Parameters
    ----------
    attrs : Mapping
        A dataset's global attributes.

    Returns
    -------
    list of dict of str to str
        Records with ``name``, ``email``, ``id``, ``role`` and ``role_vocabulary``,
        creators first.

    """
    creator_fields = tuple(
        (key, attr.replace("contributor", "creator"))
        for key, attr in _CONTRIBUTOR_ATTRS
    )
    return _records_from(attrs, creator_fields) + _records_from(
        attrs, _CONTRIBUTOR_ATTRS
    )


def format_contributors(people: Sequence[Mapping]) -> dict[str, str]:
    """Format person records into the five aligned ``contributor_*`` attributes.

    Parameters
    ----------
    people : sequence of Mapping
        Records with ``name``, ``email``, ``role`` and either ``id`` or ``orcid``;
        an explicit ``role_vocabulary`` overrides the role-derived one.

    Returns
    -------
    dict of str to str
        The five ``contributor_*`` attributes, each a ``", "``-joined aligned list.
        Empty when ``people`` is empty.

    """
    people = list(people or [])
    if not people:
        return {}
    names = [str(p.get("name") or "") for p in people]
    emails = [str(p.get("email") or "") for p in people]
    ids = [
        normalize_orcid(p.get("id") if p.get("id") is not None else p.get("orcid"))
        for p in people
    ]
    roles = [str(p.get("role") or "") for p in people]
    vocabs = [
        str(p.get("role_vocabulary") or "") or role_vocabulary(role)
        for p, role in zip(people, roles, strict=True)
    ]
    return {
        "contributor_name": ", ".join(names),
        "contributor_email": ", ".join(emails),
        "contributor_id": ", ".join(ids),
        "contributor_role": ", ".join(roles),
        "contributor_role_vocabulary": ", ".join(vocabs),
    }


def parse_institutions(attrs: Mapping) -> list[dict[str, str]]:
    """Parse ``contributing_institutions*`` attributes into institution records.

    Parameters
    ----------
    attrs : Mapping
        A dataset's global attributes.

    Returns
    -------
    list of dict of str to str
        Records with ``name``, ``role`` and ``id``.

    """
    return _records_from(attrs, _INSTITUTION_ATTRS)


def format_institutions(institutions: Sequence[Mapping]) -> dict[str, str]:
    """Format institution records into the four ``contributing_institutions*`` attrs.

    Parameters
    ----------
    institutions : sequence of Mapping
        Records with ``name``, ``role`` and ``id``.

    Returns
    -------
    dict of str to str
        The four aligned ``contributing_institutions*`` attributes; empty when
        ``institutions`` is empty.

    """
    institutions = list(institutions or [])
    if not institutions:
        return {}
    names = [str(i.get("name") or "") for i in institutions]
    roles = [str(i.get("role") or "") for i in institutions]
    ids = [
        str(i.get("id") or "") if i.get("id") is not None else "" for i in institutions
    ]
    vocabs = [vocabularies.ROLE_VOCABULARY_COLLECTION if role else "" for role in roles]
    return {
        "contributing_institutions": ", ".join(names),
        "contributing_institutions_role": ", ".join(roles),
        "contributing_institutions_vocabulary": ", ".join(ids),
        "contributing_institutions_role_vocabulary": ", ".join(vocabs),
    }
