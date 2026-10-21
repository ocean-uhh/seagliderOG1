.. _quickstart:

Getting started
===============

Install
-------

.. note::

   Until ``0.1.0`` is published to PyPI, install from source — the version on PyPI
   (``0.0.2``) has no command-line interface.

From source:

.. code-block:: bash

   pip install git+https://github.com/ocean-uhh/seagliderOG1.git

Once ``0.1.0`` is on PyPI:

.. code-block:: bash

   pip install seagliderOG1

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

A filled-in example for the bundled sample ships as ``data/demo_sg005/mission.yaml``; from the
repository root, ``seagliderOG1 process data/demo_sg005/mission.yaml --report`` writes the OG1
file and its conversion page to ``outputs/``.

From Python
-----------

One call does what ``process`` does for one mission — read, convert, write
``<output_dir>/<id>.nc`` — and returns the path written:

.. code-block:: python

   from seagliderOG1 import convert

   path = convert.process_mission(
       "/data/005/20080606",
       "output",
       contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
       institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
       report=True,  # also write output/<id>_conversion.html
   )

It takes ``dives``, ``platform``, ``deployment`` (one mapping of the identity, rights and
provenance globals the ``mission.yaml`` sections split apart), ``global_attributes``, ``mode``,
``keep_variables`` and ``repair`` as keyword arguments, and raises ``FileExistsError`` rather
than overwrite unless ``overwrite=True``.

Step by step
^^^^^^^^^^^^

The same pipeline as three calls, for when you want the dataset in hand before writing:

.. code-block:: python

   from seagliderOG1 import convert, readers, writers

   datasets = readers.read_mission(source, first, last)
   ds = convert.to_og1(
       datasets,
       contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
       institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
   )
   writers.write(ds, out)

The worked example in :doc:`the demo notebook <demo-output>` runs this end to end on the
bundled ``sg005`` sample data.
