"""Shared fixtures: one sg005 conversion per test session.

A conversion of the real demo files is the slow step of most tests. Tests that only
read an OG1 file use ``sg005_og1`` directly; tests that edit one take
``sg005_og1_copy``, a private copy of the file and its sidecar. Tests of the
conversion itself (refusals, overwrite, draft, report placement) still convert.
"""

import pathlib
import shutil

import pytest

from seagliderOG1 import _convert, writers

SG005 = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005"


@pytest.fixture(scope="session")
def sg005_og1(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Return an OG1 file converted from sg005 dive 1, with its sidecar; do not edit."""
    return _convert._convert_mission(
        SG005, tmp_path_factory.mktemp("sg005_og1"), dives=(1, 1)
    )


@pytest.fixture
def sg005_og1_copy(sg005_og1: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a private copy of ``sg005_og1`` and its sidecar in ``tmp_path``."""
    target = tmp_path / sg005_og1.name
    shutil.copy2(sg005_og1, target)
    shutil.copy2(
        writers.conversion_path(sg005_og1, ".json"),
        writers.conversion_path(target, ".json"),
    )
    return target
