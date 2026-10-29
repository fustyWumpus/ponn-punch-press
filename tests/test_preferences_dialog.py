import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ponn_punch_press.core.machine_profile import MachineProfile
from ponn_punch_press.core.machine_profile_store import MachineProfileStore
from ponn_punch_press.ui.preferences_dialog import PreferencesDialog


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _dialog(tmp_path, **profile_overrides):
    store = MachineProfileStore(base_dir=tmp_path / "settings")
    profile = MachineProfile(
        name="Machine 1", ip_address="192.168.1.58", recipe_path=str(tmp_path), **profile_overrides
    )
    store.save(profile)
    return store, PreferencesDialog(store, profile)


def test_dialog_shows_the_profiles_steps_per_rev(qapp, tmp_path):
    _, dialog = _dialog(tmp_path)
    assert dialog.steps_per_rev_spin.value() == 2000


def test_editing_steps_per_rev_is_saved_and_applied(qapp, tmp_path):
    store, dialog = _dialog(tmp_path)
    dialog.steps_per_rev_spin.setValue(3200)

    dialog._on_accept()

    assert dialog.selected_profile.steps_per_rev == 3200
    assert store.load("Machine 1").steps_per_rev == 3200


def test_saving_the_dialog_does_not_reset_other_settings(qapp, tmp_path):
    """The dialog rebuilds the whole profile from its fields on OK, so any
    field it forgets would silently revert to its default."""
    store, dialog = _dialog(tmp_path, steps_per_rev=3200, x_jog_speed=6.0, x_lead=0.75)

    dialog._on_accept()

    saved = store.load("Machine 1")
    assert saved.steps_per_rev == 3200
    assert saved.x_jog_speed == 6.0
    assert saved.x_lead == 0.75
    assert saved.ip_address == "192.168.1.58"
