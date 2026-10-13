"""Convert Seaglider basestation NetCDF files to OG1-format NetCDF."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("seagliderOG1")
except PackageNotFoundError:  # not installed (e.g. a source tree without a build)
    __version__ = "unknown"

__all__ = ["__version__"]
