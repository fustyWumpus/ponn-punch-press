"""Regression test for a real crash found by actually running the packaged
installer build: launching without --simulate (and without the gclib SDK
installed) used to raise an unhandled ImportError all the way out of main(),
surfacing as a raw "Unhandled exception in script" dialog instead of a
readable message. main() must now catch startup failures and exit(1) cleanly.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from ponn_punch_press import app as app_module


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_main_reports_error_and_exits_cleanly_when_controller_build_fails(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["ponn-punch-press"])  # no --simulate

    def _boom(simulate):
        raise ImportError("The 'gclib' package ... is not installed.")

    monkeypatch.setattr(app_module, "_build_controller", _boom)
    # Isolate via the ProgramData env var, not by monkeypatching
    # app_module._default_program_data_dir directly -- MachineProfileStore
    # (used by main() to save machine profiles, before _build_controller
    # ever raises) resolves its own base directory independently by reading
    # this same env var, so patching only the app-module function left it
    # writing real profile files to the real C:\ProgramData on every test run.
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))

    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *a, **k: shown.setdefault("called", True) or QMessageBox.Ok,
    )

    exit_code = app_module.main()

    assert exit_code == 1
    assert shown.get("called") is True
