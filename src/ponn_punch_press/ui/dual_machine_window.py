from __future__ import annotations

import struct

from PySide6.QtCore import QByteArray, QEvent, QRect, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMainWindow, QPushButton, QSplitter

from .about_dialog import AboutDialog
from .click_feedback import install_click_feedback
from .machine_panel import MachinePanel

# A modernized, screen-filling look: bigger type and more generous spacing
# than the legacy app's small fixed-size dialog, since this now runs as a
# full-screen shop-floor dashboard rather than a cramped 2004-era window.
# Machine 2 (left) gets a blue accent, Machine 1 (right) an amber one, purely
# so an operator can tell the two panels apart at a glance -- physical
# machine identity doesn't otherwise show up anywhere on screen.
_STYLESHEET = """
QWidget {
    font-size: 13pt;
}
QGroupBox {
    font-weight: 600;
    border: 1px solid #b0b0b0;
    border-radius: 6px;
    margin-top: 10px;
    padding: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    padding: 5px 12px;
    border-radius: 4px;
}
QPushButton[compact="true"] {
    padding: 3px 6px;
    font-size: 11pt;
}
QPushButton#primaryButton {
    background-color: #2f6fed;
    color: white;
    font-weight: 600;
}
QPushButton#dangerButton {
    background-color: #d1373f;
    color: white;
    font-weight: 600;
}
QPushButton#exitButton {
    background-color: #d1373f;
    color: white;
    font-weight: 600;
    padding: 2px 18px;
    border-radius: 4px;
}
QPushButton#framedButton {
    border: 2px solid #888;
    border-radius: 6px;
}
QPushButton#framedButton:pressed {
    border-color: #2f6fed;
    background-color: rgba(47, 111, 237, 0.2);
}
QLabel#positionLabel {
    font-size: 18pt;
    font-weight: 600;
}
QLabel#statusLabel {
    font-size: 15pt;
    font-weight: 600;
}
QLabel#machineNameLabel {
    font-size: 20pt;
    font-weight: 700;
}
#machineHeader {
    border-bottom: 3px solid #888;
    padding-bottom: 4px;
    margin-bottom: 8px;
}
#machine2Panel #machineHeader {
    border-bottom-color: #2f6fed;
}
#machine1Panel #machineHeader {
    border-bottom-color: #e08a1e;
}
QPushButton#jogButton {
    padding: 0px;
    border: 2px solid #888;
    border-radius: 6px;
}
QPushButton#jogButton:pressed {
    border-color: #2f6fed;
    background-color: rgba(47, 111, 237, 0.25);
}
QPushButton#jogButton:disabled {
    border-color: #444;
}
QPushButton#primaryButton:pressed {
    background-color: #1b4fb8;
}
QPushButton#dangerButton:pressed, QPushButton#exitButton:pressed {
    background-color: #8f1f26;
}
QLabel#downloadStatusLabel {
    font-size: 11pt;
    font-weight: 600;
    color: #e0a030;
}
QLabel#downloadStatusLabel[downloaded="true"] {
    color: #3fb950;
}
/* Brief highlight after any button is clicked -- see click_feedback.py. Kept
   last so it wins over the per-button rules above. */
QPushButton[flash="true"] {
    border-color: #2f6fed;
    background-color: rgba(47, 111, 237, 0.35);
}
QPushButton#primaryButton[flash="true"] {
    background-color: #1b4fb8;
}
QPushButton#dangerButton[flash="true"], QPushButton#exitButton[flash="true"] {
    background-color: #8f1f26;
}
"""

_GEOMETRY_MAGIC = 0x01D9D0CB


def _saved_geometry_is_sane(blob: bytes) -> bool:
    """Checks a QWidget::saveGeometry() blob before restoreGeometry() touches
    the window. Layout (Qt 6): magic u32, version u16+u16, frame rect (4x i32),
    normal rect (4x i32), screen index i32, maximized u8, fullscreen u8,
    screen width i32. The frame must land on a currently attached screen (a
    window last used on a second monitor that's since been unplugged would
    otherwise be restored off-screen). Fullscreen is allowed -- it's a real
    mode now. Any parse failure counts as unsafe."""
    try:
        if len(blob) < 50:
            return False
        magic, _major, _minor = struct.unpack(">IHH", blob[0:8])
        if magic != _GEOMETRY_MAGIC:
            return False
        x1, y1, x2, y2 = struct.unpack(">iiii", blob[8:24])
        frame = QRect(x1, y1, x2 - x1 + 1, y2 - y1 + 1)
        return any(screen.geometry().intersects(frame) for screen in QGuiApplication.screens())
    except (struct.error, IndexError):
        return False


class DualMachineWindow(QMainWindow):
    """Hosts both machines' control panels side by side: Machine 2 on the
    left, Machine 1 on the right, per the physical shop-floor layout. This
    replaces the legacy app's model of one window driving whichever single
    controller was currently selected -- both machines are live and
    controllable at the same time now.
    """

    def __init__(self, panel_machine_2: MachinePanel, panel_machine_1: MachinePanel):
        super().__init__()
        self.panel_machine_2 = panel_machine_2
        self.panel_machine_1 = panel_machine_1
        panel_machine_2.setObjectName("machine2Panel")
        panel_machine_1.setObjectName("machine1Panel")

        self.setWindowTitle("Ponn Punch Press")
        self.setStyleSheet(_STYLESHEET)
        # Where leaving fullscreen returns to. True is also the right default
        # when the app *starts* in fullscreen (restored from last session).
        self._maximized_before_fullscreen = True
        self._build_menu()

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(panel_machine_2)
        self.splitter.addWidget(panel_machine_1)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self.splitter)
        install_click_feedback(self)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("&About...", lambda: AboutDialog(self).exec())
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        # Per-machine Settings, moved here from a button in each panel's
        # header -- one pulldown menu covering both machines instead of a
        # separate button duplicated on each side of the screen.
        settings_menu = self.menuBar().addMenu("&Settings")
        settings_menu.addAction(f"{self.panel_machine_2.profile.name}...", self.panel_machine_2.open_preferences)
        settings_menu.addAction(f"{self.panel_machine_1.profile.name}...", self.panel_machine_1.open_preferences)

        # The menu bar deliberately stays visible in fullscreen, so File >
        # Exit and this toggle are always reachable.
        view_menu = self.menuBar().addMenu("&View")
        self.fullscreen_action = QAction("&Full Screen", self)
        self.fullscreen_action.setCheckable(True)
        self.fullscreen_action.setShortcut(QKeySequence(Qt.Key_F11))
        self.fullscreen_action.triggered.connect(self.set_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        # Top-right corner of the menu bar -- the one strip that stays visible
        # in fullscreen, where there is no title-bar close button. Same effect
        # as File > Exit.
        self.exit_button = QPushButton("Exit")
        self.exit_button.setObjectName("exitButton")
        self.exit_button.setToolTip("Exit the program (stops motion on both machines)")
        self.exit_button.clicked.connect(self.close)
        self.menuBar().setCornerWidget(self.exit_button, Qt.TopRightCorner)

    def set_fullscreen(self, enabled: bool) -> None:
        if enabled == self.isFullScreen():
            return
        if enabled:
            self._maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()
        elif self._maximized_before_fullscreen:
            self.showMaximized()
        else:
            self.showNormal()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.WindowStateChange:
            # Keep the menu check mark honest however fullscreen was entered
            # or left. setChecked() doesn't emit `triggered`, so no feedback loop.
            self.fullscreen_action.setChecked(self.isFullScreen())
        super().changeEvent(event)

    def start_up(self) -> None:
        self.panel_machine_2.start_up()
        self.panel_machine_1.start_up()

    def restore_geometry_or_maximize(self) -> bool:
        """Shows the window at its last saved size/position (both panels share
        the same MachineProfileStore, so either's works as the source), or
        maximized if nothing usable is saved. Returns whether a saved geometry
        was restored. This is what makes the window visible at all."""
        saved = self.panel_machine_1.machine_store.get_window_geometry()
        if saved:
            geometry = QByteArray.fromBase64(saved.encode("ascii"))
            if _saved_geometry_is_sane(bytes(geometry)) and self.restoreGeometry(geometry):
                # restoreGeometry() only applies size/position/state -- it
                # never shows the window, so without this the app would run
                # invisibly whenever a saved geometry existed.
                self.show()
                return True
        self.showMaximized()
        return False

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        geometry_base64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.panel_machine_1.machine_store.set_window_geometry(geometry_base64)
        self.panel_machine_2.shut_down()
        self.panel_machine_1.shut_down()
        super().closeEvent(event)
