.. _variable_vocabulary:

Variable vocabulary
===================

Each variable in an OG1 file carries attributes from
``seagliderOG1/config/OG1_variable_attributes.yaml``. This page lists, for every variable
there, its ``vocabulary`` term and its ``standard_name``. The tables are written from that file
on every docs build.

``vocabulary``
   A link to the term that defines the variable, in NERC's identifier form
   (``http://vocab.nerc.ac.uk/collection/OG1/current/TEMP/``). The term comes from the `OG1
   collection <http://vocab.nerc.ac.uk/collection/OG1/current/>`_ wherever OG1 has one, and from
   `P01 <http://vocab.nerc.ac.uk/collection/P01/current/>`_ only where it does not. A variable
   with no term in either carries no ``vocabulary``: platform and deployment metadata (OG1 gives
   them none), Seaglider engineering and flight-model variables, and times other than ``TIME``.
   Variables ending ``_RAW`` share the term of the corrected variable: they are the same
   quantity before the basestation's corrections.
``standard_name``
   A current name from the CF standard-name table, whose units the variable's ``units``
   convert to. Absent where CF has no name for the quantity.
``coordinates``
   Every variable on ``N_MEASUREMENTS``, ``_QC`` variables included, carries
   ``coordinates = "TIME LONGITUDE LATITUDE DEPTH"``: OG1's four coordinates, in the
   manual's order, separated by spaces as CF requires (the manual's example separates them
   with commas).

The tests check every term and name against offline copies of the OG1 collection, the P01 terms
in use and the CF table (version 95), in ``tests/data/vocabularies/``.
``scripts/fetch_vocabularies.py`` refreshes them.

With a vocabulary term
----------------------

The term label is the term's preferred label in that copy.

.. include:: _generated/vocabulary_terms.inc

Without a vocabulary term
-------------------------

.. include:: _generated/vocabulary_none.inc
