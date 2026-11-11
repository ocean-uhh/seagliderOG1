"""The report pages of one converted mission, and the nav rows that link them.

Each page sits beside the OG1 file as ``<stem>_<kind>.html`` (see
:func:`seagliderOG1.writers.page_path`). The nav follows the family reports (ctdcast): a
**Pages** row (the summary and the phase page), a **Provenance** row (how the file was
made), and a **Data inventory** strip naming the files that have an inventory page.
"""

import warnings
from pathlib import Path

import xarray as xr

from seagliderOG1 import vocabularies, writers

__all__ = [
    "NAV_ROWS",
    "number_sections",
    "page_nav",
    "write_linked_pages",
    "write_page",
]

#: The nav rows in order, as ``(label, ((kind, pill label, role), ...))``; the role picks
#: the pill's colour in the vendored styles.
NAV_ROWS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "Pages:",
        (("conversion", "Conversion", "landing"), ("phase", "Phase", "aggregate-a")),
    ),
    (
        "Provenance:",
        (
            ("variables", "Variables", "component"),
            ("processing", "Processing", "component"),
        ),
    ),
)


def number_sections(sections: list[tuple[str, ...] | None]) -> dict:
    """Return a page's sections numbered as the family reports number them.

    The jump-to line and the section headings take their numbers from here, so they
    agree when a section is left out: ``(1)``, ``(2)``, … for the sections, then ``(A)``,
    ``(B)``, … for reference sections (a glossary, the global attributes), as oceanarray
    and ctdcast.

    Parameters
    ----------
    sections : list of tuple or None
        ``(id, label)`` for a section, ``(id, label, "reference")`` for a reference
        section, in page order; None for a section this page leaves out.

    Returns
    -------
    dict
        ``items`` (for the jump-to line: ``id``, ``label``, ``mark``) and ``mark`` (the
        section id to its mark, e.g. ``"(3)"``, for its heading).

    """
    items, number, letter = [], 0, 0
    for section in sections:
        if not section:
            continue
        if len(section) > 2 and section[2] == "reference":
            mark = f"({chr(ord('A') + letter)})"
            letter += 1
        else:
            number += 1
            mark = f"({number})"
        items.append({"id": section[0], "label": section[1], "mark": mark})
    return {"items": items, "mark": {item["id"]: item["mark"] for item in items}}


def _basestation_label(inputs: list[dict]) -> str:
    """Return the dive files as one pill label, e.g. ``p2710001–0054.nc``.

    A record of datasets not read from files has no paths; the label is then the dives.
    """
    if not (inputs[0].get("path") and inputs[-1].get("path")):
        first_dive, last_dive = inputs[0].get("dive"), inputs[-1].get("dive")
        if first_dive == last_dive:
            return f"dive {first_dive}"
        return f"dives {first_dive}–{last_dive}"
    first, last = Path(inputs[0]["path"]), Path(inputs[-1]["path"])
    if first == last:
        return first.name
    if len(first.stem) == len(last.stem) and len(first.stem) > 4:
        return f"{first.stem}–{last.stem[4:]}{first.suffix}"
    return f"{first.name} – {last.name}"


def _basestation_inputs(path: str | Path) -> list[dict]:
    """Return the dive files the conversion record lists, or [] without a usable record."""
    # Lazy: _record imports writers, which the page modules import before this one.
    from seagliderOG1.reports import _record

    with warnings.catch_warnings():
        # The page's own read of the record has already warned about it.
        warnings.simplefilter("ignore")
        record = _record.conversion_sidecar(path) or {}
    if not record.get("input_variables"):
        return []
    return list(record.get("inputs") or [])


def page_nav(
    path: str | Path, current: str, *, has_phase: bool = True, draft: bool = False
) -> dict:
    """Return the nav for the vendored ``page_nav`` and ``inventory_strip`` macros.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 file the pages describe; links are its pages' file names.
    current : str
        The kind of the page this nav sits on (``conversion``, ``phase``, ``variables``,
        ``processing``, ``basestation`` or ``og1``).
    has_phase : bool, default True
        Whether a phase page is written (the file has ``PHASE`` and is not a draft); no
        phase pill otherwise.
    draft : bool, default False
        Whether the file is a draft, which has no OG1 format page, so no inventory pill.

    Returns
    -------
    dict
        ``{"rows": [...], "inventory": [...]}``. The inventory strip names the basestation
        dive files (when the conversion record lists them), linking to the Basestation
        page, then the OG1 file, linking to its OG1 format page (not for a draft).

    """
    rows = []
    for label, pills in NAV_ROWS:
        out = []
        for kind, pill_label, role in pills:
            if kind == "phase" and not has_phase:
                continue
            state = "current" if kind == current else "link"
            href = "" if state == "current" else writers.page_path(path, kind).name
            out.append(
                {"role": role, "state": state, "label": pill_label, "href": href}
            )
        rows.append({"label": label, "pills": out})
    inventory = []
    if inputs := _basestation_inputs(path):
        inventory.append(
            {
                "state": "current" if current == "basestation" else "link",
                "label": _basestation_label(inputs),
                "href": writers.page_path(path, "basestation").name,
            }
        )
    if not draft:
        inventory.append(
            {
                "state": "current" if current == "og1" else "link",
                "label": Path(path).name,
                "href": writers.page_path(path, "og1").name,
            }
        )
    return {"rows": rows, "inventory": inventory}


def write_page(
    nc_path: str | Path, conversion_page: str | Path, kind: str, html: str
) -> Path:
    """Write one page beside the conversion page, as ``<stem>_<kind>.html``.

    The one write path of the linked pages, so a change to how they are written (folder,
    encoding) is made once.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file the page describes; the page is named after it.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; this page goes in the same folder.
    kind : str
        The page kind (``variables``, ``processing``, ``phase``, ``basestation``,
        ``og1``).
    html : str
        The rendered page.

    Returns
    -------
    pathlib.Path
        The page written.

    """
    target = Path(conversion_page).with_name(writers.page_path(nc_path, kind).name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def write_linked_pages(
    nc_path: str | Path,
    conversion_page: str | Path,
    *,
    title: str | None = None,
) -> list[Path]:
    """Write the pages the conversion page links to, beside it, and return them.

    The one place that decides which pages accompany a conversion page: Variables and
    Processing always; Basestation when the conversion record lists the dive files; Phase
    (when the file has ``PHASE``) and OG1 format unless the file is a draft. Whether it is
    a draft is read from the file, so every caller (``process``, ``report``,
    :func:`seagliderOG1.reports.report`) writes the same set.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; the others go in the same folder.
    title : str, optional
        Page title; the file name by default.

    Returns
    -------
    list of pathlib.Path
        The pages written, in nav order.

    """
    # Lazy: these modules import this one at load time.
    from seagliderOG1.reports.basestation import write_basestation_page
    from seagliderOG1.reports.og1 import write_og1_page
    from seagliderOG1.reports.phase import write_phase_page
    from seagliderOG1.reports.processing import write_processing_page
    from seagliderOG1.reports.variables import write_variables_page

    # A draft is not an OG1 file: no Phase or OG1 format page.
    with xr.open_dataset(str(nc_path), engine="netcdf4", decode_times=False) as ds:
        og1_file = ds.attrs.get("draft") != vocabularies.DRAFT_NOTE
    written = [
        write_variables_page(nc_path, conversion_page, title=title),
        write_processing_page(nc_path, conversion_page, title=title),
    ]
    if page := write_basestation_page(nc_path, conversion_page, title=title):
        written.append(page)
    if og1_file and (page := write_phase_page(nc_path, conversion_page, title=title)):
        written.append(page)
    if og1_file:
        written.append(write_og1_page(nc_path, conversion_page, title=title))
    return written
