.. _defaults:

Packaged defaults and your local tables
=======================================

The package ships default tables — the OG1 mappings and vocabularies — that are not user
configuration. The user's own configuration is a ``mission.yaml`` (see :ref:`mission_yaml`);
this page is the packaged defaults and how to override them.

Built-in defaults
-----------------

Defaults live in two places, neither of which is user configuration.

Packaged YAML (``seagliderOG1/config/``), read once when ``vocabularies`` is imported, not per
conversion (each links to its current version on GitHub, so an installed user can read it without
the source):

* `OG1_variable_names.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_variable_names.yaml>`_
  — basestation → OG1 variable name mappings.
* `OG1_sensor_names.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_sensor_names.yaml>`_
  — sensor keys (``sbe41``, ``wlbb2f``) → ``OG1_sensor_attributes.yaml`` entries; a lookup, never a
  variable rename.
* `OG1_variable_attributes.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_variable_attributes.yaml>`_
  — CF/OG1 variable attributes (``standard_name``, ``long_name``, ``units``).
* `OG1_sensor_attributes.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_sensor_attributes.yaml>`_
  — sensor metadata.
* `OG1_global_attributes.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/OG1_global_attributes.yaml>`_
  — global attribute templates (for example ``featureType``).
* `institution_registry.yaml <https://github.com/ocean-uhh/seagliderOG1/blob/main/seagliderOG1/config/institution_registry.yaml>`_
  — EDMO codes for resolving institutions by name.

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
(a pip install puts them under ``site-packages``, and an edit is lost on upgrade). The
``mission.yaml`` carries only the per-deployment metadata (platform, contributors, institutions,
raw_dir and range), not a copy of these.

.. tip::

   A future release will add a fleet-level configuration file (``fleet.yaml``) for overriding these
   packaged tables without an editable checkout. Until then, changing a mapping means working from a
   source checkout.
