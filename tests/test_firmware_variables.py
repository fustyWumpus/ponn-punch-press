"""Guards against variable names the app sends that the real firmware doesn't
have. The Simulator accepts any name, so a typo like "MGRUNNING" (should be
"RUNNING", read via `MG RUNNING`) passes every simulated test and only fails
on a real controller."""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_FIRMWARE = [_REPO / "firmware" / "machine_1.dmc", _REPO / "firmware" / "machine_2.dmc"]
_WORKFLOW = _REPO / "src" / "ponn_punch_press" / "core" / "workflow.py"

# Galil built-ins / status commands -- not defined in the .dmc program itself.
_BUILT_INS = {"SCX", "SCY", "TC"}


def _is_built_in(name: str) -> bool:
    return name in _BUILT_INS or name.startswith(("_", "@"))


def _workflow_variable_names(call: str) -> set[str]:
    return set(re.findall(rf'{call}\("([^"]+)"', _WORKFLOW.read_text(encoding="utf-8")))


@pytest.mark.parametrize("firmware", _FIRMWARE, ids=lambda p: p.name)
def test_every_variable_the_workflow_reads_exists_in_the_firmware(firmware):
    source = firmware.read_text(encoding="utf-8", errors="ignore")
    names = _workflow_variable_names("get_variable")
    assert "RUNNING" in names  # the lookup is actually finding the calls
    missing = {
        name
        for name in names
        if not _is_built_in(name) and not re.search(rf"^\s*{re.escape(name)}\s*=", source, re.MULTILINE)
    }
    assert not missing, f"{firmware.name} never assigns: {sorted(missing)}"


@pytest.mark.parametrize("firmware", _FIRMWARE, ids=lambda p: p.name)
def test_every_variable_the_workflow_writes_exists_in_the_firmware(firmware):
    source = firmware.read_text(encoding="utf-8", errors="ignore")
    names = _workflow_variable_names("set_variable")
    assert "STARTX" in names
    missing = {name for name in names if not re.search(rf"\b{re.escape(name)}\b", source)}
    assert not missing, f"{firmware.name} never mentions: {sorted(missing)}"
