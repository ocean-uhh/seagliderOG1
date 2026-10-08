Command-line interface
======================

Installing the package provides a ``seagliderOG1`` command. It converts Seaglider
basestation files to OG1 using a mission configuration you own (``mission.yaml``), so
platform and contributor metadata belong to the mission rather than to the package.

Typical workflow
----------------

.. code-block:: bash

   seagliderOG1 init --from /data/005/20080606 -o sg005.yaml   # template from the first file
   seagliderOG1 validate sg005.yaml                            # config, source, dive range
   seagliderOG1 process  sg005.yaml                            # -> <output_dir>/<id>.nc

Verbs
-----

``init [--from DIR] [-o PATH] [--force]``
    Write a commented ``mission.yaml``. ``--from DIR`` fills the ``platform`` block and
    ``source`` from the first basestation file in ``DIR``.

``validate CONFIG [--strict]``
    Check the configuration: known keys and types, that ``source`` exists and holds
    basestation files (a mission directory or a root of ``SN/DATE`` directories), the
    ``dives`` range, contributor and institution records (names comma-free, roles in the
    NERC W08 vocabulary, at least one ``PI`` contributor and one ``Operator`` institution).
    ``--strict`` also requires every dive in the range to be present. Exit 0 when valid,
    1 on any error.

``process CONFIG [--source DIR_OR_ROOT] [--all | --mission GLOB] [-o DIR] [--mode realtime|delayed] [--dives FIRST LAST] [--force | --skip-existing] [-n]``
    Convert the mission(s) and write ``<output_dir>/<id>.nc``. ``--source`` overrides the
    config; a root of ``SN/DATE`` missions needs ``--all`` or ``--mission GLOB``. ``--mode``
    sets the OG1 id data-mode suffix (``delayed`` or ``R``). Each mission is attempted
    independently; the run prints ``N converted, N skipped, N failed`` and exits 1 on any
    failure. ``-n`` previews without writing.

``inspect FILE [--attrs | --variables | --by-dimension DIM]``
    Print the file's variables or attributes as a text table (basestation or OG1). An HTML
    inventory page (``-o``/``--title``) arrives with the ``seagliderOG1[report]`` extra.

``list {roles | institutions | missions} [PATH]``
    Print a registry: the NERC W08 contributor roles, the EDMO institution registry, or the
    missions discovered under ``PATH``.

The mission configuration
-------------------------

``mission.yaml`` is a file you keep with your data, not inside the package. ``init`` writes a
commented template; the key blocks are ``source``, ``output_dir``, ``mode``, ``dives``,
``platform``, ``global_attributes``, ``contributors`` (one entry per person per role, with a
W08 ``role:``) and ``institutions`` (at least one with ``role: Operator``). Paths resolve
relative to the configuration file.
