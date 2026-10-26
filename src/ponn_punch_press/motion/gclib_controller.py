from __future__ import annotations

import concurrent.futures

from .controller import Axis, MotionControllerCommandError, MotionControllerConnectionError

try:
    import gclib
except ImportError:  # gclib SDK not installed -- only needed on the real machine
    gclib = None

# Galil status queries that are sent as bare commands (no "MG " prefix),
# matching exactly what MainScreen.vb's PollTimer_Tick sent via DMCCommand.
_BARE_COMMAND_VARIABLES = {"SCX", "SCY", "TC"}

# Bounds how long GOpen blocks the UI if a machine's Ethernet link is down --
# without this, a real OS-level TCP connect attempt to an unplugged/powered-off
# controller can hang for tens of seconds. Confirmed valid syntax and behavior
# against a real, physically connected controller (a DMC2125) on 2026-07-06.
_CONNECT_TIMEOUT_SECONDS = 5

# GOpen's "-t" sets the *connect* timeout; gclib separately carries a command
# timeout (read via the .timeout property) that starts equal to the connect
# timeout in seconds, expressed in milliseconds -- i.e. "-t 5" leaves the
# command timeout at 5000ms. That's too short for GProgramDownload with a
# multi-hundred-line .dmc file: confirmed directly against a real DMC2125 that
# the identical download which times out under the default 5000ms completes
# in well under a second once the command timeout is raised via GTimeout().
# The actual transfer is fast; the default just isn't generous enough for it.
_FIRMWARE_DOWNLOAD_TIMEOUT_MS = 30000

# Belt-and-suspenders hard timeout, enforced from Python rather than trusted
# to gclib/the controller: testing against a real DMC2125 showed that
# GOpen/GCommand/GProgramDownload can block *indefinitely* -- well past any
# configured -t/GTimeout value -- after the controller has been left in a
# confused state (e.g. by an earlier download that itself timed out
# mid-transfer). gclib's own timeout is not reliably enforced in that
# situation, so every gclib call here runs on a throwaway worker thread with
# a real wall-clock cutoff; if it fires, that thread is abandoned (its stuck
# native call may never return) rather than let the whole app hang forever.
_COMMAND_HARD_TIMEOUT_SECONDS = 10
_FIRMWARE_DOWNLOAD_HARD_TIMEOUT_SECONDS = 40


def _run_with_hard_timeout(fn, timeout_seconds):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        executor.shutdown(wait=False)
        raise TimeoutError(
            f"gclib call did not return within {timeout_seconds}s -- the controller may be "
            "unresponsive and could need a power cycle."
        ) from None
    else:
        executor.shutdown(wait=True)


class GclibMotionController:
    """Real MotionController implementation using Galil's official gclib
    Python binding, connecting to the controller over Ethernet.

    Validated end-to-end against a real, physically connected Galil
    controller (a DMC2125) on 2026-07-06 -- not just documentation or a
    disconnected library:
    `gclib.py()`, `.GOpen('<ip> --direct -t <n>')`, `.GCommand(cmd)`,
    `.GProgramDownload(dmc_source)` (single argument -- a second "label"
    argument, guessed earlier by analogy with the legacy DMC32 API, does not
    exist), `.GClose()`, and errors consistently raised as `gclib.GclibError`
    all behave as used below.

    The "--direct" flag is required, not optional: without it, GOpen tries to
    go through gcaps (Galil's local discovery/broker service) first, and
    fails outright ("device failed to open") for any controller gcaps hasn't
    already discovered -- which includes older, non-DHCP-self-announcing
    models like this DMC2125 that gclib's own broadcast discovery
    (GIpRequests/GAddresses) never finds. "--direct" skips gcaps and connects
    straight to the given address, which works even when discovery reports
    nothing at all.
    """

    def __init__(self):
        if gclib is None:
            raise ImportError(
                "The 'gclib' package (Galil's Communications Library Python binding) "
                "is not installed. Install the Galil gclib SDK for this controller and "
                "its Python wrapper before using GclibMotionController."
            )
        self._g = gclib.py()

    def open(self, ip_address: str) -> None:
        try:
            _run_with_hard_timeout(
                lambda: self._g.GOpen(f"{ip_address} --direct -t {_CONNECT_TIMEOUT_SECONDS}"),
                _COMMAND_HARD_TIMEOUT_SECONDS,
            )
        except (gclib.GclibError, TimeoutError) as exc:
            raise MotionControllerConnectionError(str(exc)) from exc

    def close(self) -> None:
        try:
            _run_with_hard_timeout(self._g.GClose, _COMMAND_HARD_TIMEOUT_SECONDS)
        except (gclib.GclibError, TimeoutError) as exc:
            raise MotionControllerConnectionError(str(exc)) from exc

    def abort(self) -> None:
        self.execute("HX")

    def download_firmware(self, dmc_source: str) -> None:
        previous_timeout = self._g.timeout

        def _do_download():
            self._g.GTimeout(_FIRMWARE_DOWNLOAD_TIMEOUT_MS)
            self._g.GProgramDownload(dmc_source)

        try:
            _run_with_hard_timeout(_do_download, _FIRMWARE_DOWNLOAD_HARD_TIMEOUT_SECONDS)
        except (gclib.GclibError, TimeoutError) as exc:
            raise MotionControllerCommandError(f"Firmware download failed: {exc}") from exc
        else:
            # Only attempt to restore the timeout on a clean success -- if the
            # hard timeout fired, self._g's worker thread may still be stuck
            # inside the native call, and touching self._g again from here
            # risks blocking too. Treat the connection as unusable at that
            # point; the caller should close() and reconnect.
            self._g.GTimeout(previous_timeout)

    def run_program(self, label: str) -> None:
        self.execute(f"XQ{label}")

    def execute(self, command: str) -> str:
        try:
            return _run_with_hard_timeout(lambda: self._g.GCommand(command), _COMMAND_HARD_TIMEOUT_SECONDS)
        except (gclib.GclibError, TimeoutError) as exc:
            raise MotionControllerCommandError(f"Command {command!r} failed: {exc}") from exc

    def set_variable(self, name: str, value: float) -> None:
        self.execute(f"{name}={value}")

    def get_variable(self, name: str) -> float:
        is_bare = name in _BARE_COMMAND_VARIABLES or name.startswith("@IN")
        command = name if is_bare else f"MG {name}"
        return float(self.execute(command).strip())

    def get_position(self) -> tuple[float, float]:
        x = float(self.execute("TPX").strip())
        y = float(self.execute("TPY").strip())
        return (x, y)

    def jog(self, axis: Axis, speed: float) -> None:
        axis_letter = "X" if axis is Axis.X else "Y"
        self.execute(f"JG{axis_letter}={speed}")
        self.execute(f"BG{axis_letter}")

    def jog_stop(self) -> None:
        self.execute("STXY")

    def set_pause(self, paused: bool) -> None:
        self.execute(f"PAUSE={1 if paused else 0}")

    def set_vacuum(self, enabled: bool) -> None:
        if enabled:
            self.execute("VACEN=1")
        else:
            self.execute("VACEN=0")
            self.execute("CB2")
