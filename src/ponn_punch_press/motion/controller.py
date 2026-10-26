from __future__ import annotations

from enum import Enum
from typing import Protocol


class Axis(Enum):
    X = "X"
    Y = "Y"


class MotionControllerError(Exception):
    """Base exception for motion controller failures."""


class MotionControllerConnectionError(MotionControllerError):
    """Raised when opening/closing the connection to the controller fails."""


class MotionControllerCommandError(MotionControllerError):
    """Raised when a command sent to the controller fails or errors."""


class MotionController(Protocol):
    """Abstraction over the Galil motion controller link.

    Mirrors what MainScreen.vb/Preferences.vb call today via the legacy
    dmc32.dll P/Invoke layer (DMCOpen, DMCClose, DMCCommand, DMCDownloadFile),
    so both GclibMotionController (real hardware, over Ethernet via gclib) and
    Simulator (no hardware needed) implement the exact same surface, and
    PunchPressWorkflow / the UI never need to know which one they're talking
    to. Kept command-oriented (not a raw passthrough everywhere) so magic DMC
    strings stay out of the UI/workflow layers.
    """

    def open(self, ip_address: str) -> None:
        """Connect to the controller at the given Ethernet address."""
        ...

    def close(self) -> None:
        """Disconnect from the controller."""
        ...

    def abort(self) -> None:
        """Abort all motion immediately (was DMCCommand(hDmc, "HX", ...))."""
        ...

    def download_firmware(self, dmc_source: str) -> None:
        """Download a .dmc program's source text to the controller (was
        DMCDownloadFile)."""
        ...

    def run_program(self, label: str) -> None:
        """Run a labeled routine on the controller, e.g. run_program("#INIT")
        (was DMCCommand(hDmc, "XQ#INIT", ...))."""
        ...

    def execute(self, command: str) -> str:
        """Send a raw command string and return the controller's response.

        Used sparingly, for commands not covered by the more specific methods
        below (e.g. compound reset sequences like "HX;ST;AM;MO", or the
        multi-value "HX0;XQ#HOMEALL" home command).
        """
        ...

    def set_variable(self, name: str, value: float) -> None:
        """Set a DMC variable, e.g. set_variable("STARTX", 12288.0) sends
        "STARTX=12288.0"."""
        ...

    def get_variable(self, name: str) -> float:
        """Read a DMC variable via "MG {name}", e.g. get_variable("COUNT")."""
        ...

    def get_position(self) -> tuple[float, float]:
        """Return the current (X, Y) position in encoder counts (TPX/TPY)."""
        ...

    def jog(self, axis: Axis, speed: float) -> None:
        """Begin jogging one axis. Sign of speed indicates direction (was
        JGX=/JGY= followed by BGX/BGY)."""
        ...

    def jog_stop(self) -> None:
        """Stop all jogging motion, both axes (was STXY)."""
        ...

    def set_pause(self, paused: bool) -> None:
        """Pause or resume the punch cycle (was PAUSE=1/PAUSE=0)."""
        ...

    def set_vacuum(self, enabled: bool) -> None:
        """Enable or disable the vacuum system (was VACEN=1/0, plus CB2 when
        disabling)."""
        ...
