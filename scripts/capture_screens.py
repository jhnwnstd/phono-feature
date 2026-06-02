"""Drive the GUI through representative states and save PNGs.

Run from anywhere; uses ``QT_QPA_PLATFORM=offscreen`` so no display is
needed. Outputs to ``.github/screenshots/`` at the repo root (used by
the README and PR templates so the images travel with the repo, not
in a separate docs tree).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent.parent
APP_DIR = REPO_ROOT / "app"
SRC_DIR = APP_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

INVENTORIES = sorted((APP_DIR / "inventories").glob("*.json"))
OUT_DIR = REPO_ROOT / ".github" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIN_W, WIN_H = 1600, 1050


def _isolate_qsettings() -> None:
    td = tempfile.mkdtemp(prefix="phon-shots-")
    from PyQt6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, td)


def main() -> int:
    _isolate_qsettings()
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication

    from phonology_features.gui.main_window import MainWindow, Mode

    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    win = MainWindow()
    win.show()
    app.processEvents()

    def settle(ms: int = 0) -> None:
        for _ in range(4):
            app.processEvents()

        if ms > 0:
            loop = QEventLoop()
            QTimer.singleShot(ms, loop.quit)
            loop.exec()

        for _ in range(4):
            app.processEvents()

    def force_size(w: int = WIN_W, h: int = WIN_H) -> None:
        # _fit_to_content autoshrinks after a load; override here so the
        # full segments grid + features panel + analysis pane all fit.
        win.resize(w, h)
        settle()

    def grab(name: str, widget=None) -> None:
        settle(1000)
        target = widget or win
        pix = target.grab()
        path = OUT_DIR / f"{name}.png"
        pix.save(str(path), "PNG")
        print(
            f"  wrote {path.relative_to(REPO_ROOT)}  ({pix.width()}x{pix.height()})"
        )

    hayes = next(p for p in INVENTORIES if "hayes" in p.name.lower())
    win._load_path(str(hayes))
    win._set_mode(Mode.SEG_TO_FEAT)
    settle()  # let _fit_to_content's deferred autoshrink fire first
    force_size()
    print("Phase 1: Hayes loaded, ready to explore")
    grab("01_overview")

    print(
        "Phase 2: voiced stops /b d ɡ/ selected -> shared features in analysis"
    )
    for s in ("b", "d", "ɡ"):
        if s in win._seg_buttons:
            win._on_segment_clicked(s, True)
    # _on_segment_clicked schedules the analysis through a 150 ms debounce
    # timer; bypass it so the screenshot doesn't catch an empty pane.
    win._mode_ctrl.refresh_analysis()
    settle()
    force_size()
    grab("02_voiced_stops")

    print("Phase 3: feat-to-seg query [+nasal, +sonorant] -> nine nasals")
    win._clear_segments(silent=True)
    win._set_mode(Mode.FEAT_TO_SEG)
    settle()
    # Drive the row's own _on_click so the row tints itself ("+ chip
    # green"); calling _on_feature_changed directly updates the model
    # but bypasses the row's visual state, leaving the query invisible.
    for f in ("Nasal", "Sonorant"):
        if f in win._feat_rows:
            win._feat_rows[f]._on_click("+")
    win._mode_ctrl.refresh_analysis()
    settle()
    force_size()
    grab("03_nasal_query")

    print("Phase 4: Inventory Builder editing Hayes")
    win._open_builder()
    settle()
    if win._builder is not None:
        win._builder.resize(1500, 950)
        win._builder.show()
        settle()
        grab("04_builder", widget=win._builder)
        win._builder.close()
        win._builder = None

    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
