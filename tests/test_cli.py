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


def test_init_from_fills_source_and_serial(tmp_path: pathlib.Path) -> None:
    """Init --from fills source and the serial; model/maker/depth are left null to fill."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    data = yaml.safe_load(out.read_text())
    assert data["source"] == str(DATA_DIR.resolve())
    assert data["platform"]["PLATFORM_SERIAL_NUMBER"] == "sg005"
    # The UW-specific model/maker/depth are no longer baked in; they stay null.
    assert data["platform"]["PLATFORM_MODEL"] is None


def test_validate_errors_on_null_platform_fields_then_passes(
    tmp_path: pathlib.Path,
) -> None:
    """A template with null platform fields errors; filling them validates."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    assert cli.main(["validate", str(out)]) == 1  # model/maker/depth still null
    data = yaml.safe_load(out.read_text())
    data["platform"]["PLATFORM_MODEL"] = "Seaglider"
    data["platform"]["PLATFORM_MAKER"] = "University of Washington"
    data["platform"]["PLATFORM_DEPTH_RATING"] = 1000
    out.write_text(yaml.safe_dump(data))
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


def test_process_dry_run_ignores_existing_output(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-n previews and exits 0 even when the output exists (no act-phase check)."""
    from seagliderOG1 import convertOG1

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    out = tmp_path / "out"
    out.mkdir()
    (out / "sg005_delayed.nc").write_text("existing")
    config = _write_config(
        tmp_path / "mission.yaml", source=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "-n"]) == 0


def test_process_save_failure_counts_as_failed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save_dataset returning False is a mission failure (exit 1), not silent success."""
    from seagliderOG1 import convertOG1, writers

    monkeypatch.setattr(convertOG1, "convert_to_OG1", _simple_fake_convert)
    monkeypatch.setattr(writers, "save_dataset", lambda *_a, **_k: False)
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(DATA_DIR),
        output_dir=str(tmp_path / "out"),
    )
    assert cli.main(["process", str(config)]) == 1


def test_validate_source_override_rescues_missing_config_source(
    tmp_path: pathlib.Path,
) -> None:
    """A --source override is validated, rescuing a config whose own source is missing."""
    path = tmp_path / "mission.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "contributors": [{"name": "Jane", "role": "PI"}],
                "institutions": [{"name": "Inst", "role": "Operator"}],
            }
        )
    )
    assert any(i.key == "source" for i in _mission.validate_config(path))
    issues = _mission.validate_config(path, source_override=str(DATA_DIR))
    assert not any(i.key == "source" for i in issues)


# --- inspect / list --------------------------------------------------------


def test_inspect_variables(capsys: pytest.CaptureFixture[str]) -> None:
    """Inspect prints a variable table for a basestation file."""
    sample = DATA_DIR / "p0050001_20080606.nc"
    assert cli.main(["inspect", str(sample)]) == 0
    assert "dtype" in capsys.readouterr().out


def test_inspect_attrs() -> None:
    """Inspect --attrs prints the global attributes."""
    sample = DATA_DIR / "p0050001_20080606.nc"
    assert cli.main(["inspect", str(sample), "--attrs"]) == 0


def test_inspect_missing_file_is_exit_one(tmp_path: pathlib.Path) -> None:
    """Inspecting a non-existent file exits 1 (a failure, not a usage error)."""
    assert cli.main(["inspect", str(tmp_path / "nope.nc")]) == 1


def test_list_roles(capsys: pytest.CaptureFixture[str]) -> None:
    """List roles prints the W08 roles with their term URIs."""
    assert cli.main(["list", "roles"]) == 0
    out = capsys.readouterr().out
    assert "PI" in out and "W08/current/CONT0004/" in out


def test_list_institutions(capsys: pytest.CaptureFixture[str]) -> None:
    """List institutions prints the EDMO registry (code and standard name)."""
    assert cli.main(["list", "institutions"]) == 0
    out = capsys.readouterr().out
    assert "1434" in out and "University of Washington (School of Oceanography)" in out


def test_list_missions(capsys: pytest.CaptureFixture[str]) -> None:
    """List missions discovers the missions under a directory."""
    assert cli.main(["list", "missions", str(DATA_DIR)]) == 0
    assert "5 dives" in capsys.readouterr().out


def test_list_missions_requires_path() -> None:
    """List missions without a path is a usage error (exit 2)."""
    assert cli.main(["list", "missions"]) == 2


def test_list_rejects_unknown_registry() -> None:
    """An unknown registry name is a usage error (exit 2)."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["list", "nonsense"])
    assert exc.value.code == 2


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
