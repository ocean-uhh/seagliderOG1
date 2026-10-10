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

Variable names are mapped to OG1 (full mapping in ``config/OG1_var_names.yaml``):

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
* **Global attributes**: CF and OG1 global attributes from ``config/OG1_global_attrs.yaml`` and
  the mission configuration.
* **QC variables**: a ``<NAME>_QC`` companion variable is created for each kept science
  variable (``convertOG1.py``).

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

* ``OG1_var_names.yaml`` — variable name mappings;
* ``OG1_vocab_attrs.yaml`` — CF variable attributes;
* ``OG1_sensor_attrs.yaml`` — sensor metadata;
* ``OG1_global_attrs.yaml`` — global attribute templates;
* ``institution_registry.yml`` — EDMO codes for resolving institutions.

OG1 compliance
--------------

Output files target:

* `OG1 Format Specification <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_
* `CF Conventions <http://cfconventions.org/>`_ (version 1.10)
* `ACDD Conventions <https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery>`_

The output carries ``featureType: trajectoryProfile`` (``config/OG1_global_attrs.yaml``).

Validation
----------

The ``validate`` verb checks the **mission configuration** before conversion: known and
required keys, that ``source`` is reachable and holds basestation files, the dive range, the
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

   from seagliderOG1 import convertOG1, readers, writers

   datasets = readers.load_basestation_files(source, first, last)
   ds, _ = convertOG1.convert_to_OG1(
       datasets,
       contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
       institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
   )
   writers.save_dataset(ds, out)

The ``contributors`` and ``institutions`` arguments are lists of records, one entry per person
(or institution) per role; a conversion with no PI warns. See :ref:`cli_reference`.
