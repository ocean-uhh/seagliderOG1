# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic versioning. Each entry is one line: what changed and what to do about it. The full
old → new API table and output-format detail for the 0.1.0 break are in the migration guide
(*Migrating to 0.1.0* in the docs; `docs/source/migrating_0_1_0.rst`).

## [Unreleased]

### Breaking changes

- Public API reshaped to the OceanGliders family convention — modules, functions and arguments
  renamed (`convert.to_og1`, `writers.write`, `readers.read_mission`, …). See the migration guide
  for the full old → new table.
- Output variable dtypes changed: QC flags `int8` (`6` for unsampled, no `_FillValue`), `PHASE`
  `int8`, `PROFILE_NUMBER`/`DIVE_NUMBER`/`VBD_MIN_CNTS` `int16`, `DEPTH`/`DEPTH_Z` `float32`. A
  reader that assumes the old dtypes or tests `np.isnan` on a QC flag must adapt.
- Time units are `seconds since 1970-01-01T00:00:00Z` / `gregorian` (was `… 00:00:00` /
  `standard`); the instant is unchanged. TEMP units are `degree_Celsius` (was `Celsius`).
- Output `featureType` is `trajectory` (was `trajectoryProfile`); `Conventions` is
  `CF-1.10, ACDD-1.3, OG-1.0` (was `CF-1.10,OG-1.0`).
- Minimum Python raised to 3.11.
- Platform, contributor and institution metadata come from `mission.yaml`, not package defaults: a
  missing `PLATFORM_SERIAL_NUMBER` raises (was `sg000`); other platform fields are `"UNK"` with a
  warning (was `0000000` / a hard-coded model); no `PI` role default; no default EDMO code.
- A missing OG1-mandatory global is no longer written as a placeholder (`null` / `null@null.com`);
  `convert.to_og1` raises `MetadataError`. A config that relied on the fabricated email must set a
  real `contributor_email`.
- `mission.yaml` is `config_version: 2` (a v1 file still converts). `global_attributes` may not set
  a key with a structured home in the new `deployment:` block; `id` is config-overridable there.
- Per-dive-varying scalars are written as a JSON-string scalar variable instead of broadcast onto
  `N_MEASUREMENTS` (#117); decode the JSON to read them.

### Added

- `seagliderOG1` CLI: `init`, `validate`, `process`, `inspect`, `list`; `-v`/`-vv` for diagnostics.
- `seagliderOG1.contributors` module and `config/institution_registry.yaml` (EDMO codes).
- `convert.to_og1` gains `contributors=`, `institutions=`, `platform=`, `deployment=`,
  `global_attributes=`, `mode=`; `convert.name_mapping(datasets)` returns the variable-mapping table.
- `deployment:` block in `mission.yaml` (OG1 identity globals) with `config_version: 2`.
- Optional platform variables: `PLATFORM_NAME`, `TELECOM_TYPE`, `TRACKING_SYSTEM`, `BATTERY_TYPE`,
  `BATTERY_PACK`, `platform_maker_vocabulary`.
- `required:` tier block in `config/OG1_global_attributes.yaml` → `vocabularies.REQUIRED_GLOBALS`.
- `seagliderOG1.exceptions.MetadataError`.
- `conversion_attribute_sources` global: JSON provenance of each written global (names only).
- Conversion ledger: per-variable `original_name` on every variable, and the `conversion_dimensions`,
  `conversion_derived_variables` and `conversion_dropped_variables` globals record each dimension's
  fate, the converter-created variables, and any `keep_variables` drops; `inspect --conversion`
  prints them from the file.
- Scalar parameters carry `storage_type` (`constant_scalar` or `per_dive_scalar`); `inspect
  --conversion` lists them in a Scalar parameters section and `inspect --parameter NAME` decodes a
  per-dive JSON scalar to a dive/value table.
- Template lines name each key's destination (variable / attribute / global); `validate` gives a
  case hint on a mis-cased key.
- `writers.write` applies lossless zlib compression to numeric variables.
- `convert.process_mission(source, output_dir, ...)`: one mission read → convert → write, the
  library form of `process`; the CLI calls it per mission.
- `process --report` (and `report:` in `mission.yaml`) writes the HTML conversion page
  `<id>_conversion.html` beside each file.
- `data/demo_sg005/mission.yaml`: a filled-in example configuration for the bundled sample (writes
  to the gitignored `outputs/`); the demo notebook runs it through `convert.process_mission`.

### Changed

- Packaged config files and `vocabularies` tables renamed to whole words (package data, no API
  change): `OG1_variable_names.yaml`, `OG1_variable_attributes.yaml`, `OG1_sensor_attributes.yaml`,
  `OG1_global_attributes.yaml`; `DIMENSION_RENAMES`, `VARIABLES_TO_DROP`, `VARIABLES_AS_IS`,
  `ATTRIBUTE_ORDER`.
- Conversion retains basestation variables previously dropped, merged onto a shared time axis with
  `original_name`/`original_dimension` provenance (#117).
- Basestation `comment` is no longer renamed to `history`; `history` is a single conversion
  provenance line (the basestation per-dive processing log is not carried).
- Coverage gate floor raised from 75 to 82 (`main` is at 83%).
- Dependencies in `pyproject.toml` only (`requirements*.txt`/`environment.yml` removed); ruff-family
  config, `ruff format` replaces `black`, CI coverage gate.

### Fixed

- `start_date`, `TRAJECTORY` and `id` are seeded from the earliest measurement time, so they agree
  with `time_coverage_start` regardless of input order.
- A null or wholly-empty global is never written; `date_created` is always the conversion time.
- Scalar parameters no longer carry an empty `original_dimension`; the attribute is omitted when
  there is no source dimension.
- Whitespace stripped from vocabulary `long_name` strings written into output attributes.
- `writers.write` preserves `_FillValue`/`scale_factor`/`add_offset`, does not mutate the caller's
  dataset, and reuses one encoding on the retry path.
- Dtype optimisation runs once post-concat (QC flags stay `int8`); `set_best_dtype` visits
  coordinates and respects an existing `_FillValue`; `find_best_dtype` no longer truncates `*raw`
  floats; the writer and `encode_times_og1` share one canonical time-units constant.
