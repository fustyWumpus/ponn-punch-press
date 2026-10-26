from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.machine_profile import MachineProfile
from .core.machine_profile_store import MachineProfileStore
from .core.workflow import PunchPressWorkflow
from .motion.controller import MotionController
from .ui.dual_machine_window import DualMachineWindow
from .ui.machine_panel import MachinePanel

# Machine 1 is the RIGHT physical machine, Machine 2 is LEFT (per the shop
# floor layout) -- both are stepper-motor-driven and run their own
# .dmc firmware, which has diverged over years of on-site tweaks (different
# I/O pin assignments, a variable-speed-control feature, etc.) even though
# both still expose the same variable interface this app talks to
# (STARTX, PAUSE, HOMED, SPEED, ...).
_MACHINES = [
    {"key": "machine_1", "name": "Machine 1", "default_ip": "192.168.1.11"},
    {"key": "machine_2", "name": "Machine 2", "default_ip": "192.168.1.12"},
]


def _bundle_root() -> Path:
    """Root directory to resolve bundled resources (firmware, seed recipes)
    from, whether running from source or from a PyInstaller bundle.
    sys._MEIPASS is PyInstaller's own extraction directory -- the correct way
    to find bundled data regardless of --onedir vs --onefile packaging."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]  # src/ponn_punch_press/app.py -> repo root


def _get_firmware_source(machine_key: str) -> str:
    return (_bundle_root() / "firmware" / f"{machine_key}.dmc").read_text(encoding="utf-8")


def _icon_path() -> Path:
    return _bundle_root() / "installer" / "assets" / "app_icon.ico"


def _set_windows_app_user_model_id() -> None:
    """Without this, Windows groups this app's taskbar button under
    python.exe's own identity and shows python.exe's icon there instead of
    the one set via QApplication.setWindowIcon() -- the window's own
    title-bar icon is unaffected, only the taskbar button. Registering a
    distinct AppUserModelID tells Windows to treat this as its own
    application. Must run before QApplication is constructed. No-op on
    non-Windows, and harmless (if unnecessary) for the packaged PyInstaller
    build, which already gets its own taskbar identity from the .exe."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PonnMachine.PunchPress")
    except (AttributeError, OSError):
        pass


def _seed_recipes_dir(machine_key: str) -> Path | None:
    seed_dir = _bundle_root() / "recipes" / machine_key
    return seed_dir if seed_dir.is_dir() else None


def _default_program_data_dir() -> Path:
    import os

    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "PonnPunchPress"


def _default_recipe_path(machine_key: str) -> str:
    """Where a brand-new machine profile's recipes live: a writable local
    folder, seeded from the bundled recipe library on first run so the
    shop's existing (hundreds of files, 20 years of) recipes aren't lost in
    the migration even if the installer's own seeding step is skipped."""
    target_dir = _default_program_data_dir() / "recipes" / machine_key
    if not target_dir.exists() or not any(target_dir.iterdir()):
        seed_dir = _seed_recipes_dir(machine_key)
        if seed_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
            for src in seed_dir.iterdir():
                if src.is_file():
                    shutil.copy2(src, target_dir / src.name)
    target_dir.mkdir(parents=True, exist_ok=True)
    return str(target_dir)


def _build_controller(simulate: bool) -> MotionController:
    if simulate:
        from .motion.simulator import Simulator

        return Simulator()
    from .motion.gclib_controller import GclibMotionController

    return GclibMotionController()


def _load_or_create_profile(store: MachineProfileStore, name: str, default_ip: str, machine_key: str) -> MachineProfile:
    profile = store.load(name)
    if profile is not None:
        return profile
    profile = MachineProfile(name=name, ip_address=default_ip, recipe_path=_default_recipe_path(machine_key))
    store.save(profile)
    return profile


def _build_panel(store: MachineProfileStore, machine: dict, simulate: bool) -> MachinePanel:
    profile = _load_or_create_profile(store, machine["name"], machine["default_ip"], machine["key"])
    controller = _build_controller(simulate)
    workflow = PunchPressWorkflow(controller, profile)
    dmc_source = _get_firmware_source(machine["key"])
    return MachinePanel(workflow, profile, dmc_source, store)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ponn Punch Press control application")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run both machines against simulated motion controllers instead of real Galil hardware.",
    )
    args = parser.parse_args()

    _set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv)
    icon_path = _icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Building a panel can fail before any window exists (missing/corrupt
    # firmware file, or -- discovered by actually running the packaged
    # installer build -- the gclib SDK not being installed when --simulate
    # isn't passed, which used to crash with a raw, operator-unfriendly
    # "Unhandled exception in script" dialog from the PyInstaller bootloader).
    # Show a real message and exit cleanly instead.
    try:
        store = MachineProfileStore()
        panel_1 = _build_panel(store, _MACHINES[0], args.simulate)
        panel_2 = _build_panel(store, _MACHINES[1], args.simulate)
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Ponn Punch Press - Startup Error",
            "Ponn Punch Press could not start:\n\n"
            f"{exc}\n\n"
            "If this mentions 'gclib', the Galil gclib SDK (and its Python "
            "wrapper) must be installed on this PC to control real hardware. "
            "Run with --simulate to try the app without hardware attached.",
        )
        return 1

    window = DualMachineWindow(panel_machine_2=panel_2, panel_machine_1=panel_1)
    # Show the window *before* attempting hardware connections, not after --
    # start_up() connects to real controllers synchronously and can block for
    # up to ~50s per machine on a bad or unreachable IP. Showing the window
    # first means the app visibly opens right away regardless of how long
    # (or whether) that succeeds, and any connection-failure dialog is
    # properly parented to an already-visible window instead of one that has
    # never been shown yet.
    window.restore_geometry_or_maximize()
    window.start_up()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
