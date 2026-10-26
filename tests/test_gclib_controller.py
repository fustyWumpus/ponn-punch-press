"""Integration test against the REAL gclib library (not a mock) -- skipped
entirely if gclib isn't installed in this environment. No real Galil
controller is available, so these tests only exercise the "not connected" /
"connection failed" paths, but that's enough to confirm the real gclib
Python API shape (gclib.py(), GOpen, GCommand, GProgramDownload, GClose,
gclib.GclibError) matches what GclibMotionController assumes -- verified
directly in this environment on 2026-07-06 against gclib 2.2.1 / Python
wrapper 1.0.1.
"""
import pytest

gclib = pytest.importorskip("gclib")

from ponn_punch_press.motion.controller import (
    MotionControllerCommandError,
    MotionControllerConnectionError,
)
from ponn_punch_press.motion.gclib_controller import GclibMotionController

# Reserved/unroutable address: fails fast without a real controller present.
_UNREACHABLE_IP = "192.168.255.254"


def test_constructs_without_error_when_gclib_installed():
    GclibMotionController()


def test_open_against_unreachable_address_raises_connection_error():
    controller = GclibMotionController()
    with pytest.raises(MotionControllerConnectionError):
        controller.open(_UNREACHABLE_IP)


def test_execute_without_open_connection_raises_command_error():
    controller = GclibMotionController()
    with pytest.raises(MotionControllerCommandError):
        controller.execute("MG 1")


def test_download_firmware_without_open_connection_raises_command_error():
    controller = GclibMotionController()
    with pytest.raises(MotionControllerCommandError):
        controller.download_firmware('MG "hello"')


def test_get_variable_without_open_connection_raises_command_error():
    controller = GclibMotionController()
    with pytest.raises(MotionControllerCommandError):
        controller.get_variable("COUNT")
