"""The Variables page: every variable of a conversion, basestation input beside OG1 output.

One table, one entry per variable, searchable by either name and filtered by fate,
subsystem and marks. It replaces the conversion page's tier, reconciliation, derived,
by-origin and scalar-parameter tables; the rows come from :mod:`._index`.
"""

from datetime import UTC, datetime
from pathlib import Path

import xarray as xr

from seagliderOG1 import __version__, vocabularies
from seagliderOG1.reports import _index, _masthead, _pages, _record, design
from seagliderOG1.reports._env import get_template

__all__ = ["render_variables", "write_variables_page"]

#: The subsystem filter chips, in order (see :func:`seagliderOG1.vocabularies.subsystem_of`).
SUBSYSTEMS: tuple[str, ...] = (
    "science",
    "sensors",
    "flight",
    "GPS",
    "G&C",
    "engineering",
    "log",
    "calibration",
)


def render_variables(path: str | Path, *, title: str | None = None) -> str:
    """Return the Variables page for an OG1 file as a self-contained HTML string.

    Parameters
    ----------
    path : str or pathlib.Path
        An OG1 netCDF file written by :func:`seagliderOG1.convert`, with its conversion
        record beside it (without the record the input columns read "not recorded").
    title : str, optional
        The page title; defaults to the file name.

    Returns
    -------
    str
        The rendered HTML page.

    """
    record = _record.conversion_sidecar(path)
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        ledger = _record.conversion_ledger(ds)
        rows = _index.variable_rows(ds, ledger, record)
        draft = ds.attrs.get("draft") == vocabularies.DRAFT_NOTE
        has_phase = "PHASE" in ds.variables and not draft
    fates = [key for key, _meaning in _index.FATES] + ["derived"]
    counts = {key: sum(r["fate"] == key for r in rows) for key in fates}
    return get_template("variables.html").render(
        title=title or Path(path).name,
        css=design.SHARED_CSS,
        version=__version__,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        masthead=_masthead.masthead(path, "variables", title=title),
        page_nav=_pages.page_nav(path, "variables", has_phase=has_phase, draft=draft),
        rows=rows,
        fates=[(key, counts[key]) for key in fates if counts[key]],
        fate_meanings=dict(_index.FATES)
        | {"derived": "Built by the converter; its inputs are listed."},
        subsystems=[s for s in SUBSYSTEMS if any(r["subsystem"] == s for r in rows)],
        record_present=bool(record and record.get("input_variables")),
        input_count=ledger["input_variable_count"],
        n_candidates=sum(bool(r["candidate"]) for r in rows),
        absent_candidates=sorted(
            set(vocabularies.OG1_CANDIDATE_VARS)
            - {r["name"] for r in rows}
            - {r["basestation"] for r in rows}
        ),
    )


def write_variables_page(
    nc_path: str | Path, conversion_page: str | Path, *, title: str | None = None
) -> Path:
    """Write the Variables page beside the conversion page and return it.

    Parameters
    ----------
    nc_path : str or pathlib.Path
        The OG1 file.
    conversion_page : str or pathlib.Path
        Where its conversion page was written; the Variables page goes in the same folder.
    title : str, optional
        Page title; the file name by default.

    Returns
    -------
    pathlib.Path
        The page written.

    """
    return _pages.write_page(
        nc_path, conversion_page, "variables", render_variables(nc_path, title=title)
    )
