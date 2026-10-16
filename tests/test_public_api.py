"""Guard the public API surface: public modules declare __all__, and the private
pipeline is never reached from outside the package (notebooks, docs)."""

import importlib
import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

PUBLIC_MODULES = [
    "readers",
    "convert",
    "writers",
    "tools",
    "plotters",
    "contributors",
]


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
