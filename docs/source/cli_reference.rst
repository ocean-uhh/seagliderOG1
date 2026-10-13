.. _cli_reference:

CLI reference
=============

The ``seagliderOG1`` command converts Seaglider basestation files to OG1 with one subcommand
per verb. The typical workflow is ``init`` → ``validate`` → ``process``; ``inspect`` and
``list`` are read-only helpers.

.. code-block:: console

   $ seagliderOG1 init --from /data/005/20080606 -o sg005.yaml
   $ seagliderOG1 validate sg005.yaml
   $ seagliderOG1 process  sg005.yaml

The same entry point is available as a module:

.. code-block:: console

   $ python -m seagliderOG1.cli --help

See :ref:`mission_yaml` for the configuration file the verbs read and write.

Data mode
---------

``process --mode`` (and the ``mode`` key in ``mission.yaml``) sets the OG1 data mode, which
determines the data-mode suffix of the output id: ``realtime`` gives the suffix ``R`` and
``delayed`` gives ``delayed`` (``vocabularies.MODE_SUFFIX``).

Verbs
-----

.. argparse::
   :module: seagliderOG1.cli
   :func: build_parser
   :prog: seagliderOG1

Exit status
-----------

* ``0`` — success.
* ``1`` — a handled error (a missing file, an invalid configuration, a conversion that wrote
  nothing).
* ``2`` — a usage error (argparse: an unknown flag or a missing argument).
