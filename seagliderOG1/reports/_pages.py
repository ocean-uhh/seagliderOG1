"""The report pages of one converted mission, and the nav row that links them.

Each page sits beside the OG1 file as ``<stem>_<kind>.html`` (see
:func:`seagliderOG1.writers.page_path`); the nav row on every page names them all, links the
ones written, and shows the rest as not yet generated.
"""

from pathlib import Path

from seagliderOG1 import writers

__all__ = ["PAGES", "page_nav"]

#: The pages in nav order, as ``(kind, label)``. ``basestation`` and ``og1`` are planned
#: inventory pages, not written yet, so their pills show as not generated.
PAGES: tuple[tuple[str, str], ...] = (
    ("conversion", "conversion"),
    ("variables", "variables"),
    ("processing", "processing"),
    ("phase", "phase"),
    ("basestation", "basestation"),
    ("og1", "OG1 format"),
)

#: The pages this package writes today; the others show as not generated.
WRITTEN: frozenset[str] = frozenset({"conversion", "variables", "phase"})


def page_nav(path: str | Path, current: str, *, has_phase: bool = True) -> dict:
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
        elif kind in WRITTEN:
            state, href = "link", writers.page_path(path, kind).name
        else:
            state, href = "missing", ""
        pills.append({"role": kind, "state": state, "label": label, "href": href})
    return {"rows": [{"label": "", "pills": pills}]}
