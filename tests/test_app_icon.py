from __future__ import annotations

from importlib.resources import files
from xml.etree import ElementTree

from PySide6.QtGui import QImage

from scheimpflug_optimeter.app import _load_application_icon, create_application
from scheimpflug_optimeter.ui.main_window import MainWindow


def test_original_logo_assets_are_square_and_loadable():
    assets = files("scheimpflug_optimeter.assets")
    svg_payload = assets.joinpath("app_icon.svg").read_bytes()
    root = ElementTree.fromstring(svg_payload)

    assert root.attrib["viewBox"] == "0 0 512 512"
    assert root.attrib["width"] == root.attrib["height"] == "512"

    image = QImage()
    assert image.loadFromData(assets.joinpath("app_icon.png").read_bytes(), "PNG")
    assert image.width() == image.height() == 512

    ico_payload = assets.joinpath("app_icon.ico").read_bytes()
    assert ico_payload[:4] == b"\x00\x00\x01\x00"


def test_application_and_window_receive_the_bundled_icon(qtbot):
    application = create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)

    assert not application.windowIcon().isNull()
    assert not window.windowIcon().isNull()


def test_missing_or_invalid_icon_resource_is_non_fatal(qapp):
    missing = _load_application_icon("not-present.png")
    invalid = _load_application_icon("__init__.py")

    assert missing.isNull()
    assert invalid.isNull()
