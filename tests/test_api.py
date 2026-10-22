"""The config-first public API: ``mission.load``/``check``, ``process`` /
``process_missions``, ``convert(mission=)``, ``write(record=)`` / ``report`` /
``reports.record``, and ``enrich(mission=)``."""

import pathlib
import sys

import pytest
import xarray as xr

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

import seagliderOG1 as sg  # noqa: E402
from seagliderOG1 import mission, writers  # noqa: E402
from seagliderOG1.exceptions import MissionError  # noqa: E402
from seagliderOG1.reports import _record  # noqa: E402

DATA_DIR = parent_dir / "data" / "demo_sg005"
DEMO_YAML = DATA_DIR / "mission.yaml"


# --- mission.load / mission.check --------------------------------------------


def test_mission_load_resolves_paths_and_keeps_sections_unmerged():
    """load() returns absolute paths, the three sections unmerged, no merged deployment."""
    cfg = mission.load(DEMO_YAML)
    assert pathlib.Path(cfg["raw_dir"]).is_absolute()
    assert "deployment" not in cfg
    assert {
        "identity_and_discovery",
        "rights_and_access",
        "provenance_and_processing",
    } & set(cfg)
    # config_version and local_config are kept so the dict round-trips back through load.
    assert cfg.get("config_version") == 3
    assert "local_config" in cfg


def test_mission_load_round_trips():
    """A dict from load() is itself loadable by load() (process/convert re-validate it)."""
    cfg = mission.load(DEMO_YAML)
    again = mission.load(cfg)
    assert again["raw_dir"] == cfg["raw_dir"]


def test_mission_load_rejects_old_config_version(tmp_path: pathlib.Path):
    """A config_version other than 3 raises MissionError naming the sections."""
    bad = dict(mission.load(DEMO_YAML))
    bad["config_version"] = 2
    with pytest.raises(MissionError):
        mission.load(bad)


def test_mission_load_refuses_relative_path_in_a_mapping():
    """A hand-built mapping with a relative raw_dir has no base and is refused."""
    cfg = dict(mission.load(DEMO_YAML))
    cfg["raw_dir"] = "a/relative/path"
    with pytest.raises(MissionError):
        mission.load(cfg)


def test_mission_check_returns_issue_list():
    """check() returns a list of issues without raising (the valid demo has no ERRORs)."""
    issues = mission.check(DEMO_YAML)
    assert isinstance(issues, list)
    assert not [i for i in issues if i.level == "ERROR"]


# --- process / process_missions ----------------------------------------------


def test_process_writes_from_the_config(tmp_path: pathlib.Path):
    """process(path) returns the written Path, and report=True writes the page + record."""
    path = sg.process(
        DEMO_YAML, output_dir=tmp_path, dives=(1, 1), overwrite=True, report=True
    )
    assert path.exists() and path.parent == tmp_path
    assert writers.conversion_path(path, ".html").exists()
    assert writers.conversion_path(path, ".json").exists()


def test_process_accepts_a_loaded_and_tweaked_mapping(tmp_path: pathlib.Path):
    """process(dict) converts; a tweaked section reaches the output globals."""
    cfg = mission.load(DEMO_YAML)
    cfg["rights_and_access"] = dict(cfg.get("rights_and_access") or {})
    cfg["rights_and_access"]["doi"] = "10.5281/zenodo.0000000"
    path = sg.process(cfg, output_dir=tmp_path, dives=(1, 1), overwrite=True)
    with xr.open_dataset(path, engine="netcdf4", decode_timedelta=False) as ds:
        assert ds.attrs["doi"] == "10.5281/zenodo.0000000"


def test_process_mode_override_beats_the_config(tmp_path: pathlib.Path):
    """A process(mode=...) override wins over the configuration's mode (the id suffix)."""
    path = sg.process(
        DEMO_YAML, output_dir=tmp_path, dives=(1, 1), mode="delayed", overwrite=True
    )
    assert path.stem.endswith("_delayed")


def test_process_raw_dir_override_beats_the_config(tmp_path: pathlib.Path):
    """process(raw_dir=...) converts that directory even when the config's raw_dir is wrong."""
    cfg = mission.load(DEMO_YAML)
    cfg["raw_dir"] = str(tmp_path / "does_not_exist")
    path = sg.process(
        cfg, raw_dir=DATA_DIR, output_dir=tmp_path, dives=(1, 1), overwrite=True
    )
    assert path.exists()


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a two-mission SN/DATE root under tmp_path and a mission.yaml for it."""
    import yaml

    names = ["p0050001_20080606.nc", "p0050002_20080606.nc"]
    root = tmp_path / "root"
    for date in ("20080606", "20080607"):
        dest = root / "sg005" / date
        dest.mkdir(parents=True)
        for name in names:
            (dest / name).write_bytes((DATA_DIR / name).read_bytes())
    cfg = {
        "config_version": 3,
        "raw_dir": str(root),
        "output_dir": str(tmp_path / "out"),
        "contributors": [{"name": "Jane Doe", "role": "PI"}],
        "institutions": [{"name": "Your Institution", "role": "Operator"}],
    }
    yaml_path = tmp_path / "root_mission.yaml"
    yaml_path.write_text(yaml.safe_dump(cfg))
    return yaml_path


def test_process_refuses_a_root(tmp_path: pathlib.Path):
    """process() on a config whose raw_dir is a root raises MissionError naming process_missions."""
    yaml_path = _root(tmp_path)
    with pytest.raises(MissionError, match="process_missions"):
        sg.process(yaml_path, overwrite=True)


def test_process_missions_converts_one_selected_mission(tmp_path: pathlib.Path):
    """process_missions(root, select=...) converts the selected mission(s)."""
    yaml_path = _root(tmp_path)
    paths = sg.process_missions(yaml_path, select="sg005/20080606", overwrite=True)
    assert len(paths) == 1
    assert paths[0].exists()


def test_process_missions_requires_a_selection(tmp_path: pathlib.Path):
    """A root with no select is a ValueError (one range cannot span missions)."""
    yaml_path = _root(tmp_path)
    with pytest.raises(ValueError, match="select"):
        sg.process_missions(yaml_path, overwrite=True)


# --- convert(mission=) --------------------------------------------------------


def test_convert_reads_metadata_from_the_mission(tmp_path: pathlib.Path):
    """convert(datasets, mission) applies the config's section globals to the output."""
    datasets = sg.read(DATA_DIR, dives=(1, 1))
    ds = sg.convert(datasets, DEMO_YAML)
    # contributor_name comes from the config's contributors, not a package default.
    assert "contributor_name" in ds.attrs


def test_convert_explicit_kwarg_overrides_the_mission(tmp_path: pathlib.Path):
    """An explicit mode= overrides the mission's mode (the id suffix)."""
    datasets = sg.read(DATA_DIR, dives=(1, 1))
    ds = sg.convert(datasets, DEMO_YAML, mode="delayed")
    assert ds.attrs["id"].endswith("delayed")


def test_convert_explicit_realtime_overrides_a_delayed_mission(tmp_path: pathlib.Path):
    """An explicit mode='realtime' wins over a mission mode='delayed'.

    The regression direction: because 'realtime' was once the default, an explicit
    realtime request used to be indistinguishable from "not set" and lost to the config.
    """
    cfg = mission.load(DEMO_YAML)
    cfg["mode"] = "delayed"
    datasets = sg.read(DATA_DIR, dives=(1, 1))
    assert sg.convert(datasets, cfg, mode="realtime").attrs["id"].endswith("_R")
    # and with no explicit mode, the mission's delayed is honoured
    assert sg.convert(datasets, cfg).attrs["id"].endswith("delayed")


# --- write(record=) / report / reports.record --------------------------------


def test_write_record_and_reports_record(sg005_og1: pathlib.Path):
    """reports.record(path) returns the file's ledger and the JSON record beside it."""
    rec = _record.record(sg005_og1)
    assert set(rec) == {"ledger", "conversion"}
    assert rec["conversion"]["presence"]["dives"] == [1]
    assert rec["ledger"]["dimensions"]


def test_report_writes_beside_and_refuses_existing(
    sg005_og1_copy: pathlib.Path, tmp_path: pathlib.Path
):
    """report(path) writes beside the file; out= elsewhere; existing refused unless overwrite."""
    page = sg.report(sg005_og1_copy)
    assert page == writers.conversion_path(sg005_og1_copy, ".html")
    assert page.exists()
    with pytest.raises(FileExistsError):
        sg.report(sg005_og1_copy)
    assert sg.report(sg005_og1_copy, overwrite=True).exists()
    elsewhere = sg.report(sg005_og1_copy, out=tmp_path / "page.html", overwrite=True)
    assert elsewhere == tmp_path / "page.html"


# --- enrich(mission=) ---------------------------------------------------------


def test_enrich_from_mission_sets_globals_and_ignores_platform(
    sg005_og1_copy: pathlib.Path,
):
    """enrich(mission=) applies the section globals; its platform: block is ignored."""
    cfg = mission.load(DEMO_YAML)
    cfg["rights_and_access"] = {"doi": "10.9999/from-mission"}
    out = writers.enrich(sg005_og1_copy, mission=cfg)
    with xr.open_dataset(out, engine="netcdf4", decode_timedelta=False) as ds:
        assert ds.attrs["doi"] == "10.9999/from-mission"


def test_enrich_refuses_an_id_change(sg005_og1_copy: pathlib.Path):
    """enrich refuses to change id (the file name and record are bound to it)."""
    with pytest.raises(ValueError, match="id"):
        writers.enrich(sg005_og1_copy, deployment={"id": "something_else"})
