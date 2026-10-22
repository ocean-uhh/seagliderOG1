.. _mission_yaml:

mission.yaml reference
======================

The mission configuration (``mission.yaml``) lives with your data, not inside the package, so
platform, contributor and global-attribute metadata belong to you rather than to seagliderOG1.
``init`` writes a commented template; ``validate`` checks it; ``process`` reads it. Paths in it
resolve relative to the file.

UPPER-case keys become OG1 variables, lower-case keys become attributes or globals; the comment
on each line of the generated template says which. Keys are case-sensitive — ``validate`` errors
on a mis-cased key (``platform_model``) and names the right spelling (``PLATFORM_MODEL``).

Keys
----

.. list-table::
   :header-rows: 1
   :widths: 22 14 14 50

   * - Key
     - Type
     - Default
     - Notes
   * - ``config_version``
     - int
     - ``3``
     - Schema version; must be ``3``. Version 3 replaced the single ``deployment`` block with
       the three global-attribute sections below. ``validate`` errors on an older version and
       names the sections; ``seagliderOG1 init`` regenerates a file.
   * - ``raw_dir``
     - str
     - *(required)*
     - The basestation files: a mission directory holding ``pSSSDDDD*.nc``, or a root of
       ``SN/DATE`` directories. ``source``, its old name, is still read with a deprecation
       warning for one release.
       The only key required at the top level, but ``validate`` also enforces a ``PI``
       contributor and an ``Operator`` institution (see those rows). Checked to exist and to
       hold basestation files.
   * - ``output_dir``
     - str
     - ``./``
     - Where OG1 files are written.
   * - ``mode``
     - str
     - ``realtime``
     - ``realtime`` or ``delayed``; sets the id data-mode suffix (``R`` or ``delayed``). A file
       is delayed mode only when the config (or ``process --mode``) says so.
   * - ``dives``
     - list or null
     - ``null``
     - ``[first, last]`` dive numbers, or ``null`` for all files present. For a single mission
       directory, checked against the files found (``validate --strict`` also requires no gaps);
       for a ``SN/DATE`` root this check is skipped — the range is applied per mission by
       ``process``.
   * - ``repair``
     - bool
     - ``false``
     - Run ``repair_files`` on the basestation files before loading (writes the raw_dir tree).
   * - ``keep_variables``
     - list or null
     - ``null``
     - Science variables to keep; ``null`` keeps all.
   * - ``report``
     - bool
     - ``false``
     - Also write the HTML conversion page ``<id>_conversion.html`` beside each file (as
       ``process --report``).
   * - ``platform``
     - mapping
     - *(see below)*
     - OG1 platform fields. The required fields must be non-null when a platform block is
       present.
   * - ``identity_and_discovery``,
       ``rights_and_access``,
       ``provenance_and_processing``
     - mapping
     - *(see below)*
     - The OG1 global attributes a mission supplies, grouped by the conversion page's
       convention groups: identity (``id``, ``naming_authority``, ``site``, ``data_url``,
       ``project``), rights (``doi``, ``license``, ``acknowledgment``) and provenance
       (``comment``). One key per global, written when set and skipped when null.
       ``validate`` errors on a key in the wrong section or an unknown one. ``program``,
       ``program_vocabulary`` and ``network`` are not here — they are per-platform facts a
       local-config overlay will supply; until it lands, set them under ``global_attributes``.
   * - ``local_config``
     - str or null
     - ``null``
     - Optional path to a directory of local config overrides. Reserved for a coming release and
       not read yet, so it must be ``null``; ``validate`` errors on a non-null value (a dropped
       override would produce a wrong file that looks right). No ``config_version`` bump when the
       feature lands — the key is already declared and optional.
   * - ``global_attributes``
     - mapping or null
     - ``null``
     - Verbatim escape hatch written into the OG1 file (null values are skipped). You may not
       set keys the converter derives (``time_coverage_start``/``_end``, the ``geospatial_*``
       bounds, ``date_created``, ``start_date``) or keys with a structured home in a section
       (``id``, ``naming_authority``, ``doi``, ...); ``validate`` reports either as an error,
       naming where the key goes. Replace the ``{}`` with an indented block:

       .. code-block:: yaml

          global_attributes:
            institution: "University of Hamburg"
   * - ``sensors``
     - mapping or null
     - ``null``
     - Corrections to a basestation sensor record, keyed by the sensor's name in the files'
       ``instrument`` global (``legato``, ``tridentebb700chla470fdom365``, ``sbe41``, ...):
       ``serial_number`` and ``calibration_date``. See `Sensor corrections`_.
   * - ``contributors``
     - list
     - *(required)*
     - One record per person per role; at least one with role ``PI``.
   * - ``institutions``
     - list
     - *(required)*
     - One record per institution per role; at least one with role ``Operator``; resolved
       against the EDMO registry.

Platform fields
---------------

A **required** field that is null is a ``validate`` error; fill it by hand, or let
``init --raw-dir DIR`` read the fields with an ``init --raw-dir reads`` entry from the first
basestation file. An optional field left null is not written. ``seagliderOG1 list platform``
prints the same table.

.. include:: _generated/platform_fields.inc

The two ``*_vocabulary`` keys take the NERC term for this glider's model (collection B76) and
maker (collection B75); the package supplies no default, because the right term depends on the
glider. For a University of Washington Seaglider M1, as in ``data/demo_sg005/mission.yaml``:
``https://vocab.nerc.ac.uk/collection/B76/current/B7600024/`` and
``https://vocab.nerc.ac.uk/collection/B75/current/ORG00142/``.

Global-attribute fields
-----------------------

The three sections ``identity_and_discovery``, ``rights_and_access`` and
``provenance_and_processing`` carry the OG1 globals a mission supplies, grouped by the
conversion page's convention groups so the key you fill names the page group it lands in. The
correspondence is one-directional: every key here appears in the matching page group, but a
page group also holds globals the converter derives or reads from ``platform:``, which have no
key here. A null key is not written; seagliderOG1 lets you supply OG1 metadata but does not
enforce the format (the external ``cc-plugin-og`` checker does that). The OG1 requirement tier
is from the manual, v1.0.0; ``optional`` marks ACDD globals with no OG1 tier.
``seagliderOG1 list globals`` lists every OG1 global, including the ones the converter derives.

.. include:: _generated/deployment_fields.inc

Sensor corrections
------------------

The serial number and calibration date of each sensor come from the basestation calibration
comments (``sg_cal_calibcomm*``, set in ``sg_calib_constants.m``). When one is wrong — a
comment copied from another instrument, or a placeholder ``0000`` — correct it here rather
than in the basestation files:

.. code-block:: yaml

   sensors:
     tridentebb700chla470fdom365:
       serial_number: "237998"
       calibration_date: 2025-03-11

The corrected serial names the ``SENSOR_*`` variable and the ``sensor`` attribute of every
variable from that instrument. The sensor variable's ``comment`` records the value each
correction replaced, so the change can be read back from the file. A key that is not one of
the mission's sensors stops the conversion with the list of keys; the conversion page's
*Sensors named by OG1* table shows the serials and dates in use.

Contributor and institution records
------------------------------------

Each entry is a mapping with a ``name`` (no commas — commas separate entries), a ``role`` from
the W08 vocabulary (``Manufacturer``, ``Owner``, ``Operator``, ``PI``, ``Technical
Coordinator``, ``Data scientist``, ``Service Provider``), and optional ``email`` and ``orcid``.
List a person once per role. ``contributors`` needs at least one ``PI``; ``institutions`` needs
at least one ``Operator``, whose ``id`` may be an EDMO/ROR URL or ``null`` to resolve by name.

Example
-------

The template ``init`` writes (fill the nulls before ``validate``):

.. code-block:: yaml

   config_version: 3

   raw_dir: /data/005/20080606  # basestation files: a mission dir (p*.nc inside) or a root of SN/DATE dirs
   output_dir: ./          # where OG1 files are written
   mode: realtime          # realtime (id suffix R) | delayed
   dives: null             # [first, last] dive numbers; null = all files present
   repair: false           # run repair_files on the basestation files (writes the raw_dir tree)
   keep_variables: null    # optional list of science variables to keep; null = all
   report: false           # also write <id>_conversion.html beside each file

   platform:               # UPPER keys -> variables, lower keys -> attributes
     PLATFORM_SERIAL_NUMBER: sg005   # required -> variable; from platform_id
     PLATFORM_MODEL: University of Washington Seaglider M1 glider   # required -> variable
     platform_model_vocabulary: null   # optional -> attribute on PLATFORM_MODEL
     PLATFORM_DEPTH_RATING: 1000   # required -> variable; metres
     PLATFORM_MAKER: University of Washington, School of Oceanography   # required -> variable
     platform_maker_vocabulary: null   # optional -> attribute on PLATFORM_MAKER
     GLIDER_FIRMWARE_VERSION: null   # optional -> variable; from seaglider_software_version
     LANDSTATION_VERSION: null   # optional -> variable; from base_station_version
     WMO_IDENTIFIER: null   # optional -> variable; from wmo_identifier
     PLATFORM_NAME: null   # optional -> variable
     TELECOM_TYPE: null   # optional -> variable
     TRACKING_SYSTEM: null   # optional -> variable
     BATTERY_TYPE: null   # optional -> variable
     BATTERY_PACK: null   # optional -> variable

   local_config: null   # optional path to a directory of local config overrides; read once the feature lands

   identity_and_discovery:   # -> global attributes
     id: null              # mandatory -> global attribute; null keeps the derived id
     naming_authority: null # highly desirable -> global attribute
     site: null            # highly desirable -> global attribute
     site_vocabulary: null # highly desirable -> global attribute
     data_url: null        # highly desirable -> global attribute
     project: null         # suggested -> global attribute

   rights_and_access:        # -> global attributes
     doi: null             # highly desirable -> global attribute
     license: null         # optional -> global attribute
     acknowledgment: null  # optional -> global attribute

   provenance_and_processing:  # -> global attributes
     comment: null         # suggested -> global attribute

   global_attributes: {}   # any other OG1 global, written as given: replace {} with lines
     #   institution: "University of Hamburg"   (a key above goes under its own block)

   contributors:           # one entry per person per role; at least one PI
     - name: Jane Doe       # no commas in a name
       email: jane@example.org
       orcid: null          # bare ORCID or full https://orcid.org/ URL
       role: PI

   institutions:           # at least one with role Operator
     - name: Your Institution
       role: Operator
       id: null             # EDMO/ROR URL; null to resolve by name against the registry
