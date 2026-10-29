from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from ..motion.controller import Axis, MotionController, MotionControllerError
from .machine_profile import MachineProfile
from .recipe import Recipe
from .recipe_mapper import build_controller_variables, counts_to_inches, jog_speeds_counts_per_sec


# #INIT takes about a second (a run of `WT 100` delays) and only starts the
# button-monitor thread (`XQ#PAUSBUT,1`, thread 1) at its very end. Until then
# thread 1 legitimately reads -1 ("not running"), exactly like a crashed
# thread. A fault is only believed once thread 1 has been seen running, or this
# long has passed -- generous so a slow controller isn't misreported, short
# enough that a genuinely failed init is still caught.
_INIT_GRACE_SECONDS = 10.0


class WorkflowState(Enum):
    ESTOP = "estop"
    HOMING = "homing"
    NOT_HOMED = "not_homed"
    PAUSED = "paused"
    RUNNING = "running"


class FaultType(Enum):
    """Mirrors the three distinct error messages MainScreen.vb's
    PollTimer_Tick can show, distinguished by MG _AB (abort button) and
    MG@IN[4] (light shield input) once a task fault (_XQ0/_XQ1 == -1) is
    detected."""

    LIGHT_SHIELD = "light_shield"          # _AB == 0 and @IN[4] == 1
    ESTOP_OR_THERMAL = "estop_or_thermal"  # _AB == 0 and @IN[4] == 0
    PROGRAM_ERROR = "program_error"        # _AB == 1 (abort button pressed)


@dataclass
class FaultInfo:
    fault_type: FaultType
    scx: float
    scy: float
    tc: float
    xq0: float
    xq1: float


@dataclass
class PollResult:
    x_position_inches: float
    y_position_inches: float
    piece_count: int
    homed: bool
    new_program_error: bool = False
    program_error_cleared: bool = False
    new_fault: FaultInfo | None = None


class RecipeDownloadRejected(Exception):
    """Raised when DownloadRecipe is requested while the controller reports
    a job already running (was the "Punch Press is Running" message box)."""


class PunchPressWorkflow:
    """Business logic behind MainScreen.vb, decoupled from any UI toolkit.

    Owns the runtime state that used to live in VariableDeclarations.vb's
    global module (EStop, AllHomed, IsPaused, IsVacEnabled, VBCount, etc.) as
    instance attributes instead, and talks to the controller only through the
    MotionController Protocol so it can be exercised in tests against
    motion.simulator.Simulator with no hardware attached.
    """

    def __init__(self, controller: MotionController, profile: MachineProfile):
        self.controller = controller
        self.profile = profile

        self.is_paused = True  # matches firmware #INIT default (PAUSE=1)
        self.is_vacuum_enabled = False
        self.recipe_downloaded = False
        self.estop = False
        self._all_homed = False
        self._homing_requested = False
        self._prev_error = False
        self._vb_count: int | None = None  # None == "not yet initialized", was VBCount = -1
        self._clock = time.monotonic  # replaceable in tests
        self._init_deadline: float | None = None  # set while #INIT may still be starting threads

    @property
    def state(self) -> WorkflowState:
        if self.estop:
            return WorkflowState.ESTOP
        if self._homing_requested and not self._all_homed:
            return WorkflowState.HOMING
        if not self._all_homed:
            return WorkflowState.NOT_HOMED
        if self.is_paused:
            return WorkflowState.PAUSED
        return WorkflowState.RUNNING

    def start_up(self, ip_address: str, dmc_source: str) -> None:
        """Port of MainScreen_Load: connect, abort any prior motion, download
        firmware, and run #INIT."""
        self.controller.open(ip_address)
        self.controller.abort()
        self.controller.download_firmware(dmc_source)
        self.controller.run_program("#INIT")
        self._init_deadline = self._clock() + _INIT_GRACE_SECONDS
        self._ensure_count_defined()
        self.is_paused = True
        self.recipe_downloaded = False

    def _ensure_count_defined(self) -> None:
        """#INIT deliberately leaves COUNT untouched, so the piece count
        survives across app restarts -- only #AUTO (the firmware's
        power-up/reset entry point) declares it. #AUTO only runs on a real
        controller reset with this exact program already burned to EEPROM,
        which is normally true in production (the controller's been running
        this firmware continuously since its last real boot) but is not
        guaranteed -- e.g. this exact .dmc freshly downloaded to a controller
        that has never run its #AUTO. In that case MG COUNT raises
        (confirmed against real hardware: a DMC2125 with this firmware
        downloaded but never burned/reset returns "question mark returned by
        controller" for it), which would otherwise crash the first poll().
        Only define it when it's genuinely missing, so a controller with a
        real count already going is never clobbered back to 0."""
        try:
            self.controller.get_variable("COUNT")
        except MotionControllerError:
            self.controller.set_variable("COUNT", 0)

    def shut_down(self) -> None:
        """Port of MainScreen_Closed: safe-stop then disconnect."""
        self.controller.execute("HX;ST;AM;MO")
        self.controller.close()

    def jog_start(self, axis: Axis) -> None:
        if self.estop:
            return
        x_speed, y_speed = jog_speeds_counts_per_sec(self.profile)
        speed = x_speed if axis is Axis.X else y_speed
        self.controller.jog(axis, speed)

    def jog_start_negative(self, axis: Axis) -> None:
        if self.estop:
            return
        x_speed, y_speed = jog_speeds_counts_per_sec(self.profile)
        speed = x_speed if axis is Axis.X else y_speed
        self.controller.jog(axis, -speed)

    def jog_stop(self) -> None:
        self.controller.jog_stop()

    def toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        self.controller.set_pause(self.is_paused)

    def toggle_vacuum(self) -> None:
        self.is_vacuum_enabled = not self.is_vacuum_enabled
        self.controller.set_vacuum(self.is_vacuum_enabled)

    def download_recipe(self, recipe: Recipe) -> None:
        """Port of DownloadRecipe_Click. Raises RecipeDownloadRejected if the
        controller reports a job already running."""
        if self.controller.get_variable("RUNNING") != 0:
            raise RecipeDownloadRejected(
                "Punch Press is running a job. Wait until finished before downloading a new program."
            )

        variables = build_controller_variables(recipe, self.profile)
        self.controller.set_variable("STARTX", variables.start_x)
        self.controller.set_variable("STARTY", variables.start_y)
        self.controller.set_variable("SPACINGX", variables.spacing_x)
        self.controller.set_variable("SPACINGY", variables.spacing_y)
        self.controller.set_variable("VACON", variables.vacuum_on)
        self.controller.set_variable("VACOFF", variables.vacuum_off)
        self.controller.set_variable("ROWS", variables.rows)
        self.controller.set_variable("COLUMNS", variables.columns)
        self.controller.set_variable("XSPEED", variables.x_speed)
        self.controller.set_variable("YSPEED", variables.y_speed)
        self.controller.set_variable("LAYOUT", variables.layout)
        self.controller.set_variable("SPEED", variables.speed_percent)
        self.controller.execute("HX0;XQ#MAINLP")
        self.recipe_downloaded = True

    def home(self) -> None:
        if self.estop:
            return
        self.controller.execute("HX0;XQ#HOMEALL")
        self._homing_requested = True
        self.recipe_downloaded = False

    def restart(self) -> None:
        """Port of RestartButton_Click: clear E-stop and reinitialize."""
        self.controller.execute("HX")
        self.controller.execute("ST;AM;MO")
        self.controller.run_program("#INIT")
        self._init_deadline = self._clock() + _INIT_GRACE_SECONDS
        self.estop = False
        # #INIT puts the controller back to PAUSE=1 and zeroes the program
        # variables (STARTX... ROWS...), so mirror that here.
        self.is_paused = True
        self.recipe_downloaded = False

    def reset_counter(self) -> None:
        self._vb_count = 0
        self.controller.set_variable("COUNT", 0)

    def poll(self) -> PollResult:
        """Port of PollTimer_Tick: position/counter/homed readback and fault
        detection."""
        x_counts, y_counts = self.controller.get_position()
        x_inches = counts_to_inches(x_counts, self.profile.x_lead, self.profile.steps_per_rev)
        y_inches = counts_to_inches(y_counts, self.profile.y_lead, self.profile.steps_per_rev)

        dmc_count = int(self.controller.get_variable("COUNT"))
        if dmc_count == 0 and self._vb_count is None:
            self._vb_count = 0
        elif dmc_count == 0 and self._vb_count != 0:
            self.controller.set_variable("COUNT", self._vb_count)
        else:
            self._vb_count = dmc_count

        self._all_homed = bool(self.controller.get_variable("HOMED"))
        if self._all_homed:
            self._homing_requested = False

        new_program_error = False
        program_error_cleared = False
        has_error = bool(self.controller.get_variable("ERROR"))
        if has_error and not self._prev_error:
            new_program_error = True
            self._prev_error = True
        elif self._prev_error and not has_error:
            program_error_cleared = True
            self._prev_error = False

        new_fault = self._check_for_fault()

        return PollResult(
            x_position_inches=x_inches,
            y_position_inches=y_inches,
            piece_count=self._vb_count or 0,
            homed=self._all_homed,
            new_program_error=new_program_error,
            program_error_cleared=program_error_cleared,
            new_fault=new_fault,
        )

    def _check_for_fault(self) -> FaultInfo | None:
        xq0 = self.controller.get_variable("_XQ0")
        xq1 = self.controller.get_variable("_XQ1")

        if self._init_deadline is not None:
            if xq1 != -1 or self._clock() >= self._init_deadline:
                self._init_deadline = None  # init finished (or overran): judge normally
            else:
                return None  # #INIT still starting its threads -- not a fault

        if (xq0 != -1 and xq1 != -1) or self.estop:
            return None

        self.controller.execute("CB1;CB2;CB3")
        self.estop = True

        abort_button = self.controller.get_variable("_AB")
        scx = self.controller.get_variable("SCX")
        scy = self.controller.get_variable("SCY")
        tc = self.controller.get_variable("TC")

        if abort_button == 0:
            light_shield = self.controller.get_variable("@IN[4]")
            fault_type = FaultType.LIGHT_SHIELD if light_shield == 1 else FaultType.ESTOP_OR_THERMAL
        else:
            fault_type = FaultType.PROGRAM_ERROR

        return FaultInfo(fault_type=fault_type, scx=scx, scy=scy, tc=tc, xq0=xq0, xq1=xq1)
