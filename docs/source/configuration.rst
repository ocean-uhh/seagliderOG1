.. _configuration:

Configuration
=============

Converting a Seaglider mission to OG1 needs metadata the basestation files do not carry, carry
only in part, or carry wrongly. That configuration sits at three levels, from fixed to
per-mission.

Packaged, not yours to set
--------------------------

Units, the basestation → OG1 variable-name mappings, and the OG1 controlled vocabularies are
fixed by the OG1 format and shipped with the package. They are the same for every mission and
are not user configuration; see :ref:`defaults`. A variable OG1 does not specify keeps its
basestation name — the one place a local vocabulary choice may later matter (below).

Reused across missions
----------------------

Some metadata rarely changes between deployments: your institution and its EDMO code, and, in
future, vocabulary choices for variables OG1 does not specify. Today the institution and
contributor records are repeated in each mission's ``mission.yaml``. A future ``fleet.yaml``
will hold them once for a fleet or institution, set in one place rather than per mission (see
the tip on :ref:`defaults`).

Per mission
-----------

The ``mission.yaml`` you keep beside the data carries everything specific to one deployment (see
:ref:`mission_yaml` for every key). The file name is yours — ``mission.yaml`` is only the default
``seagliderOG1 init`` writes, and ``seagliderOG1 process my_mission.yaml`` works just as well; the
convention is one configuration per discrete glider mission, so one configuration makes one OG1
file. It carries:

* who and where — the PI and contributors, the institution(s) with their EDMO codes, and
  discovery metadata;
* the platform — its WMO number, serial number, model and depth rating;
* the data — the raw-data directory, the dive range, and the data mode;
* corrections — fixes for errors in the basestation calibration metadata
  (``sg_calib_constants.m`` → ``sg_cal_calibcomm*``), such as a wrong instrument serial number,
  through the ``sensors:`` block.

Generating a starting configuration
-----------------------------------

``seagliderOG1 init`` writes a commented ``mission.yaml`` to edit; with ``--raw-dir`` it fills
``raw_dir`` and the platform block from the basestation files:

.. code-block:: console

   $ seagliderOG1 init sg005.yaml --raw-dir /data/sg005/

Generating a configuration from Python (a ``mission.template()``, and a ``fleet.template()`` for
the fleet file) is planned for a future release.

What the conversion report checks
---------------------------------

The configuration need not be complete before the first run. ``seagliderOG1 report`` (and
``process --report``) writes an HTML page that checks the configuration against the data and
suggests fixes: it proposes an EDMO code when your institution name matches the packaged
registry, and flags recommended metadata that is missing or platform fields written as ``UNK``.
See :ref:`conversion_page`.
