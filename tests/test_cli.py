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
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(data) >= {"source", "contributors", "platform", "mode"}
    assert data["mode"] == "delayed"


def test_init_refuses_overwrite_without_force(tmp_path: pathlib.Path) -> None:
    """``init`` refuses an existing file unless ``--force`` is given."""
    out = tmp_path / "mission.yaml"
    out.write_text("existing")
    assert cli.main(["init", "-o", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "existing"
    assert cli.main(["init", "-o", str(out), "--force"]) == 0
    assert out.read_text(encoding="utf-8") != "existing"


def test_init_from_fills_platform(tmp_path: pathlib.Path) -> None:
    """``init --from`` fills the platform block from the first basestation file."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    platform = yaml.safe_load(out.read_text(encoding="utf-8"))["platform"]
    assert platform["PLATFORM_SERIAL_NUMBER"] == "sg005"
    assert str(platform["GLIDER_FIRMWARE_VERSION"]).startswith("seaglider")
    assert str(platform["LANDSTATION_VERSION"]).startswith("basestation")


def test_init_from_fills_source_and_serial(tmp_path: pathlib.Path) -> None:
    """Init --from fills source and the serial; model/maker/depth are left null to fill."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", "--from", str(DATA_DIR), "-o", str(out)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
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
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    data["platform"]["PLATFORM_MODEL"] = "Seaglider"
    data["platform"]["PLATFORM_MAKER"] = "University of Washington"
    data["platform"]["PLATFORM_DEPTH_RATING"] = 1000
    out.write_text(yaml.safe_dump(data))
    assert cli.main(["validate", str(out)]) == 0


def test_validate_rejects_unknown_deployment_key(tmp_path: pathlib.Path) -> None:
    """A typo'd deployment key errors; known keys validate."""
    cfg = _write_config(
        tmp_path / "mission.yaml", deployment={"program": "X", "nonsense": "y"}
    )
    assert cli.main(["validate", str(cfg)]) == 1


def test_validate_accepts_known_deployment_keys(tmp_path: pathlib.Path) -> None:
    """A deployment block with only OG1 identity globals validates."""
    cfg = _write_config(
        tmp_path / "mission.yaml",
        deployment={"program": "MOOSE", "license": "CC-BY-4.0"},
    )
    assert cli.main(["validate", str(cfg)]) == 0


def test_template_comments_name_the_destination() -> None:
    """Each generated line's comment says where the key goes (variable/attribute/global)."""
    template = _mission.render_template(source="/tmp/x")
    assert "UPPER keys become OG1 variables" in template
    assert "PLATFORM_MODEL: null   # required -> variable" in template
    assert (
        "platform_model_vocabulary: null   # optional -> attribute on PLATFORM_MODEL"
        in (template)
    )
    assert "id: null   # mandatory -> global attribute" in template


def test_case_hint_helper() -> None:
    """_case_hint returns a correctly-cased match only for a mis-cased key."""
    assert _mission._case_hint("program", ["id", "program"]) is None  # exact: no hint
    assert _mission._case_hint("Program", ["id", "program"]) == "program"
    assert _mission._case_hint("xyz", ["id", "program"]) is None


def test_validate_case_hint_for_miscased_deployment_key() -> None:
    """A mis-cased deployment key errors naming the exact spelling."""
    issues = _mission._validate_deployment({"Program": "X"})
    assert any(
        i.level == "ERROR"
        and "'program'" in i.message
        and "case-sensitive" in i.message
        for i in issues
    )


def test_validate_case_hint_for_miscased_platform_key() -> None:
    """A lower-cased platform variable name errors naming the UPPER spelling."""
    issues = _mission._validate_platform({"platform_model": "Seaglider"})
    assert any(i.level == "ERROR" and "'PLATFORM_MODEL'" in i.message for i in issues)


def test_validate_warns_on_unset_highly_desirable_global() -> None:
    """A null highly-desirable deployment global is a WARNING, not an ERROR."""
    issues = _mission._validate_highly_desirable({"deployment": {"program": None}})
    assert any(i.key == "program" for i in issues)
    assert all(i.level == "WARNING" for i in issues)  # advisory only, never ERROR


# --- process ---------------------------------------------------------------


def test_process_v_flag_controls_library_logging(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-v`` surfaces the library's INFO progress on stderr; without it, stderr stays quiet."""
    cfg = _write_config(tmp_path / "mission.yaml")

    assert cli.main(["process", str(cfg), "-o", str(tmp_path / "quiet")]) == 0
    assert "Start converting" not in capsys.readouterr().err

    assert cli.main(["-v", "process", str(cfg), "-o", str(tmp_path / "loud")]) == 0
    assert "Start converting" in capsys.readouterr().err

    # -v is accepted after the verb too, not only before it.
    assert cli.main(["process", str(cfg), "-o", str(tmp_path / "loud2"), "-v"]) == 0
    assert "Start converting" in capsys.readouterr().err


def test_inspect_conversion_shows_ledger(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """inspect --conversion prints the ledger sections read from the OG1 file."""
    from seagliderOG1 import convert, readers, writers

    ds = convert.to_og1(readers.read_mission(str(DATA_DIR), 1, 1))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    assert cli.main(["inspect", str(nc), "--conversion"]) == 0
    out = capsys.readouterr().out
    assert "Dimensions" in out
    assert "backbone" in out and "gps_info" in out
    assert "Global attributes by source" in out
    assert "History" in out


def test_inspect_conversion_rejects_pre_ledger_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A basestation file has no ledger, so --conversion is a plain error (exit 1)."""
    raw = sorted(DATA_DIR.glob("p*.nc"))[0]
    assert cli.main(["inspect", str(raw), "--conversion"]) == 1
    assert "conversion_dimensions" in capsys.readouterr().err


def test_inspect_conversion_lists_scalar_parameters(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--conversion has a Scalar parameters section naming the per-dive JSON storage."""
    from seagliderOG1 import convert, readers, writers

    ds = convert.to_og1(readers.read_mission(str(DATA_DIR), 1, 2))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    assert cli.main(["inspect", str(nc), "--conversion"]) == 0
    out = capsys.readouterr().out
    assert "Scalar parameters" in out
    assert "per-dive JSON" in out
    # Constants are summarised as a count, not listed, unless --all is given.
    assert "constant scalars (storage_type: constant_scalar)" in out
    assert cli.main(["inspect", str(nc), "--conversion", "--all"]) == 0
    assert "constant scalars (storage_type" not in capsys.readouterr().out


def test_inspect_parameter_conflicts_with_conversion() -> None:
    """--parameter and --conversion are mutually exclusive (argparse usage error)."""
    with pytest.raises(SystemExit):
        cli.main(["inspect", "any.nc", "--conversion", "--parameter", "x"])


def test_inspect_parameter_decodes_per_dive_scalar(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--parameter decodes one per-dive JSON scalar; a non-per-dive variable is an error."""
    from seagliderOG1 import convert, readers, writers

    ds = convert.to_og1(readers.read_mission(str(DATA_DIR), 1, 2))
    per_dive = next(
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "per_dive_scalar"
    )
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    assert cli.main(["inspect", str(nc), "--parameter", per_dive]) == 0
    out = capsys.readouterr().out
    assert "dive" in out and "value" in out
    assert cli.main(["inspect", str(nc), "--parameter", "TEMP"]) == 1


def test_inspect_conversion_writes_html_page(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """inspect --conversion -o writes a self-contained HTML conversion page."""
    from seagliderOG1 import convert, readers, writers

    ds = convert.to_og1(readers.read_mission(str(DATA_DIR), 1, 2))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    out = tmp_path / "conversion.html"
    assert cli.main(["inspect", str(nc), "--conversion", "-o", str(out)]) == 0
    assert f"wrote {out}" in capsys.readouterr().out
    html = out.read_text(encoding="utf-8")
    assert "Reconciliation" in html
    assert "Variables on" in html  # grouped by original dimension
    assert "Valid %" in html  # the merge diagnostic column
    assert "<table" in html
    # The six fates account for every basestation variable (demo_sg005 dives 1-2: 342).
    assert "sum to the 342 basestation input variables" in html
    # The transient derived-sources stamp is internal and never reaches the page.
    assert "_derived_sources" not in html
    # Item #2 sections render as tables, not the earlier interim text block.
    assert "5. Derived variables" in html
    assert "7. Global attributes" in html
    assert "<h3>History</h3>" in html
    assert "(scalar)" in html  # the Dimensions scalar row
    assert "Interim text view" not in html
    assert "data:image/png;base64," in html  # the section-1 fate histogram
    # Masthead (S18) and the renamed calibration group (S15).
    assert 'class="meta-grid"' in html
    assert "<code>sg_calib_constants</code>" in html
    # Spatiotemporal coverage computed column (S17) and the OG1-requirement line (S25).
    assert "Computed" in html
    assert "OG1 requirement: mandatory 9/9 present" in html
    # Masthead polish (S19): meta-grid pairs are div-wrapped, and the jump-nav sits after the
    # masthead closes (not a descendant of it).
    assert "<div><dt>" in html
    assert '</div>\n<nav class="jump-nav"' in html
    # The per-heading "↑ top" link script is emitted (S24); it appends .top-link client-side.
    assert "top-link" in html and "↑ top" in html
    # Vendored features adopted at the sync-4 re-vendor: numbered rows and the OG1-requirement
    # column on the globals table.
    assert ">#<" in html
    assert "Requirement" in html


def test_inspect_output_without_conversion_errors(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-o`` without ``--conversion`` fails (exit 2): the HTML page is the conversion page's."""
    from seagliderOG1 import convert, readers, writers

    ds = convert.to_og1(readers.read_mission(str(DATA_DIR), 1, 1))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    out = tmp_path / "x.html"
    assert cli.main(["inspect", str(nc), "-o", str(out)]) == 2
    assert "pass --conversion" in capsys.readouterr().err
    assert not out.exists()  # nothing written


def _simple_fake_convert(_datasets: object, **kwargs: object) -> object:
    """Stand in for to_og1: no real conversion, deterministic id from mode."""
    import xarray as xr

    suffix = "R" if kwargs.get("mode") == "realtime" else "delayed"
    return xr.Dataset({"x": ("n", [1.0, 2.0])}, attrs={"id": f"sg005_{suffix}"})


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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
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
    from seagliderOG1 import convert

    counter = {"n": 0}

    def counting_fake(_datasets: object, **_kwargs: object) -> object:
        import xarray as xr

        counter["n"] += 1
        return xr.Dataset({"x": ("n", [1.0])}, attrs={"id": f"sg005_m{counter['n']}"})

    monkeypatch.setattr(convert, "to_og1", counting_fake)
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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
    root = _build_root(tmp_path / "root")
    config = _write_config(
        tmp_path / "mission.yaml", source=str(root), output_dir=str(tmp_path / "out")
    )
    assert cli.main(["process", str(config)]) == 1


def test_process_failing_mission_exits_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mission that raises is counted as failed and the run exits 1."""
    from seagliderOG1 import convert

    def failing(_datasets: object, **_kwargs: object) -> tuple:
        msg = "boom"
        raise ValueError(msg)

    monkeypatch.setattr(convert, "to_og1", failing)
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
    from seagliderOG1 import convert

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
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
    """A write failure (it raises) is a mission failure (exit 1), not silent success."""
    from seagliderOG1 import convert, writers

    def _raise(*_a: object, **_k: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(convert, "to_og1", _simple_fake_convert)
    monkeypatch.setattr(writers, "write", _raise)
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


def test_validate_role_and_roles_together_is_error(tmp_path: pathlib.Path) -> None:
    """Setting both role: and roles: on one entry is an ERROR (not a silent drop)."""
    config = _write_config(
        tmp_path / "mission.yaml",
        source=str(tmp_path),
        contributors=[{"name": "Ann", "role": "PI", "roles": ["Operator"]}],
    )
    issues = _mission.validate_config(config)
    assert any(
        i.level == "ERROR" and "both role: and roles:" in i.message for i in issues
    )


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


def test_validate_missing_file_is_exit_one(tmp_path: pathlib.Path) -> None:
    """Validating a non-existent config exits 1 (an input failure, not a usage error)."""
    assert cli.main(["validate", str(tmp_path / "nope.yaml")]) == 1


def test_process_missing_config_is_exit_one(tmp_path: pathlib.Path) -> None:
    """Processing a non-existent config exits 1 (an input failure, not a usage error)."""
    assert cli.main(["process", str(tmp_path / "nope.yaml")]) == 1


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
