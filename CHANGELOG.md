# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic versioning.

## [Unreleased]

### Breaking changes

- Public API reshaped to the OceanGliders family convention (0.1.0), a clean break with no
  deprecation shims. Old → new:

  | was | now |
  |---|---|
  | `ds, varlist = convert_to_OG1(ds_or_list)` | `ds = convert.to_og1(sequence_of_datasets)` — returns the Dataset; takes a sequence (wrap a single dataset as `[ds]`) |
  | `from seagliderOG1 import convertOG1` → `convertOG1.convert_to_OG1(...)` | `from seagliderOG1 import convert` → `convert.to_og1(...)` — module `convertOG1.py` renamed to `convert.py`; function `convert_to_OG1` to `to_og1`, addressed as `convert.to_og1()` |
  | `writers.save_dataset(ds, output_file="../test.nc") -> bool` | `writers.write(ds, path, *, overwrite=False) -> pathlib.Path` — renamed; `path: str \| Path`, no default; returns the path written; raises `FileExistsError` (or the underlying write error) instead of returning `False` |
  | `plotters.plot_*(…)` returned `None` and called `plt.show()` | `plotters.plot_*(…, ax=None) -> (fig, ax)`; no `plt.show()` |
  | `plotters.show_*(path_or_dataset)` | `plotters.show_*(dataset)` — Dataset only (the file-path branch is gone) |
  | `readers.load_sample_dataset()` | `readers.load_sample_basestation()` |
  | `standardise_OG10`, `tools.OG1_name_mapping`, `print_OG1_mapping_summary`, the `OG1_mapping` argument | `standardise_og1`, `og1_name_mapping`, `print_og1_mapping_summary`, `og1_mapping` — `og1` lower-case in names; the package name keeps its spelling |
  | `tools.<pipeline internals>` (`og1_name_mapping`, `gather_sensor_info`, `add_sensor_to_dataset`, `merge_datasets_along_time`, `extract_scalar_parameters`/`add_scalar_parameters`, `set_best_dtype`, …) and the whole `seagliderOG1.utilities` module | private `seagliderOG1._pipeline` (not part of the public API); `tools` keeps the user-facing utilities (`add_depth`, `add_phase`, `convert_units_var`, `convert_qc_flags`, `encode_times_og1`, …) |
  | `firstrun=` parameters (e.g. `tools.convert_units_var(..., firstrun=...)`) | removed; progress and diagnostics go through `logging.getLogger("seagliderOG1...")` (set the level, e.g. the CLI `-v`) |
  | `readers.load_basestation_files(dir, first, last, repair=)` | `readers.read_mission(path, first=None, last=None, *, repair=False)` |
  | `readers.load_first_basestation_file` | `readers.read_file` |
  | `readers.scan_and_repair_files` | `readers.repair_files` |
  | `readers.profnum_from_filename` / `readers.glider_sn_from_filename` | `readers.profile_number_from_filename` / `readers.serial_from_filename` |
  | `readers.repair_netcdf_time_metadata_inplace` | `readers.repair_time_metadata` |
  | `convert.apply_keep_variables(ds, keep)` | `convert.keep_variables(ds, names)` |
  | `tools.calc_Z` / `tools.assign_phase` / `tools.assign_profile_number` | `tools.add_depth` / `tools.add_phase` / `tools.add_profile_number` |
  | `contributors.registry_institutions()` | `contributors.institution_registry()` |
  | `vocabularies.load_default_contributors`, `vocabularies.contrib_to_append`, `config/OG1_author.yaml` | removed — contributors come from `mission.yaml`; no packaged default-identity block |
  | `contributors.normalize_orcid` / `contributors.normalize_role` | `contributors.canonical_orcid` / `contributors.canonical_role` — public names carry no British/American-variant word |
  | `TEMP`/`TEMP_RAW`/`TEMP_OXYGEN` output `units: Celsius` | `units: degree_Celsius` — CF spelling (udunits-equivalent; values unchanged) |

- Output variable dtypes changed. QC flags are `int8` (were `float32`/`int64`); `PHASE` is
  `int8`; `PROFILE_NUMBER`, `DIVE_NUMBER` and `VBD_MIN_CNTS` are `int16`; `DEPTH` and
  `DEPTH_Z` are `float32`. `LATITUDE`/`LONGITUDE` stay `float64`. Non-QC integer variables
  carry a `_FillValue`; QC flags use `6` (unsampled) and have no `_FillValue`. A reader that
  assumes the old dtypes, or tests `np.isnan` on a QC flag, must adapt; CF-decoding readers
  are unaffected.
- Time variables are written with the OG1-specified units `seconds since
  1970-01-01T00:00:00Z` (ISO UTC; xarray serialises the zone as `+00:00`) and calendar
  `gregorian` (OG1 Format v1.0.0), replacing the previous non-conformant `seconds since
  1970-01-01 00:00:00` / `standard`. The instant is unchanged; a parser that string-matched
  the old units must adapt.
- Minimum Python raised to 3.11 (`requires-python = ">=3.11"`). The pinned `numpy 2.2` and
  `xarray 2025.3` already require a recent Python, so the former `>=3.8` was not installable;
  users on earlier Python must stay on an earlier release.
- Platform metadata is no longer silently defaulted. `convert.to_og1` takes `platform=` and
  `global_attributes=` from the mission config, config values overriding file-derived ones. A
  missing `PLATFORM_SERIAL_NUMBER` (no file `platform_id`, none in the config) now raises instead
  of defaulting to `sg000` — it names the output file and OG1 id. `WMO_IDENTIFIER`,
  `PLATFORM_MODEL`, `PLATFORM_MAKER`, `GLIDER_FIRMWARE_VERSION` and `LANDSTATION_VERSION` are
  written as `"UNK"` with a warning when absent, not `0000000` or the hard-coded M1 model.
  `PLATFORM_DEPTH_RATING` (numeric) is omitted when absent rather than written as a string.
  `PLATFORM_MAKER`, `PLATFORM_DEPTH_RATING`, `GLIDER_FIRMWARE_VERSION` and `LANDSTATION_VERSION`
  are new output variables. The hard-coded `platform_model_vocabulary` is dropped and written
  only when the config supplies it. A `global_attributes` key colliding with a converter-derived
  global (`id`, `time_coverage_*`, `geospatial_*`, `date_created`) raises.

- Contributor and institution attributes are rebuilt as OG1 positional, comma-aligned lists
  (`contributor_name`/`_email`/`_id`/`_role`/`_role_vocabulary`, and `contributing_institutions`
  with its `_role`/`_vocabulary`/`_role_vocabulary`): one slot per person/institution, empty
  slots kept so the lists stay aligned, one role per slot. Roles normalise to the NERC W08
  vocabulary. `convert.to_og1` takes `contributors=` and `institutions=` as lists of records;
  the former `contrib_to_append` dict is removed (passing a dict raises `TypeError`). Two silent
  substitutions are removed: a missing contributor role is no longer defaulted to `PI`, and an
  unrecognised institution is no longer stamped with the School of Oceanography EDMO code
  (`…/report/1434`) — institutions resolve to their own EDMO id via
  `config/institution_registry.yaml`, or are written with no id and a warning.

- Mission configuration is `config_version: 2` (adds the `deployment:` block and the optional
  platform variables below). A `config_version: 1` file still converts; `init` writes version 2.
- A missing OG1-mandatory global attribute is no longer written as a placeholder. The old
  `attr_mandatory` fill table (which wrote the literal `null`, and `contributer_email:
  null@null.com` into a misspelt key) is removed; a null or empty attribute is simply not
  written, and `convert.to_og1` raises `seagliderOG1.exceptions.MetadataError` if a mandatory
  global is absent after all metadata sources are merged. A mission config that relied on the
  fabricated `null@null.com` contributor email must set a real `contributor_email`.
- `global_attributes` may no longer set a key that has a structured home in the new `deployment:`
  block (`id`, `program`, `license`, `doi`, ...); move it under `deployment:`. `id` is no longer
  rejected as a converter-derived collision — it is derived by default but may be set in
  `deployment:` (overriding the derived value with a warning).
- Output global `featureType` is `trajectory` (was `trajectoryProfile`) and `Conventions` is
  `CF-1.10, ACDD-1.3, OG-1.0` (was `CF-1.10,OG-1.0`), matching the OG1 manual's fixed value and
  example files. A reader that string-matched the old values must adapt.

### Added

- `seagliderOG1.contributors` module and `config/institution_registry.yaml` (EDMO codes) backing
  the contributor/institution rebuild above.
- `seagliderOG1` command-line interface (`cli/` package), run as `seagliderOG1 <verb>`:
  - `init` — write a commented `mission.yaml`; `--from DIR` fills the platform block and
    `source` from the first basestation file.
  - `validate` — check keys, types, `source` and the dive range; roles against the W08
    vocabulary; require a PI contributor and an Operator institution; `--strict`.
  - `process` — convert a mission directory, or every `SN/DATE` mission under a root
    (`--all`/`--mission GLOB`), writing `<output_dir>/<id>.nc`; `--mode`, `--dives`, `-o`,
    `--force`/`--skip-existing`, `-n`; per-mission summary and exit 1 on any failure.
  - `inspect FILE` — the file's variables or attributes as a text table (`--attrs`,
    `--variables`, `--by-dimension DIM`); the HTML inventory page arrives with the planned
    `seagliderOG1[report]` extra.
  - `list {roles|institutions|missions}` — the W08 roles, the EDMO institution registry, or
    the missions discovered under a directory.
  Exit codes follow the CLI family convention: `0` success, `1` a conversion or validation
  failure or a missing/unreadable input path, `2` an argparse-level usage error (an unknown
  flag, a bad `choices` value, or `list missions` with no path).
  A global `-v`/`--verbose` flag routes library diagnostics to stderr (`-v` INFO progress,
  `-vv` debug); command results stay on stdout.
  `convert.to_og1` gains `contributors=`, `institutions=`, `platform=`, `global_attributes=`
  and `mode=`. `OG1_author.yaml` is no longer loaded at import (`load_default_contributors`
  loads it on demand); `readers.discover_missions` and public `readers.validate_filename`/
  `profnum_from_filename`/`glider_sn_from_filename`.
- `convert.name_mapping(datasets)` returns the basestation→OG1 variable-mapping table — the
  data the old `convert_to_OG1` returned as its second tuple element, now an explicit function.
- `deployment:` block in `mission.yaml` and `convert.to_og1(deployment=...)`: the OG1
  deployment-identity globals (`id`, `program`, `program_vocabulary`, `network`, `site`,
  `site_vocabulary`, `project`, `comment`, `license`, `acknowledgment`, `doi`, `data_url`), one
  key per global, written when set and skipped when null. `init` writes the block with each
  key's requirement tier as a comment.
- Optional platform variables in the `platform:` block, written only when set:
  `PLATFORM_NAME`, `TELECOM_TYPE`, `TRACKING_SYSTEM`, `BATTERY_TYPE`, `BATTERY_PACK` (each with
  its OG1 long_name and, where defined, its controlled-vocabulary attribute), and
  `platform_maker_vocabulary` on `PLATFORM_MAKER` (mirroring `platform_model_vocabulary`).
- `required:` block in `config/OG1_global_attributes.yaml`: the OG1 global-attribute requirement
  tiers (mandatory / highly desirable / suggested) transcribed from the OG1 manual (v1.0.0),
  with the source URL and verification date in the file header; read as
  `vocabularies.REQUIRED_GLOBALS`. `validate` reports an unknown `deployment:` key.
- `seagliderOG1.exceptions` module with `MetadataError` (raised by `convert.to_og1`).
- `writers.write` now writes every non-scalar numeric variable, coordinates
  included, with lossless zlib compression (level 4) and the shuffle filter. String
  and scalar variables are left uncompressed. Output files are smaller and remain
  readable by any netCDF4 client.
- `tests/test_writers.py` (9 tests, 100% coverage of `writers.py`): compression applied,
  lossless round-trip, string/scalar variables skipped, time encoding preserved, size
  reduction, retry path, caller's dataset not mutated, integer `_FillValue` preserved,
  and the failure return.

- Per-dive scalar parameters change representation (#117). A value that is constant for a whole
  dive but differs between dives (for example the flight-model constants `C_VBD`, `HD_A`/`HD_B`/
  `HD_C`) has no valid home in OG1, which permits no dimension other than `N_MEASUREMENTS`.
  Rather than broadcast it across every measurement — which wastes space and implies a
  per-measurement variation that does not exist — such a parameter is written as a single scalar
  variable holding a JSON string: a `{"dives": [...], "values": [...]}` object with aligned lists
  and `null` for a missing dive, tagged `serialization: json` and `storage_type: per_dive_scalar`.
  The numeric range attributes (`_FillValue`, `valid_min`/`valid_max`, `scale_factor`/`add_offset`)
  are dropped; units and source metadata describe the decoded values. Scalars constant across all
  dives (for example `MASS`, `VOLMAX`) are still written as ordinary scalar values. This replaces
  the previous handling, which expanded these parameters onto `N_MEASUREMENTS` as numeric arrays;
  code that read them numerically must now decode the JSON.

### Changed

- Packaged config files renamed to whole words (no API change; they are package data):
  `OG1_var_names.yaml` → `OG1_variable_names.yaml`, `OG1_vocab_attrs.yaml` →
  `OG1_variable_attributes.yaml`, `OG1_sensor_attrs.yaml` → `OG1_sensor_attributes.yaml`,
  `OG1_global_attrs.yaml` → `OG1_global_attributes.yaml`. The `vocabularies` module tables
  likewise: `dims_rename_dict` → `DIMENSION_RENAMES`, `vars_to_remove` → `VARIABLES_TO_DROP`,
  `vars_as_is` → `VARIABLES_AS_IS`, `order_of_attr` → `ATTRIBUTE_ORDER`.
- Conversion retains basestation variables that were previously dropped (#117). Every scalar
  variable is carried through with `tools.extract_scalar_parameters` / `add_scalar_parameters`,
  replacing the earlier hydrodynamic-model-only extraction (`extract_hdm_parameters`); the
  per-dive representation of varying scalars is described under Breaking changes above. Non-scalar
  variables are merged onto a shared `time` axis by `tools.merge_datasets_along_time`, keeping
  their source identity in the `original_name` and `original_dimension` attributes.
  `tools.OG1_name_mapping` returns the per-dimension time variables separately; the
  `sg_data_point` time source is the basestation `time` clock, never the science-controller
  `ctd_time`.
- Dependencies are declared in `pyproject.toml` (`pip install -e ".[dev]"`); `requirements*.txt`
  and `environment.yml` are removed; `scipy`, `cartopy` and `pooch` are dropped as unused; the
  ruff configuration is aligned with the family set and `ruff format` replaces `black`;
  pre-commit is removed; CI gains a coverage gate.

### Fixed

- `start_date`, `TRAJECTORY` and the output `id` are seeded from the earliest measurement time
  (the time-sorted concatenation), not from whichever dataset was first in the input sequence, so
  they agree with `time_coverage_start` regardless of input order.
- A null or wholly-empty global attribute is never written (not as an empty string, not as the
  word `null`); a multi-value string with an empty slot (e.g. a role-less first contributor's
  `", PI"`) is kept. This removes the previous `""`-with-warning behaviour and the
  `contributing_institutions_role: ""` that a role-less institution produced.
- `date_created` is now always the conversion time (ACDD: the creation date of this OG1 file),
  was copied from the basestation file when present and `""` otherwise. A basestation creation
  date, when carried through in a later release, will go to `history`, not `date_created`.
- Output global attribute `featureType` is now `trajectory` (was `trajectoryProfile`), the fixed
  value the OG1 manual gives and the value the manual's own example files carry; and `Conventions`
  is `CF-1.10, ACDD-1.3, OG-1.0` (was `CF-1.10,OG-1.0`), declaring the ACDD discovery attributes
  the output already writes and spacing the list as the manual shows it
  (`config/OG1_global_attributes.yaml`).
- Trailing/leading whitespace stripped from vocabulary `long_name` strings (`TEMP*`, `ICES_CODE`,
  the WET Labs sensors) that were written verbatim into output attributes; a test guards against
  edge whitespace in the vocabulary YAMLs.
- `writers.write` preserves each compressed variable's `_FillValue` (and
  `scale_factor`/`add_offset`) when applying compression, so an integer missing-value
  sentinel is not written as an ordinary value.
- `writers.write` no longer mutates the caller's dataset: it copies the input
  before clearing conflicting time attributes and stringifying attributes.
- `writers.write` reuses one encoding on the retry path, so a file written after
  a `TypeError` fallback keeps its time encoding and compression instead of being
  written unencoded.
- Dtype optimisation now runs once on the concatenated dataset (in `convert.to_og1`) instead
  of per dive, so `int8` QC flags are no longer re-promoted to `float32` by the concat.
- `tools.set_best_dtype` now visits coordinates (so `DEPTH` becomes `float32`) and restores
  coordinate status after coercion; it respects an existing `_FillValue` sentinel (e.g.
  `PROFILE_NUMBER`'s `-9999`) instead of overriding it, never leaves `_FillValue` in attrs,
  skips QC flags, and coerces scalar variables without an indexing error.
- `tools.find_best_dtype` no longer casts variables whose name ends in `raw` to `int16` (it
  truncated float "raw" variables); named integer variables map to a fixed integer type.
- `tools.convert_qc_flags` drops the inherited float `_FillValue` from the `int8` result;
  `tools.assign_profile_number` writes `_FillValue` to encoding rather than attrs.
- `writers.write` no longer silently overrides `tools.encode_times_og1`: both use one
  canonical time-units constant (`tools.OG1_TIME_UNITS` / `OG1_TIME_CALENDAR`), so the saved
  file's TIME units match the OG1 encoder instead of a divergent hard-coded string.
