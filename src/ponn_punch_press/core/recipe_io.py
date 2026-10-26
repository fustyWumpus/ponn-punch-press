from __future__ import annotations

import glob
import os

from .recipe import Recipe, RecipeLayout

# Confirmed against real, currently-in-production recipe files (both
# machines' Programs/*.txt libraries, 584 files total): 9 fixed "Label: value"
# lines, a 10th "Speed: N" line (percent of max speed -- added along with the
# V2 firmware's variable speed control feature), then a "Comments: " header
# whose remainder (to EOF) is a free-form, possibly multi-line comment block.
#
# The older reference recipes from the original 2004 install CD predate the
# Speed field entirely (9 fields, Comments immediately follows Vacuum Off
# Duration) -- parse_recipe_file tolerates that older format for backward
# compatibility, defaulting speed_percent to 100.
_FIELD_PREFIXES = [
    "Layout: ",
    "Rows: ",
    "Columns: ",
    "X Spacing: ",
    "Y Spacing: ",
    "Starting X: ",
    "Starting Y: ",
    "Vacuum On Duration: ",
    "Vacuum Off Duration: ",
]
_SPEED_PREFIX = "Speed: "
_COMMENTS_PREFIX = "Comments: "
_DEFAULT_SPEED_PERCENT = 100

# The legacy app's StreamReader/StreamWriter used the system default (ANSI)
# codepage; real recipe content is plain ASCII, so cp1252 reads it faithfully
# while also tolerating any stray extended characters.
_ENCODING = "cp1252"


class RecipeParseError(ValueError):
    """Raised when a recipe .txt file doesn't match the expected format."""


def _strip_prefix(line: str, prefix: str, field_name: str) -> str:
    if not line.startswith(prefix):
        raise RecipeParseError(
            f"Expected line starting with {prefix!r} for {field_name!r}, got {line!r}"
        )
    return line[len(prefix):]


def parse_recipe_file(path: str) -> Recipe:
    """Parse a recipe .txt file. Raises RecipeParseError on malformed input."""
    with open(path, "r", encoding=_ENCODING, newline="") as f:
        content = f.read()

    normalized = content.replace("\r\n", "\n")
    lines = normalized.split("\n")

    if len(lines) < len(_FIELD_PREFIXES) + 1:
        raise RecipeParseError(f"Recipe file {path!r} is too short")

    field_names = [
        "Layout", "Rows", "Columns", "X Spacing", "Y Spacing",
        "Starting X", "Starting Y", "Vacuum On Duration", "Vacuum Off Duration",
    ]
    values = [
        _strip_prefix(lines[i], _FIELD_PREFIXES[i], field_names[i])
        for i in range(len(_FIELD_PREFIXES))
    ]

    remainder_start = len(_FIELD_PREFIXES)
    speed_line = lines[remainder_start] if remainder_start < len(lines) else ""
    if speed_line.startswith(_SPEED_PREFIX):
        speed_text = speed_line[len(_SPEED_PREFIX):]
        comments_block = "\n".join(lines[remainder_start + 1:])
    else:
        # Older (pre-2010-ish) recipe file, predating the Speed field.
        speed_text = str(_DEFAULT_SPEED_PERCENT)
        comments_block = "\n".join(lines[remainder_start:])

    comments = _strip_prefix(comments_block, _COMMENTS_PREFIX, "Comments")

    try:
        layout = RecipeLayout.from_label(values[0])
        rows = int(values[1])
        columns = int(values[2])
        x_spacing = float(values[3])
        y_spacing = float(values[4])
        x_start = float(values[5])
        y_start = float(values[6])
        vacuum_on = int(values[7])
        vacuum_off = int(values[8])
        speed_percent = int(speed_text)
    except ValueError as exc:
        raise RecipeParseError(
            f"Recipe file {path!r} has an invalid field value: {exc}"
        ) from exc

    return Recipe(
        file_path=path,
        layout=layout,
        rows=rows,
        columns=columns,
        x_spacing=x_spacing,
        y_spacing=y_spacing,
        x_start=x_start,
        y_start=y_start,
        vacuum_on=vacuum_on,
        vacuum_off=vacuum_off,
        comments=comments,
        speed_percent=speed_percent,
    )


def write_recipe_file(path: str, recipe: Recipe) -> None:
    """Write a recipe to disk in the same format the legacy app used."""
    lines = [
        f"Layout: {recipe.layout.label}",
        f"Rows: {recipe.rows}",
        f"Columns: {recipe.columns}",
        f"X Spacing: {recipe.x_spacing}",
        f"Y Spacing: {recipe.y_spacing}",
        f"Starting X: {recipe.x_start}",
        f"Starting Y: {recipe.y_start}",
        f"Vacuum On Duration: {recipe.vacuum_on}",
        f"Vacuum Off Duration: {recipe.vacuum_off}",
        f"Speed: {recipe.speed_percent}",
        f"Comments: {recipe.comments}",
    ]
    # Note: the legacy app's WriteLine() always appended one trailing newline
    # after the Comments text, and ReadToEnd() read it straight back into the
    # in-memory Comments field on next load -- so every resave grew the file by
    # one blank line forever (that's why real recipe files on disk already have
    # several trailing blank lines). We intentionally don't reproduce that; the
    # comments text is written exactly as given, with no extra newline appended.
    with open(path, "w", encoding=_ENCODING, newline="\r\n") as f:
        f.write("\n".join(lines))


def list_recipe_files(directory: str) -> list[Recipe]:
    """Scan a directory for *.txt recipe files, mirroring RetrieveAllRecipeFiles.

    Files that fail to parse are skipped rather than raising, so one bad file
    doesn't prevent the rest of the recipe library from loading.
    """
    recipes: list[Recipe] = []
    for index, file_path in enumerate(sorted(glob.glob(os.path.join(directory, "*.txt")))):
        try:
            recipe = parse_recipe_file(file_path)
        except (RecipeParseError, OSError):
            continue
        recipe.index = index
        recipes.append(recipe)
    return recipes
