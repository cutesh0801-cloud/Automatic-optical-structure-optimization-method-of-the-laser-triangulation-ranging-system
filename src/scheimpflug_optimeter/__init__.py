"""Scheimpflug OptiMeter public package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("scheimpflug-optimeter")
except PackageNotFoundError:
    # Direct source-tree imports are intentionally identifiable. Supported
    # installs and the portable bundle always include distribution metadata.
    __version__ = "0+unknown"
