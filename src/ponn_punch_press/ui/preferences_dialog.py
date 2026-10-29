from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.machine_profile import MachineProfile
from ..core.machine_profile_store import MachineProfileStore


class PreferencesDialog(QDialog):
    """Port of Preferences.vb, for one fixed machine.

    Each machine now has its own permanent slot in the UI (see
    DualMachineWindow) rather than a single window that could be pointed at
    whichever controller was currently selected, so there's no more
    "Change Machines" flow to reimplement here -- gclib connects directly to
    a controller's IP address, and that address is just another field on
    this machine's profile that can be edited if the network configuration
    changes.
    """

    def __init__(self, store: MachineProfileStore, profile: MachineProfile, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{profile.name} Settings")
        self.store = store
        self.selected_profile = profile

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.ip_address_edit = QLineEdit()
        form.addRow("Controller IP Address:", self.ip_address_edit)

        recipe_path_row = QHBoxLayout()
        self.recipe_path_edit = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_recipe_path)
        recipe_path_row.addWidget(self.recipe_path_edit)
        recipe_path_row.addWidget(browse_button)
        form.addRow("Program Path:", recipe_path_row)

        self.x_lead_spin = self._make_double_spin()
        form.addRow("X Leadscrew Pitch (in/rev):", self.x_lead_spin)
        self.y_lead_spin = self._make_double_spin()
        form.addRow("Y Leadscrew Pitch (in/rev):", self.y_lead_spin)
        self.steps_per_rev_spin = QSpinBox()
        self.steps_per_rev_spin.setRange(1, 1_000_000)
        self.steps_per_rev_spin.setToolTip(
            "Pulses the controller sends per motor revolution: full steps per rev x microstepping "
            "(e.g. 200-step motor at 1/10 microstepping = 2000). Scales every speed and distance "
            "sent to this machine, and the X/Y position readout."
        )
        form.addRow("Steps per Motor Revolution:", self.steps_per_rev_spin)
        self.max_x_speed_spin = self._make_double_spin(maximum=5000)
        form.addRow("Max X Speed (in/min):", self.max_x_speed_spin)
        self.max_y_speed_spin = self._make_double_spin(maximum=5000)
        form.addRow("Max Y Speed (in/min):", self.max_y_speed_spin)
        self.x_jog_speed_spin = self._make_double_spin(maximum=5000)
        form.addRow("X Jog Speed (in/min):", self.x_jog_speed_spin)
        self.y_jog_speed_spin = self._make_double_spin(maximum=5000)
        form.addRow("Y Jog Speed (in/min):", self.y_jog_speed_spin)
        layout.addLayout(form)

        self._load_fields(profile)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_double_spin(self, maximum: float = 100.0) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0.0, maximum)
        return spin

    def _load_fields(self, profile: MachineProfile) -> None:
        self.ip_address_edit.setText(profile.ip_address)
        self.recipe_path_edit.setText(profile.recipe_path)
        self.x_lead_spin.setValue(profile.x_lead)
        self.y_lead_spin.setValue(profile.y_lead)
        self.steps_per_rev_spin.setValue(profile.steps_per_rev)
        self.max_x_speed_spin.setValue(profile.max_x_speed)
        self.max_y_speed_spin.setValue(profile.max_y_speed)
        self.x_jog_speed_spin.setValue(profile.x_jog_speed)
        self.y_jog_speed_spin.setValue(profile.y_jog_speed)

    def _on_browse_recipe_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Program Directory", self.recipe_path_edit.text())
        if path:
            self.recipe_path_edit.setText(path)

    def _on_accept(self) -> None:
        if not os.path.isdir(self.recipe_path_edit.text()):
            QMessageBox.warning(
                self,
                "Source directory does not exist.",
                "Program directory does not exist. Files will be saved to C:\\",
            )
            self.recipe_path_edit.setText("C:\\")

        self.selected_profile = MachineProfile(
            name=self.selected_profile.name,
            ip_address=self.ip_address_edit.text(),
            recipe_path=self.recipe_path_edit.text(),
            x_lead=self.x_lead_spin.value(),
            y_lead=self.y_lead_spin.value(),
            steps_per_rev=self.steps_per_rev_spin.value(),
            max_x_speed=self.max_x_speed_spin.value(),
            max_y_speed=self.max_y_speed_spin.value(),
            x_jog_speed=self.x_jog_speed_spin.value(),
            y_jog_speed=self.y_jog_speed_spin.value(),
        )
        self.store.save(self.selected_profile)
        self.accept()
