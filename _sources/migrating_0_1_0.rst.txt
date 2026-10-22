.. _migrating_0_1_0:

Migrating to 0.1.0
==================

0.1.0 reshapes the public API into the OceanGliders family's verbs and changes the output
format. To ease the move, the pre-0.1.0 names are kept for one release: most are **still
importable and warn**, a few are **removed and raise** with a message that points back here.
("Pre-0.1.0" because a few of these names never shipped in a tagged release — they lived on
``main`` between 0.0.2 and 0.1.0; they are marked where they appear.)

This page is organised by what you do in a notebook — load, convert, write, plot, metadata —
so you can find the line you have and read the line to write. Each old name is marked:

- *(warns)* — still importable until 0.3.0. It works, delegates to the new name, and prints a
  ``DeprecationWarning`` naming the new spelling. Change it at your leisure before 0.3.0.
- *(raises)* — removed. Importing or calling it raises with a message that says why and what
  to use instead (the same text as the relevant section below).
- *(changed)* — not shimmed: the call shape changed, so update it now.

The shims are removed in 0.3.0; see the :doc:`changelog`.

The whole mission in one call
-----------------------------

Most of what a conversion notebook does is read a mission, convert it, and write the file.
That is now one call that takes a ``mission.yaml`` (see :doc:`mission_yaml`).

Before (v0.0.2):

.. code-block:: python

   from seagliderOG1 import readers, convertOG1, writers

   list_datasets = readers.load_basestation_files(input_dir, start_profile=1, end_profile=5)
   ds_OG1, var_list = convertOG1.convert_to_OG1(list_datasets)
   writers.save_dataset(ds_OG1, output_file="out.nc")

After (0.1.0):

.. code-block:: python

   import seagliderOG1 as sg

   path = sg.process("mission.yaml", overwrite=True, report=True)  # read + convert + write (+ page)

``process`` reads the raw directory, dive range, platform, contributors and global attributes
from the ``mission.yaml``; there is no separate metadata argument. For a root of ``SN/DATE``
missions, ``sg.process_missions("mission.yaml", select="*/*")``.

Load dive files
---------------

``load_basestation_files`` *(warns)* → ``read`` (``read_mission`` keeps the old positionals):

.. code-block:: python

   # before
   list_datasets = readers.load_basestation_files(input_dir, start_profile=1, end_profile=5)

   # after
   list_datasets = sg.read(input_dir, dives=(1, 5))

``read`` takes a ``dives=(first, last)`` tuple; ``readers.read_mission(source, start, end)`` is
the same function with the old positional arguments if you prefer them.
``readers.load_sample_dataset`` *(raises)* is gone (see below); the bundled sample is
``readers.load_sample_basestation()`` and any file is ``readers.read_file(path)``.

Convert
-------

``convertOG1.convert_to_OG1`` *(warns)* → ``convert``. The old module ``convertOG1.py`` is a
tombstone; importing it is silent, and each name warns or raises when used. ``convert``
returns a single ``Dataset`` (not a ``(dataset, var_list)`` tuple) and takes a sequence:

.. code-block:: python

   # before
   ds_OG1, var_list = convertOG1.convert_to_OG1(list_datasets)

   # after — a sequence in, one Dataset out
   ds_OG1 = sg.convert(list_datasets)

To apply a ``mission.yaml``'s metadata without writing a file, pass it: ``sg.convert(list_datasets,
mission="mission.yaml")``. ``convert`` builds the basestation → OG1 name mapping internally;
``tools.OG1_name_mapping`` / ``print_OG1_mapping_summary`` are gone (see below).

Write
-----

``writers.save_dataset`` *(warns)* → ``write``. The old default path (``../test.nc``) is not
reproduced — ``path`` is required — and ``write`` returns the ``pathlib.Path`` written rather
than a bool. Note a behaviour change: v0.0.2 coerced an attribute netCDF cannot store (a bool
or dict global) to text and returned ``False`` on failure; ``write`` raises ``TypeError`` naming
it, and writes with compression.

.. code-block:: python

   # before
   writers.save_dataset(ds_OG1, output_file="out.nc")   # -> bool

   # after
   path = sg.write(ds_OG1, "out.nc", overwrite=True)     # -> pathlib.Path

To write the HTML conversion page for a file, ``sg.report("out.nc")``.

Plot
----

``plotters.show_*(path_or_dataset)`` *(warns)* now takes a Dataset only; pass an open dataset.
``plotters.plot_*`` *(changed)* returns ``(fig, ax)`` and no longer calls ``plt.show()`` — this
one is not shimmed, because a function cannot both return a value and not:

.. code-block:: python

   # before — returned None, drew to the screen
   plotters.plot_profile_depth(ds_OG1)

   # after — returns the figure and axes; show it yourself
   fig, ax = plotters.plot_profile_depth(ds_OG1)
   fig.show()

Metadata: contributors, institutions, platform
-----------------------------------------------

This is the one change in kind. In v0.0.2 the platform, contributor and institution metadata
came from package defaults (a bundled ``OG1_author.yaml``, a default EDMO code, a default PI
role). In 0.1.0 that metadata comes from a ``mission.yaml`` you keep beside your data, so no
file is ever written with someone else's identity. Get one and fill it in:

.. code-block:: console

   $ seagliderOG1 init mission.yaml --raw-dir /path/to/dives   # writes a commented template
   $ seagliderOG1 validate mission.yaml                        # check it before converting

Then convert from it (``sg.process("mission.yaml")`` above). A missing
``PLATFORM_SERIAL_NUMBER`` (none in the files, none in the config) now raises rather than
defaulting to ``sg000``; a missing contributor role is no longer defaulted to ``PI``; an
unrecognised institution is no longer stamped with a default EDMO code. The removed
``vocabularies.load_default_contributors`` / ``contrib_to_append`` / ``config/OG1_author.yaml``
*(raises)* say so.

Names that no longer exist, and why
-----------------------------------

These are *(raises)*: calling or importing one raises with the message below rather than
returning something different from what it used to.

- ``convertOG1.process_and_save_data`` — it filled platform, contributor and institution
  metadata from package defaults, which were removed so no file is written with someone else's
  identity. Use a ``mission.yaml``: ``seagliderOG1 init out.yaml --raw-dir DIR``, fill it, then
  ``seagliderOG1.process("out.yaml")``.
- ``vocabularies.load_default_contributors`` / ``vocabularies.contrib_to_append`` /
  ``config/OG1_author.yaml`` — contributors come from the ``mission.yaml`` ``contributors:``
  block now.
- ``tools.OG1_name_mapping`` / ``tools.print_OG1_mapping_summary`` — the mapping is built inside
  ``convert``; ``seagliderOG1 inspect --conversion FILE.nc`` prints what was renamed.
- ``tools.og1_name_mapping``, ``gather_sensor_info``, ``add_sensor_to_dataset``,
  ``merge_datasets_along_time``, ``extract_scalar_parameters`` / ``add_scalar_parameters``,
  ``set_best_dtype``, and the ``seagliderOG1.utilities`` module — pipeline internals, private
  since 0.1.0; call ``seagliderOG1.convert``.
- ``standardise_OG10`` (and its ``OG1_mapping`` argument) — the OG1 name/attribute/unit step is
  internal to ``seagliderOG1.convert`` since 0.1.0; call ``seagliderOG1.convert``.
- ``readers.load_sample_dataset`` — it fetched a named sample from an online registry that was
  removed; the bundled sample is ``readers.load_sample_basestation()`` and any file is
  ``readers.read_file(path)``. (Returning the bundled sample for an arbitrary key would be a
  silent substitution.)

Other renamed names
-------------------

All *(warns)* — importable until 0.3.0, delegating to the new name. Rows marked *(main only)*
never shipped in a tagged release; they lived on ``main`` between 0.0.2 and 0.1.0, so if you
installed from PyPI you never had them — they are shimmed for development installs.

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - old name
     - 0.1.0
   * - ``readers.load_first_basestation_file``
     - ``readers.read_file``
   * - ``readers.scan_and_repair_files`` *(main only)*
     - ``readers.repair_files``
   * - ``readers.repair_netcdf_time_metadata_inplace`` *(main only)*
     - ``readers.repair_time_metadata``
   * - ``readers.profnum_from_filename`` / ``glider_sn_from_filename`` *(main only)*
     - ``readers.profile_number_from_filename`` / ``serial_from_filename``
   * - ``tools.calc_Z`` / ``assign_phase`` / ``assign_profile_number``
     - ``tools.add_depth`` / ``add_phase`` / ``add_profile_number``
   * - ``convertOG1.apply_keep_variables(ds, keep)``
     - ``keep_variables(ds, names)``
   * - ``contributors.registry_institutions`` / ``normalize_orcid`` / ``normalize_role`` *(main only)*
     - ``contributors.institution_registry`` / ``canonical_orcid`` / ``canonical_role``
   * - ``firstrun=`` keyword (e.g. ``tools.convert_units_var(..., firstrun=...)``)
     - removed; accepted and ignored with a warning. Progress goes through
       ``logging.getLogger("seagliderOG1")`` (the CLI ``-v`` sets the level)

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
- **Conversion record in the output.** Every variable carries ``original_name`` (its
  basestation name; equal to the OG1 name when it passed through unrenamed), and merged variables
  also carry ``original_dimension``. New globals record the conversion: ``conversion_dimensions``
  (each basestation dimension's fate and the variables it carried), ``conversion_derived_variables``
  (the converter-created variables mapped to the basestation variables they consumed),
  ``conversion_dropped_variables``, ``conversion_removed_variables``,
  ``conversion_input_variable_count`` and ``conversion_attribute_sources``.
  ``seagliderOG1 inspect --conversion`` reads them back and prints them (``-o`` writes an HTML
  page). The attribute is ``original_name`` — code that read the development-only
  ``original_variable_name`` must use ``original_name``.
- **history** is a single conversion line; the basestation ``comment`` is no longer renamed to
  ``history``. A reader that parsed the old per-dive processing log out of ``history`` must adapt.
