# Ponn Punch Press — Session Handoff

Rewrite of a ~20-year-old VB.NET punch-press control app (see original source
at `Punch Press Files/` on the source machine) into a modern Python/PySide6
app that controls two Galil-driven punch presses side by side. This package
is everything needed to keep working on it from a different machine —
likely one with better physical access to the real controller hardware.

## Current status

- **79/79 tests pass** (`pytest`), including a real (non-mocked) integration
  test against an actual installed gclib library.
- Full dual-machine PySide6 app (`src/ponn_punch_press/`), Machine 2 on the
  left / Machine 1 on the right, each with an independent workflow/controller
  connection — verified independent (one machine failing/faulting doesn't
  affect the other).
- Both machines' real, currently-deployed `.dmc` firmware and full recipe
  libraries (229 + 354 real production files) are bundled and get seeded
  into `%ProgramData%` on first run.
- Installer (`installer/ponn_punch_press.iss`, built with Inno Setup 6) is
  complete and compiles cleanly: bundles the app, both firmware files, both
  recipe libraries, and the real Galil gclib SDK installer
  (`installer/vendor/gclib_2.4.1.exe`, sha256-verified from
  `https://www.galil.com/gclib/latest`), silently chain-installing gclib via
  its documented `/S` switch.

## Setup on a new machine

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev,hardware]"   # hardware = real gclib wheel
.venv\Scripts\python -m pytest -q                 # should be 79 passed
```

To run the app for real: `python -m ponn_punch_press.app` (add `--simulate`
to run against the built-in fake controller instead of real hardware).

To rebuild the installer:
```bash
pyinstaller installer/ponn_punch_press.spec --distpath dist --workpath build
iscc installer/ponn_punch_press.iss   # needs Inno Setup 6 installed
```

## Real-hardware testing session (2026-08-03) — where this left off

A real Galil controller (a **DMC2125**, an old spare/backup unit, "not yet
connected to a machine") was made available at **192.168.1.10** on the
previous machine's Ethernet adapter. Testing against it found and fixed
three real bugs in `src/ponn_punch_press/motion/gclib_controller.py`:

1. **`GOpen` needs `--direct`.** Without it, gclib tries Galil's local
   discovery/broker service (`gcaps`) first and fails outright
   ("device failed to open") for any controller gcaps hasn't already
   discovered — which includes this DMC2125, since it's an older model that
   doesn't self-announce over DHCP/BOOTP the way newer Galil controllers do.
   Confirmed: `GIpRequests()`/`GAddresses()` (Galil's own broadcast discovery)
   never found it, even across two attempts with the user power-cycling the
   controller specifically so I could catch its boot-time broadcast — it
   simply doesn't send one. `--direct` bypasses gcaps and connects straight
   to the given address, which works.

2. **Firmware download needs a longer command timeout than the connection
   default.** `GOpen`'s `-t <n>` sets *both* the connect timeout and (in
   seconds→milliseconds) the initial command timeout, which is too short for
   `GProgramDownload` with a multi-hundred-line `.dmc` file. Fixed by
   explicitly raising it via `GTimeout()` around the download call, then
   restoring it afterward (only on success — see next point).

3. **Added a hard, Python-level watchdog timeout around every gclib call.**
   During testing, `GOpen`/`GCommand`/`GProgramDownload` were observed to
   block **indefinitely** — well past any configured `-t`/`GTimeout` value —
   after the controller had been left in a confused state (most likely from
   an earlier download that itself timed out mid-transfer). gclib's own
   timeout is not reliably enforced in that situation on this
   hardware/library combination, so every gclib call now runs on a
   throwaway worker thread with a real wall-clock cutoff
   (`_run_with_hard_timeout`, `_COMMAND_HARD_TIMEOUT_SECONDS` /
   `_FIRMWARE_DOWNLOAD_HARD_TIMEOUT_SECONDS`); if it fires, that thread is
   abandoned (its stuck native call may never return) rather than hanging
   the whole app. This is a real, load-bearing fix, not speculative
   hardening — it was needed to get out of an actual hang during testing.

### What's unresolved

The controller became **intermittently unresponsive** over the course of
repeated testing — sometimes hanging (before the watchdog fix), sometimes
failing instantly with "device timed out" even for a bare connect attempt,
while plain ICMP ping to it stayed clean throughout. This pattern lines up
with moments where a stuck test process had to be force-killed (via
`Stop-Process -Force`), which likely left the controller's TCP/session state
thinking a client was still connected, since a force-kill never lets
`GClose()` run.

**This looks like leftover controller-side state from aggressive rapid
test/reconnect cycling during debugging, not a remaining code bug** — but it
was never fully re-verified with a single clean end-to-end run after a
power-cycle, because the session ended before that could happen. **The very
next step on the new machine should be:**

1. Power-cycle the DMC2125 controller (or whichever real controller is
   available there).
2. Wait ~10s, confirm `ping <controller-ip>` is clean.
3. Run **one** clean test — see script below — and do not immediately retry
   if it fails; if it hangs, the watchdog fix means it should now fail with
   a clear `TimeoutError`/`MotionControllerConnectionError` instead of
   hanging forever, which itself is useful information.

```python
import sys, time
sys.path.insert(0, "src")
from ponn_punch_press.core.machine_profile import MachineProfile
from ponn_punch_press.core.workflow import PunchPressWorkflow
from ponn_punch_press.motion.gclib_controller import GclibMotionController
from ponn_punch_press.motion.controller import MotionControllerError

CONTROLLER_IP = "192.168.1.10"  # update to match the new machine's setup
with open("firmware/machine_1.dmc", encoding="utf-8") as f:
    dmc_source = f.read()

profile = MachineProfile(name="Machine 1", ip_address=CONTROLLER_IP)
workflow = PunchPressWorkflow(GclibMotionController(), profile)
start = time.time()
try:
    workflow.start_up(CONTROLLER_IP, dmc_source)
    print(f"start_up() SUCCEEDED after {time.time()-start:.1f}s")
    print("poll():", workflow.poll())
except MotionControllerError as e:
    print(f"start_up() FAILED after {time.time()-start:.1f}s: {e}")
```

If this comes back clean, the natural next step is running the actual app
(`python -m ponn_punch_press.app`, no `--simulate`) against the real
controller and exercising it from the UI — jog, home, download a recipe —
still being mindful this is real equipment. Note this DMC2125 is described
as a **spare/backup, not wired to any physical machine**, so no motion
commands should have any physical effect regardless, but that assumption is
worth reconfirming on-site before assuming it's fully safe.

### Notes on the physical setup encountered

- The Windows machine's Ethernet adapter needed a **static IP on the same
  /24 subnet as the controller** (no DHCP, no default gateway needed) —
  Galil controllers of this vintage have no universal factory-default IP and
  don't route across subnets, so simple ping sweeps/ARP find nothing unless
  the host is on the exact right subnet.
- This particular controller does **not** support zero-config Ethernet
  discovery (no DHCP/BOOTP self-announce) — confirmed by two power-cycle
  listening windows with gclib's own `GIpRequests()`/`GAddresses()`
  producing nothing both times. A **serial (RS-232) connection** would be
  the reliable way to read/reassign its IP from scratch if it's ever moved
  to an unknown network again (`IA`/`BN` commands) — none was available on
  the previous machine.
- A Galil **Master Reset** (`<Ctrl-R><Ctrl-S>` or a physical `MRST` jumper)
  erases the *entire* EEPROM, not just the IP, including whatever `.dmc`
  program is burned in. Low risk for this specific spare/unconfigured unit
  since it has nothing valuable on it, but avoid this reflexively on the
  real production controllers (Machine 1 / Machine 2) — their current,
  real, currently-deployed firmware is already safely backed up in this
  package at `firmware/machine_1.dmc` / `firmware/machine_2.dmc`, so a
  reset+redownload is recoverable if it ever became necessary, but should
  still be a deliberate, confirmed decision, not a casual troubleshooting
  step.

## Project layout

```
src/ponn_punch_press/
  app.py                  entry point / composition root (two machines)
  core/                    domain logic (Recipe, MachineProfile, workflow state machine)
  motion/                  MotionController Protocol + Simulator + GclibMotionController
  ui/                      PySide6 widgets (MachinePanel, DualMachineWindow, dialogs)
firmware/                  real per-machine .dmc firmware (machine_1.dmc, machine_2.dmc)
recipes/                   real per-machine recipe libraries (seeded on first run)
installer/                 PyInstaller spec + Inno Setup script + vendored gclib installer
tests/                     79 tests, including one real (non-mocked) gclib integration test
```
