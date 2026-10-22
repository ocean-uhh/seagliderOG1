.. _package_layout:

Package layout and defaults
===========================

Where the code and the built-in defaults live. The user's own configuration is a
``mission.yaml`` (see :ref:`mission_yaml`); everything on this page is internal to the package.

Modules
-------

* ``__init__.py`` — the public verbs (``read``, ``convert``, ``write``, ``report``,
  ``enrich``, ``process``, ``process_missions``), re-exported from the modules below.
* ``readers.py`` — ``read`` basestation files from a server or a local directory.
* ``_convert.py`` — ``convert`` orchestrates mapping, standardisation, concat and the
  single post-concat dtype pass; ``process`` / ``process_missions`` run the pipeline from a
  configuration. Private: not imported directly.
* ``writers.py`` — ``write`` OG1 files and ``enrich`` a written file's globals.
* ``mission.py`` — the ``mission.yaml`` schema: ``load``, ``check``.
* ``tools.py`` — user-facing utilities.
* ``vocabularies.py`` — vocabulary and mapping tables (the defaults; see below).
* ``plotters.py`` — plotting. ``contributors.py`` — contributor/institution record handling.
* ``reports/`` — the HTML conversion page (``report``) and the reader behind it.
* ``cli/`` — the ``seagliderOG1`` command, one module per verb.
* ``config/*.yaml`` — the OG1 mappings and vocabularies (see below).

Built-in defaults
-----------------

Defaults live in two places, neither of which is user configuration.

Packaged YAML (``seagliderOG1/config/``), loaded at conversion time:

* ``OG1_variable_names.yaml`` — basestation → OG1 variable name mappings.
* ``OG1_sensor_names.yaml`` — sensor keys (``sbe41``, ``wlbb2f``) → ``OG1_sensor_attributes.yaml``
  entries; a lookup, never a variable rename.
* ``OG1_variable_attributes.yaml`` — CF/OG1 variable attributes (``standard_name``, ``long_name``,
  ``units``).
* ``OG1_sensor_attributes.yaml`` — sensor metadata.
* ``OG1_global_attributes.yaml`` — global attribute templates (for example ``featureType``).
* ``institution_registry.yaml`` — EDMO codes for resolving institutions by name.

Tables in ``vocabularies.py``:

* ``DIMENSION_RENAMES`` — dimension renaming (``sg_data_point`` → ``N_MEASUREMENTS``).
* ``MODE_SUFFIX`` — data mode to id suffix (``realtime`` → ``R``, ``delayed`` → ``delayed``).
* ``PLATFORM_FIELDS`` — the OG1 platform fields with their source attribute, formatter and
  required flag.
* ``preferred_units``, ``unit_str_format``, ``unit1_to_unit2`` — unit standardisation and the
  conversion factors.
* ``VARIABLES_TO_DROP`` — basestation variables dropped from the OG1 output; empty, so every
  basestation variable is retained.
* ``ROLE_VOCABULARY``, ``ROLE_ALIASES`` — the W08 contributor roles and the accepted aliases.

These are the packaged defaults, read-only for an installed package — do not edit them in place
(a pip install puts them under ``site-packages``, and an edit is lost on upgrade). A local-override
mechanism (``local_config``) is planned; until it lands, changing the mappings means an editable
checkout. The ``mission.yaml`` carries only the per-deployment metadata (platform, contributors,
institutions, raw_dir and range), not a copy of these.
