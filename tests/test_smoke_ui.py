"""End-to-end smoke test: drive the whole dual-machine PySide6 app against
two independent Simulator motion backends, with no real Galil hardware,
exercising the full operator workflow (load recipe, jog, download, home,
pause, simulated fault) on BOTH machines independently and asserting nothing
crashes or leaks state between panels.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from ponn_punch_press.core.machine_profile import MachineProfile
from ponn_punch_press.core.machine_profile_store import MachineProfileStore
from ponn_punch_press.core.recipe_io import parse_recipe_file
from ponn_punch_press.core.workflow import PunchPressWorkflow
from ponn_punch_press.motion.simulator import Simulator
from ponn_punch_press.ui.dual_machine_window import DualMachineWindow, _saved_geometry_is_sane
from ponn_punch_press.ui.machine_panel import MachinePanel

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "recipes")
DMC_SOURCE = "; smoke test dmc source, never interpreted by the Simulator"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Prevent QMessageBox popups from blocking the (headless) test run;
    record how many times each severity was shown instead."""
    calls = {"critical": 0, "warning": 0, "information": 0}
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: calls.__setitem__("critical", calls["critical"] + 1) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: calls.__setitem__("warning", calls["warning"] + 1) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.__setitem__("information", calls["information"] + 1) or QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    return calls


def _make_panel(tmp_path, name: str, recipe_files: list[str]) -> MachinePanel:
    import shutil

    recipe_dir = tmp_path / name.replace(" ", "_")
    recipe_dir.mkdir()
    for filename in recipe_files:
        shutil.copy(os.path.join(FIXTURES_DIR, filename), recipe_dir / filename)

    store = MachineProfileStore(base_dir=tmp_path / f"settings_{name.replace(' ', '_')}")
    profile = MachineProfile(name=name, ip_address="192.168.1.10", recipe_path=str(recipe_dir))
    store.save(profile)

    controller = Simulator()
    workflow = PunchPressWorkflow(controller, profile)
    return MachinePanel(workflow, profile, DMC_SOURCE, store)


@pytest.fixture
def window(qapp, tmp_path):
    panel_1 = _make_panel(tmp_path, "Machine 1", ["machine1_75037.txt", "machine1_595X073.txt"])
    panel_2 = _make_panel(tmp_path, "Machine 2", ["machine2_NOVA150.txt", "machine2_S275_WELCH.txt"])

    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()
    qapp.processEvents()
    yield win
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_both_panels_load_their_own_independent_recipe_lists(window):
    assert window.panel_machine_1.recipe_list.count() == 2
    assert window.panel_machine_2.recipe_list.count() == 2


def test_panels_are_arranged_machine2_left_machine1_right(window):
    splitter = window.splitter
    assert splitter.widget(0) is window.panel_machine_2
    assert splitter.widget(1) is window.panel_machine_1


def test_selecting_recipe_on_one_panel_does_not_affect_the_other(window):
    window.panel_machine_1.recipe_list.setCurrentRow(0)
    assert window.panel_machine_1.current_recipe is not None
    assert window.panel_machine_2.current_recipe is None


def test_download_recipe_then_poll_updates_status_independently(window):
    window.panel_machine_1.recipe_list.setCurrentRow(0)
    window.panel_machine_1._on_download_recipe()
    assert window.panel_machine_1.workflow.recipe_downloaded is True
    assert window.panel_machine_2.workflow.recipe_downloaded is False

    window.panel_machine_1._on_poll_tick()
    assert window.panel_machine_1.piece_counter_label.text() == "Count: 0"


def test_download_status_label_follows_the_download_state(window):
    panel_1 = window.panel_machine_1
    panel_2 = window.panel_machine_2
    assert panel_1.download_status_label.text() == "No program downloaded"

    panel_1.recipe_list.setCurrentRow(0)
    panel_1._on_download_recipe()
    assert panel_1.download_status_label.text() == "Program downloaded"
    assert panel_1.download_status_label.property("downloaded") is True
    assert panel_2.download_status_label.text() == "No program downloaded"

    # Picking a different program means the controller no longer holds it.
    panel_1.recipe_list.setCurrentRow(1)
    assert panel_1.download_status_label.text() == "No program downloaded"
    assert panel_1.download_status_label.property("downloaded") is False


def test_jog_arrows_follow_the_theme_so_they_stay_visible_in_light_and_dark(window):
    from PySide6.QtGui import QColor, QPalette

    panel = window.panel_machine_1

    def arrow_colour() -> str:
        image = panel.jog_right_button.icon().pixmap(64, 64).toImage()
        return image.pixelColor(16, 32).name()  # inside the arrow's stem

    for colour in ("#101010", "#f0f0f0"):  # a light theme's text, a dark theme's text
        palette = panel.palette()
        palette.setColor(QPalette.ButtonText, QColor(colour))
        panel.setPalette(palette)
        assert arrow_colour() == colour


def test_every_button_flashes_when_clicked_then_clears(window, qapp):
    from PySide6.QtWidgets import QPushButton

    buttons = window.findChildren(QPushButton)
    assert window.exit_button in buttons
    assert window.panel_machine_1.download_button in buttons
    assert window.panel_machine_2.jog_left_button in buttons

    button = window.panel_machine_1.reset_counter_button
    assert not button.property("flash")
    button.click()
    assert button.property("flash") is True

    for _ in range(40):  # the flash is ~300 ms; let the single-shot timer fire
        qapp.processEvents()
        QTest.qWait(10)
    assert button.property("flash") is False


def test_jog_on_machine1_does_not_move_machine2(window):
    window.panel_machine_1.jog_right_button.pressed.emit()
    window.panel_machine_1.workflow.controller.advance(1.0)
    window.panel_machine_1.jog_right_button.released.emit()

    window.panel_machine_1._on_poll_tick()
    window.panel_machine_2._on_poll_tick()
    assert window.panel_machine_1.x_position_label.text() != "X: 0.000"
    assert window.panel_machine_2.x_position_label.text() == "X: 0.000"


@pytest.mark.parametrize(
    "button_name, axis_index, expected_sign",
    [
        ("jog_forward_button", 1, +1),
        ("jog_back_button", 1, -1),
        ("jog_right_button", 0, +1),
        ("jog_left_button", 0, -1),
    ],
)
def test_jog_buttons_move_in_the_expected_direction(window, button_name, axis_index, expected_sign):
    """Forward = +Y, back = -Y, right = +X, left = -X. Forward/back were
    reversed on the real machines before this was pinned down."""
    panel = window.panel_machine_1
    button = getattr(panel, button_name)

    button.pressed.emit()
    panel.workflow.controller.advance(1.0)
    button.released.emit()

    position = panel.workflow.controller.get_position()[axis_index]
    assert position * expected_sign > 0


def test_home_axes_reaches_homed_after_polling(window):
    window.panel_machine_2._on_home()
    assert window.panel_machine_2.homed_status_label.text() == "Homing..."

    window.panel_machine_2.workflow.controller.advance(2.0)
    window.panel_machine_2._on_poll_tick()

    assert window.panel_machine_2.homed_status_label.text() == "HOMED"
    assert window.panel_machine_1.homed_status_label.text() == "Not Homed"


def test_pause_toggle_updates_button_label(window):
    assert window.panel_machine_1.toggle_pause_button.text() == "UN-PAUSE"
    window.panel_machine_1._on_toggle_pause()
    assert window.panel_machine_1.toggle_pause_button.text() == "PAUSE"
    assert window.panel_machine_1.workflow.controller.get_variable("PAUSE") == 0.0
    assert window.panel_machine_2.toggle_pause_button.text() == "UN-PAUSE"


def test_simulated_fault_on_one_machine_does_not_estop_the_other(window, no_modal_dialogs):
    window.panel_machine_1.workflow.controller.inject_fault("light_shield")
    window.panel_machine_1._on_poll_tick()

    assert window.panel_machine_1.workflow.estop is True
    assert window.panel_machine_2.workflow.estop is False
    assert no_modal_dialogs["critical"] == 1


def test_restart_clears_estop(window):
    window.panel_machine_2.workflow.controller.inject_fault("program_error")
    window.panel_machine_2._on_poll_tick()
    assert window.panel_machine_2.workflow.estop is True

    window.panel_machine_2._on_restart()
    assert window.panel_machine_2.workflow.estop is False


def test_selecting_recipe_populates_speed_field(window):
    window.panel_machine_1.recipe_list.setCurrentRow(0)
    recipe = window.panel_machine_1.current_recipe
    assert window.panel_machine_1.speed_spin.value() == recipe.speed_percent


def test_download_sends_speed_variable_to_correct_machine_only(window):
    window.panel_machine_1.recipe_list.setCurrentRow(0)  # machine1_595X073.txt sorts first, Speed: 81
    window.panel_machine_1._on_download_recipe()

    assert window.panel_machine_1.workflow.controller.get_variable("SPEED") == 81
    assert window.panel_machine_2.workflow.controller.get_variable("SPEED") == 0.0


def test_save_and_delete_recipe_round_trip(window, tmp_path):
    window.panel_machine_1.recipe_list.setCurrentRow(0)
    window.panel_machine_1.rows_spin.setValue(99)

    from PySide6.QtWidgets import QFileDialog

    new_path = str(tmp_path / "Machine_1" / "NEW_RECIPE.txt")
    original_get_save = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (new_path, "Text files (*.txt)"))
    try:
        window.panel_machine_1._on_save_recipe()
    finally:
        QFileDialog.getSaveFileName = original_get_save

    assert window.panel_machine_1.recipe_list.count() == 3
    saved = parse_recipe_file(new_path)
    assert saved.rows == 99

    for i in range(window.panel_machine_1.recipe_list.count()):
        if window.panel_machine_1.recipe_list.item(i).text() == "NEW_RECIPE":
            window.panel_machine_1.recipe_list.setCurrentRow(i)
            break
    window.panel_machine_1._on_delete_recipe()
    assert window.panel_machine_1.recipe_list.count() == 2


def _make_panel_with_store(store: MachineProfileStore, name: str) -> MachinePanel:
    profile = MachineProfile(name=name, ip_address="192.168.1.10", recipe_path=".")
    controller = Simulator()
    workflow = PunchPressWorkflow(controller, profile)
    return MachinePanel(workflow, profile, DMC_SOURCE, store)


def test_closing_window_saves_geometry_to_the_shared_store(qapp, tmp_path):
    # Mirrors app.py's real setup: both panels share one MachineProfileStore
    # (restore_geometry_or_maximize/closeEvent read and write via
    # panel_machine_1's store specifically, so this is what makes that valid).
    store = MachineProfileStore(base_dir=tmp_path / "shared_settings")
    panel_1 = _make_panel_with_store(store, "Machine 1")
    panel_2 = _make_panel_with_store(store, "Machine 2")
    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()
    qapp.processEvents()

    assert store.get_window_geometry() is None
    win.close()
    assert store.get_window_geometry() is not None


def test_restore_geometry_or_maximize_uses_saved_geometry_when_present(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "shared_settings")
    panel_1 = _make_panel_with_store(store, "Machine 1")
    panel_2 = _make_panel_with_store(store, "Machine 2")
    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()
    qapp.processEvents()
    win.close()  # saves geometry into the shared store

    panel_1b = _make_panel_with_store(store, "Machine 1")
    panel_2b = _make_panel_with_store(store, "Machine 2")
    win2 = DualMachineWindow(panel_machine_2=panel_2b, panel_machine_1=panel_1b)
    win2.start_up()

    restored = win2.restore_geometry_or_maximize()

    assert restored is True
    # Regression: restoreGeometry() alone never shows the window, so a
    # successful restore used to leave the app running with no visible window.
    assert win2.isVisible() is True
    win2.panel_machine_1.shut_down()
    win2.panel_machine_2.shut_down()


def test_restore_geometry_or_maximize_falls_back_to_maximize_on_first_run(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "fresh_settings")
    panel_1 = _make_panel_with_store(store, "Machine 1")
    panel_2 = _make_panel_with_store(store, "Machine 2")
    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()

    restored = win.restore_geometry_or_maximize()

    assert restored is False
    assert win.isVisible() is True
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


# Captured from a real config.json: a window maximized on screen index 1 (a
# second monitor sitting above the primary, so negative Y coordinates).
_SECOND_MONITOR_GEOMETRY_BASE64 = (
    "AdnQywADAAAAAAAA///7wAAABND///7eAAACgP///N0AAAcD"
    "////sgAAAAECAAAAB4AAAAAA///73wAABND///7e"
)


def _geometry_blob(frame=(10, 10, 500, 400), screen=0, maximized=0, fullscreen=0, screen_width=800) -> bytes:
    """Builds a QWidget::saveGeometry() blob (Qt 6 layout)."""
    import struct

    return (
        struct.pack(">IHH", 0x01D9D0CB, 3, 0)
        + struct.pack(">iiii", *frame)
        + struct.pack(">iiii", *frame)
        + struct.pack(">i", screen)
        + struct.pack(">BB", maximized, fullscreen)
        + struct.pack(">i", screen_width)
    )


def test_saved_geometry_is_sane_accepts_an_on_screen_blob(qapp):
    assert _saved_geometry_is_sane(_geometry_blob()) is True
    assert _saved_geometry_is_sane(_geometry_blob(maximized=2)) is True


def test_saved_geometry_is_sane_accepts_fullscreen(qapp):
    # Fullscreen is a real mode now (F11), so a window closed in it must be
    # restorable.
    assert _saved_geometry_is_sane(_geometry_blob(fullscreen=4)) is True


def test_saved_geometry_is_sane_rejects_a_frame_on_no_attached_screen(qapp):
    assert _saved_geometry_is_sane(_geometry_blob(frame=(0, -1088, 1232, -290))) is False


def test_saved_geometry_is_sane_rejects_truncated_or_foreign_data(qapp):
    assert _saved_geometry_is_sane(b"") is False
    assert _saved_geometry_is_sane(_geometry_blob()[:30]) is False
    assert _saved_geometry_is_sane(b"\x00" * 60) is False


def test_saved_geometry_is_sane_rejects_a_second_monitor_that_is_not_attached(qapp):
    """That second monitor's frame sits at negative Y; with only the primary
    attached (as here) restoring it would put the window off-screen."""
    from base64 import b64decode

    assert _saved_geometry_is_sane(b64decode(_SECOND_MONITOR_GEOMETRY_BASE64)) is False


def test_saved_geometry_is_sane_accepts_a_freshly_saved_blob(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "good_geometry_settings")
    panel_1 = _make_panel_with_store(store, "Machine 1")
    panel_2 = _make_panel_with_store(store, "Machine 2")
    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()
    win.showMaximized()  # realistic: geometry is normally saved from a shown window
    qapp.processEvents()

    assert _saved_geometry_is_sane(bytes(win.saveGeometry())) is True
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def _new_window(store, qapp):
    win = DualMachineWindow(
        panel_machine_2=_make_panel_with_store(store, "Machine 2"),
        panel_machine_1=_make_panel_with_store(store, "Machine 1"),
    )
    win.start_up()
    return win


def test_fullscreen_menu_action_toggles_fullscreen_and_stays_in_sync(qapp, tmp_path):
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_toggle"), qapp)
    win.show()
    qapp.processEvents()
    assert win.isFullScreen() is False
    assert win.fullscreen_action.isChecked() is False
    assert win.fullscreen_action.shortcut().toString() == "F11"

    win.fullscreen_action.trigger()
    qapp.processEvents()
    assert win.isFullScreen() is True
    assert win.fullscreen_action.isChecked() is True

    win.fullscreen_action.trigger()
    qapp.processEvents()
    assert win.isFullScreen() is False
    assert win.fullscreen_action.isChecked() is False
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_fullscreen_toggle_follows_the_real_window_state_not_the_check_mark(qapp, tmp_path):
    """If the menu's check mark ever disagrees with the window, the toggle
    used to trust the mark: the click re-requested the state the window was
    already in, and "it won't leave fullscreen"."""
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_desync"), qapp)
    win.show()
    win.set_fullscreen(True)
    qapp.processEvents()
    assert win.isFullScreen() is True

    win.fullscreen_action.setChecked(False)  # out of sync; emits nothing
    win.fullscreen_action.trigger()  # the mark flips to True, window is already fullscreen
    qapp.processEvents()

    assert win.isFullScreen() is False
    assert win.fullscreen_action.isChecked() is False
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_escape_leaves_fullscreen_and_does_nothing_otherwise(qapp, tmp_path):
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_escape"), qapp)
    win.show()
    qapp.processEvents()

    win._leave_fullscreen_shortcut.activated.emit()  # not fullscreen: no effect
    assert win.isFullScreen() is False

    win.set_fullscreen(True)
    qapp.processEvents()
    win._leave_fullscreen_shortcut.activated.emit()
    qapp.processEvents()
    assert win.isFullScreen() is False
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_the_exit_recheck_does_not_undo_a_quick_re_entry(qapp, tmp_path):
    """F11, F11 within the re-check delay: the first exit's delayed check must
    not see the *new* fullscreen window and throw it out again."""
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_quick"), qapp)
    win.show()
    win.set_fullscreen(True)
    win.set_fullscreen(False)
    win.set_fullscreen(True)

    QTest.qWait(800)  # well past the re-check delay

    assert win.isFullScreen() is True
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_leaving_fullscreen_is_retried_if_the_first_attempt_is_ignored(qapp, tmp_path, monkeypatch):
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_retry"), qapp)
    win.show()
    win.set_fullscreen(True)
    qapp.processEvents()

    monkeypatch.setattr(win, "showMaximized", lambda: None)  # the window manager ignores it
    monkeypatch.setattr(win, "showNormal", lambda: None)
    win.set_fullscreen(False)
    assert win.isFullScreen() is True

    win._ensure_left_fullscreen()  # what the delayed re-check does
    assert win.isFullScreen() is False
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_exit_button_sits_in_the_top_right_corner_of_the_menu_bar(qapp, tmp_path):
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "exit_pos"), qapp)
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()

    assert win.menuBar().cornerWidget(Qt.TopRightCorner) is win.exit_button
    assert win.exit_button.text() == "Exit"
    assert win.exit_button.isVisible() is True
    # Right-aligned against the window's right edge, within the menu bar strip.
    right_edge = win.exit_button.mapTo(win, win.exit_button.rect().topRight()).x()
    assert right_edge >= win.width() - 4
    assert win.exit_button.mapTo(win, win.exit_button.rect().topLeft()).y() <= win.menuBar().height()
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_clicking_exit_closes_the_window_saves_geometry_and_stops_polling(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "exit_click")
    win = _new_window(store, qapp)
    win.show()
    qapp.processEvents()
    assert store.get_window_geometry() is None
    assert win.panel_machine_1.poll_timer.isActive() is True

    win.exit_button.click()
    qapp.processEvents()

    assert win.isVisible() is False
    assert store.get_window_geometry() is not None
    assert win.panel_machine_1.poll_timer.isActive() is False
    assert win.panel_machine_2.poll_timer.isActive() is False


def test_leaving_fullscreen_returns_to_the_previous_maximized_or_normal_state(qapp, tmp_path):
    win = _new_window(MachineProfileStore(base_dir=tmp_path / "fs_return"), qapp)
    win.showMaximized()
    qapp.processEvents()
    win.set_fullscreen(True)
    qapp.processEvents()
    win.set_fullscreen(False)
    qapp.processEvents()
    assert win.isMaximized() is True

    win.showNormal()
    qapp.processEvents()
    win.set_fullscreen(True)
    qapp.processEvents()
    win.set_fullscreen(False)
    qapp.processEvents()
    assert win.isMaximized() is False
    assert win.isFullScreen() is False
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()


def test_a_window_closed_in_fullscreen_reopens_in_fullscreen(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "fs_restore")
    win = _new_window(store, qapp)
    win.show()
    win.set_fullscreen(True)
    qapp.processEvents()
    win.close()

    win2 = _new_window(store, qapp)
    assert win2.restore_geometry_or_maximize() is True
    qapp.processEvents()
    assert win2.isVisible() is True
    assert win2.isFullScreen() is True
    assert win2.fullscreen_action.isChecked() is True
    win2.panel_machine_1.shut_down()
    win2.panel_machine_2.shut_down()


def test_restore_geometry_or_maximize_falls_back_and_shows_when_saved_geometry_is_unusable(qapp, tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "unusable_geometry_settings")
    store.set_window_geometry(_SECOND_MONITOR_GEOMETRY_BASE64)
    panel_1 = _make_panel_with_store(store, "Machine 1")
    panel_2 = _make_panel_with_store(store, "Machine 2")
    win = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    win.start_up()

    restored = win.restore_geometry_or_maximize()
    qapp.processEvents()

    assert restored is False
    assert win.isVisible() is True
    assert win.isFullScreen() is False
    assert win.width() > 0
    assert win.height() > 0
    win.panel_machine_1.shut_down()
    win.panel_machine_2.shut_down()
