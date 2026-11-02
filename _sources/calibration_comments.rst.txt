.. _calibration_comments:

How calibration comments are read
=================================

Each sensor's serial number and calibration date come from a basestation calibration comment:
a ``sg_cal_calibcomm*`` variable, set in ``sg_calib_constants.m``. The comments are typed by the
glider operator, not written by the basestation, so their format varies from mission to mission.
This page states the rules the converter uses to read them, and lists every comment it is tested
against, so you can check how yours will be read.

Where the comments come from
----------------------------

Each sensor key in the basestation ``instrument`` global is matched to a comment variable:

* ``sg_cal_calibcomm_<key>`` (for example ``sg_cal_calibcomm_coda``);
* ``sg_cal_calibcomm`` for the CTD;
* ``sg_cal_calibcomm_oxygen`` or ``sg_cal_calibcomm_optode`` for an oxygen sensor;
* ``sg_cal_calibcomm_wetlabs`` for a WET Labs sensor.

The first dive with a comment is used. When that comment gives no serial number or no date and
a later dive's comment does, without contradicting it (a different serial number, or a different
date), the value is taken from the later dive, and the sensor's ``comment`` says which file and
comment it came from. Comments that give different values on different dives
are reported in the log. In the OG1 file, the ``SENSOR_*`` variable carries:

``sensor_serial_number``
   The serial number, or ``UNK`` when it was not read.
``sensor_calibration_date``
   ISO ``YYYY-MM-DD``, or ``UNK``. For a comment with one date per channel, the latest.
``sensor_calibration_dates``
   Every channel date, ``"<channel>: <YYYY-MM-DD>"`` joined by ``"; "`` (RBR comments only).
``original_calibcomm``
   The comment exactly as written in the basestation file.

The ``conversion_sensor_calibration`` global records, per ``SENSOR_*`` variable, the basestation
variable the comment came from, the serial and date rules that read it, and any note. The
:ref:`conversion page <conversion_page>` shows these in its *Calibration comments* table.

Serial number
-------------

The rules are tried in this order; the first that matches is used. The serial is kept as an
identifier: letters and dashes are not removed (``25281-1``, ``F0012``). A model number before
the label is not the serial (``SBE 43F s/n 005`` reads ``005``).

.. include:: _generated/calibcomm_serial_rules.inc

Calibration date
----------------

The date must come directly after ``cal``, ``CAL:``, ``calibration`` or ``calibrated``; only a
serial label with its number (``SN 1234``), punctuation and the words ``on`` or ``date`` may stand
between them. A date later in the comment (``recal due 2013-08-12``) is not read, and
``calibration was done 12 Aug 2011`` gives ``UNK``.

**Dates with the year first** (``2012-05-12``, ``2012/05/12``, ``2012.05.12``) have one reading.
**Dates with the month as a word** have one reading too, with the day or the month first
(``May 12, 2012``): ``04FEB08``, ``15sep08``, ``12 Aug 01``,
``27 Feb 2025``, ``26 sept 07``, ``10 june 08``, ``24-May-17``, ``31-May-2017``. RBR comments
give one ISO date per channel (``temp15:2025-02-26T13:58:29Z doxy24:2025-03-20T11:45:16Z``).

**All-numeric dates** can have more than one reading. The converter lists the readings the
shape allows and keeps those that are calendar dates on or before the mission's first sample
and at most 30 years before it:

.. list-table::
   :header-rows: 1

   * - Shape
     - Readings
     - When more than one fits
   * - ``n/n/yy`` (slashes)
     - month first, day first
     - month first (``9/10/08`` is 10 September 2008)
   * - ``n.n.yy``, ``n-n-yy`` (dots, dashes)
     - day first, month first
     - day first (``12.05.2012`` is 12 May 2012)
   * - 8 digits
     - ``yyyymmdd``, ``ddmmyyyy``
     - ``UNK``
   * - 6 digits
     - ``ddmmyy``, ``yymmdd``
     - ``UNK``

When only one reading fits, it is used, and the note says why the other was rejected. For
example ``251114`` on a mission whose first sample is 15 August 2015 reads 25 November 2014,
because the other reading (14 November 2025) is after the first sample. When the preferred
reading is not a calendar date, the other is used (``28/4/08`` is 28 April; ``05.25.2012`` is
25 May). Check ``original_calibcomm`` when a date matters: the preference is a convention, not
something the comment says. A two-digit year takes
the latest century that does not put it after the first sample.

The first sample is the earliest ``start_time`` global across the dive files.

A comment that matches none of these gives ``UNK`` with a note. The numbers after a serial
label (``s/n``, ``SN``) are never read as a date.

Checks
------

The converter keeps what the comment says, and flags:

* a calibration date after the mission's first sample (a calibration cannot postdate the data
  it calibrated), or more than 30 years before it — in the log, in the sensor's ``comment`` and
  on the conversion page;
* two sensors with the same serial number (usually a comment copied from another instrument) —
  in the log and on the conversion page;
* a serial number read from a comment that is a single token with no label (it may be a model
  number) — on the conversion page;
* an all-numeric date with two readings, chosen by the convention above — in the log and on the
  conversion page;
* two sensors that would get the same ``SENSOR_*`` name (for example two fluorometers with no
  serial) — in the log; the second is written with its sensor key appended
  (``SENSOR_FLUOROMETER_UNK_wlbb2fl``) rather than overwriting the first.

The ``conversion_sensor_calibration`` record also stores the window (``window_years``) and the
first sample used, so the date choice can be reconstructed from the file.

A value corrected with ``sensors:`` (below) clears the flag on the conversion page.

If yours is not read correctly
------------------------------

Correct the serial number or calibration date with ``sensors:`` in ``mission.yaml`` (see
:ref:`mission_yaml`). For example, on the sg271 sample the RBR tridente comment carries the RBR
coda's serial number:

.. code-block:: yaml

   sensors:
     tridentebb700chla470fdom365:
       serial_number: "237998"

The correction replaces the serial number; ``original_calibcomm`` still holds the comment as
written. To have a new comment format read, open an issue with the comment text and what it
means; it becomes a row in the table below.

Every comment the parser is tested against
------------------------------------------

The rows below are ``tests/data/calibcomm_answers.csv``: each comment, what it means, and the
first-sample date the test uses. The expected values were read from the string, or decided by
the maintainers where the string is ambiguous.

.. include:: _generated/calibcomm_answers.inc
