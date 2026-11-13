"""Shared fixtures: one conversion of each bundled mission per test session.

A conversion of the real demo files is the slow step of most tests. Tests that only
read an OG1 file use ``sg005_og1`` directly; tests that edit one take
``sg005_og1_copy``, a private copy of the file and its sidecar. Tests of the
conversion itself (refusals, overwrite, draft, report placement) still convert.
"""

import os
import pathlib
import shutil

import pytest
import xarray as xr

from seagliderOG1 import _convert, writers

SG005 = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005"
SG271 = (
    pathlib.Path(__file__).resolve().parent.parent / "seagliderOG1" / "data" / "sg271"
)


@pytest.fixture(scope="session")
def dev_data() -> pathlib.Path:
    """Return the dev pack folder named by ``SEAGLIDEROG1_DEV_DATA``; skip when unset.

    The dev pack is a collection of single-dive basestation files from several gliders and
    basestation versions, kept outside the repository (see CONTRIBUTING).
    """
    folder = os.environ.get("SEAGLIDEROG1_DEV_DATA")
    if not folder:
        pytest.skip("SEAGLIDEROG1_DEV_DATA is unset; dev-pack tests skipped")
    path = pathlib.Path(folder)
    if not path.is_dir():
        pytest.skip(f"SEAGLIDEROG1_DEV_DATA={folder} is not a folder")
    return path


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


@pytest.fixture(scope="session")
def converted_missions(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Convert the sg271 sample (3 dives) and the sg005 demo (5 dives) once, without a
    mission file; return name -> (written file, its dataset opened without decoding times,
    the raw dive files opened the same way). Do not edit."""
    out = {}
    for name, raw in {"sg271": SG271, "sg005": SG005}.items():
        path = _convert._convert_mission(raw, tmp_path_factory.mktemp(name))
        ds = xr.open_dataset(path, engine="netcdf4", decode_times=False)
        raws = [
            xr.open_dataset(p, engine="netcdf4", decode_times=False)
            for p in sorted(raw.glob("p*.nc"))
        ]
        out[name] = (path, ds, raws)
    yield out
    for _path, ds, raws in out.values():
        ds.close()
        for r in raws:
            r.close()
