.. _demo:

Demo: the sg271 sample
======================

The package ships one short Seaglider mission inside the wheel, so the conversion runs end to end
from a ``pip install`` — nothing to download.

The sample
----------

``sg271`` is a University of Washington Seaglider (model SGX), operated by the University of
Hamburg. The bundled sample is three dive-climb cycles — ``p2710001``–``p2710003`` — from the
PycnMix deployment in the Drygalski Trough (Ross Sea, Antarctica). The glider went in the water at
19:24 UTC on 2 March 2026, at 72°58.8′S, 171°24.5′E. The principal investigator is Eleanor
Frajka-Williams. The three dives are released for demonstration under CC-BY-4.0; the full mission
dataset is embargoed.

Run it
------

``init --example`` writes the sample's configuration with ``raw_dir`` pointing at the packaged
dives; ``process`` then converts them and writes the OG1 file and its report into your current
directory:

.. code-block:: console

   $ seagliderOG1 init --example        # writes ./sg271.yaml
   $ seagliderOG1 process sg271.yaml    # writes the OG1 file and its conversion page

The output is ``sg271_20260302T193828_R.nc`` with ``sg271_20260302T193828_R_conversion.html``
beside it. The hosted copy of that report is :ref:`example_report`; the same run as an executed
notebook is :doc:`the demo notebook <demo-output>`.

From Python, ``readers.load_sample_basestation()`` returns the first dive of this sample as an
xarray dataset, and ``readers.sample_mission_dir()`` gives the packaged directory.
