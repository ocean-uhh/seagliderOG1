seagliderOG1
============

seagliderOG1 converts Seaglider basestation files (``pSSSDDDD*.nc``) into `OceanGliders OG1
format <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_. One
mission in, one OG1 file out; the platform, contributor and institution metadata come from a
``mission.yaml`` you keep with your data, never from defaults inside the package.

`Open the example report <_static/demo/index.html>`__ — the linked HTML pages a conversion
writes, for the bundled sg271 sample (three dives); see :ref:`example_report`.

For recommendations or bug reports, open an issue at
https://github.com/ocean-uhh/seagliderOG1/issues/new.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   quickstart
   demo
   demo-output.ipynb

.. toctree::
   :maxdepth: 2
   :caption: The conversion

   conversion
   phase
   calibration_comments

.. toctree::
   :maxdepth: 2
   :caption: Report

   conversion_page
   example_report

.. toctree::
   :maxdepth: 2
   :caption: Configuration

   configuration
   mission_yaml
   units_mapping
   variable_vocabulary
   defaults

.. toctree::
   :maxdepth: 2
   :caption: Reference

   cli_reference
   api

.. toctree::
   :maxdepth: 2
   :caption: Changelog / Migration

   migrating_0_3_0
   migrating_0_1_0
   changelog

.. toctree::
   :maxdepth: 1
   :caption: Links

   GitHub repository <https://github.com/ocean-uhh/seagliderOG1>

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
