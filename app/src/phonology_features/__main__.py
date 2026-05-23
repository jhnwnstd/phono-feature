#!/usr/bin/env python3
"""Phonology Segment & Feature Engine. Desktop app for browsing
inventories, inspecting features, computing natural classes, finding
minimal distinguishing feature sets, and inferring feature geometry.

Usage:
    python -m phonology_features [inventory.json]
    python -m phonology_features -platform xcb
    python -m phonology_features -platform wayland

After ``pip install`` the ``phonology-features`` console script is
also installed with the same arguments.
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
    """True if a line of Qt output reports a fatal Wayland connection drop.

    Some compositors (XWayland bridges, nested sessions, flaky VNC) accept
    the initial wl_display connection but tear it down once the client
    starts painting. The Qt wayland plugin logs this message and then
    terminates the process directly, so ``app.exec()`` never returns. We
    can only catch the death from a supervisor parent.
    """
    if message is None:
        return False
    return "wayland connection broke" in message.lower()


def _spawn_gui_child(platform: str) -> tuple[int, bool]:
    """Run the GUI as a child process pinned to ``platform``. Returns
    (exit_code, wayland_disconnect_seen). The child's stderr is streamed
    to ours in real time.
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
    """Run the Qt GUI in this process. Doesn't return on Wayland disconnect."""
    app = QApplication(argv)
    app.setApplicationName("Phonology Segment & Feature Engine")
    app.setOrganizationName("Phonology Research Tools")
    # Wayland uses this to map the process to a .desktop file; without
    # it, WSLg / GNOME / KDE show a generic fallback icon.
    app.setDesktopFileName("phonology-features")
    from PyQt6.QtGui import QColor, QIcon, QPixmap

    icon_pix = QPixmap(64, 64)
    icon_pix.fill(QColor("#2563EB"))
    app.setWindowIcon(QIcon(icon_pix))
    app.setStyle("Fusion")
    # Seed Qt's default palette + app-wide background BEFORE any window
    # is constructed. Without this, the compositor's initial surface
    # is filled by Qt against its default light palette; in dark mode
    # the user sees a brief light flash inside any region our QSS
    # hasn't painted yet (typical on Wayland/WSLg). Reading the saved
    # theme here keeps this in sync with whatever MainWindow will pick.
    from PyQt6.QtCore import QSettings
    from PyQt6.QtGui import QPalette
    from phonology_features.gui.constants import SETTINGS_APP, SETTINGS_ORG
    from phonology_features.gui.palette import C, detect_system_theme, set_theme
    _settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    _seed_theme = _settings.value("theme", detect_system_theme())
    if not isinstance(_seed_theme, str):
        _seed_theme = detect_system_theme()
    set_theme(_seed_theme)
    _pal = app.palette()
    _bg = QColor(C["bg"])
    _pal.setColor(QPalette.ColorRole.Window, _bg)
    _pal.setColor(QPalette.ColorRole.Base, _bg)
    app.setPalette(_pal)
    app.setStyleSheet(f"QMainWindow {{ background: {C['bg']}; }}")
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
    # Lazy import: skip loading the GUI tree when --help exits early.
    from phonology_features.gui.main_window import MainWindow

    window = MainWindow(startup_path=startup_path)
    # Force-realize the native handle so Qt commits the final geometry
    # in one xdg_toplevel.configure round on Wayland, not two (default
    # size -> our size). Cuts the brief flash where the compositor maps
    # at minimum size before our resize takes effect.
    window.winId()
    window.show()
    app.processEvents()
    return app.exec()


def main() -> int:
    argv = sys.argv[:]
    # Supervised child: just run, no recursive supervision.
    if os.environ.get(_FALLBACK_GUARD_ENV):
        return _run_gui(argv)
    user_set_platform = bool(
        os.environ.get("QT_QPA_PLATFORM")
    ) or _argv_requests_qt_platform(argv)
    if user_set_platform:
        return _run_gui(argv)
    auto_platform = _auto_qt_platform()
    have_x11_fallback = bool(os.environ.get("DISPLAY"))
    needs_supervision = auto_platform == "wayland" and have_x11_fallback
    if not needs_supervision:
        if auto_platform is not None:
            argv[1:1] = ["-platform", auto_platform]
        return _run_gui(argv)
    # Try Wayland under supervision; silently relaunch on xcb if the
    # compositor drops the connection.
    rc, disconnect_seen = _spawn_gui_child("wayland")
    if disconnect_seen:
        rc, _ = _spawn_gui_child("xcb")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
