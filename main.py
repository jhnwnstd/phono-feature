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

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtCore import QCommandLineParser  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Phonology Segment & Feature Engine")
    app.setOrganizationName("Phonology Research Tools")

    # Set application-wide style
    app.setStyle("Fusion")

    # Parse optional positional inventory path argument
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

    # Create and show main window
    window = MainWindow(startup_path=startup_path)
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
