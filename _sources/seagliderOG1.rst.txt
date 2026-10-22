:mod:`seagliderOG1 API`
-----------------------

The public API is a set of verbs on the top-level package:

- ``seagliderOG1.read`` — read a mission's basestation files into a list of datasets.
- ``seagliderOG1.convert`` — convert that list into one OG1 dataset.
- ``seagliderOG1.write`` — write the OG1 dataset to netCDF.
- ``seagliderOG1.report`` — write the HTML conversion page for a written file.
- ``seagliderOG1.enrich`` — set global attributes on a written file, in place.
- ``seagliderOG1.process`` — load a mission configuration and run read + convert + write
  (and optionally the page) for one mission.
- ``seagliderOG1.process_missions`` — the same across a root of several missions.
- ``seagliderOG1.mission`` — load and check a ``mission.yaml`` (``mission.load`` /
  ``mission.check``).

plus the exceptions ``seagliderOG1.MissionError`` and ``seagliderOG1.MetadataError``, and the
supporting modules ``tools``, ``plotters``, ``vocabularies`` and ``contributors``.

verbs
=====
.. autofunction:: seagliderOG1.read
.. autofunction:: seagliderOG1.convert
.. autofunction:: seagliderOG1.write
.. autofunction:: seagliderOG1.report
.. autofunction:: seagliderOG1.enrich
.. autofunction:: seagliderOG1.process
.. autofunction:: seagliderOG1.process_missions

mission
=======
.. automodule:: seagliderOG1.mission
   :members:

vocabularies
============
.. automodule:: seagliderOG1.vocabularies
   :members:

contributors
============
.. automodule:: seagliderOG1.contributors
   :members:

readers
=======
.. automodule:: seagliderOG1.readers
   :members:

plotters
========
.. automodule:: seagliderOG1.plotters
   :members:

writers
=======
.. automodule:: seagliderOG1.writers
   :members:

tools
=====
.. automodule:: seagliderOG1.tools
   :members:
