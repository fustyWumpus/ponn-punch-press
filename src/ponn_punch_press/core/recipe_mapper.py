from __future__ import annotations

from dataclasses import dataclass

from .machine_profile import MachineProfile
from .recipe import Recipe


@dataclass
class ControllerRecipeVariables:
    """The DMC variables MainScreen.vb's DownloadRecipe_Click sends to the
    controller, expressed in the units the PONN_PUNCH_PRESS.dmc firmware
    expects (step-pulse counts, counts/sec)."""

    start_x: float
    start_y: float
    spacing_x: float
    spacing_y: float
    vacuum_on: int
    vacuum_off: int
    rows: int
    columns: int
    x_speed: float
    y_speed: float
    layout: int  # 1=Matrix, 2=Staggered -- matches the firmware's LAYOUT variable
    speed_percent: int  # percent of max speed -- matches the firmware's SPEED variable


def inches_to_counts(inches: float, lead: float, steps_per_rev: float) -> float:
    """Convert a linear distance in inches to controller counts (step pulses).

    Port of the legacy `value * XEncoder / XLead` (or YEncoder/YLead) formula,
    with the per-revolution figure now the machine's own steps_per_rev rather
    than a hardcoded constant -- deliberately a required argument so a caller
    can't silently fall back to a wrong default.
    """
    return inches * steps_per_rev / lead


def counts_to_inches(counts: float, lead: float, steps_per_rev: float) -> float:
    """Inverse of inches_to_counts -- used for position readback (RPX/RPY)."""
    return counts / steps_per_rev * lead


def speed_in_per_min_to_counts_per_sec(speed_in_per_min: float, lead: float, steps_per_rev: float) -> float:
    """Convert a speed in inches/minute (as entered in Preferences) to
    controller counts/second (as sent for XSPEED/YSPEED/JGX/JGY)."""
    return speed_in_per_min * steps_per_rev / lead / 60


def build_controller_variables(recipe: Recipe, profile: MachineProfile) -> ControllerRecipeVariables:
    """Port of MainScreen.vb's DownloadRecipe_Click unit conversions.

    Bug fix vs. the legacy app: Preferences.vb computed MaxYSpeed/YJogSpeed
    using XEncoder/XLead instead of YEncoder/YLead (lines 343/346), silently
    mis-scaling the Y axis speed whenever XLead != YLead. Since encoder
    resolution is identical for both axes this only bites when the leadscrew
    pitches differ, but it's a real correctness bug -- fixed here by using
    profile.y_lead for all Y-axis conversions.
    """
    n = profile.steps_per_rev
    return ControllerRecipeVariables(
        start_x=inches_to_counts(recipe.x_start, profile.x_lead, n),
        start_y=inches_to_counts(recipe.y_start, profile.y_lead, n),
        spacing_x=inches_to_counts(recipe.x_spacing, profile.x_lead, n),
        spacing_y=inches_to_counts(recipe.y_spacing, profile.y_lead, n),
        vacuum_on=recipe.vacuum_on,
        vacuum_off=recipe.vacuum_off,
        rows=recipe.rows,
        columns=recipe.columns,
        x_speed=speed_in_per_min_to_counts_per_sec(profile.max_x_speed, profile.x_lead, n),
        y_speed=speed_in_per_min_to_counts_per_sec(profile.max_y_speed, profile.y_lead, n),
        layout=recipe.layout.value,
        speed_percent=recipe.speed_percent,
    )


def jog_speeds_counts_per_sec(profile: MachineProfile) -> tuple[float, float]:
    """X, Y jog speeds in counts/sec, for the JGX=/JGY= commands."""
    return (
        speed_in_per_min_to_counts_per_sec(profile.x_jog_speed, profile.x_lead, profile.steps_per_rev),
        speed_in_per_min_to_counts_per_sec(profile.y_jog_speed, profile.y_lead, profile.steps_per_rev),
    )
