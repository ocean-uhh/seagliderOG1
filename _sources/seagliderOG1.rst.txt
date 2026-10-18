:mod:`seagliderOG1 API`
-----------------------

At a glance, in pipeline order:

- ``convert.process_mission`` — the whole pipeline for one mission: read, convert, write
  (and optionally the HTML conversion page). The calls below are its steps.
- ``readers.read_mission`` — read a mission's basestation files into a list of datasets.
- ``convert.to_og1`` — convert that list into one OG1 dataset.
- ``convert.keep_variables`` — optionally subset to a science-variable allow-list.
- ``writers.write`` — write the OG1 dataset to netCDF.
- ``tools.add_depth`` / ``add_phase`` / ``add_profile_number`` — add derived variables.
- ``plotters.plot_*`` / ``plotters.show_*`` — quick-look figures and text tables.
- ``vocabularies`` and ``contributors`` — the metadata vocabularies and contributor/institution records.

convert
=======
.. automodule:: seagliderOG1.convert
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
