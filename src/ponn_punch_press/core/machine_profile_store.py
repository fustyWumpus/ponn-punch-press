from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .machine_profile import MachineProfile

_CONFIG_FILENAME = "config.json"
_MACHINES_DIRNAME = "machines"


def _default_base_dir() -> Path:
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(program_data) / "PonnPunchPress"


def _sanitize_filename(name: str) -> str:
    """Turn a machine profile name into a safe filename."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "machine"


class MachineProfileStore:
    """JSON-file-backed persistence for machine profiles.

    Replaces the legacy registry-based Preferences.vb settings
    (HKCU\\Software\\VB and VBA Program Settings\\Ponn Punch Press\\...) and
    the DMCSelectController-based machine picker -- gclib connects directly to
    a controller's IP address, so there's no registry-based controller
    enumeration to replicate.
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else _default_base_dir()
        self.machines_dir = self.base_dir / _MACHINES_DIRNAME
        self.config_path = self.base_dir / _CONFIG_FILENAME

    def _path_for(self, name: str) -> Path:
        return self.machines_dir / f"{_sanitize_filename(name)}.json"

    def get_all(self) -> list[MachineProfile]:
        if not self.machines_dir.is_dir():
            return []
        profiles = []
        for path in sorted(self.machines_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                profiles.append(MachineProfile.from_dict(data))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
        return profiles

    def load(self, name: str) -> MachineProfile | None:
        path = self._path_for(name)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return MachineProfile.from_dict(data)

    def save(self, profile: MachineProfile) -> None:
        self.machines_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(profile.name)
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")

    def delete(self, name: str) -> None:
        path = self._path_for(name)
        if path.is_file():
            path.unlink()

    def _read_config(self) -> dict:
        if not self.config_path.is_file():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_config(self, updates: dict) -> None:
        """Merges into the existing config.json rather than overwriting it,
        so unrelated settings (default machine, window geometry) don't clobber
        each other when only one of them changes."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        data = self._read_config()
        data.update(updates)
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_default_machine_name(self) -> str | None:
        return self._read_config().get("default_machine")

    def set_default_machine_name(self, name: str) -> None:
        self._write_config({"default_machine": name})

    def get_window_geometry(self) -> str | None:
        """Base64 text of QMainWindow.saveGeometry()'s QByteArray, or None if
        never saved (e.g. first run)."""
        return self._read_config().get("window_geometry")

    def set_window_geometry(self, geometry_base64: str) -> None:
        self._write_config({"window_geometry": geometry_base64})
