"""
Pytest fixtures for headless GUI tests.

Runs the full PyQt6 widget tree against the offscreen platform plugin so the
state machine can be exercised without a display server. QSettings is
redirected to a per-session temp dir so the user's real saved preferences are
never touched.
"""

from __future__ import annotations

import os

# Must be set before any PyQt6 import so the QApplication picks the
# right plugin. The imports below are intentionally post-env-setup
# (flake8 E402 silenced).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_palette_module_state() -> None:
    """Pin module-level palette state to (light, standard) before
    each test.

    :py:mod:`phonology_features.gui.palette` keeps ``_active_theme``,
    ``_active_mode``, ``C``, and ``theme_version`` at module scope so
    a test that mutates them leaks into the next test's view of the
    palette. Today the suite happens to pass anyway because most
    tests reset implicitly via MainWindow construction, but the
    invariant is fragile: a future test that constructs widgets
    directly (no MainWindow) inherits whatever the previous test
    left behind.

    Resetting in an autouse fixture removes the order dependency
    without forcing every test to import the palette module just to
    clean up after itself. Yield-less form because the reset has no
    cleanup; one-call-per-test is enough.
    """
    from phonology_features.gui.palette import (
        set_palette_mode,
        set_theme,
    )

    set_theme("light")
    set_palette_mode("standard")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory: pytest.TempPathFactory) -> QApplication:
    """Single QApplication for the whole session.

    Qt only allows one QApplication per process, so this is session-scoped.
    QSettings is redirected to a temp dir for the same reason; and because
    we don't want tests reading/writing the developer's real config.
    """
    settings_dir = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    # MainWindow constructs QSettings(org, app) which uses NativeFormat on
    # all platforms; redirecting only IniFormat would leak the developer's
    # real config into the test run. Redirect both formats to be safe.
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(settings_dir))
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
    from phonology_features.gui.main_window import MainWindow

    repo_root = Path(__file__).resolve().parent.parent
    inventory = str(repo_root / "inventories" / "hayes_features.json")
    w = MainWindow()
    w._load_path(inventory)
    w._set_mode("seg_to_feat")
    yield w
    w.close()


def close_builder_silent(builder) -> None:
    """Close an InventoryBuilder in tests without triggering the
    unsaved-changes modal.

    The builder's ``closeEvent`` calls ``_check_unsaved()`` which
    pops a modal ``QMessageBox`` when ``_dirty`` is True. Modal
    ``exec()`` blocks the event loop waiting for a user click that
    never comes under the offscreen QPA, so tests that mutated the
    grid would hang forever on teardown.

    Forcing ``_dirty=False`` is the cheapest fix: it asserts "no
    unsaved changes worth prompting about" and lets ``closeEvent``
    fall through cleanly. ``_save_in_flight`` is also forced low
    because any pending save would block via ``_wait_for_save`` --
    tests that care about that path should call ``_wait_for_save``
    explicitly rather than relying on close-time bookkeeping.
    """
    builder._dirty = False
    builder._save_in_flight = False
    builder.close()


@pytest.fixture
def close_builder_silent_fn():
    """Expose ``close_builder_silent`` as a pytest fixture for tests
    that prefer parameter injection over module import."""
    return close_builder_silent
