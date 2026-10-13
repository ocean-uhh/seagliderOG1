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

   $ seagliderOG1 init --from /data/005/20080606 -o sg005.yaml   # template from the first file
   $ seagliderOG1 validate sg005.yaml                            # config, source, dive range
   $ seagliderOG1 process  sg005.yaml                            # -> <output_dir>/<id>.nc

``init`` fills the platform block from the basestation file; open ``sg005.yaml`` and complete
the contributor and institution records before ``validate``. For a root of ``SN/DATE`` mission
directories, point ``source`` at the root and select with ``--all`` or ``--mission GLOB``; ``-n``
previews without writing. Paths in ``sg005.yaml`` resolve relative to the file. See
:ref:`mission_yaml` for every key and :ref:`cli_reference` for every flag.

From Python
-----------

.. code-block:: python

   from seagliderOG1 import convertOG1, readers, writers

   datasets = readers.load_basestation_files(source, first, last)
   ds, _ = convertOG1.convert_to_OG1(
       datasets,
       contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
       institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
   )
   writers.save_dataset(ds, out)

The worked example in :doc:`the demo notebook <demo-output>` runs this end to end on the
bundled ``sg005`` sample data.
