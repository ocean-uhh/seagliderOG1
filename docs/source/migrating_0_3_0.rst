.. _migrating_0_3_0:

Migrating to 0.3.0
==================

.. note::

   **Draft.** 0.3.0 is not released. This page collects the changes on ``main`` since 0.2.0
   that change what a file holds or what a call accepts, and will be completed before the
   tag.

0.3.0 changes the output: reconvert your missions. Nothing on this page needs a code change
unless you read ``PHASE``, ``PHASE_QC`` or the ``SENSOR_*`` serial numbers and dates, or still
import a pre-0.1.0 name.

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
     - 1 ascent, 2 descent, 3 surfacing, 5 inflection, 7 transition, 0 unknown
   * - descent / ascent split
     - at the pressure maximum
     - at the glider's apogee (state table, or the G&C event that moves the VBD to zero)
   * - start of the dive
     - descent
     - transition, up to the last sample above ``$D_FLARE``
   * - bottom of the dive
     - descent to the pressure maximum, then ascent
     - inflection (the apogee), then transition from the end of the apogee to the deepest
       sample
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
samples (5) and the transitions (7) are no longer in either. A 7 before the inflection belongs
to the descent, a 7 after it to the climb; to keep every sample, split each dive at its
inflection, or at its deepest sample as 0.2.0 did.

xarray reads ``PHASE`` with its ``_FillValue`` 0 as missing, so ``PHASE`` 0 (unknown) comes back
as NaN; ``xr.open_dataset(..., mask_and_scale=False)`` or ``ds.PHASE.fillna(0)`` keeps the 0.

``PHASE_QC``
   0 (no QC performed) on every row, with the OG1 flag scale 0–4 as ``flag_values`` and
   ``flag_meanings``. 0.2.0 wrote 0 with no flag attributes.

Basestation 2.10 files
----------------------

Files whose ``gc_state_secs`` are seconds from the dive start (basestation 2.10) no longer put
rows in January 1970. Their output name and ``time_coverage_start`` change from
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

*To be completed with the release.* The pre-0.1.0 names that warn in 0.1.x and 0.2.x are
removed in 0.3.0; :doc:`migrating_0_1_0` gives each one's replacement.
