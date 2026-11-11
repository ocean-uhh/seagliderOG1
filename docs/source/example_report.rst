.. _example_report:

Example report
==============

`Open the example report <_static/demo/index.html>`__ — the pages ``seagliderOG1 process
--report`` writes beside the OG1 file for the bundled sg271 sample (Drygalski Trough, three
dives; see :ref:`demo`), rebuilt on every docs build. It opens on the Conversion page; the nav
at the top of each page reaches the others.

- `Conversion <_static/demo/sg271_20260302T193828_R_conversion.html>`__ — the summary: what
  went in, what came out, what was lost, and anything to check in ``mission.yaml``.
- `Variables <_static/demo/sg271_20260302T193828_R_variables.html>`__ — every variable,
  basestation input beside OG1 output, searchable and filterable.
- `Processing <_static/demo/sg271_20260302T193828_R_processing.html>`__ — every step of the
  conversion, in the order it ran.
- `Phase <_static/demo/sg271_20260302T193828_R_phase.html>`__ — how ``PHASE`` was assigned.
- `Basestation <_static/demo/sg271_20260302T193828_R_basestation.html>`__ — the dive files as
  read, across the mission.
- `OG1 format <_static/demo/sg271_20260302T193828_R_og1.html>`__ — the OG1 file: conformance
  and inventory.

What each page shows is in :ref:`conversion_page`. To make the report yourself, from any
directory::

   seagliderOG1 init --example        # writes sg271.yaml pointing at the packaged dives
   seagliderOG1 process sg271.yaml    # writes the OG1 file and the report pages beside it
