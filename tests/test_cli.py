"""Tests for the seagliderOG1 command-line interface (``init``, ``validate``)."""

import json
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

from seagliderOG1 import cli, mission
from seagliderOG1.cli import _mission

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_sg005"


def _write_config(path: pathlib.Path, **overrides: object) -> pathlib.Path:
    """Write a minimal valid mission config, applying overrides, and return its path.

    A ``deployment=`` override is split across the three global-attribute sections
    (config_version 3); a key with no section (e.g. ``program``) goes to
    ``global_attributes``, its interim home until the platform registry lands.
    """
    from seagliderOG1 import vocabularies

    config: dict[str, object] = {
        "config_version": 3,
        "raw_dir": str(DATA_DIR),
        "output_dir": "./",
        "contributors": [{"name": "Jane Doe", "role": "PI"}],
        "institutions": [{"name": "Your Institution", "role": "Operator"}],
    }
    deployment = overrides.pop("deployment", None)
    config.update(overrides)
    if deployment:
        placed = set()
        for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items():
            block = {k: v for k, v in deployment.items() if k in keys}
            if block:
                config[slug] = block
                placed.update(block)
        homeless = {k: v for k, v in deployment.items() if k not in placed}
        if homeless:
            extra = dict(config.get("global_attributes") or {})
            extra.update(homeless)
            config["global_attributes"] = extra
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


def test_cli_forces_noninteractive_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() pins a headless matplotlib backend so a figure render never blocks on a GUI."""
    monkeypatch.delenv("MPLBACKEND", raising=False)
    with pytest.raises(SystemExit):  # --version exits after main() sets the backend
        cli.main(["--version"])
    assert os.environ["MPLBACKEND"] == "Agg"


def test_cli_respects_an_explicit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend the user set themselves is left untouched (setdefault, not override)."""
    monkeypatch.setenv("MPLBACKEND", "pdf")
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert os.environ["MPLBACKEND"] == "pdf"


# --- init ------------------------------------------------------------------


def test_init_writes_template(tmp_path: pathlib.Path) -> None:
    """``init`` writes a parseable template with the expected keys."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", str(out)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(data) >= {"raw_dir", "contributors", "platform", "mode"}
    assert data["mode"] == "realtime"
    assert "naming_authority" in data["identity_and_discovery"]  # OG1 highly desirable


def test_init_refuses_overwrite_without_force(tmp_path: pathlib.Path) -> None:
    """``init`` refuses an existing file unless ``--force`` is given."""
    out = tmp_path / "mission.yaml"
    out.write_text("existing")
    assert cli.main(["init", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "existing"
    assert cli.main(["init", str(out), "--force"]) == 0
    assert out.read_text(encoding="utf-8") != "existing"


def test_init_from_fills_platform(tmp_path: pathlib.Path) -> None:
    """``init --raw-dir`` fills the platform block from the first basestation file."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", str(out), "--raw-dir", str(DATA_DIR)]) == 0
    platform = yaml.safe_load(out.read_text(encoding="utf-8"))["platform"]
    assert platform["PLATFORM_SERIAL_NUMBER"] == "sg005"
    assert str(platform["GLIDER_FIRMWARE_VERSION"]).startswith("seaglider")
    assert str(platform["LANDSTATION_VERSION"]).startswith("basestation")


def test_init_from_one_file_fills_platform_and_its_directory(
    tmp_path: pathlib.Path,
) -> None:
    """Init --raw-dir accepts one basestation file; raw_dir is that file's directory."""
    out = tmp_path / "mission.yaml"
    one = DATA_DIR / "p0050001_20080606.nc"
    assert cli.main(["init", str(out), "--raw-dir", str(one)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["raw_dir"] == str(DATA_DIR.resolve())
    assert data["platform"]["PLATFORM_SERIAL_NUMBER"] == "sg005"


def test_init_template_does_not_promise_an_id(tmp_path: pathlib.Path) -> None:
    """The id line says null means the derived id; init never fills it."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", str(out), "--raw-dir", str(DATA_DIR)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "proposes" not in text
    assert yaml.safe_load(text)["identity_and_discovery"]["id"] is None


def test_init_from_fills_raw_dir_and_serial(tmp_path: pathlib.Path) -> None:
    """Init --raw-dir fills raw_dir and the serial; model/maker/depth are left null to fill."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", str(out), "--raw-dir", str(DATA_DIR)]) == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["raw_dir"] == str(DATA_DIR.resolve())
    assert data["platform"]["PLATFORM_SERIAL_NUMBER"] == "sg005"
    # The UW-specific model/maker/depth are no longer baked in; they stay null.
    assert data["platform"]["PLATFORM_MODEL"] is None


def test_validate_errors_on_null_platform_fields_then_passes(
    tmp_path: pathlib.Path,
) -> None:
    """A template with null platform fields errors; filling them validates."""
    out = tmp_path / "mission.yaml"
    assert cli.main(["init", str(out), "--raw-dir", str(DATA_DIR)]) == 0
    assert cli.main(["validate", str(out)]) == 1  # model/maker/depth still null
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    data["platform"]["PLATFORM_MODEL"] = "Seaglider"
    data["platform"]["PLATFORM_MAKER"] = "University of Washington"
    data["platform"]["PLATFORM_DEPTH_RATING"] = 1000
    out.write_text(yaml.safe_dump(data))
    assert cli.main(["validate", str(out)]) == 0


def test_validate_rejects_unknown_global_section_key(tmp_path: pathlib.Path) -> None:
    """A typo'd key in a global-attribute section errors."""
    cfg = _write_config(
        tmp_path / "mission.yaml", identity_and_discovery={"nonsense": "y"}
    )
    assert cli.main(["validate", str(cfg)]) == 1


def test_validate_names_the_home_of_a_refused_global(tmp_path: pathlib.Path) -> None:
    """A deployment key or a derived global in global_attributes errors before conversion."""
    cfg = _write_config(
        tmp_path / "mission.yaml",
        global_attributes={
            "naming_authority": "de.uni-hamburg",
            "date_created": "x",
            "institution": "University of Hamburg",  # no other home: allowed
        },
    )
    issues = {
        i.key: i.message
        for i in mission.check(cfg)
        if (i.key or "").startswith("global_attributes")
    }
    assert set(issues) == {
        "global_attributes.naming_authority",
        "global_attributes.date_created",
    }
    assert (
        "identity_and_discovery:\n      naming_authority: de.uni-hamburg"
        in (issues["global_attributes.naming_authority"])
    )
    assert cli.main(["process", str(cfg)]) == 1  # refused by validate, nothing read


def test_validate_placeholder_in_global_attributes_is_unset_not_misplaced(
    tmp_path: pathlib.Path,
) -> None:
    """A placeholder ("null") under a sectioned key in global_attributes is unset, not an error.

    The converter drops placeholder values, so validate must not flag one as a misplaced key.
    """
    cfg = _write_config(tmp_path / "mission.yaml", global_attributes={"doi": "null"})
    issues = [
        i for i in mission.check(cfg) if (i.key or "").startswith("global_attributes")
    ]
    assert issues == []


def test_validate_errors_on_a_set_local_config(tmp_path: pathlib.Path) -> None:
    """local_config is reserved and unread; a non-null value is an ERROR (null is legal)."""
    cfg = _write_config(tmp_path / "mission.yaml", local_config="local/")
    bad = [i for i in mission.check(cfg) if i.key == "local_config"]
    assert bad and all(i.level == "ERROR" for i in bad)
    assert (
        cli.main(["validate", str(cfg)]) == 1
    )  # a dropped override makes a wrong file
    # null is legal, so the template's reserved key validates.
    ok = _write_config(tmp_path / "ok.yaml", local_config=None)
    assert [i for i in mission.check(ok) if i.key == "local_config"] == []


def test_validate_checks_the_sensors_block_shape(tmp_path: pathlib.Path) -> None:
    """sensors: fields must be serial_number / calibration_date and non-empty."""
    good = {"wlbb2f": {"serial_number": "1234", "calibration_date": "2008-02-01"}}
    assert not [
        i
        for i in mission.check(_write_config(tmp_path / "good.yaml", sensors=good))
        if (i.key or "").startswith("sensors")
    ]
    for bad in ({"wlbb2f": {"serial": "1"}}, {"wlbb2f": {"serial_number": None}}, [1]):
        issues = mission.check(_write_config(tmp_path / "bad.yaml", sensors=bad))
        assert any(
            i.level == "ERROR" and (i.key or "").startswith("sensors") for i in issues
        )


def test_validate_accepts_known_deployment_keys(tmp_path: pathlib.Path) -> None:
    """A deployment block with only OG1 identity globals validates."""
    cfg = _write_config(
        tmp_path / "mission.yaml",
        deployment={"program": "MOOSE", "license": "CC-BY-4.0"},
    )
    assert cli.main(["validate", str(cfg)]) == 0


def test_template_comments_name_the_destination() -> None:
    """Each generated line's comment says where the key goes (variable/attribute/global)."""
    template = _mission.render_template(raw_dir="/tmp/x")
    assert "UPPER keys become OG1 variables" in template
    assert "PLATFORM_MODEL: null   # required -> variable" in template
    assert (
        "platform_model_vocabulary: null   # optional -> attribute on PLATFORM_MODEL"
        in (template)
    )
    assert "id: null   # mandatory -> global attribute" in template


def test_case_hint_helper() -> None:
    """_case_hint returns a correctly-cased match only for a mis-cased key."""
    assert mission._case_hint("program", ["id", "program"]) is None  # exact: no hint
    assert mission._case_hint("Program", ["id", "program"]) == "program"
    assert mission._case_hint("xyz", ["id", "program"]) is None


def test_validate_case_hint_for_miscased_section_key() -> None:
    """A mis-cased key in a global-attribute section errors naming the exact spelling."""
    issues = mission._validate_global_sections({"rights_and_access": {"Doi": "X"}})
    assert any(
        i.level == "ERROR" and "'doi'" in i.message and "case-sensitive" in i.message
        for i in issues
    )


def test_validate_case_hint_for_miscased_platform_key() -> None:
    """A lower-cased platform variable name errors naming the UPPER spelling."""
    issues = mission._validate_platform({"platform_model": "Seaglider"})
    assert any(i.level == "ERROR" and "'PLATFORM_MODEL'" in i.message for i in issues)


def test_validate_warns_on_unset_highly_desirable_global() -> None:
    """A null highly-desirable section global is a WARNING, not an ERROR."""
    issues = mission._validate_highly_desirable(
        {"identity_and_discovery": {"site": None}}
    )
    assert any(i.key == "site" for i in issues)
    assert all(i.level == "WARNING" for i in issues)  # advisory only, never ERROR


# --- process ---------------------------------------------------------------


def test_process_v_flag_controls_library_logging(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``-v`` surfaces the library's INFO progress on stderr; without it, stderr stays quiet."""
    # One dive: the test is about logging, not about the mission's length.
    cfg = _write_config(tmp_path / "mission.yaml", dives=[1, 1])

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
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 1))
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
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 2))
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
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 2))
    per_dive = next(
        v for v in ds.data_vars if ds[v].attrs.get("storage_type") == "per_dive_scalar"
    )
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    assert cli.main(["inspect", str(nc), "--parameter", per_dive]) == 0
    out = capsys.readouterr().out
    assert "dive" in out and "value" in out
    assert cli.main(["inspect", str(nc), "--parameter", "TEMP"]) == 1


def test_report_writes_html_page(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """report writes a self-contained HTML conversion page beside the file."""
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 2))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    out = tmp_path / "og1_conversion.html"
    assert cli.main(["report", str(nc)]) == 0
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
    # Located by section id, so inserting or renumbering sections does not break it.
    for section in ("derived", "globals"):
        body = html.split(f'<section id="{section}">', 1)[1].split("</section>", 1)[0]
        assert "<table" in body, section
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


def test_report_output_dir_and_report_dir(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """report -o DIR writes into DIR; --report-dir ROOT into ROOT/<id>/; no overwrite."""
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 2))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    out_dir = tmp_path / "pages"
    assert cli.main(["report", str(nc), "-o", str(out_dir)]) == 0
    expected = out_dir / writers.conversion_path(nc, ".html").name
    assert expected.is_file()
    assert f"wrote {expected}" in capsys.readouterr().out
    assert cli.main(["report", str(nc), "-o", str(out_dir)]) == 1  # exists
    assert "use --force" in capsys.readouterr().err
    assert cli.main(["report", str(nc), "-o", str(out_dir), "--force"]) == 0
    assert cli.main(["report", str(nc), "--report-dir", str(tmp_path / "site")]) == 0
    assert (tmp_path / "site" / "og1" / "og1_conversion.html").is_file()


def test_inspect_output_points_at_report(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """inspect prints text only: -o/--title exit 2 and name the report verb."""
    from seagliderOG1 import _convert, readers, writers

    ds = _convert.convert(readers.read_mission(str(DATA_DIR), 1, 1))
    nc = tmp_path / "og1.nc"
    writers.write(ds, str(nc), overwrite=True)
    out = tmp_path / "x.html"
    assert cli.main(["inspect", str(nc), "--conversion", "-o", str(out)]) == 2
    assert "seagliderOG1 report" in capsys.readouterr().err
    assert not out.exists()  # nothing written
    assert cli.main(["inspect", str(nc), "--parameter", "C_VBD", "-o", str(out)]) == 2
    assert cli.main(["inspect", str(nc), "--title", "x"]) == 2
    assert not out.exists()


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
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config)]) == 0
    assert (out / "sg005_R.nc").is_file()  # no mode in the config: realtime


def test_process_dry_run_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-n prints the target path but writes no file."""
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "-n"]) == 0
    assert not out.exists()


def test_process_mode_realtime_sets_suffix(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--mode realtime names the output with the R data-mode suffix."""
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "--mode", "realtime"]) == 0
    assert (out / "sg005_R.nc").is_file()


def test_process_existing_output_refused_then_force_and_skip(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing output is refused by default, overwritten with --force, skipped with --skip-existing."""
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config)]) == 0
    assert cli.main(["process", str(config)]) == 1  # exists, refused
    assert cli.main(["process", str(config), "--skip-existing"]) == 0
    assert cli.main(["process", str(config), "--force"]) == 0


def test_process_root_all_converts_each(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root with --all converts every SN/DATE mission (distinct ids per mission)."""
    from seagliderOG1 import _convert

    counter = {"n": 0}

    def counting_fake(_datasets: object, **_kwargs: object) -> object:
        import xarray as xr

        counter["n"] += 1
        return xr.Dataset({"x": ("n", [1.0])}, attrs={"id": f"sg005_m{counter['n']}"})

    monkeypatch.setattr(_convert, "convert", counting_fake)
    root = _build_root(tmp_path / "root")
    out = tmp_path / "out"
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(root), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "--all"]) == 0
    assert len(list(out.glob("*.nc"))) == 2


def test_process_root_requires_selection(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root without --all/--mission is an error."""
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    root = _build_root(tmp_path / "root")
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(root), output_dir=str(tmp_path / "out")
    )
    assert cli.main(["process", str(config)]) == 1


def test_process_failing_mission_exits_one(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mission that raises is counted as failed and the run exits 1."""
    from seagliderOG1 import _convert

    def failing(_datasets: object, **_kwargs: object) -> tuple:
        msg = "boom"
        raise ValueError(msg)

    monkeypatch.setattr(_convert, "convert", failing)
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(DATA_DIR),
        output_dir=str(tmp_path / "out"),
    )
    assert cli.main(["process", str(config)]) == 1


def test_process_dry_run_ignores_existing_output(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-n previews and exits 0 even when the output exists (no act-phase check)."""
    from seagliderOG1 import _convert

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    out = tmp_path / "out"
    out.mkdir()
    (out / "sg005_delayed.nc").write_text("existing")
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(DATA_DIR), output_dir=str(out)
    )
    assert cli.main(["process", str(config), "-n"]) == 0


def test_process_report_writes_page_and_refuses_existing(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--report writes <id>_conversion.html; an existing page without --force fails."""
    out = tmp_path / "out"
    config = _write_config(tmp_path / "mission.yaml", output_dir=str(out), dives=[1, 1])
    assert cli.main(["process", str(config), "--report", "-n"]) == 0
    assert "_conversion.html" in capsys.readouterr().out
    assert not out.exists()

    assert cli.main(["process", str(config), "--report"]) == 0
    (nc,) = out.glob("*.nc")
    page = out / f"{nc.stem}_conversion.html"
    assert page.is_file()

    nc.unlink()
    assert cli.main(["process", str(config), "--report"]) == 1
    assert f"{page} exists" in capsys.readouterr().err
    assert cli.main(["process", str(config), "--report", "--force"]) == 0
    assert nc.is_file()


def test_validate_report_must_be_bool(tmp_path: pathlib.Path) -> None:
    """The report: key is known and must be a boolean."""
    good = _write_config(tmp_path / "good.yaml", report=True)
    assert not [i for i in mission.check(good) if i.level == "ERROR"]
    bad = _write_config(tmp_path / "bad.yaml", report="yes")
    assert any(i.key == "report" for i in mission.check(bad))


def test_process_prints_presence_line_when_dives_disagree(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real sg005 conversion prints one presence line pointing at the report verb."""
    config = _write_config(tmp_path / "mission.yaml", output_dir=str(tmp_path / "out"))
    assert cli.main(["process", str(config)]) == 0
    out = capsys.readouterr().out
    assert "on every dive, 5 on some (3 patterns) — see seagliderOG1 report" in out


def test_process_save_failure_counts_as_failed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write failure (it raises) is a mission failure (exit 1), not silent success."""
    from seagliderOG1 import _convert, writers

    def _raise(*_a: object, **_k: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(_convert, "convert", _simple_fake_convert)
    monkeypatch.setattr(writers, "write", _raise)
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(DATA_DIR),
        output_dir=str(tmp_path / "out"),
    )
    assert cli.main(["process", str(config)]) == 1


def test_validate_raw_dir_override_rescues_missing_config_raw_dir(
    tmp_path: pathlib.Path,
) -> None:
    """A --raw-dir override is validated, rescuing a config whose raw_dir is missing."""
    path = tmp_path / "mission.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "contributors": [{"name": "Jane", "role": "PI"}],
                "institutions": [{"name": "Inst", "role": "Operator"}],
            }
        )
    )
    assert any(i.key == "raw_dir" for i in mission.check(path))
    issues = mission.check(path, raw_dir_override=str(DATA_DIR))
    assert not any(i.key == "raw_dir" for i in issues)


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
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["Mission", "Dives", "First", "Last", "Path"]
    assert "1 mission under" in out


def test_list_missions_requires_path() -> None:
    """List missions without a path is a usage error (exit 2)."""
    assert cli.main(["list", "missions"]) == 2


def test_list_rejects_unknown_registry() -> None:
    """An unknown registry name is a usage error (exit 2)."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["list", "nonsense"])
    assert exc.value.code == 2


def test_list_without_registry_names_them(capsys: pytest.CaptureFixture[str]) -> None:
    """Bare ``list`` names every registry and exits 0."""
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    for name in (
        "roles",
        "institutions",
        "missions",
        "globals",
        "platform",
        "variables",
    ):
        assert f"  {name} " in out


def test_list_globals_matches_required_globals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``list globals`` has a row for every tiered global and every section key."""
    from seagliderOG1 import vocabularies

    assert cli.main(["list", "globals"]) == 0
    rows = {
        line.split()[0]: line.split()
        for line in capsys.readouterr().out.splitlines()[2:]
        if line.strip()
    }
    for names in vocabularies.REQUIRED_GLOBALS.values():
        for name in names:
            assert name in rows
    home = {
        key: slug
        for slug, keys in vocabularies.CONFIG_GLOBAL_SECTIONS.items()
        for key in keys
    }
    for name, slug in home.items():
        assert rows[name][-1] == slug


def test_global_rows_set_in() -> None:
    """Each user-set global names the mission.yaml block it is set in."""
    rows = {row["name"]: row for row in mission.global_rows()}
    assert rows["site"]["set_in"] == "identity_and_discovery"
    assert rows["id"]["set_in"] == "identity_and_discovery"  # derived, overridable
    assert rows["internal_mission_identifier"]["set_in"] == "global_attributes"
    assert rows["contributor_id"]["set_in"] == "contributors"
    assert rows["contributing_institutions_vocabulary"]["set_in"] == "institutions"
    assert rows["title"]["set_in"] == ""  # package constant
    assert rows["license"]["tier"] == "optional"  # ACDD, no OG1 tier


def test_list_platform_matches_platform_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``list platform`` lists every platform field plus the two vocabulary attributes."""
    from seagliderOG1 import vocabularies

    assert cli.main(["list", "platform"]) == 0
    out = capsys.readouterr().out
    for key in vocabularies.PLATFORM_FIELDS:
        assert f"{key} " in out
    assert "attribute on PLATFORM_MAKER" in out
    assert "seaglider_software_version" in out  # the From file column


def test_list_variables_shows_sources(capsys: pytest.CaptureFixture[str]) -> None:
    """``list variables`` lists each attribute entry with the basestation names mapping to it."""
    from seagliderOG1 import vocabularies

    assert cli.main(["list", "variables"]) == 0
    out = capsys.readouterr().out
    temp = next(line for line in out.splitlines() if line.startswith("TEMP "))
    assert "degree_Celsius" in temp and "temperature" in temp
    assert f"{len(vocabularies.vocab_attrs)} variables" in out
    assert "sbe41" not in out  # a sensor key, not a variable source


def test_list_one_variable_and_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    """``list variables NAME`` prints the entry; an unknown name exits 1 with suggestions."""
    assert cli.main(["list", "variables", "TEMP"]) == 0
    out = capsys.readouterr().out
    assert "sea_water_temperature" in out and "Basestation names: temperature" in out
    assert cli.main(["list", "variables", "TMEP"]) == 1
    assert "TEMP" in capsys.readouterr().err


def test_list_sensors(capsys: pytest.CaptureFixture[str]) -> None:
    """``list sensors`` lists the L22 catalogue with each entry's L22 code."""
    from seagliderOG1 import vocabularies

    assert cli.main(["list", "sensors"]) == 0
    out = capsys.readouterr().out
    assert "TOOL1254" in out
    assert f"{len(vocabularies.sensor_vocabs)} sensors" in out


def test_list_search_filters_rows(capsys: pytest.CaptureFixture[str]) -> None:
    """``--search`` keeps only rows containing the text in any column."""
    assert cli.main(["list", "institutions", "--search", "washington"]) == 0
    body = [line for line in capsys.readouterr().out.splitlines()[2:] if line.strip()]
    rows = body[:-1]  # last line is the summary
    assert rows and all("washington" in line.lower() for line in rows)


def test_list_rejects_argument_where_none_is_taken() -> None:
    """A PATH|NAME given to a registry that takes none is a usage error (exit 2)."""
    assert cli.main(["list", "roles", "extra"]) == 2


# --- validate --------------------------------------------------------------


def test_validate_accepts_valid_config(tmp_path: pathlib.Path) -> None:
    """A minimal valid config validates with exit 0."""
    config = _write_config(tmp_path / "mission.yaml")
    assert cli.main(["validate", str(config)]) == 0


def test_validate_role_and_roles_together_is_error(tmp_path: pathlib.Path) -> None:
    """Setting both role: and roles: on one entry is an ERROR (not a silent drop)."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        contributors=[{"name": "Ann", "role": "PI", "roles": ["Operator"]}],
    )
    issues = mission.check(config)
    assert any(
        i.level == "ERROR" and "both role: and roles:" in i.message for i in issues
    )


def test_validate_rejects_unknown_key(tmp_path: pathlib.Path) -> None:
    """An unknown top-level key is an ERROR (pure schema check, no real data)."""
    config = _write_config(tmp_path / "mission.yaml", raw_dir=str(tmp_path), nonsense=1)
    assert cli.main(["validate", str(config)]) == 1
    issues = mission.check(config)
    assert any(i.level == "ERROR" and i.key == "nonsense" for i in issues)


def test_validate_rejects_bad_types(tmp_path: pathlib.Path) -> None:
    """mode, dives and keep_variables type errors surface without real data."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        mode="sideways",
        dives="all",
        keep_variables="TEMP",
    )
    bad = {i.key for i in mission.check(config) if i.level == "ERROR"}
    assert {"mode", "dives", "keep_variables"} <= bad


def test_validate_rejects_non_w08_role(tmp_path: pathlib.Path) -> None:
    """A role outside the W08 vocabulary is an ERROR."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        contributors=[{"name": "Ann", "role": "Chief Wrangler"}],
    )
    assert any(i.level == "ERROR" and "W08" in i.message for i in mission.check(config))


def test_validate_rejects_name_with_comma(tmp_path: pathlib.Path) -> None:
    """A contributor name containing a comma is an ERROR."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        contributors=[{"name": "Doe, Jane", "role": "PI"}],
    )
    assert any(
        i.level == "ERROR" and "comma" in i.message for i in mission.check(config)
    )


def test_validate_requires_pi_and_operator(tmp_path: pathlib.Path) -> None:
    """Missing a PI contributor and an Operator institution are both ERRORs."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        contributors=[{"name": "Ann", "role": "Data scientist"}],
        institutions=[{"name": "Inst", "role": "Owner"}],
    )
    errors = [i.message for i in mission.check(config) if i.level == "ERROR"]
    assert any("PI" in message for message in errors)
    assert any("Operator" in message for message in errors)


def test_validate_warns_on_roles_list(tmp_path: pathlib.Path) -> None:
    """A single-element roles: is a warning (prefer role:), not an error."""
    config = _write_config(
        tmp_path / "mission.yaml",
        raw_dir=str(tmp_path),
        contributors=[{"name": "Ann", "roles": ["PI"]}],
    )
    issues = mission.check(config)
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
    issues = mission.check(config)
    assert any(i.level == "ERROR" and i.key == "dives" for i in issues)


def test_validate_strict_flags_gap(tmp_path: pathlib.Path) -> None:
    """``--strict`` reports a dive missing from the range."""
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    for name in ("p0050001_20080606.nc", "p0050003_20080606.nc"):
        (mission_dir / name).write_bytes((DATA_DIR / name).read_bytes())
    config = _write_config(
        tmp_path / "mission.yaml", raw_dir=str(mission_dir), dives=[1, 3]
    )
    assert not [i for i in mission.check(config, strict=False) if i.key == "dives"]
    strict = mission.check(config, strict=True)
    assert any(i.level == "ERROR" and "missing" in i.message for i in strict)


def test_bundled_example_config_validates_and_plans(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed data/demo_sg005/mission.yaml validates and plans, so it cannot rot."""
    example = DATA_DIR / "mission.yaml"
    assert cli.main(["validate", str(example)]) == 0
    assert cli.main(["process", str(example), "-n"]) == 0
    out = capsys.readouterr().out
    assert "1 would convert" in out
    assert "outputs" in out


def test_report_output_dir_is_created(tmp_path: pathlib.Path) -> None:
    """report -o new/ (not yet existing) writes <id>_conversion.html inside it."""
    from seagliderOG1 import _convert, readers, writers

    nc = tmp_path / "og1.nc"
    writers.write(_convert.convert(readers.read_mission(str(DATA_DIR), 1, 1)), str(nc))
    out_dir = tmp_path / "reports"
    assert cli.main(["report", str(nc), "-o", f"{out_dir}/"]) == 0
    assert (out_dir / "og1_conversion.html").is_file()


def test_deprecated_source_key_is_read_as_raw_dir_with_a_warning(
    tmp_path: pathlib.Path,
) -> None:
    """A config that still says source: validates with a WARNING; both keys is an ERROR."""
    config = _write_config(tmp_path / "old.yaml")
    data = yaml.safe_load(config.read_text())
    data["source"] = data.pop("raw_dir")
    config.write_text(yaml.safe_dump(data))
    issues = mission.check(config)
    assert [i.level for i in issues if i.key == "source"] == ["WARNING"]
    assert not [i for i in issues if i.level == "ERROR"]
    assert mission._load_raw(config)["raw_dir"] == str(DATA_DIR)
    data["raw_dir"] = str(DATA_DIR)
    config.write_text(yaml.safe_dump(data))
    assert any(
        i.level == "ERROR" and "both 'raw_dir'" in i.message
        for i in mission.check(config)
    )


def test_init_dest_is_a_directory_or_a_yaml_file(tmp_path: pathlib.Path) -> None:
    """init dest: a directory gets mission.yaml inside (created); a .yaml path is used."""
    assert cli.main(["init", str(tmp_path / "new" / "dir")]) == 0
    assert (tmp_path / "new" / "dir" / "mission.yaml").is_file()
    assert cli.main(["init", str(tmp_path / "sg271.yaml")]) == 0
    assert (tmp_path / "sg271.yaml").is_file()


def test_process_report_dir_writes_pages_apart_from_the_data(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """process --report-dir ROOT writes the page in ROOT/<id>/, nothing beside the data."""
    out = tmp_path / "data"
    site = tmp_path / "site"
    config = _write_config(tmp_path / "mission.yaml", output_dir=str(out), dives=[1, 1])
    assert cli.main(["process", str(config), "--report-dir", str(site)]) == 0
    (nc,) = out.glob("*.nc")
    assert (site / nc.stem / f"{nc.stem}_conversion.html").is_file()
    assert not list(out.glob("*.html"))
    assert (
        out / f"{nc.stem}_conversion.json"
    ).is_file()  # the sidecar stays with the data


def test_enrich_sets_the_doi_and_rebinds_the_sidecar(
    tmp_path: pathlib.Path,
    sg005_og1_copy: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """enrich --doi edits the globals in place, keeps date_created, rebinds the sidecar."""
    import json

    import numpy as np
    import xarray as xr

    from seagliderOG1 import writers
    from seagliderOG1.reports import _record

    nc = sg005_og1_copy
    with xr.open_dataset(nc, engine="netcdf4", decode_timedelta=False) as ds:
        before = dict(ds.attrs)
        temp_before = ds["TEMP"].values.copy()
    assert cli.main(["enrich", str(nc)]) == 2  # nothing to set
    assert cli.main(["enrich", str(nc), "--doi", "10.5281/zenodo.1"]) == 0
    with xr.open_dataset(nc, engine="netcdf4", decode_timedelta=False) as ds:
        after = dict(ds.attrs)
        np.testing.assert_array_equal(ds["TEMP"].values, temp_before)
    assert after["doi"] == "10.5281/zenodo.1"
    assert after["date_created"] == before["date_created"]
    assert after["tracking_id"] != before["tracking_id"]
    assert "enrich set doi" in after["history"].splitlines()[-1]
    assert "doi" in json.loads(after["conversion_attribute_sources"])["enriched"]
    sidecar = json.loads(writers.conversion_path(nc, ".json").read_text())
    assert sidecar["tracking_id"] == after["tracking_id"]
    assert sidecar["sha256"] == writers.file_sha256(nc)
    assert _record.conversion_sidecar(nc)["presence"]  # still bound, no warning


def test_enrich_from_config_refuses_converter_owned_keys(
    tmp_path: pathlib.Path,
    sg005_og1_copy: pathlib.Path,
) -> None:
    """enrich FILE CONFIG applies deployment:; a derived key in global_attributes fails."""
    import xarray as xr

    nc = sg005_og1_copy
    good = _write_config(tmp_path / "good.yaml", deployment={"program": "MOOSE"})
    assert cli.main(["enrich", str(nc), str(good)]) == 0
    with xr.open_dataset(nc, engine="netcdf4", decode_timedelta=False) as ds:
        assert ds.attrs["program"] == "MOOSE"
    bad = _write_config(
        tmp_path / "bad.yaml", global_attributes={"date_created": "20000101T000000"}
    )
    assert cli.main(["enrich", str(nc), str(bad)]) == 1
    listed = _write_config(
        tmp_path / "listed.yaml", global_attributes={"keywords": ["a", "b"]}
    )
    assert cli.main(["enrich", str(nc), str(listed)]) == 1  # refused, no traceback
    for key in ("date_modified", "tracking_id", "history", "conversion_dimensions"):
        owned = _write_config(tmp_path / "owned.yaml", global_attributes={key: "x"})
        assert cli.main(["enrich", str(nc), str(owned)]) == 1, key


def test_draft_writes_only_draft_files_and_a_draft_page(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """draft: four files, every name ends _draft*; the netCDF says it is not OG1."""
    import xarray as xr

    out = tmp_path / "drafts"
    raw = tmp_path / "raw"
    raw.mkdir()
    for name in ("p0050001_20080606.nc", "p0050002_20080606.nc"):
        (raw / name).symlink_to(DATA_DIR / name)
    assert cli.main(["draft", "--raw-dir", str(raw), "-o", str(out)]) == 0
    written = sorted(path.name for path in out.iterdir())
    stem = written[0].removesuffix(".nc")
    assert stem.endswith("_draft")
    assert written == sorted(
        [
            f"{stem}.nc",
            f"{stem}_conversion.html",
            f"{stem}_conversion.json",
            f"{stem}_mission.yaml",
        ]
    )
    with xr.open_dataset(out / f"{stem}.nc", engine="netcdf4") as ds:
        assert ds.attrs["id"] == stem
        assert "not an OG1 file" in ds.attrs["draft"]
        assert "OG-1.0" not in ds.attrs["Conventions"]
        assert "CF-1.10" in ds.attrs["Conventions"]
    html = (out / f"{stem}_conversion.html").read_text(encoding="utf-8")
    assert '<span class="masthead-type">draft</span>' in html
    assert "this is not an OG1 file" in html
    assert "9. Basestation global attributes" in html
    assert "What an OG1 file would hold" in html
    assert "Suggested mission.yaml lines" in html
    assert "dives: [1, 2]" in html and 'class="copy"' in html
    assert "mission.yaml against the data" not in html  # a draft has no config
    sidecar = json.loads((out / f"{stem}_conversion.json").read_text(encoding="utf-8"))
    assert "config" not in sidecar
    proposal = (out / f"{stem}_mission.yaml").read_text(encoding="utf-8")
    assert stem.removesuffix("_draft") in proposal.splitlines()[1]
    data = yaml.safe_load(proposal)
    assert data["dives"] == [1, 2]
    assert data["raw_dir"] == str(raw.resolve())
    assert data["identity_and_discovery"]["id"] is None  # stays derived
    assert cli.main(["draft", "--raw-dir", str(raw), "-o", str(out)]) == 1  # exists
    # The proposal is checked before anything is written, even with the .nc gone: the
    # user is told to edit it in place. --force replaces it.
    (out / f"{stem}.nc").unlink()
    (out / f"{stem}_conversion.html").unlink()
    (out / f"{stem}_conversion.json").unlink()
    (out / f"{stem}_mission.yaml").write_text("edited\n", encoding="utf-8")
    assert cli.main(["draft", "--raw-dir", str(raw), "-o", str(out)]) == 1
    assert f"{stem}_mission.yaml exists" in capsys.readouterr().err
    assert not (out / f"{stem}.nc").exists()  # refused before writing
    argv = ["draft", "--raw-dir", str(raw), "-o", str(out), "--force"]
    assert cli.main(argv) == 0
    assert "edited" not in (out / f"{stem}_mission.yaml").read_text(encoding="utf-8")
    # A proposal that cannot be written is one error line and exit 1, not a traceback.
    (out / f"{stem}_mission.yaml").unlink()
    (out / f"{stem}_mission.yaml").mkdir()
    assert cli.main(argv) == 1
    assert "could not write" in capsys.readouterr().err
