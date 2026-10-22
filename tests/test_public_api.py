"""Guard the public API surface: the frozen verb contract, each public module's
``__all__``, the import graph (library code never reaches into the CLI), the single
mission-config parser, and that no jargon leaks into user-facing strings."""

import importlib
import inspect
import pathlib
import re
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

PKG = parent_dir / "seagliderOG1"

PUBLIC_MODULES = [
    "readers",
    "mission",
    "writers",
    "tools",
    "plotters",
    "contributors",
]

CONTRACT = [
    "MetadataError",
    "MissionError",
    "__version__",
    "convert",
    "enrich",
    "mission",
    "process",
    "process_missions",
    "read",
    "report",
    "write",
]


def test_package_all_is_the_verb_contract():
    """``seagliderOG1.__all__`` is exactly the frozen verb set, and each name resolves."""
    import seagliderOG1 as sg

    assert sorted(sg.__all__) == sorted(CONTRACT)
    for name in sg.__all__:
        assert getattr(sg, name) is not None, f"{name} does not resolve"


def test_public_modules_define_all():
    """Each public module declares __all__ with existing, non-private names."""
    for name in PUBLIC_MODULES:
        mod = importlib.import_module(f"seagliderOG1.{name}")
        assert hasattr(mod, "__all__"), f"{name} defines no __all__"
        for sym in mod.__all__:
            assert hasattr(mod, sym), f"{name}.__all__ lists a missing name: {sym}"
            assert not sym.startswith("_"), f"{name}.__all__ advertises private {sym}"


def test_pipeline_not_advertised():
    """The private _pipeline module is not re-exported by any public module."""
    for name in PUBLIC_MODULES:
        mod = importlib.import_module(f"seagliderOG1.{name}")
        assert "_pipeline" not in getattr(mod, "__all__", [])


def test_no_external_private_imports():
    """Shipped notebooks and docs must not reach into seagliderOG1._pipeline."""
    offenders = []
    for pattern in ("notebooks/*.ipynb", "docs/source/*.rst"):
        for path in parent_dir.glob(pattern):
            if "_pipeline" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(parent_dir)))
    assert not offenders, f"private _pipeline referenced from: {offenders}"


def test_library_does_not_import_cli():
    """No module outside ``cli/`` imports from ``seagliderOG1.cli`` (no reverse dependency)."""
    offenders = []
    for py in PKG.rglob("*.py"):
        rel = py.relative_to(PKG)
        if rel.parts[0] == "cli":
            continue
        if re.search(
            r"(from|import)\s+seagliderOG1\.cli\b", py.read_text(encoding="utf-8")
        ):
            offenders.append(str(rel))
    assert not offenders, f"library modules import from cli: {offenders}"


def test_only_mission_parses_a_mission_config():
    """The mission-config parser lives only in ``mission.py``.

    Scoped (per the plan's N2) to the names that *parse a mission config* —
    ``_read_yaml`` / ``_load_raw`` — not to ``yaml.safe_load`` generally (vocabularies and
    contributors read packaged YAML, which is not a mission config).
    """
    definers, importers = [], []
    for py in PKG.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if re.search(r"def _(read_yaml|load_raw)\b", text) and py.name != "mission.py":
            definers.append(str(py.relative_to(PKG)))
        if re.search(r"import\s+_(read_yaml|load_raw)\b", text):
            importers.append(str(py.relative_to(PKG)))
    assert not definers, f"_read_yaml/_load_raw defined outside mission.py: {definers}"
    assert not importers, f"_read_yaml/_load_raw imported elsewhere: {importers}"


def _cli_help_strings() -> str:
    """Return every argparse help/description/epilog string, joined."""
    from seagliderOG1 import cli

    texts: list[str] = []

    def walk(parser: object) -> None:
        texts.append(getattr(parser, "description", "") or "")
        texts.append(getattr(parser, "epilog", "") or "")
        for action in parser._actions:
            texts.append(action.help or "")
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for sub in choices.values():
                    walk(sub)

    walk(cli.build_parser())
    return " ".join(texts)


def test_no_jargon_in_user_facing_strings():
    """``sidecar`` / ``ledger`` / ``provenance`` do not appear in user-facing strings.

    Scoped (per the plan's N3) to the CLI help, the page template, and the docstrings of
    the public-contract names — not to identifiers or internal module docstrings, which
    decision 8 lets keep the old words. The ``.rst`` sources are covered on the docs branch.
    """
    import seagliderOG1 as sg

    bad = ("sidecar", "ledger", "provenance")
    hits = []

    for name in (
        "read",
        "convert",
        "write",
        "report",
        "enrich",
        "process",
        "process_missions",
    ):
        doc = (inspect.getdoc(getattr(sg, name)) or "").lower()
        hits += [f"{name} docstring: {w}" for w in bad if w in doc]
    for name in ("load", "check"):
        doc = (inspect.getdoc(getattr(sg.mission, name)) or "").lower()
        hits += [f"mission.{name} docstring: {w}" for w in bad if w in doc]

    for html in (PKG / "reports" / "templates").glob("*.html"):
        low = html.read_text(encoding="utf-8").lower()
        hits += [f"{html.name}: {w}" for w in bad if w in low]

    help_blob = _cli_help_strings().lower()
    hits += [f"cli help: {w}" for w in bad if w in help_blob]

    assert not hits, hits
