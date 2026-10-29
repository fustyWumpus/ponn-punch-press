import pytest

from ponn_punch_press.motion.controller import Axis, MotionControllerConnectionError
from ponn_punch_press.motion.simulator import Simulator


def test_operations_require_open_first():
    sim = Simulator()
    with pytest.raises(MotionControllerConnectionError):
        sim.get_position()


def test_open_close_round_trip():
    sim = Simulator()
    sim.open("192.168.1.10")
    assert sim.get_position() == (0.0, 0.0)
    sim.close()
    with pytest.raises(MotionControllerConnectionError):
        sim.get_position()


def test_jog_ramps_position_over_simulated_time():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.jog(Axis.X, 1000.0)  # counts/sec
    sim.advance(2.0)
    x, y = sim.get_position()
    assert x == pytest.approx(2000.0)
    assert y == pytest.approx(0.0)


def test_jog_stop_freezes_position():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.jog(Axis.Y, 500.0)
    sim.advance(1.0)
    sim.jog_stop()
    sim.advance(5.0)
    x, y = sim.get_position()
    assert y == pytest.approx(500.0)


def test_homing_sequence_completes_after_simulated_delay():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.jog(Axis.X, 100.0)
    sim.advance(1.0)  # move off of (0, 0) first
    sim.run_program("#HOMEALL")
    assert sim.get_variable("HOMED") == 0.0

    sim.advance(0.5)
    assert sim.get_variable("HOMED") == 0.0  # not yet, homing takes ~1 simulated second

    sim.advance(0.6)
    assert sim.get_variable("HOMED") == 1.0
    assert sim.get_position() == (0.0, 0.0)


def test_run_init_resets_variables_to_defaults():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_variable("ERROR", 1.0)

    sim.run_program("#INIT")

    assert sim.get_variable("ERROR") == 0.0


def test_run_init_does_not_reset_count():
    """Real #INIT deliberately leaves COUNT untouched, so the piece count
    survives app restarts -- only #AUTO (run on a real power-up/reset)
    declares it."""
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_variable("COUNT", 42.0)

    sim.run_program("#INIT")

    assert sim.get_variable("COUNT") == 42.0


def test_set_and_get_variable_round_trip():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_variable("STARTX", 12288.0)
    assert sim.get_variable("STARTX") == 12288.0


def test_get_unknown_variable_defaults_to_zero():
    sim = Simulator()
    sim.open("192.168.1.10")
    assert sim.get_variable("SOMETHING_NEVER_SET") == 0.0


def test_execute_compound_command_string_is_tokenized():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.jog(Axis.X, 100.0)
    sim.execute("HX0;XQ#HOMEALL")
    assert sim.get_variable("HOMED") == 0.0
    x, _ = sim.get_position()
    assert x == pytest.approx(0.0)  # HX0 stopped the jog before it could ramp


def test_set_pause_and_set_vacuum_update_variables():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_pause(False)
    assert sim.get_variable("PAUSE") == 0.0
    sim.set_vacuum(True)
    assert sim.get_variable("VACEN") == 1.0


def test_inject_fault_light_shield():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.inject_fault("light_shield")
    assert sim.get_variable("_XQ0") == -1.0
    assert sim.get_variable("_AB") == 0.0
    assert sim.get_variable("@IN[4]") == 1.0


def test_inject_fault_program_error():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.inject_fault("program_error")
    assert sim.get_variable("_AB") == 1.0


def test_inject_fault_rejects_unknown_type():
    sim = Simulator()
    sim.open("192.168.1.10")
    with pytest.raises(ValueError):
        sim.inject_fault("not_a_real_fault")


def test_set_running_toggles_running():
    sim = Simulator()
    sim.open("192.168.1.10")
    sim.set_running(True)
    assert sim.get_variable("RUNNING") == 1.0
    sim.set_running(False)
    assert sim.get_variable("RUNNING") == 0.0
