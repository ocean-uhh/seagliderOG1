How the conversion is checked
=============================

Every change to the converter is tested against real basestation files, in four ways: three in
the test suite and one in the continuous-integration run. The expectations are tables in
``tests/data``, written to be read: a change to what the converter writes shows up as a changed
line in one of them.

The files are the bundled sg271 sample (three dives, RBR Legato CTD) and the sg005 demo (five
dives, Sea-Bird CTD). For the three checks in the test suite each is converted without a
mission file.

The written file against the raw files
--------------------------------------

Each row of ``tests/data/raw_vs_output.csv`` ties one variable of the written file back to the
raw dive files.

- **equal**: the OG1 variable equals the factor times the basestation variable, at every point
  of the basestation variable's own time axis, within the tolerance (in the OG1 units). Every
  raw point must be on the file's time axis, and no raw value may be missing in the file. The
  one exception is a GPS fix that the file records as dropped (see **gps_fixes**).
- **count**: the same number of non-missing values over the mission.
- **gps_fixes**: one ``TIME_GPS`` per raw fix, less the repeated fixes at dive boundaries that
  the file records in ``conversion_dropped_gps_fixes``.
- **missing_at_fixes**: the variable is missing, not zero, at every GPS fix.
- **no_missing_on_read**: no value reads back as missing when the file is opened.

A status starting ``known:`` marks a row that fails today and names the branch that fixes it;
the test fails when such a row starts to pass, so the marker is removed with the fix.

.. include:: _generated/raw_vs_output.inc

Names, units and sensors
------------------------

Each row of ``tests/data/og1_names.csv`` is one basestation variable that is written under an
OG1 name: the name, the units it is written in, and the ``SENSOR_*`` record it points to. A
copy numbered ``_2``, ``_3`` is checked without its number. A variable written under a new name
that the table does not list fails the tests. A row with no OG1 name says that the variable
must not be written under one. A status starting ``pending:`` marks a name that is tested as
written today and is waiting for a decision.

.. include:: _generated/og1_names.inc

The whole file against a stored reference
-----------------------------------------

``tests/data/reference/sg271.csv`` and ``sg005.csv`` hold one line per variable of the written
file: data type, dimensions, units, fill value, the number of values, and the minimum, median
and maximum. The test compares a fresh conversion with them, so any change to the output is a
line-by-line difference in a pull request. They are regenerated only for an intended change::

    SEAGLIDEROG1_UPDATE_REFERENCE=1 pytest tests/output/test_reference.py

OG1 compliance
--------------

The continuous-integration run converts the sg271 sample with the example mission file and runs
the OG1 compliance checker (``cc-plugin-og``) on it. ``tests/data/og1_known_findings.txt`` lists
the findings known today; a finding that is not in the list fails the run, and the list shrinks
as fixes land.
