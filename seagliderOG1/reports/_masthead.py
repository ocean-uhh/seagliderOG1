"""The masthead every report page of a conversion shares: what the mission is, at a glance.

One builder for the six pages, so the title, the facts grid and the warnings agree. The
layout follows the family reports (oceanarray, ctdcast): the thing described as the title,
the page type at the right, a subtitle saying what the page is, the labelled nav rows, then
a grid of the deployment's facts, with a warning shown in the grid where one applies.
"""

import contextlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr

from seagliderOG1 import vocabularies
from seagliderOG1.reports import _record

__all__ = ["PAGE_TYPES", "masthead"]

#: Each page's type label (top right), subtitle and masthead role. The landing page is
#: ``landing`` (blue, as ctdcast's index); the others keep the navy masthead.
PAGE_TYPES: dict[str, tuple[str, str, str]] = {
    "conversion": (
        "Conversion",
        "Conversion summary · Seaglider basestation to OG1",
        "landing",
    ),
    "variables": (
        "Variables",
        "Every variable: basestation input beside OG1 output",
        "",
    ),
    "processing": (
        "Processing",
        "Every step of the conversion, in the order it ran",
        "",
    ),
    "phase": ("Phase", "How PHASE was assigned, and what it gives", ""),
    "basestation": (
        "Basestation",
        "The basestation dive files: what they hold, across the mission",
        "",
    ),
    "og1": ("OG1 format", "The OG1 file: conformance and inventory", ""),
}


def _degrees_minutes(value: float, positive: str, negative: str, width: int) -> str:
    """Return a coordinate as degrees and decimal minutes, e.g. ``72° 58.80′ S``."""
    hemisphere = positive if value >= 0 else negative
    degrees, minutes = divmod(abs(value) * 60, 60)
    return f"{int(degrees):0{width}d}° {minutes:05.2f}′ {hemisphere}"


def _scalar(ds: xr.Dataset, name: str) -> object | None:
    """Return a one-value variable's value, or None when absent or empty."""
    if name not in ds.variables or ds[name].size != 1:
        return None
    value = np.asarray(ds[name].values).ravel()[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, np.floating) and not np.isfinite(value):
        return None
    if isinstance(value, np.datetime64) and np.isnat(value):
        return None
    return value


def _utc(value: object) -> str | None:
    """Return a time as ``YYYY-MM-DD HH:MM UTC``, or None when it cannot be read.

    Reads a datetime64 or a compact (``20260302T193828``) or ISO string, with or without
    fractional seconds and a trailing ``Z``.
    """
    if value is None:
        return None
    text = str(value).strip().removesuffix("Z").split(".")[0]
    for fmt in ("%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            continue
    return None


def _duration(start: object, end: object) -> str | None:
    """Return the span between two times as ``7 d 5 h`` (or ``5 h 06 m`` under a day)."""
    try:
        first = datetime.strptime(str(_utc(start)), "%Y-%m-%d %H:%M UTC")
        last = datetime.strptime(str(_utc(end)), "%Y-%m-%d %H:%M UTC")
    except ValueError:
        return None
    seconds = int((last - first).total_seconds())
    if seconds < 0:
        return None
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days} d {hours} h"
    return f"{hours} h {rest // 60:02d} m"


def _facts(
    ds: xr.Dataset, record: dict | None, *, draft: bool
) -> list[tuple[str, str, bool]]:
    """Return the facts grid as ``(label, value, warn)``, absent facts left out."""
    # Lazy: these modules import the page modules that import this one.
    from seagliderOG1.reports import _index, og1, processing

    attrs = ds.attrs
    facts: list[tuple[str, str, bool]] = []

    def add(label: str, value: object, warn: bool = False) -> None:
        if value not in (None, "", "UNK"):
            facts.append((label, str(value), warn))

    serial = _scalar(ds, "PLATFORM_SERIAL_NUMBER")
    wmo = _scalar(ds, "WMO_IDENTIFIER")
    add("Glider", f"{serial} · WMO {wmo}" if serial and wmo else serial)
    add("Model", _scalar(ds, "PLATFORM_MODEL"))
    add("Project", attrs.get("project"))
    add("Institution", attrs.get("institution"))
    add("Site", attrs.get("site"))
    deployed = _scalar(ds, "DEPLOYMENT_TIME")
    add("Deployed", _utc(deployed))
    lat, lon = _scalar(ds, "DEPLOYMENT_LATITUDE"), _scalar(ds, "DEPLOYMENT_LONGITUDE")
    if isinstance(lat, float | np.floating) and isinstance(lon, float | np.floating):
        add(
            "Deployment position",
            f"{_degrees_minutes(float(lat), 'N', 'S', 2)}, "
            f"{_degrees_minutes(float(lon), 'E', 'W', 3)}",
        )
    add(
        "Duration",
        _duration(attrs.get("time_coverage_start"), attrs.get("time_coverage_end")),
    )
    dives = ((record or {}).get("presence") or {}).get("dives") or []
    if dives:
        span = f"{dives[0]}–{dives[-1]}" if len(dives) > 1 else str(dives[0])
        add("Dives", f"{len(dives)} ({span})")
    with contextlib.suppress(KeyError, TypeError, ValueError):
        add("Max depth", f"{float(attrs['geospatial_vertical_max']):.0f} m")
    versions = [
        v
        for v in (
            _scalar(ds, "LANDSTATION_VERSION"),
            _scalar(ds, "GLIDER_FIRMWARE_VERSION"),
        )
        if v
    ]
    if not versions:
        found = ((record or {}).get("basestation_globals") or {}).get(
            "base_station_version", {}
        )
        versions = [f"basestation {v}" for v in sorted(set(found.get("values", [])))]
    add("Basestation", " · ".join(str(v) for v in versions))
    mode = str(attrs.get("id", "")).rsplit("_", 1)[-1]
    add("Mode", {"R": "real time", "D": "delayed"}.get(mode))
    inputs = (record or {}).get("inputs") or []
    add("Source", f"{len(inputs)} dive files" if inputs else None)
    add("Processed", _utc(attrs.get("date_created")))
    ledger = _record.conversion_ledger(ds)
    rows = _index.variable_rows(ds, ledger, record)
    kinds = [
        loss
        for loss in processing.losses(record, rows)
        if loss["count"] or loss["count"] is None
    ]
    add("Losses", f"⚠ {len(kinds)} kinds" if kinds else "none", bool(kinds))
    if not draft:
        unmet = [
            r
            for r in og1.conformance_rows(ds)
            if r["tier"] == "mandatory" and not r["met"]
        ]
        add(
            "OG1 conformance",
            f"⚠ {len(unmet)} mandatory not met"
            if unmet
            else "every mandatory item met",
            bool(unmet),
        )
    return facts


def masthead(path: str | Path, kind: str, *, title: str | None = None) -> dict:
    """Return the masthead of one report page.

    Parameters
    ----------
    path : str or pathlib.Path
        The OG1 file the pages describe (its conversion record beside it, if any).
    kind : str
        The page: a key of :data:`PAGE_TYPES`.
    title : str, optional
        A title to use instead of the one built from the file.

    Returns
    -------
    dict
        ``title`` (the glider and site, else the file's ``id``), ``type`` and
        ``subtitle`` (from :data:`PAGE_TYPES`; a draft's type reads Draft), ``role``,
        ``generated`` (``YYYY-MM-DD HH:MM UTC``), ``draft`` and ``facts`` (a list of
        ``(label, value, warn)``).

    """
    record = _record.conversion_sidecar(path)
    with xr.open_dataset(str(path), engine="netcdf4", decode_timedelta=False) as ds:
        draft = ds.attrs.get("draft") == vocabularies.DRAFT_NOTE
        serial = _scalar(ds, "PLATFORM_SERIAL_NUMBER")
        site = str(ds.attrs.get("site", "")).strip()
        built = f"{serial} · {site}" if serial and site else ds.attrs.get("id")
        facts = _facts(ds, record, draft=draft)
    label, subtitle, role = PAGE_TYPES[kind]
    if draft and kind == "conversion":
        label = "Draft"
    return {
        "title": title or built or Path(path).stem,
        "type": label,
        "subtitle": subtitle,
        "role": role,
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "draft": draft,
        "facts": facts,
    }
