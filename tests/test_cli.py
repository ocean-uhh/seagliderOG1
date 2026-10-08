"""Tests for the seagliderOG1 command-line interface (``init``, ``validate``)."""

import pathlib
import subprocess
import sys

import pytest
import yaml

from seagliderOG1 import cli
from seagliderOG1.cli import _mission

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005"


def _write_config(path: pathlib.Path, **overrides: object) -> pathlib.Path:
    """Write a minimal valid mission config, applying overrides, and return its path."""
    config: dict[str, object] = {
        "config_version": 1,
        "source": str(DATA_DIR),
        "output_dir": "./",
        "contributors": [{"name": "Jane Doe", "role": "PI"}],
        "institutions": [{"name": "Your Institution", "role": "Operator"}],
    }
    config.update(overrides)
    path.write_text(yaml.safe_dump(config))
    return path


# --- parser ---------------------------------------------------------------


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """``--version`` prints a version and exits 0."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "seagliderOG1" in capsys.readouterr().out


def test_no_command_is_usage_error() -> None:
    """Invoking with no subcommand is a usage error (exit 2)."""
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_help_imports_stay_light() -> None:
    """Building the parser must not import xarray or matplotlib."""
    code = (
        "import sys; from seagliderOG1 import cli; cli.build_parser(); "
        "assert 'xarray' not in sys.modules, 'xarray imported'; "
        "assert 'matplotlib' not in sys.modules, 'matplotlib imported'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


# --- init ------------------------------------------------------------------


def test_init_writes_template(tmp_path: pathlib.Path) -> None:
    """``init`` writes a parseable template with the expected keys."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "-o", str(out)]) == 0
    data = yaml.safe_load(out.read_text())
    assert set(data) >= {"source", "contributors", "platform", "mode"}
    assert data["mode"] == "delayed"


def test_init_refuses_overwrite_without_force(tmp_path: pathlib.Path) -> None:
    """``init`` refuses an existing file unless ``--force`` is given."""
    out = tmp_path / "mission.yaml"
    out.write_text("existing")
    assert cli.main(["init", "-o", str(out)]) == 1
    assert out.read_text() == "existing"
    assert cli.main(["init", "-o", str(out), "--force"]) == 0
    assert out.read_text() != "existing"


def test_init_from_fills_platform(tmp_path: pathlib.Path) -> None:
    """``init --from`` fills the platform block from the first basestation file."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    platform = yaml.safe_load(out.read_text())["platform"]
    assert platform["PLATFORM_SERIAL_NUMBER"] == "sg005"
    assert str(platform["GLIDER_FIRMWARE_VERSION"]).startswith("seaglider")
    assert str(platform["LANDSTATION_VERSION"]).startswith("basestation")


def test_init_from_then_validate_passes(tmp_path: pathlib.Path) -> None:
    """The documented two-command workflow works: init --from writes a valid config."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    assert yaml.safe_load(out.read_text())["source"] == str(DATA_DIR.resolve())
    assert cli.main(["validate", str(out)]) == 0


# --- process ---------------------------------------------------------------


def _simple_fake_convert(_datasets: object, **kwargs: object) -> tuple:
    """Stand in for convert_to_OG1: no real conversion, deterministic id from mode."""
    import xarray as xr

    suffix = "R" if kwargs.get("mode") == "realtime" else "delayed"
    ds = xr.Dataset({"x": ("n", [1.0, 2.0])}, attrs={"id": f"sg005_{suffix}"})
    return ds, None


def _build_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a two-mission SN/DATE root in tmp_path from the sample files."""
    names = [f.name for f in DATA_DIR.iterdir() if f.name.endswith(".nc")]
    for date in ("20080606", "20080607"):
        dest = tmp_path / "005" / date
        dest.mkdir(parents=True)
        for name in names:
            (dest / name).write_bytes((DATA_DIR / name).read_bytes())
    return tmp_path


def test_process_writes_output(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process converts the mission and writes <id>.nc under the output dir."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", source=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config)]) == 0
    assert (out / "sg005_delayed.nc").is_file()


def test_process_dry_run_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-n prints the target path but writes no file."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", source=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "-n"]) == 0
    assert not out.exists()


def test_process_mode_realtime_sets_suffix(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--mode realtime names the output with the R data-mode suffix."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", source=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "--mode", "realtime"]) == 0
    assert (out / "sg005_R.nc").is_file()


def test_process_existing_output_refused_then_force_and_skip(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing output is refused by default, overwritten with --force, skipped with --skip-existing."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", source=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config)]) == 0
    assert cli.main(["process", str(config)]) == 1  # exists, refused
    assert cli.main(["process", str(config), "--skip-existing"]) == 0
    assert cli.main(["process", str(config), "--force"]) == 0


def test_process_root_all_converts_each(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root with --all converts every SN/DATE mission (distinct ids per mission)."""
    from seagliderOG1 import convertOG1

    counter = {"n": 0}

    def counting_fake(_datasets: object, **_kwargs: object) -> tuple:
        import xarray as xr

        counter["n"] += 1
        ds = xr.Dataset({"x": ("n", [1.0])}, attrs={"id": f"sg005_m{counter['n']}"})
        return ds, None

    monkeypatch.setattr(convertOG1, "convert_to_OG1", counting_fake)
    root = _build_root(tmp_path / "root")
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", source=str(root), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "--all"]) == 0
    assert len(list(out.glob("*.nc"))) == 2


def test_process_root_requires_selection(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root without --all/--mission is an error."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    root = _build_root(tmp_path / "root")
    config = _write_config(
        tmp_path / "mission.yaml", source=str(root), output_dir=str(tmp_path / "out")
    )
    assert cli.main(["process", str(config)]) == 1


def test_process_failing_mission_exits_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mission that raises is counted as failed and the run exits 1."""
    from seagliderOG1 import convertOG1

    def failing(_datasets: object, **_kwargs: object) -> tuple:
        msg = "boom"
        raise ValueError(msg)

    monkeypatch.setattr(convertOG1, "convert_to_OG1", failing)
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(DATA_DIR),
        output_dir=str(tmp_path / "out"),
    )
    assert cli.main(["process", str(config)]) == 1


# --- validate --------------------------------------------------------------


def test_validate_accepts_valid_config(tmp_path: pathlib.Path) -> None:
    """A minimal valid config validates with exit 0."""
    config = _write_config(tmp_path / "mission.yaml")
    assert cli.main(["validate", str(config)]) == 0


def test_validate_rejects_unknown_key(tmp_path: pathlib.Path) -> None:
    """An unknown top-level key is an ERROR (pure schema check, no real data)."""
    config = _write_config(tmp_path / "mission.yaml", source=str(tmp_path), nonsense=1)
    assert cli.main(["validate", str(config)]) == 1
    issues = _mission.validate_config(config)
    assert any(i.level == "ERROR" and i.key == "nonsense" for i in issues)


def test_validate_rejects_bad_types(tmp_path: pathlib.Path) -> None:
    """mode, dives and keep_variables type errors surface without real data."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        mode="sideways",
        dives="all",
        keep_variables="TEMP",
    )
    bad = {i.key for i in _mission.validate_config(config) if i.level == "ERROR"}
    assert {"mode", "dives", "keep_variables"} <= bad


def test_validate_rejects_non_w08_role(tmp_path: pathlib.Path) -> None:
    """A role outside the W08 vocabulary is an ERROR."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        contributors=[{"name": "Ann", "role": "Chief Wrangler"}],
    )
    assert any(
        i.level == "ERROR" and "W08" in i.message
        for i in _mission.validate_config(config)
    )


def test_validate_rejects_name_with_comma(tmp_path: pathlib.Path) -> None:
    """A contributor name containing a comma is an ERROR."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        contributors=[{"name": "Doe, Jane", "role": "PI"}],
    )
    assert any(
        i.level == "ERROR" and "comma" in i.message
        for i in _mission.validate_config(config)
    )


def test_validate_requires_pi_and_operator(tmp_path: pathlib.Path) -> None:
    """Missing a PI contributor and an Operator institution are both ERRORs."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        contributors=[{"name": "Ann", "role": "Data scientist"}],
        institutions=[{"name": "Inst", "role": "Owner"}],
    )
    errors = [i.message for i in _mission.validate_config(config) if i.level == "ERROR"]
    assert any("PI" in message for message in errors)
    assert any("Operator" in message for message in errors)


def test_validate_warns_on_roles_list(tmp_path: pathlib.Path) -> None:
    """A single-element roles: is a warning (prefer role:), not an error."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        contributors=[{"name": "Ann", "roles": ["PI"]}],
    )
    issues = _mission.validate_config(config)
    assert any(i.level == "WARNING" and "roles:" in i.message for i in issues)
    assert not any(
        i.level == "ERROR" and (i.key or "").startswith("contributors") for i in issues
    )


def test_validate_requires_source(tmp_path: pathlib.Path) -> None:
    """A missing ``source`` is an ERROR."""
    path = tmp_path / "mission.yaml"
    path.write_text(yaml.safe_dump({"contributors": [{"name": "Jane"}]}))
    assert cli.main(["validate", str(path)]) == 1


def test_validate_missing_file_is_exit_two(tmp_path: pathlib.Path) -> None:
    """Validating a non-existent config exits 2."""
    assert cli.main(["validate", str(tmp_path / "nope.yaml")]) == 2


def test_validate_dives_out_of_range(tmp_path: pathlib.Path) -> None:
    """A ``dives`` range beyond the files present is an ERROR."""
    config = _write_config(tmp_path / "mission.yaml", dives=[1, 99])
    issues = _mission.validate_config(config)
    assert any(i.level == "ERROR" and i.key == "dives" for i in issues)


def test_validate_strict_flags_gap(tmp_path: pathlib.Path) -> None:
    """``--strict`` reports a dive missing from the range."""
    mission = tmp_path / "mission_dir"
    mission.mkdir()
    for name in ("p0050001_20080606.nc", "p0050003_20080606.nc"):
        (mission / name).write_bytes((DATA_DIR / name).read_bytes())
    config = _write_config(tmp_path / "mission.yaml", source=str(mission), dives=[1, 3])
    assert not [
        i for i in _mission.validate_config(config, strict=False) if i.key == "dives"
    ]
    strict = _mission.validate_config(config, strict=True)
    assert any(i.level == "ERROR" and "missing" in i.message for i in strict)
