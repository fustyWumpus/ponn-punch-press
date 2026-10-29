from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QWidget

# A click on a fast action button (Home, Reset Counter, ...) is over in a few
# milliseconds, so the stylesheet's :pressed state alone is barely visible.
# Every button also gets a short "flash" afterwards so the operator can see
# the click registered.
_FLASH_MS = 300


def _set_flash(button: QPushButton, on: bool) -> None:
    button.setProperty("flash", on)
    # Dynamic-property selectors in the stylesheet only re-evaluate on repolish.
    button.style().unpolish(button)
    button.style().polish(button)


def install_click_feedback(root: QWidget) -> None:
    """Make every QPushButton under `root` flash (stylesheet selector
    `QPushButton[flash="true"]`) for a moment after it is clicked."""
    for button in root.findChildren(QPushButton):
        timer = QTimer(button)
        timer.setSingleShot(True)
        timer.setInterval(_FLASH_MS)
        timer.timeout.connect(lambda b=button: _set_flash(b, False))

        def on_clicked(_checked: bool = False, b: QPushButton = button, t: QTimer = timer) -> None:
            _set_flash(b, True)
            t.start()  # restarts the countdown if clicked again mid-flash

        button.clicked.connect(on_clicked)
