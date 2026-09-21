# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic versioning.

## [Unreleased]

### Breaking changes

- Output variable dtypes changed. QC flags are `int8` (were `float32`/`int64`); `PHASE` is
  `int8`; `PROFILE_NUMBER`, `DIVE_NUMBER` and `VBD_MIN_CNTS` are `int16`; `DEPTH` and
  `DEPTH_Z` are `float32`. `LATITUDE`/`LONGITUDE` stay `float64`. Integer variables carry a
  `_FillValue`. A reader that assumes the old dtypes, or tests `np.isnan` on a QC flag, must
  adapt; CF-decoding readers are unaffected.

### Added

- `writers.save_dataset` now writes every non-scalar numeric variable, coordinates
  included, with lossless zlib compression (level 4) and the shuffle filter. String
  and scalar variables are left uncompressed. Output files are smaller and remain
  readable by any netCDF4 client.
- `tests/test_writers.py` (9 tests, 100% coverage of `writers.py`): compression applied,
  lossless round-trip, string/scalar variables skipped, time encoding preserved, size
  reduction, retry path, caller's dataset not mutated, integer `_FillValue` preserved,
  and the failure return.

### Fixed

- `writers.save_dataset` preserves each compressed variable's `_FillValue` (and
  `scale_factor`/`add_offset`) when applying compression, so an integer missing-value
  sentinel is not written as an ordinary value.
- `writers.save_dataset` no longer mutates the caller's dataset: it copies the input
  before clearing conflicting time attributes and stringifying attributes.
- `writers.save_dataset` reuses one encoding on the retry path, so a file written after
  a `TypeError` fallback keeps its time encoding and compression instead of being
  written unencoded.
- `writers.save_dataset` return annotation corrected from `None` to `bool`.
- Dtype optimisation now runs once on the concatenated dataset (in `convert_to_OG1`) instead
  of per dive, so `int8` QC flags are no longer re-promoted to `float32` by the concat.
- `tools.set_best_dtype` now visits coordinates (so `DEPTH` becomes `float32`) and restores
  coordinate status after coercion; it respects an existing `_FillValue` sentinel (e.g.
  `PROFILE_NUMBER`'s `-9999`) instead of overriding it, never leaves `_FillValue` in attrs,
  skips QC flags, and coerces scalar variables without an indexing error.
- `tools.find_best_dtype` no longer casts variables whose name ends in `raw` to `int16` (it
  truncated float "raw" variables); named integer variables map to a fixed integer type.
- `tools.convert_qc_flags` drops the inherited float `_FillValue` from the `int8` result;
  `tools.assign_profile_number` writes `_FillValue` to encoding rather than attrs.
