.. _migrating_0_1_0:

Migrating to 0.1.0
==================

0.1.0 is a breaking release: the public API was reshaped to the OceanGliders family
convention (a clean break, no deprecation shims), and the output format changed. This page
is the "what you need to change" reference; the :doc:`changelog` lists the changes tersely.

Renamed functions, modules and arguments
-----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 48 52

   * - was
     - now
   * - ``ds, varlist = convert_to_OG1(ds_or_list)``
     - ``ds = seagliderOG1.convert(sequence_of_datasets)`` — returns the Dataset; takes a sequence
       (wrap a single dataset as ``[ds]``)
   * - ``from seagliderOG1 import convertOG1`` → ``convertOG1.convert_to_OG1(...)``
     - ``import seagliderOG1 as sg`` → ``sg.convert(...)`` — the module ``convertOG1.py`` became the
       private ``_convert.py``; the public entry is the top-level verb ``seagliderOG1.convert``
   * - ``convertOG1.process_and_save_data(directory)`` (convert a mission directory and write
       its OG1 file)
     - ``seagliderOG1.process(mission, *, output_dir=, dives=, mode=, report=, overwrite=) ->
       Path`` for one mission, or ``seagliderOG1 process mission.yaml`` from the command line —
       ``mission`` is the ``mission.yaml`` path or a loaded mapping; the output path and all
       metadata come from it, not from keyword arguments. ``seagliderOG1.process_missions`` runs
       it across a root of ``SN/DATE`` missions
   * - ``writers.save_dataset(ds, output_file="../test.nc") -> bool``
     - ``writers.write(ds, path, *, overwrite=False) -> pathlib.Path`` — ``path: str | Path``,
       no default; returns the path written; raises instead of returning ``False``
   * - ``plotters.plot_*(…)`` returned ``None`` and called ``plt.show()``
     - ``plotters.plot_*(…, ax=None) -> (fig, ax)``; no ``plt.show()``
   * - ``plotters.show_*(path_or_dataset)``
     - ``plotters.show_*(dataset)`` — Dataset only (the file-path branch is gone)
   * - ``readers.load_sample_dataset()``
     - ``readers.load_sample_basestation()``
   * - ``standardise_OG10`` and its ``OG1_mapping`` argument
     - ``standardise_og1`` and ``og1_mapping`` — ``og1`` lower-case in names; the package name
       keeps its spelling
   * - ``tools.OG1_name_mapping(...)`` / ``print_OG1_mapping_summary(...)``
     - the basestation → OG1 name mapping is built internally by ``seagliderOG1.convert``; the
       internal ``og1_name_mapping`` and the former ``name_mapping`` helper moved to the private
       conversion module, and ``print_OG1_mapping_summary`` was removed
   * - ``tools`` pipeline internals (``og1_name_mapping``, ``gather_sensor_info``,
       ``add_sensor_to_dataset``, ``merge_datasets_along_time``, ``extract_scalar_parameters`` /
       ``add_scalar_parameters``, ``set_best_dtype``, …) and the ``seagliderOG1.utilities`` module
     - moved to a private module (not part of the public API); ``tools`` keeps the user-facing
       utilities (``add_depth``, ``add_phase``, ``convert_units_var``, ``convert_qc_flags``,
       ``encode_times_og1``, …)
   * - ``firstrun=`` parameters (e.g. ``tools.convert_units_var(..., firstrun=...)``)
     - removed; progress and diagnostics go through ``logging.getLogger("seagliderOG1...")``
       (set the level, e.g. the CLI ``-v``)
   * - ``readers.load_basestation_files(dir, first, last, repair=)``
     - ``readers.read_mission(source, start_profile=None, end_profile=None, *, repair=False)``
   * - ``readers.load_first_basestation_file``
     - ``readers.read_file``
   * - ``readers.scan_and_repair_files``
     - ``readers.repair_files``
   * - ``readers.profnum_from_filename`` / ``readers.glider_sn_from_filename``
     - ``readers.profile_number_from_filename`` / ``readers.serial_from_filename``
   * - ``readers.repair_netcdf_time_metadata_inplace``
     - ``readers.repair_time_metadata``
   * - ``convert.apply_keep_variables(ds, keep)``
     - ``convert.keep_variables(ds, names)``
   * - ``tools.calc_Z`` / ``tools.assign_phase`` / ``tools.assign_profile_number``
     - ``tools.add_depth`` / ``tools.add_phase`` / ``tools.add_profile_number``
   * - ``contributors.registry_institutions()``
     - ``contributors.institution_registry()``
   * - ``contributors.normalize_orcid`` / ``contributors.normalize_role``
     - ``contributors.canonical_orcid`` / ``contributors.canonical_role``
   * - ``vocabularies.load_default_contributors``, ``vocabularies.contrib_to_append``,
       ``config/OG1_author.yaml``
     - removed — contributors come from ``mission.yaml``; no packaged default-identity block

Output-format changes
----------------------

- **Variable dtypes.** QC flags are ``int8`` (were ``float32``/``int64``) and use ``6`` for
  unsampled with no ``_FillValue``; ``PHASE`` is ``int8``; ``PROFILE_NUMBER``, ``DIVE_NUMBER`` and
  ``VBD_MIN_CNTS`` are ``int16``; ``DEPTH`` and ``DEPTH_Z`` are ``float32``;
  ``LATITUDE``/``LONGITUDE`` stay ``float64``. A reader that assumes the old dtypes, or tests
  ``np.isnan`` on a QC flag, must adapt; CF-decoding readers are unaffected.
- **Time units.** ``seconds since 1970-01-01T00:00:00Z`` / ``gregorian`` (was the non-conformant
  ``seconds since 1970-01-01 00:00:00`` / ``standard``). The instant is unchanged; a parser that
  string-matched the old units must adapt.
- **TEMP units** are ``degree_Celsius`` (CF spelling) rather than ``Celsius``; values unchanged.
- **featureType / Conventions.** ``featureType`` is ``trajectory`` (was ``trajectoryProfile``);
  ``Conventions`` is ``CF-1.10, ACDD-1.3, OG-1.0`` (was ``CF-1.10,OG-1.0``).
- **No placeholders.** A missing mandatory global is no longer written as ``null`` /
  ``null@null.com``; a config that relied on the fabricated email must set a real
  ``contributor_email``. ``seagliderOG1.convert`` raises ``MetadataError`` on a missing mandatory global.
- **Per-dive-varying scalars** (e.g. the flight-model constants ``C_VBD``, ``HD_A``/``HD_B``/
  ``HD_C``) are written as a JSON-string scalar variable
  (``{"dives": [...], "values": [...]}``, tagged ``serialization: json``) instead of broadcast
  onto ``N_MEASUREMENTS``. Decode the JSON to read them.
- **Conversion provenance in the output.** Every variable carries ``original_name`` (its
  basestation name; equal to the OG1 name when it passed through unrenamed), and merged variables
  also carry ``original_dimension``. New globals record the conversion: ``conversion_dimensions``
  (each basestation dimension's fate and the variables it carried), ``conversion_derived_variables``
  (the converter-created variables mapped to the basestation variables they consumed),
  ``conversion_dropped_variables``, ``conversion_removed_variables``,
  ``conversion_input_variable_count`` and ``conversion_attribute_sources``.
  ``seagliderOG1 inspect --conversion`` reads them back and
  prints them (``-o`` writes an HTML page). The attribute is ``original_name`` — code that read
  the development-only ``original_variable_name`` must use ``original_name``.
- **history** is a single conversion provenance line; the basestation ``comment`` is no longer
  renamed to ``history``. A reader that parsed the old per-dive processing log out of ``history``
  must adapt.

Metadata now comes from the mission config
-------------------------------------------

Platform, contributor, institution and deployment metadata are supplied in ``mission.yaml`` (see
:doc:`mission_yaml`), not defaulted inside the package:

- A missing ``PLATFORM_SERIAL_NUMBER`` (no file ``platform_id``, none in the config) raises
  instead of defaulting to ``sg000``; other platform fields are written ``"UNK"`` with a warning
  rather than ``0000000`` or a hard-coded model.
- ``seagliderOG1.convert`` takes ``contributors=``, ``institutions=``, ``platform=``, ``deployment=``,
  ``global_attributes=`` as lists/dicts from the config. A missing contributor role is no longer
  defaulted to ``PI``; an unrecognised institution is no longer stamped with a default EDMO code.
