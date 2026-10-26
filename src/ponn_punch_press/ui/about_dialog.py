from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class AboutDialog(QDialog):
    """Port of AboutScreen.vb."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Ponn Punch Press"))
        layout.addWidget(QLabel("Originally written by Aaron Size, May 2004"))
        layout.addWidget(QLabel("Rewritten in Python for modern Windows, 2026"))
        layout.addWidget(QLabel("absize@gmail.com"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
