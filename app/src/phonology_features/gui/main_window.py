"""
gui/main_window.py
PyQt6 GUI for the Segment & Feature Engine.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from enum import StrEnum
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
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from phonology_features.engine.feature_engine import FeatureEngine
from phonology_features.engine.inventory_validator import (
    validate_inventory_data,
)
from phonology_features.engine.segment_grouper import group_segments
from phonology_features.gui.analysis import (
    compute_contrastive,
    render_feat_to_seg,
    render_multi_segment,
    render_single_segment,
)
from phonology_features.gui.constants import (
    BTN_GAP,
    BTN_W,
    FEATURE_GROUPS,
    FEATURE_ORDER,
    SETTINGS_APP,
    SETTINGS_ORG,
    scrollbar_style,
    sort_features,
)
from phonology_features.gui.palette import C, get_theme_name, set_theme
from phonology_features.gui.vowel_chart import VOWEL_LABEL_W, VowelChartWidget
from phonology_features.gui.widgets import (
    AnalysisPanel,
    FeatureRow,
    SegmentButton,
    SegmentGridWidget,
    SegmentState,
)

if TYPE_CHECKING:
    from phonology_features.gui.builder import InventoryBuilder
# Mode-independent: same style applied at construction, never changed
# (within one theme). Function rather than module-level constant so it
# evaluates against the current palette; important after a live
# theme swap, where the constant would have been baked at import time.


def _clear_btn_style() -> str:
    return (
        f"QPushButton {{"
        f" color: {C['text']}; background: transparent;"
        f" border: 1px solid {C['border']};"
        f" border-radius: 5px; padding: 0 10px;"
        f" }}"
        f" QPushButton:hover {{ color: {C['text']};"
        f" background: {C['bg']}; }}"
    )


# Minimum decoration assumed when the WM doesn't report frame extents
# (Wayland CSD, some X11 themes). Used to guarantee the window's frame
# stays inside the screen during inventory swaps even when Qt thinks
# the frame equals the widget.
_MIN_DECO_W = 8
_MIN_DECO_H = 32

# Cached enum member: eventFilter runs on every Qt event (10k+ per
# user action), and resolving QEvent.Type.MouseButtonPress through the
# enum machinery on each call shows up in profiles. Binding to a name
# once turns the comparison into a single attribute load.
_QEVENT_MOUSE_BUTTON_PRESS = QEvent.Type.MouseButtonPress


class Mode(StrEnum):
    """Top-level UI mode. StrEnum members compare equal to their string
    values, so existing comparisons against bare strings keep working."""

    SEG_TO_FEAT = "seg_to_feat"
    FEAT_TO_SEG = "feat_to_seg"


class _BrandedStatusBar(QStatusBar):
    """Status bar with a 'Language Doodad' brand pinned at the lower-right.

    Default QStatusBar.showMessage() hides any addWidget() items while a
    message is shown; that would blink the message label on every
    status update. This subclass instead routes messages to a managed
    QLabel on the left, so both message and brand stay visible at all
    times. The brand uses addPermanentWidget() to anchor it on the right.

    Both labels share an explicit font, height policy, and vertical
    centering so the bar's row height accommodates them consistently and
    they sit on the same baseline regardless of italic vs regular metrics.
    """

    _FONT = QFont("Noto Sans", 9)
    # Picked so italic ascenders/descenders don't push the bar taller
    # than non-italic text would. ~22 px matches the toolbar baseline.
    _BAR_HEIGHT = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(self._BAR_HEIGHT)
        self._message_label = QLabel("")
        self._message_label.setFont(self._FONT)
        self._message_label.setStyleSheet(f"color: {C['text']};")
        self._message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._brand = QLabel("Language Doodad")
        self._brand.setFont(self._FONT)
        self._brand.setStyleSheet(
            f"color: {C['text_dim']}; font-style: italic; padding: 0 4px;"
        )
        self._brand.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # Left section: message label fills remaining width.
        self.addWidget(self._message_label, 1)
        # Right section: brand sits permanently in the lower-right corner.
        self.addPermanentWidget(self._brand, 0)

    def showMessage(self, text: str, timeout: int = 0) -> None:  # type: ignore[override]
        # Don't call super(); that would hide left-section widgets.
        # timeout=0 (no auto-clear) is the only mode the app uses, so we
        # ignore the parameter.
        self._message_label.setText(text)

    def clearMessage(self) -> None:  # type: ignore[override]
        self._message_label.setText("")

    def currentMessage(self) -> str:  # type: ignore[override]
        return self._message_label.text()


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, startup_path: str | None = None):
        super().__init__()
        self.engine: FeatureEngine | None = None
        self._mode: Mode = Mode.SEG_TO_FEAT
        # segment -> SegmentButton for the active inventory
        self._seg_buttons: dict = {}
        # Cross-inventory pool: keyed by segment symbol. Created once and
        # reused on subsequent loads where the symbol reappears (most do ;
        # /p t k m n s/ etc. are nearly universal). The grid and chart
        # layouts are still recomputed every swap; this only avoids the
        # QPushButton.__init__ + setStyleSheet costs for known symbols.
        self._seg_button_pool: dict[str, SegmentButton] = {}
        self._feat_rows: dict = {}  # feature  -> FeatureRow
        self._selected_segments: list = []
        self._selected_features: dict = {}  # feature -> '+'/'-'
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
        # Row pool: built once on first inventory load, then show/hide per
        # subsequent load instead of destroying and recreating widgets.
        # _feat_row_pool holds every row created (full FEATURE_ORDER plus any
        # inventory-specific extras). _feat_rows above keeps its existing
        # contract; only active-this-inventory rows; so external code that
        # iterates _feat_rows is unaffected.
        self._feat_row_pool: dict[str, FeatureRow] = {}
        self._feat_cards: list[tuple[QFrame, list[str]]] = []
        self._other_card: QFrame | None = None
        self._feature_pool_initialized: bool = False
        # Depth counter for ``_batched_updates`` so nested scopes share
        # one setUpdatesEnabled(False/True) pair instead of toggling
        # paint events back on mid-rebuild.
        self._batched_depth: int = 0
        self.setWindowTitle("Feature visualizer")
        self.setMinimumSize(640, 480)
        # -- persistent settings (read theme before ANY palette-using
        # stylesheet evaluates) --
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Apply the saved theme BEFORE the QMainWindow background and
        # _build_ui so every f-string baked into a stylesheet during
        # construction picks up the right palette. Was previously
        # ordered after the setStyleSheet below; on a dark-mode cold
        # start the main window's own background was baked light while
        # children built by _build_ui were dark, leaving light streaks
        # around toolbar margins and splitter handles until the user
        # toggled the theme twice.
        saved_theme = self._read_setting_str("theme", "light")
        set_theme(saved_theme)
        self.setStyleSheet(f"background-color: {C['bg']};")
        # -- 150 ms debounce: batch rapid selection changes before analysis --
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._run_pending_update)
        # -- file-system watcher: auto-reload when inventory JSON changes --
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        # Small delay so editors that do delete-then-write don't re-trigger
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(600)
        self._reload_timer.timeout.connect(self._do_auto_reload)
        self._build_ui()
        # Always watch the project's ``inventories/`` dir so newly-saved
        # inventories (from the Builder, or from external edits) appear
        # in the dropdown without restarting the app.
        inventories_dir = self._get_inventories_dir()
        if (
            os.path.isdir(inventories_dir)
            and inventories_dir not in self._watcher.directories()
        ):
            self._watcher.addPath(inventories_dir)
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        app.installEventFilter(self)
        # Initial mode is already SEG_TO_FEAT (set above), so _set_mode
        # would no-op; call _apply_mode_phases directly to wire up the
        # freshly-built chrome.
        self._apply_mode_phases()
        self._restore_settings(startup_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    # ---- toolbar button style (also used by _build_toolbar's factory) ----
    @staticmethod
    def _nav_btn_style() -> str:
        return f"""
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
        """

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

    def _build_toolbar(self) -> None:
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
        # Inventory dropdown
        self.inventory_combo = QComboBox()
        self.inventory_combo.setFont(QFont("Noto Sans", 10))
        self.inventory_combo.setFixedHeight(32)
        self.inventory_combo.setMinimumWidth(220)
        self.inventory_combo.setStyleSheet(f"""
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
        self._populate_inventory_dropdown()
        self.inventory_combo.activated.connect(self._on_inventory_selected)
        toolbar.addWidget(self.inventory_combo)
        # Nav buttons share the same height/font/style.
        nav_style = self._nav_btn_style()

        def add_nav(label: str, slot) -> QPushButton:
            btn = QPushButton(label)
            btn.setFont(QFont("Noto Sans", 10))
            btn.setFixedHeight(32)
            btn.setStyleSheet(nav_style)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
            return btn

        add_nav("Browse\u2026", self._browse_inventory)
        add_nav("Builder", self._open_builder)
        # Push the theme toggle to the far right of the toolbar so it
        # doesn't crowd the primary actions but stays visible.
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)
        # Toggle shows the OPPOSITE of the active theme; i.e. what
        # clicking will switch you to. Sun = "switch to light",
        # moon = "switch to dark".
        is_dark_now = get_theme_name() == "dark"
        self._theme_btn = QPushButton("\u263c" if is_dark_now else "\u263e")
        self._theme_btn.setFont(QFont("Noto Sans", 12))
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setToolTip(
            "Switch to light mode" if is_dark_now else "Switch to dark mode"
        )
        self._theme_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C["text_dim"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                color: {C["accent"]};
                border: 1.5px solid {C["accent"]};
            }}
        """)
        self._theme_btn.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self._theme_btn)

    def _build_central(self) -> None:
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
        # The segment panel sticks to the natural width of its content
        # (consonant grid + vowel chart). The feature panel hugs the
        # vowels' right edge and absorbs any extra horizontal room as
        # the window grows. Inverting these stretch factors used to
        # leave dead space after the vowels inside the segment panel.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Analysis panel below the split panes.
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

    def _build_status_bar(self) -> None:
        self.status = _BrandedStatusBar()
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
        self.clear_seg_btn.setStyleSheet(_clear_btn_style())
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
            "QScrollArea { background: transparent; }" + scrollbar_style()
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
        # stretch=0 on both: consonants and vowels sit at their natural
        # widths next to each other (separated only by the layout's
        # 12 px spacing). Any leftover horizontal room is absorbed by
        # the *outer* splitter (feat_panel has the splitter stretch),
        # not by inflating the gap inside the segment panel.
        seg_content_layout.addWidget(left_wrap, stretch=0)
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
        self.clear_feat_btn.setStyleSheet(_clear_btn_style())
        self.clear_feat_btn.clicked.connect(self._clear_features)
        header.addWidget(self._feat_title)
        header.addStretch()
        header.addWidget(self.clear_feat_btn)
        vlay.addLayout(header)
        self._feat_scroll = QScrollArea()
        self._feat_scroll.setWidgetResizable(True)
        self._feat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feat_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + scrollbar_style()
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

    def _clamp_size_to_screen(
        self,
        w: int,
        h: int,
        deco_w: int | None = None,
        deco_h: int | None = None,
    ) -> tuple[int, int]:
        """Clamp ``(w, h)`` to the target screen's available area.

        ``deco_w`` / ``deco_h`` are the WM decoration size (title bar +
        borders). When known; i.e. once the window has been shown and
        decorated; they let us size the widget so the *frame* fits
        exactly inside ``availableGeometry``. When unknown (pre-show)
        we fall back to a 40-pixel heuristic margin.
        """
        screen = self._target_screen()
        if screen is None:
            return w, h
        avail = screen.availableGeometry()
        if deco_w is not None and deco_h is not None:
            max_w = max(640, avail.width() - deco_w)
            max_h = max(480, avail.height() - deco_h)
        else:
            max_w = max(640, avail.width() - 40)
            max_h = max(480, avail.height() - 40)
        return min(w, max_w), min(h, max_h)

    def _ensure_visible_on_screen(self) -> None:
        """
        Run after the first show via QTimer so the WM has decorated the window.
        Ensures the window is on the primary screen.  If the user had a saved
        position that is still on *some* screen, we leave it alone; otherwise
        we center on the primary screen.

        Note: ``raise_`` and ``activateWindow`` are only called when we
        actually move the window. On the happy path (window already on
        a sane screen) they cause a visible title-bar focus blink and a
        brief restack on some Linux WMs; and they're redundant since
        the WM gives the only freshly-shown window focus by default.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        screen = self._target_screen()
        if screen is None:
            return
        frame = self.frameGeometry()
        primary_geo = screen.geometry()
        # If the window is already mostly on the primary screen, leave it
        # alone; no raise/activate, no flicker.
        if (
            primary_geo.intersects(frame)
            and frame.width() >= 300
            and frame.height() >= 200
        ):
            return
        # If the window is on *some* other screen and has a saved position,
        # leave it there; the user intentionally placed it.
        if self._read_setting("window_pos") is not None:
            on_any = any(s.geometry().intersects(frame) for s in app.screens())
            if on_any and frame.width() >= 300 and frame.height() >= 200:
                return
        # Off-screen recovery: center on the primary screen and bring the
        # window forward so the user can find it.
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

    def _read_setting(self, key: str, default=None):
        """Read a QSettings key, returning ``default`` if the stored value
        can't be deserialized.

        Older builds wrote pickled Python objects (e.g. enum members) under
        ``mode``; renaming the package invalidates those pickles and
        ``QSettings.value`` raises ``SystemError``. Catching here lets a
        fresh default replace the bad blob on the next ``setValue``.
        """
        try:
            value = self._settings.value(key, default)
        except (SystemError, ModuleNotFoundError, TypeError):
            self._settings.remove(key)
            return default
        return value

    def _read_setting_str(self, key: str, default: str) -> str:
        value = self._read_setting(key, default)
        return value if isinstance(value, str) else default

    def _restore_settings(self, startup_path: str | None) -> None:
        """Restore window size/position, mode, and last inventory on launch."""
        # Drop the old binary geometry blob; it encodes absolute positions that
        # can place the window off-screen after a display config change.
        self._settings.remove("geometry")
        size = self._read_setting("window_size")
        pos = self._read_setting("window_pos")
        self._has_saved_size = size is not None
        screen = self._target_screen()
        if size is not None:
            # Saved size may come from a larger display than the current
            # one; clamp before applying so the window can't overflow.
            self.resize(
                *self._clamp_size_to_screen(size.width(), size.height())
            )
        else:
            # Reasonable pre-load default; _fit_to_content will refine after loading.
            self.resize(*self._clamp_size_to_screen(1200, 900))
        if pos is not None:
            self.move(pos)
        elif screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        # Determine which inventory to open
        path = startup_path or self._read_setting("last_inventory")
        if path and isinstance(path, str) and os.path.isfile(path):
            idx = self.inventory_combo.findData(path)
            if idx >= 0:
                self.inventory_combo.setCurrentIndex(idx)
            self._load_path(path)
        # Restore mode after loading (overrides _load_path's default mode).
        # Stored as a plain string so the value survives module renames and
        # other refactors that would otherwise invalidate a pickled enum.
        saved_mode = self._read_setting_str("mode", Mode.SEG_TO_FEAT.value)
        if saved_mode in (Mode.SEG_TO_FEAT.value, Mode.FEAT_TO_SEG.value):
            self._set_mode(Mode(saved_mode))

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
        self._settings.setValue("mode", self._mode.value)
        if self._current_path:
            self._settings.setValue("last_inventory", self._current_path)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Inventory loading
    # ------------------------------------------------------------------
    def _get_inventories_dir(self) -> str:
        """Return the absolute path to the project's ``inventories/`` directory.

        Resolves relative to this file: ``src/phonology_features/gui/`` is
        three levels below the repo root, so we walk up three.
        """
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "inventories"
            )
        )

    def _populate_inventory_dropdown(self) -> None:
        """Scan ``inventories/`` and fill the dropdown.

        Preserves the current selection if the previously-selected path
        is still present after the rescan \u2014 this matters when the
        Builder saves a new inventory and the directory watcher
        triggers a refresh; we don't want to drop whatever the user
        had loaded out from under them. ``blockSignals`` keeps the
        clear/repopulate from emitting a spurious ``activated``.
        """
        inventories_dir = self._get_inventories_dir()
        previous_path = self.inventory_combo.currentData()
        self.inventory_combo.blockSignals(True)
        try:
            self.inventory_combo.clear()
            self.inventory_combo.addItem(
                "Select inventory\u2026", userData=None
            )
            # Disable the placeholder row so it cannot be picked.
            # QStandardItemModel is the default; the guard is defensive
            # against style plugins that substitute a different model type.
            # If it fails, _on_inventory_selected's `if path:` guard still
            # prevents any action.
            model = self.inventory_combo.model()
            if isinstance(model, QStandardItemModel):
                item = model.item(0)
                if item is not None:
                    item.setEnabled(False)
            if os.path.isdir(inventories_dir):
                for fname in sorted(os.listdir(inventories_dir)):
                    if fname.endswith(".json"):
                        path = os.path.join(inventories_dir, fname)
                        pretty = fname[:-5].replace("_", " ").title()
                        self.inventory_combo.addItem(pretty, userData=path)
            if previous_path:
                idx = self.inventory_combo.findData(previous_path)
                if idx >= 0:
                    self.inventory_combo.setCurrentIndex(idx)
                else:
                    self.inventory_combo.setCurrentIndex(0)
            else:
                self.inventory_combo.setCurrentIndex(0)
        finally:
            self.inventory_combo.blockSignals(False)

    def _on_inventory_selected(self, index: int):
        """Load the inventory chosen from the dropdown."""
        path = self.inventory_combo.itemData(index)
        if path:
            self._load_path(path)

    def _browse_inventory(self) -> None:
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
        idx = self.inventory_combo.findData(path)
        if idx < 0:
            pretty = os.path.splitext(os.path.basename(path))[0]
            pretty = pretty.replace("_", " ").title()
            self.inventory_combo.addItem(pretty, userData=path)
            idx = self.inventory_combo.count() - 1
        self.inventory_combo.setCurrentIndex(idx)
        self._load_path(path)

    def _toggle_theme(self) -> None:
        """Switch between light and dark theme; live, no restart.

        Mutates the active palette in place and rebuilds the central
        widget + toolbar so all freshly-constructed widgets pick up
        the new colors. Pooled SegmentButtons / FeatureRows are
        discarded (their styles were baked against the old palette)
        and recreated on the inventory reload.
        """
        new_theme = "dark" if get_theme_name() == "light" else "light"
        set_theme(new_theme)
        self._settings.setValue("theme", new_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Live theme swap with widget pools and engine preserved.

        Re-styles every pooled SegmentButton and FeatureRow in place
        (cheap; uses the per-class theme cache so the f-string work
        runs once per theme), tears down only the chrome (toolbar +
        central widget), rebuilds it, then re-parents the pool widgets
        to the new chrome via the populate helpers. The engine and
        cached inventory data are NOT reloaded; there's no JSON
        re-parse and no validation pass on a theme change.

        Window position and size are explicitly preserved so the
        toggle never visually moves the window: a tear-down + rebuild
        otherwise lets the WM re-place us, and ``_fit_to_content``
        re-centers on a recomputed frame which can drift a few px due
        to layout-time measurement differences.

        Mode and current inventory are preserved; per-mode selections
        are reset (acceptable for an explicit theme-change action).
        """
        saved_mode = self._mode
        saved_pos = self.pos()
        saved_size = self.size()
        # Capture splitter sizes too; _build_ui re-creates the
        # splitters with default sizes (500/400 + 700/220), so without
        # this the panes visibly jump on every theme toggle.
        saved_hsplit = (
            list(self._hsplit.sizes()) if hasattr(self, "_hsplit") else None
        )
        saved_vsplit = (
            list(self._vsplit.sizes()) if hasattr(self, "_vsplit") else None
        )
        # Suspend paint events for the entire tear-down + rebuild. Without
        # this the user sees a sequence of intermediate frames: empty
        # central widget after setCentralWidget, missing toolbar after
        # removeToolBar, missing status bar, then unstyled rebuilt chrome,
        # then populated chrome. Wrapping the whole thing means Qt paints
        # exactly once, after restore_geometry, with the final state.
        with self._batched_updates():
            # Re-style pooled widgets and detach them so the upcoming
            # central-widget destruction doesn't take them with it.
            for btn in self._seg_button_pool.values():
                btn.apply_theme()
                btn.setParent(None)
            for row in self._feat_row_pool.values():
                row.apply_theme()
                row.setParent(None)
            # Cards live as children of the old central widget; drop our
            # references so _init_feature_pool rebuilds them (it sees the
            # populated row pool and skips re-creating rows).
            self._feat_cards.clear()
            self._other_card = None
            self._feat_rows = {}
            # Tear down central + toolbars + status bar; the QMainWindow
            # itself stays so window pos/size and any child windows
            # (Builder) are unaffected. Each of these would otherwise
            # leak a chrome subtree per toggle (~90 widgets), and Qt
            # would have to walk all of them on every subsequent
            # re-style; that was the linear slowdown.
            self.setCentralWidget(QWidget())
            for tb in self.findChildren(QToolBar):
                self.removeToolBar(tb)
                tb.deleteLater()
            # setStatusBar transfers ownership of the new bar but does NOT
            # delete the old one; same accumulator pattern.
            old_status = self.statusBar()
            self.setStatusBar(QStatusBar())
            if old_status is not None:
                old_status.deleteLater()
            # Drain DeferredDelete events now so the orphan trees are
            # gone before we rebuild; otherwise findChildren and the
            # style engine still see them on the next pass.
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            self.setStyleSheet(f"background-color: {C['bg']};")
            # Rebuild chrome; every f-string stylesheet inside _build_ui
            # re-evaluates against the active palette.
            self._build_ui()
            # _set_mode would bail (mode unchanged); apply chrome
            # directly to wire up the freshly-built widgets.
            if saved_mode != self._mode:
                self._set_mode(saved_mode)
            else:
                self._apply_mode_phases()
            # Re-place pooled widgets in the new chrome WITHOUT going
            # through _load_path (no engine reload, no JSON parse, no
            # validator). The cached engine data is unchanged; we only
            # need the populate helpers to wire pool widgets to the
            # freshly-built panels.
            if self.engine is not None:
                self._saved_seg_state = []
                self._saved_feat_state = {}
                self._populate_segments()
                self._populate_features()
                self._apply_mode_to_new_widgets()
                self.analysis.clear()
            # Restore geometry while paint is still suspended so the
            # window doesn't flash at the default splitter ratios before
            # snapping back to the user's sizes.
            self.resize(saved_size)
            self.move(saved_pos)
            if saved_hsplit and len(saved_hsplit) == self._hsplit.count():
                self._hsplit.setSizes(saved_hsplit)
            if saved_vsplit and len(saved_vsplit) == self._vsplit.count():
                self._vsplit.setSizes(saved_vsplit)
        # Deferred geometry pass: after one event-loop tick any singleShot
        # resize that _fit_to_content queued (via the populate path) has
        # fired. Re-apply the saved sizes to win against it and silence
        # the late jiggle.
        if self.isVisible():
            QTimer.singleShot(
                0,
                lambda: self._restore_theme_geometry(
                    saved_pos, saved_size, saved_hsplit, saved_vsplit
                ),
            )

    def _restore_theme_geometry(
        self,
        pos,
        size,
        hsplit: list[int] | None,
        vsplit: list[int] | None,
    ) -> None:
        """Re-apply geometry after a deferred ``_fit_to_content`` tick.

        Pulled out so the closure capture is explicit and the lambda in
        ``_apply_theme`` stays a one-liner. Same paint-suspended pattern
        as the inline pass above.
        """
        with self._batched_updates():
            self.resize(size)
            self.move(pos)
            if hsplit and len(hsplit) == self._hsplit.count():
                self._hsplit.setSizes(hsplit)
            if vsplit and len(vsplit) == self._vsplit.count():
                self._vsplit.setSizes(vsplit)

    def _open_builder(self) -> None:
        if self._builder is not None and self._builder.isVisible():
            self._builder.raise_()
            self._builder.activateWindow()
            return
        from phonology_features.gui.builder import InventoryBuilder

        # Default behavior: if the main window has an inventory loaded,
        # the builder opens editing it directly; no intermediate dialog.
        # The builder's own "New" toolbar button is the way to start
        # from scratch instead.
        if self._current_path:
            self._builder = InventoryBuilder(
                parent=self, load_path=self._current_path
            )
            self._builder.setWindowFlag(Qt.WindowType.Window)
            self._builder.show()
            return
        # Nothing loaded; show the setup dialog so the user can pick
        # what to build. Cancel here means no builder window appears.
        builder = InventoryBuilder(parent=self)
        builder.setWindowFlag(Qt.WindowType.Window)
        if not builder.show_setup_dialog():
            builder.deleteLater()
            return
        self._builder = builder
        self._builder.show()

    def _load_path(self, path: str):
        """Core loading logic shared by dropdown, browse, and auto-reload.

        Each phase has its own helper so failures short-circuit cleanly
        and the responsibilities (parse / validate / install / register /
        populate) are obvious.
        """
        path = os.path.abspath(path)
        data = self._parse_and_validate(path)
        if data is None:
            return
        if not self._install_engine(path, data):
            return
        self._register_loaded_path(path)
        self._populate_after_load()

    def _parse_and_validate(self, path: str) -> dict | None:
        """Read the JSON file and run the shared-with-engine validator.

        Returns the parsed dict on success, or None after surfacing a
        human-readable error in the status bar / analysis panel.
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self.status.showMessage(
                f"Cannot load {os.path.basename(path)}: file not found"
            )
            return None
        except OSError as e:
            self.status.showMessage(
                f"Cannot load {os.path.basename(path)}: {e}"
            )
            return None
        except json.JSONDecodeError as e:
            self.status.showMessage(
                f"Cannot load {os.path.basename(path)}: invalid JSON "
                f"({e.msg} on line {e.lineno})"
            )
            return None
        errors, warnings = validate_inventory_data(data)
        if errors:
            self.status.showMessage(
                f"Cannot load {os.path.basename(path)}: {errors[0]}"
            )
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
            return None
        for w in warnings:
            self.status.showMessage(f"Warning: {w}")
        return data

    def _install_engine(self, path: str, data: dict) -> bool:
        """Build a fresh FeatureEngine for ``data`` and adopt it.

        Returns True on success. ``load_inventory_data`` raises
        ``ValueError`` for shapes the data-validator didn't catch
        (defensive) and the engine itself can raise ``KeyError`` on
        missing keys; surface both as a status message instead of
        crashing the GUI.
        """
        try:
            engine = FeatureEngine()
            engine.load_inventory_data(data)
        except (ValueError, KeyError) as e:
            self.status.showMessage(
                f"Cannot load {os.path.basename(path)}: {e}"
            )
            return False
        self.engine = engine
        self._cached_groups = None
        self._cached_norm_feats = None
        name = engine.metadata.get("name", os.path.basename(path))
        self.status.showMessage(
            f"{name}: "
            f"{len(engine.segments)} segments, "
            f"{len(engine.features)} features."
        )
        return True

    def _register_loaded_path(self, path: str) -> None:
        """Wire watcher + dropdown + settings for a freshly-loaded path."""
        # Update file-system watcher (file + containing directory).
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
        # Sync the dropdown to reflect the loaded inventory.
        idx = self.inventory_combo.findData(path)
        if idx >= 0:
            self.inventory_combo.setCurrentIndex(idx)
        # Persist for next launch.
        self._settings.setValue("last_inventory", path)

    def _populate_after_load(self) -> None:
        """Rebuild segment + feature widgets for the freshly-loaded engine.

        Startup runs ``_rebalance_vsplit`` synchronously so the first
        paint is already at the right size. Runtime swaps defer one
        event-loop tick so pending paints drain before we resize again.
        """
        self._saved_seg_state = []
        self._saved_feat_state = {}
        with self._batched_updates():
            self._populate_segments()
            self._populate_features()
            self._apply_mode_to_new_widgets()
            self.analysis.clear()
        if self.isVisible():
            QTimer.singleShot(0, self._rebalance_vsplit)
        else:
            self._rebalance_vsplit()

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

    def _on_directory_changed(self, directory: str):
        """Called when a watched directory changes (file created/renamed/deleted)."""
        # When the project's inventories/ directory changes; e.g. the Builder
        # just saved a new inventory; rescan and refresh the dropdown
        # so the new file shows up without restarting the app.
        if os.path.normpath(directory) == self._get_inventories_dir():
            self._populate_inventory_dropdown()
        # Existing: if the target file reappeared but fell out of the
        # file watcher (delete-then-write editors), re-arm it.
        if not self._current_path:
            return
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
            from phonology_features.engine.segment_grouper import (
                _normalize_feats,
            )

            self._cached_groups = group_segments(self.engine.segments)
            self._cached_norm_feats = {
                seg: _normalize_feats(self.engine.segments[seg])
                for seg in self.engine.segments
            }
        groups = dict(self._cached_groups)  # shallow copy; pop mutates
        norm_feats = self._cached_norm_feats
        vowel_segs = groups.pop("Vowels", [])
        consonant_buttons: dict = {}
        for segs in groups.values():
            for seg in segs:
                consonant_buttons[seg] = self._get_or_create_seg_button(seg)
        self.seg_grid_widget.set_groups(groups, consonant_buttons)
        vowel_buttons: dict = {}
        if vowel_segs:
            for seg in vowel_segs:
                vowel_buttons[seg] = self._get_or_create_seg_button(seg)
            if norm_feats is not None:
                self.vowel_chart_widget.set_vowels(
                    vowel_segs, vowel_buttons, norm_feats
                )
                self.vowel_chart_widget.show()
        else:
            self.vowel_chart_widget.clear()
            self.vowel_chart_widget.hide()
        self._seg_buttons = {**consonant_buttons, **vowel_buttons}
        # Detach pool entries not used by the active inventory so they
        # don't linger in old layouts. They stay in the pool, ready for
        # reuse if a later inventory brings them back.
        active = set(self._seg_buttons)
        for sym, btn in self._seg_button_pool.items():
            if sym not in active and btn.parent() is not None:
                btn.setParent(None)
                btn.hide()

    def _get_or_create_seg_button(self, seg: str):
        """Return a SegmentButton for ``seg``, creating it on first use.

        Reused buttons are reset to the default visual state; the
        previous inventory may have left them checked or styled.
        """
        btn = self._seg_button_pool.get(seg)
        if btn is None:
            btn = SegmentButton(seg)
            btn.clicked.connect(
                lambda checked, s=seg: self._on_segment_clicked(s, checked)
            )
            self._seg_button_pool[seg] = btn
            return btn
        btn.setChecked(False)
        btn.set_state(SegmentState.DEFAULT)
        btn.setToolTip("")
        return btn

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

    def _init_feature_pool(self) -> None:
        """Pre-create FeatureRow widgets for all features in FEATURE_ORDER and
        build the static FEATURE_GROUPS cards. Column placement happens
        per-inventory in ``_redistribute_feature_cards`` because card heights
        depend on the *active* feature count, which varies per inventory
        (e.g. Hayes activates 1 of 4 features in Tongue-Root, Blevins 4 of 4).

        _feat_row_pool keeps a permanent reference to every row in the pool;
        _feat_rows below tracks which subset is active for the current
        inventory and is the dict external code reads from.
        """
        # Create any rows missing from the pool. After a theme swap the
        # pool is preserved (so we don't re-init 30+ widgets) but the
        # cards; which are children of the central widget; were torn
        # down. The cards-only rebuild path below handles that.
        for feat in FEATURE_ORDER:
            if feat not in self._feat_row_pool:
                row = FeatureRow(feat)
                row.value_changed.connect(self._on_feature_changed)
                self._feat_row_pool[feat] = row
        if self._feature_pool_initialized and self._feat_cards:
            return
        # Temporarily expose pool rows via _feat_rows so _build_feature_group
        # can find them while constructing cards.
        self._feat_rows = dict(self._feat_row_pool)
        for title, feats_list in FEATURE_GROUPS:
            card = self._build_feature_group(title, feats_list)
            if card is not None:
                # Hide and float; _redistribute_feature_cards will pick up
                # and place these into columns once we know the active set.
                card.hide()
                self._feat_cards.append((card, list(feats_list)))
        # Reset _feat_rows to the active-only contract; the next
        # _populate_features call will repopulate it for the loaded inventory.
        self._feat_rows = {}
        for row in self._feat_row_pool.values():
            row.setVisible(False)
        self._feature_pool_initialized = True

    def _populate_features(self) -> None:
        if self.engine is None:
            return
        active_feature_set: set = set()
        for seg_feats in self.engine.segments.values():
            for f, v in seg_feats.items():
                if v != "0":
                    active_feature_set.add(f)
        active_feature_set &= set(self.engine.features)
        self._init_feature_pool()
        self._selected_features.clear()
        # Rebuild _feat_rows from the active subset so external code keeps
        # seeing only "rows present in the current inventory."
        self._feat_rows = {}
        # Show/hide pool rows based on the active set; reset the visible ones.
        for feat, row in self._feat_row_pool.items():
            if feat in active_feature_set:
                row.setVisible(True)
                row.reset()
                self._feat_rows[feat] = row
            else:
                row.setVisible(False)
        # Build / tear down the dynamic "Other" card BEFORE redistribute
        # so it can be placed alongside the standard cards.
        unknown_active = sort_features(
            [f for f in active_feature_set if f not in set(FEATURE_ORDER)]
        )
        self._refresh_other_card(unknown_active)
        # Lay out cards across the two columns based on the inventory's
        # actual active feature counts (per-card visibility and ordering).
        self._redistribute_feature_cards(active_feature_set)

    def _refresh_other_card(self, unknown_active: list[str]) -> None:
        """Build/destroy the dynamic 'Other' card for inventory-specific
        features that don't appear in FEATURE_ORDER. Doesn't place it in a
        column; that happens in ``_redistribute_feature_cards`` so the
        Other card participates in the same balancing pass as the standard
        cards.
        """
        if self._other_card is not None:
            for feat in list(self._feat_rows.keys()):
                if feat not in self._feat_row_pool:
                    self._feat_rows.pop(feat).setParent(None)
            self._other_card.setParent(None)
            self._other_card.deleteLater()
            self._other_card = None
        if not unknown_active:
            return
        for feat in unknown_active:
            row = FeatureRow(feat)
            row.value_changed.connect(self._on_feature_changed)
            self._feat_rows[feat] = row
        self._other_card = self._build_feature_group("Other", unknown_active)
        if self._other_card is not None:
            self._other_card.hide()  # placed by _redistribute_feature_cards

    # -- Layout policy for feature-group cards ----------------------------
    #
    # "Soft pins" for the canonical groups (placed only if they have any
    # active features for the current inventory):
    #   - Major Class top of the LEFT column
    #   - Place under Major Class in the LEFT column
    #   - Manner top of the RIGHT column
    #
    # Everything else (other FEATURE_GROUPS entries plus the dynamic
    # "Other" card if it exists) is sorted by active feature count
    # descending, then dropped into whichever column is shorter at the
    # moment of placement (LPT scheduling). This packs the columns as
    # close to equal height as the active counts permit, which minimises
    # the window height the GUI needs to fit them.
    _LEFT_PINS: tuple[str, ...] = ("Major Class", "Place")
    _RIGHT_PINS: tuple[str, ...] = ("Manner",)
    # Each card in the column adds a roughly fixed-height header + padding
    # on top of its rows (~32 px in practice). When balancing column heights
    # we add this overhead per card so that a column with many small cards
    # doesn't get under-counted relative to one with a few big cards.
    # Expressed in row-equivalents.
    _CARD_OVERHEAD: int = 1

    def _redistribute_feature_cards(self, active: set[str]) -> None:
        """Place feature-group cards into left/right columns based on the
        current inventory's active feature counts. Re-runs on every
        inventory load because the same card has different visible heights
        across inventories (e.g. Tongue-Root has 1 active feature in Hayes
        but 4 in Blevins).

        Heuristic: Major Class top of the left column, Place under it,
        Manner top of the right column (any of these soft pins are only
        applied if the card has at least one active feature). Then every
        remaining card is sorted by active feature count descending and
        dropped into whichever column is shorter at the moment of
        placement (LPT scheduling). Column "height" is measured in
        row-equivalents and includes ``_CARD_OVERHEAD`` per card so that
        per-card chrome (headers, padding) is reflected in the balance.
        """
        self._take_cards_out_of_columns()
        # Build (title -> (card, cost)) for every card we know about.
        # cost = active row count + per-card overhead.
        info: dict[str, tuple[QFrame, int]] = {}
        for card, feats in self._feat_cards:
            n_active = sum(1 for f in feats if f in active)
            title = self._card_title(card)
            if title:
                info[title] = (
                    card,
                    n_active + self._CARD_OVERHEAD if n_active > 0 else 0,
                )
                card.setVisible(n_active > 0)
        if self._other_card is not None:
            other_title = self._card_title(self._other_card) or "Other"
            n_active = sum(1 for f in active if f not in self._feat_row_pool)
            info[other_title] = (
                self._other_card,
                n_active + self._CARD_OVERHEAD if n_active > 0 else 0,
            )
            self._other_card.setVisible(n_active > 0)
        pinned: set[str] = set(self._LEFT_PINS) | set(self._RIGHT_PINS)
        left_height = 0
        right_height = 0
        # Soft pins: only added if the card has any active rows.
        for title in self._LEFT_PINS:
            entry = info.get(title)
            if entry is not None and entry[1] > 0:
                self._feat_left_layout.addWidget(entry[0])
                left_height += entry[1]
        for title in self._RIGHT_PINS:
            entry = info.get(title)
            if entry is not None and entry[1] > 0:
                self._feat_right_layout.addWidget(entry[0])
                right_height += entry[1]
        # Everything else: sort by cost desc, distribute LPT.
        unpinned_titles: list[str] = [
            t for t, _ in FEATURE_GROUPS if t not in pinned
        ]
        if self._other_card is not None:
            other_title = self._card_title(self._other_card) or "Other"
            if other_title not in pinned:
                unpinned_titles.append(other_title)
        remaining: list[tuple[QFrame, int]] = sorted(
            (info[t] for t in unpinned_titles if t in info and info[t][1] > 0),
            key=lambda pair: pair[1],
            reverse=True,
        )
        for card, cost in remaining:
            if left_height <= right_height:
                self._feat_left_layout.addWidget(card)
                left_height += cost
            else:
                self._feat_right_layout.addWidget(card)
                right_height += cost
        self._feat_left_layout.addStretch()
        self._feat_right_layout.addStretch()

    def _take_cards_out_of_columns(self) -> None:
        """Remove every item from both column layouts. Card widgets stay
        alive (we hold references in _feat_cards / _other_card); spacer
        items are released."""
        for layout in (self._feat_left_layout, self._feat_right_layout):
            while layout.count():
                layout.takeAt(0)

    @staticmethod
    def _card_title(card: QFrame) -> str:
        """Read the title text from a feature-group card. Cards are built
        by ``_build_feature_group``, which always puts a QLabel(title) as
        the card's first child widget."""
        layout = card.layout()
        if layout is None or layout.count() == 0:
            return ""
        item = layout.itemAt(0)
        if item is None:
            return ""
        first = item.widget()
        if first is not None and hasattr(first, "text"):
            return first.text()
        return ""

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
        # The seg panel sticks to exactly its natural content width so
        # the feature pane (with stretch=1 in the splitter) can hug the
        # vowels' right edge. No extra padding here; leftover room
        # belongs to the feature pane, not to dead space after the
        # vowels.
        seg_content = self._seg_scroll.widget()
        seg_content_w = seg_content.sizeHint().width() if seg_content else 400
        seg_chrome = 28 + 6  # panel margins (14*2) + scrollbar clearance
        seg_need_w = seg_content_w + seg_chrome
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
        # -- Size window + splitters to fit content --
        # Paint is suspended for the entire resize + splitter pass so the
        # window doesn't flash through "new size + old splitter ratio"
        # before the splitter setSizes lands. One paint at the end.
        screen = self._target_screen()
        with self._batched_updates():
            self._fit_window_to_size(
                screen, seg_need_w + feat_need_w + 1, total_need_h
            )
            self._apply_splitter_sizes(seg_need_w, feat_need_w, top_need_h)

    def _fit_window_to_size(self, screen, need_w: int, need_h: int) -> None:
        """Resize the window to fit ``(need_w, need_h)`` and keep the user's
        chosen corner.

        Behavior, in one sentence: anchor to wherever the title bar is
        right now, change the size, and only shift the window if doing
        so would put the title bar itself off the screen (the only
        scenario where the window would become unreachable).

        First load is the one exception; the saved-pos check (``_has_
        saved_size``) is False on a fresh launch, so we center on the
        target screen so the user sees something sensible. Every load
        after that anchors to ``self.pos()`` -- the live position,
        including any manual drag the user just did.
        """
        if screen is None:
            return
        avail = screen.availableGeometry()
        cur_w = self.width()
        cur_h = self.height()
        old_pos = self.pos()
        deco_w, deco_h, left_pad, top_pad = self._decoration_padding(old_pos)
        new_w, new_h = self._clamp_size_to_screen(
            need_w, need_h, deco_w, deco_h
        )
        # First-ever load: nothing to preserve, center on the screen so
        # the window doesn't flash at the WM-default top-left.
        if not self._has_saved_size:
            frame_x = avail.x() + (avail.width() - (new_w + deco_w)) // 2
            frame_y = avail.y() + (avail.height() - (new_h + deco_h)) // 2
            self.setGeometry(
                frame_x + left_pad, frame_y + top_pad, new_w, new_h
            )
            self._has_saved_size = True
            return
        # Same size as before: leave the position alone entirely.
        if new_w == cur_w and new_h == cur_h:
            return
        # Anchor to the current corner. Only shift if doing nothing
        # would push the *title bar* (frame.x()/y()) off the screen --
        # that's the unreachable case the user actually cares about.
        # Partial overflow on the right or bottom is left alone so the
        # window stays where the user put it.
        new_x = old_pos.x()
        new_y = old_pos.y()
        frame_x = new_x - left_pad
        frame_y = new_y - top_pad
        if frame_x < avail.x():
            new_x = avail.x() + left_pad
        if frame_y < avail.y():
            new_y = avail.y() + top_pad
        # setGeometry applies resize + move atomically; separate
        # resize+move calls produce a visible intermediate frame on
        # some WMs where the window snaps to its old top-left at the
        # new size before move() lands.
        self.setGeometry(new_x, new_y, new_w, new_h)

    def _decoration_padding(self, old_pos) -> tuple[int, int, int, int]:
        """Return (deco_w, deco_h, left_pad, top_pad) from the current
        frame. Falls back to typical title-bar sizes when the WM reports
        zero (Wayland CSD, freshly-shown windows).
        """
        if not self.isVisible():
            return 0, 0, 0, 0
        old_frame = self.frameGeometry()
        deco_w_reported = max(0, old_frame.width() - self.width())
        deco_h_reported = max(0, old_frame.height() - self.height())
        if deco_h_reported == 0:
            deco_h, top_pad = _MIN_DECO_H, _MIN_DECO_H
        else:
            deco_h = deco_h_reported
            top_pad = max(0, old_pos.y() - old_frame.y())
        if deco_w_reported == 0:
            deco_w, left_pad = _MIN_DECO_W, 0
        else:
            deco_w = deco_w_reported
            left_pad = max(0, old_pos.x() - old_frame.x())
        return deco_w, deco_h, left_pad, top_pad

    def _apply_splitter_sizes(
        self, seg_need_w: int, feat_need_w: int, top_need_h: int
    ) -> None:
        """Size the seg pane to its content width and let the feature
        pane absorb the rest; rebalance the vertical splitter so the
        analysis panel keeps its minimum.
        """
        available = self._hsplit.width() or (seg_need_w + feat_need_w)
        feat_w = max(feat_need_w, available - seg_need_w)
        self._hsplit.setSizes([seg_need_w, feat_w])
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
        changed; only the newly created feature rows and buttons need updating.
        """
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        self.seg_grid_widget.set_headers_active(is_s2f)
        self.vowel_chart_widget.set_headers_active(is_s2f)
        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)
        self._clear_segments(silent=True)
        self._clear_features(silent=True)

    @contextmanager
    def _batched_updates(self):
        """Suspend Qt paint events for the duration. Used around any block
        that issues many setStyleSheet/set_state calls in sequence so the
        result paints once with the final state instead of flickering
        through intermediate frames. Cuts both wall-clock latency and
        visible blink during mode toggles + inventory loads.

        Depth-aware: nested ``with self._batched_updates()`` blocks share
        a single setUpdatesEnabled(False/True) pair across the outermost
        scope. Required because ``_apply_theme`` and ``_fit_to_content``
        both wrap themselves AND call helpers that also use this context
        manager; without depth tracking the inner exit would re-enable
        paint mid tear-down and a blank frame would leak through.
        """
        if self._batched_depth == 0:
            self.setUpdatesEnabled(False)
        self._batched_depth += 1
        try:
            yield
        finally:
            self._batched_depth -= 1
            if self._batched_depth == 0:
                self.setUpdatesEnabled(True)

    def _set_mode(self, mode: Mode | str) -> None:
        """Switch top-level UI mode. Pure orchestration; every step is in a
        named helper below so individual phases stay easy to inspect and diff.

        Accepts bare strings (from QSettings / tests) and coerces to Mode.
        Bails immediately when the requested mode equals the current one;
        callers that need to re-apply chrome (e.g. after a theme swap
        rebuilds the central widget) call ``_apply_mode_phases`` directly.
        """
        mode = Mode(mode)
        if mode == self._mode:
            return
        self._save_outgoing_mode_state()
        self._mode = mode
        self._apply_mode_phases()

    def _apply_mode_phases(self) -> None:
        """Run all mode-aware UI updates against the current ``self._mode``.

        Used as the body of ``_set_mode`` and called directly from
        ``_apply_theme`` to wire up freshly-built chrome without the
        no-op gate on _set_mode.
        """
        with self._batched_updates():
            self._apply_panel_chrome()
            self._apply_row_interactivity()
            self._restore_segment_selection()
            self._restore_feature_selection()
            self._refresh_analysis_for_mode()
            self._update_status_message()

    # -- _set_mode phases -------------------------------------------------
    #
    # Each phase reads self._mode directly. _save_outgoing_mode_state runs
    # BEFORE self._mode is updated (it captures the state of the mode being
    # left); every other phase runs after.
    def _save_outgoing_mode_state(self) -> None:
        """Snapshot the current mode's exact state and project it into the
        opposite mode's saved state. Called only when the mode is actually
        changing.
        """
        if self._mode == Mode.SEG_TO_FEAT:
            # Preserve exact seg selection so toggling back restores it.
            self._saved_seg_state = list(self._selected_segments)
            # Project into feat mode: shared (non-contradictory) features only.
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
            # Preserve exact feat query so toggling back restores it.
            self._saved_feat_state = dict(self._selected_features)
            # Project into seg mode: segments matched by current feature query.
            if self._selected_features and self.engine:
                self._saved_seg_state = list(
                    self.engine.find_segments(self._selected_features)
                )
            else:
                self._saved_seg_state = []

    def _apply_panel_chrome(self) -> None:
        """Update panel backgrounds, borders, titles, and clear-button
         styling to reflect which side of the UI is active.

         Only the outer ``seg_panel`` and ``feat_panel`` frames get their
         bg/border restyled. The inner viewports, scroll content, and
         grid widgets are set ``background: transparent`` at construction
        ; they show through to the parent frame's bg, so we don't need
         to restyle them per toggle. Skipping that cascade saved ~80 ms
         per mode toggle (each setStyleSheet on a parent invalidates
         every descendant's style; the seg side has 140+).
        """
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        seg_bg = C["panel"] if is_s2f else C["bg"]
        feat_bg = C["panel"] if not is_s2f else C["bg"]
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
            f"color: {C['text'] if is_s2f else C['text_dim']};"
            " letter-spacing: 1.5px;"
        )
        feat_color = C["text"] if not is_s2f else C["text_dim"]
        self._feat_title.setStyleSheet(
            f"color: {feat_color}; letter-spacing: 1.5px;"
        )
        self.seg_grid_widget.set_headers_active(is_s2f)
        self.vowel_chart_widget.set_headers_active(is_s2f)

    def _apply_row_interactivity(self) -> None:
        """Toggle each FeatureRow's interactivity to match the active mode."""
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)

    def _restore_segment_selection(self) -> None:
        """Single-pass: set each segment button to its final state directly.

        In seg-mode, segments listed in _saved_seg_state become "selected";
        all others become "default". In feat-mode this clears the visual
        selection; segment matched/unmatched styling is then applied by
        _refresh_analysis_for_mode below.
        """
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        restore_segs = set(self._saved_seg_state) if is_s2f else set()
        self._selected_segments.clear()
        for seg, btn in self._seg_buttons.items():
            if seg in restore_segs:
                self._selected_segments.append(seg)
                if btn._state != SegmentState.SELECTED:
                    btn.set_state(SegmentState.SELECTED)
                    btn.setChecked(True)
            elif btn._state != SegmentState.DEFAULT:
                btn.set_state(SegmentState.DEFAULT)
                btn.setChecked(False)

    def _restore_feature_selection(self) -> None:
        """Single-pass: set each feature row to its final state directly.

        This is the sole authority on per-row visual state during a mode
        switch; no later phase touches feature rows. Rows in restore_feats
        get restore_value (button checked + tinted); the rest get reset.
        """
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        restore_feats = self._saved_feat_state if not is_s2f else {}
        self._selected_features.clear()
        for feat, row in self._feat_rows.items():
            if feat in restore_feats:
                self._selected_features[feat] = restore_feats[feat]
                row.restore_value(restore_feats[feat])
            else:
                row.reset()

    def _refresh_analysis_for_mode(self) -> None:
        """Clear the analysis panel and re-run the active mode's analysis if
        there's something to analyze."""
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        self.analysis.clear()
        if is_s2f and self._selected_segments:
            self._update_seg_to_feat()
        elif not is_s2f and self._selected_features:
            self._update_feat_to_seg()

    def _update_status_message(self) -> None:
        """Show the per-mode helper text in the status bar."""
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        if not self.engine:
            self.status.showMessage(
                "Select an inventory from the dropdown to begin."
            )
        elif is_s2f:
            self.status.showMessage("Click a segment to inspect its features.")
        else:
            self.status.showMessage(
                "Toggle feature values (+/\u2212) to find matching segments."
            )

    def eventFilter(self, a0, a1):
        """Activate a panel on any mouse press anywhere inside it.

        This is installed on the QApplication, so EVERY Qt event in the
        process flows through here; paint, layout, mouse-move, focus, etc.
        Volume can hit 10k+ events per mode-toggle. Check the cheap event
        type first and bail; only do the isinstance + parent walk on the
        rare MouseButtonPress.
        """
        if a1 is None or a1.type() != _QEVENT_MOUSE_BUTTON_PRESS:
            return False
        if not isinstance(a0, QWidget):
            return False
        w = a0
        while w is not None:
            if w is self.seg_panel:
                if self._mode != Mode.SEG_TO_FEAT:
                    self._set_mode(Mode.SEG_TO_FEAT)
                break
            if w is self.feat_panel:
                if self._mode != Mode.FEAT_TO_SEG:
                    self._set_mode(Mode.FEAT_TO_SEG)
                break
            w = w.parent()
        return False

    # ------------------------------------------------------------------
    # Event handlers  (state changes are immediate; analysis is debounced)
    # ------------------------------------------------------------------
    def _on_segment_clicked(self, segment: str, checked: bool):
        if self._mode != Mode.SEG_TO_FEAT:
            # Prevent visual toggle in feat_to_seg mode
            self._seg_buttons[segment].setChecked(False)
            return
        btn = self._seg_buttons[segment]
        if checked:
            btn.set_state(SegmentState.SELECTED)
            if segment not in self._selected_segments:
                self._selected_segments.append(segment)
        else:
            btn.set_state(SegmentState.DEFAULT)
            if segment in self._selected_segments:
                self._selected_segments.remove(segment)
        self._debounce.start()

    def _on_feature_changed(self, feature: str, value: str):
        if self._mode != Mode.FEAT_TO_SEG:
            return
        if value:
            self._selected_features[feature] = value
        else:
            self._selected_features.pop(feature, None)
        self._debounce.start()

    def _run_pending_update(self) -> None:
        """Fired by the debounce timer; dispatches to the active mode."""
        with self._batched_updates():
            if self._mode == Mode.SEG_TO_FEAT:
                self._update_seg_to_feat()
            else:
                self._update_feat_to_seg()

    # ------------------------------------------------------------------
    # Seg -> Feat logic
    # ------------------------------------------------------------------
    def _update_seg_to_feat(self) -> None:
        segs = self._selected_segments
        if not segs or not self.engine:
            self._reset_feature_display()
            for btn in self._seg_buttons.values():
                btn.set_state(SegmentState.DEFAULT)
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
                    btn.set_state(SegmentState.DEFAULT)
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
                        SegmentState.SUGGESTED
                        if seg in suggested_set
                        else SegmentState.DEFAULT
                    )
            self.analysis.set_html(
                render_multi_segment(
                    self.engine, segs, common, contrastive, suggested
                )
            )

    # ------------------------------------------------------------------
    # Feat -> Seg logic
    # ------------------------------------------------------------------
    def _update_feat_to_seg(self) -> None:
        if not self.engine:
            return
        selected_feats = self._selected_features
        if not selected_feats:
            for btn in self._seg_buttons.values():
                btn.set_state(SegmentState.DEFAULT)
            self.analysis.clear()
            return
        matching = self.engine.find_segments(selected_feats)
        matching_set = set(matching)
        for seg, btn in self._seg_buttons.items():
            btn.set_state(
                SegmentState.MATCHED
                if seg in matching_set
                else SegmentState.UNMATCHED
            )
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
        """Clear seg-side state and any seg-derived feat display.

        Always resets _selected_segments and the seg buttons. Also resets the
        feat rows IFF we are in seg mode; there they mirror the segment
        selection via set_display(), so without this they'd show stale data.
        In feat mode the feat rows hold the user's actual query, so they
        are left alone (clearing segments shouldn't wipe the feat query).
        """
        self._selected_segments.clear()
        for btn in self._seg_buttons.values():
            if btn._state != SegmentState.DEFAULT:
                btn.set_state(SegmentState.DEFAULT)
                btn.setChecked(False)
        if self._mode == Mode.SEG_TO_FEAT:
            for row in self._feat_rows.values():
                row.reset()
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()

    def _clear_features(self, silent=False):
        """Clear feat-side state and any feat-derived seg display.

        Always resets _selected_features and the feat rows. Also resets the
        seg buttons IFF we are in feat mode; there they mirror the feature
        query via matched/unmatched. In seg mode the seg buttons hold the
        user's actual selection, so they are left alone (clearing features
        shouldn't wipe the segment selection).
        """
        self._selected_features.clear()
        for row in self._feat_rows.values():
            if row._current_value:
                row.reset()
        if self._mode == Mode.FEAT_TO_SEG:
            for btn in self._seg_buttons.values():
                if btn._state != SegmentState.DEFAULT:
                    btn.set_state(SegmentState.DEFAULT)
                    btn.setChecked(False)
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()
