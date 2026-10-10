.. _mission_yaml:

mission.yaml reference
======================

The mission configuration (``mission.yaml``) lives with your data, not inside the package, so
platform, contributor and global-attribute metadata belong to you rather than to seagliderOG1.
``init`` writes a commented template; ``validate`` checks it; ``process`` reads it. Paths in it
resolve relative to the file.

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
     - ``1``
     - Schema version; a missing value warns and assumes ``1``.
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
     - Run ``scan_and_repair`` on the basestation files before loading (writes the source tree).
   * - ``keep_variables``
     - list or null
     - ``null``
     - Science variables to keep; ``null`` keeps all.
   * - ``platform``
     - mapping
     - *(see below)*
     - OG1 platform fields. The required fields must be non-null when a platform block is
       present.
   * - ``global_attributes``
     - mapping or null
     - ``null``
     - Written into the OG1 file (null values are skipped). You may not set keys the converter
       derives (``id``, ``time_coverage_start``/``_end``, the ``geospatial_*`` bounds,
       ``date_created``, ``start_date``); ``process`` raises a ``ValueError`` if you do.
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

   config_version: 1

   source: /data/005/20080606   # mission dir (p*.nc inside) or a root of SN/DATE dirs
   output_dir: ./          # where OG1 files are written
   mode: delayed           # realtime | delayed
   dives: null             # [first, last] dive numbers; null = all files present
   repair: false           # run scan_and_repair on the basestation files (writes the source tree)
   keep_variables: null    # optional list of science variables to keep; null = all

   platform:               # 'init --from' fills these; fill any null before validate
     PLATFORM_SERIAL_NUMBER: sg005   # from platform_id; a serial or a local nickname
     PLATFORM_MODEL: University of Washington Seaglider M1 glider
     platform_model_vocabulary: null   # e.g. NERC B76 B7600024 (Seaglider)
     PLATFORM_DEPTH_RATING: 1000   # metres
     PLATFORM_MAKER: University of Washington School of Oceanography
     GLIDER_FIRMWARE_VERSION: null   # from seaglider_software_version
     LANDSTATION_VERSION: null   # from base_station_version
     WMO_IDENTIFIER: null   # from wmo_identifier

   global_attributes:      # written verbatim into the OG1 file
     project: null
     program: null
     title: null

   contributors:           # one entry per person per role; at least one PI
     - name: Jane Doe       # no commas in a name
       email: jane@example.org
       orcid: null          # bare ORCID or full https://orcid.org/ URL
       role: PI

   institutions:           # at least one with role Operator
     - name: Your Institution
       role: Operator
       id: null             # EDMO/ROR URL; null to resolve by name against the registry
