from ponn_punch_press.core.machine_profile import (
    DEFAULT_MAX_X_SPEED,
    DEFAULT_RECIPE_PATH,
    DEFAULT_X_LEAD,
    MachineProfile,
)
from ponn_punch_press.core.machine_profile_store import MachineProfileStore


def test_new_profile_uses_legacy_default_values():
    profile = MachineProfile(name="Machine 1", ip_address="192.168.1.10")
    assert profile.recipe_path == DEFAULT_RECIPE_PATH
    assert profile.x_lead == DEFAULT_X_LEAD
    assert profile.max_x_speed == DEFAULT_MAX_X_SPEED


def test_save_then_load_round_trips(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    profile = MachineProfile(
        name="Machine 1",
        ip_address="192.168.1.10",
        recipe_path="D:\\Recipes",
        x_lead=0.4,
        y_lead=0.4,
        max_x_speed=1200,
        max_y_speed=1000,
        x_jog_speed=90,
        y_jog_speed=90,
    )
    store.save(profile)

    loaded = store.load("Machine 1")
    assert loaded == profile


def test_load_missing_profile_returns_none(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    assert store.load("Nonexistent") is None


def test_get_all_returns_saved_profiles(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    store.save(MachineProfile(name="Machine 1", ip_address="192.168.1.10"))
    store.save(MachineProfile(name="Machine 2", ip_address="192.168.1.11"))

    names = sorted(p.name for p in store.get_all())
    assert names == ["Machine 1", "Machine 2"]


def test_get_all_on_empty_store_returns_empty_list(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path / "does_not_exist_yet")
    assert store.get_all() == []


def test_delete_removes_profile(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    store.save(MachineProfile(name="Machine 1", ip_address="192.168.1.10"))
    store.delete("Machine 1")
    assert store.load("Machine 1") is None


def test_default_machine_name_round_trips(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    assert store.get_default_machine_name() is None

    store.set_default_machine_name("Machine 1")
    assert store.get_default_machine_name() == "Machine 1"


def test_window_geometry_round_trips(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    assert store.get_window_geometry() is None

    store.set_window_geometry("some-base64-geometry-blob")
    assert store.get_window_geometry() == "some-base64-geometry-blob"


def test_setting_one_config_value_does_not_clobber_another(tmp_path):
    """set_default_machine_name and set_window_geometry share config.json --
    each must merge into it rather than overwriting the whole file, or
    setting one after the other silently erases the first."""
    store = MachineProfileStore(base_dir=tmp_path)
    store.set_default_machine_name("Machine 1")
    store.set_window_geometry("some-base64-geometry-blob")

    assert store.get_default_machine_name() == "Machine 1"
    assert store.get_window_geometry() == "some-base64-geometry-blob"


def test_machine_name_with_special_characters_is_sanitized_for_filename(tmp_path):
    store = MachineProfileStore(base_dir=tmp_path)
    profile = MachineProfile(name="Press #1 / East Wing", ip_address="192.168.1.20")
    store.save(profile)

    loaded = store.load("Press #1 / East Wing")
    assert loaded == profile
