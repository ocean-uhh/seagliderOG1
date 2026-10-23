"""Generate the Unit mapping docs page from the bundled samples.

Writes ``docs/source/_static/units/units_mapping.html``: for each bundled sample
(with its basestation version), a table of every mapped variable's source units,
the OG1 canonical spelling, the factor, and the action the converter takes. Run
by the docs Makefile (``make units``) so the page is rebuilt on every docs build
and cannot drift from ``vocabularies.UNITS``.
"""

import html
import pathlib
import warnings
from collections import Counter

import xarray as xr

import seagliderOG1 as sg
from seagliderOG1 import readers, vocabularies
from seagliderOG1.reports._vendored import units

REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "source" / "_static" / "units" / "units_mapping.html"

# Action display order and colour.
ORDER = {
    "convert": 0,
    "relabel": 1,
    "label correction": 2,
    "wrong-quantity (mapping removed)": 3,
    "no source units": 4,
    "unchanged": 5,
}
COLOUR = {
    "convert": "#b45309",
    "wrong-quantity (mapping removed)": "#b91c1c",
    "label correction": "#7c3aed",
    "relabel": "#047857",
    "unchanged": "#9ca3af",
    "no source units": "#6b7280",
}


def _rows(mission_dir: str) -> list[tuple[str, str, str, str, str, str]]:
    """Return ``(og1_var, source, canonical, target, factor, action)`` per mapped variable."""
    corrections = vocabularies.basestation_unit_corrections
    datasets = readers.read_mission(mission_dir, 1, 1)
    raw = datasets[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        og1 = sg.convert(datasets)
    rows, seen = [], set()
    for name in og1.data_vars:
        origin = str(og1[name].attrs.get("original_name", ""))
        target_attrs = vocabularies.vocab_attrs.get(name, {})
        if origin in ("", name) or "units" not in target_attrs:
            continue
        target = target_attrs["units"]
        standard_name = target_attrs.get("standard_name")
        source = raw[origin].attrs.get("units") if origin in raw.variables else None
        if (name, origin, str(source)) in seen:
            continue
        seen.add((name, origin, str(source)))
        if origin in corrections and source == corrections[origin]["from"]:
            action, canonical, factor = (
                "label correction",
                corrections[origin]["to"],
                "-",
            )
            source_text = f"{source} -> {corrections[origin]['to']}"
        elif source in (None, ""):
            action, canonical, factor, source_text = (
                "no source units",
                target,
                "-",
                "(none)",
            )
        else:
            try:
                canonical, value = units.resolve_units(
                    str(source),
                    standard_name,
                    tables=vocabularies.UNITS,
                    canonical=target,
                )
                if value != 1:
                    action = "convert"
                elif str(source) == str(canonical):
                    action = "unchanged"
                else:
                    action = "relabel"
                factor, source_text = f"x{value:g}", str(source)
            except units.UnitsError:
                action, canonical, factor = "wrong-quantity (mapping removed)", "-", "-"
                source_text = str(source)
        rows.append((name, source_text, str(canonical), target, factor, action))
    rows.sort(key=lambda row: (ORDER.get(row[5], 9), row[0]))
    return rows


def _basestation_version(mission_dir: str) -> str:
    """Return the ``base_station_version`` global of the mission's first dive file."""
    first = sorted(pathlib.Path(mission_dir).glob("p*.nc"))[0]
    value = xr.open_dataset(first, engine="netcdf4", decode_times=False).attrs.get(
        "base_station_version", "unknown"
    )
    return str(value)


def _section(tag: str, mission_dir: str) -> str:
    """Return the HTML for one sample's heading, legend and table."""
    rows = _rows(mission_dir)
    counts = Counter(row[5] for row in rows)
    legend = " &middot; ".join(
        f"<b style='color:{COLOUR[action]}'>{action}</b>: {counts[action]}"
        for action in ORDER
        if counts.get(action)
    )
    body = "".join(
        f"<tr><td><b>{name}</b></td><td>{html.escape(src)}</td>"
        f"<td>{html.escape(canon)}</td><td>{html.escape(target)}</td><td>{factor}</td>"
        f"<td style='color:{COLOUR[action]};font-weight:600'>{action}</td></tr>"
        for name, src, canon, target, factor, action in rows
    )
    return (
        f"<h3>{tag} &mdash; basestation {_basestation_version(mission_dir)}</h3>"
        f"<p>{legend}</p><table><tr><th>OG1 variable</th><th>source units</th>"
        "<th>canonical</th><th>OG1 target</th><th>factor</th><th>action</th></tr>"
        f"{body}</table>"
    )


def main() -> None:
    """Build the page and write it under ``_static/units``."""
    samples = [
        ("sg005", str(REPO / "data" / "demo_sg005")),
        ("sg271", str(readers.SAMPLE_DIR)),
    ]
    sections = "".join(_section(tag, mission_dir) for tag, mission_dir in samples)
    doc = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        "body{font:14px -apple-system,system-ui,sans-serif;padding:16px;color:#111}"
        "table{border-collapse:collapse;margin-bottom:18px}"
        "td,th{border:1px solid #ddd;padding:4px 10px;text-align:left}"
        "th{background:#f3f4f6}h3{margin-top:26px}</style></head><body>"
        "<p><b>unchanged</b>: the source is already the OG1 spelling (no-op). "
        "<b>relabel</b>: same quantity, a different spelling, values unchanged (factor 1). "
        "<b>convert</b>: factor is not 1, values are multiplied. "
        "<b>label correction</b>: the basestation label is wrong for the magnitude the values hold. "
        "<b>no source units</b>: the source had no units; the OG1 label is adopted. "
        "<b>wrong-quantity</b>: the source is a different quantity, so the mapping is removed and "
        "it passes through under its basestation name.</p>"
        f"{sections}</body></html>"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"regenerated {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
