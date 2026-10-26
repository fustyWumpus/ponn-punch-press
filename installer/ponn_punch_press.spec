# PyInstaller spec for Ponn Punch Press.
#
# Build (from the repo root, with the project's venv active):
#   pyinstaller installer/ponn_punch_press.spec --distpath dist --workpath build
#
# Produces a --onedir bundle (dist/PonnPunchPress/) rather than --onefile:
# onedir starts faster and is far less likely to trip antivirus false
# positives than a self-extracting onefile exe, which matters for a shop-floor
# PC that may have no one around to click through an AV warning.
#
# gclib native runtime: gclib.py (the Python wrapper) locates gclib.dll via
# ctypes.util.find_library(), which searches the system PATH -- and Galil's
# own native installer adds its dll\x64 folder to the machine-wide PATH
# (confirmed by inspecting a real install in this environment). PyInstaller's
# own dependency scan also opportunistically discovered and bundled
# gclib.dll/gclibo.dll into _internal/ when gclib was importable in the build
# venv (observed directly, not just expected) -- harmless redundancy, but the
# native SDK install (silently chain-installed by Inno Setup, see
# ponn_punch_press.iss) is still what actually registers the driver/PATH
# entry a real deployment depends on. Only the small Python-side wrapper (the
# "gclib" module, an optional pyproject.toml dependency -- see the "hardware"
# extra) needs to be importable in this build's venv for any of this to
# happen at all.

import os

block_cipher = None

src_path = os.path.join(SPECPATH, "..", "src")
repo_root = os.path.join(SPECPATH, "..")

# Both machines' real, currently-deployed firmware (not the stale original
# 2001-era reference file) plus each machine's real recipe library (584 files
# total, seeded into %ProgramData% on first run by app.py -- see
# _default_recipe_path) are bundled as data so a fresh install preserves the
# shop's existing recipes rather than starting empty.
app_icon = os.path.join(repo_root, "installer", "assets", "app_icon.ico")

datas = [
    (os.path.join(repo_root, "firmware", "machine_1.dmc"), "firmware"),
    (os.path.join(repo_root, "firmware", "machine_2.dmc"), "firmware"),
    (os.path.join(repo_root, "recipes", "machine_1"), os.path.join("recipes", "machine_1")),
    (os.path.join(repo_root, "recipes", "machine_2"), os.path.join("recipes", "machine_2")),
    (app_icon, os.path.join("installer", "assets")),
]

a = Analysis(
    [os.path.join(SPECPATH, "run_app.py")],
    pathex=[src_path],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PonnPunchPress",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="PonnPunchPress",
)
