"""Dark-mode support on Windows 10.

Windows 10 has no "windows11" Qt style, so Qt falls back to "windowsvista",
which ignores the system dark setting -- the whole UI stayed light and the
jog arrows (drawn in a fixed light colour) became invisible."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ponn_punch_press import app as app_module
from ponn_punch_press.ui.machine_panel import _make_arrow_icon

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only style handling")


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    original = app.style().objectName()
    yield app
    app.setStyle(original)


@pytest.mark.parametrize("style", ["windowsvista", "windows"])
def test_styles_that_ignore_dark_mode_are_replaced_by_fusion(qapp, style):
    if style not in [key.lower() for key in QStyleFactory.keys()]:
        pytest.skip(f"{style} style not available")
    qapp.setStyle(style)

    app_module._ensure_dark_mode_support(qapp)

    assert qapp.style().objectName() == "fusion"


def test_the_windows_11_style_is_left_alone(qapp):
    if "windows11" not in [key.lower() for key in QStyleFactory.keys()]:
        pytest.skip("windows11 style not available")
    qapp.setStyle("windows11")

    app_module._ensure_dark_mode_support(qapp)

    assert qapp.style().objectName() == "windows11"


def _arrow_body_color(icon) -> QColor:
    image = icon.pixmap(64, 64).toImage()
    return image.pixelColor(16, 32)  # inside the arrow's stem


def test_arrow_icon_uses_the_requested_colour():
    assert _arrow_body_color(_make_arrow_icon(0, color="#000000")).name() == "#000000"
    assert _arrow_body_color(_make_arrow_icon(0, color="#ffffff")).name() == "#ffffff"
