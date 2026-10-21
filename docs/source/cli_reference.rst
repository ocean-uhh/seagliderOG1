.. _cli_reference:

CLI reference
=============

The ``seagliderOG1`` command converts Seaglider basestation files to OG1 with one subcommand
per verb. The typical workflow is ``draft`` (optional) → ``init`` → ``validate`` → ``process``
→ ``report``; ``enrich`` adds metadata to a written file; ``inspect`` and ``list`` are
read-only helpers.

.. code-block:: console

   $ seagliderOG1 draft --raw-dir /data/005/20080606 -o drafts/
   $ seagliderOG1 init sg005.yaml --raw-dir /data/005/20080606
   $ seagliderOG1 validate sg005.yaml
   $ seagliderOG1 process  sg005.yaml
   $ seagliderOG1 report   out/sg005_20080606T180256_delayed.nc

The same entry point is available as a module:

.. code-block:: console

   $ python -m seagliderOG1.cli --help

See :ref:`mission_yaml` for the configuration file the verbs read and write.

Data mode
---------

``process --mode`` (and the ``mode`` key in ``mission.yaml``) sets the OG1 data mode, which
determines the data-mode suffix of the output id: ``realtime`` gives the suffix ``R`` and
``delayed`` gives ``delayed`` (``vocabularies.MODE_SUFFIX``). With neither set the mode is
``realtime``: a file is delayed mode only when you say so.

Conversion page
---------------

``seagliderOG1 report FILE.nc`` writes the HTML conversion page ``<id>_conversion.html`` for a
written OG1 file: beside the file by default, directly into ``-o DIR``, or into ``ROOT/<id>/``
with ``--report-dir ROOT`` — so the pages can live apart from the archived data. ``process
--report`` (or ``report: true`` in ``mission.yaml``) writes the same page as it converts, and
``process --report-dir ROOT`` puts it under ROOT. An existing page is refused unless
``--force``. ``inspect`` prints text only. See :ref:`conversion_page` for the sections the
page shows.

``process`` also writes ``<id>_conversion.json`` beside each OG1 file: the input files (name,
size, dive number, dimension lengths and global-attribute count) and which dives each
basestation variable was present in and had values in.
The page reads it for its *Presence across dives* and *Before → after* sections. When the input dives disagree,
``process`` prints one line per mission after ``wrote``:

.. code-block:: console

   wrote outputs/sg005_20080606T180256_delayed.nc
     sg005_20080606T180256_delayed: 343 variables over 5 dives; 338 on every dive, 5 on some (3 patterns) — see seagliderOG1 report outputs/sg005_20080606T180256_delayed.nc

The sidecar belongs to its OG1 file: it is replaced whenever the file is written. It records
the file's ``tracking_id`` (a new UUID on every write) and the SHA-256 of its bytes; ``report``
warns when the file beside it has changed since.

Draft
-----

``seagliderOG1 draft --raw-dir DIR [-o OUT] [--dives FIRST LAST]`` converts one mission with
no ``mission.yaml``, to see what the basestation files hold before writing one. It writes
``<id>_draft.nc``, ``<id>_draft_conversion.html``, ``<id>_draft_conversion.json`` and
``<id>_draft_mission.yaml`` (the ``init`` template with ``raw_dir``, ``dives`` and the platform
fields filled, and the derived id in a comment). None of these is an OG1 file: every name ends
``_draft``, the netCDF carries a ``draft`` global attribute, and its ``Conventions`` has no
``OG-1.0``. If any of the four files exists, ``draft`` writes nothing unless given ``--force``
(the proposal may have been edited in place). The draft page shows the basestation files' own
global attributes, marking those that differ between files, and what ``mission.yaml`` must
still supply.

Adding metadata later
---------------------

``seagliderOG1 enrich FILE.nc [mission.yaml] [--doi DOI]`` sets global attributes on a written
OG1 file without converting again — a DOI assigned after publication, or a corrected
``deployment:`` / ``global_attributes:`` value. It changes the netCDF file, not the
configuration: the globals are edited in place, ``date_modified`` is set, a ``history`` line
names the keys, ``tracking_id`` is renewed, ``date_created`` is kept, and the sidecar is
rebound. Values must be text, numbers or dates (a date is written as ISO 8601 text); every
value is checked before the file is opened, so a refused one leaves the file unchanged.
Replacing a different value already in the file warns with both values. ``deployment.id``
cannot change: the file name and sidecar are bound to it, so a new id means converting again.
The globals ``enrich`` writes itself (``date_modified``, ``history``, ``tracking_id``,
``draft``) and the ``conversion_*`` records cannot be set.
Reserving the DOI first and setting ``deployment.doi`` before ``process`` is the
alternative.

Listing the vocabulary
----------------------

``seagliderOG1 list`` prints what an OG1 file expects, read from the tables the converter uses:

.. code-block:: console

   $ seagliderOG1 list                          # the registry names
   $ seagliderOG1 list globals                  # every OG1 global: tier, source, where it is set
   $ seagliderOG1 list platform                 # the platform: keys and where each is written
   $ seagliderOG1 list variables --search temp  # OG1 variables, filtered on any column
   $ seagliderOG1 list variables TEMP           # one variable's attributes in full
   $ seagliderOG1 list sensors                  # the sensor catalogue (NERC L22)

Verbs
-----

.. argparse::
   :module: seagliderOG1.cli
   :func: build_parser
   :prog: seagliderOG1

Exit status
-----------

* ``0`` — success.
* ``1`` — a handled error (a missing file, an invalid configuration, a conversion that wrote
  nothing).
* ``2`` — a usage error (argparse: an unknown flag or a missing argument).
