"""Report layer: owned builders over a vendored, byte-identical design core.

The ``_vendored`` subpackage is copied byte-for-byte across the family packages
(ctdcast, oceanarray, glidertest, seagliderOG1) and is never edited here;
``_vendored/check.py`` verifies the bytes against ``_vendored/MANIFEST.txt``. Owned
modules in this package build the row data; the vendored macros render the tables.
"""

import matplotlib

# The report layer only ever renders figures to PNG bytes for the conversion page, never to a
# screen, so pin a non-interactive backend the moment it is imported — in the CLI, a notebook,
# a script, or a test. Without it, the first figure blocks on a GUI window under an interactive
# backend (macOS defaults to `macosx`). Set here, before any submodule imports pyplot, so it
# covers every entry point into rendering, not just the CLI (which also sets MPLBACKEND).
matplotlib.use("Agg")
