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
    python main.py

"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QCommandLineParser
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


def main() -> int:
    app = QApplication(sys.argv)
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
