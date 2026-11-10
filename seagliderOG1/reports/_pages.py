"""The report pages of one converted mission, and the nav row that links them.

Each page sits beside the OG1 file as ``<stem>_<kind>.html`` (see
:func:`seagliderOG1.writers.page_path`); the nav row on every page names them all, links the
ones written, and shows the rest as not yet generated.
"""

from pathlib import Path

from seagliderOG1 import writers

__all__ = ["PAGES", "page_nav", "write_linked_pages"]

#: The pages in nav order, as ``(kind, label)``. ``basestation`` is a planned inventory
#: page, not written yet, so its pill shows as not generated.
PAGES: tuple[tuple[str, str], ...] = (
    ("conversion", "conversion"),
    ("variables", "variables"),
    ("processing", "processing"),
    ("phase", "phase"),
    ("basestation", "basestation"),
    ("og1", "OG1 format"),
)

#: The pages this package writes today; the others show as not generated.
WRITTEN: frozenset[str] = frozenset(
    {"conversion", "variables", "processing", "phase", "og1"}
)


def page_nav(
    path: str | Path, current: str, *, has_phase: bool = True, draft: bool = False
) -> dict:
    """Return the page-nav structure for the vendored ``page_nav`` macro.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 file the pages describe; links are its pages' file names.
    current : str
        The kind of the page this nav sits on (one of :data:`PAGES`).
    has_phase : bool, default True
        Whether a phase page is written (the file has ``PHASE`` and is not a draft); no
        phase pill otherwise.
    draft : bool, default False
        Whether the file is a draft; a draft has no OG1 format page, so that pill shows
        as not generated.

    Returns
    -------
    dict
        ``{"rows": [...]}`` for ``page_nav``.

    """
    pills = []
    for kind, label in PAGES:
        if kind == "phase" and not has_phase:
            continue
        if kind == current:
            state, href = "current", ""
        elif kind in WRITTEN and not (draft and kind == "og1"):
            state, href = "link", writers.page_path(path, kind).name
        else:
            state, href = "missing", ""
        pills.append({"role": kind, "state": state, "label": label, "href": href})
    return {"rows": [{"label": "", "pills": pills}]}


def write_linked_pages(
    nc_path: str | Path,
    conversion_page: str | Path,
    *,
    title: str | None = None,
    phase: bool = True,
) -> list[Path]:
    """Write the pages the conversion page links to, beside it, and return them.

    The one place that decides which pages accompany a conversion page: Variables and
    Processing always; Phase (when the file has ``PHASE``) and OG1 format unless the file
    is a draft.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; the others go in the same folder.
    title : str, optional
        Page title; the file name by default.
    phase : bool, default True
        Whether to write the phase and OG1 format pages (a draft, which is not an OG1
        file, has neither).

    Returns
    -------
    list of pathlib.Path
        The pages written, in nav order.

    """
    # Lazy: these modules import this one at load time.
    from seagliderOG1.reports.og1 import write_og1_page
    from seagliderOG1.reports.phase import write_phase_page
    from seagliderOG1.reports.processing import write_processing_page
    from seagliderOG1.reports.variables import write_variables_page

    written = [
        write_variables_page(nc_path, conversion_page, title=title),
        write_processing_page(nc_path, conversion_page, title=title),
    ]
    if phase and (page := write_phase_page(nc_path, conversion_page, title=title)):
        written.append(page)
    if phase:
        written.append(write_og1_page(nc_path, conversion_page, title=title))
    return written
