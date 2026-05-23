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
from phonology_features.gui.palette import (
    C,
    detect_system_theme,
    get_theme_name,
    set_theme,
)
from phonology_features.gui.vowel_chart import VOWEL_LABEL_W, VowelChartWidget
from phonology_features.gui.widgets import (
    AnalysisPanel,
    FeatureRow,
    SegmentButton,
    SegmentGridWidget,
    SegmentState,
)
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
    QToolTip,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from phonology_features.gui.builder import InventoryBuilder


def _clear_btn_style() -> str:
    """Stylesheet for the per-panel Clear buttons. Function-not-constant
    so it re-evaluates against the active palette after a theme swap.
    """
    return (
        f"QPushButton {{"
        f" color: {C['text']}; background: transparent;"
        f" border: 1px solid {C['border']};"
        f" border-radius: 5px; padding: 0 10px;"
        f" }}"
        f" QPushButton:hover {{ color: {C['text']};"
        f" background: {C['bg']}; }}"
    )


# Floor for WM decoration when the WM reports zero (Wayland CSD, some
# X11 themes). Keeps the window frame inside the screen on inventory
# swaps even when Qt thinks frame == widget.
_MIN_DECO_W = 8
_MIN_DECO_H = 32

# Cached enum member. eventFilter runs on every Qt event (10k+ per user
# action); binding the comparison target to a name avoids resolving
# QEvent.Type.MouseButtonPress through the enum machinery each call.
_QEVENT_MOUSE_BUTTON_PRESS = QEvent.Type.MouseButtonPress


class Mode(StrEnum):
    """Top-level UI mode. StrEnum so members compare equal to their
    string values for QSettings round-tripping.
    """

    SEG_TO_FEAT = "seg_to_feat"
    FEAT_TO_SEG = "feat_to_seg"


class _BrandedStatusBar(QStatusBar):
    """Status bar with a 'Language Doodad' brand pinned at the right.

    QStatusBar.showMessage() hides addWidget() items while a message is
    shown, which would blink the brand on every status update. This
    subclass routes messages to a managed QLabel on the left so both
    message and brand stay visible.
    """

    _FONT = QFont("Noto Sans", 9)
    # 22 px matches the toolbar baseline; sized so italic ascenders /
    # descenders don't push the bar taller than non-italic text would.
    _BAR_HEIGHT = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(self._BAR_HEIGHT)
        self._message_label = QLabel("", self)
        self._message_label.setFont(self._FONT)
        self._message_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._brand = QLabel("Language Doodad", self)
        self._brand.setFont(self._FONT)
        self._brand.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.addWidget(self._message_label, 1)
        self.addPermanentWidget(self._brand, 0)
        self.apply_theme()

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        self.setStyleSheet(
            f"background: {C['panel']};"
            f" border-top: 1px solid {C['border']};"
        )
        self._message_label.setStyleSheet(f"color: {C['text']};")
        self._brand.setStyleSheet(
            f"color: {C['text_dim']}; font-style: italic; padding: 0 4px;"
        )

    def showMessage(self, text: str, timeout: int = 0) -> None:  # type: ignore[override]
        """Override that doesn't call super() (which would hide
        left-section widgets). ``timeout`` is ignored; the app never
        uses auto-clear.
        """
        self._message_label.setText(text)

    def clearMessage(self) -> None:  # type: ignore[override]
        self._message_label.setText("")

    def currentMessage(self) -> str:  # type: ignore[override]
        return self._message_label.text()


class MainWindow(QMainWindow):
    def __init__(self, startup_path: str | None = None):
        super().__init__()
        self.engine: FeatureEngine | None = None
        self._mode: Mode = Mode.SEG_TO_FEAT
        # segment -> SegmentButton for the active inventory
        self._seg_buttons: dict = {}
        # Cross-inventory pool keyed by segment symbol. Reused across
        # loads since /p t k m n s/ etc. are nearly universal; avoids
        # the QPushButton + setStyleSheet cost on every swap.
        self._seg_button_pool: dict[str, SegmentButton] = {}
        self._feat_rows: dict = {}  # feature -> FeatureRow, active subset
        self._selected_segments: list = []
        self._selected_features: dict = {}  # feature -> '+'/'-'
        # State of each mode at the moment we leave it, projected into
        # the other mode as a pre-fill on switch.
        self._saved_seg_state: list = []
        self._saved_feat_state: dict = {}
        self._current_path: str | None = None
        self._did_first_show = False
        # Per-engine cache for segment grouping. Cleared on engine reload.
        self._cached_groups: dict | None = None
        self._cached_norm_feats: dict | None = None
        self._builder: InventoryBuilder | None = None
        # Pool of every FeatureRow ever created (FEATURE_ORDER plus any
        # inventory-specific Other-card extras). ``_feat_rows`` above is
        # the active subset; external code reads from _feat_rows.
        self._feat_row_pool: dict[str, FeatureRow] = {}
        self._feat_cards: list[tuple[QFrame, list[str]]] = []
        self._other_card: QFrame | None = None
        self._feature_pool_initialized: bool = False
        # Depth counter so nested ``_batched_updates`` scopes share one
        # setUpdatesEnabled(False/True) pair.
        self._batched_depth: int = 0
        self.setWindowTitle("Feature visualizer")
        self.setMinimumSize(640, 480)
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Read + apply the theme BEFORE the QMainWindow background so the
        # window's own bg uses the right palette. First-launch default
        # follows the OS color scheme; subsequent launches honor the
        # user's last manual toggle.
        saved_theme = self._read_setting_str("theme", detect_system_theme())
        set_theme(saved_theme)
        self.setStyleSheet(f"background-color: {C['bg']};")
        # 150 ms debounce for selection-change analysis.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._run_pending_update)
        # File-system watcher for live inventory reloads.
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        # 600 ms delay so editors that delete-then-write don't re-trigger.
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(600)
        self._reload_timer.timeout.connect(self._do_auto_reload)
        self._build_ui()
        # Watch ``inventories/`` so newly-saved inventories (from the
        # Builder or external edits) appear in the dropdown live.
        inventories_dir = self._get_inventories_dir()
        if (
            os.path.isdir(inventories_dir)
            and inventories_dir not in self._watcher.directories()
        ):
            self._watcher.addPath(inventories_dir)
        # Initial mode is already SEG_TO_FEAT, so _set_mode would no-op.
        # Apply chrome directly to wire up the freshly-built widgets.
        self._apply_mode_phases()
        self._restore_settings(startup_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    @staticmethod
    def _nav_btn_style() -> str:
        """Toolbar nav-button stylesheet, evaluated against the active
        palette. Shared between construction and theme re-styling.
        """
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
        """Build the top toolbar. Every widget gets a parent at
        construction; a parent-less QToolBar would take the Qt.Tool
        window flag and flash as a transient floating window on Wayland.
        """
        self._toolbar = QToolBar(self)
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)
        toolbar = self._toolbar
        self._nav_buttons: list[QPushButton] = []
        self.inventory_combo = QComboBox(toolbar)
        self.inventory_combo.setFont(QFont("Noto Sans", 10))
        self.inventory_combo.setFixedHeight(32)
        self.inventory_combo.setMinimumWidth(220)
        self._populate_inventory_dropdown()
        self.inventory_combo.activated.connect(self._on_inventory_selected)
        toolbar.addWidget(self.inventory_combo)

        def add_nav(label: str, slot) -> QPushButton:
            btn = QPushButton(label, toolbar)
            btn.setFont(QFont("Noto Sans", 10))
            btn.setFixedHeight(32)
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
            self._nav_buttons.append(btn)
            return btn

        add_nav("Browse\u2026", self._browse_inventory)
        add_nav("Builder", self._open_builder)
        # Spacer pushes the theme toggle to the far right.
        spacer = QWidget(toolbar)
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)
        # Theme button text and tooltip are set by ``_apply_theme_btn``.
        self._theme_btn = QPushButton("", toolbar)
        self._theme_btn.setFont(QFont("Noto Sans", 12))
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self._theme_btn)
        self._restyle_toolbar()

    def _build_central(self) -> None:
        """Build the central widget: horizontal split (seg | feat) over
        the analysis panel. Every widget gets a parent at construction
        so none are transiently top-level during the build.
        """
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {C['border']}; }}"
        )
        self.seg_panel = self._build_segment_panel(splitter)
        splitter.addWidget(self.seg_panel)
        self.feat_panel = self._build_feature_panel(splitter)
        splitter.addWidget(self.feat_panel)
        # Filter installed on each panel directly (not the QApplication)
        # so it only fires on empty-area clicks; clicks on child buttons
        # / rows trigger mode-switch via their own pressed handlers.
        self.seg_panel.installEventFilter(self)
        self.feat_panel.installEventFilter(self)
        self._hsplit = splitter
        # Balanced default; _fit_to_content overrides after an
        # inventory loads. Stretch factors keep the seg panel at its
        # natural content width and let feat absorb extra horizontal room.
        splitter.setSizes([500, 400])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.analysis = AnalysisPanel(central)
        self._vsplit = QSplitter(Qt.Orientation.Vertical, central)
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
        self.status = _BrandedStatusBar(self)
        self.status.setStyleSheet(
            f"background: {C['panel']}; border-top: 1px solid {C['border']};"
        )
        self.setStatusBar(self.status)
        self.status.showMessage(
            "Select an inventory from the dropdown to begin."
        )

    def _build_segment_panel(self, parent=None) -> QFrame:
        """Build the left (segment) panel: title, Clear button, scroll
        area containing the consonant grid + vowel chart side by side.
        The container's stylesheet has both active and inactive rules
        keyed off the ``active`` Qt property so mode toggles polish
        in place without cascading through descendants.
        """
        container = QFrame(parent)
        container.setObjectName("seg_panel")
        container.setStyleSheet(self._panel_chrome_qss("seg_panel"))
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(14, 14, 14, 10)
        vlay.setSpacing(10)
        header = QHBoxLayout()
        self._seg_title = QLabel("SEGMENTS")
        self._seg_title.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        self._seg_title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1.5px;"
        )
        self.clear_seg_btn = QPushButton("Clear", container)
        self.clear_seg_btn.setFixedHeight(26)
        self.clear_seg_btn.setFont(QFont("Noto Sans", 9))
        self.clear_seg_btn.setStyleSheet(_clear_btn_style())
        self.clear_seg_btn.clicked.connect(self._clear_then_activate_segs)
        header.addWidget(self._seg_title)
        header.addStretch()
        header.addWidget(self.clear_seg_btn)
        vlay.addLayout(header)
        self._seg_scroll = QScrollArea(container)
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
        seg_content = QWidget(self._seg_scroll)
        seg_content.setStyleSheet("background: transparent;")
        seg_content_layout = QHBoxLayout(seg_content)
        seg_content_layout.setContentsMargins(0, 0, 0, 0)
        seg_content_layout.setSpacing(12)
        left_wrap = QWidget(seg_content)
        left_wrap.setStyleSheet("background: transparent;")
        left_lay = QVBoxLayout(left_wrap)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        self.seg_grid_widget = SegmentGridWidget(left_wrap)
        left_lay.addWidget(self.seg_grid_widget)
        left_lay.addStretch()
        self.vowel_chart_widget = VowelChartWidget(seg_content)
        self.vowel_chart_widget.hide()
        self.vowel_chart_widget.setFixedWidth(
            VOWEL_LABEL_W + 6 * (BTN_W + BTN_GAP)
        )
        # stretch=0 on both so consonants and vowels keep their natural
        # widths. Extra horizontal space goes to feat_panel via the
        # outer splitter's stretch factor.
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

    def _build_feature_panel(self, parent=None) -> QFrame:
        container = QFrame(parent)
        container.setObjectName("feat_panel")
        container.setStyleSheet(self._panel_chrome_qss("feat_panel"))
        vlay = QVBoxLayout(container)
        vlay.setContentsMargins(14, 14, 14, 10)
        vlay.setSpacing(10)
        header = QHBoxLayout()
        self._feat_title = QLabel("FEATURES")
        self._feat_title.setFont(QFont("Noto Sans", 9, QFont.Weight.Bold))
        self._feat_title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1.5px;"
        )
        self.clear_feat_btn = QPushButton("Clear", container)
        self.clear_feat_btn.setFixedHeight(26)
        self.clear_feat_btn.setFont(QFont("Noto Sans", 9))
        self.clear_feat_btn.setStyleSheet(_clear_btn_style())
        self.clear_feat_btn.clicked.connect(self._clear_then_activate_feats)
        header.addWidget(self._feat_title)
        header.addStretch()
        header.addWidget(self.clear_feat_btn)
        vlay.addLayout(header)
        self._feat_scroll = QScrollArea(container)
        self._feat_scroll.setWidgetResizable(True)
        self._feat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feat_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + scrollbar_style()
        )
        self._feat_content = QWidget(self._feat_scroll)
        self._feat_content.setStyleSheet("background: transparent;")
        feat_main_layout = QHBoxLayout(self._feat_content)
        feat_main_layout.setContentsMargins(0, 0, 0, 0)
        feat_main_layout.setSpacing(8)
        self._feat_left_col = QWidget(self._feat_content)
        self._feat_left_col.setStyleSheet("background: transparent;")
        self._feat_left_layout = QVBoxLayout(self._feat_left_col)
        self._feat_left_layout.setContentsMargins(0, 0, 0, 0)
        self._feat_left_layout.setSpacing(8)
        self._feat_left_layout.addStretch()
        self._feat_right_col = QWidget(self._feat_content)
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

    def _target_screen(self) -> QScreen | None:
        """Primary screen for initial placement. The user can drag the
        window anywhere afterwards; that position is what's persisted.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        return app.primaryScreen()

    def _clamp_size_to_screen(
        self, w: int, h: int, deco_w: int = 40, deco_h: int = 40
    ) -> tuple[int, int]:
        """Clamp ``(w, h)`` so widget + decoration fits in
        ``availableGeometry``. Defaults to 40 px decoration, the
        heuristic used pre-show when real decoration isn't known.
        """
        screen = self._target_screen()
        if screen is None:
            return w, h
        avail = screen.availableGeometry()
        return (
            min(w, max(640, avail.width() - deco_w)),
            min(h, max(480, avail.height() - deco_h)),
        )

    def _ensure_visible_on_screen(self) -> None:
        """Run after first show. Leaves the window alone when it's a
        reasonable size and intersects any screen; only recenters when
        truly off-screen. ``raise_`` / ``activateWindow`` fire only on
        the recovery path (on the happy path they cause a visible focus
        blink on some Linux WMs).
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        screen = self._target_screen()
        if screen is None:
            return
        frame = self.frameGeometry()
        sane_size = frame.width() >= 300 and frame.height() >= 200
        if sane_size and any(
            s.geometry().intersects(frame) for s in app.screens()
        ):
            return
        avail = screen.availableGeometry()
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
        """Read a QSettings key, returning ``default`` if the stored
        value can't be deserialized. Older builds wrote pickled enum
        members; renaming the package invalidates those pickles and
        QSettings.value raises SystemError. Catching here lets a fresh
        default replace the bad blob on the next setValue.
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
        """Restore window size/position, mode, and last inventory."""
        # Drop the old binary geometry blob: it encodes absolute
        # positions that can place the window off-screen after a
        # display configuration change.
        self._settings.remove("geometry")
        size = self._read_setting("window_size")
        pos = self._read_setting("window_pos")
        self._has_saved_size = size is not None
        screen = self._target_screen()
        if size is not None:
            self.resize(
                *self._clamp_size_to_screen(size.width(), size.height())
            )
        else:
            self.resize(*self._clamp_size_to_screen(1200, 900))
        if pos is not None:
            self.move(pos)
        elif screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        path = startup_path or self._read_setting("last_inventory")
        if path and isinstance(path, str) and os.path.isfile(path):
            idx = self.inventory_combo.findData(path)
            if idx >= 0:
                self.inventory_combo.setCurrentIndex(idx)
            self._load_path(path)
        # Mode stored as a plain string so it survives package renames
        # that would invalidate a pickled enum.
        saved_mode = self._read_setting_str("mode", Mode.SEG_TO_FEAT.value)
        if saved_mode in (Mode.SEG_TO_FEAT.value, Mode.FEAT_TO_SEG.value):
            self._set_mode(Mode(saved_mode))

    def closeEvent(self, event):  # type: ignore[override]
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

    def _get_inventories_dir(self) -> str:
        """Absolute path to the bundled ``inventories/`` directory.
        Resolves three levels up from this file (``app/src/phonology_features/gui/``).
        """
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "inventories"
            )
        )

    def _populate_inventory_dropdown(self) -> None:
        """Scan ``inventories/`` and fill the dropdown. Preserves the
        current selection if the previously-loaded path still exists
        after the rescan (matters when the Builder saves a new file
        and the directory watcher triggers a refresh).
        """
        previous_path = self.inventory_combo.currentData()
        self.inventory_combo.blockSignals(True)
        try:
            self.inventory_combo.clear()
            self.inventory_combo.addItem(
                "Select inventory\u2026", userData=None
            )
            # Disable the placeholder row so it can't be picked.
            model = self.inventory_combo.model()
            placeholder = (
                model.item(0)
                if isinstance(model, QStandardItemModel)
                else None
            )
            if placeholder is not None:
                placeholder.setEnabled(False)
            inventories_dir = self._get_inventories_dir()
            if os.path.isdir(inventories_dir):
                for fname in sorted(os.listdir(inventories_dir)):
                    if fname.endswith(".json"):
                        path = os.path.join(inventories_dir, fname)
                        pretty = fname[:-5].replace("_", " ").title()
                        self.inventory_combo.addItem(pretty, userData=path)
            idx = (
                self.inventory_combo.findData(previous_path)
                if previous_path
                else 0
            )
            self.inventory_combo.setCurrentIndex(max(idx, 0))
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
        idx = self.inventory_combo.findData(path)
        if idx < 0:
            pretty = os.path.splitext(os.path.basename(path))[0]
            pretty = pretty.replace("_", " ").title()
            self.inventory_combo.addItem(pretty, userData=path)
            idx = self.inventory_combo.count() - 1
        self.inventory_combo.setCurrentIndex(idx)
        self._load_path(path)

    def _toggle_theme(self) -> None:
        """Switch between light and dark theme in place. Geometry,
        splitter sizes, selections, and the widget tree are all
        preserved; only stylesheet strings change.
        """
        new_theme = "dark" if get_theme_name() == "light" else "light"
        set_theme(new_theme)
        self._settings.setValue("theme", new_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Re-style every palette-dependent widget in place. Calls
        ``apply_theme`` on each widget that owns palette state, then
        forces a panel-chrome polish so the active-mode border picks
        up the new accent color, then re-runs the active analysis so
        ``set_display``-painted badges and matched/unmatched segment
        styling refresh against the new palette.
        """
        QToolTip.hideText()
        with self._batched_updates():
            for btn in self._seg_button_pool.values():
                btn.apply_theme()
            # Iterate every FeatureRow we own, not just the pool: the
            # "Other" card in inventories with non-FEATURE_ORDER features
            # (e.g. general_features.json) creates rows that live in
            # ``_feat_rows`` but NOT in ``_feat_row_pool``. Missing them
            # leaves their name / +/- buttons styled with the old
            # palette -- in dark mode after starting from light, the
            # name label's text color stays light against the dark bg,
            # making the name appear "unpopulated".
            for row in self._feat_row_pool.values():
                row.apply_theme()
            for feat, row in self._feat_rows.items():
                if feat not in self._feat_row_pool:
                    row.apply_theme()
            self._restyle_chrome()
            # Refresh the panel-chrome QSS rules then re-polish so the
            # active-mode border picks up the new accent color.
            for panel in (self.seg_panel, self.feat_panel):
                panel.setStyleSheet(self._panel_chrome_qss(panel.objectName()))
                panel.setProperty("active", None)
            self._apply_panel_chrome()
            self._refresh_analysis_for_mode()

    def _restyle_chrome(self) -> None:
        """Re-apply every chrome stylesheet that depends on the palette.
        Each helper touches one logical group of widgets in place.
        """
        self.setStyleSheet(f"background-color: {C['bg']};")
        self._restyle_toolbar()
        self._restyle_splitters()
        self._restyle_panel_chrome_widgets()
        self._restyle_feature_cards()
        self.seg_grid_widget.apply_theme()
        self.vowel_chart_widget.apply_theme()
        self.analysis.apply_theme()
        self.status.apply_theme()

    def _restyle_toolbar(self) -> None:
        self._toolbar.setStyleSheet(f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
        """)
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
        nav_style = self._nav_btn_style()
        for btn in self._nav_buttons:
            btn.setStyleSheet(nav_style)
        self._apply_theme_btn()

    def _apply_theme_btn(self) -> None:
        """Set the theme-button text, tooltip, and styling. The symbol
        shows the OPPOSITE of the active theme: clicking switches to that.
        """
        is_dark = get_theme_name() == "dark"
        self._theme_btn.setText("☼" if is_dark else "☾")
        self._theme_btn.setToolTip(
            "Switch to light mode" if is_dark else "Switch to dark mode"
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

    def _restyle_splitters(self) -> None:
        """Re-style splitter handles directly on each ``handle()`` widget.
        Calling ``setStyleSheet`` on the splitter itself would cascade
        through every descendant (140+ segment buttons), the bulk of
        the old theme-toggle cost.
        """
        for i in range(self._hsplit.count()):
            handle = self._hsplit.handle(i)
            if handle is not None:
                handle.setStyleSheet(f"background: {C['border']};")

    def _restyle_panel_chrome_widgets(self) -> None:
        """Re-style panel-child widgets with palette-dependent stylesheets:
        clear buttons, scroll bars, the seg hint. Scrollbar styles go
        directly on each ``QScrollBar`` widget (not the scroll area)
        so the cascade doesn't invalidate every panel descendant.
        Panel container backgrounds / borders are handled separately
        by ``_apply_panel_chrome`` via property-selector polish.
        """
        self.clear_seg_btn.setStyleSheet(_clear_btn_style())
        self.clear_feat_btn.setStyleSheet(_clear_btn_style())
        sb_qss = scrollbar_style()
        for scroll in (self._seg_scroll, self._feat_scroll):
            for bar in (
                scroll.verticalScrollBar(),
                scroll.horizontalScrollBar(),
            ):
                if bar is not None:
                    bar.setStyleSheet(sb_qss)
        self.seg_hint.setStyleSheet(f"color: {C['text_dim']};")

    def _restyle_feature_cards(self) -> None:
        """Re-style each group card frame and its title label."""
        card_qss = f"""
            QFrame {{
                background: {C["panel"]};
                border: 1px solid {C["border"]};
                border-radius: 7px;
            }}
        """
        title_qss = (
            f"color: {C['text_dim']}; letter-spacing: 1px; "
            "background: transparent; border: none; "
            "padding: 0 8px 2px 8px;"
        )
        cards: list[QFrame] = [card for card, _ in self._feat_cards]
        if self._other_card is not None:
            cards.append(self._other_card)
        for card in cards:
            card.setStyleSheet(card_qss)
            # Each card's first child label is its title.
            title = card.findChild(QLabel)
            if title is not None:
                title.setStyleSheet(title_qss)

    def _restore_geometry(
        self,
        pos,
        size,
        hsplit: list[int] | None,
        vsplit: list[int] | None,
    ) -> None:
        """Apply saved geometry atomically: window pos/size + splitter
        ratios, paint suspended so it's one frame.
        """
        with self._batched_updates():
            self.resize(size)
            self.move(pos)
            if hsplit and len(hsplit) == self._hsplit.count():
                self._hsplit.setSizes(hsplit)
            if vsplit and len(vsplit) == self._vsplit.count():
                self._vsplit.setSizes(vsplit)

    def _open_builder(self) -> None:
        """Open (or raise) the Builder window. Edits the current
        inventory in place if one is loaded; otherwise shows the
        new-inventory setup dialog.
        """
        if self._builder is not None and self._builder.isVisible():
            self._builder.raise_()
            self._builder.activateWindow()
            return
        from phonology_features.gui.builder import InventoryBuilder

        if self._current_path:
            self._builder = InventoryBuilder(
                parent=self, load_path=self._current_path
            )
            self._builder.setWindowFlag(Qt.WindowType.Window)
            self._builder.show()
            return
        # No inventory loaded; show the setup dialog. Cancel = no window.
        builder = InventoryBuilder(parent=self)
        builder.setWindowFlag(Qt.WindowType.Window)
        if not builder.show_setup_dialog():
            builder.deleteLater()
            return
        self._builder = builder
        self._builder.show()

    def _load_path(self, path: str):
        """Load an inventory JSON. Shared by the dropdown, Browse, and
        the file-system watcher's auto-reload path. Phases (parse,
        install engine, register, populate) live in named helpers below
        so a failure short-circuits cleanly.
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
        """Read the JSON file and run the shared validator. Returns the
        parsed dict on success, or None after surfacing a human-readable
        error in the status bar and analysis panel.
        """
        fname = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self.status.showMessage(f"Cannot load {fname}: file not found")
            return None
        except json.JSONDecodeError as e:
            self.status.showMessage(
                f"Cannot load {fname}: invalid JSON "
                f"({e.msg} on line {e.lineno})"
            )
            return None
        except OSError as e:
            self.status.showMessage(f"Cannot load {fname}: {e}")
            return None
        errors, warnings = validate_inventory_data(data)
        if errors:
            self.status.showMessage(f"Cannot load {fname}: {errors[0]}")
            self.analysis.set_html(
                self._validation_report_html(errors, warnings)
            )
            return None
        for w in warnings:
            self.status.showMessage(f"Warning: {w}")
        return data

    @staticmethod
    def _validation_report_html(errors: list[str], warnings: list[str]) -> str:
        parts = [
            f"<p><b style='color:{C['minus']}'>Validation errors:</b></p>"
        ]
        parts.extend(f"<p>{e}</p>" for e in errors)
        if warnings:
            parts.append("<p><b>Warnings:</b></p>")
            parts.extend(f"<p>{w}</p>" for w in warnings)
        return "".join(parts)

    def _install_engine(self, path: str, data: dict) -> bool:
        """Build a fresh FeatureEngine for ``data`` and adopt it.
        Returns True on success. Surface engine errors as status
        messages rather than crashing the GUI.
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
        """Wire watcher, dropdown, and settings for a newly-loaded path."""
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
        idx = self.inventory_combo.findData(path)
        if idx >= 0:
            self.inventory_combo.setCurrentIndex(idx)
        self._settings.setValue("last_inventory", path)

    def _populate_after_load(self) -> None:
        """Rebuild segment + feature widgets for the freshly-loaded engine.
        Startup runs ``_rebalance_vsplit`` synchronously so the first
        paint is already at the right size; runtime swaps defer one
        event-loop tick so pending paints drain before we resize.
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
        """Watched directory changed (file created / renamed / deleted).
        Refresh the dropdown if the inventories dir changed; re-arm the
        file watcher if the current file reappeared after a
        delete-then-write editor cycle.
        """
        if os.path.normpath(directory) == self._get_inventories_dir():
            self._populate_inventory_dropdown()
        if not self._current_path:
            return
        if (
            os.path.isfile(self._current_path)
            and self._current_path not in self._watcher.files()
        ):
            self._watcher.addPath(self._current_path)
            self._reload_timer.start()

    def _do_auto_reload(self) -> None:
        """Reload the current inventory after the watcher debounce fires."""
        if self._current_path and os.path.isfile(self._current_path):
            self._load_path(self._current_path)
            fname = os.path.basename(self._current_path)
            self.status.showMessage(f"Auto-reloaded \u201c{fname}\u201d")

    def _populate_segments(self):
        """Populate the seg grid + vowel chart from the active engine.
        Reuses pooled SegmentButtons where possible; detaches pool
        entries not in the current inventory.
        """
        if self.engine is None:
            return
        self._selected_segments.clear()
        self.seg_hint.hide()
        # Cache grouping per engine; cleared in _load_path on engine swap.
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
        # Detach inactive pool entries (hide before setParent(None) so
        # they don't briefly become top-level windows).
        active = set(self._seg_buttons)
        for sym, btn in self._seg_button_pool.items():
            if sym not in active and btn.parent() is not None:
                btn.hide()
                btn.setParent(None)

    def _get_or_create_seg_button(self, seg: str):
        """Return a SegmentButton for ``seg``, creating it on first use.
        Reused buttons get reset to DEFAULT since the previous inventory
        may have left them checked or styled.
        """
        btn = self._seg_button_pool.get(seg)
        if btn is None:
            btn = SegmentButton(seg)
            btn.pressed.connect(self._on_segment_pressed)
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
        """Build one labelled group card. Returns None if no features
        in this group are active in the current inventory. Parented to
        the left-column container; ``_redistribute_feature_cards`` will
        re-parent to whichever column the LPT balancer picks.
        """
        active = [f for f in features if f in self._feat_rows]
        if not active:
            return None
        group_frame = QFrame(self._feat_left_col)
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
        """Pre-create a FeatureRow per FEATURE_ORDER entry and build the
        FEATURE_GROUPS cards. Column placement happens per-inventory in
        ``_redistribute_feature_cards`` because card heights depend on
        the active feature count (e.g. Tongue-Root has 1 active feature
        in Hayes but 4 in Blevins).

        ``_feat_row_pool`` keeps every row created; ``_feat_rows`` is
        the active subset and is what external code iterates.
        """
        for feat in FEATURE_ORDER:
            if feat not in self._feat_row_pool:
                row = FeatureRow(feat)
                row.value_changed.connect(self._on_feature_changed)
                row.plus_btn.pressed.connect(self._on_feature_pressed)
                row.minus_btn.pressed.connect(self._on_feature_pressed)
                self._feat_row_pool[feat] = row
        if self._feature_pool_initialized and self._feat_cards:
            return
        # Temporarily expose pool rows via _feat_rows so
        # _build_feature_group can find them while constructing cards.
        self._feat_rows = dict(self._feat_row_pool)
        for title, feats_list in FEATURE_GROUPS:
            card = self._build_feature_group(title, feats_list)
            if card is not None:
                card.hide()
                self._feat_cards.append((card, list(feats_list)))
        # Reset to the active-only contract; _populate_features will
        # repopulate for the current inventory.
        self._feat_rows = {}
        for row in self._feat_row_pool.values():
            row.setVisible(False)
        self._feature_pool_initialized = True

    def _populate_features(self) -> None:
        """Show / hide / reset pool rows for the active feature set, build
        the Other card for non-FEATURE_ORDER features, then balance the
        cards across the two columns.
        """
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
        self._feat_rows = {}
        for feat, row in self._feat_row_pool.items():
            if feat in active_feature_set:
                row.setVisible(True)
                row.reset()
                self._feat_rows[feat] = row
            else:
                row.setVisible(False)
        # Build the Other card BEFORE redistribute so it joins the
        # same column-balancing pass as the standard cards.
        unknown_active = sort_features(
            [f for f in active_feature_set if f not in set(FEATURE_ORDER)]
        )
        self._refresh_other_card(unknown_active)
        self._redistribute_feature_cards(active_feature_set)

    def _refresh_other_card(self, unknown_active: list[str]) -> None:
        """Rebuild the dynamic "Other" card for inventory-specific
        features that don't appear in FEATURE_ORDER. Doesn't place it
        in a column; that happens in ``_redistribute_feature_cards``.
        """
        if self._other_card is not None:
            for feat in list(self._feat_rows.keys()):
                if feat not in self._feat_row_pool:
                    orphan = self._feat_rows.pop(feat)
                    orphan.hide()
                    orphan.setParent(None)
            self._other_card.hide()
            self._other_card.setParent(None)
            self._other_card.deleteLater()
            self._other_card = None
        if not unknown_active:
            return
        for feat in unknown_active:
            row = FeatureRow(feat)
            row.value_changed.connect(self._on_feature_changed)
            row.plus_btn.pressed.connect(self._on_feature_pressed)
            row.minus_btn.pressed.connect(self._on_feature_pressed)
            self._feat_rows[feat] = row
        self._other_card = self._build_feature_group("Other", unknown_active)
        if self._other_card is not None:
            self._other_card.hide()

    # Layout policy for feature-group cards.
    #
    # Soft pins (placed only if the card has any active features in the
    # current inventory):
    #   Major Class -> top of left column
    #   Place       -> under Major Class in left column
    #   Manner      -> top of right column
    #
    # Everything else is sorted by active feature count descending and
    # dropped into whichever column is shorter at placement time (LPT
    # scheduling). Packs columns as close to equal height as the active
    # counts allow.
    _LEFT_PINS: tuple[str, ...] = ("Major Class", "Place")
    _RIGHT_PINS: tuple[str, ...] = ("Manner",)
    # Per-card overhead (header + padding) expressed in row-equivalents,
    # added to each card's row count when balancing column heights so
    # many-small-cards columns aren't under-counted vs few-big-cards.
    _CARD_OVERHEAD: int = 1

    def _redistribute_feature_cards(self, active: set[str]) -> None:
        """Place cards in left/right columns using soft pins + LPT.
        Re-runs on every inventory load because card heights vary with
        the active feature count (Tongue-Root has 1 active feature in
        Hayes but 4 in Blevins).
        """
        self._take_cards_out_of_columns()
        # info[title] = (card, cost) where cost = active rows + overhead.
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
        """Empty both column layouts. Card widgets stay alive (held by
        ``_feat_cards`` / ``_other_card``); spacer items get released.
        """
        for layout in (self._feat_left_layout, self._feat_right_layout):
            while layout.count():
                layout.takeAt(0)

    @staticmethod
    def _card_title(card: QFrame) -> str:
        """Read the title text from a feature-group card. The card's
        first child is always a QLabel(title) per ``_build_feature_group``.
        """
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

    def _fit_to_content(self) -> None:
        """Measure content and size window + splitters to fit. Called
        after each inventory load. On first load (no saved size) the
        window itself is resized; always sets the horizontal splitter
        so both panels get the width their content needs.
        """
        QApplication.processEvents()
        # Seg panel sticks to its natural content width; extra horizontal
        # room belongs to the feature pane (stretch=1 on the splitter),
        # not to dead space after the vowels.
        seg_content = self._seg_scroll.widget()
        seg_content_w = seg_content.sizeHint().width() if seg_content else 400
        seg_chrome = 28 + 6  # panel margins (14 * 2) + scrollbar clearance
        seg_need_w = seg_content_w + seg_chrome
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
        feat_v_padding = 20
        top_need_h = feat_content_h + 80 + feat_v_padding
        analysis_h = self._min_analysis_h
        toolbar_h = 50
        total_need_h = top_need_h + analysis_h + toolbar_h + 30
        # Paint suspended so the window doesn't flash through
        # "new size + old splitter ratio" before setSizes lands.
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
        ``_has_saved_size`` is False on a fresh launch, so the first
        load centers; every load after that anchors to ``self.pos()``,
        the live position including any manual drag the user just did.
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
        if not self._has_saved_size:
            frame_x = avail.x() + (avail.width() - (new_w + deco_w)) // 2
            frame_y = avail.y() + (avail.height() - (new_h + deco_h)) // 2
            self.setGeometry(
                frame_x + left_pad, frame_y + top_pad, new_w, new_h
            )
            self._has_saved_size = True
            return
        if new_w == cur_w and new_h == cur_h:
            return
        # Anchor to the current corner. Only shift when the title bar
        # itself would go off the left/top edge (unreachable case).
        # Partial overflow on right or bottom is left alone.
        new_x = old_pos.x()
        new_y = old_pos.y()
        if new_x - left_pad < avail.x():
            new_x = avail.x() + left_pad
        if new_y - top_pad < avail.y():
            new_y = avail.y() + top_pad
        # setGeometry applies resize + move atomically; separate calls
        # produce a visible intermediate frame on some WMs.
        self.setGeometry(new_x, new_y, new_w, new_h)

    def _decoration_padding(self, old_pos) -> tuple[int, int, int, int]:
        """Return (deco_w, deco_h, left_pad, top_pad) for the current
        frame. Trusts the WM-reported decoration when nonzero; falls back
        to ``_MIN_DECO_*`` only when the WM reports zero (Wayland CSD,
        pre-show callers). Inflating thin-border-WM values past their
        true size used to shift the anchor left a few pixels per resize.
        """
        if not self.isVisible():
            return _MIN_DECO_W, _MIN_DECO_H, 0, 0
        old_frame = self.frameGeometry()
        deco_w_reported = max(0, old_frame.width() - self.width())
        deco_h_reported = max(0, old_frame.height() - self.height())
        deco_w = deco_w_reported if deco_w_reported else _MIN_DECO_W
        deco_h = deco_h_reported if deco_h_reported else _MIN_DECO_H
        left_pad = max(0, old_pos.x() - old_frame.x())
        top_pad = max(0, old_pos.y() - old_frame.y())
        return deco_w, deco_h, left_pad, top_pad

    def _apply_splitter_sizes(
        self, seg_need_w: int, feat_need_w: int, top_need_h: int
    ) -> None:
        """Size the seg pane to its content width and let the feature
        pane absorb the rest. Rebalance the vertical splitter so the
        analysis panel keeps its minimum height.
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
        """Re-run the fit pass. Wired to the post-load QTimer."""
        self._fit_to_content()

    def _apply_mode_to_new_widgets(self) -> None:
        """Set interactivity on freshly-populated rows + headers for the
        current mode, then clear both sides. Called after inventory load.
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
        """Suspend Qt paint events for the duration. Depth-aware so
        nested scopes share one setUpdatesEnabled(False/True) pair,
        which prevents an inner exit from re-enabling paint mid-rebuild.
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
        """Switch top-level UI mode. Accepts bare strings (from QSettings
        and tests) and coerces. Bails when the requested mode equals the
        current one; callers that need to re-apply chrome unconditionally
        call ``_apply_mode_phases`` directly.
        """
        mode = Mode(mode)
        if mode == self._mode:
            return
        self._save_outgoing_mode_state()
        self._mode = mode
        self._apply_mode_phases()

    def _apply_mode_phases(self) -> None:
        """Run every mode-aware UI update against the current mode."""
        with self._batched_updates():
            self._apply_panel_chrome()
            self._apply_row_interactivity()
            self._restore_segment_selection()
            self._restore_feature_selection()
            self._refresh_analysis_for_mode()
            self._update_status_message()

    # _save_outgoing_mode_state runs BEFORE self._mode is updated (it
    # captures the state of the mode being left); every other _set_mode
    # phase runs after self._mode has been set.
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

    @staticmethod
    def _panel_chrome_qss(object_name: str) -> str:
        """Stylesheet baked once at panel creation with both active and
        inactive rules. ``_apply_panel_chrome`` toggles the ``active``
        property instead of replacing the sheet; Qt then only re-polishes
        the panel widget, not every descendant.
        """
        return (
            f"QFrame#{object_name} {{ background: {C['bg']}; border: none; }}"
            f'QFrame#{object_name}[active="true"] {{'
            f" background: {C['panel']};"
            f" border: 1.5px solid {C['accent']};"
            f" }}"
        )

    def _apply_panel_chrome(self) -> None:
        """Reflect the active mode on the chrome. Panel highlight uses
        a Qt property + ``style().polish()`` so the active border swap
        re-styles the panel only, not its 140+ descendants. Title
        labels are tiny so a direct setStyleSheet on them is fine.
        """
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        self._polish_active(self.seg_panel, is_s2f)
        self._polish_active(self.feat_panel, not is_s2f)
        self._seg_title.setStyleSheet(
            f"color: {C['text'] if is_s2f else C['text_dim']};"
            " letter-spacing: 1.5px;"
        )
        self._feat_title.setStyleSheet(
            f"color: {C['text'] if not is_s2f else C['text_dim']};"
            " letter-spacing: 1.5px;"
        )
        self.seg_grid_widget.set_headers_active(is_s2f)
        self.vowel_chart_widget.set_headers_active(is_s2f)

    @staticmethod
    def _polish_active(widget, active: bool) -> None:
        """Flip the ``active`` Qt property and re-polish so the
        property-selector rule takes effect. Cheaper than setStyleSheet
        because polish doesn't cascade.
        """
        if widget.property("active") == active:
            return
        widget.setProperty("active", active)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def _apply_row_interactivity(self) -> None:
        """Set each FeatureRow's interactivity to match the active mode."""
        is_s2f = self._mode == Mode.SEG_TO_FEAT
        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)

    def _restore_segment_selection(self) -> None:
        """Set each segment button to its final state for the new mode.
        Seg mode restores from ``_saved_seg_state``; feat mode clears
        the visual selection (matched/unmatched styling is applied
        later by ``_refresh_analysis_for_mode``).
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
        """Set each feature row to its final state for the new mode.
        Sole authority on per-row visual state during a mode switch;
        rows in ``_saved_feat_state`` get ``restore_value``, the rest
        get ``reset``.
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
        """Clear the analysis panel and re-run the active mode's
        analysis if there's something to analyze.
        """
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
        """Activate the clicked panel on a press in its empty area.
        Installed on ``seg_panel`` / ``feat_panel`` only, so ``a0`` is
        always one of the two. Clicks on child widgets switch mode via
        their own pressed handlers.
        """
        if a1 is None or a1.type() != _QEVENT_MOUSE_BUTTON_PRESS:
            return False
        if a0 is self.seg_panel and self._mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)
        elif a0 is self.feat_panel and self._mode != Mode.FEAT_TO_SEG:
            self._set_mode(Mode.FEAT_TO_SEG)
        return False

    # State changes are immediate; analysis is debounced via _debounce.
    def _on_segment_clicked(self, segment: str, checked: bool):
        if self._mode != Mode.SEG_TO_FEAT:
            # Real mouse clicks switch mode via _on_segment_pressed
            # before the clicked signal fires; this branch protects
            # programmatic / test callers from mutating state.
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

    def _on_segment_pressed(self) -> None:
        """Mouse press on a segment button: switch to seg mode before
        the click signal lands.
        """
        if self._mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)

    def _on_feature_changed(self, feature: str, value: str):
        if self._mode != Mode.FEAT_TO_SEG:
            return
        if value:
            self._selected_features[feature] = value
        else:
            self._selected_features.pop(feature, None)
        self._debounce.start()

    def _on_feature_pressed(self) -> None:
        """Mouse press on a +/- button: switch to feat mode before the
        value_changed signal lands.
        """
        if self._mode != Mode.FEAT_TO_SEG:
            self._set_mode(Mode.FEAT_TO_SEG)

    def _run_pending_update(self) -> None:
        """Fired by the debounce timer; dispatches to the active mode."""
        with self._batched_updates():
            if self._mode == Mode.SEG_TO_FEAT:
                self._update_seg_to_feat()
            else:
                self._update_feat_to_seg()

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
            # Natural-class completion: find segments that would extend
            # the current selection to the smallest valid natural class.
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

    def _reset_feature_display(self) -> None:
        for row in self._feat_rows.values():
            row.reset()

    def _clear_segments(self, silent=False):
        """Either Clear button wipes both panes. See ``_reset_both_sides``."""
        self._reset_both_sides(silent)

    def _clear_features(self, silent=False):
        """Either Clear button wipes both panes. See ``_reset_both_sides``."""
        self._reset_both_sides(silent)

    def _clear_then_activate_segs(self) -> None:
        """Clear button handler: wipe both panes, then activate seg mode.
        Reversing the order would flash the new mode's colors for a
        frame before the wipe lands.
        """
        self._reset_both_sides(silent=False)
        if self._mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)

    def _clear_then_activate_feats(self) -> None:
        """See ``_clear_then_activate_segs``."""
        self._reset_both_sides(silent=False)
        if self._mode != Mode.FEAT_TO_SEG:
            self._set_mode(Mode.FEAT_TO_SEG)

    def _reset_both_sides(self, silent: bool) -> None:
        """Reset segments and features to their neutral state. Shared
        implementation behind both Clear buttons. "Clear means clear":
        the two panes are wired together, so each Clear wipes both.
        """
        self._selected_segments.clear()
        self._selected_features.clear()
        for btn in self._seg_buttons.values():
            if btn._state != SegmentState.DEFAULT:
                btn.set_state(SegmentState.DEFAULT)
                btn.setChecked(False)
        for row in self._feat_rows.values():
            row.reset()
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()
