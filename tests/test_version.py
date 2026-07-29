from __future__ import annotations

from importlib.metadata import version

from scheimpflug_optimeter import __version__
from scheimpflug_optimeter.app import create_application


def test_runtime_version_uses_installed_project_metadata():
    assert __version__ == version("scheimpflug-optimeter")


def test_qt_application_exposes_the_project_version(qapp):
    application = create_application([])

    assert application.applicationVersion() == __version__
