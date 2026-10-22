.. _quickstart:

Getting started
===============

Install
-------

.. code-block:: bash

   pip install seagliderOG1

Or the latest development version from source:

.. code-block:: bash

   pip install git+https://github.com/ocean-uhh/seagliderOG1.git

For a development install, see ``CONTRIBUTING.md`` in the repository.

Convert a mission
-----------------

The command-line interface converts one mission with three steps: write a configuration
template from the first basestation file, check it, then convert.

.. code-block:: console

   $ seagliderOG1 draft --raw-dir /data/005/20080606             # optional: a draft page, no config
   $ seagliderOG1 init sg005.yaml --raw-dir /data/005/20080606   # template from the first file
   $ seagliderOG1 validate sg005.yaml                            # config, raw_dir, dive range
   $ seagliderOG1 process  sg005.yaml                            # -> <output_dir>/<id>.nc

``init`` fills the platform block from the basestation file; open ``sg005.yaml`` and complete
the contributor and institution records before ``validate``. For a root of ``SN/DATE`` mission
directories, point ``raw_dir`` at the root and select with ``--all`` or ``--mission GLOB``; ``-n``
previews without writing. Paths in ``sg005.yaml`` resolve relative to the file. See
:ref:`mission_yaml` for every key and :ref:`cli_reference` for every flag.

A filled-in example ships inside the package: ``seagliderOG1 init --example`` writes
``sg271.yaml`` pointing at the bundled sg271 dives, and ``seagliderOG1 process sg271.yaml``
writes the OG1 file and its conversion page to ``outputs/`` (see :ref:`demo`).

From Python
-----------

One call does what ``process`` does for one mission — read, convert, write
``<output_dir>/<id>.nc`` — taking the ``mission.yaml`` as its only argument and returning the
path written:

.. code-block:: python

   import seagliderOG1 as sg

   path = sg.process("sg005.yaml", overwrite=True, report=True)

To inspect or adjust the configuration before converting, load it, change a value and pass the
mapping:

.. code-block:: python

   import seagliderOG1 as sg

   cfg = sg.mission.load("sg005.yaml")
   cfg["rights_and_access"]["doi"] = "10.5281/zenodo.0000000"
   path = sg.process(cfg, overwrite=True)

``process`` takes ``output_dir``, ``dives``, ``mode``, ``report`` and ``report_dir`` as keyword
overrides of the configuration, and raises ``FileExistsError`` rather than overwrite unless
``overwrite=True``.

Step by step
^^^^^^^^^^^^

The same pipeline as separate calls, for when you want the dataset in hand before writing:

.. code-block:: python

   import seagliderOG1 as sg

   cfg = sg.mission.load("sg005.yaml")
   ds = sg.convert(sg.read(cfg["raw_dir"], dives=cfg.get("dives")), cfg)
   out = sg.write(ds, "output/out.nc", overwrite=True)
   sg.report(out)

The worked example in :doc:`the demo notebook <demo-output>` runs this end to end on the
bundled ``sg271`` sample data.
