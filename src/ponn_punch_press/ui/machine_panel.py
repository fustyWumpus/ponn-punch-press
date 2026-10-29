from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.machine_profile import MachineProfile
from ..core.machine_profile_store import MachineProfileStore
from ..core.recipe import Recipe, RecipeLayout
from ..core.recipe_io import list_recipe_files, write_recipe_file
from ..core.workflow import FaultType, PunchPressWorkflow, RecipeDownloadRejected, WorkflowState
from ..motion.controller import Axis, MotionControllerConnectionError, MotionControllerError
from .preferences_dialog import PreferencesDialog

_POLL_INTERVAL_MS = 500
_STARTUP_POLL_INTERVAL_MS = 2000  # matches PollTimer.Interval = 2000 at first load
_DIGIT3_SPIN_WIDTH = 90  # fits a 3-digit value plus the spinner arrows without clipping
_JOG_BUTTON_WIDTH = 62  # ~30% wider than the previous 48 px square
_JOG_BUTTON_HEIGHT = 54  # slightly taller than the previous 48 px
_JOG_SIDE_GAP = 5  # gap between left/right, independent of button width

# The legacy app's AllowKeyJog flag was declared but never set anywhere in the
# source (VB Booleans default False), so arrow/numpad keyboard jogging was
# silently dead in the shipped app despite the handler code existing for it.
# Preserved as-is rather than "fixed", since enabling it would be a behavior
# change beyond a straight technology port.
_ALLOW_KEYBOARD_JOG = False

_JOG_KEYS = {
    Qt.Key_Up: (Axis.Y, False),
    Qt.Key_8: (Axis.Y, False),  # numpad 8
    Qt.Key_Down: (Axis.Y, True),
    Qt.Key_2: (Axis.Y, True),  # numpad 2
    Qt.Key_Left: (Axis.X, True),
    Qt.Key_4: (Axis.X, True),  # numpad 4
    Qt.Key_Right: (Axis.X, False),
    Qt.Key_6: (Axis.X, False),  # numpad 6
}


def _make_arrow_icon(rotation_degrees: float, size: int = 64, color: str = "#ffffff") -> QIcon:
    """A bold, filled directional-arrow icon (thick stem + wide triangular
    head) drawn on the fly rather than relying on a thin Unicode glyph, whose
    weight and legibility varies a lot by font and renders far too small at
    real button sizes for a shop-floor touchscreen."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(size / 2, size / 2)
    painter.rotate(rotation_degrees)
    painter.translate(-size / 2, -size / 2)

    path = QPainterPath()
    path.moveTo(0, 0.28 * size)
    path.lineTo(0.45 * size, 0.28 * size)
    path.lineTo(0.45 * size, 0.06 * size)
    path.lineTo(size, 0.5 * size)
    path.lineTo(0.45 * size, 0.94 * size)
    path.lineTo(0.45 * size, 0.72 * size)
    path.lineTo(0, 0.72 * size)
    path.closeSubpath()

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


class MachinePanel(QWidget):
    """Port of MainScreen.vb for a single machine, as an embeddable widget so
    two of these can run side by side in DualMachineWindow (one machine no
    longer means one top-level window -- both machines are controlled from
    the same screen at once). Holds no motion-control logic itself --
    everything goes through a PunchPressWorkflow, backed by either the real
    gclib controller or motion.simulator.Simulator for hardware-less
    development and testing.
    """

    def __init__(
        self,
        workflow: PunchPressWorkflow,
        profile: MachineProfile,
        dmc_source: str,
        machine_store: MachineProfileStore,
    ):
        super().__init__()
        self.workflow = workflow
        self.profile = profile
        self.dmc_source = dmc_source
        self.machine_store = machine_store
        self.current_recipe: Recipe | None = None
        self._key_jog_active = False
        self._last_x_position = 0.0
        self._last_y_position = 0.0

        self._build_ui()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._on_poll_tick)

    # --- startup / shutdown ---

    def start_up(self) -> None:
        """Port of MainScreen_Load."""
        try:
            self.workflow.start_up(self.profile.ip_address, self.dmc_source)
        except MotionControllerError as exc:
            self._show_controller_error("connect to", exc)
        self._refresh_recipe_list()
        self._update_pause_button_text()
        self.poll_timer.start(_STARTUP_POLL_INTERVAL_MS)
        # Subsequent ticks run at the normal 500ms rate (was PollTimer.Interval
        # = 500 set on the first tick in PollTimer_Tick).
        QTimer.singleShot(_STARTUP_POLL_INTERVAL_MS, lambda: self.poll_timer.setInterval(_POLL_INTERVAL_MS))

    def _show_controller_error(self, action: str, exc: MotionControllerError) -> None:
        """Verbose, actionable error dialog for controller connection/command
        failures. The original dialog was just str(exc) with no IP address or
        guidance at all -- a real misconfigured-IP issue (a machine silently
        pointed at the wrong controller) looked identical to an unexplained
        hardware failure with nothing to go on."""
        if isinstance(exc, MotionControllerConnectionError):
            likely_causes = (
                "Likely causes:\n"
                "  - The controller is powered off, or its Ethernet cable is unplugged.\n"
                "  - The IP address in Settings does not match the controller's actual address.\n"
                "  - This PC's network adapter is not on the same subnet as the controller.\n\n"
                f"Try: confirm the controller is powered on, ping {self.profile.ip_address} "
                f"from a command prompt, and check Settings > {self.profile.name}... for the "
                "correct IP address."
            )
        else:
            likely_causes = (
                "Likely causes:\n"
                "  - The controller was left in a confused state by a previous abrupt "
                "disconnect (e.g. the app was force-closed rather than exited normally) -- "
                "try power-cycling it.\n"
                "  - This controller's hardware configuration may not match what this "
                "machine's firmware expects.\n\n"
                "Try: power-cycle the controller, wait about 10 seconds for it to fully boot, "
                "then reopen this application."
            )

        QMessageBox.critical(
            self,
            f"{self.profile.name}: Motion Controller Error",
            f"Failed to {action} the controller at {self.profile.ip_address}.\n\n"
            f"Details: {exc}\n\n"
            f"{likely_causes}",
        )

    def shut_down(self) -> None:
        self.poll_timer.stop()
        try:
            self.workflow.shut_down()
        except MotionControllerError:
            pass

    # --- UI construction ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.addWidget(self._build_header())

        upper_row = QHBoxLayout()
        upper_row.addWidget(self._build_recipe_panel(), stretch=1)
        upper_row.addWidget(self._build_pattern_panel(), stretch=3)
        root.addLayout(upper_row, stretch=3)

        root.addWidget(self._build_motion_panel(), stretch=2)

    def _build_header(self) -> QWidget:
        # No fixed pixel height here -- a hardcoded guess doesn't account for
        # this system's DPI scaling and clipped/corrupted the label's actual
        # rendered text twice already. Sizing naturally from the label's real
        # font metrics, with a small explicit margin, is what actually works
        # regardless of DPI.
        header = QFrame()
        header.setObjectName("machineHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 4, 0, 4)

        layout.addStretch(1)
        self.machine_name_label = QLabel(self.profile.name)
        self.machine_name_label.setObjectName("machineNameLabel")
        layout.addWidget(self.machine_name_label)
        layout.addStretch(1)

        return header

    def _build_recipe_panel(self) -> QGroupBox:
        box = QGroupBox("Programs")
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(box)

        self.recipe_list = QListWidget()
        self.recipe_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recipe_list.setMinimumHeight(220)
        self.recipe_list.currentRowChanged.connect(self._on_recipe_selected)
        layout.addWidget(self.recipe_list)

        self.delete_recipe_button = QPushButton("Delete Program")
        self.delete_recipe_button.setObjectName("framedButton")
        self.delete_recipe_button.clicked.connect(self._on_delete_recipe)
        layout.addWidget(self.delete_recipe_button)

        self.save_recipe_button = QPushButton("Save Current Program")
        self.save_recipe_button.setObjectName("framedButton")
        self.save_recipe_button.clicked.connect(self._on_save_recipe)
        layout.addWidget(self.save_recipe_button)

        return box

    def _build_pattern_panel(self) -> QGroupBox:
        box = QGroupBox("Punch Pattern")
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QGridLayout(box)
        layout.setVerticalSpacing(4)
        row = 0

        # Spans columns 0-1 only (not the full 0-3), so its right edge lines
        # up with every other field's right edge instead of stretching to
        # match the wider Rows/Columns row.
        layout.addWidget(QLabel("Comments:"), row, 0, 1, 2)
        row += 1
        self.comments_edit = QPlainTextEdit()
        self.comments_edit.setMaximumHeight(60)
        layout.addWidget(self.comments_edit, row, 0, 1, 2)
        row += 1

        layout.addWidget(QLabel("Layout:"), row, 0)
        self.layout_combo = QComboBox()
        self.layout_combo.addItems([RecipeLayout.MATRIX.label, RecipeLayout.STAGGERED.label])
        layout.addWidget(self.layout_combo, row, 1)
        row += 1

        # A nested row (instead of grid columns 2/3) so this row spans the
        # same width as every other row (label col + field col) rather than
        # adding two brand-new grid columns that stretch it wider than the
        # rest of the section. The stretch pushes "Columns:" to the right
        # edge, so its input lines up with the other fields' right edge.
        rows_columns_row = QHBoxLayout()
        rows_columns_row.addWidget(QLabel("Rows:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(0, 999)
        self.rows_spin.setMaximumWidth(_DIGIT3_SPIN_WIDTH)
        rows_columns_row.addWidget(self.rows_spin)
        rows_columns_row.addStretch(1)
        rows_columns_row.addWidget(QLabel("Columns:"))
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(0, 999)
        self.columns_spin.setMaximumWidth(_DIGIT3_SPIN_WIDTH)
        rows_columns_row.addWidget(self.columns_spin)
        layout.addLayout(rows_columns_row, row, 0, 1, 2)
        row += 1

        self.x_spacing_spin = self._add_float_field(layout, row, "X Spacing (in):")
        row += 1
        self.y_spacing_spin = self._add_float_field(layout, row, "Y Spacing (in):")
        row += 1
        self.x_start_spin = self._add_float_field(layout, row, "Starting X (in):")
        row += 1
        self.y_start_spin = self._add_float_field(layout, row, "Starting Y (in):")
        row += 1

        self.use_current_button = QPushButton("Use Current Position")
        self.use_current_button.setObjectName("framedButton")
        self.use_current_button.clicked.connect(self._on_use_current_position)
        layout.addWidget(self.use_current_button, row, 0, 1, 2)
        row += 1

        self.vac_on_spin = self._add_int_field(layout, row, "Vacuum On Duration:")
        row += 1
        self.vac_off_spin = self._add_int_field(layout, row, "Vacuum Off Duration:")
        row += 1

        self.speed_spin = self._add_int_field(layout, row, "Speed (% of max):")
        self.speed_spin.setRange(1, 100)
        self.speed_spin.setValue(100)
        row += 1

        return box

    def _add_int_field(self, layout: QGridLayout, row: int, label: str) -> QSpinBox:
        layout.addWidget(QLabel(label), row, 0)
        spin = QSpinBox()
        spin.setRange(0, 100_000)
        layout.addWidget(spin, row, 1)
        return spin

    def _add_float_field(self, layout: QGridLayout, row: int, label: str) -> QDoubleSpinBox:
        layout.addWidget(QLabel(label), row, 0)
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0.0, 10_000.0)
        layout.addWidget(spin, row, 1)
        return spin

    def _build_motion_panel(self) -> QGroupBox:
        box = QGroupBox("Motion Control")
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer = QHBoxLayout(box)

        left_column = QVBoxLayout()
        left_column.setSpacing(4)
        outer.addLayout(left_column, stretch=1)

        self.home_button = QPushButton("Home Axes")
        self.home_button.setObjectName("framedButton")
        self.home_button.clicked.connect(self._on_home)
        left_column.addWidget(self.home_button)

        self.homed_status_label = QLabel("Not Homed")
        self.homed_status_label.setObjectName("statusLabel")
        self.homed_status_label.setAlignment(Qt.AlignCenter)
        left_column.addWidget(self.homed_status_label)

        self.x_position_label = QLabel("X: 0.000")
        self.y_position_label = QLabel("Y: 0.000")
        self.x_position_label.setObjectName("positionLabel")
        self.y_position_label.setObjectName("positionLabel")
        self.x_position_label.setAlignment(Qt.AlignCenter)
        self.y_position_label.setAlignment(Qt.AlignCenter)
        left_column.addWidget(self.x_position_label)
        left_column.addWidget(self.y_position_label)
        left_column.addStretch(1)

        outer.addWidget(self._build_jog_buttons())

        # Count/Reset and the three action buttons sit to the right of the
        # jog arrows -- the jog buttons are sized down to roughly match this
        # column's natural height instead of dictating the row's height.
        right_column = QVBoxLayout()
        right_column.setSpacing(4)
        outer.addLayout(right_column, stretch=1)

        counter_row = QHBoxLayout()
        self.piece_counter_label = QLabel("Count: 0")
        self.piece_counter_label.setObjectName("positionLabel")
        self.reset_counter_button = QPushButton("Reset Counter")
        self.reset_counter_button.setObjectName("framedButton")
        self.reset_counter_button.clicked.connect(self.workflow.reset_counter)
        counter_row.addWidget(self.piece_counter_label)
        counter_row.addWidget(self.reset_counter_button)
        right_column.addLayout(counter_row)

        self.download_status_label = QLabel()
        self.download_status_label.setObjectName("downloadStatusLabel")
        self.download_status_label.setAlignment(Qt.AlignCenter)
        right_column.addWidget(self.download_status_label)
        self._update_download_status()

        self.download_button = QPushButton("DOWNLOAD PROGRAM")
        self.download_button.setObjectName("primaryButton")
        self.download_button.clicked.connect(self._on_download_recipe)
        right_column.addWidget(self.download_button)

        self.toggle_pause_button = QPushButton("UN-PAUSE")
        self.toggle_pause_button.setObjectName("framedButton")
        self.toggle_pause_button.clicked.connect(self._on_toggle_pause)
        right_column.addWidget(self.toggle_pause_button)

        self.restart_button = QPushButton("RESTART")
        self.restart_button.setObjectName("dangerButton")
        self.restart_button.clicked.connect(self._on_restart)
        right_column.addWidget(self.restart_button)

        # Smaller text/padding on the three action buttons frees width for the
        # larger jog arrows.
        for button in (self.download_button, self.toggle_pause_button, self.restart_button):
            button.setProperty("compact", True)

        right_column.addStretch(1)

        return box

    def _build_jog_buttons(self) -> QWidget:
        container = QWidget()
        jog_column = QVBoxLayout(container)
        jog_column.setContentsMargins(0, 0, 0, 0)
        jog_column.setSpacing(3)

        self.jog_forward_button = QPushButton()  # forward = Y+
        self.jog_back_button = QPushButton()  # back = Y-
        self.jog_left_button = QPushButton()  # X-
        self.jog_right_button = QPushButton()  # X+
        icon_edge = int(_JOG_BUTTON_HEIGHT * 0.85)
        icon_size = QSize(icon_edge, icon_edge)
        self._jog_arrows = (
            (self.jog_forward_button, -90),
            (self.jog_back_button, 90),
            (self.jog_left_button, 180),
            (self.jog_right_button, 0),
        )
        for button, _rotation in self._jog_arrows:
            button.setObjectName("jogButton")
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setFixedSize(_JOG_BUTTON_WIDTH, _JOG_BUTTON_HEIGHT)
            button.setIconSize(icon_size)
        self._refresh_jog_icons()

        jog_column.addWidget(self.jog_forward_button, alignment=Qt.AlignHCenter)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(_JOG_SIDE_GAP)
        middle_row.addWidget(self.jog_left_button)
        middle_row.addWidget(self.jog_right_button)
        jog_column.addLayout(middle_row)

        jog_column.addWidget(self.jog_back_button, alignment=Qt.AlignHCenter)

        self.jog_forward_button.pressed.connect(lambda: self.workflow.jog_start(Axis.Y))
        self.jog_back_button.pressed.connect(lambda: self.workflow.jog_start_negative(Axis.Y))
        self.jog_left_button.pressed.connect(lambda: self.workflow.jog_start_negative(Axis.X))
        self.jog_right_button.pressed.connect(lambda: self.workflow.jog_start(Axis.X))
        for button in (
            self.jog_forward_button,
            self.jog_back_button,
            self.jog_left_button,
            self.jog_right_button,
        ):
            button.released.connect(self.workflow.jog_stop)

        return container

    def _refresh_jog_icons(self) -> None:
        """Arrows are drawn in the current theme's button-text colour, so they
        stay visible in both light and dark mode (a fixed light colour
        disappears on a light button)."""
        color = self.palette().buttonText().color().name()
        for button, rotation in self._jog_arrows:
            button.setIcon(_make_arrow_icon(rotation, color=color))

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange) and hasattr(self, "_jog_arrows"):
            self._refresh_jog_icons()
        super().changeEvent(event)

    # --- recipe list ---

    def _update_download_status(self) -> None:
        downloaded = self.workflow.recipe_downloaded
        self.download_status_label.setText("Program downloaded" if downloaded else "No program downloaded")
        self.download_status_label.setProperty("downloaded", downloaded)
        # The stylesheet colours the label by this dynamic property.
        self.download_status_label.style().unpolish(self.download_status_label)
        self.download_status_label.style().polish(self.download_status_label)

    def _refresh_recipe_list(self) -> None:
        self.recipe_list.blockSignals(True)
        self.recipe_list.clear()
        for recipe in list_recipe_files(self.profile.recipe_path):
            item = QListWidgetItem(recipe.recipe_number)
            item.setData(Qt.UserRole, recipe)
            self.recipe_list.addItem(item)
        self.recipe_list.setCurrentRow(-1)
        self.recipe_list.blockSignals(False)
        self.workflow.recipe_downloaded = False
        self._update_download_status()

    def _on_recipe_selected(self, row: int) -> None:
        self.workflow.recipe_downloaded = False
        self._update_download_status()
        if row < 0:
            return
        recipe: Recipe = self.recipe_list.item(row).data(Qt.UserRole)
        self.current_recipe = recipe
        self.layout_combo.setCurrentText(recipe.layout.label)
        self.rows_spin.setValue(recipe.rows)
        self.columns_spin.setValue(recipe.columns)
        self.x_spacing_spin.setValue(recipe.x_spacing)
        self.y_spacing_spin.setValue(recipe.y_spacing)
        self.x_start_spin.setValue(recipe.x_start)
        self.y_start_spin.setValue(recipe.y_start)
        self.vac_on_spin.setValue(recipe.vacuum_on)
        self.vac_off_spin.setValue(recipe.vacuum_off)
        self.speed_spin.setValue(recipe.speed_percent)
        self.comments_edit.setPlainText(recipe.comments)

    def _recipe_from_form(self, file_path: str) -> Recipe:
        return Recipe(
            file_path=file_path,
            layout=RecipeLayout.from_label(self.layout_combo.currentText()),
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
            x_spacing=self.x_spacing_spin.value(),
            y_spacing=self.y_spacing_spin.value(),
            x_start=self.x_start_spin.value(),
            y_start=self.y_start_spin.value(),
            vacuum_on=self.vac_on_spin.value(),
            vacuum_off=self.vac_off_spin.value(),
            speed_percent=self.speed_spin.value(),
            comments=self.comments_edit.toPlainText(),
        )

    def _clear_form(self) -> None:
        self.recipe_list.setCurrentRow(-1)
        self.rows_spin.setValue(0)
        self.columns_spin.setValue(0)
        self.x_spacing_spin.setValue(0)
        self.y_spacing_spin.setValue(0)
        self.x_start_spin.setValue(0)
        self.y_start_spin.setValue(0)
        self.vac_on_spin.setValue(0)
        self.vac_off_spin.setValue(0)
        self.speed_spin.setValue(100)
        self.comments_edit.setPlainText("")
        self.workflow.recipe_downloaded = False
        self._update_download_status()

    def _on_save_recipe(self) -> None:
        default_name = self.current_recipe.recipe_number if self.current_recipe else ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Program", os.path.join(self.profile.recipe_path, default_name), "Text files (*.txt)"
        )
        if not path:
            return
        write_recipe_file(path, self._recipe_from_form(path))
        self._refresh_recipe_list()
        self._clear_form()

    def _on_delete_recipe(self) -> None:
        if self.current_recipe is None:
            return
        confirm = QMessageBox.question(
            self, "Confirm Delete", f"Are you sure you want to delete {self.current_recipe.recipe_number}?"
        )
        if confirm == QMessageBox.Yes:
            os.remove(self.current_recipe.file_path)
            self._refresh_recipe_list()

    # --- action buttons ---

    def _on_download_recipe(self) -> None:
        recipe = self.current_recipe or self._recipe_from_form("")
        try:
            self.workflow.download_recipe(recipe)
        except RecipeDownloadRejected as exc:
            QMessageBox.information(self, "Punch Press is Running", str(exc))
        except MotionControllerError as exc:
            self._show_controller_error("send the program to", exc)
        self._update_download_status()

    def _on_home(self) -> None:
        try:
            self.workflow.home()
        except MotionControllerError as exc:
            self._show_controller_error("send the home command to", exc)
            return
        self.homed_status_label.setText("Homing...")
        self._update_download_status()

    def _on_toggle_pause(self) -> None:
        try:
            self.workflow.toggle_pause()
        except MotionControllerError as exc:
            self._show_controller_error("communicate with", exc)
            return
        self._update_pause_button_text()

    def _update_pause_button_text(self) -> None:
        self.toggle_pause_button.setText("UN-PAUSE" if self.workflow.is_paused else "PAUSE")

    def _on_restart(self) -> None:
        try:
            self.workflow.restart()
        except MotionControllerError as exc:
            self._show_controller_error("send the restart command to", exc)
        self._update_download_status()

    def _on_use_current_position(self) -> None:
        self.x_start_spin.setValue(self._last_x_position)
        self.y_start_spin.setValue(self._last_y_position)

    def open_preferences(self) -> None:
        """Opens this machine's settings dialog -- called from the main
        window's Settings menu (moved there from a per-panel button)."""
        dialog = PreferencesDialog(self.machine_store, self.profile, self)
        if dialog.exec() != PreferencesDialog.DialogCode.Accepted:
            return
        self.profile = dialog.selected_profile
        self.workflow.profile = self.profile
        self.machine_name_label.setText(self.profile.name)
        self._refresh_recipe_list()

    # --- polling ---

    def _on_poll_tick(self) -> None:
        try:
            result = self.workflow.poll()
        except MotionControllerError as exc:
            # Previously unhandled -- a connection lost mid-session (cable
            # pulled, controller power-cycled) would raise straight out of
            # this Qt timer callback with no dialog at all. Stop polling so
            # the error isn't shown again every 500ms.
            self.poll_timer.stop()
            self._show_controller_error("communicate with", exc)
            return
        self._last_x_position = result.x_position_inches
        self._last_y_position = result.y_position_inches

        self.x_position_label.setText(f"X: {result.x_position_inches:.3f}")
        self.y_position_label.setText(f"Y: {result.y_position_inches:.3f}")
        self.piece_counter_label.setText(f"Count: {result.piece_count}")
        self.homed_status_label.setText("HOMED" if result.homed else "Not Homed")
        self._update_download_status()  # catches flag changes made inside the workflow

        if result.new_program_error:
            QMessageBox.warning(
                self,
                "Punch Press Program Error",
                "Punch Press Program Error! Please download new program to Punch Press and retry.",
            )

        if result.new_fault is not None:
            self._show_fault_message(result.new_fault)

    def _show_fault_message(self, fault) -> None:
        if fault.fault_type is FaultType.LIGHT_SHIELD:
            QMessageBox.critical(
                self,
                f"{self.profile.name}: LIGHT SHIELD",
                "Light Shield broken. All routines aborted. Remove obstruction from Light Shield "
                "and press restart to continue.",
            )
        elif fault.fault_type is FaultType.ESTOP_OR_THERMAL:
            QMessageBox.critical(
                self,
                f"{self.profile.name}: E-STOP HIT",
                "E-Stop has been hit, or motors have over-heated. Release E-Stop or allow motors to "
                f"cool for 2 hours and repair reason for overheat and press restart button to continue.\n"
                f"SC= {fault.scx},{fault.scy}\nTC= {fault.tc}",
            )
        else:
            QMessageBox.critical(
                self,
                f"{self.profile.name}: Program Error",
                "Motion Control Program Error! Press restart button to attempt restart.\n"
                f"SC= {fault.scx},{fault.scy}\nTC= {fault.tc}\nXQ0= {fault.xq0}, XQ1= {fault.xq1}",
            )

    # --- keyboard jog (dormant, see _ALLOW_KEYBOARD_JOG) ---

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if _ALLOW_KEYBOARD_JOG and self.workflow.state not in (WorkflowState.ESTOP,):
            handled = self._try_start_key_jog(event.key())
            if handled:
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if _ALLOW_KEYBOARD_JOG and self._key_jog_active and event.key() in _JOG_KEYS:
            self.workflow.jog_stop()
            self._key_jog_active = False
            return
        super().keyReleaseEvent(event)

    def _try_start_key_jog(self, key: int) -> bool:
        if self.focusWidget() in (self.comments_edit, self.recipe_list):
            return False
        mapping = _JOG_KEYS.get(key)
        if mapping is None:
            return False
        axis, negative = mapping
        if negative:
            self.workflow.jog_start_negative(axis)
        else:
            self.workflow.jog_start(axis)
        self._key_jog_active = True
        return True
