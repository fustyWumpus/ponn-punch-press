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


class _FakeGalil:
    """Stands in for the opened gclib handle: records every command and
    answers like the real controllers did (padded integers, \"\\r\\n\" free)."""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.commands: list[str] = []

    def GCommand(self, command: str) -> str:
        self.commands.append(command)
        return self.replies[command]


def test_get_position_reads_the_commanded_position_not_the_encoder():
    """Regression: the readout used TPX/TPY, which stayed 0 on both real
    machines (open-loop steppers, nothing counting on the encoder input)
    while RPX/RPY held the real position."""
    controller = GclibMotionController()
    controller._g = _FakeGalil({"TPX": "0", "TPY": "0", "RPX": "58619", "RPY": "6821"})

    assert controller.get_position() == (58619.0, 6821.0)
    assert controller._g.commands == ["RPX", "RPY"]


def test_get_position_handles_negative_and_padded_replies():
    controller = GclibMotionController()
    controller._g = _FakeGalil({"RPX": "  -1200", "RPY": "       0"})

    assert controller.get_position() == (-1200.0, 0.0)


def test_get_variable_without_open_connection_raises_command_error():
    controller = GclibMotionController()
    with pytest.raises(MotionControllerCommandError):
        controller.get_variable("COUNT")
