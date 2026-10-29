import pytest

from ponn_punch_press.core.machine_profile import MachineProfile
from ponn_punch_press.core.recipe import Recipe, RecipeLayout
from ponn_punch_press.core.recipe_mapper import jog_speeds_counts_per_sec
from ponn_punch_press.core.workflow import (
    FaultType,
    PunchPressWorkflow,
    RecipeDownloadRejected,
    WorkflowState,
)
from ponn_punch_press.motion.controller import Axis, MotionControllerCommandError
from ponn_punch_press.motion.simulator import Simulator


class _ControllerWithUndefinedCount(Simulator):
    """Simulator variant where COUNT starts genuinely undefined and stays
    that way across #INIT, matching a real controller that has never run
    this firmware's #AUTO -- unlike the base Simulator, which always
    pre-seeds every #INIT-set variable including COUNT."""

    def __init__(self) -> None:
        super().__init__()
        del self._variables["COUNT"]

    def get_variable(self, name: str) -> float:
        self._require_connected()
        if name == "COUNT" and "COUNT" not in self._variables:
            raise MotionControllerCommandError("Command 'MG COUNT' failed: question mark returned by controller")
        return super().get_variable(name)


@pytest.fixture
def profile():
    return MachineProfile(name="Machine 1", ip_address="192.168.1.10")


@pytest.fixture
def workflow(profile):
    sim = Simulator()
    wf = PunchPressWorkflow(sim, profile)
    wf.start_up("192.168.1.10", "; dummy dmc source")
    return wf


@pytest.fixture
def sample_recipe():
    return Recipe(
        file_path="test.txt",
        layout=RecipeLayout.MATRIX,
        rows=2,
        columns=3,
        x_spacing=1.0,
        y_spacing=1.0,
        x_start=0.0,
        y_start=0.0,
        vacuum_on=0,
        vacuum_off=0,
        comments="",
        speed_percent=75,
    )


def test_start_up_leaves_workflow_paused_and_not_homed(workflow):
    assert workflow.is_paused is True
    assert workflow.recipe_downloaded is False
    assert workflow.state is WorkflowState.NOT_HOMED


def test_start_up_defines_count_when_controller_never_ran_auto(profile):
    sim = _ControllerWithUndefinedCount()
    wf = PunchPressWorkflow(sim, profile)
    wf.start_up("192.168.1.10", "; dummy dmc source")
    assert sim.get_variable("COUNT") == 0.0
    result = wf.poll()
    assert result.piece_count == 0


def test_start_up_does_not_clobber_existing_count(profile):
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_variable("COUNT", 42)
    wf = PunchPressWorkflow(sim, profile)
    wf.start_up("192.168.1.10", "; dummy dmc source")
    assert sim.get_variable("COUNT") == 42


def test_toggle_pause_flips_state_and_sends_command(workflow):
    workflow.toggle_pause()
    assert workflow.is_paused is False
    assert workflow.controller.get_variable("PAUSE") == 0.0

    workflow.toggle_pause()
    assert workflow.is_paused is True
    assert workflow.controller.get_variable("PAUSE") == 1.0


def test_toggle_vacuum_flips_state_and_sends_command(workflow):
    workflow.toggle_vacuum()
    assert workflow.is_vacuum_enabled is True
    assert workflow.controller.get_variable("VACEN") == 1.0


def test_download_recipe_happy_path_sets_controller_variables(workflow, sample_recipe):
    workflow.download_recipe(sample_recipe)

    assert workflow.recipe_downloaded is True
    assert workflow.controller.get_variable("ROWS") == 2
    assert workflow.controller.get_variable("COLUMNS") == 3
    assert workflow.controller.get_variable("LAYOUT") == 1  # RecipeLayout.MATRIX.value
    assert workflow.controller.get_variable("SPEED") == 75


def test_download_recipe_rejected_when_controller_running(workflow, sample_recipe):
    workflow.controller.set_running(True)
    with pytest.raises(RecipeDownloadRejected):
        workflow.download_recipe(sample_recipe)
    assert workflow.recipe_downloaded is False


def test_home_sets_homing_state_until_poll_observes_homed(workflow):
    workflow.home()
    assert workflow.state is WorkflowState.HOMING

    workflow.controller.advance(2.0)  # let the simulated home sequence finish
    result = workflow.poll()

    assert result.homed is True
    assert workflow.state is WorkflowState.PAUSED  # homed + still paused (default)


def test_home_is_ignored_during_estop(workflow):
    workflow.controller.inject_fault("program_error")
    workflow.poll()  # sets workflow.estop = True
    assert workflow.estop is True

    workflow.home()
    assert workflow.state is WorkflowState.ESTOP  # home() was a no-op


def test_jog_start_sends_correct_signed_speed(workflow, profile):
    x_speed, y_speed = jog_speeds_counts_per_sec(profile)

    workflow.jog_start(Axis.X)
    workflow.controller.advance(1.0)
    x, _ = workflow.controller.get_position()
    assert x == pytest.approx(x_speed)

    workflow.jog_stop()
    workflow.jog_start_negative(Axis.Y)
    workflow.controller.advance(1.0)
    _, y = workflow.controller.get_position()
    assert y == pytest.approx(-y_speed)


@pytest.mark.parametrize("steps_per_rev", [800, 1600, 3200, 16384])
def test_position_readout_agrees_with_jog_speed_for_any_steps_per_rev(steps_per_rev):
    """Jogging for 1 s at 80 in/min must read ~1.333 in on the position
    display regardless of steps_per_rev -- the jog command and the readout
    have to use the same counts-per-inch, or speed and position disagree."""
    profile = MachineProfile(name="Machine 1", ip_address="192.168.1.10", steps_per_rev=steps_per_rev)
    wf = PunchPressWorkflow(Simulator(), profile)
    wf.start_up("192.168.1.10", "; dummy dmc source")

    wf.jog_start(Axis.X)
    wf.controller.advance(1.0)
    wf.jog_stop()

    assert wf.poll().x_position_inches == pytest.approx(80 / 60)


def test_jog_is_ignored_during_estop(workflow):
    workflow.controller.inject_fault("program_error")
    workflow.poll()
    assert workflow.estop is True

    workflow.jog_start(Axis.X)
    workflow.controller.advance(1.0)
    x, _ = workflow.controller.get_position()
    assert x == pytest.approx(0.0)  # jog_start was a no-op


def test_restart_clears_estop(workflow):
    workflow.controller.inject_fault("program_error")
    workflow.poll()
    assert workflow.estop is True

    workflow.restart()
    assert workflow.estop is False


def test_restart_puts_the_workflow_back_to_the_init_defaults(workflow, sample_recipe):
    workflow.toggle_pause()  # running (PAUSE=0)
    workflow.download_recipe(sample_recipe)
    assert workflow.is_paused is False and workflow.recipe_downloaded is True

    workflow.restart()

    # #INIT sets PAUSE=1 and zeroes the program variables on the controller.
    assert workflow.is_paused is True
    assert workflow.recipe_downloaded is False


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _mid_init(workflow):
    """The controller as seen ~0.5 s after XQ#INIT: thread 0 is at a `WT 100`
    line (the real fault dump said XQ0=180) and #PAUSBUT (thread 1) has not
    been started yet, so it reads -1 -- same as a crashed thread."""
    workflow.controller.set_variable("_XQ0", 180)
    workflow.controller.set_variable("_XQ1", -1)


def test_restart_does_not_report_a_fault_while_init_is_still_starting_threads(workflow):
    """Regression: pressing RESTART popped "Motion Control Program Error"
    (XQ0=180, XQ1=-1) because the 500 ms poll landed inside #INIT, before it
    reached XQ#PAUSBUT,1."""
    workflow.restart()
    _mid_init(workflow)

    result = workflow.poll()

    assert result.new_fault is None
    assert workflow.estop is False


def test_a_thread_that_dies_right_after_init_is_still_reported(workflow):
    workflow.restart()
    _mid_init(workflow)
    assert workflow.poll().new_fault is None

    workflow.controller.set_variable("_XQ1", 1)  # init finished: thread 1 is up
    assert workflow.poll().new_fault is None

    workflow.controller.set_variable("_XQ1", -1)  # ...and now it has died
    result = workflow.poll()
    assert result.new_fault is not None
    assert workflow.estop is True


def test_an_init_that_never_starts_its_threads_is_reported_after_the_grace_period(workflow):
    clock = _FakeClock()
    workflow._clock = clock
    workflow.restart()
    _mid_init(workflow)

    clock.now += 5
    assert workflow.poll().new_fault is None

    clock.now += 6  # 11 s since restart, thread 1 still absent
    assert workflow.poll().new_fault is not None


def test_start_up_also_gets_the_init_grace_period(profile):
    wf = PunchPressWorkflow(Simulator(), profile)
    wf.start_up("192.168.1.10", "; dummy dmc source")
    _mid_init(wf)

    assert wf.poll().new_fault is None


def test_reset_counter_zeroes_both_vb_and_controller_count(workflow):
    workflow.controller.set_variable("COUNT", 99)
    workflow.reset_counter()
    assert workflow.controller.get_variable("COUNT") == 0
    result = workflow.poll()
    assert result.piece_count == 0


def test_poll_first_call_initializes_zero_count(workflow):
    result = workflow.poll()
    assert result.piece_count == 0


def test_poll_follows_controller_count_when_nonzero(workflow):
    workflow.controller.set_variable("COUNT", 5)
    result = workflow.poll()
    assert result.piece_count == 5


def test_poll_restores_controller_count_after_it_resets_to_zero(workflow):
    workflow.controller.set_variable("COUNT", 5)
    workflow.poll()  # VBCount now tracks 5

    workflow.controller.set_variable("COUNT", 0)  # simulate controller losing its count
    result = workflow.poll()

    assert result.piece_count == 5
    assert workflow.controller.get_variable("COUNT") == 5  # workflow restored it


def test_poll_reports_new_program_error_once(workflow):
    workflow.controller.set_variable("ERROR", 1)
    first = workflow.poll()
    second = workflow.poll()

    assert first.new_program_error is True
    assert second.new_program_error is False


def test_poll_reports_program_error_cleared(workflow):
    workflow.controller.set_variable("ERROR", 1)
    workflow.poll()
    workflow.controller.set_variable("ERROR", 0)
    result = workflow.poll()

    assert result.program_error_cleared is True


def test_poll_detects_light_shield_fault(workflow):
    workflow.controller.inject_fault("light_shield")
    result = workflow.poll()

    assert result.new_fault is not None
    assert result.new_fault.fault_type is FaultType.LIGHT_SHIELD
    assert workflow.estop is True
    assert workflow.state is WorkflowState.ESTOP


def test_poll_detects_estop_or_thermal_fault(workflow):
    workflow.controller.inject_fault("estop_or_thermal")
    result = workflow.poll()
    assert result.new_fault.fault_type is FaultType.ESTOP_OR_THERMAL


def test_poll_detects_program_error_fault(workflow):
    workflow.controller.inject_fault("program_error")
    result = workflow.poll()
    assert result.new_fault.fault_type is FaultType.PROGRAM_ERROR


def test_poll_only_reports_fault_once(workflow):
    workflow.controller.inject_fault("program_error")
    first = workflow.poll()
    second = workflow.poll()

    assert first.new_fault is not None
    assert second.new_fault is None  # already in EStop, not re-reported
