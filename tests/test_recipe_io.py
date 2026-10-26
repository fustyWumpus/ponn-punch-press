import os

import pytest

from ponn_punch_press.core.recipe import Recipe, RecipeLayout
from ponn_punch_press.core.recipe_io import (
    RecipeParseError,
    list_recipe_files,
    parse_recipe_file,
    write_recipe_file,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "recipes")


def test_parse_staggered_recipe_no_comments():
    recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, "1125X930.TXT"))
    assert recipe.layout is RecipeLayout.STAGGERED
    assert recipe.rows == 9
    assert recipe.columns == 30
    assert recipe.x_spacing == pytest.approx(1.195)
    assert recipe.y_spacing == pytest.approx(1.135)
    assert recipe.x_start == pytest.approx(0.375)
    assert recipe.y_start == pytest.approx(3.000)
    assert recipe.vacuum_on == 0
    assert recipe.vacuum_off == 0
    assert recipe.recipe_number == "1125X930"


def test_parse_recipe_with_multiline_comment():
    recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, "NOVA332.TXT"))
    assert recipe.layout is RecipeLayout.STAGGERED
    assert recipe.rows == 32
    assert recipe.columns == 28
    assert "USE  .325 DIE" in recipe.comments


def test_parse_matrix_recipe_with_vacuum_durations():
    recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, "DATA_CARD.TXT"))
    assert recipe.layout is RecipeLayout.MATRIX
    assert recipe.rows == 7
    assert recipe.columns == 75
    assert recipe.vacuum_on == 5
    assert recipe.vacuum_off == 5


def test_old_format_files_without_speed_field_default_to_100(tmp_path):
    """Pre-2010-ish recipe files (from the original install CD) predate the
    Speed field entirely. Real production libraries on both machines today
    always have it, but old reference/backup files may not."""
    for name in ("1125X930.TXT", "NOVA332.TXT", "DATA_CARD.TXT"):
        recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, name))
        assert recipe.speed_percent == 100


def test_parse_real_machine1_recipe_with_speed_field():
    recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, "machine1_595X073.txt"))
    assert recipe.speed_percent == 81
    assert recipe.rows == 19
    assert recipe.columns == 53
    assert recipe.vacuum_on == 10


def test_parse_real_machine2_recipe_with_speed_field():
    recipe = parse_recipe_file(os.path.join(FIXTURES_DIR, "machine2_S275_WELCH.txt"))
    assert recipe.speed_percent == 100
    assert recipe.rows == 31
    assert recipe.columns == 100
    assert "CUT STOCK 10\" X 36\"" in recipe.comments


@pytest.mark.parametrize(
    "filename", ["1125X930.TXT", "machine1_595X073.txt", "machine2_S275_WELCH.txt"]
)
def test_round_trip_write_then_parse(tmp_path, filename):
    original = parse_recipe_file(os.path.join(FIXTURES_DIR, filename))
    out_path = tmp_path / "roundtrip.txt"
    write_recipe_file(str(out_path), original)

    reparsed = parse_recipe_file(str(out_path))
    assert reparsed.layout == original.layout
    assert reparsed.rows == original.rows
    assert reparsed.columns == original.columns
    assert reparsed.x_spacing == original.x_spacing
    assert reparsed.y_spacing == original.y_spacing
    assert reparsed.x_start == original.x_start
    assert reparsed.y_start == original.y_start
    assert reparsed.vacuum_on == original.vacuum_on
    assert reparsed.vacuum_off == original.vacuum_off
    assert reparsed.speed_percent == original.speed_percent
    assert reparsed.comments == original.comments


def test_write_recipe_uses_crlf_line_endings(tmp_path):
    recipe = Recipe(
        file_path="unused.txt",
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
    out_path = tmp_path / "crlf.txt"
    write_recipe_file(str(out_path), recipe)

    raw = out_path.read_bytes()
    assert b"\r\n" in raw
    assert raw.startswith(b"Layout: Matrix\r\n")
    assert b"Speed: 100\r\n" in raw


def test_parse_rejects_malformed_file(tmp_path):
    bad_path = tmp_path / "bad.txt"
    bad_path.write_text("Not a recipe file\n")
    with pytest.raises(RecipeParseError):
        parse_recipe_file(str(bad_path))


def test_list_recipe_files_skips_unparseable_and_ignores_non_txt(tmp_path):
    write_recipe_file(
        str(tmp_path / "good.txt"),
        Recipe(
            file_path="unused",
            layout=RecipeLayout.MATRIX,
            rows=2,
            columns=3,
            x_spacing=0.5,
            y_spacing=0.5,
            x_start=0.0,
            y_start=0.0,
            vacuum_on=0,
            vacuum_off=0,
            comments="",
        ),
    )
    (tmp_path / "bad.txt").write_text("garbage")
    (tmp_path / "notes.md").write_text("Layout: Matrix\n")

    recipes = list_recipe_files(str(tmp_path))
    assert len(recipes) == 1
    assert recipes[0].recipe_number == "good"
