.. _package_layout:

Package layout and defaults
===========================

Where the code and the built-in defaults live. The user's own configuration is a
``mission.yaml`` (see :ref:`mission_yaml`); everything on this page is internal to the package.

Modules
-------

* ``readers.py`` — read basestation files from a server or a local directory.
* ``convert.py`` — ``to_og1`` orchestrates mapping, standardisation, concat and the
  single post-concat dtype pass.
* ``writers.py`` — write OG1 files.
* ``tools.py`` — user-facing utilities (the conversion internals and validation
  helpers live in a private module).
* ``vocabularies.py`` — vocabulary and mapping tables (the defaults; see below).
* ``plotters.py`` — plotting. ``contributors.py`` — contributor/institution record handling.
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

To change what the conversion writes, edit these — not a copy in ``mission.yaml``. The
``mission.yaml`` carries only the per-deployment metadata (platform, contributors, institutions,
source and range).
