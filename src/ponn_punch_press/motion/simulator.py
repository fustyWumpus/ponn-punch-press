from __future__ import annotations

from .controller import Axis, MotionControllerConnectionError

# Mirrors the variable defaults PONN_PUNCH_PRESS.dmc's #INIT routine sets
# (PAUSE=1, ERROR=0, VACEN=0, HOMED=0, COUNT=0) plus the fault-detection
# variables PollTimer_Tick reads (_XQ0, _XQ1, _AB, SCX, SCY, TC, @IN[4]) and
# RUNNING (legacy: `MG RUNNING`), which DownloadRecipe_Click checks before
# allowing a download.
_DEFAULT_VARIABLES: dict[str, float] = {
    "RUNNING": 0.0,
    "PAUSE": 1.0,
    "ERROR": 0.0,
    "VACEN": 0.0,
    "HOMED": 0.0,
    "COUNT": 0.0,
    "_XQ0": 0.0,
    "_XQ1": 0.0,
    "_AB": 0.0,
    "SCX": 0.0,
    "SCY": 0.0,
    "TC": 0.0,
    "@IN[4]": 0.0,
}

_HOMING_DURATION_SECONDS = 1.0


class Simulator:
    """Fake MotionController for developing/testing without any Galil
    hardware attached. Implements the same surface as
    motion.controller.MotionController structurally (no hardware I/O).

    Models jog-driven position ramping, a small variable table standing in
    for the firmware's variables, a short simulated homing delay, and a test
    hook (inject_fault) to exercise PunchPressWorkflow's E-stop/fault
    classification path.
    """

    def __init__(self) -> None:
        self._connected = False
        self._variables: dict[str, float] = dict(_DEFAULT_VARIABLES)
        self._x_counts = 0.0
        self._y_counts = 0.0
        self._x_velocity = 0.0  # counts/sec
        self._y_velocity = 0.0
        self._homing_seconds_remaining: float | None = None

    # --- connection ---

    def open(self, ip_address: str) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            raise MotionControllerConnectionError("Simulator is not connected -- call open() first")

    # --- program control ---

    def abort(self) -> None:
        self._require_connected()
        self._x_velocity = 0.0
        self._y_velocity = 0.0

    def download_firmware(self, dmc_source: str) -> None:
        self._require_connected()
        # No-op: the simulator fakes the variables/behavior firmware would
        # otherwise provide, rather than interpreting .dmc source itself.

    def run_program(self, label: str) -> None:
        self._require_connected()
        self.execute(f"XQ{label}")

    def execute(self, command: str) -> str:
        self._require_connected()
        for token in command.split(";"):
            self._execute_one(token.strip())
        return ""

    def _execute_one(self, token: str) -> None:
        if not token:
            return
        if token in ("HX", "HX0"):
            self._x_velocity = 0.0
            self._y_velocity = 0.0
        elif token in ("ST", "AM", "MO"):
            pass  # stop / after-motion wait / motor-off: nothing observable to simulate
        elif token in ("CB1", "CB2", "CB3"):
            pass  # clear outputs: nothing observable to simulate
        elif token.startswith("XQ"):
            label = token[2:].strip().lstrip("#")
            self._run_label(label)

    def _run_label(self, label: str) -> None:
        if label == "INIT":
            # Real #INIT deliberately leaves COUNT untouched, so the piece
            # count survives app restarts -- only #AUTO (run on a real
            # power-up/reset) declares it.
            defaults = dict(_DEFAULT_VARIABLES)
            del defaults["COUNT"]
            self._variables.update(defaults)
        elif label == "HOMEALL":
            self._homing_seconds_remaining = _HOMING_DURATION_SECONDS
            self._variables["HOMED"] = 0.0
        elif label == "MAINLP":
            pass  # idle loop -- nothing to simulate

    # --- variables ---

    def set_variable(self, name: str, value: float) -> None:
        self._require_connected()
        self._variables[name] = float(value)

    def get_variable(self, name: str) -> float:
        self._require_connected()
        return self._variables.get(name, 0.0)

    def get_position(self) -> tuple[float, float]:
        self._require_connected()
        return (self._x_counts, self._y_counts)

    # --- motion ---

    def jog(self, axis: Axis, speed: float) -> None:
        self._require_connected()
        if axis is Axis.X:
            self._x_velocity = speed
        else:
            self._y_velocity = speed

    def jog_stop(self) -> None:
        self._require_connected()
        self._x_velocity = 0.0
        self._y_velocity = 0.0

    def set_pause(self, paused: bool) -> None:
        self._require_connected()
        self._variables["PAUSE"] = 1.0 if paused else 0.0

    def set_vacuum(self, enabled: bool) -> None:
        self._require_connected()
        self._variables["VACEN"] = 1.0 if enabled else 0.0

    # --- simulated time / test hooks (not part of the MotionController shape) ---

    def advance(self, elapsed_seconds: float) -> None:
        """Advance simulated time: ramps position from jog velocity and
        progresses any in-flight homing sequence. Call this from tests, or
        from the UI's poll timer, to keep the simulation moving."""
        self._x_counts += self._x_velocity * elapsed_seconds
        self._y_counts += self._y_velocity * elapsed_seconds

        if self._homing_seconds_remaining is not None:
            self._homing_seconds_remaining -= elapsed_seconds
            if self._homing_seconds_remaining <= 0:
                self._homing_seconds_remaining = None
                self._x_counts = 0.0
                self._y_counts = 0.0
                self._x_velocity = 0.0
                self._y_velocity = 0.0
                self._variables["HOMED"] = 1.0

    def inject_fault(self, fault: str) -> None:
        """Test hook: simulate a controller-side fault so
        PunchPressWorkflow._check_for_fault can be exercised without hardware.

        fault: one of "light_shield", "estop_or_thermal", "program_error",
        matching core.workflow.FaultType.
        """
        self._variables["_XQ0"] = -1.0
        if fault == "light_shield":
            self._variables["_AB"] = 0.0
            self._variables["@IN[4]"] = 1.0
        elif fault == "estop_or_thermal":
            self._variables["_AB"] = 0.0
            self._variables["@IN[4]"] = 0.0
        elif fault == "program_error":
            self._variables["_AB"] = 1.0
        else:
            raise ValueError(f"Unknown fault type: {fault!r}")

    def set_running(self, running: bool) -> None:
        """Test hook: simulate the controller reporting a job in progress
        (RUNNING), for testing the download-while-running rejection path."""
        self._variables["RUNNING"] = 1.0 if running else 0.0
