from __future__ import annotations

from dataclasses import asdict, dataclass

# Defaults match the legacy Preferences.vb GetSettings() fallback values
# (registry keys RecipePath/XLead/YLead/MaxXSpeed/MaxYSpeed/XJogSpeed/YJogSpeed
# under "Ponn Punch Press\Machine Number {N}").
DEFAULT_RECIPE_PATH = "C:\\"
DEFAULT_X_LEAD = 0.5
DEFAULT_Y_LEAD = 0.5
DEFAULT_MAX_X_SPEED = 1100.0
DEFAULT_MAX_Y_SPEED = 915.0
DEFAULT_X_JOG_SPEED = 80.0
DEFAULT_Y_JOG_SPEED = 80.0


@dataclass
class MachineProfile:
    """Per-machine settings, replacing the legacy per-machine registry keys.

    Speeds (max_x_speed, max_y_speed, x_jog_speed, y_jog_speed) are stored here
    in inches/minute, exactly as the operator enters them in Preferences -- the
    conversion to controller counts/sec happens in recipe_mapper.py, not here.
    """

    name: str
    ip_address: str
    recipe_path: str = DEFAULT_RECIPE_PATH
    x_lead: float = DEFAULT_X_LEAD
    y_lead: float = DEFAULT_Y_LEAD
    max_x_speed: float = DEFAULT_MAX_X_SPEED
    max_y_speed: float = DEFAULT_MAX_Y_SPEED
    x_jog_speed: float = DEFAULT_X_JOG_SPEED
    y_jog_speed: float = DEFAULT_Y_JOG_SPEED

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MachineProfile":
        return cls(**data)
