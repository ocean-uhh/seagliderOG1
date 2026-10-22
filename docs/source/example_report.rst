.. _example_report:

Example report
==============

The HTML conversion report for the bundled sg271 sample — the page ``seagliderOG1 process
--report`` writes beside each OG1 file. It checks the configuration against the data, lists the
OG1 variables present and absent, names each basestation variable's fate, and shows the scalar
parameters and global attributes. This one is the sg271 Drygalski Trough sample (three dives, see
:ref:`demo`), rebuilt on every docs build.

.. raw:: html

   <iframe src="_static/demo/conversion.html" title="sg271 conversion report"
           width="100%" height="900" style="border: 1px solid #ccc;"></iframe>

To make it yourself, from any directory::

   seagliderOG1 init --example        # writes sg271.yaml pointing at the packaged dives
   seagliderOG1 process sg271.yaml    # writes the OG1 file and this page beside it
