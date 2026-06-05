"""
gui/main_window.py
PyQt6 GUI for the Segment & Feature Engine.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QMoveEvent,
    QPalette,
    QResizeEvent,
    QShowEvent,
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
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from phonology_features._logging import get_logger
from phonology_features._settings import (
    SettingsKey,
    safe_read_setting,
    write_setting,
)
from phonology_features.gui.controllers.geometry import GeometryController
from phonology_features.gui.controllers.inventory_dir import (
    InventoryDirController,
)
from phonology_features.gui.controllers.mode import ModeController
from phonology_features.gui.controllers.theme import ThemeController
from phonology_features.gui.style_utils import (
    set_css,
)
from phonology_features.gui.themed_widgets import (
    _BrandedStatusBar,
    _clear_btn_style,
    _ThemedCard,
    _ThemedSplitter,
)
from phonology_features.gui.vowel_chart import VowelChartWidget
from phonology_features.gui.widgets import (
    AnalysisPanel,
    FeatureRow,
    SegmentButton,
    SegmentGridWidget,
    SegmentState,
)
from phonology_shared.data.inventory import Inventory, ValidationError
from phonology_shared.presentation import layout
from phonology_shared.presentation.analysis import render_validation_report
from phonology_shared.presentation.constants import (
    FEATURE_GROUPS,
    FEATURE_ORDER,
    SETTINGS_APP,
    SETTINGS_ORG,
    scrollbar_style,
    sort_features,
)
from phonology_shared.presentation.layout import distribute_feature_groups
from phonology_shared.presentation.mode_logic import (
    Mode,
    clipboard_copy_message,
    inventory_load_failure_message,
    inventory_loaded_message,
    mode_status_text,
)
from phonology_shared.presentation.palette import (
    ALLOWED_PALETTE_MODES,
    ALLOWED_THEMES,
    C,
    detect_system_theme,
    set_palette_mode,
    set_theme,
)
from phonology_shared.presentation.view_models import (
    AnalysisTabsPayload,
    summarize_feature_query,
    summarize_segment_selection,
)
from phonology_shared.theory.feature_engine import FeatureEngine

if TYPE_CHECKING:
    from phonology_features.gui.builder import InventoryBuilder

_log = get_logger(__name__)


# Cached enum member. eventFilter runs on every Qt event (10k+ per user
# action); binding the comparison target to a name avoids resolving
# QEvent.Type.MouseButtonPress through the enum machinery each call.
_QEVENT_MOUSE_BUTTON_PRESS = QEvent.Type.MouseButtonPress


class MainWindow(QMainWindow):
    def __init__(self, startup_path: str | None = None) -> None:
        super().__init__()
        self.engine: FeatureEngine | None = None
        # Mode controller owns ``mode``, ``saved_seg_state``, and
        # ``saved_feat_state``. Reach through ``self._mode_ctrl`` at
        # call sites; do not add forwarding properties here.
        self._mode_ctrl = ModeController(self)
        # segment -> SegmentButton for the active inventory
        self._seg_buttons: dict[str, SegmentButton] = {}
        # Cross-inventory pool keyed by segment symbol. Reused across
        # loads since /p t k m n s/ etc. are nearly universal; avoids
        # the QPushButton + setStyleSheet cost on every swap.
        self._seg_button_pool: dict[str, SegmentButton] = {}
        self._feat_rows: dict[str, FeatureRow] = {}  # active subset
        self._selected_segments: list[str] = []
        self._selected_features: dict[str, str] = {}  # feature -> '+'/'-'
        self._current_path: str | None = None
        # Watcher, MRU, dropdown population, and delete-fallback all
        # live in the InventoryDirController, built after _build_ui
        # because it needs the combobox widget.
        self._inv_dir: InventoryDirController  # populated below
        self._did_first_show = False
        self._builder: InventoryBuilder | None = None
        # Last-seen segment-pane width; ``_on_seg_pane_width_changed``
        # short-circuits when the width hasn't actually changed across
        # a Qt-internal layout pass. Initialized to -1 so the first
        # real width always falls through; explicit field beats a
        # ``getattr(..., -1)`` because it surfaces the contract in
        # __init__ instead of hiding behind a defaulted read.
        self._last_seg_pane_w: int = -1
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
        # Geometry / splitter policy lives in a controller built in
        # _build_central once the splitter widgets exist. Holds the
        # anchor_pos, programmatic_geom flag, and the sizing rules
        # that previously lived inline as MainWindow methods.
        self._geom: GeometryController  # populated in _build_central
        self.setWindowTitle("Feature visualizer")
        self.setMinimumSize(640, 480)
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Apply theme BEFORE the window background so its own bg picks
        # up the right palette. First launch follows the OS scheme;
        # subsequent launches honour the user's last manual toggle.
        saved_theme = self._read_setting_str(
            SettingsKey.THEME, detect_system_theme()
        )
        # Validate at the trust boundary: a corrupt QSettings value
        # would crash ``set_theme`` (strict since the silent-coercion
        # fix), so map unknown values back to the OS default before
        # calling in.
        if saved_theme not in ALLOWED_THEMES:
            saved_theme = detect_system_theme()
        set_theme(saved_theme)
        # Restore the user's standard/colorblind palette choice so chrome
        # built before ``apply()`` runs picks up the right hues from
        # ``C`` directly (avoids a one-frame flash of standard colors).
        saved_mode = self._read_setting_str(
            SettingsKey.PALETTE_MODE, "standard"
        )
        if saved_mode not in ALLOWED_PALETTE_MODES:
            saved_mode = "standard"
        set_palette_mode(saved_mode)
        set_css(self, f"background-color: {C['bg']};")
        # 150 ms debounce for selection-change analysis.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._run_pending_update)
        # Theme controller built before ``_build_ui`` because the
        # toolbar wires its toggle into the theme button click signal.
        self._theme = ThemeController(self)
        self._build_ui()
        # Constructed AFTER _build_ui: needs the inventory_combo
        # widget that _build_toolbar creates.
        self._inv_dir = InventoryDirController(
            self, self._settings, self.inventory_combo
        )
        # Initial mode is already SEG_TO_FEAT, so _set_mode would no-op;
        # apply chrome directly.
        self._mode_ctrl.apply_phases()
        self._restore_settings(startup_path)
        # The first PaletteChange after a palette-mode swap triggers a
        # full polish cascade that can sub-pixel-shift widgets (visible
        # as a "shake" on the user's first colorblind toggle). One
        # synthetic round-trip now lets Qt finish that work invisibly.
        self._warm_palette_cache()

    def _warm_palette_cache(self) -> None:
        """Cycle the active palette mode once to pre-build cached
        style strings and exercise Qt's PaletteChange path for both
        modes. The intermediate state is never shown because
        ``setUpdatesEnabled(False)`` is held for the whole pair of
        toggles. Idempotent: calling twice does no extra work since
        the second pass is a cache hit.
        """
        from phonology_shared.presentation.palette import (
            get_palette_mode,
            set_palette_mode,
        )

        original = get_palette_mode()
        alternate = "colorblind" if original == "standard" else "standard"
        with self._batched_updates():
            set_palette_mode(alternate)
            self._theme.apply()
            set_palette_mode(original)
            self._theme.apply()

    def _set_mode(self, mode: Mode | str) -> None:
        """Thin wrapper around the mode-controller transition.

        Kept as a one-liner because it is called from many internal
        sites (event filter, builder save handler, click handlers)
        and the short name reads better at the call site than the
        controller-qualified form.
        """
        self._mode_ctrl.set_mode(mode)

    def _build_ui(self) -> None:
        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

    def _build_toolbar(self) -> None:
        """Build the top toolbar.

        Every widget gets a parent at construction; a parent-less
        :class:`QToolBar` would take the ``Qt.Tool`` window flag and
        flash as a transient floating window on Wayland.
        """
        self._toolbar = QToolBar(self)
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)
        toolbar = self._toolbar
        self._nav_buttons: list[QPushButton] = []
        self.inventory_combo = QComboBox(toolbar)
        self.inventory_combo.setFont(QFont("Noto Sans", 10))
        # Minimum (not fixed) height so the combo grows with font
        # metrics on 200%+ scaled displays without clipping.
        self.inventory_combo.setMinimumHeight(32)
        self.inventory_combo.setMinimumWidth(176)
        set_css(self.inventory_combo, ThemeController.combo_style())
        # Populated by ``InventoryDirController.__init__``, which
        # runs after ``_build_ui`` because it needs the combo widget.
        self.inventory_combo.activated.connect(self._on_inventory_selected)
        toolbar.addWidget(self.inventory_combo)

        def add_nav(label: str, slot: Callable[[], object]) -> QPushButton:
            btn = QPushButton(label, toolbar)
            btn.setFont(QFont("Noto Sans", 10))
            # Floor at 32px (the historic 1x baseline); Qt grows the
            # button when the font scales up on a hi-DPI display so
            # glyphs don't clip at 200% / 300% OS scaling.
            btn.setMinimumHeight(32)
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
        set_css(spacer, "background: transparent;")
        toolbar.addWidget(spacer)
        # Colorblind toggle; text/tooltip/styling set by
        # :py:meth:`ThemeController.apply_cb_btn`.
        self._cb_btn = QPushButton("", toolbar)
        self._cb_btn.setFont(QFont("Noto Sans", 12))
        self._cb_btn.setFixedSize(32, 32)
        self._cb_btn.clicked.connect(self._theme.toggle_palette_mode)
        toolbar.addWidget(self._cb_btn)
        cb_gap = QWidget(toolbar)
        cb_gap.setFixedWidth(8)
        set_css(cb_gap, "background: transparent;")
        toolbar.addWidget(cb_gap)
        # Theme button text and tooltip are set later by
        # :py:meth:`ThemeController.apply_theme_btn`.
        self._theme_btn = QPushButton("", toolbar)
        self._theme_btn.setFont(QFont("Noto Sans", 12))
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.clicked.connect(self._theme.toggle)
        toolbar.addWidget(self._theme_btn)
        self._theme._restyle_toolbar()

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
        splitter = _ThemedSplitter(Qt.Orientation.Horizontal, central)
        # DPR-scaled so the handle stays the same physical size
        # under fractional/integer OS scaling. Fall back to 1.0
        # only in headless tests where Qt reports no screen.
        primary = QApplication.primaryScreen()
        dpr = primary.devicePixelRatio() if primary is not None else 1.0
        splitter.setHandleWidth(layout.scaled_handle_w(dpr))
        self.seg_panel = self._build_segment_panel(splitter)
        # Floors so the user can't drag a pane to zero. Below
        # SEG_MIN_W the segments grid + vowel chart genuinely can't
        # render; below FEAT_MIN_W feature card titles clip.
        self.seg_panel.setMinimumWidth(layout.SEG_MIN_W)
        splitter.addWidget(self.seg_panel)
        self.feat_panel = self._build_feature_panel(splitter)
        self.feat_panel.setMinimumWidth(layout.FEAT_MIN_W)
        splitter.addWidget(self.feat_panel)
        # And prevent the splitter from collapsing either child even
        # if the user double-clicks the handle.
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        # Filter installed on each panel directly (not the QApplication)
        # so it only fires on empty-area clicks; clicks on child buttons
        # / rows trigger mode-switch via their own pressed handlers.
        self.seg_panel.installEventFilter(self)
        self.feat_panel.installEventFilter(self)
        self._hsplit = splitter
        # Initial split. ``apply_splitter_sizes`` reroutes through the
        # shared ``layout.distribute_pane_widths`` on the first
        # inventory load and from then on; this seed is what users
        # see for the ~50 ms between window paint and inventory mount.
        initial_seg, initial_feat = layout.distribute_pane_widths(
            900, seg_content_w=500, feat_content_w=380
        )
        splitter.setSizes([initial_seg, initial_feat])
        # Stretch policy: seg pane absorbs extra horizontal width on
        # resize (more room for segments → more columns → less
        # crowded). Feat pane stays at its content-driven width
        # (kept "relatively consistent" per the user's request).
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self.analysis = AnalysisPanel(central)
        self._vsplit = _ThemedSplitter(Qt.Orientation.Vertical, central)
        self._vsplit.addWidget(splitter)
        self._vsplit.addWidget(self.analysis)
        # First-paint seed: reserve the comfortable analysis floor so
        # the 50 ms pre-fit_to_content paint shows the analysis pane
        # at its real minimum, not the historical 220 px stub. The top
        # half gets whatever remains of MIN_FIRST_LAUNCH_H after the
        # toolbar / status bar / floor reservation; on the first
        # ``fit_to_content`` call those numbers get re-applied against
        # the live vsplit height.
        _initial_analysis_h = layout.analysis_content_floor_h()
        _initial_top_h = max(
            layout.MIN_TOP_PANE_H,
            layout.MIN_FIRST_LAUNCH_H - _initial_analysis_h - 100,
        )
        self._vsplit.setSizes([_initial_top_h, _initial_analysis_h])
        # Vertical handle is not user-draggable; the split is driven
        # by the analysis pane's four-row floor plus the top pane's
        # content-derived minimum. Qt resets ``handleWidth`` on every
        # style polish, so ``setHandleWidth(0)`` doesn't stick.
        # Disabling the handle widget AND clamping its max height to
        # 0 does.
        handle = self._vsplit.handle(1)
        if handle is not None:
            handle.setEnabled(False)
            handle.setCursor(Qt.CursorShape.ArrowCursor)
            handle.setMaximumHeight(0)
            handle.setMinimumHeight(0)
        # Vertical stretch: extra height goes to the TOP pane (seg
        # + feat). The analysis pane keeps its comfortable four-row
        # floor; spare vertical room is what lets the segment grid
        # fit more rows / reduce its internal scrollbar, and what
        # the feature panel uses to drop its own scrollbar.
        self._vsplit.setStretchFactor(0, 1)
        self._vsplit.setStretchFactor(1, 0)
        self._geom = GeometryController(
            self, self._hsplit, self._vsplit, self._settings
        )
        # The widget's ``minimumSizeHint`` already returns the
        # comfortable four-row floor via
        # ``REGION_CONSTRAINTS['analysis_panel'].min_h``. Setting an
        # explicit ``setMinimumHeight`` here would lock that into a
        # second authority and break the degenerate-window fallback;
        # leave Qt's minimum-resolution machinery to read the hint.
        self._vsplit.setCollapsible(1, False)
        root.addWidget(self._vsplit)
        # A manual drag owns the ratio until the next inventory
        # load; without this flag, ``fit_to_content`` would clobber
        # it. Initialised in _restore_settings.
        self._hsplit.splitterMoved.connect(self._geom.mark_splitter_owned)
        self._vsplit.splitterMoved.connect(self._geom.mark_splitter_owned)
        # Push horizontal drag into seg-pane internals so the vowel
        # chart resizes and flips at the ``VOWEL_STACK_W`` threshold.
        self._hsplit.splitterMoved.connect(self._on_hsplit_moved)

    def _build_status_bar(self) -> None:
        self.status = _BrandedStatusBar(self)
        self.status.setStyleSheet(
            f"background: {C['panel']}; border-top: 1px solid {C['border']};"
        )
        self.setStatusBar(self.status)
        self.status.showMessage(
            mode_status_text(Mode.SEG_TO_FEAT, has_engine=False)
        )

    def _build_segment_panel(self, parent: QWidget | None = None) -> QFrame:
        """Build the left (segment) panel: title, Clear button, scroll
        area containing the consonant grid + vowel chart side by side.
        The container's stylesheet has both active and inactive rules
        keyed off the ``active`` Qt property so mode toggles polish
        in place without cascading through descendants.
        """
        container = QFrame(parent)
        container.setObjectName("seg_panel")
        set_css(container, ModeController.panel_chrome_qss("seg_panel"))
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
        set_css(self.clear_seg_btn, _clear_btn_style())
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
        set_css(seg_content, "background: transparent;")
        # VBox root so the vowel chart can move between beside-
        # and below-consonants slots when the seg pane is narrow.
        # ``_on_seg_pane_width_changed`` flips at ``VOWEL_STACK_W``.
        seg_content_layout = QVBoxLayout(seg_content)
        seg_content_layout.setContentsMargins(0, 0, 0, 0)
        seg_content_layout.setSpacing(12)
        self._seg_h_pair = QHBoxLayout()
        self._seg_h_pair.setContentsMargins(0, 0, 0, 0)
        self._seg_h_pair.setSpacing(12)
        left_wrap = QWidget(seg_content)
        set_css(left_wrap, "background: transparent;")
        left_lay = QVBoxLayout(left_wrap)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        self.seg_grid_widget = SegmentGridWidget(left_wrap)
        # Stretch=1 + ``MinimumExpanding`` vertical policy on the widget
        # (set inside SegmentGridWidget.__init__) lets the consonant
        # grid absorb whatever vertical space left_wrap holds -- so
        # the spillover algorithm sees the FULL available column-of-
        # consonants height as its budget instead of just the
        # natural-content height. No trailing ``addStretch`` so the
        # widget actually claims that space.
        left_lay.addWidget(self.seg_grid_widget, stretch=1)
        self.vowel_chart_widget = VowelChartWidget(seg_content)
        self.vowel_chart_widget.hide()
        # Seed with the per-pane width default; the splitter-drag
        # callback pushes the adapted value in later. We can't read
        # ``self._hsplit`` here because it's still being built.
        self.vowel_chart_widget.set_target_width(
            layout.vowel_chart_width(layout.SEG_MIN_W)
        )
        # Consonants take stretch so they fan out across whatever
        # width the seg pane has; vowels stay at their target width.
        self._seg_h_pair.addWidget(left_wrap, stretch=1)
        self._seg_h_pair.addWidget(
            self.vowel_chart_widget,
            stretch=0,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        seg_content_layout.addLayout(self._seg_h_pair, stretch=1)
        # Tracks whether the chart is currently in the bottom-stacked
        # slot (True) or the right-side slot (False). Flipped by
        # ``_on_seg_pane_width_changed``.
        self._seg_vowels_stacked: bool = False
        self._seg_content_layout = seg_content_layout
        self._seg_scroll.setWidget(seg_content)
        vp = self._seg_scroll.viewport()
        assert vp is not None
        set_css(vp, "background: transparent;")
        vlay.addWidget(self._seg_scroll, stretch=1)
        # Sources the same "no inventory" text both UIs use; the
        # left arrow is desktop-only decoration that points at the
        # dropdown to the left of the seg pane.
        self.seg_hint = QLabel(
            "\u2190 " + mode_status_text(Mode.SEG_TO_FEAT, has_engine=False)
        )
        self.seg_hint.setFont(QFont("Noto Sans", 9))
        set_css(self.seg_hint, f"color: {C['text_dim']};")
        self.seg_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vlay.addWidget(self.seg_hint)
        return container

    def _build_feature_panel(self, parent: QWidget | None = None) -> QFrame:
        container = QFrame(parent)
        container.setObjectName("feat_panel")
        set_css(container, ModeController.panel_chrome_qss("feat_panel"))
        # Width floor + stretch policy from the constraint table. The
        # hsplit applies the panel's ``FEAT_MIN_W`` separately (at the
        # splitter-add site) so a future ``setMinimumWidth(0)`` reset
        # for a drag operation doesn't silently let cards crush; the
        # policy keeps the panel "Preferred" so it absorbs leftover
        # width up to the splitter handle.
        _fp = layout.REGION_CONSTRAINTS["feature_panel"]
        container.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        container.setMinimumHeight(_fp.min_h)
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
        set_css(self.clear_feat_btn, _clear_btn_style())
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
        set_css(self._feat_content, "background: transparent;")
        feat_main_layout = QHBoxLayout(self._feat_content)
        feat_main_layout.setContentsMargins(0, 0, 0, 0)
        feat_main_layout.setSpacing(8)
        self._feat_left_col = QWidget(self._feat_content)
        set_css(self._feat_left_col, "background: transparent;")
        self._feat_left_layout = QVBoxLayout(self._feat_left_col)
        self._feat_left_layout.setContentsMargins(0, 0, 0, 0)
        self._feat_left_layout.setSpacing(8)
        self._feat_left_layout.addStretch()
        self._feat_right_col = QWidget(self._feat_content)
        set_css(self._feat_right_col, "background: transparent;")
        self._feat_right_layout = QVBoxLayout(self._feat_right_col)
        self._feat_right_layout.setContentsMargins(0, 0, 0, 0)
        self._feat_right_layout.setSpacing(8)
        self._feat_right_layout.addStretch()
        feat_main_layout.addWidget(self._feat_left_col, stretch=1)
        feat_main_layout.addWidget(self._feat_right_col, stretch=1)
        self._feat_scroll.setWidget(self._feat_content)
        vlay.addWidget(self._feat_scroll, stretch=1)
        return container

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        if not self._did_first_show:
            self._did_first_show = True
            QTimer.singleShot(0, self._geom.ensure_visible_on_screen)

    def moveEvent(self, event: QMoveEvent | None) -> None:
        """Forward to the geometry controller so it can update its
        anchor (only on user-initiated moves; programmatic geometry
        changes are guarded inside the controller)."""
        super().moveEvent(event)
        self._geom.on_user_move(self.pos())

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Default resize handling. The vsplit absorbs any extra
        height via its own stretch factors; nothing for MainWindow
        to do beyond delegating."""
        super().resizeEvent(event)

    def _read_setting(self, key: str, default: Any = None) -> Any:
        """Defensive QSettings read. Thin wrapper around the
        shared ``safe_read_setting`` helper; kept as an instance
        method so call sites don't have to plumb ``self._settings``."""
        return safe_read_setting(self._settings, key, default)

    def _read_setting_str(self, key: str, default: str) -> str:
        return safe_read_setting(
            self._settings, key, default, expected_type=str
        )

    def _restore_settings(self, startup_path: str | None) -> None:
        """Restore window size/position, splitter state, mode, and
        last inventory."""
        # Drop the old binary geometry blob: it encodes absolute
        # positions that can place the window off-screen after a
        # display configuration change.
        self._settings.remove("geometry")
        # expected_type guards against a hand-edited INI or a previous
        # schema putting a string / int / wrong shape under these keys.
        # Without the check ``size.width()`` would AttributeError-crash
        # startup; with the check the bad value falls back to default.
        size = safe_read_setting(
            self._settings, SettingsKey.WINDOW_SIZE, None, expected_type=QSize
        )
        pos = safe_read_setting(
            self._settings, SettingsKey.WINDOW_POS, None, expected_type=QPoint
        )
        screen = self._geom.target_screen()
        if size is not None:
            # Floor against MIN_FIRST_LAUNCH so a stale saved size
            # from a crashed mid-resize doesn't stick forever.
            w = max(size.width(), self._geom.MIN_FIRST_LAUNCH_W)
            h = max(size.height(), self._geom.MIN_FIRST_LAUNCH_H)
            self.resize(*self._geom.clamp_size_to_screen(w, h))
        else:
            # Fresh install: 75% of the primary screen.
            self.resize(*self._geom.default_window_size())
        self._geom.has_saved_size = True
        # Fall back to centering when the saved position would put the
        # window entirely off-screen. Stale geometry from a previous
        # monitor configuration would otherwise leave the user with
        # no visible window even though the app started cleanly.
        if pos is not None and self._geom.is_pos_visible(
            pos, self.width(), self.height()
        ):
            self.move(pos)
        elif screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        # Restore BEFORE the inventory load so fit_to_content sees
        # the saved-splitter flag and skips its content-derived
        # sizing. Returns False on empty/incompatible blob; the
        # first-launch path picks up.
        self._geom.has_saved_splitter = self._geom.restore_splitter_state()
        path = startup_path or safe_read_setting(
            self._settings, SettingsKey.LAST_INVENTORY, None, expected_type=str
        )
        if path and os.path.isfile(path):
            idx = self.inventory_combo.findData(path)
            if idx >= 0:
                self.inventory_combo.setCurrentIndex(idx)
            self._load_path(path)
        else:
            # Fresh install: auto-pick the first bundled .json (skip
            # the disabled placeholder at index 0) so the user opens
            # to a populated UI instead of a blank shell.
            for idx in range(1, self.inventory_combo.count()):
                auto_path = self.inventory_combo.itemData(idx)
                if auto_path and os.path.isfile(auto_path):
                    self.inventory_combo.setCurrentIndex(idx)
                    self._load_path(auto_path)
                    break
        # Mode stored as a plain string so it survives package renames
        # that would invalidate a pickled enum.
        saved_mode = self._read_setting_str(
            SettingsKey.MODE, Mode.SEG_TO_FEAT.value
        )
        if saved_mode in (Mode.SEG_TO_FEAT.value, Mode.FEAT_TO_SEG.value):
            self._set_mode(Mode(saved_mode))

    def closeEvent(self, event: QCloseEvent | None) -> None:
        # Stop pending timers before any Qt teardown. A click ~100 ms
        # before close otherwise leaves the debounce timer armed; its
        # slot then fires on a half-destroyed window. Calling stop()
        # is safe even if the timer is not active.
        self._debounce.stop()
        # Let the builder prompt for unsaved changes. Without this,
        # Qt parent-child cleanup destroys it without firing its
        # closeEvent and unsaved edits are silently dropped.
        if self._builder is not None and self._builder.isVisible():
            if not self._builder.close():
                if event is not None:
                    event.ignore()
                return
        self._settings.remove("geometry")
        if self.isMaximized() or self.isFullScreen():
            normal = self.normalGeometry()
            write_setting(
                self._settings, SettingsKey.WINDOW_POS, normal.topLeft()
            )
            write_setting(
                self._settings, SettingsKey.WINDOW_SIZE, normal.size()
            )
        else:
            write_setting(self._settings, SettingsKey.WINDOW_POS, self.pos())
            write_setting(self._settings, SettingsKey.WINDOW_SIZE, self.size())
        # Persist splitter state so reopening + inventory swaps don't
        # snap the panel boundary back to the content-derived ratio.
        # Stored as the Qt-native QByteArray from ``saveState`` so the
        # round-trip matches Qt's internal format exactly.
        write_setting(
            self._settings, SettingsKey.HSPLIT_STATE, self._hsplit.saveState()
        )
        write_setting(
            self._settings, SettingsKey.VSPLIT_STATE, self._vsplit.saveState()
        )
        write_setting(
            self._settings, SettingsKey.MODE, self._mode_ctrl.mode.value
        )
        if self._current_path:
            write_setting(
                self._settings, SettingsKey.LAST_INVENTORY, self._current_path
            )
        # Flush settings to disk synchronously. Without sync(), a hard
        # process exit between the setValue calls and QSettings'
        # destructor can lose the last update (window geometry,
        # last_inventory, theme).
        self._settings.sync()
        super().closeEvent(event)

    def _on_inventory_selected(self, index: int) -> None:
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

    def _open_builder(self) -> None:
        """Open (or raise) the Builder window. Edits the current
        inventory in place if one is loaded; otherwise shows the
        new-inventory setup dialog.

        The Builder is window-modal against MainWindow: while it's
        open the user can't interact with the visualizer (in
        particular, can't toggle the theme). The Builder's own
        palette-dependent chrome doesn't get rebuilt on theme
        changes, so blocking those changes while it's up avoids
        the half-restyled state.
        """
        if self._builder is not None and self._builder.isVisible():
            self._builder.raise_()
            self._builder.activateWindow()
            return
        # Drop any stale (closed-but-not-yet-deleted) reference
        # before constructing the new builder. Without this the old
        # instance's _save_finished connection lingers alongside the
        # new one's, and a save fires the handler twice.
        if self._builder is not None:
            self._builder.deleteLater()
            self._builder = None

        from phonology_features.gui.builder import InventoryBuilder

        if self._current_path:
            builder = InventoryBuilder(
                parent=self, load_path=self._current_path
            )
        else:
            builder = InventoryBuilder(parent=self)
            if not builder.show_setup_dialog():
                builder.deleteLater()
                return

        builder.setWindowFlag(Qt.WindowType.Window)
        builder.setWindowModality(Qt.WindowModality.WindowModal)
        builder._save_finished.connect(self._on_builder_save_finished)
        # When Qt destroys the builder, clear the field so the next
        # open creates a fresh instance instead of resurrecting a
        # dangling pointer.
        builder.destroyed.connect(self._on_builder_destroyed)
        self._builder = builder
        self._builder.show()

    def _on_builder_destroyed(self, _obj: object) -> None:
        """Reset the cached builder reference when Qt finishes
        destroying it. Connected by :py:meth:`_open_builder`."""
        self._builder = None

    def _on_builder_save_finished(self, path: str, err: str) -> None:
        """When the builder finishes a save, switch the main viewer to
        the freshly-saved file if it's not already the current one.

        Covers the "user just authored a new inventory in the builder"
        case (current_path was None) and the "Save As to a different
        path" case. For saves to the SAME path the user is already
        viewing, the directory watcher's auto-reload handles it --
        explicit reload here would clear the user's analysis state
        twice for no benefit.
        """
        if err:
            return  # builder already showed its own error dialog
        if path == self._current_path:
            return  # same-path save -> watcher will refresh
        if os.path.isfile(path):
            _log.info(
                "switching to inventory saved from builder: %s",
                os.path.basename(path),
            )
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        """Load an inventory JSON. Shared by the dropdown, Browse, and
        the file-system watcher's auto-reload path. One try/except
        handles every failure mode because ``Inventory.load`` wraps
        ``OSError`` and ``JSONDecodeError`` as ``ValidationError``."""
        path = os.path.abspath(path)
        fname = os.path.basename(path)
        _log.info("load path: %s", fname)
        try:
            inventory = Inventory.load(path)
        except ValidationError as e:
            # Inventory.load already logged the failure category; here
            # we just record what the GUI did about it.
            _log.info("surfacing validation error to user: %s", fname)
            self.status.showMessage(
                inventory_load_failure_message(fname=fname, issue=e.issues[0])
            )
            self.analysis.set_html(render_validation_report(e.issues))
            return
        # Swap engines: grouping/normalization caches live on the
        # engine (cached_property), so a new engine = fresh caches.
        # No manual invalidation needed.
        self.engine = FeatureEngine(inventory)
        name = inventory.name
        base_msg = inventory_loaded_message(
            name=name,
            n_segments=len(self.engine.segments),
            n_features=len(self.engine.features),
        )
        if inventory.advisories:
            # Show the first advisory inline; the rest go to the log so
            # we don't truncate or wrap the status bar. Empty for every
            # bundled inventory.
            self.status.showMessage(
                f"{base_msg} Note: {inventory.advisories[0]}"
            )
            for note in inventory.advisories:
                _log.info("inventory advisory: %s: %s", fname, note)
        else:
            self.status.showMessage(base_msg)
        self._inv_dir.register_loaded_path(path)
        self._populate_after_load()

    def _populate_after_load(self) -> None:
        """Rebuild segment + feature widgets for the freshly-loaded engine.
        Startup runs ``_geom.fit_to_content`` synchronously so the
        first paint is already at the right size; runtime swaps defer
        one event-loop tick so pending paints drain before we resize.
        """
        self._mode_ctrl.saved_seg_state = []
        self._mode_ctrl.saved_feat_state = {}
        with self._batched_updates():
            self._populate_segments()
            self._populate_features()
            self._mode_ctrl.apply_to_new_widgets()
            self.analysis.clear()
        if self.isVisible():
            QTimer.singleShot(0, self._geom.fit_to_content)
        else:
            self._geom.fit_to_content()

    def _populate_segments(self) -> None:
        """Populate the seg grid + vowel chart from the active engine.
        Reuses pooled SegmentButtons where possible; detaches pool
        entries not in the current inventory.
        """
        if self.engine is None:
            return
        self._selected_segments.clear()
        self.seg_hint.hide()
        # grouped_segments/normalized_segment_feats are cached_property
        # on the engine itself, so swapping engines (in _load_path)
        # automatically invalidates them.
        groups = dict(self.engine.grouped_segments)  # shallow; pop mutates
        norm_feats = self.engine.normalized_segment_feats
        # Case-insensitive lookup so an inventory with "vowels" or
        # "VOWELS" still gets routed to the IPA chart. Matches the
        # web bridge's _summarize_engine behaviour.
        vowel_key = next(
            (k for k in groups if k.lower() == "vowels"),
            None,
        )
        vowel_segs = groups.pop(vowel_key, []) if vowel_key else []
        consonant_buttons: dict[str, SegmentButton] = {}
        for segs in groups.values():
            for seg in segs:
                consonant_buttons[seg] = self._get_or_create_seg_button(seg)
        self.seg_grid_widget.set_groups(groups, consonant_buttons)
        vowel_buttons: dict[str, SegmentButton] = {}
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

    def _get_or_create_seg_button(self, seg: str) -> SegmentButton:
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
            btn.right_clicked.connect(self._on_segment_right_clicked)
            self._seg_button_pool[seg] = btn
            return btn
        # Refresh theme on pool reuse: theme toggles skip orphaned
        # entries, so a pooled button may carry stylesheets from a
        # prior palette. No-op when already current.
        btn.apply_theme()
        btn.setChecked(False)
        btn.set_state(SegmentState.DEFAULT)
        btn.setToolTip("")
        return btn

    def _build_feature_group(
        self, title: str, features: list[str]
    ) -> QFrame | None:
        """Build one labelled group card. Returns None if no features
        in this group are active in the current inventory. Parented to
        the left-column container; ``_redistribute_feature_cards`` will
        re-parent to whichever column the LPT balancer picks.
        """
        active = [f for f in features if f in self._feat_rows]
        if not active:
            return None
        group_frame = _ThemedCard(self._feat_left_col)
        glay = QVBoxLayout(group_frame)
        glay.setContentsMargins(0, 6, 0, 6)
        glay.setSpacing(1)
        title_label = QLabel(title)
        title_label.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        # Static styling once; color comes from QPalette so theme
        # changes only need setPalette (no setStyleSheet polish).
        title_label.setStyleSheet(
            "letter-spacing: 1px; background: transparent;"
            " border: none; padding: 0 8px 2px 8px;"
        )
        self._apply_title_palette(title_label)
        glay.addWidget(title_label)
        for feat in active:
            glay.addWidget(self._feat_rows[feat])
        return group_frame

    @staticmethod
    def _apply_title_palette(label: QLabel) -> None:
        """Set the card-title color via QPalette (live ``text_dim``)."""
        pal = label.palette()
        pal.setColor(QPalette.ColorRole.WindowText, QColor(C["text_dim"]))
        label.setPalette(pal)

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
        active_feature_set: set[str] = set()
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

    def _redistribute_feature_cards(self, active: set[str]) -> None:
        """Place cards in left/right columns using soft pins + LPT.
        Re-runs on every inventory load because card heights vary
        with the active feature count.

        Placement is delegated to
        :py:func:`phonology_shared.presentation.layout.distribute_feature_groups`
        so the web app uses the same algorithm via Pyodide. This
        function only does the Qt-specific work: clear and refill
        the column layouts and toggle card visibility.
        """
        self._take_cards_out_of_columns()
        cards_by_title: dict[str, QFrame] = {}
        sizes: dict[str, int] = {}
        for card, feats in self._feat_cards:
            n_active = sum(1 for f in feats if f in active)
            title = self._card_title(card)
            if not title:
                continue
            cards_by_title[title] = card
            sizes[title] = n_active
            card.setVisible(n_active > 0)
        if self._other_card is not None:
            other_title = self._card_title(self._other_card) or "Other"
            n_active = sum(1 for f in active if f not in self._feat_row_pool)
            cards_by_title[other_title] = self._other_card
            sizes[other_title] = n_active
            self._other_card.setVisible(n_active > 0)
        group_order = [t for t, _ in FEATURE_GROUPS]
        if self._other_card is not None:
            other_title = self._card_title(self._other_card) or "Other"
            if other_title not in group_order:
                group_order.append(other_title)
        left_names, right_names = distribute_feature_groups(
            sizes, group_order=group_order
        )
        for name in left_names:
            self._feat_left_layout.addWidget(cards_by_title[name])
        for name in right_names:
            self._feat_right_layout.addWidget(cards_by_title[name])
        self._feat_left_layout.addStretch()
        self._feat_right_layout.addStretch()

    def _take_cards_out_of_columns(self) -> None:
        """Empty both column layouts. Card widgets stay alive (held by
        ``_feat_cards`` / ``_other_card``); spacer items get released.
        """
        for col_layout in (self._feat_left_layout, self._feat_right_layout):
            while col_layout.count():
                col_layout.takeAt(0)

    @staticmethod
    def _card_title(card: QFrame) -> str:
        """Read the title text from a feature-group card. The card's
        first child is always a QLabel(title) per ``_build_feature_group``.
        """
        card_layout = card.layout()
        if card_layout is None or card_layout.count() == 0:
            return ""
        item = card_layout.itemAt(0)
        if item is None:
            return ""
        first = item.widget()
        if first is not None and hasattr(first, "text"):
            return cast(str, first.text())
        return ""

    @contextmanager
    def _batched_updates(self) -> Iterator[None]:
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

    def _on_hsplit_moved(self, *_args: object) -> None:
        """Splitter-drag callback. Re-runs the seg-pane layout rules
        (vowel chart width + stack-vs-side-by-side) using the new
        seg-pane width. The widgets themselves don't re-measure on
        resize; width is pushed in from here, so a drag is one
        cheap layout invalidation instead of the per-pixel widget
        churn an earlier attempt produced.
        """
        sizes = self._hsplit.sizes()
        if not sizes:
            return
        self._on_seg_pane_width_changed(sizes[0])

    def _on_seg_pane_width_changed(self, seg_pane_w: int) -> None:
        """Apply the shared layout rules to the seg pane internals
        whenever the seg-pane width changes (initial layout, splitter
        drag, window resize, or inventory-load fit). Pure-Python
        decisions come from ``phonology_shared.presentation.layout``; this
        method just wires the results into Qt.

        Decisions delegated:
          * ``vowel_chart_width(seg_pane_w)`` → push into the chart
            via ``set_target_width``.
          * ``should_stack_vowels(seg_pane_w)`` → flip the chart
            between the side-by-side slot (right of consonants) and
            the bottom-stacked slot (under consonants). Run at most
            once per threshold crossing so a continuous drag doesn't
            churn the layout.

        Idempotent on same-width calls. The resize event filter
        fires this on every resizeEvent, including Qt's own internal
        layout passes; the early-return below keeps that cheap.
        """
        if seg_pane_w == self._last_seg_pane_w:
            return
        self._last_seg_pane_w = seg_pane_w
        target_w = layout.vowel_chart_width(seg_pane_w)
        self.vowel_chart_widget.set_target_width(target_w)
        should_stack = layout.should_stack_vowels(seg_pane_w)
        if should_stack == self._seg_vowels_stacked:
            return
        self._seg_vowels_stacked = should_stack
        # Move the chart between the two slots. ``QLayout.removeWidget``
        # detaches without reparenting; we re-add to the new container,
        # which is owned by the same parent widget either way.
        if should_stack:
            self._seg_h_pair.removeWidget(self.vowel_chart_widget)
            # Insert at index 1, directly under the consonants pair,
            # before the trailing stretch.
            self._seg_content_layout.insertWidget(
                1,
                self.vowel_chart_widget,
                stretch=0,
                alignment=Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignTop,
            )
        else:
            self._seg_content_layout.removeWidget(self.vowel_chart_widget)
            self._seg_h_pair.addWidget(
                self.vowel_chart_widget,
                stretch=0,
                alignment=Qt.AlignmentFlag.AlignTop,
            )

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        """Activate the clicked panel on a press in its empty area,
        and keep the seg-pane-dependent layout state (vowel chart
        width, stack-vs-side-by-side flag) in sync whenever the seg
        panel changes width, not only on splitter drag.

        Installed on ``seg_panel`` / ``feat_panel`` only, so ``a0`` is
        always one of the two.
        """
        if a1 is None:
            return False
        # Width-change hook: any time the seg panel is resized (window
        # drag, splitter drag, programmatic resize, even the initial
        # show event), re-run the shared layout policy so the vowel
        # chart and stack flag stay aligned with the seg pane's
        # actual width. QSplitter's ``splitterMoved`` only fires on
        # user-drag, not on automatic stretch-factor redistribution,
        # so we hook the widget's own resize instead.
        if a0 is self.seg_panel and a1.type() == QEvent.Type.Resize:
            self._on_seg_pane_width_changed(self.seg_panel.width())
            return False
        if a1.type() != _QEVENT_MOUSE_BUTTON_PRESS:
            return False
        if a0 is self.seg_panel and self._mode_ctrl.mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)
        elif (
            a0 is self.feat_panel and self._mode_ctrl.mode != Mode.FEAT_TO_SEG
        ):
            self._set_mode(Mode.FEAT_TO_SEG)
        return False

    # State changes are immediate; analysis is debounced via _debounce.
    def _on_segment_clicked(self, segment: str, checked: bool) -> None:
        if self._mode_ctrl.mode != Mode.SEG_TO_FEAT:
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

    def _on_segment_right_clicked(self, segment: str) -> None:
        """Copy the segment symbol to the clipboard when the user
        right-clicks a segment button. Gated to ``Mode.SEG_TO_FEAT``
        because that's when the segments pane drives interaction; in
        FEAT_TO_SEG mode the buttons are display-only (matched /
        unmatched paint) and a right-click "copy" would surprise.

        Status-bar feedback confirms the copy so the user gets the
        same affordance they'd see from a Qt-style "Copied X" toast
        without us pulling in a transient overlay widget.
        """
        if self._mode_ctrl.mode != Mode.SEG_TO_FEAT:
            return
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        clipboard = app.clipboard()
        status = self.statusBar()
        if clipboard is None or status is None:
            return
        clipboard.setText(segment)
        status.showMessage(clipboard_copy_message(segment), 0)

    def _on_segment_pressed(self) -> None:
        """Mouse press on a segment button: switch to seg mode before
        the click signal lands.
        """
        if self._mode_ctrl.mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)

    def _on_feature_changed(self, feature: str, value: str) -> None:
        if self._mode_ctrl.mode != Mode.FEAT_TO_SEG:
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
        if self._mode_ctrl.mode != Mode.FEAT_TO_SEG:
            self._set_mode(Mode.FEAT_TO_SEG)

    def _run_pending_update(self) -> None:
        """Fired by the debounce timer; dispatches to the active mode."""
        with self._batched_updates():
            if self._mode_ctrl.mode == Mode.SEG_TO_FEAT:
                self._update_seg_to_feat()
            else:
                self._update_feat_to_seg()

    def _update_seg_to_feat(self) -> None:
        """Apply the SEG-mode summary to the panels. The shared
        ``summarize_segment_selection`` returns a total payload --
        every segment in ``segment_states``, every feature in
        ``feature_rows`` -- so the empty-selection case needs no
        special branch here; it's just the payload returned for an
        empty ``segs`` list. The web bridge path is the same shape.
        """
        if not self.engine:
            return
        summary = summarize_segment_selection(
            self.engine, self._selected_segments
        )
        for feat, row in self._feat_rows.items():
            state = summary["feature_rows"][feat]
            row.set_display(
                state["value"],
                bool(state["shared"]),
                contrastive=bool(state["contrastive"]),
                badge=state["badge"],
            )
        for seg, btn in self._seg_buttons.items():
            btn.set_state(summary["segment_states"][seg])
        self._apply_analysis_tabs(summary["analysis_tabs"])

    def _update_feat_to_seg(self) -> None:
        """Apply the FEAT-mode summary to the panels. Like
        :py:meth:`_update_seg_to_feat`, the shared helper returns a
        total payload for any input (including the empty spec), so
        there is no separate empty-selection branch."""
        if not self.engine:
            return
        summary = summarize_feature_query(self.engine, self._selected_features)
        for seg, btn in self._seg_buttons.items():
            btn.set_state(summary["segment_states"][seg])
        self._apply_analysis_tabs(summary["analysis_tabs"])

    def _apply_analysis_tabs(self, tabs: AnalysisTabsPayload) -> None:
        """Unpack the shared view-model's ``analysis_tabs`` payload
        into :py:meth:`AnalysisPanel.set_sections`. Required because
        the payload key ``"class"`` is a Python keyword and can't be
        used with ``**`` unpacking; otherwise this would be a
        one-liner.
        """
        self.analysis.set_sections(
            tabs["selection"],
            tabs["class"],
            tabs["features"],
            tabs["contrasts"],
            contrasts_enabled=tabs["contrasts_enabled"],
            class_state=tabs["class_state"],
        )

    def _clear_segments(self, silent: bool = False) -> None:
        """Either Clear button wipes both panes. See ``_reset_both_sides``."""
        self._reset_both_sides(silent)

    def _clear_features(self, silent: bool = False) -> None:
        """Either Clear button wipes both panes. See ``_reset_both_sides``."""
        self._reset_both_sides(silent)

    def _clear_then_activate_segs(self) -> None:
        """Clear button handler: empty the selection, snap to seg mode,
        render the empty-selection state.

        Clear is "make the selection empty", not a distinct UI state.
        The view-model's empty-selection payload produces the default
        placeholder text -- same shape as app launch -- so the post-
        clear analysis re-renders through the normal pipeline:
        :py:meth:`ModeController.apply_phases` schedules the deferred
        refresh on a mode change; the same-mode branch refreshes
        directly.
        """
        self._reset_both_sides(silent=False)
        if self._mode_ctrl.mode != Mode.SEG_TO_FEAT:
            self._set_mode(Mode.SEG_TO_FEAT)
        else:
            self._mode_ctrl.refresh_analysis()

    def _clear_then_activate_feats(self) -> None:
        """See :py:meth:`_clear_then_activate_segs`."""
        self._reset_both_sides(silent=False)
        if self._mode_ctrl.mode != Mode.FEAT_TO_SEG:
            self._set_mode(Mode.FEAT_TO_SEG)
        else:
            self._mode_ctrl.refresh_analysis()

    def _reset_both_sides(self, silent: bool) -> None:
        """Reset segments and features to their neutral state. Shared
        implementation behind both Clear buttons. "Clear means clear":
        the two panes are wired together, so each Clear wipes both.
        ``silent=True`` is the inventory-load path: visible selection
        resets but the saved cross-mode state survives (the user
        did not press Clear). The analysis pane is never wiped here;
        the caller's subsequent refresh re-renders the empty-selection
        state through the normal view-model pipeline, which is what
        produces the default placeholder text.
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
            self._mode_ctrl.saved_seg_state = []
            self._mode_ctrl.saved_feat_state = {}
