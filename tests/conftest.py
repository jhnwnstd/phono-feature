"""
Pytest fixtures for headless GUI tests.

Runs the full PyQt6 widget tree against the offscreen platform plugin so the
state machine can be exercised without a display server. QSettings is
redirected to a per-session temp dir so the user's real saved preferences are
never touched.
"""

from __future__ import annotations

import os

# Must be set before any PyQt6 import so the QApplication picks the right plugin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp(tmp_path_factory: pytest.TempPathFactory) -> QApplication:
    """Single QApplication for the whole session.

    Qt only allows one QApplication per process, so this is session-scoped.
    QSettings is redirected to a temp dir for the same reason; and because
    we don't want tests reading/writing the developer's real config.
    """
    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_dir),
    )
    app = QApplication.instance() or QApplication([])
    return app  # type: ignore[return-value]


@pytest.fixture
def window(qapp: QApplication):
    """Fresh MainWindow with the Hayes inventory loaded and seg_to_feat mode.

    Each test gets its own window so state can't leak between tests. We force
    seg_to_feat after load because _load_path may otherwise honor a persisted
    mode from settings; tests want a deterministic starting state.
    """
    # Late import: keeps QT_QPA_PLATFORM env var setup before the first PyQt
    # import in conftest module-load order.
    from gui.main_window import MainWindow

    repo_root = Path(__file__).resolve().parent.parent
    inventory = str(repo_root / "config" / "hayes_features.json")
    w = MainWindow()
    w._load_path(inventory)
    w._set_mode("seg_to_feat")
    yield w
    w.close()
