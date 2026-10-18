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
     - ``2``
     - Schema version; a missing value warns and assumes ``1``. Version 2 adds the
       ``deployment`` block and the optional platform variables. A version 1 file still
       converts.
   * - ``source``
     - str
     - *(required)*
     - A mission directory holding ``pSSSDDDD*.nc``, or a root of ``SN/DATE`` directories.
       The only key required at the top level, but ``validate`` also enforces a ``PI``
       contributor and an ``Operator`` institution (see those rows). Checked to exist and to
       hold basestation files.
   * - ``output_dir``
     - str
     - ``./``
     - Where OG1 files are written.
   * - ``mode``
     - str
     - ``delayed``
     - ``realtime`` or ``delayed``; sets the id data-mode suffix (``R`` or ``delayed``).
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
     - Run ``repair_files`` on the basestation files before loading (writes the source tree).
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
   * - ``deployment``
     - mapping
     - *(see below)*
     - OG1 deployment-identity globals (``id``, ``program``, ``license``, ``doi``, ...), one
       key per global, written when set and skipped when null. ``validate`` errors on an
       unknown key.
   * - ``global_attributes``
     - mapping or null
     - ``null``
     - Verbatim escape hatch written into the OG1 file (null values are skipped). You may not
       set keys the converter derives (``time_coverage_start``/``_end``, the ``geospatial_*``
       bounds, ``date_created``, ``start_date``) or keys with a structured home in
       ``deployment`` (``id``, ``program``, ...); ``process`` raises a ``ValueError`` if you do.
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

Within ``platform``, these fields are **required** (a null is a ``validate`` error) — fill them
by hand or let ``init --from DIR`` read them from the first basestation file:

* ``PLATFORM_SERIAL_NUMBER`` (from ``platform_id``)
* ``PLATFORM_MODEL``
* ``PLATFORM_DEPTH_RATING``
* ``PLATFORM_MAKER``

These are optional: ``GLIDER_FIRMWARE_VERSION`` (from ``seaglider_software_version``),
``LANDSTATION_VERSION`` (from ``base_station_version``), ``WMO_IDENTIFIER`` (from
``wmo_identifier``), and ``platform_model_vocabulary``.

Also optional, written as OG1 variables only when you set them (a null is not written):
``PLATFORM_NAME``, ``TELECOM_TYPE``, ``TRACKING_SYSTEM``, ``BATTERY_TYPE``, ``BATTERY_PACK``,
and ``platform_maker_vocabulary`` (attached to ``PLATFORM_MAKER``).

Deployment fields
-----------------

The ``deployment`` block carries the OG1 globals that identify the deployment, one key per
global. A null key is not written; seagliderOG1 lets you supply OG1 metadata but does not
enforce the format (the external ``cc-plugin-og`` checker does that). The OG1 requirement tier
(from the manual, v1.0.0) is shown for each:

* **mandatory**: ``id`` (overrides the derived ``<serial>_<start>_<mode>``; ``init --from``
  proposes the derived value).
* **highly desirable**: ``site``, ``site_vocabulary``, ``program``, ``program_vocabulary``,
  ``data_url``, ``doi``.
* **suggested**: ``project``, ``network``, ``comment`` (overrides the comment derived from the
  file's ``history``).
* **optional** (ACDD globals with no OG1 tier): ``license``, ``acknowledgment``.

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

   config_version: 2

   source: /data/005/20080606   # mission dir (p*.nc inside) or a root of SN/DATE dirs
   output_dir: ./          # where OG1 files are written
   mode: delayed           # realtime | delayed
   dives: null             # [first, last] dive numbers; null = all files present
   repair: false           # run repair_files on the basestation files (writes the source tree)
   keep_variables: null    # optional list of science variables to keep; null = all
   report: false           # also write <id>_conversion.html beside each file

   platform:               # UPPER keys -> variables, lower keys -> attributes
     PLATFORM_SERIAL_NUMBER: sg005   # required -> variable; from platform_id
     PLATFORM_MODEL: University of Washington Seaglider M1 glider   # required -> variable
     platform_model_vocabulary: null   # optional -> attribute on PLATFORM_MODEL
     PLATFORM_DEPTH_RATING: 1000   # required -> variable; metres
     PLATFORM_MAKER: University of Washington School of Oceanography   # required -> variable
     platform_maker_vocabulary: null   # optional -> attribute on PLATFORM_MAKER
     GLIDER_FIRMWARE_VERSION: null   # optional -> variable; from seaglider_software_version
     LANDSTATION_VERSION: null   # optional -> variable; from base_station_version
     WMO_IDENTIFIER: null   # optional -> variable; from wmo_identifier
     PLATFORM_NAME: null   # optional -> variable
     TELECOM_TYPE: null   # optional -> variable
     TRACKING_SYSTEM: null   # optional -> variable
     BATTERY_TYPE: null   # optional -> variable
     BATTERY_PACK: null   # optional -> variable

   deployment:             # each key -> a global attribute; null = not written
     id: null              # mandatory -> global attribute; overrides the derived id
     site: null            # highly desirable -> global attribute
     site_vocabulary: null # highly desirable -> global attribute
     program: null         # highly desirable -> global attribute
     program_vocabulary: null  # highly desirable -> global attribute
     data_url: null        # highly desirable -> global attribute
     doi: null             # highly desirable -> global attribute
     project: null         # suggested -> global attribute
     network: null         # suggested -> global attribute
     comment: null         # suggested -> global attribute
     license: null         # optional -> global attribute
     acknowledgment: null  # optional -> global attribute

   global_attributes: {}   # verbatim escape hatch for any OG1 global without a home above

   contributors:           # one entry per person per role; at least one PI
     - name: Jane Doe       # no commas in a name
       email: jane@example.org
       orcid: null          # bare ORCID or full https://orcid.org/ URL
       role: PI

   institutions:           # at least one with role Operator
     - name: Your Institution
       role: Operator
       id: null             # EDMO/ROR URL; null to resolve by name against the registry
