"""Exceptions raised by seagliderOG1.

Kept in one module so callers can catch them without importing the pipeline
internals that raise them.
"""

__all__ = ["MetadataError"]


class MetadataError(ValueError):
    """An OG1-mandatory global attribute is missing from the converted dataset.

    Raised by :func:`seagliderOG1.convert.to_og1` after the three metadata
    sources (data-derived, package constants, mission config) are merged, when a
    mandatory global attribute is absent or holds a placeholder. Subclasses
    :class:`ValueError` so existing ``except ValueError`` handlers still catch it.
    """
