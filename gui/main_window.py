"""
gui/main_window.py
PyQt6 GUI for the Segment & Feature Engine.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QSettings,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QFont,
    QScreen,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from engine.feature_engine import FeatureEngine
from engine.inventory_validator import validate_inventory
from engine.segment_grouper import group_segments
from gui.analysis import (
    compute_contrastive,
    render_feat_to_seg,
    render_multi_segment,
    render_single_segment,
)
from gui.constants import (
    BTN_GAP,
    BTN_W,
    FEATURE_GROUPS,
    SCROLLBAR_STYLE,
    SETTINGS_APP,
    SETTINGS_ORG,
    sort_features,
)
from gui.palette import C
from gui.vowel_chart import VOWEL_LABEL_W, VowelChartWidget
from gui.widgets import (
    AnalysisPanel,
    FeatureRow,
    SegmentButton,
    SegmentGridWidget,
)

if TYPE_CHECKING:
    from gui.builder import InventoryBuilder

# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, startup_path: str | None = None):
        super().__init__()
        self.engine: FeatureEngine | None = None
        self._mode = "seg_to_feat"  # 'seg_to_feat' | 'feat_to_seg'
        self._seg_buttons: dict = {}  # segment → SegmentButton
        self._feat_rows: dict = {}  # feature  → FeatureRow
        self._selected_segments: list = []
        self._selected_features: dict = {}  # feature → '+'/'-'
        # Exact state of each mode when leaving it; projected into the other
        # mode as a convenience pre-fill on switch.
        self._saved_seg_state: list = []
        self._saved_feat_state: dict = {}
        self._current_path: str | None = None
        self._did_first_show = False
        # Per-engine cache for segment grouping. Cleared on engine reload.
        self._cached_groups: dict | None = None
        self._cached_norm_feats: dict | None = None
        self._builder: InventoryBuilder | None = None

        self.setWindowTitle("Language Doodad")
        self.setMinimumSize(640, 480)
        self.setStyleSheet(f"background-color: {C['bg']};")

        # -- 150 ms debounce: batch rapid selection changes before analysis --
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._run_pending_update)

        # -- file-system watcher: auto-reload when config JSON changes --
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        # Small delay so editors that do delete-then-write don't re-trigger
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(600)
        self._reload_timer.timeout.connect(self._do_auto_reload)

        # -- persistent settings --
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        self._build_ui()
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        app.installEventFilter(self)
        self._set_mode("seg_to_feat")
        self._restore_settings(startup_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── toolbar ──────────────────────────────────────────────────
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
        """)
        self.addToolBar(toolbar)

        # Config dropdown
        self.config_combo = QComboBox()
        self.config_combo.setFont(QFont("Noto Sans", 10))
        self.config_combo.setFixedHeight(32)
        self.config_combo.setMinimumWidth(220)
        self.config_combo.setStyleSheet(f"""
            QComboBox {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 10px;
            }}
            QComboBox:hover {{
                border: 1.5px solid {C["accent"]};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                selection-background-color: {C["accent_light"]};
                selection-color: {C["accent"]};
                outline: none;
            }}
        """)
        self._populate_config_dropdown()
        self.config_combo.activated.connect(self._on_config_selected)
        toolbar.addWidget(self.config_combo)

        # Browse button
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setFont(QFont("Noto Sans", 10))
        browse_btn.setFixedHeight(32)
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C["accent_light"]};
                border: 1.5px solid {C["accent"]};
                color: {C["accent"]};
            }}
        """)
        browse_btn.clicked.connect(self._browse_config)
        toolbar.addWidget(browse_btn)

        builder_btn = QPushButton("Builder")
        builder_btn.setFont(QFont("Noto Sans", 10))
        builder_btn.setFixedHeight(32)
        builder_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C["accent_light"]};
                border: 1.5px solid {C["accent"]};
                color: {C["accent"]};
            }}
        """)
        builder_btn.clicked.connect(self._open_builder)
        toolbar.addWidget(builder_btn)

        # ── central widget ────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {C['border']}; }}"
        )

        self.seg_panel = self._build_segment_panel()
        splitter.addWidget(self.seg_panel)

        self.feat_panel = self._build_feature_panel()
        splitter.addWidget(self.feat_panel)

        self._hsplit = splitter
        # Pre-load default: balanced split. _fit_to_content overrides
        # these once an inventory is loaded.
        splitter.setSizes([500, 400])
        splitter.setStretchFactor(0, 1)  # segments take extra space
        splitter.setStretchFactor(1, 0)  # features stay fixed width

        # ── bottom: analysis ──────────────────────────────────────────
        self.analysis = AnalysisPanel()

        self._vsplit = QSplitter(Qt.Orientation.Vertical)
        self._vsplit.setHandleWidth(4)
        self._vsplit.setStyleSheet(
            "QSplitter::handle { background: transparent; }"
        )
        self._vsplit.addWidget(splitter)
        self._vsplit.addWidget(self.analysis)
        self._vsplit.setSizes([700, 220])
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)
        self._min_analysis_h = 220

        root.addWidget(self._vsplit)

        # ── status bar ────────────────────────────────────────────────
        self.status = QStatusBar()
        self.status.setStyleSheet(
            f"background: {C['panel']}; border-top: 1px solid {C['border']};"
        )
        self.setStatusBar(self.status)
        self.status.showMessage(
            "Select an inventory from the dropdown to begin."
        )

    def _build_segment_panel(self) -> QFrame:
        container = QFrame()
        container.setObjectName("seg_panel")
        container.setStyleSheet(
            f"QFrame#seg_panel {{ background: {C['panel']}; }}"
        )
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(14, 14, 14, 10)
        vlay.setSpacing(10)

        header = QHBoxLayout()
        self._seg_title = QLabel("SEGMENTS")
        self._seg_title.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        self._seg_title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1.5px;"
        )

        self.clear_seg_btn = QPushButton("Clear")
        self.clear_seg_btn.setFixedHeight(26)
        self.clear_seg_btn.setFont(QFont("Noto Sans", 9))
        self.clear_seg_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C["text_dim"]};
                background: transparent;
                border: 1px solid {C["border"]};
                border-radius: 5px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                color: {C["text"]};
                background: {C["bg"]};
            }}
        """)
        self.clear_seg_btn.clicked.connect(self._clear_segments)

        header.addWidget(self._seg_title)
        header.addStretch()
        header.addWidget(self.clear_seg_btn)
        vlay.addLayout(header)

        self._seg_scroll = QScrollArea()
        self._seg_scroll.setWidgetResizable(True)
        self._seg_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._seg_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._seg_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._seg_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + SCROLLBAR_STYLE
        )

        seg_content = QWidget()
        seg_content.setStyleSheet("background: transparent;")

        seg_content_layout = QHBoxLayout(seg_content)
        seg_content_layout.setContentsMargins(0, 0, 0, 0)
        seg_content_layout.setSpacing(12)

        left_wrap = QWidget()
        left_wrap.setStyleSheet("background: transparent;")
        left_lay = QVBoxLayout(left_wrap)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        self.seg_grid_widget = SegmentGridWidget()
        left_lay.addWidget(self.seg_grid_widget)
        left_lay.addStretch()

        self.vowel_chart_widget = VowelChartWidget()
        self.vowel_chart_widget.hide()
        self.vowel_chart_widget.setFixedWidth(
            VOWEL_LABEL_W + 6 * (BTN_W + BTN_GAP)
        )

        seg_content_layout.addWidget(left_wrap, stretch=1)
        seg_content_layout.addWidget(
            self.vowel_chart_widget,
            stretch=0,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        self._seg_scroll.setWidget(seg_content)
        vp = self._seg_scroll.viewport()
        assert vp is not None
        vp.setStyleSheet("background: transparent;")
        vlay.addWidget(self._seg_scroll, stretch=1)

        self.seg_hint = QLabel("\u2190 Select an inventory to see segments")
        self.seg_hint.setFont(QFont("Noto Sans", 9))
        self.seg_hint.setStyleSheet(f"color: {C['text_dim']};")
        self.seg_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vlay.addWidget(self.seg_hint)

        return container

    def _build_feature_panel(self) -> QFrame:
        container = QFrame()
        container.setObjectName("feat_panel")
        container.setStyleSheet(
            f"QFrame#feat_panel {{ background: {C['bg']}; }}"
        )
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(14, 14, 14, 10)
        vlay.setSpacing(10)

        header = QHBoxLayout()
        self._feat_title = QLabel("FEATURES")
        self._feat_title.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        self._feat_title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1.5px;"
        )

        self.clear_feat_btn = QPushButton("Clear")
        self.clear_feat_btn.setFixedHeight(26)
        self.clear_feat_btn.setFont(QFont("Noto Sans", 9))
        self.clear_feat_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C["text_dim"]};
                background: transparent;
                border: 1px solid {C["border"]};
                border-radius: 5px;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                color: {C["text"]};
                background: {C["panel"]};
            }}
        """)
        self.clear_feat_btn.clicked.connect(self._clear_features)

        header.addWidget(self._feat_title)
        header.addStretch()
        header.addWidget(self.clear_feat_btn)
        vlay.addLayout(header)

        self._feat_scroll = QScrollArea()
        self._feat_scroll.setWidgetResizable(True)
        self._feat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feat_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + SCROLLBAR_STYLE
        )

        self._feat_content = QWidget()
        self._feat_content.setStyleSheet("background: transparent;")
        feat_main_layout = QHBoxLayout(self._feat_content)
        feat_main_layout.setContentsMargins(0, 0, 0, 0)
        feat_main_layout.setSpacing(8)

        self._feat_left_col = QWidget()
        self._feat_left_col.setStyleSheet("background: transparent;")
        self._feat_left_layout = QVBoxLayout(self._feat_left_col)
        self._feat_left_layout.setContentsMargins(0, 0, 0, 0)
        self._feat_left_layout.setSpacing(8)
        self._feat_left_layout.addStretch()

        self._feat_right_col = QWidget()
        self._feat_right_col.setStyleSheet("background: transparent;")
        self._feat_right_layout = QVBoxLayout(self._feat_right_col)
        self._feat_right_layout.setContentsMargins(0, 0, 0, 0)
        self._feat_right_layout.setSpacing(8)
        self._feat_right_layout.addStretch()

        feat_main_layout.addWidget(self._feat_left_col, stretch=1)
        feat_main_layout.addWidget(self._feat_right_col, stretch=1)

        self._feat_scroll.setWidget(self._feat_content)
        vlay.addWidget(self._feat_scroll, stretch=1)

        return container

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _target_screen(self) -> QScreen | None:
        """Return the primary screen.

        On multi-monitor setups, we always target the primary screen for
        initial placement.  The user can then drag the window wherever
        they like, and that position is saved/restored on next launch.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        return app.primaryScreen()

    def _ensure_visible_on_screen(self) -> None:
        """
        Run after the first show via QTimer so the WM has decorated the window.
        Ensures the window is on the primary screen.  If the user had a saved
        position that is still on *some* screen, we leave it alone; otherwise
        we center on the primary screen.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        screen = self._target_screen()
        if screen is None:
            return

        frame = self.frameGeometry()
        primary_geo = screen.geometry()

        # If the window is already mostly on the primary screen, keep it.
        if (
            primary_geo.intersects(frame)
            and frame.width() >= 300
            and frame.height() >= 200
        ):
            self.raise_()
            self.activateWindow()
            return

        # If the window is on *some* other screen and has a saved position,
        # leave it there — the user intentionally placed it.
        if self._settings.value("window_pos") is not None:
            on_any = any(s.geometry().intersects(frame) for s in app.screens())
            if on_any and frame.width() >= 300 and frame.height() >= 200:
                self.raise_()
                self.activateWindow()
                return

        # Otherwise, center on the primary screen.
        avail = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(avail.center())
        self.move(frame.topLeft())

        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._did_first_show:
            self._did_first_show = True
            QTimer.singleShot(0, self._ensure_visible_on_screen)

    def _restore_settings(self, startup_path: str | None) -> None:
        """Restore window size/position, mode, and last inventory on launch."""
        # Drop the old binary geometry blob — it encodes absolute positions that
        # can place the window off-screen after a display config change.
        self._settings.remove("geometry")

        self._has_saved_size = self._settings.value("window_size") is not None
        size = self._settings.value("window_size")
        pos = self._settings.value("window_pos")
        screen = self._target_screen()

        if size is not None:
            self.resize(size)
        else:
            # Reasonable pre-load default; _fit_to_content will refine after loading.
            if screen is not None:
                avail = screen.availableGeometry()
                self.resize(
                    min(1200, avail.width() - 40),
                    min(900, avail.height() - 40),
                )
            else:
                self.resize(1200, 900)

        if pos is not None:
            self.move(pos)
        elif screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())

        # Determine which inventory to open
        path = startup_path or self._settings.value("last_inventory")
        if path and isinstance(path, str) and os.path.isfile(path):
            idx = self.config_combo.findData(path)
            if idx >= 0:
                self.config_combo.setCurrentIndex(idx)
            self._load_path(path)

        # Restore mode after loading (overrides _load_path's default mode)
        saved_mode = self._settings.value("mode", "seg_to_feat")
        if saved_mode in ("seg_to_feat", "feat_to_seg"):
            self._set_mode(saved_mode)

    def closeEvent(self, event):  # type: ignore[override]
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.removeEventFilter(self)
        self._settings.remove("geometry")
        if self.isMaximized() or self.isFullScreen():
            normal = self.normalGeometry()
            self._settings.setValue("window_pos", normal.topLeft())
            self._settings.setValue("window_size", normal.size())
        else:
            self._settings.setValue("window_pos", self.pos())
            self._settings.setValue("window_size", self.size())
        self._settings.setValue("mode", self._mode)
        if self._current_path:
            self._settings.setValue("last_inventory", self._current_path)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _populate_config_dropdown(self) -> None:
        """Scan config/ directory and fill the dropdown."""
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "config")
        )
        self.config_combo.clear()
        self.config_combo.addItem("Select inventory\u2026", userData=None)

        # Disable the placeholder row so it cannot be picked.
        # QStandardItemModel is the default; the guard is defensive against
        # style plugins that substitute a different model type.  If it fails,
        # _on_config_selected's `if path:` guard still prevents any action.
        model = self.config_combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(0)
            if item is not None:
                item.setEnabled(False)

        if os.path.isdir(config_dir):
            for fname in sorted(os.listdir(config_dir)):
                if fname.endswith(".json"):
                    path = os.path.join(config_dir, fname)
                    pretty = fname[:-5].replace("_", " ").title()
                    self.config_combo.addItem(pretty, userData=path)

        self.config_combo.setCurrentIndex(0)

    def _on_config_selected(self, index: int):
        """Load the config chosen from the dropdown."""
        path = self.config_combo.itemData(index)
        if path:
            self._load_path(path)

    def _browse_config(self) -> None:
        """Open a file dialog and load the chosen JSON."""
        dlg = QFileDialog(
            self, "Open Phonological Inventory", "", "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        # Center on parent's screen for multi-monitor setups
        screen = self.screen()
        if screen:
            geo = screen.availableGeometry()
            frame = dlg.frameGeometry()
            frame.moveCenter(geo.center())
            dlg.move(frame.topLeft())
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if not path:
            return
        # Select existing entry or add a new one
        idx = self.config_combo.findData(path)
        if idx < 0:
            pretty = os.path.splitext(os.path.basename(path))[0]
            pretty = pretty.replace("_", " ").title()
            self.config_combo.addItem(pretty, userData=path)
            idx = self.config_combo.count() - 1
        self.config_combo.setCurrentIndex(idx)
        self._load_path(path)

    def _open_builder(self) -> None:
        if self._builder is not None and self._builder.isVisible():
            self._builder.raise_()
            self._builder.activateWindow()
            return
        from gui.builder import InventoryBuilder

        self._builder = InventoryBuilder(parent=self)
        self._builder.setWindowFlag(Qt.WindowType.Window)  # own taskbar entry
        self._builder.show()
        self._builder._show_setup_dialog()

    def _load_path(self, path: str):
        """Core loading logic shared by dropdown, browse, and auto-reload."""
        path = os.path.abspath(path)
        # Validate before loading — catches malformed JSON, bad values, etc.
        errors, warnings = validate_inventory(path)
        if errors:
            msg = f"Cannot load {os.path.basename(path)}: {errors[0]}"
            self.status.showMessage(msg)
            self.analysis.set_html(
                f"<p><b style='color:{C['minus']}'>Validation errors:</b></p>"
                + "".join(f"<p>{e}</p>" for e in errors)
                + (
                    "<p><b>Warnings:</b></p>"
                    + "".join(f"<p>{w}</p>" for w in warnings)
                    if warnings
                    else ""
                )
            )
            return
        if warnings:
            for w in warnings:
                self.status.showMessage(f"Warning: {w}")

        try:
            engine = FeatureEngine()
            engine.load_inventory(path)
            self.engine = engine
            self._cached_groups = None
            self._cached_norm_feats = None
            name = engine.metadata.get("name", os.path.basename(path))
            self.status.showMessage(
                f"{name}  \u2014  "
                f"{len(engine.segments)} segments, "
                f"{len(engine.features)} features."
            )

            # Update file-system watcher (file + containing directory)
            if self._current_path and self._current_path != path:
                self._watcher.removePath(self._current_path)
                old_dir = os.path.dirname(os.path.abspath(self._current_path))
                new_dir = os.path.dirname(os.path.abspath(path))
                if old_dir != new_dir:
                    self._watcher.removePath(old_dir)
            self._current_path = path
            if path not in self._watcher.files():
                self._watcher.addPath(path)
            parent_dir = os.path.dirname(os.path.abspath(path))
            if parent_dir not in self._watcher.directories():
                self._watcher.addPath(parent_dir)

            # Sync the dropdown to reflect the loaded inventory
            idx = self.config_combo.findData(path)
            if idx >= 0:
                self.config_combo.setCurrentIndex(idx)

            # Persist for next launch
            self._settings.setValue("last_inventory", path)

            self._saved_seg_state = []
            self._saved_feat_state = {}
            self._populate_segments()
            self._populate_features()
            self._apply_mode_to_new_widgets()
            self.analysis.clear()
            QTimer.singleShot(0, self._rebalance_vsplit)
        except Exception as e:
            self.status.showMessage(f"Error: {e}")

    # ------------------------------------------------------------------
    # File-system watcher: auto-reload on disk change
    # ------------------------------------------------------------------

    def _on_file_changed(self, path: str):
        """Called by QFileSystemWatcher when the watched file changes."""
        # Some editors remove and recreate the file; re-add if needed.
        QTimer.singleShot(
            200,
            lambda: (
                self._watcher.addPath(path)
                if path not in self._watcher.files()
                else None
            ),
        )
        self._reload_timer.start()

    def _on_directory_changed(self, _directory: str):
        """Called when the watched directory changes (file created/renamed/deleted)."""
        if not self._current_path:
            return
        # If the target file has reappeared but fell out of the file watcher, re-arm it.
        if (
            os.path.isfile(self._current_path)
            and self._current_path not in self._watcher.files()
        ):
            self._watcher.addPath(self._current_path)
            self._reload_timer.start()

    def _do_auto_reload(self) -> None:
        """Reload the current inventory after the debounce period."""
        if self._current_path and os.path.isfile(self._current_path):
            self._load_path(self._current_path)
            fname = os.path.basename(self._current_path)
            self.status.showMessage(f"Auto-reloaded \u201c{fname}\u201d")

    # ------------------------------------------------------------------
    # Populate panels
    # ------------------------------------------------------------------

    def _populate_segments(self):
        if self.engine is None:
            return
        self._selected_segments.clear()
        self.seg_hint.hide()

        # Cache grouping for the current engine. Cleared in _load_path
        # whenever a new engine is created, so a stale cache is impossible.
        if self._cached_groups is None:
            from engine.segment_grouper import _normalize_feats

            self._cached_groups = group_segments(self.engine.segments)
            self._cached_norm_feats = {
                seg: _normalize_feats(self.engine.segments[seg])
                for seg in self.engine.segments
            }

        groups = dict(self._cached_groups)  # shallow copy — pop mutates
        norm_feats = self._cached_norm_feats
        vowel_segs = groups.pop("Vowels", [])

        # Build consonant buttons
        consonant_buttons: dict = {}
        for segs in groups.values():
            for seg in segs:
                btn = SegmentButton(seg)
                btn.clicked.connect(
                    lambda checked, s=seg: self._on_segment_clicked(s, checked)
                )
                consonant_buttons[seg] = btn

        self.seg_grid_widget.set_groups(groups, consonant_buttons)

        # Build vowel buttons separately (vowel chart owns these)
        vowel_buttons: dict = {}
        if vowel_segs:
            for seg in vowel_segs:
                btn = SegmentButton(seg)
                btn.clicked.connect(
                    lambda checked, s=seg: self._on_segment_clicked(s, checked)
                )
                vowel_buttons[seg] = btn

            if norm_feats is not None:
                self.vowel_chart_widget.set_vowels(
                    vowel_segs, vowel_buttons, norm_feats
                )
                self.vowel_chart_widget.show()
        else:
            self.vowel_chart_widget.clear()
            self.vowel_chart_widget.hide()

        self._seg_buttons = {**consonant_buttons, **vowel_buttons}

    def _build_feature_group(
        self, title: str, features: list
    ) -> QFrame | None:
        """Build a labelled group card. Returns None if no features are active."""
        active = [f for f in features if f in self._feat_rows]
        if not active:
            return None

        group_frame = QFrame()
        group_frame.setStyleSheet(f"""
            QFrame {{
                background: {C["panel"]};
                border: 1px solid {C["border"]};
                border-radius: 7px;
            }}
        """)
        glay = QVBoxLayout(group_frame)
        glay.setContentsMargins(0, 6, 0, 6)
        glay.setSpacing(1)

        title_label = QLabel(title)
        title_label.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        title_label.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px; "
            "background: transparent; border: none; "
            "padding: 0 8px 2px 8px;"
        )
        glay.addWidget(title_label)

        for feat in active:
            glay.addWidget(self._feat_rows[feat])

        return group_frame

    def _populate_features(self) -> None:
        if self.engine is None:
            return

        active_feature_set: set = set()
        for seg_feats in self.engine.segments.values():
            for f, v in seg_feats.items():
                if v != "0":
                    active_feature_set.add(f)
        active_feature_set &= set(self.engine.features)

        # Skip full rebuild if the feature set hasn't changed
        if active_feature_set == set(self._feat_rows.keys()):
            self._selected_features.clear()
            for row in self._feat_rows.values():
                row.reset()
            return

        # Clear both columns
        for layout in (self._feat_left_layout, self._feat_right_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item is not None:
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()

        self._feat_rows.clear()
        self._selected_features.clear()

        # Build all FeatureRow widgets first so _build_feature_group can find them
        for feat in active_feature_set:
            row = FeatureRow(feat)
            row.value_changed.connect(self._on_feature_changed)
            self._feat_rows[feat] = row

        # Collect features not in any known group
        grouped_features = set()
        for _, feats in FEATURE_GROUPS:
            grouped_features.update(feats)
        unknown_active = sort_features(
            [f for f in active_feature_set if f not in grouped_features]
        )

        # Build cards and count active features per group
        all_groups = list(FEATURE_GROUPS)
        if unknown_active:
            all_groups.append(("Other", unknown_active))

        cards: list = []
        for title, feats_list in all_groups:
            card = self._build_feature_group(title, feats_list)
            if card is not None:
                active_count = sum(
                    1 for f in feats_list if f in self._feat_rows
                )
                cards.append((card, active_count))

        # Distribute cards to balance total feature count per column
        left_count = 0
        right_count = 0
        for card, count in cards:
            if left_count <= right_count:
                self._feat_left_layout.addWidget(card)
                left_count += count
            else:
                self._feat_right_layout.addWidget(card)
                right_count += count

        self._feat_left_layout.addStretch()
        self._feat_right_layout.addStretch()

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

    def _fit_to_content(self) -> None:
        """Measure actual content and size window + splitters to fit.

        Called after each inventory load.  On first load (no saved size),
        also resizes the window.  Always sets the horizontal splitter so
        both panels get the width their content needs.
        """
        QApplication.processEvents()

        # -- Measure segment panel content width --
        seg_content = self._seg_scroll.widget()
        seg_content_w = seg_content.sizeHint().width() if seg_content else 400
        seg_chrome = 28 + 6  # panel margins (14*2) + scrollbar clearance
        seg_padding = 50  # breathing room so content isn't flush to edges
        seg_need_w = seg_content_w + seg_chrome + seg_padding

        # -- Measure feature panel content --
        feat_content = self._feat_scroll.widget()
        feat_content_w = (
            feat_content.sizeHint().width() if feat_content else 380
        )
        feat_chrome = 28 + 6
        feat_padding = 40
        feat_need_w = feat_content_w + feat_chrome + feat_padding
        feat_content_h = (
            feat_content.sizeHint().height() if feat_content else 400
        )

        # Top panel: header chrome (~80px) + content + vertical breathing room
        feat_v_padding = 20
        top_need_h = feat_content_h + 80 + feat_v_padding
        analysis_h = self._min_analysis_h
        toolbar_h = 50  # toolbar + status bar
        total_need_h = (
            top_need_h + analysis_h + toolbar_h + 30
        )  # extra overall height

        # -- Size window to fit content on every inventory load --
        screen = self._target_screen()
        if screen is not None:
            avail = screen.availableGeometry()
            need_w = seg_need_w + feat_need_w + 1
            need_h = total_need_h

            # Grow to fit content, but never shrink below current size
            # (respects the user if they manually enlarged the window).
            cur_w = self.width()
            cur_h = self.height()
            new_w = min(max(need_w, cur_w), avail.width() - 40)
            new_h = min(max(need_h, cur_h), avail.height() - 40)
            new_w = max(new_w, 640)
            new_h = max(new_h, 480)

            if new_w != cur_w or new_h != cur_h:
                self.resize(new_w, new_h)

            # Center on first load only
            if not self._has_saved_size:
                frame = self.frameGeometry()
                frame.moveCenter(avail.center())
                self.move(frame.topLeft())
                self._has_saved_size = True

        # -- Apply to horizontal splitter --
        # Give both panels exactly what their content needs.
        # The splitter stretch factors (seg=1, feat=0) handle any extra
        # space — segments absorb it, features stay tight.
        self._hsplit.setSizes([seg_need_w, feat_need_w])

        # -- Rebalance vertical splitter --
        total = self._vsplit.height()
        if total > 0:
            top_h = min(top_need_h, total - self._min_analysis_h)
            top_h = max(top_h, 200)
            self._vsplit.setSizes([top_h, total - top_h])

    def _rebalance_vsplit(self) -> None:
        """Size the top panel so segments/features don't need scrollbars.

        On first call after loading, also fits the window to content.
        Subsequent calls (e.g. after resize) only adjust the vertical split.
        """
        self._fit_to_content()

    def _apply_mode_to_new_widgets(self) -> None:
        """After populating new widgets, apply the current mode's interactivity.

        Skips expensive panel-level stylesheet changes since those haven't
        changed — only the newly created feature rows and buttons need updating.
        """
        is_s2f = self._mode == "seg_to_feat"
        self.seg_grid_widget.set_headers_active(is_s2f)
        self.vowel_chart_widget.set_headers_active(is_s2f)
        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)
        self._clear_segments(silent=True)
        self._clear_features(silent=True)

    def _set_mode(self, mode: str):
        if mode != self._mode:
            if self._mode == "seg_to_feat":
                # Preserve exact seg selection so toggling back restores it
                self._saved_seg_state = list(self._selected_segments)
                # Project into feat mode: shared (non-contradictory) features only
                if self._selected_segments and self.engine:
                    self._saved_feat_state = {
                        f: v
                        for f, v in self.engine.common_features(
                            self._selected_segments
                        ).items()
                        if v in ("+", "-")
                    }
                else:
                    self._saved_feat_state = {}
            else:
                # Preserve exact feat query so toggling back restores it
                self._saved_feat_state = dict(self._selected_features)
                # Project into seg mode: segments matched by current feature query
                if self._selected_features and self.engine:
                    self._saved_seg_state = list(
                        self.engine.find_segments(self._selected_features)
                    )
                else:
                    self._saved_seg_state = []
        self._mode = mode
        is_s2f = mode == "seg_to_feat"

        seg_bg = C["panel"] if is_s2f else C["bg"]
        feat_bg = C["panel"] if not is_s2f else C["bg"]

        seg_vp = self._seg_scroll.viewport()
        feat_vp = self._feat_scroll.viewport()
        assert seg_vp is not None and feat_vp is not None
        seg_vp.setStyleSheet(f"background: {seg_bg};")
        self.seg_grid_widget.setStyleSheet(f"background: {seg_bg};")
        feat_vp.setStyleSheet(f"background: {feat_bg};")
        self._feat_content.setStyleSheet(f"background: {feat_bg};")

        self.seg_panel.setStyleSheet(
            f"QFrame#seg_panel {{ background: {seg_bg};"
            + (
                f" border: 1.5px solid {C['accent']};"
                if is_s2f
                else " border: none;"
            )
            + "}"
        )
        self.feat_panel.setStyleSheet(
            f"QFrame#feat_panel {{ background: {feat_bg};"
            + (
                f" border: 1.5px solid {C['accent']};"
                if not is_s2f
                else " border: none;"
            )
            + "}"
        )

        self._seg_title.setStyleSheet(
            f"color: {C['text'] if is_s2f else C['text_dim']}; letter-spacing: 1.5px;"
        )
        feat_color = C["text"] if not is_s2f else C["text_dim"]
        self._feat_title.setStyleSheet(
            f"color: {feat_color}; letter-spacing: 1.5px;"
        )
        self.seg_grid_widget.set_headers_active(is_s2f)
        self.vowel_chart_widget.set_headers_active(is_s2f)

        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)

        _clear_style = (
            f"color: {C['text']}; background: transparent;"
            f" border: 1px solid {C['border']}; border-radius: 5px; padding: 0 10px;"
        )
        for btn in (self.clear_seg_btn, self.clear_feat_btn):
            btn.setStyleSheet(
                f"QPushButton {{ {_clear_style} }}"
                f" QPushButton:hover {{ color: {C['text']}; background: {C['bg']}; }}"
            )

        self.analysis.clear()

        # Single-pass: set each button/row to its final state directly,
        # avoiding a clear-all then restore-some two-pass sequence.
        restore_segs = set(self._saved_seg_state) if is_s2f else set()
        self._selected_segments.clear()
        for seg, btn in self._seg_buttons.items():
            if seg in restore_segs:
                self._selected_segments.append(seg)
                if btn._state != "selected":
                    btn.set_state("selected")
                    btn.setChecked(True)
            elif btn._state != "default":
                btn.set_state("default")
                btn.setChecked(False)

        restore_feats = self._saved_feat_state if not is_s2f else {}
        self._selected_features.clear()
        for feat, row in self._feat_rows.items():
            if feat in restore_feats:
                self._selected_features[feat] = restore_feats[feat]
                row.restore_value(restore_feats[feat])
            elif row._current_value:
                row.reset()

        self._reset_feature_display()
        if is_s2f and self._selected_segments:
            self._update_seg_to_feat()
        elif not is_s2f and self._selected_features:
            self._update_feat_to_seg()

        if is_s2f:
            self.status.showMessage(
                "Click a segment to inspect its features."
                if self.engine
                else "Select an inventory from the dropdown to begin."
            )
        else:
            self.status.showMessage(
                "Toggle feature values (+/\u2212) to find matching segments."
                if self.engine
                else "Select an inventory from the dropdown to begin."
            )

    def eventFilter(self, a0, a1):
        """Activate a panel on any mouse press anywhere inside it."""
        if not isinstance(a0, QWidget):
            return False
        if a1 is not None and a1.type() == QEvent.Type.MouseButtonPress:
            w = a0
            while w is not None:
                if w is self.seg_panel:
                    if self._mode != "seg_to_feat":
                        self._set_mode("seg_to_feat")
                    break
                if w is self.feat_panel:
                    if self._mode != "feat_to_seg":
                        self._set_mode("feat_to_seg")
                    break
                w = w.parent()
        return False

    # ------------------------------------------------------------------
    # Event handlers  (state changes are immediate; analysis is debounced)
    # ------------------------------------------------------------------

    def _on_segment_clicked(self, segment: str, checked: bool):
        if self._mode != "seg_to_feat":
            # Prevent visual toggle in feat_to_seg mode
            self._seg_buttons[segment].setChecked(False)
            return
        btn = self._seg_buttons[segment]
        if checked:
            btn.set_state("selected")
            if segment not in self._selected_segments:
                self._selected_segments.append(segment)
        else:
            btn.set_state("default")
            if segment in self._selected_segments:
                self._selected_segments.remove(segment)
        self._debounce.start()

    def _on_feature_changed(self, feature: str, value: str):
        if self._mode != "feat_to_seg":
            return
        if value:
            self._selected_features[feature] = value
        else:
            self._selected_features.pop(feature, None)
        self._debounce.start()

    def _run_pending_update(self) -> None:
        """Fired by the debounce timer; dispatches to the active mode."""
        if self._mode == "seg_to_feat":
            self._update_seg_to_feat()
        else:
            self._update_feat_to_seg()

    # ------------------------------------------------------------------
    # Seg → Feat logic
    # ------------------------------------------------------------------

    def _update_seg_to_feat(self) -> None:
        segs = self._selected_segments
        if not segs or not self.engine:
            self._reset_feature_display()
            for btn in self._seg_buttons.values():
                btn.set_state("default")
            self.analysis.clear()
            return

        selected_set = set(segs)

        if len(segs) == 1:
            feats = self.engine.get_segment_features(segs[0])
            for feat, row in self._feat_rows.items():
                v = feats.get(feat, "0")
                row.set_display("" if v == "0" else v, shared=True)
            for seg, btn in self._seg_buttons.items():
                if seg not in selected_set:
                    btn.set_state("default")
            self.analysis.set_html(
                render_single_segment(self.engine, segs[0], feats)
            )
        else:
            common = self.engine.common_features(segs)
            contrastive = compute_contrastive(self.engine, segs)
            for feat, row in self._feat_rows.items():
                if feat in common:
                    row.set_display(common[feat], shared=True)
                elif feat in contrastive:
                    row.set_display("", shared=False, contrastive=True)
                else:
                    row.set_display("", shared=False)

            # Natural class completion: find segments that would extend the
            # current selection to the smallest valid natural class.
            is_nc, _ = self.engine.is_natural_class(segs)
            suggested: list = []
            if not is_nc and common:
                nc_extension = self.engine.find_segments(
                    common, underspec_compatible=True
                )
                suggested = [s for s in nc_extension if s not in selected_set]

            suggested_set = set(suggested)
            for seg, btn in self._seg_buttons.items():
                if seg not in selected_set:
                    btn.set_state(
                        "suggested" if seg in suggested_set else "default"
                    )

            self.analysis.set_html(
                render_multi_segment(
                    self.engine, segs, common, contrastive, suggested
                )
            )

    # ------------------------------------------------------------------
    # Feat → Seg logic
    # ------------------------------------------------------------------

    def _update_feat_to_seg(self) -> None:
        if not self.engine:
            return

        selected_feats = self._selected_features
        if not selected_feats:
            for btn in self._seg_buttons.values():
                btn.set_state("default")
            self.analysis.clear()
            return

        matching = self.engine.find_segments(selected_feats)
        matching_set = set(matching)

        for seg, btn in self._seg_buttons.items():
            btn.set_state("matched" if seg in matching_set else "unmatched")

        self.analysis.set_html(
            render_feat_to_seg(self.engine, selected_feats, matching)
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reset_feature_display(self) -> None:
        for row in self._feat_rows.values():
            row.reset()

    def _clear_segments(self, silent=False):
        self._selected_segments.clear()
        for btn in self._seg_buttons.values():
            if btn._state != "default":
                btn.set_state("default")
                btn.setChecked(False)
        self._reset_feature_display()
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()

    def _clear_features(self, silent=False):
        self._selected_features.clear()
        for row in self._feat_rows.values():
            if row._current_value:
                row.reset()
        for btn in self._seg_buttons.values():
            if btn._state != "default":
                btn.set_state("default")
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()
