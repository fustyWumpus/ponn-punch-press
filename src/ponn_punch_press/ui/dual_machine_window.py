from __future__ import annotations

import re
import struct

from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QPushButton, QSplitter, QWidget

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
    font-size: 10pt;
    font-weight: 700;
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
    color: #c0820a;
}
QLabel#downloadStatusLabel[downloaded="true"] {
    color: #2a9d43;
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
_LEAVE_FULLSCREEN_RECHECK_MS = 400

# Text sizes tried, largest first, until the whole window fits the space the
# screen leaves it. 1.0 is the design size (what a 1920x1080 screen at 150%
# scaling -- 1280x720 usable -- gets in fullscreen); the smaller steps only
# kick in on a screen, or a maximized window, with less room than that.
_TEXT_SCALES = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7)
_REFIT_DELAY_MS = 150  # lets the window manager finish a state change first


def _scaled_stylesheet(scale: float) -> str:
    """The stylesheet with every font-size multiplied by `scale`."""
    return re.sub(
        r"font-size:\s*([\d.]+)pt",
        lambda match: f"font-size: {float(match.group(1)) * scale:.2f}pt",
        _STYLESHEET,
    )


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
        self._text_scale = 1.0
        self.setStyleSheet(_scaled_stylesheet(self._text_scale))
        # Owned by the window, so it dies with it, and restarting it merges a
        # burst of state changes into a single re-fit.
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(_REFIT_DELAY_MS)
        self._refit_timer.timeout.connect(self.fit_text_to_screen)
        # Where leaving fullscreen returns to. True is also the right default
        # when the app *starts* in fullscreen (restored from last session).
        self._maximized_before_fullscreen = True
        self._fullscreen_requested = False  # what the user last asked for
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
        self.fullscreen_action.triggered.connect(self._on_fullscreen_action)
        view_menu.addAction(self.fullscreen_action)

        # Esc is a second, always-available way out (F11 and the menu are the
        # others). Does nothing unless the window is actually fullscreen.
        self._leave_fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._leave_fullscreen_shortcut.activated.connect(lambda: self.set_fullscreen(False))

        # Top-right corner of the menu bar -- the one strip that stays visible
        # in fullscreen, where there is no title-bar close button. Same effect
        # as File > Exit.
        self.exit_button = QPushButton("Exit")
        self.exit_button.setObjectName("exitButton")
        self.exit_button.setToolTip("Exit the program (stops motion on both machines)")
        self.exit_button.clicked.connect(self.close)
        self.menuBar().setCornerWidget(self.exit_button, Qt.TopRightCorner)

    def _on_fullscreen_action(self, _checked: bool = False) -> None:
        # Toggle from the window's real state, never from the menu's check
        # mark: if the two ever disagree, trusting the mark turns the first
        # click/F11 into a silent no-op ("it won't leave fullscreen").
        self.set_fullscreen(not self.isFullScreen())

    def set_fullscreen(self, enabled: bool) -> None:
        if enabled == self.isFullScreen():
            self.fullscreen_action.setChecked(self.isFullScreen())
            return
        self._fullscreen_requested = enabled
        if enabled:
            self._maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()
        else:
            if self._maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()
            # Windows can occasionally ignore the first request (the window
            # manager is mid-transition); check a moment later and insist.
            QTimer.singleShot(_LEAVE_FULLSCREEN_RECHECK_MS, self._ensure_left_fullscreen)

    def _ensure_left_fullscreen(self) -> None:
        # Only if nobody asked for fullscreen again in the meantime -- a quick
        # F11, F11 must not be undone by the re-check of the first exit.
        if self.isFullScreen() and not self._fullscreen_requested:
            self.setWindowState(self.windowState() & ~Qt.WindowFullScreen)
            if self._maximized_before_fullscreen:
                self.showMaximized()
            else:
                self.showNormal()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.WindowStateChange:
            # Keep the menu check mark honest however fullscreen was entered
            # or left. setChecked() doesn't emit `triggered`, so no feedback loop.
            self.fullscreen_action.setChecked(self.isFullScreen())
            # Fullscreen has more room than a maximized window (no taskbar or
            # title bar), so the best text size changes with the state.
            self._refit_timer.start()
        super().changeEvent(event)

    # --- keeping everything on screen ---

    def _available_size(self) -> QSize | None:
        """Room this window's contents can occupy on its screen: all of it in
        fullscreen, otherwise the work area minus the window frame."""
        screen = self.screen()
        if screen is None:
            return None
        if self.isFullScreen():
            return screen.geometry().size()
        frame = self.frameGeometry().size() - self.geometry().size()
        return screen.availableGeometry().size() - frame

    def fit_text_to_screen(self) -> None:
        available = self._available_size()
        if available is not None:
            self.fit_text_to_size(available.width(), available.height())

    def fit_text_to_size(self, width: int, height: int) -> float:
        """Use the largest text size (from _TEXT_SCALES) at which the whole
        window -- every button and label -- fits in width x height, so nothing
        is ever cut off or pushed past the screen edge. Returns the scale."""
        state = self.windowState()
        chosen = _TEXT_SCALES[-1]
        for scale in _TEXT_SCALES:
            self._apply_text_scale(scale)
            hint = self.minimumSizeHint()
            if hint.width() <= width and hint.height() <= height:
                chosen = scale
                break
        else:
            self._apply_text_scale(chosen)  # nothing fits: smallest text is the best we can do
        # Changing the minimum size must never knock the window out of
        # fullscreen/maximized -- put the state back if a platform dropped it.
        if self.windowState() != state:
            self.setWindowState(state)
        return chosen

    def _apply_text_scale(self, scale: float) -> None:
        if scale == self._text_scale:
            return
        self._text_scale = scale
        self.setStyleSheet(_scaled_stylesheet(scale))
        # minimumSizeHint() is stale right after a stylesheet change (verified:
        # off by 5-70 px). Only polishing every child and then delivering the
        # pending posted events (the layout invalidations) makes it exact.
        # Posted events only -- not processEvents(), which would also run
        # timers and window-state handling in the middle of this.
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        QCoreApplication.sendPostedEvents(None, 0)
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)

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
                self._refit_timer.start()
                return True
        self.showMaximized()
        self._refit_timer.start()
        return False

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        geometry_base64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.panel_machine_1.machine_store.set_window_geometry(geometry_base64)
        self.panel_machine_2.shut_down()
        self.panel_machine_1.shut_down()
        super().closeEvent(event)
