"""Exceptions raised by seagliderOG1.

Kept in one module so callers can catch them without importing the pipeline
internals that raise them.
"""

__all__ = ["MetadataError", "MissionError", "UnitsError"]


class MetadataError(ValueError):
    """An OG1-mandatory global attribute is missing from the converted dataset.

    Raised by :func:`seagliderOG1.convert` after the three metadata sources
    (data-derived, package constants, mission config) are merged, when a
    mandatory global attribute is absent or holds a placeholder. Subclasses
    :class:`ValueError` so existing ``except ValueError`` handlers still catch it.
    """


class UnitsError(ValueError):
    """A unit conversion produced values implausible for the variable.

    Raised by :func:`seagliderOG1.convert` when a units factor is applied and
    the converted values fall outside the OG1 variable's ``valid_min`` /
    ``valid_max`` range, and no documented correction (such as the density
    anomaly offset) brings them back into range. Refusing is safer than writing
    a file whose values are off by a unit factor. Subclasses :class:`ValueError`
    so existing ``except ValueError`` handlers still catch it.
    """


class MissionError(ValueError):
    """A mission configuration is invalid and cannot be converted.

    Raised by :func:`seagliderOG1.mission.load` when the configuration has one
    or more validation errors, and by :func:`seagliderOG1.process` when given a
    configuration it cannot act on (for example a root of several missions where
    a single mission is required). The validation issues that caused it, if any,
    are on the ``issues`` attribute. Subclasses :class:`ValueError` so existing
    ``except ValueError`` handlers still catch it.
    """

    def __init__(self, message: str, issues: list | None = None) -> None:
        """Store the message and the validation issues that caused it.

        Parameters
        ----------
        message : str
            A description of why the configuration cannot be converted.
        issues : list of ValidationIssue or None, optional
            The validation issues that caused the error, if any.

        """
        super().__init__(message)
        self.issues = issues or []
