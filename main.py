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

Author: Claude
License: MIT
"""

import sys
from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def main():
    """Main entry point for the application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Phonology Segment & Feature Engine")
    app.setOrganizationName("Phonology Research Tools")

    # Set application-wide style
    app.setStyle('Fusion')

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
