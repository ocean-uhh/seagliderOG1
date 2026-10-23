.. _units_mapping:

Unit mapping
============

Every OG1 variable has a canonical units spelling, set in ``config/OG1_variable_attributes.yaml``
(for example ``mS cm-1`` for conductivity, ``m s-1`` for velocities, ``degree_Celsius`` for
temperature). A basestation file may label the same quantity differently (``S/m``, ``cm/s``,
``degrees_Celsius``), so the converter resolves each source spelling to the canonical one through
the shared units tables (``seagliderOG1.vocabularies.UNITS``) and applies a factor where the units
differ in size. An unknown spelling is **refused** (``UnitsError``) rather than written with a
wrong or unchecked label.

What the converter does to a variable's units, in order:

- **unchanged** — the source is already the OG1 spelling; nothing happens.
- **relabel** — the same quantity in a different spelling (``degrees_Celsius`` → ``degree_Celsius``);
  the units string is rewritten to the canonical one, the values are unchanged (factor 1).
- **convert** — the units differ in size (``S/m`` → ``mS cm-1``, ×10; ``cm/s`` → ``m s-1``, ×0.01);
  the values are multiplied by the factor and ``original_units`` records the source label.
- **label correction** — the basestation label is wrong for the magnitude the values hold
  (``g/m^3`` for kg m⁻³ density); corrected before conversion, recorded in ``original_units`` and
  ``comment`` (see :ref:`conversion`).
- **no source units** — the source variable has no ``units``; the OG1 label is adopted unchanged.
- **wrong-quantity** — the source is a different quantity from the OG1 variable (per-mass versus
  per-volume oxygen); the mapping is removed and the variable passes through under its basestation
  name, with a drop recommendation on the conversion page.

The tables below are regenerated on every docs build from the two bundled samples (sg005,
basestation 2.8; sg271, basestation 3.0.6), so they always match the code.

.. raw:: html

   <iframe src="_static/units/units_mapping.html" title="Unit mapping by variable"
           width="100%" height="900" style="border: 1px solid #ccc;"></iframe>
