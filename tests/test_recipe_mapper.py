import pytest

from ponn_punch_press.core.machine_profile import DEFAULT_STEPS_PER_REV, MachineProfile
from ponn_punch_press.core.recipe import Recipe, RecipeLayout
from ponn_punch_press.core.recipe_mapper import (
    build_controller_variables,
    counts_to_inches,
    inches_to_counts,
    jog_speeds_counts_per_sec,
    speed_in_per_min_to_counts_per_sec,
)

# 2000 steps per motor revolution, and the machines' 0.5 in/rev default.
STEPS = 2000


def test_default_steps_per_rev_is_2000():
    assert DEFAULT_STEPS_PER_REV == 2000
    assert MachineProfile(name="Machine 1", ip_address="192.168.1.10").steps_per_rev == 2000


def test_counts_per_inch_at_the_defaults():
    # 2000 steps/rev / 0.5 in/rev = 4000 steps per inch
    assert inches_to_counts(1.0, lead=0.5, steps_per_rev=STEPS) == pytest.approx(4000.0)


def test_inches_to_counts_matches_hand_computed_value():
    # 0.375 in * 2000 / 0.5 in/rev = 1500 counts
    assert inches_to_counts(0.375, lead=0.5, steps_per_rev=STEPS) == pytest.approx(1500.0)


def test_counts_to_inches_is_inverse_of_inches_to_counts():
    counts = inches_to_counts(3.0, lead=0.5, steps_per_rev=STEPS)
    assert counts_to_inches(counts, lead=0.5, steps_per_rev=STEPS) == pytest.approx(3.0)


def test_speed_conversion_matches_hand_computed_value():
    # 1100 in/min * 2000 / 0.5 / 60 = 73333.333...
    assert speed_in_per_min_to_counts_per_sec(1100, lead=0.5, steps_per_rev=STEPS) == pytest.approx(
        73333.3333, rel=1e-6
    )


def test_steps_per_rev_scales_distance_and_speed_proportionally():
    base_d = inches_to_counts(2.0, lead=0.5, steps_per_rev=2000)
    base_v = speed_in_per_min_to_counts_per_sec(80, lead=0.5, steps_per_rev=2000)
    assert inches_to_counts(2.0, lead=0.5, steps_per_rev=4000) == pytest.approx(base_d * 2)
    assert speed_in_per_min_to_counts_per_sec(80, lead=0.5, steps_per_rev=4000) == pytest.approx(base_v * 2)


def test_build_controller_variables_from_real_recipe_sample():
    # Values taken from tests/fixtures/recipes/1125X930.TXT
    recipe = Recipe(
        file_path="1125X930.TXT",
        layout=RecipeLayout.STAGGERED,
        rows=9,
        columns=30,
        x_spacing=1.195,
        y_spacing=1.135,
        x_start=0.375,
        y_start=3.000,
        vacuum_on=0,
        vacuum_off=0,
        comments="",
        speed_percent=81,
    )
    profile = MachineProfile(name="Machine 1", ip_address="192.168.1.10")  # defaults: lead 0.5, 2000 steps/rev

    variables = build_controller_variables(recipe, profile)

    assert variables.start_x == pytest.approx(0.375 * STEPS / 0.5)
    assert variables.start_y == pytest.approx(3.000 * STEPS / 0.5)
    assert variables.spacing_x == pytest.approx(1.195 * STEPS / 0.5)
    assert variables.spacing_y == pytest.approx(1.135 * STEPS / 0.5)
    assert variables.rows == 9
    assert variables.columns == 30
    assert variables.layout == 2  # RecipeLayout.STAGGERED.value
    assert variables.speed_percent == 81


def test_recipe_variables_use_the_profiles_own_steps_per_rev():
    recipe = Recipe(
        file_path="r.txt",
        layout=RecipeLayout.MATRIX,
        rows=1,
        columns=1,
        x_spacing=1.0,
        y_spacing=1.0,
        x_start=2.0,
        y_start=0.0,
        vacuum_on=0,
        vacuum_off=0,
        comments="",
    )
    profile = MachineProfile(name="Machine 1", ip_address="192.168.1.10", steps_per_rev=3200)

    variables = build_controller_variables(recipe, profile)

    assert variables.start_x == pytest.approx(2.0 * 3200 / 0.5)


def test_y_axis_speed_uses_y_lead_not_x_lead_unlike_legacy_bug():
    """The legacy Preferences.vb computed MaxYSpeed using XEncoder/XLead
    instead of YEncoder/YLead -- a real bug whenever the leadscrew pitches
    differ between axes. This rewrite must use y_lead for the Y axis."""
    profile = MachineProfile(
        name="Machine 1",
        ip_address="192.168.1.10",
        x_lead=0.5,
        y_lead=0.25,  # deliberately different from x_lead
        max_x_speed=1100,
        max_y_speed=915,
    )
    recipe = Recipe(
        file_path="r.txt",
        layout=RecipeLayout.MATRIX,
        rows=1,
        columns=1,
        x_spacing=1.0,
        y_spacing=1.0,
        x_start=0.0,
        y_start=0.0,
        vacuum_on=0,
        vacuum_off=0,
        comments="",
    )

    variables = build_controller_variables(recipe, profile)

    expected_y_speed = speed_in_per_min_to_counts_per_sec(915, lead=0.25, steps_per_rev=STEPS)
    buggy_legacy_y_speed = speed_in_per_min_to_counts_per_sec(915, lead=0.5, steps_per_rev=STEPS)
    assert variables.y_speed == pytest.approx(expected_y_speed)
    assert variables.y_speed != pytest.approx(buggy_legacy_y_speed)


def test_jog_speeds_use_each_axis_own_lead():
    profile = MachineProfile(
        name="Machine 1",
        ip_address="192.168.1.10",
        x_lead=0.5,
        y_lead=0.25,
        x_jog_speed=80,
        y_jog_speed=80,
    )
    x_jog, y_jog = jog_speeds_counts_per_sec(profile)
    assert x_jog == pytest.approx(speed_in_per_min_to_counts_per_sec(80, lead=0.5, steps_per_rev=STEPS))
    assert y_jog == pytest.approx(speed_in_per_min_to_counts_per_sec(80, lead=0.25, steps_per_rev=STEPS))
    assert x_jog != pytest.approx(y_jog)


def test_jog_speed_command_values_at_the_defaults():
    """Pins the numbers behind the real-machine report that jog was ~9x too
    fast: 80 in/min is now 4266.7 counts/s (it was 43690.7 at 16384/rev)."""
    profile = MachineProfile(name="Machine 2", ip_address="192.168.1.10", x_jog_speed=80, y_jog_speed=6)
    x_jog, y_jog = jog_speeds_counts_per_sec(profile)
    assert x_jog == pytest.approx(80 * 2000 / 0.5 / 60)  # 5333.33
    assert y_jog == pytest.approx(6 * 2000 / 0.5 / 60)  # 400.0
