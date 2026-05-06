#!/usr/bin/env python3
"""
Phonology Segment & Feature Engine

A desktop application for phonological analysis of segment inventories.
Provides tools for:
- Loading and browsing phonological inventories
- Inspecting segments and their distinctive features
- Computing natural classes
- Finding minimal distinguishing feature sets
- Inferring hierarchical feature dependencies (geometry)

Usage:
    python main.py [inventory.json]
    python main.py -platform xcb
    python main.py -platform wayland
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from PyQt6.QtCore import QCommandLineParser
from PyQt6.QtWidgets import QApplication

_FALLBACK_GUARD_ENV = "FEATURES_QT_PLATFORM_FALLBACK"


def _argv_requests_qt_platform(argv: list[str]) -> bool:
    """Return True if the user already supplied a Qt platform argument."""
    for arg in argv:
        if arg == "-platform":
            return True

        if arg.startswith("-platform="):
            return True

    return False


def _auto_qt_platform() -> str | None:
    """Pick a Qt platform plugin for Linux, or None to let Qt decide."""
    is_linux = sys.platform.startswith("linux")
    if not is_linux:
        return None

    wayland_display = os.environ.get("WAYLAND_DISPLAY")

    if wayland_display:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")

        if os.path.isabs(wayland_display):
            socket_path = wayland_display
        else:
            socket_path = os.path.join(runtime_dir, wayland_display)

        wayland_socket_exists = os.path.exists(socket_path)
        if wayland_socket_exists:
            return "wayland"

    x11_display = os.environ.get("DISPLAY")
    if x11_display:
        return "xcb"

    return None


def _is_wayland_disconnect_message(message: str | None) -> bool:
    """True if a line of Qt output reports a fatal wayland connection drop.

    Some compositors (XWayland bridges, nested sessions, sandboxed/Linux-on-X
    desktops, flaky VNC) accept the initial wl_display connection but tear it
    down once the client starts painting. The Qt wayland plugin logs this
    message and then terminates the process directly — `app.exec()` does not
    return — so we can only catch it from outside, in a supervisor parent.
    The wording has been stable across Qt 5 and 6.
    """
    if message is None:
        return False
    return "wayland connection broke" in message.lower()


def _spawn_gui_child(platform: str) -> tuple[int, bool]:
    """Run the GUI as a child process pinned to `platform`.

    Returns (exit_code, wayland_disconnect_seen). The child's stderr is
    streamed to our stderr in real time so the user sees output as normal.
    """
    child_env = dict(os.environ)
    child_env[_FALLBACK_GUARD_ENV] = "1"
    child_env["QT_QPA_PLATFORM"] = platform

    proc = subprocess.Popen(
        [sys.executable, *sys.argv],
        env=child_env,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    disconnect_seen = [False]

    def pump_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            if _is_wayland_disconnect_message(line):
                disconnect_seen[0] = True

    pump = threading.Thread(target=pump_stderr, daemon=True)
    pump.start()
    exit_code = proc.wait()
    pump.join(timeout=1.0)

    return exit_code, disconnect_seen[0]


def _run_gui(argv: list[str]) -> int:
    """Run the Qt GUI in this process. Never returns on wayland disconnect."""
    app = QApplication(argv)
    app.setApplicationName("Phonology Segment & Feature Engine")
    app.setOrganizationName("Phonology Research Tools")
    app.setStyle("Fusion")

    parser = QCommandLineParser()
    parser.setApplicationDescription("Phonology Segment & Feature Engine")
    parser.addHelpOption()
    parser.addPositionalArgument(
        "inventory",
        "Path to a JSON inventory file to load on startup.",
        "[inventory]",
    )
    parser.process(app)

    positional = parser.positionalArguments()

    if positional:
        startup_path = positional[0]
    else:
        startup_path = None

    # Lazy import. Avoid loading the full GUI module tree when --help exits early.
    from gui.main_window import MainWindow

    window = MainWindow(startup_path=startup_path)
    window.show()

    return app.exec()


def main() -> int:
    argv = sys.argv[:]

    # If we are the supervised child, just run — no recursive supervision.
    if os.environ.get(_FALLBACK_GUARD_ENV):
        return _run_gui(argv)

    user_set_platform = bool(
        os.environ.get("QT_QPA_PLATFORM")
    ) or _argv_requests_qt_platform(argv)

    if user_set_platform:
        # User picked the platform explicitly. Run direct, no fallback dance.
        return _run_gui(argv)

    auto_platform = _auto_qt_platform()
    have_x11_fallback = bool(os.environ.get("DISPLAY"))
    needs_supervision = auto_platform == "wayland" and have_x11_fallback

    if not needs_supervision:
        # Either no fallback exists, or wayland wasn't picked — run direct.
        if auto_platform is not None:
            argv[1:1] = ["-platform", auto_platform]
        return _run_gui(argv)

    # Try wayland under supervision; if the compositor drops the connection,
    # silently relaunch on xcb.
    rc, disconnect_seen = _spawn_gui_child("wayland")
    if disconnect_seen:
        rc, _ = _spawn_gui_child("xcb")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
