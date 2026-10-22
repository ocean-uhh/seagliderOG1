.. _demo:

Demo: the sg005 sample
======================

The repository bundles one short Seaglider mission so the conversion can be run end to end
without downloading data: ``data/demo_sg005/``.

The sample
----------

``sg005`` (``SG005``) is a University of Washington Seaglider. The bundled mission is five
dive-climb cycles — ``p0050001``–``p0050005`` — from 6–7 June 2008, on the Iceland–Scotland
(Faroe–Iceland) Ridge in the North Atlantic. It was operated by the University of Washington
School of Oceanography; the principal investigators are Charlie Eriksen and Peter Rhines.

The mission configuration beside the files, ``data/demo_sg005/mission.yaml``, carries the
platform block, the contributor and institution records, and the output directory. It is the
file every ``seagliderOG1`` command takes.

Run it
------

The sample ships with the source repository, not the PyPI wheel, so running the demo needs a
source checkout:

.. code-block:: console

   $ git clone https://github.com/ocean-uhh/seagliderOG1
   $ cd seagliderOG1
   $ pip install -e .
   $ seagliderOG1 process data/demo_sg005/mission.yaml --report

This reads the five dive files, converts them to one OG1 file, and writes it — with its HTML
conversion page beside it — under the configuration's ``output_dir`` (``outputs/``): the OG1
file ``outputs/<id>.nc`` and the page ``outputs/<id>_conversion.html``, where ``<id>`` is
derived from the serial and the mission start.

Installed from PyPI the sample is not on disk, so to see the result without running it use the
hosted conversion page `here <_static/demo/conversion.html>`_ or :doc:`the demo notebook
<demo-output>`.
