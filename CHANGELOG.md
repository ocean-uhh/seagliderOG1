# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
semantic versioning.

## [Unreleased]

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
