#!/usr/bin/env python3
"""
Cold-start profile of the full app session.

Walks through the interactions a real user would perform: launch, load
each bundled inventory, toggle segments and features, switch modes,
toggle the theme, and open the Builder. Each phase is wrapped in its
own cProfile run, then the combined stats are printed sorted by
cumulative and tottime.

Run from anywhere; the script puts ``app/src/`` on sys.path and uses the
offscreen Qt platform plugin so no display is needed:

    python app/tools/profile_app.py
    python app/tools/profile_app.py --section seg_toggle  # one phase only
"""

from __future__ import annotations

import argparse
import cProfile
import io
import os
import pstats
import sys
import time
from pathlib import Path

# --- bootstrap ----------------------------------------------------------------

HERE = Path(__file__).resolve()
APP_DIR = HERE.parent.parent  # app/
SRC_DIR = APP_DIR / "src"  # app/src/
sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

INVENTORIES_DIR = APP_DIR / "inventories"
INVENTORIES = sorted(p for p in INVENTORIES_DIR.glob("*.json"))


def _redirect_qsettings_to_tempdir() -> None:
    """Make sure the profile run doesn't read/write the developer's real
    QSettings (which carries window position, last-loaded inventory, etc.).
    """
    import tempfile

    from PyQt6.QtCore import QSettings

    td = tempfile.mkdtemp(prefix="phon-profile-")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, td)


# --- profiling helpers --------------------------------------------------------


class Phase:
    """One named phase of the simulated session."""

    def __init__(self, name: str, fn) -> None:
        self.name = name
        self.fn = fn
        self.wall: float = 0.0
        self.profile = cProfile.Profile()

    def run(self) -> None:
        self.profile.enable()
        t0 = time.perf_counter()
        try:
            self.fn()
        finally:
            self.wall = time.perf_counter() - t0
            self.profile.disable()


def print_section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")


def print_phase_summary(phases: list[Phase]) -> None:
    print_section("Per-phase wall clock")
    width = max(len(p.name) for p in phases)
    total = sum(p.wall for p in phases)
    for p in phases:
        bar = "#" * int(40 * p.wall / total) if total else ""
        print(f"  {p.name:<{width}}  {p.wall * 1000:7.1f} ms  {bar}")
    print(f"  {'TOTAL':<{width}}  {total * 1000:7.1f} ms")


def print_top(phases: list[Phase], sort_key: str, n: int = 20) -> None:
    combined = pstats.Stats(phases[0].profile)
    for p in phases[1:]:
        combined.add(p.profile)
    buf = io.StringIO()
    combined.stream = buf  # type: ignore[attr-defined]
    combined.sort_stats(sort_key).print_stats(n)
    print(buf.getvalue())


# --- session ------------------------------------------------------------------


def run_session(only: str | None = None) -> None:
    """Build and run every interaction phase, recording each separately."""
    _redirect_qsettings_to_tempdir()

    # PyQt imports stay deferred so QT_QPA_PLATFORM applies first.
    from PyQt6.QtWidgets import QApplication

    from phonology_features.gui.main_window import MainWindow, Mode

    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)

    win: MainWindow | None = None

    def cold_start() -> None:
        nonlocal win
        win = MainWindow()
        win.show()
        app.processEvents()

    def load_first_inventory() -> None:
        assert win is not None
        win._load_path(str(INVENTORIES[0]))
        app.processEvents()

    def switch_through_all_inventories() -> None:
        """Each bundled inventory gets loaded twice: first time exercises
        the cold path (engine rebuilds caches), second time exercises the
        warm cache path."""
        assert win is not None
        for path in INVENTORIES:
            win._load_path(str(path))
            app.processEvents()
        for path in INVENTORIES:
            win._load_path(str(path))
            app.processEvents()

    def toggle_segments() -> None:
        assert win is not None
        win._set_mode(Mode.SEG_TO_FEAT)
        app.processEvents()
        segments = list(win._seg_buttons.keys())[:30]
        # Select then deselect each in turn to exercise both branches.
        for s in segments:
            win._on_segment_clicked(s, True)
        app.processEvents()
        for s in segments:
            win._on_segment_clicked(s, False)
        app.processEvents()

    def toggle_features() -> None:
        assert win is not None
        win._set_mode(Mode.FEAT_TO_SEG)
        app.processEvents()
        features = list(win._feat_rows.keys())[:15]
        for f in features:
            win._on_feature_changed(f, "+")
        app.processEvents()
        for f in features:
            win._on_feature_changed(f, "-")
        app.processEvents()
        for f in features:
            win._on_feature_changed(f, "")
        app.processEvents()

    def mode_switch_burst() -> None:
        assert win is not None
        for _ in range(10):
            win._set_mode(Mode.FEAT_TO_SEG)
            win._set_mode(Mode.SEG_TO_FEAT)
        app.processEvents()

    def theme_toggle_burst() -> None:
        assert win is not None
        for _ in range(6):
            win._toggle_theme()
            app.processEvents()

    def open_builder() -> None:
        assert win is not None
        win._open_builder()
        app.processEvents()
        # Close it so it doesn't keep affecting later phases.
        if win._builder is not None:
            win._builder.close()
            win._builder = None
        app.processEvents()

    phases: list[Phase] = [
        Phase("cold_start", cold_start),
        Phase("load_first_inventory", load_first_inventory),
        Phase("switch_all_inventories", switch_through_all_inventories),
        Phase("toggle_segments_x60", toggle_segments),
        Phase("toggle_features_x45", toggle_features),
        Phase("mode_switch_x20", mode_switch_burst),
        Phase("theme_toggle_x6", theme_toggle_burst),
        Phase("open_close_builder", open_builder),
    ]

    if only:
        phases = [p for p in phases if p.name == only]
        if not phases:
            print(f"Unknown phase: {only!r}", file=sys.stderr)
            sys.exit(2)

    for p in phases:
        print(f"Running phase: {p.name} ...", flush=True)
        p.run()

    print_phase_summary(phases)

    print_section("Top 25 by cumulative time (combined)")
    print_top(phases, "cumulative", n=25)

    print_section("Top 25 by total time (combined)")
    print_top(phases, "tottime", n=25)

    # Per-phase top-10 cumulative for the slowest three phases
    phases_sorted = sorted(phases, key=lambda p: -p.wall)
    for p in phases_sorted[:3]:
        print_section(
            f"Top 10 cumulative in '{p.name}' ({p.wall * 1000:.0f} ms)"
        )
        buf = io.StringIO()
        s = pstats.Stats(p.profile)
        s.stream = buf  # type: ignore[attr-defined]
        s.sort_stats("cumulative").print_stats(10)
        print(buf.getvalue())

    if win is not None:
        win.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", help="Run only this phase by name")
    args = parser.parse_args()
    run_session(only=args.section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
