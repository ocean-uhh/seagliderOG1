.. _conversion_page:

The report pages
================

``seagliderOG1 report`` (and ``process --report``) writes a set of linked HTML pages beside the
OG1 file, each named ``<id>_<page>.html``. They describe the same mission for two readers: one
who knows the basestation files, and one who knows OG1. See the :ref:`example_report`.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Page
     - What it shows
   * - **Conversion** (``_conversion``)
     - The landing page: a summary of what went in and what came out, the losses, the flight
       model's inputs, the sensors and their calibration comments, one variable traced from
       the basestation file to the OG1 file, and the ``mission.yaml`` checks below.
   * - **Variables** (``_variables``)
     - Every basestation variable once, beside its OG1 counterpart: name, fate, dimension,
       units, dtype and value counts (basestation form above, OG1 form below), vocabulary, the
       inputs and method of each variable the converter built, and marks for each step and
       loss. Search by either name; filter by fate, subsystem, a loss, a scalar, an OG1 name
       without a vocabulary link, or *candidate for OG1* (the project's proposed OG1
       parameters, :data:`seagliderOG1.vocabularies.OG1_CANDIDATE_VARS`; the ones the file
       does not hold are listed under the filters).
   * - **Processing** (``_processing``)
     - Every step of the conversion in the order it ran, with what each step did to this
       mission, and the unit changes.
   * - **Phase** (``_phase``)
     - How ``PHASE`` was assigned and what it gives; see :ref:`phase`. Not written for a
       draft.
   * - **Basestation** (``_basestation``)
     - The dive files as read, for a mission of any length: the dimension sizes by dive
       (shaded by samples per minute of dive), the variables not in every dive (one strip per
       pattern), the parameters that change between dives, the basestation's salinity
       corrections, the global attributes that differ between files, and every variable by
       dimension. Needs the conversion record.
   * - **OG1 format** (``_og1``)
     - The OG1 file read as OG1: conformance against the OG1 requirements, the OG1 variables
       by group, the sensors, the per-dive parameters decoded, the variables passed through
       under basestation names, and the global attributes with the Conventions check and the
       history. Not written for a draft.

Each page opens with the same masthead: the glider and site, the deployment's facts, and the
nav to the other pages. The pages' sections are numbered, ``(1)``, ``(2)``, …, with reference
sections (the glossary, the global attributes) lettered ``(A)``, ``(B)``.

A draft (``seagliderOG1 draft``) gets the Conversion, Variables, Processing and Basestation
pages, with the basestation files' own global attributes on its Conversion page.

The mission.yaml checks
-----------------------

The Conversion page has a section **mission.yaml against the data** when the ``mission.yaml``
the conversion was given (``process``, or ``seagliderOG1.process``) and the output disagree or
fall short, as copyable boxes of ``mission.yaml`` lines. Each check is shown only when it finds something:

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

Salinity on the Basestation page
--------------------------------

The basestation writes salinity twice: corrected (``salinity``, which becomes ``PSAL``) and
uncorrected (``salinity_raw``). The Basestation page compares them, and each with practical
salinity recomputed from the basestation's conductivity, temperature and ``ctd_pressure`` with
``gsw.SP_from_C`` (for the page only; nothing is written):

* ``salinity_raw`` − SP(``conductivity_raw``, ``temperature_raw``) — the plain conversion;
  about zero when gsw and the basestation agree on it;
* ``salinity`` − ``salinity_raw`` — the basestation's corrections in total;
* ``salinity`` − SP(``conductivity``, ``temperature``) — what is left after the corrected
  temperature and conductivity: corrections the basestation applies to salinity itself.

Each gives the median, RMS and largest difference, and the median by dive as a strip, so a
correction that drifts through the mission shows.

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
