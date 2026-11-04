.. _migrating_0_3_0:

Migrating to 0.3.0
==================

.. note::

   **Draft.** 0.3.0 is not released. This page collects the changes on ``main`` since 0.2.0
   that change what a file holds or what a call accepts, and will be completed before the
   tag.

0.3.0 changes the output: reconvert your missions. Nothing on this page needs a code change
unless you read ``PHASE``, ``PHASE_QC``, ``SA``/``CT``, ``uri`` or the ``SENSOR_*`` serial numbers
and dates, or still import a pre-0.1.0 name.

PHASE
-----

``PHASE`` is assigned from what the glider recorded it did (see :doc:`phase`). On the same
dive, 0.2.0 and 0.3.0 differ like this:

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * -
     - 0.2.0
     - 0.3.0
   * - values used
     - 1 ascent, 2 descent, 3 at the first two GPS fixes
     - 1 ascent, 2 descent, 3 surfacing, 4 parking (a loiter), 5 inflection, 0 unknown
   * - descent / ascent split
     - at the pressure maximum
     - at the glider's apogee (state table, or the G&C event that moves the VBD to zero)
   * - bottom of the dive
     - descent to the pressure maximum, then ascent
     - inflection (the apogee); the deepest sample can fall in the first ascent data points
   * - end of the climb
     - ascent
     - ascent through the surface coast (the OG1 table does not name it), then surfacing from
       begin surface
   * - GPS fixes
     - the first two 3, the last one ascent
     - every fix 3
   * - data type
     - byte, ``_FillValue`` 127
     - byte, ``_FillValue`` 0
   * - attributes
     - ``phase_vocabulary``
     - also ``flag_values``, ``flag_meanings``, ``phase_calculation_method``,
       ``phase_calculation_method_vocabulary``

Code that selects profiles with ``PHASE == 2`` / ``PHASE == 1`` still works, but the apogee
samples (5) are no longer in either. To keep every sample, split
each dive at its inflection, or at its deepest sample as 0.2.0 did.

xarray reads ``PHASE`` with its ``_FillValue`` 0 as missing, so ``PHASE`` 0 (unknown) comes back
as NaN; ``xr.open_dataset(..., mask_and_scale=False)`` or ``ds.PHASE.fillna(0)`` keeps the 0.

``PROFILE_NUMBER``
   Now from ``PHASE``, as OG1 defines it: one number per run of descent or ascent, -9999 on
   every other data point (surfacing, inflection). 0.2.0 split each dive at the pressure maximum,
   numbered the halves 2n-1 and 2n from the dive number, and gave every data point a number.
   ``tools.add_profile_number`` (and its old name ``assign_profile_number``), which did that, is
   removed: call ``tools.add_phase``, then ``tools.add_profiles``.
``PROFILE_DIRECTION``, ``SEGMENT_NUMBER``
   New (OG1): 1/-1/0 for descent/ascent/other, and +1 each time the glider enters surfacing.
``dive_number``
   Renamed from ``DIVE_NUMBER``: it is the Seaglider's dive number, not an OG1 variable, so
   it is written in lower case like the other non-OG1 variables.
``PHASE_QC``
   0 (no QC performed) on every data point, with the OG1 flag scale 0–4 as ``flag_values`` and
   ``flag_meanings``. 0.2.0 wrote 0 with no flag attributes.

Salinity: no ``SA`` or ``CT``
-----------------------------

Files carry practical salinity (``PSAL``) only, as TEOS-10 recommends archiving. 0.2.0 renamed a
basestation file's ``absolute_salinity`` and ``conservative_temperature`` to ``SA`` and ``CT``;
they now pass through under those names, with the basestation's own attributes (for example
``units = "g/kg"``, no ``standard_name``). ``POTDENS0`` is still written (computed with TEOS-10).
Compute SA and CT when you need them:

.. code-block:: python

   import gsw

   SA = gsw.SA_from_SP(ds.PSAL, ds.PRES, ds.LONGITUDE, ds.LATITUDE)
   CT = gsw.CT_from_t(SA, ds.TEMP, ds.PRES)

Variable attributes
-------------------

* ``uri`` is renamed ``vocabulary`` (OG1's name); read ``vocabulary``. See
  :doc:`variable_vocabulary`.
* Every variable on ``N_MEASUREMENTS`` carries ``coordinates = "TIME LONGITUDE LATITUDE DEPTH"``.
* Units are written in one canonical spelling on every variable, including those that keep
  their basestation names (``g kg-1``, ``kg m-3``, ``degree_Celsius``, ``m``, ``degree``). A
  passed-through variable in ``cm/s`` is converted to ``m s-1``, with ``original_units`` and a
  ``conversion_units`` entry. Spellings the converter does not recognise are left as written.

Basestation 2.10 files
----------------------

Files whose ``gc_state_secs`` are seconds from the dive start (basestation 2.10) no longer put
data points in January 1970. Their output name and ``time_coverage_start`` change from
``sg033_19700101T000012_R`` to the dive's real start, for example ``sg033_20100903T181710_R``.

Sensor serial numbers and calibration dates
-------------------------------------------

Serial numbers and calibration dates are read from the calibration comments by named rules
(see :doc:`calibration_comments`); files differ from 0.2.0 wherever the old parser was wrong.

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - sample
     - 0.2.0 wrote
     - 0.3.0
   * - sg005 CTD (``SBE 24520-1 calibration 04FEB08``)
     - ``SENSOR_CTD_245201``
     - ``SENSOR_CTD_24520-1``
   * - sg005 WET Labs (no comment)
     - ``SENSOR_FLUOROMETER_0000``, date ``00-00-0000``
     - ``SENSOR_FLUOROMETER_UNK``, date ``UNK``

* A serial or date that cannot be read is ``UNK``; ``0000``, ``00-00-0000``, ``0000-00-00``,
  ``Format Error`` and ``None Found`` are no longer written.
* Two-number dates are read by separator: slashes month-first (``9/10/08`` → 10 September),
  dots and dashes day-first (``12.05.2012`` → 12 May). 0.2.0 read every such date day-first.
* New on each ``SENSOR_*``: ``original_calibcomm`` (the comment as written) and, for
  multi-channel instruments, ``sensor_calibration_dates``. New global:
  ``conversion_sensor_calibration``.
* ``sensors.<key>.calibration_date`` in ``mission.yaml`` must be an ISO date (``YYYY-MM-DD``).

Removed names
-------------

The pre-0.1.0 names that warned or raised through 0.1.x and 0.2.x are removed. Using one gives
Python's ordinary ``AttributeError`` (``ImportError`` for ``from ... import``); :doc:`migrating_0_1_0` gives each one's replacement:

* ``readers``: ``load_basestation_files``, ``load_first_basestation_file``,
  ``scan_and_repair_files``, ``repair_netcdf_time_metadata_inplace``, ``profnum_from_filename``,
  ``glider_sn_from_filename``, ``load_sample_dataset``;
* ``writers``: ``save_dataset``;
* ``tools``: ``calc_Z``, ``assign_phase``, ``reformat_units_str``, ``reformat_units_var``,
  ``convert_units_var``, ``OG1_name_mapping``, ``print_OG1_mapping_summary`` and the pipeline
  internals (``og1_name_mapping``, ``gather_sensor_info``, ``add_sensor_to_dataset``,
  ``merge_datasets_along_time``, ``extract_scalar_parameters``, ``add_scalar_parameters``,
  ``set_best_dtype``);
* ``contributors``: ``registry_institutions``, ``normalize_orcid``, ``normalize_role``;
* ``vocabularies``: ``load_default_contributors``, ``contrib_to_append``, ``unit_str_format``,
  ``unit1_to_unit2``, ``preferred_units``;
* the ``convertOG1`` module;
* ``plotters.show_*`` no longer accept a file path: pass an open dataset.

``tools.add_profile_number`` (and its old name ``assign_profile_number``) is also removed; see
``PROFILE_NUMBER`` above.
