import pytest

from ponn_punch_press.core.machine_profile import MachineProfile
from ponn_punch_press.core.recipe import Recipe, RecipeLayout
from ponn_punch_press.core.recipe_mapper import (
    build_controller_variables,
    counts_to_inches,
    inches_to_counts,
    jog_speeds_counts_per_sec,
    speed_in_per_min_to_counts_per_sec,
)

ENCODER = 16384


def test_inches_to_counts_matches_hand_computed_value():
    # 0.375 in * 16384 / 0.5 in/rev = 12288 counts
    assert inches_to_counts(0.375, lead=0.5) == pytest.approx(12288.0)


def test_counts_to_inches_is_inverse_of_inches_to_counts():
    counts = inches_to_counts(3.0, lead=0.5)
    assert counts_to_inches(counts, lead=0.5) == pytest.approx(3.0)


def test_speed_conversion_matches_hand_computed_value():
    # 1100 in/min * 16384 / 0.5 / 60 = 600746.6666...
    assert speed_in_per_min_to_counts_per_sec(1100, lead=0.5) == pytest.approx(600746.6666, rel=1e-6)


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
    profile = MachineProfile(name="Machine 1", ip_address="192.168.1.10")  # defaults: x_lead=y_lead=0.5

    variables = build_controller_variables(recipe, profile)

    assert variables.start_x == pytest.approx(0.375 * ENCODER / 0.5)
    assert variables.start_y == pytest.approx(3.000 * ENCODER / 0.5)
    assert variables.spacing_x == pytest.approx(1.195 * ENCODER / 0.5)
    assert variables.spacing_y == pytest.approx(1.135 * ENCODER / 0.5)
    assert variables.rows == 9
    assert variables.columns == 30
    assert variables.layout == 2  # RecipeLayout.STAGGERED.value
    assert variables.speed_percent == 81


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

    expected_y_speed = speed_in_per_min_to_counts_per_sec(915, lead=0.25)
    buggy_legacy_y_speed = speed_in_per_min_to_counts_per_sec(915, lead=0.5)
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
    assert x_jog == pytest.approx(speed_in_per_min_to_counts_per_sec(80, lead=0.5))
    assert y_jog == pytest.approx(speed_in_per_min_to_counts_per_sec(80, lead=0.25))
    assert x_jog != pytest.approx(y_jog)
