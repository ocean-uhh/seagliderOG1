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

import pathlib
import warnings
from collections.abc import Mapping, Sequence

import yaml

from seagliderOG1 import vocabularies

_ORCID_PREFIX = "https://orcid.org/"
_REGISTRY_PATH = pathlib.Path(vocabularies.config_dir) / "institution_registry.yml"

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


def normalize_role(role: str) -> str | None:
    """Return the preferred W08 label for a role.

    Parameters
    ----------
    role : str
        The role label as given (any case), a known spelling variant, or empty.

    Returns
    -------
    str or None
        The preferred W08 label; ``""`` for an empty (role-less) value; ``None``
        when the role is not a W08 term or attested alias (caller decides whether
        that is a config error or a file-derived passthrough).

    """
    if not role or not str(role).strip():
        return ""
    key = str(role).strip()
    if key in vocabularies.ROLE_VOCABULARY:
        return key
    lowered = key.lower()
    for label in vocabularies.ROLE_VOCABULARY:
        if label.lower() == lowered:
            return label
    return vocabularies.ROLE_ALIASES.get(lowered)


def _preferred_role(role: str) -> str:
    """Return the preferred label for a known role, else the role unchanged."""
    normalized = normalize_role(role)
    return role if normalized is None else normalized


def role_vocabulary(role: str) -> str:
    """Return the W08 term URI for a contributor or institution role.

    Parameters
    ----------
    role : str
        The role label (any case) or a known spelling variant.

    Returns
    -------
    str
        The term URI from :data:`vocabularies.ROLE_VOCABULARY`; ``""`` for an empty
        or unrecognised role (an unrecognised role is never given a URL).

    """
    normalized = normalize_role(role)
    if not normalized:
        return ""
    return vocabularies.ROLE_VOCABULARY[normalized]


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
    raw_roles = [str(p.get("role") or "") for p in people]
    roles = [_preferred_role(role) for role in raw_roles]
    vocabs = [
        str(p.get("role_vocabulary") or "") or role_vocabulary(role)
        for p, role in zip(people, raw_roles, strict=True)
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
    raw_roles = [str(i.get("role") or "") for i in institutions]
    roles = [_preferred_role(role) for role in raw_roles]
    ids = [
        str(i.get("id") or "") if i.get("id") is not None else "" for i in institutions
    ]
    vocabs = [role_vocabulary(role) for role in raw_roles]
    return {
        "contributing_institutions": ", ".join(names),
        "contributing_institutions_role": ", ".join(roles),
        "contributing_institutions_vocabulary": ", ".join(ids),
        "contributing_institutions_role_vocabulary": ", ".join(vocabs),
    }


def _norm_name(name: object) -> str:
    """Return a name with whitespace (and newlines) collapsed, stripped, lower-cased."""
    return " ".join(str(name or "").split()).strip().lower()


def _fill(target: dict, source: Mapping) -> None:
    """Fill empty fields of ``target`` from ``source`` in place."""
    for key, value in source.items():
        if not target.get(key) and value:
            target[key] = value


def consolidate(records: Sequence[Mapping]) -> list[dict[str, str]]:
    """Merge records on (normalised name, role), filling empty fields.

    Same person/institution with the same role from two sources becomes one slot,
    its empty email/id filled from the duplicate. Two different roles stay two
    slots. A role-less record merges into a same-name record that has a role (in
    either order); a role is never invented and two roles are never combined.

    Parameters
    ----------
    records : sequence of Mapping
        Records with at least ``name`` and ``role``.

    Returns
    -------
    list of dict of str to str
        Consolidated records, order preserved by first appearance.

    """
    result: list[dict[str, str]] = []
    for original in records:
        record = dict(original)
        name_key = _norm_name(record.get("name"))
        role = record.get("role") or ""
        merged = False
        for index, existing in enumerate(result):
            if _norm_name(existing.get("name")) != name_key:
                continue
            existing_role = existing.get("role") or ""
            if existing_role == role:
                _fill(existing, record)
                merged = True
                break
            if role == "" and existing_role != "":
                _fill(existing, record)
                merged = True
                break
            if role != "" and existing_role == "":
                _fill(record, existing)
                result[index] = record
                merged = True
                break
        if not merged:
            result.append(record)
    return result


def load_institution_registry() -> dict[str, tuple[str, str]]:
    """Load the EDMO institution registry into a name lookup.

    Returns
    -------
    dict of str to (str, str)
        Maps each normalised standard name and name variant to its
        ``(standard_name, id_url)``.

    """
    with open(_REGISTRY_PATH) as file:
        data = yaml.safe_load(file)
    lookup: dict[str, tuple[str, str]] = {}
    for entry in data.get("institutions", {}).values():
        standard = entry["standard_name"]
        id_url = entry.get("id_url", "")
        for variant in [standard, *entry.get("name_variants", [])]:
            lookup[_norm_name(variant)] = (standard, id_url)
    return lookup


def enrich_institutions(institutions: Sequence[Mapping]) -> list[dict[str, str]]:
    """Resolve institution names against the EDMO registry.

    A name (whitespace-collapsed) matched in the registry is written as the
    registry ``standard_name`` with the EDMO URL; a config ``id`` wins over the
    registry. An unmatched name is written as given (a comma replaced by a space,
    with a warning) and no EDMO id (also warned); nothing is invented.

    Parameters
    ----------
    institutions : sequence of Mapping
        Records with ``name``, ``role`` and optional ``id``.

    Returns
    -------
    list of dict of str to str
        Records with ``name``, ``role`` and ``id`` resolved for formatting.

    """
    lookup = load_institution_registry()
    enriched = []
    for institution in institutions:
        collapsed = " ".join(str(institution.get("name") or "").split()).strip()
        role = institution.get("role") or ""
        config_id = institution.get("id")
        has_config_id = config_id not in (None, "", "None")
        hit = lookup.get(collapsed.lower())
        if hit is not None:
            name = hit[0]
            institution_id = str(config_id) if has_config_id else hit[1]
        else:
            name = collapsed
            if "," in collapsed:
                warnings.warn(
                    f"institution {collapsed!r} is not in institution_registry.yml and "
                    "contains a comma; writing it with the comma replaced by a space. "
                    "Add it to the registry to get an EDMO id.",
                    stacklevel=2,
                )
                name = " ".join(collapsed.replace(",", " ").split())
            institution_id = str(config_id) if has_config_id else ""
            if not institution_id:
                warnings.warn(
                    f"no EDMO id for institution {collapsed!r}; add it to "
                    "institution_registry.yml or set id: in the config.",
                    stacklevel=2,
                )
        enriched.append({"name": name, "role": role, "id": institution_id})
    return enriched
