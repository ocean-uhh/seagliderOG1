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

Where to add or change a unit
-----------------------------

The unit definitions below are **package-level**: they live in the package and apply to every file
of a given basestation version, so adding one needs a change to seagliderOG1 and a release. (The
tables further down are the data these produce, not where you change it.) The factor itself is
applied in ``seagliderOG1._convert`` from the ``(canonical, factor)`` that ``vocabularies.UNITS``
resolves, so adding a row is all a new spelling needs — no code change.

* A **wrong label** — a basestation units string that is wrong for the magnitude the values hold
  (density written ``g/m^3`` for kg m⁻³ values; ``glide_angle`` written ``cm/s`` for degrees): add a
  row keyed by the basestation variable to
  `OG1_unit_corrections.yaml
  <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_unit_corrections.yaml>`_.
* An **accepted spelling and its factor** — a source spelling that resolves to a canonical one
  (``S/m`` → ``mS cm-1``, ×10; ``cm/s`` → ``m s-1``, ×0.01; ``micrograms/liter`` → ``mg m-3``, ×1):
  add a row to the ``UNITS`` view in
  `vocabularies.py
  <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/vocabularies.py>`_. The view
  layers the package rows over the shared family tables in
  `reports/_vendored/units_tables.py
  <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/reports/_vendored/units_tables.py>`_,
  which are vendored byte-for-byte from ctdcast — edit those upstream and re-vendor, not here.
* The **canonical units of an OG1 variable** (the target spelling a source resolves to): the
  variable's ``units`` in
  `OG1_variable_attributes.yaml
  <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_variable_attributes.yaml>`_.
* Which **basestation variable maps to which OG1 variable** (add a mapping, or remove a
  wrong-quantity one so the source passes through under its own name):
  `OG1_variable_names.yaml
  <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_variable_names.yaml>`_.

**Mission-level**, in your own ``mission.yaml`` with no change to the package:

* **Leave a variable out** whose units you cannot use (for example one that is refused, or a
  wrong-quantity pass-through): list it under ``drop_variables`` (see :ref:`mission_yaml`).
* **Correct a wrong label on one variable** with a ``unit_corrections:`` block keyed by the
  basestation variable name: ``to`` is the label to write, ``from`` is the label as written
  (``null`` for an unlabelled source). It is applied before conversion, in origin terms, and
  layered over the package ``OG1_unit_corrections.yaml`` so a mission entry wins on a shared key.
  Use it for a one-off mislabel on this mission; the package file carries the systematic,
  cross-mission defects. The ``to`` spelling must be one the OG1 target resolves (an alias in
  ``UNITS`` or the target's own units) — a genuinely new spelling is still a package-level change
  above. A fleet-wide overlay (the reserved ``local_config`` key) is not yet available.

The tables below are regenerated on every docs build from the two bundled samples (sg005,
basestation 2.8; sg271, basestation 3.0.6), so they always match the code.

.. raw:: html

   <iframe src="_static/units/units_mapping.html" title="Unit mapping by variable"
           width="100%" height="900" style="border: 1px solid #ccc;"></iframe>
