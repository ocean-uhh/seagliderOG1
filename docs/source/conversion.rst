.. _conversion:

What the conversion does
========================

``seagliderOG1`` converts `Seaglider <https://apl.uw.edu/project/project.php?id=seaglider>`_
basestation files (``pSSSDDDD*.nc``) into `OG1 format
<https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_, the
OceanGliders community format for glider data exchange. This page describes what changes
between the input and the output.

Purpose
-------

Seaglider data is produced in a basestation format that varies between deployments and has
changed over time. OG1 is a single, CF-compliant layout for sharing glider data. The
conversion:

* concatenates the per-dive basestation files of one mission into a single trajectory file;
* renames variables, standardises units, and attaches CF and OG1 attributes;
* adds platform, sensor, contributor and institution metadata from a ``mission.yaml`` the
  user keeps with the data;
* adds GPS fixes, dive and profile numbering, and dive phase.

Data structure
--------------

* **Input**: one file per dive-climb cycle (``pSSSDDDD_YYYYMMDD.nc``).
* **Output**: one file per mission, all cycles concatenated.
* **Dimension**: ``sg_data_point`` becomes ``N_MEASUREMENTS``.

Variable names
--------------

Variable names are mapped to OG1 (full mapping in ``config/OG1_variable_names.yaml``):

.. code-block:: text

   Basestation   OG1
   ----------------------------
   latitude      LATITUDE
   longitude     LONGITUDE
   ctd_time      TIME
   gps_lat       LATITUDE_GPS
   gps_lon       LONGITUDE_GPS
   eng_pitchAng  PITCH
   eng_rollAng   ROLL
   ctd_depth     DEPTH

Metadata added
--------------

* **Sensors**: sensor information and calibration coefficients are catalogued from the
  basestation attributes and written as OG1 sensor variables.
* **Global attributes**: CF and OG1 global attributes from ``config/OG1_global_attributes.yaml`` and
  the mission configuration.
* **QC variables**: where the basestation input carries a ``<name>_qc`` flag, it is carried
  through as the OG1 ``<NAME>_QC`` companion of the kept variable; variables with no input flag
  do not gain one (``convert.py``).

GPS data
--------

GPS fixes are **appended to the dataset as extra rows along** ``N_MEASUREMENTS`` (increasing its
length), not interpolated onto the measurement times:

* ``LATITUDE_GPS``, ``LONGITUDE_GPS`` and ``TIME_GPS`` hold the fix values, non-NaN only at the
  appended GPS rows;
* the dataset is sorted by ``TIME`` after the fixes are added.

Units
-----

* Units are converted to the OG1 preferred units where a mapping exists (for example cm/s to
  m/s); the mappings are in ``vocabularies.py``.
* Variables carry ``standard_name``, ``long_name`` and ``units``.
* Controlled vocabularies come from `NERC <http://vocab.nerc.ac.uk/>`_.

Configuration
-------------

The user's configuration is a ``mission.yaml`` file kept with the data — source, output
directory, dive range, platform block, and the contributor and institution records. See
:ref:`mission_yaml` for every key and :ref:`cli_reference` for the commands.

The package's own YAML files are not user settings; they hold the OG1 vocabularies and
mappings:

* ``OG1_variable_names.yaml`` — variable name mappings;
* ``OG1_variable_attributes.yaml`` — CF variable attributes;
* ``OG1_sensor_attributes.yaml`` — sensor metadata;
* ``OG1_global_attributes.yaml`` — global attribute templates;
* ``institution_registry.yaml`` — EDMO codes for resolving institutions.

OG1 compliance
--------------

Output files target:

* `OG1 Format Specification <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_
* `CF Conventions <http://cfconventions.org/>`_ (version 1.10)
* `ACDD Conventions <https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery>`_

The output carries ``featureType: trajectory`` (``config/OG1_global_attributes.yaml``).

Variables that differ between dives
-----------------------------------

The basestation files of one mission need not carry the same variables: a sensor switched on
part-way through, or present but off, makes the files disagree. The converter works from the
union of the variables, so the OG1 file has one variable where the inputs had it on some dives
and not others, and cannot say which dives that was.

``convert.process_mission`` (and so ``process``) records this in ``<id>_conversion.json`` beside
the OG1 file. For each basestation variable it gives the runs of dives it is *present* in (the
variable exists in the file) and *valid* in (present, with at least one non-missing value). The
sidecar also lists the input files and carries the file's ``id`` and ``date_created``;
``convert.conversion_sidecar`` reads it back and ignores a sidecar whose ``id`` or
``date_created`` differs from the file's.

The conversion page groups the variables into patterns — ``every dive``, ``from dive k``,
``until dive k``, ``dive k only``, ``dives a–b``, ``sporadic`` — and shows each as a strip over
the dives. On the bundled ``demo_sg005`` sample (dives 1–5), 338 variables are on every dive,
the four depth-averaged currents are present on every dive but have values from dive 2, and
``log_ALTIM_BOTTOM_PING`` is on dive 4 only.

Nothing about this is added to the OG1 file.

.. _conversion_page:

The conversion page
-------------------

``seagliderOG1 report`` (and ``process --report``) writes an HTML page for the OG1 file. A
draft (``seagliderOG1 draft``) gets the same page with its global attributes replaced by the
basestation files' own.
Its sections, in order:

#. **Before → after** — files, dives, size on disk, samples on the shared axis, variable and
   global-attribute counts, time span and OG1-requirement coverage, basestation input beside
   OG1 output, with a one-line verdict. The input column reads the sidecar; its cells show
   ``—`` when the sidecar is absent.
#. **The OG1 file** — the output read by what OG1 says about each variable, not by where it
   came from, with an *Orig var* / *Orig dim* column pair naming the basestation source:

   * *Required by OG1* — the variables (and the ``N_MEASUREMENTS`` dimension) a valid OG1 file
     must carry, present/absent, from :data:`seagliderOG1.vocabularies.OG1_REQUIRED_VARS` (the
     upstream ``ioos/cc-plugin-og`` checker list).
   * *Named by OG1* — variables OG1 defines but does not require (science, phase, sensor, QC).
   * *Candidate for OG1* — variables the project proposes to canonise, from
     :data:`seagliderOG1.vocabularies.OG1_CANDIDATE_VARS` (e.g. the flight-model inputs and
     outputs), shown present/absent; edit that list as candidates are agreed.
   * *Carried through* — everything else, summarised by basestation family.
   * *Same quantity, more than once* — where several variables share a ``standard_name``, each
     compared (member − reference) to the OG1 reference member, in its units.
#. **Reconciliation** — each basestation variable's one fate (renamed, passed through,
   consumed, removed, dropped, skipped) with a count, a Meaning column, and a fate histogram.
#. **Presence across dives** — the patterns above, with each pattern's share of the input dives.
#. **Dimensions** — each basestation dimension's fate, the samples it supplied, and the
   dimension it ended on.
#. **Derived variables** — variables the converter built, with their basestation sources.
#. **Dropped and removed variables** — variables left out by ``keep_variables`` or the package
   drop list (empty, so every basestation variable is retained).
#. **By basestation origin** — the same output variables grouped by original dimension, with a
   Valid % column and a per-group baseline (the share of the axis that dimension supplied).
#. **Global attributes** — grouped by convention and OG1 tier, with recomputed coverage bounds
   and the history.
#. **Scalar parameters** — the per-dive and constant scalars, split by group, each collapsible.

Validation
----------

The ``validate`` verb checks the **mission configuration** before conversion: known and
required keys, that ``raw_dir`` is reachable and holds basestation files, the dive range, the
required platform fields, and that the contributor and institution records include at least
one PI and one Operator. During conversion the input coordinates are checked.

Neither step runs an OG1 compliance check on the output file. To check a finished OG1 file
against the format, use `glidertest <https://github.com/OceanGlidersCommunity/glidertest>`_.

Extended variables
------------------

Beyond the core OG1 variables, the output preserves:

* flight-model velocities (vertical and horizontal) from the glider flight model;
* engineering variables describing glider state;
* derived oceanographic variables where present in the input.

Example
-------

From the command line, after ``init`` and ``validate`` (see :ref:`cli_reference`):

.. code-block:: console

   $ seagliderOG1 process sg005.yaml      # -> <output_dir>/<id>.nc

or from Python:

.. code-block:: python

   from seagliderOG1 import convert, readers, writers

   datasets = readers.read_mission(source, first, last)
   ds = convert.to_og1(
       datasets,
       contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
       institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
   )
   writers.write(ds, out)

The ``contributors`` and ``institutions`` arguments are lists of records, one entry per person
(or institution) per role; a conversion with no PI warns. See :ref:`cli_reference`.

What the conversion records
---------------------------

The output file records what the conversion did, so the treatment can be read back from the
file alone:

* every renamed or passed-through variable carries ``original_name`` (its basestation name; equal
  to the OG1 name when the variable passed through unrenamed), and merged variables also carry
  ``original_dimension``; converter-created variables have neither (see below);
* ``conversion_dimensions`` gives each basestation dimension a fate — ``backbone`` (the dimension
  that becomes ``N_MEASUREMENTS``), ``merged``, or ``skipped`` — and lists the variables it carried
  (a variable on more than one dimension is listed under each, so the counts are not a partition);
* ``conversion_derived_variables`` lists the variables the converter created (which therefore have
  no ``original_name``);
* ``conversion_dropped_variables`` lists variables removed by ``convert.keep_variables``;
* ``conversion_attribute_sources`` records the source of each global attribute;
* ``history`` is a single conversion provenance line (the basestation per-dive processing log
  is a per-dive QC record, not a mission record, so it is not carried).

A scalar that is constant across the mission is stored as a plain scalar with
``storage_type: constant_scalar``; one that varies per dive (or is missing on some dives)
is stored as a JSON string with ``storage_type: per_dive_scalar``, holding aligned ``dives``
and ``values`` lists (``null`` for a missing value).

``inspect --conversion`` prints these from any converted file, including a *Scalar
parameters* section that lists the per-dive scalars in full and summarises the constants as a
count (``--all`` lists the constants too); ``--parameter NAME`` decodes one per-dive JSON
scalar to a dive/value table:

.. code-block:: console

   $ seagliderOG1 inspect sg005_20080606_delayed.nc --conversion
   $ seagliderOG1 inspect sg005_20080606_delayed.nc --parameter surface_curr_north
