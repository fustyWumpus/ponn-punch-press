from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecipeLayout(Enum):
    MATRIX = 1
    STAGGERED = 2

    @classmethod
    def from_label(cls, label: str) -> "RecipeLayout":
        normalized = label.strip().lower()
        if normalized == "matrix":
            return cls.MATRIX
        if normalized == "staggered":
            return cls.STAGGERED
        raise ValueError(f"Unknown recipe layout: {label!r}")

    @property
    def label(self) -> str:
        return "Matrix" if self is RecipeLayout.MATRIX else "Staggered"


@dataclass
class Recipe:
    file_path: str
    layout: RecipeLayout
    rows: int
    columns: int
    x_spacing: float
    y_spacing: float
    x_start: float
    y_start: float
    vacuum_on: int
    vacuum_off: int
    comments: str
    speed_percent: int = 100
    index: int = 0

    @property
    def recipe_number(self) -> str:
        """Display name for the recipe list: the filename without path/extension."""
        import os

        return os.path.splitext(os.path.basename(self.file_path))[0]

    def __str__(self) -> str:
        return self.recipe_number
