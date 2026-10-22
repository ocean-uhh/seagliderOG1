# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic versioning. Each entry is one line: what changed and what to do about it. The full
old → new API table and output-format detail for the 0.1.0 break are in the migration guide
(*Migrating to 0.1.0* in the docs; `docs/source/migrating_0_1_0.rst`).

## [Unreleased]

### Breaking changes

- The public API is a config-first set of verbs on the top-level package: `read`, `convert`,
  `write`, `report`, `enrich`, `process`, `process_missions`, plus `mission.load` / `mission.check`.
  `process("mission.yaml")` loads a configuration and runs read + convert + write (+ report) for
  one mission, so a Python user no longer hand-merges the three global-attribute sections or
  passes a dozen keyword arguments. `to_og1` is renamed `convert` and takes a `mission=` path or
  mapping; `enrich` moved to the package (and `writers`) and takes `mission=`; the batch primitive
  `process_mission` is now internal. The conversion module `convert.py` is renamed `_convert.py`,
  the mission-config schema moved to a new `seagliderOG1.mission`, and the conversion-record
  readers are no longer a public API. See the migration guide.
- `mission.yaml` groups the user-set global attributes into three sections named for the
  conversion page's convention groups — `identity_and_discovery:`, `rights_and_access:`,
  `provenance_and_processing:` — replacing the single `deployment:` block, so the keys you fill
  name the page group they land in. `config_version` is now `3`; `validate` rejects an older
  version (and a stray `deployment:` block), naming the sections, and `seagliderOG1 init`
  regenerates a file. `program`, `program_vocabulary` and `network` leave the sections for the
  forthcoming local-config overlay (set them under `global_attributes:` until it lands); a
  `local_config:` key is reserved (must be `null` — `validate` errors on a non-null value,
  since a dropped override would make a wrong file; no `config_version` bump when the feature
  lands). `convert` / `enrich` keep their single `deployment=` mapping argument.
- The data mode defaults to `realtime` (id and file name suffix `R`) when neither the config
  nor `process --mode` sets it; it was `delayed`. `convert` defaults to `mode="realtime"`,
  and `init` writes `mode: realtime`. Set `mode: delayed` for a delayed-mode file.
- The basestation `naming_authority` (`edu.washington.apl`), `uuid` (one dive file's, written as
  `uri`), `summary` (written as `site`) and `file_version` are no longer carried into the OG1
  file: they describe the basestation files, not the OG1 dataset. `naming_authority` is an
  `identity_and_discovery:` key (written by `init`).
- When the config lists `institutions`, the basestation `institution` global (free text, a postal
  address on sg005) is no longer written as a role-less contributing institution beside them;
  the conversion page offers its registry match as an `institutions:` entry instead. Without
  config institutions it is kept as before.
- The basestation sensor-string variables keep their names (`sbe41`, `sbe43`, `wlbb2f`); they
  were written as `SeaBird SBE 41 CTD`, `Seabird SBE43F`, `Wetlabs BB2FL-VMT` (names with
  spaces). The sensor-key map moved from `OG1_variable_names.yaml` to `OG1_sensor_names.yaml`
  (`vocabularies.sensor_names`).
- `writers.write` refuses an attribute netCDF cannot store (a dict, a bool) with a `TypeError`
  naming it, before anything is written; it used to convert such attributes to text and retry.
- CLI flags in the family shape: `init [dest]` (a directory gets `mission.yaml`, a `.yaml` path is
  that file) replaces `init -o FILE`; `--raw-dir` replaces `init --from` and `process --source`;
  the `mission.yaml` key is `raw_dir` (`source:` is read with a deprecation warning for one
  release; both set is an error). `inspect` prints text only: the HTML page is `seagliderOG1
  report` (`inspect -o` / `--title` exit 2 and say so).
- The conversion record binds to its file by `id` + `tracking_id` (was `id` + `date_created`; an
  older conversion record is still read) and records the file's SHA-256.
- Raw WET Labs counts are no longer written as `BBP700` / `BBP470` (they were labelled m-1); they
  keep their basestation names (`eng_wlbb2f_redCount`, `eng_wlbb2f_blueCount`) with `units: counts`.
  A volume scattering function (`*_bb700`, m-1 sr-1) is no longer written as `BBP700` either.
- A second or later basestation variable mapping to the same OG1 name is numbered with an
  underscore (`DEPTH_2`, was `DEPTH2`); the first keeps the plain name.
- `log_VBD_MIN` is no longer mapped to `VBD_MIN_CNTS` (which `sg_cal_vbd_min_cnts` holds); it is
  written under its basestation name (was `VBD_MIN_CNTS2`).
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
- `global_attributes` may not set a key with a structured home in one of the three global-attribute
  sections (`validate` and the converter refuse it, naming the section); `id` is overridable under
  `identity_and_discovery:`.
- Per-dive-varying scalars are written as a JSON-string scalar variable instead of broadcast onto
  `N_MEASUREMENTS` (#117); decode the JSON to read them.

### Added

- A bundled sg271 sample mission (three dives, Drygalski Trough, PycnMix) ships inside the package:
  `readers.load_sample_basestation()` returns it, `readers.sample_mission_dir()` gives its path, and
  `seagliderOG1 init --example` writes its config pointing at the packaged dives so the demo runs from
  a `pip install`. The `init` template lists the OG1 `tracking_system` and `battery_type` vocabularies.
- A `deployment_information:` block in `mission.yaml` (`DEPLOYMENT_TIME`, `DEPLOYMENT_LATITUDE`,
  `DEPLOYMENT_LONGITUDE`) sets the OG1 deployment variables from the cruise log instead of deriving
  them from the first in-water fix; a `DEPLOYMENT_TIME` after the first data sample warns.
- The v0.0.2 names are importable for one release and warn: a renamed name (e.g.
  `readers.load_basestation_files`, `convertOG1.convert_to_OG1`, `writers.save_dataset`)
  delegates to its 0.1.0 spelling and emits a `SeagliderDeprecationWarning` naming it; a removed
  name (e.g. `convertOG1.process_and_save_data`, `vocabularies.load_default_contributors`) raises
  with a message pointing at the migration guide. All of it is removed in 0.3.0. See *Migrating
  to 0.1.0*.
- `sensors:` in `mission.yaml` (`to_og1(sensors=...)`): correct a basestation sensor record's
  `serial_number` and `calibration_date` by its sensor key; the corrected serial names the
  `SENSOR_*` variable, and its `comment` records the replaced value.
- Conversion page: a *Sensors named by OG1* table (type, maker, model, serial, calibration date,
  the variables using each sensor; amber for a placeholder or shared serial); suggestions for a
  `identity_and_discovery.id` from a conversion starting at dive 1, and for registry entries close to an
  unmatched institution name. `creator_*` / `publisher_*` are no longer suggested (OG1 uses
  `contributor_*`). The missing-globals box also lists the OG1 highly-desirable globals
  `validate` warns about, each labelled with its tier.
- `validate` reports a `global_attributes` key that belongs in a global-attribute section (naming the
  section and the lines to write) or that the converter computes, before any file is read; `process` used to
  refuse it only after loading the mission.
- Conversion page: *mission.yaml against the data*, copyable `mission.yaml` lines where the
  requested `dives` or a config platform field (serial, firmware, basestation version, WMO id)
  differs from the basestation files, where platform fields were written as `UNK` or omitted,
  where the EDMO registry resolved an institution id the config left null, and for missing ACDD
  globals (under a global-attribute section or `global_attributes:`). The conversion record records the `dives`,
  `platform` and `institutions` values `process_mission` was given.
- Three ACDD globals derived from the data: `geospatial_bounds` (lat/lon bounding box as a WKT
  polygon, latitude first), `geospatial_vertical_positive` (`down` or `up`, from the sign of mean
  DEPTH), and `time_coverage_duration`
  (end − start as an ISO 8601 duration). Recorded as `derived` in `conversion_attribute_sources`.
- `CONTRIBUTING.md`: licensing of contributions, credit and authorship, and scope.
- `seagliderOG1 draft --raw-dir DIR`: convert with no config to see what the basestation files
  hold — `<id>_draft.nc` (a `draft` global, no `OG-1.0` in `Conventions`), a draft conversion
  page with the basestation's own global attributes, the conversion record, and a proposed
  `<id>_draft_mission.yaml`. `convert.process_mission(draft=True)`.
- `seagliderOG1 report FILE.nc [-o DIR | --report-dir ROOT]` writes the conversion page;
  `process --report-dir ROOT` writes it to `ROOT/<id>/`, apart from the data.
- `seagliderOG1 enrich FILE.nc [CONFIG] [--doi DOI]` / `convert.enrich`: set globals (e.g. a DOI)
  on a written file in place; sets `date_modified`, appends `history`, renews `tracking_id`,
  keeps `date_created`, rebinds the conversion record.
- A `tracking_id` global (UUID, new on every write); `writers.file_sha256`, `writers.write_sidecar`.
- Conversion page: a conventions box under the global attributes — what `Conventions` claims, ACDD
  1.3 highly recommended / recommended present (lists from the IOOS compliance-checker 6.1.0), and
  dimensioned floating-point variables without `units`.
- `seagliderOG1` CLI: `init`, `validate`, `process`, `inspect`, `list`; `-v`/`-vv` for diagnostics.
- `seagliderOG1.contributors` module and `config/institution_registry.yaml` (EDMO codes).
- `convert.to_og1` gains `contributors=`, `institutions=`, `platform=`, `deployment=`,
  `global_attributes=`, `mode=`; `convert.name_mapping(datasets)` returns the variable-mapping table.
- Three global-attribute sections in `mission.yaml` — `identity_and_discovery:`, `rights_and_access:`,
  `provenance_and_processing:` — with `config_version: 3`.
- Optional platform variables: `PLATFORM_NAME`, `TELECOM_TYPE`, `TRACKING_SYSTEM`, `BATTERY_TYPE`,
  `BATTERY_PACK`, `platform_maker_vocabulary`.
- `required:` tier block in `config/OG1_global_attributes.yaml` → `vocabularies.REQUIRED_GLOBALS`.
- `seagliderOG1.exceptions.MetadataError`.
- `conversion_attribute_sources` global: JSON provenance of each written global (names only).
- Conversion record: per-variable `original_name` on every variable, and the `conversion_dimensions`,
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
- `seagliderOG1 list globals | platform | variables [NAME] | sensors`: the OG1 globals with
  tier and `mission.yaml` home, the `platform:` keys, the OG1 variables with their attributes
  and basestation sources, and the sensor catalogue, read from the converter's own tables.
- `process --report` (and `report:` in `mission.yaml`) writes the HTML conversion page
  `<id>_conversion.html` beside each file.
- `process` writes `<id>_conversion.json` beside each OG1 file: the input files and the dives
  each basestation variable is present and valid in. The conversion page shows it as a *Presence
  across dives* section; `process` prints a one-line summary when the dives disagree.
  `convert.presence_by_dive`, `presence_patterns`, `presence_summary`, `conversion_sidecar`.
- `data/demo_sg005/mission.yaml`: a filled-in example configuration for the bundled sample (writes
  to the gitignored `outputs/`); the demo notebook runs it through `convert.process_mission`.
- Conversion page "The OG1 file" section: the output read by what OG1 requires and names rather
  than by basestation origin — Required by OG1 (present/absent + where each came from), Named by
  OG1, a Candidate-for-OG1 tier the project curates, Carried-through families, and a "same
  quantity, more than once" comparison. `vocabularies.OG1_REQUIRED_VARS` (the upstream checker's
  list) and `vocabularies.OG1_CANDIDATE_VARS` (the project's uplift list) back it.

### Changed

- The readers (`read_mission`, `read_file`, `list_files`, `discover_missions`,
  `repair_files`) accept a `pathlib.Path` as well as a string.
- `vocabularies.VARIABLES_TO_DROP` is empty: the 24 basestation variables it removed (e.g. `density`,
  `theta`, `dissolved_oxygen_sat`, the `*_gsm` flight-model set) are now in the output. `depth` and
  `eng_depth` map to `DEPTH`, which `ctd_depth` holds, and are written as `DEPTH_2` / `DEPTH_3`.
- Conversion page reordered for a first read: a Before → after summary and the Reconciliation
  with a Meaning column first, scalar parameters last and collapsed; Presence and Dimensions
  gain percentage and Samples in columns, and each Variables group states the Valid % baseline
  its dimension sets. `<id>_conversion.json` input records gain each file's dimension lengths
  and global-attribute count (additive; an older conversion record still renders).
- `seagliderOG1 list` prints each registry as an aligned table with a header and a one-line
  summary; bare `seagliderOG1 list` names the registries; `--search TEXT` filters rows.
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

- Conversion page: the presence-strips colorbar sits in its own column; it overlapped the strips
  (and warned "Axes that are not compatible with tight_layout").
- The `init` template no longer says `provenance_and_processing.comment` overrides a comment "derived
  from the file's history": none is derived; it overrides a `comment` global the basestation files carry.
- `data/demo_sg005/mission.yaml` names its Operator `University of Washington School of
  Oceanography`, a registry variant, so it carries the EDMO id; as `University of Washington` it
  matched no registry entry.
- The EDMO registry resolves `University of Hamburg` to EDMO 3323 (the current university) rather
  than 1156 (the dissolved Institute of Oceanography); the institute names remain as aliases.
- Conversion page: `contributing_institutions_role` and `_role_vocabulary` are grouped under
  People & institutions (were under Other).
- `date_created` is the conversion time; the basestation files' own `date_created` (sg005:
  2014-03-11) was written instead, because `OG1_global_attributes.yaml` kept it as-is.
- `date_modified` (and so `date_created`) is UTC; it was the converting machine's local time.
- `LATITUDE_GPS`, `LONGITUDE_GPS` and `TIME_GPS` carry `original_dimension: gps_info`;
  `TIME_GPS` keeps its vocabulary `long_name` (all attributes were removed).
- `PHASE`, `PROFILE_NUMBER` and `DIVE_NUMBER` take their attributes from the vocabulary
  (`PHASE` and `PROFILE_NUMBER` had none);
  `PHASE_QC`'s `long_name` was `" quality flag"`.
- Conversion is about 2.5 times faster (sg005, 5 dives: 7.5 s → 2.9 s), output unchanged:
  splitting a dive by dimension, the dtype pass and the scalar parameters rebuilt a dataset once
  per variable.
- The fate figure on the conversion page writes `->`, avoiding a missing-glyph warning.
- A sensor key in the `instrument` global with no entry in `OG1_sensor_names.yaml` is skipped
  with a warning (no `SENSOR_` variable); the conversion failed with `KeyError`.
- `init --from` and the converter read dotted version strings (`base_station_version: "3.0.6"`)
  from newer basestation files instead of failing; `init --from` also accepts one
  `pSSSDDDD*.nc` file.
- `inspect --conversion -o DIR` accepts a directory and writes `<id>_conversion.html` into it
  (was a file path only, failing with `IsADirectoryError`).
- Raw instrument count channels with no units (`*redCount`, `*blueCount`, `*fluorCount`, `*redRef`,
  `*blueRef`) are written with `units: counts`.
- The "dimensions not merged" warning is read from the conversion record and names only
  dimensions whose variables are absent (it listed merged basestation-3 dimensions).
- A unit pair with no conversion warns once, not once per dive.
- A version attribute stored as a string is written as is (`"2.10"` stayed `2.10`, was `2.1`).
- Conversion page: the Before → after verdict counts required OG1 variables as well as globals;
  the Reconciliation Meaning texts name sections instead of numbers (they pointed one section
  off after the reorder); the OG1-file caption names the Orig var / Orig dim columns.
- `inspect --conversion -o DIR/` creates the directory, and a write error exits 1 with a message
  instead of a traceback.
- The `init` template's `id` line no longer says `init --from` proposes an id (it never did);
  null means the derived `<serial>_<start>_<mode>`.
- `config/OG1_variable_attributes.yaml` no longer carries `platform_model_vocabulary` /
  `platform_maker_vocabulary` defaults (never written to files; the maker term named Teledyne Webb
  Research, the Slocum maker). Set both per glider in `mission.yaml`; the sg005 example now does.
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
