"""Report layer: owned builders over a vendored, byte-identical design core.

The ``_vendored`` subpackage is copied byte-for-byte across the family packages
(ctdcast, oceanarray, glidertest, seagliderOG1) and is never edited here;
``_vendored/check.py`` verifies the bytes against ``_vendored/MANIFEST.txt``. Owned
modules in this package build the row data; the vendored macros render the tables.
"""
