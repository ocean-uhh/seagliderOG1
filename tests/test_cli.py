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
