.. _conversion:

What the conversion does
========================

``seagliderOG1`` converts `Seaglider <https://apl.uw.edu/project/project.php?id=seaglider>`_
basestation files (``pSSSDDDD*.nc``) into `OG1 format
<https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_, the
OceanGliders community format for glider data exchange. This page describes what changes
between the input and the output.

Overview
--------

Seaglider data is produced in a basestation format that varies between deployments and has
changed over time. OG1 is a single, CF-compliant layout for sharing glider data.

**Inputs**

* the per-dive basestation files of one mission (``pSSSDDDD_YYYYMMDD.nc``, one file per
  dive-climb cycle);
* a ``mission.yaml`` — the per-deployment metadata you supply (platform, contributors,
  institutions, raw-data directory, dive range, mode; see :ref:`configuration`);
* the packaged OG1 mappings and vocabularies, the same for every mission (see :ref:`defaults`).

**Outputs**

* one OG1 file per mission, all dive-climb cycles concatenated onto a single measurement axis
  (``sg_data_point`` becomes ``N_MEASUREMENTS``);
* a conversion record ``<id>_conversion.json`` beside it (what was renamed, merged and dropped,
  and each variable's per-dive presence);
* optionally an HTML conversion page (see :ref:`conversion_page`).

**Overall action** — concatenate the dives onto one measurement axis; rename variables to OG1,
attach CF and OG1 attributes, and convert units; add platform, sensor, contributor and
institution metadata from the ``mission.yaml``; and add GPS fixes, dive and profile numbering,
and dive phase. A basestation variable OG1 does not name is passed through under its own name.

The steps
---------

``seagliderOG1.convert`` turns the dive files of one mission into one OG1 dataset. In order:

#. **Plan the merge.** Read every dive file's dimensions and decide which merge onto the
   measurement axis (``sg_data_point`` becomes ``N_MEASUREMENTS``) and which are carried as
   scalars. Build the basestation → OG1 name mapping once, across all files, so a variable
   present in only some dives gets the same name everywhere.
   *Page:* Dimensions; Reconciliation.

#. **Per dive file:**

   * merge that file's dimensions onto the measurement axis;
   * append the GPS fixes as extra rows (``LATITUDE_GPS``, ``LONGITUDE_GPS``, ``TIME_GPS``);
   * add ``DIVE_NUMBER``, ``PROFILE_NUMBER`` and ``PHASE``;
   * apply the OG1 vocabulary: rename, attach the OG1 attributes, convert units, mark the
     coordinates, encode time. A variable with no OG1 name keeps its basestation name.

   *Page:* Derived variables; Variables.

#. **Concatenate** the dives on ``N_MEASUREMENTS`` and sort by ``TIME``.
   *Page:* Before → after (samples on the shared axis).

#. **Sensors.** Gather each instrument's record from the calibration comments, apply the
   ``sensors:`` corrections from the mission file, write one ``SENSOR_*`` variable per instrument
   and point each measured variable's ``sensor`` attribute at it.
   *Mission file:* ``sensors:``. *Page:* Sensors named by OG1.

#. **Scalars.** Collect the per-dive parameters (``log_*``, ``sg_cal_*``, ``gc_*``); a value
   constant across the mission is stored as a scalar, one that varies is stored per dive.
   *Page:* Scalar parameters.

#. **Identity and metadata.** Resolve the platform fields (mission file over the first dive
   file's attributes), add ``TRAJECTORY``, apply the global attributes from the three sections,
   the contributor and institution records, the coverage bounds computed from the data, and the
   conversion record.
   *Mission file:* ``platform:``, ``identity_and_discovery:``, ``rights_and_access:``,
   ``provenance_and_processing:``, ``contributors:``, ``institutions:``.
   *Page:* mission.yaml against the data; Global attributes.

Steps 1 and 3–6 run once per mission; step 2 runs once per dive file. Each *Page:* note names the
section of the :ref:`conversion_page` that shows that step's result.

What changes
------------

The steps above apply these transformations; each is detailed below.

Variable names
~~~~~~~~~~~~~~~

Variable names are mapped to OG1 (full mapping in `OG1_variable_names.yaml
<https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_variable_names.yaml>`_):

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

Units
~~~~~

* Units are converted to the OG1 preferred units where a mapping exists (for example cm/s to
  m/s); the mappings are in ``vocabularies.py``.
* Variables carry ``standard_name``, ``long_name`` and ``units``.
* Controlled vocabularies come from `NERC <http://vocab.nerc.ac.uk/>`_.

Some basestation versions label a variable with units that are wrong for the magnitude the
values hold: the density family (``density``, ``density_insitu``, ``sigma_t``, and on
basestation 2.8 ``sigma_theta``) is written ``g/m^3`` while holding kg m-3-magnitude values. The
corrections are listed in ``config/OG1_unit_corrections.yaml``, keyed by the basestation variable
and **guarded by the label as written** -- a file that already labels the variable ``kg/m^3`` is
left untouched, so the correction is harmless once a basestation fixes its output. The label is
corrected to ``kg m-3`` before conversion, so no factor runs and the output equals the basestation
value; the basestation label is kept in ``original_units`` with a note in ``comment``, and the
correction is logged.

The converter does **not** silently change a value because it is out of range. The one exception is
a refusal, not a change: if a unit conversion moved a value outside the OG1 variable's
``valid_min`` / ``valid_max`` and undoing the conversion lands it back in range, the basestation
label is wrong and the conversion raises ``UnitsError`` rather than writing a file off by a unit
factor. Any other out-of-range value is left as-is and flagged on the conversion page (for example
basestation 2.8 stores ``sigma_theta`` as full density, ~1027, not the anomaly its name implies).
Use ``drop_variables`` or a ``mission.yaml`` override to act on what the page flags; the page also
recommends variables to drop where OG1 defines the name for a different quantity (such as
``gsw_sigma0``, the density anomaly, where OG1 ``POTDENS0`` is full potential density).

GPS data
~~~~~~~~

GPS fixes are **appended to the dataset as extra rows along** ``N_MEASUREMENTS`` (increasing its
length), not interpolated onto the measurement times:

* ``LATITUDE_GPS``, ``LONGITUDE_GPS`` and ``TIME_GPS`` hold the fix values, non-NaN only at the
  appended GPS rows;
* the dataset is sorted by ``TIME`` after the fixes are added.

Sensors, global attributes and QC
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Sensors**: sensor information and calibration coefficients are catalogued from the
  basestation attributes and written as OG1 sensor variables.
* **Global attributes**: CF and OG1 global attributes from ``config/OG1_global_attributes.yaml`` and
  the mission configuration.
* **QC variables**: where the basestation input carries a ``<name>_qc`` flag, it is carried
  through as the OG1 ``<NAME>_QC`` companion of the kept variable; variables with no input flag
  do not gain one (``convert.py``).

Extended variables
~~~~~~~~~~~~~~~~~~~

Beyond the core OG1 variables, the output preserves:

* flight-model velocities (vertical and horizontal) from the glider flight model;
* engineering variables describing glider state;
* derived oceanographic variables where present in the input.

Variables that differ between dives
-----------------------------------

The basestation files of one mission need not carry the same variables: a sensor switched on
part-way through, or present but off, makes the files disagree. The converter works from the
union of the variables, so the OG1 file has one variable where the inputs had it on some dives
and not others, and cannot say which dives that was.

``seagliderOG1.process`` (and the ``process`` CLI) records this in ``<id>_conversion.json`` beside
the OG1 file. For each basestation variable it gives the runs of dives it is *present* in (the
variable exists in the file) and *valid* in (present, with at least one non-missing value). The
conversion record also lists the input files, records the ``dives``, ``platform`` and ``institutions`` values
the conversion was given (not for a draft) and the basestation ``institution`` global's registry
match, and carries the file's ``id``, ``tracking_id`` and SHA-256;
the conversion-record reader reads it back and ignores a conversion record whose ``id`` or
``tracking_id`` differs from the file's (``seagliderOG1 report`` also checks the SHA-256).

The conversion page groups the variables into patterns — ``every dive``, ``from dive k``,
``until dive k``, ``dive k only``, ``dives a–b``, ``sporadic`` — and shows each as a strip over
the dives. On the bundled ``sg271`` sample (three dives), 500 of the 542 variables are on every
dive and 42 vary across the dives, in five patterns.

Nothing about this is added to the OG1 file.

Checking the output
-------------------

The ``validate`` verb checks the **mission configuration** before conversion: known and
required keys, that ``raw_dir`` is reachable and holds basestation files, the dive range, the
required platform fields, and that the contributor and institution records include at least
one PI and one Operator. During conversion the input coordinates are checked. Neither step runs
an OG1 compliance check on the output file.

Output files target:

* `OG1 Format Specification <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_
* `CF Conventions <http://cfconventions.org/>`_ (version 1.10)
* `ACDD Conventions <https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery>`_

The output carries ``featureType: trajectory`` (``config/OG1_global_attributes.yaml``).

Two results of the OG1 checker (``ioos/cc-plugin-og``, ``compliance-checker --test og:1.0``) are
expected on every file this package writes:

* **Variable names should be capitalized** — a basestation variable with no OG1 name keeps its
  basestation spelling (``log_D_TGT``, ``sg_cal_calibcomm``, ``sbe41``), so its name shows at a
  glance that it is not an OG1 variable. The OG1 manual calls upper-case variable names "the OG1
  convention" (in its sensor-variable section); keeping the basestation spelling is a deliberate
  departure from it. Variables renamed to an OG1 name are upper case; a variable passed through
  carries ``original_name`` equal to its name.
* **Global attribute comment is missing** — when ``provenance_and_processing.comment`` in
  ``mission.yaml`` is null. The OG1 manual lists ``comment`` as *suggested* (cc-plugin-og 0.1.2
  checks it as mandatory), so the converter writes no default text; set it to add one.

Any other checker finding is a converter problem. To run the checker:

.. code-block:: console

   $ pip install cc-plugin-og
   $ compliance-checker --test og:1.0 <output_dir>/<id>.nc

For the data themselves, use `glidertest
<https://github.com/OceanGlidersCommunity/glidertest>`_.
