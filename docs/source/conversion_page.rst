.. _conversion_page:

The conversion page
===================

``seagliderOG1 report`` (and ``process --report``) writes an HTML page for the OG1 file. A
draft (``seagliderOG1 draft``) gets the same page with its global attributes replaced by the
basestation files' own.

The page opens with **mission.yaml against the data** when the ``mission.yaml`` the conversion
was given (``process``, or ``seagliderOG1.process``) and the output disagree or fall short, as
copyable boxes of ``mission.yaml`` lines. Each check is shown only when it finds something:

* *Dive range* — the requested ``dives`` against the first and last dive that reached the file
  (a dive outside the files, or an end dive rejected as empty or invalid), naming dives inside
  that span that were not converted;
* *Platform from the files* — each platform field set in the config against the value the
  converter derives from the first basestation file (``PLATFORM_SERIAL_NUMBER``,
  ``GLIDER_FIRMWARE_VERSION``, ``LANDSTATION_VERSION``, ``WMO_IDENTIFIER``), naming the source
  global when the files carry more than one value. The config wins by design, so a pair is a
  value to check, not an error;
* *Platform not filled* — required or file-derivable platform fields written as ``UNK`` or, for
  the numeric ``PLATFORM_DEPTH_RATING``, omitted;
* *Institution ids* — config institutions with no ``id`` that the package's EDMO registry
  (``config/institution_registry.yaml``) matched by name, as an ``institutions:`` block with the
  registry name and id filled in;
* *Deployment id* — the derived ``id`` as an ``identity_and_discovery.id`` line, when the
  conversion starts at dive 1 and that ``id`` is null: pinned, it survives a later conversion of
  part of the mission, which would derive a later start time and so a different id;
* *Institution not in the registry* — a config institution the registry does not match
  exactly, with the registry entries whose names contain every word of it (``University of
  Hamburg Oceanography`` → ``University of Hamburg``, EDMO 3323);
* *Institution in the basestation files* — the basestation ``institution`` global's registry
  match, when no config institution resolved to it. The converter does not write the file's
  institution when the config lists institutions (it would be a second, role-less record), so
  this is where it surfaces, with ``role: null`` to fill;
* *Missing globals* — OG1 highly-desirable globals (the ones ``validate`` warns about) and ACDD
  1.3 globals the file does not carry, each labelled with its tier, under the global-attribute
  section that sets it and ``global_attributes:`` otherwise. Globals the converter supplies
  itself (``standard_name_vocabulary``, ``geospatial_bounds_crs``, ``time_coverage_resolution``,
  …) are named, not boxed: they are not ``mission.yaml`` values. Nor are ``creator_*`` and
  ``publisher_*``: OG1 defines neither and records people and organisations in
  ``contributor_*`` and ``contributing_institutions_*``.

The dive, platform-pair and institution checks read the ``config`` the conversion record records, so a page
for a file converted before it was recorded shows only the other two. A draft has no such section.

Its sections, in order:

#. **Before → after** — files, dives, size on disk, samples on the shared axis, variable and
   global-attribute counts, time span and OG1-requirement coverage, basestation input beside
   OG1 output, with a one-line verdict. The input column reads the conversion record; its cells show
   ``—`` when the conversion record is absent.
#. **The OG1 file** — the output read by what OG1 says about each variable, not by where it
   came from, with an *Orig var* / *Orig dim* column pair naming the basestation source:

   * *Required by OG1* — the variables (and the ``N_MEASUREMENTS`` dimension) a valid OG1 file
     must carry, present/absent, from :data:`seagliderOG1.vocabularies.OG1_REQUIRED_VARS` (the
     upstream ``ioos/cc-plugin-og`` checker list).
   * *Sensors named by OG1* — one row per ``SENSOR_*`` variable: type, maker, model, serial
     number, calibration date, and the variables whose ``sensor`` attribute names it. Amber: a
     placeholder serial or date (empty, or every digit zero), or a serial shared by two sensors
     (a calibration comment copied between instruments); correct either with ``sensors:`` in
     ``mission.yaml``.
   * *Named by OG1* — variables OG1 defines but does not require (science, phase, QC).
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

   $ seagliderOG1 inspect sg005_20080606T180256_delayed.nc --conversion
   $ seagliderOG1 inspect sg005_20080606T180256_delayed.nc --parameter surface_curr_north
