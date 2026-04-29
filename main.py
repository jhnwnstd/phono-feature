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
import sys

from PyQt6.QtCore import QCommandLineParser
from PyQt6.QtWidgets import QApplication


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


def main() -> int:
    argv = sys.argv[:]

    qt_platform_from_environment = os.environ.get("QT_QPA_PLATFORM")
    qt_platform_from_argv = _argv_requests_qt_platform(argv)
    should_choose_platform = (
        not qt_platform_from_environment and not qt_platform_from_argv
    )

    if should_choose_platform:
        platform = _auto_qt_platform()

        if platform is not None:
            argv[1:1] = ["-platform", platform]

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


if __name__ == "__main__":
    raise SystemExit(main())
