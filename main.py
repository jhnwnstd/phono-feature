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

from gui.main_window import MainWindow


def _argv_requests_qt_platform(argv: list[str]) -> bool:
    return any(
        arg == "-platform" or arg.startswith("-platform=") for arg in argv
    )


def _detect_qt_platform(argv: list[str]) -> str | None:
    if os.environ.get("QT_QPA_PLATFORM"):
        return None
    if _argv_requests_qt_platform(argv):
        return None
    if not sys.platform.startswith("linux"):
        return None

    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    if wayland_display:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        socket_path = (
            wayland_display
            if os.path.isabs(wayland_display)
            else os.path.join(runtime_dir, wayland_display)
        )
        if os.path.exists(socket_path):
            return "wayland"

    if os.environ.get("DISPLAY"):
        return "xcb"

    return None


def main() -> int:
    argv = sys.argv[:]

    platform = _detect_qt_platform(argv)
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
    startup_path = positional[0] if positional else None

    window = MainWindow(startup_path=startup_path)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
