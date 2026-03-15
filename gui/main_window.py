"""
gui/main_window.py
PyQt6 GUI for the Segment & Feature Engine.
"""

import math
import os
from typing import Optional

from PyQt6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QSettings,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QFont, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from engine.feature_engine import FeatureEngine
from engine.segment_grouper import group_segments

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

C = {
    "bg": "#F0F2F5",
    "panel": "#FFFFFF",
    "border": "#D0D5DD",
    "accent": "#2563EB",
    "accent_light": "#DBEAFE",
    "seg_default": "#F8FAFC",
    "seg_selected": "#2563EB",
    "seg_matched": "#2563EB",
    "seg_unmatched": "#E2E8F0",
    "plus": "#15803D",
    "plus_bg": "#DCFCE7",
    "minus": "#B91C1C",
    "minus_bg": "#FEE2E2",
    "shared_plus": "#DCFCE7",
    "shared_minus": "#FEE2E2",
    "text": "#1E293B",
    "text_dim": "#94A3B8",
    "analysis_bg": "#F8FAFC",
    "tag_blue": "#DBEAFE",
    "tag_blue_text": "#1D4ED8",
    "tag_green": "#DCFCE7",
    "tag_green_text": "#15803D",
    "tag_red": "#FEE2E2",
    "tag_red_text": "#B91C1C",
    "tag_gray": "#F1F5F9",
    "tag_gray_text": "#64748B",
}

_SETTINGS_ORG = "features"
_SETTINGS_APP = "SegFeatureEngine"

_TAG_PALETTES = {
    "blue": (C["tag_blue"], C["tag_blue_text"]),
    "green": (C["tag_green"], C["tag_green_text"]),
    "red": (C["tag_red"], C["tag_red_text"]),
    "gray": (C["tag_gray"], C["tag_gray_text"]),
}

# ---------------------------------------------------------------------------
# Segment button geometry
# ---------------------------------------------------------------------------

_BTN_W = 40  # SegmentButton fixed width  (must match setFixedSize in __init__)
_BTN_H = 32  # SegmentButton fixed height
_BTN_GAP = 4  # QGridLayout spacing

# ---------------------------------------------------------------------------
# Shared scrollbar style — thin, unobtrusive overlay track
# ---------------------------------------------------------------------------

_SCROLLBAR_STYLE = f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {C["border"]};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {C["text_dim"]};
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0;
        background: none;
        border: none;
    }}
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {C["border"]};
        border-radius: 3px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {C["text_dim"]};
    }}
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {{
        width: 0;
        background: none;
        border: none;
    }}
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {{
        background: none;
    }}
"""


# ---------------------------------------------------------------------------
# SegmentButton
# ---------------------------------------------------------------------------


class SegmentButton(QPushButton):
    """Toggleable button for a single phonological segment."""

    def __init__(self, segment: str, parent=None):
        super().__init__(segment, parent)
        self.segment = segment
        self.setCheckable(True)
        self.setFixedSize(40, 32)
        self.setFont(QFont("Noto Sans", 11))
        self._state = "default"
        self._apply_style()

    def set_state(self, state: str):
        """state: 'default' | 'selected' | 'matched' | 'unmatched' | 'suggested'"""
        if self._state != state:
            self._state = state
            self._apply_style()

    def _apply_style(self):
        s = self._state
        if s == "selected":
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {C["seg_selected"]};
                    color: #FFFFFF;
                    border: 2px solid #1D4ED8;
                    border-radius: 8px;
                    font-weight: bold;
                }}
            """
            )
        elif s == "matched":
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {C["seg_matched"]};
                    color: #FFFFFF;
                    border: 2px solid #1D4ED8;
                    border-radius: 8px;
                    font-weight: bold;
                }}
            """
            )
        elif s == "unmatched":
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {C["seg_unmatched"]};
                    color: {C["text_dim"]};
                    border: 1px solid {C["border"]};
                    border-radius: 8px;
                }}
            """
            )
        elif s == "suggested":
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {C["accent_light"]};
                    color: {C["accent"]};
                    border: 1.5px dashed {C["accent"]};
                    border-radius: 8px;
                }}
            """
            )
        else:
            self.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {C["seg_default"]};
                    color: {C["text"]};
                    border: 1.5px solid {C["border"]};
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    background-color: {C["accent_light"]};
                    border: 1.5px solid {C["accent"]};
                }}
                QPushButton:checked {{
                    background-color: {C["seg_selected"]};
                    color: white;
                    border: 2px solid #1D4ED8;
                    font-weight: bold;
                }}
            """
            )


# ---------------------------------------------------------------------------
# FeatureRow
# ---------------------------------------------------------------------------


class FeatureRow(QWidget):
    """
    One feature row in the feature panel.

    In INTERACTIVE mode (Feat → Seg): shows [+] [–] toggle buttons.
    In DISPLAY mode (Seg → Feat): shows a coloured value badge.
    """

    value_changed = pyqtSignal(str, str)  # feature_name, value ('+'/'-'/'')

    def __init__(self, feature_name: str, parent=None):
        super().__init__(parent)
        self.feature = feature_name
        self._current_value = ""
        self._interactive = True
        self._panel_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(6)

        self.name_label = QLabel(feature_name)
        self.name_label.setFont(QFont("Noto Sans", 10))
        self.name_label.setMinimumWidth(110)
        self.name_label.setStyleSheet(f"color: {C['text']};")

        self.plus_btn = QPushButton("+")
        self.plus_btn.setFixedSize(30, 26)
        self.plus_btn.setCheckable(True)
        self.plus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.plus_btn, "+")

        self.minus_btn = QPushButton("\u2212")
        self.minus_btn.setFixedSize(30, 26)
        self.minus_btn.setCheckable(True)
        self.minus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.minus_btn, "-")

        self.badge = QLabel("\u00b7")
        self.badge.setFixedSize(34, 26)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self.badge.hide()

        layout.addWidget(self.name_label)
        layout.addStretch()
        layout.addWidget(self.badge)
        layout.addWidget(self.plus_btn)
        layout.addWidget(self.minus_btn)

        self.plus_btn.clicked.connect(lambda: self._on_click("+"))
        self.minus_btn.clicked.connect(lambda: self._on_click("-"))

        self.setAutoFillBackground(True)
        self.setStyleSheet("background: transparent; border-radius: 6px;")

    def _style_btn(self, btn: QPushButton, polarity: str):
        active_bg = C["plus_bg"] if polarity == "+" else C["minus_bg"]
        active_text = C["plus"] if polarity == "+" else C["minus"]
        border = C["plus"] if polarity == "+" else C["minus"]
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {C["analysis_bg"]};
                color: {C["text_dim"]};
                border: 1.5px solid {C["border"]};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background: {active_bg};
                color: {active_text};
                border: 1.5px solid {border};
            }}
            QPushButton:checked {{
                background: {active_bg};
                color: {active_text};
                border: 2px solid {border};
                font-weight: bold;
            }}
        """
        )

    def _on_click(self, polarity: str):
        if self._current_value == polarity:
            self._current_value = ""
            self.plus_btn.setChecked(False)
            self.minus_btn.setChecked(False)
        else:
            self._current_value = polarity
            self.plus_btn.setChecked(polarity == "+")
            self.minus_btn.setChecked(polarity == "-")
        self.value_changed.emit(self.feature, self._current_value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_interactive(self, yes: bool):
        self._interactive = yes
        self.plus_btn.setVisible(yes)
        self.minus_btn.setVisible(yes)
        self.badge.setVisible(not yes)
        self.reset()

    def set_display(self, value: str, shared: bool, contrastive: bool = False):
        """
        Display a feature value in Seg→Feat mode.
        value: '+', '-', or '' (inapplicable / mixed across segments)
        shared: whether this value is consistent across all selected segs
        contrastive: True when segments split cleanly on + vs - for this feature
        """
        if contrastive:
            self.badge.setText("\u00b1")
            self.badge.setStyleSheet(
                f"background: {C['accent_light']}; color: {C['accent']};"
                " border-radius: 4px; font-weight: bold;"
            )
            self.name_label.setStyleSheet(
                f"color: {C['accent']}; font-weight: bold;"
            )
            self.setStyleSheet(
                f"background: {C['accent_light']}; border-radius: 6px;"
            )
        elif not value or not shared:
            self.badge.setText("\u00b7")
            self.badge.setStyleSheet(
                f"background: {C['tag_gray']};"
                f" color: {C['tag_gray_text']}; border-radius: 4px;"
            )
            self.name_label.setStyleSheet(f"color: {C['text_dim']};")
            self.setStyleSheet("background: transparent; border-radius: 6px;")
        else:
            self.badge.setText(value)
            if value == "+":
                self.badge.setStyleSheet(
                    f"background: {C['plus_bg']}; color: {C['plus']};"
                    " border-radius: 4px; font-weight: bold;"
                )
                self.setStyleSheet(
                    f"background: {C['shared_plus']}; border-radius: 6px;"
                )
            else:
                self.badge.setStyleSheet(
                    f"background: {C['minus_bg']}; color: {C['minus']};"
                    " border-radius: 4px; font-weight: bold;"
                )
                self.setStyleSheet(
                    f"background: {C['shared_minus']}; border-radius: 6px;"
                )
            self.name_label.setStyleSheet(
                f"color: {C['text']}; font-weight: bold;"
            )

    def restore_value(self, value: str):
        """Silently restore a saved +/- value (no signal emitted)."""
        self._current_value = value
        self.plus_btn.setChecked(value == "+")
        self.minus_btn.setChecked(value == "-")

    def set_panel_active(self, active: bool):
        self._panel_active = active

    def reset(self):
        self._current_value = ""
        self.plus_btn.setChecked(False)
        self.minus_btn.setChecked(False)
        # Neutral dot badge (visible in display mode, hidden in interactive)
        self.badge.setText("\u00b7")
        self.badge.setStyleSheet(
            f"background: {C['tag_gray']};"
            f" color: {C['tag_gray_text']}; border-radius: 4px;"
        )
        name_color = C["text"] if self._panel_active else C["text_dim"]
        self.name_label.setStyleSheet(f"color: {name_color};")
        self.setStyleSheet("background: transparent; border-radius: 6px;")

    @property
    def current_value(self) -> str:
        return self._current_value


# ---------------------------------------------------------------------------
# AnalysisPanel
# ---------------------------------------------------------------------------


class AnalysisPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {C['analysis_bg']}; border-top: 1px solid {C['border']};"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.title = QLabel("Analysis")
        self.title.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        self.title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
        )

        self.content = QTextEdit()
        self.content.setReadOnly(True)
        self.content.setFont(QFont("Noto Sans Mono", 10))
        self.content.setStyleSheet(
            f"""
            QTextEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 8px;
            }}
        """
            + _SCROLLBAR_STYLE
        )
        self.content.setFixedHeight(160)

        layout.addWidget(self.title)
        layout.addWidget(self.content)

    def set_html(self, html: str):
        self.content.setHtml(html)

    def clear(self):
        self.content.clear()


# ---------------------------------------------------------------------------
# SegmentGridWidget — fluid reflowing grid of segment buttons
# ---------------------------------------------------------------------------


class SegmentGridWidget(QWidget):
    """
    Lays out segment buttons in a QGridLayout whose column count is computed
    from the widget's current width on every resize.

    Column-count policy:
      - Compute max_possible_cols from available pixel width.
      - If the largest group fits in one row  → use exactly that many cols
        (every group in a single row, no scroll needed).
      - Otherwise → target ⌈max_N / 2⌉ cols so the largest group splits
        into two even rows; cap at max_possible_cols when the panel is narrow.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: dict = {}  # manner → [seg, ...]
        self._buttons: dict = (
            {}
        )  # seg    → SegmentButton  (owned by this widget)
        self._headers: list = []  # QLabel per manner group
        self._n_cols: int = 0  # column count currently in use

        self._grid = QGridLayout(self)
        self._grid.setSpacing(_BTN_GAP)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        # Debounce resize events so we don't thrash the layout during drags
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)
        self._resize_timer.timeout.connect(self._do_relayout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_groups(self, groups: dict, buttons: dict):
        """Replace all content.  Old buttons are deleted; new ones are shown."""
        # Remove everything from layout (widgets stay alive until deleteLater)
        while self._grid.count():
            self._grid.takeAt(0)

        # Delete previous buttons and headers
        for btn in self._buttons.values():
            btn.deleteLater()
        for hdr in self._headers:
            hdr.deleteLater()
        self._headers.clear()

        self._groups = groups
        self._buttons = buttons

        # Pre-create header labels (one per group); add to layout in _do_relayout
        for manner in groups:
            hdr = QLabel(manner.upper())
            hdr.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
            hdr.setStyleSheet(
                f"color: {C['text_dim']}; letter-spacing: 1px;"
                " padding: 4px 2px 1px 2px;"
            )
            hdr.setParent(self)
            self._headers.append(hdr)

        self._n_cols = 0  # force a full relayout
        self._do_relayout()

    def set_headers_active(self, active: bool):
        color = C["text"] if active else C["text_dim"]
        for hdr in self._headers:
            hdr.setStyleSheet(
                f"color: {color}; letter-spacing: 1px; padding: 4px 2px 1px 2px;"
            )

    # ------------------------------------------------------------------
    # Resize / layout
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def _compute_n_cols(self) -> int:
        stride = _BTN_W + _BTN_GAP
        max_possible = max(1, (self.width() + _BTN_GAP) // stride)
        if not self._groups:
            return max_possible
        max_N = max(len(segs) for segs in self._groups.values())
        if max_N <= max_possible:
            # Single row for every group — use exactly as many cols as needed
            return max_N
        # Even 2-row split for the widest group, bounded by available width
        return min(max_possible, math.ceil(max_N / 2))

    def _do_relayout(self):
        n_cols = self._compute_n_cols()
        if n_cols == self._n_cols:
            return
        self._n_cols = n_cols

        # Remove all items from layout without deleting the widgets
        while self._grid.count():
            self._grid.takeAt(0)

        grid_row = 0
        hdr_iter = iter(self._headers)
        for manner, segs in self._groups.items():
            hdr = next(hdr_iter)
            self._grid.addWidget(hdr, grid_row, 0, 1, n_cols)
            hdr.show()
            grid_row += 1

            for col_i, seg in enumerate(segs):
                btn = self._buttons[seg]
                self._grid.addWidget(
                    btn,
                    grid_row + col_i // n_cols,
                    col_i % n_cols,
                )
                btn.show()
            grid_row += math.ceil(len(segs) / n_cols)


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, startup_path: Optional[str] = None):
        super().__init__()
        self.engine: Optional[FeatureEngine] = None
        self._mode = "seg_to_feat"  # 'seg_to_feat' | 'feat_to_seg'
        self._seg_buttons: dict = {}  # segment → SegmentButton
        self._feat_rows: dict = {}  # feature  → FeatureRow
        self._selected_segments: list = []
        self._selected_features: dict = {}  # feature → '+'/'-'
        self._saved_seg_state: list = []  # preserved across mode switches
        self._saved_feat_state: dict = {}  # preserved across mode switches
        self._current_path: Optional[str] = None

        self.setWindowTitle("Segment & Feature Engine")
        self.setMinimumSize(900, 680)
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
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        self._build_ui()
        app = QApplication.instance()
        assert app is not None
        app.installEventFilter(self)
        self._set_mode("seg_to_feat")
        self._restore_settings(startup_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── toolbar ──────────────────────────────────────────────────
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
        """
        )
        self.addToolBar(toolbar)

        # Config dropdown
        self.config_combo = QComboBox()
        self.config_combo.setFont(QFont("Noto Sans", 10))
        self.config_combo.setFixedHeight(32)
        self.config_combo.setMinimumWidth(220)
        self.config_combo.setStyleSheet(
            f"""
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
        """
        )
        self._populate_config_dropdown()
        self.config_combo.activated.connect(self._on_config_selected)
        toolbar.addWidget(self.config_combo)

        # Browse button
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setFont(QFont("Noto Sans", 10))
        browse_btn.setFixedHeight(32)
        browse_btn.setStyleSheet(
            f"""
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
        )
        browse_btn.clicked.connect(self._browse_config)
        toolbar.addWidget(browse_btn)

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

        splitter.setSizes([560, 340])
        root.addWidget(splitter, stretch=1)

        # ── bottom: analysis ──────────────────────────────────────────
        self.analysis = AnalysisPanel()
        root.addWidget(self.analysis)

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
        self.clear_seg_btn.setStyleSheet(
            f"""
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
        """
        )
        self.clear_seg_btn.clicked.connect(self._clear_segments)

        header.addWidget(self._seg_title)
        header.addStretch()
        header.addWidget(self.clear_seg_btn)
        vlay.addLayout(header)

        self._seg_scroll = QScrollArea()
        self._seg_scroll.setWidgetResizable(True)
        self._seg_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._seg_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._seg_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._seg_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + _SCROLLBAR_STYLE
        )

        self.seg_grid_widget = SegmentGridWidget()
        self._seg_scroll.setWidget(self.seg_grid_widget)
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
        self.clear_feat_btn.setStyleSheet(
            f"""
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
        """
        )
        self.clear_feat_btn.clicked.connect(self._clear_features)

        header.addWidget(self._feat_title)
        header.addStretch()
        header.addWidget(self.clear_feat_btn)
        vlay.addLayout(header)

        self._feat_scroll = QScrollArea()
        self._feat_scroll.setWidgetResizable(True)
        self._feat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feat_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + _SCROLLBAR_STYLE
        )

        self.feat_list_widget = QWidget()
        self.feat_list_layout = QVBoxLayout(self.feat_list_widget)
        self.feat_list_layout.setContentsMargins(0, 0, 0, 0)
        self.feat_list_layout.setSpacing(3)
        self.feat_list_layout.addStretch()

        self._feat_scroll.setWidget(self.feat_list_widget)
        vlay.addWidget(self._feat_scroll, stretch=1)

        return container

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _restore_settings(self, startup_path: Optional[str]):
        """Restore window geometry, mode, and last inventory on launch."""
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

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
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("mode", self._mode)
        if self._current_path:
            self._settings.setValue("last_inventory", self._current_path)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _populate_config_dropdown(self):
        """Scan config/ directory and fill the dropdown."""
        config_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "config")
        )
        self.config_combo.clear()
        self.config_combo.addItem("Select inventory\u2026", userData=None)

        # Disable the placeholder row so it cannot be picked
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

    def _browse_config(self):
        """Open a file dialog and load the chosen JSON."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Phonological Inventory", "", "JSON Files (*.json)"
        )
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

    def _load_path(self, path: str):
        """Core loading logic shared by dropdown, browse, and auto-reload."""
        try:
            engine = FeatureEngine()
            engine.load_inventory(path)
            self.engine = engine
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

            # Persist for next launch
            self._settings.setValue("last_inventory", path)

            self._saved_seg_state = []
            self._saved_feat_state = {}
            self._populate_segments()
            self._populate_features()
            self._set_mode(self._mode)
            self.analysis.clear()
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

    def _do_auto_reload(self):
        """Reload the current inventory after the debounce period."""
        if self._current_path and os.path.isfile(self._current_path):
            self._load_path(self._current_path)
            fname = os.path.basename(self._current_path)
            self.status.showMessage(f"Auto-reloaded \u201c{fname}\u201d")

    # ------------------------------------------------------------------
    # Populate panels
    # ------------------------------------------------------------------

    def _populate_segments(self):
        assert self.engine is not None
        self._selected_segments.clear()
        self.seg_hint.hide()

        groups = group_segments(self.engine.segments)

        # Build fresh button dict — set_groups owns deletion of previous ones
        new_buttons: dict = {}
        for segs in groups.values():
            for seg in segs:
                btn = SegmentButton(seg)
                btn.clicked.connect(
                    lambda checked, s=seg: self._on_segment_clicked(s, checked)
                )
                new_buttons[seg] = btn

        self.seg_grid_widget.set_groups(groups, new_buttons)
        self._seg_buttons = new_buttons

    def _populate_features(self):
        assert self.engine is not None
        while self.feat_list_layout.count():
            item = self.feat_list_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._feat_rows.clear()
        self._selected_features.clear()

        active_features = [
            f
            for f in self.engine.features
            if any(
                seg.get(f, "0") != "0" for seg in self.engine.segments.values()
            )
        ]
        for feat in active_features:
            row = FeatureRow(feat)
            row.value_changed.connect(self._on_feature_changed)
            self._feat_rows[feat] = row

            card = QFrame()
            card.setStyleSheet(
                f"""
                QFrame {{
                    background: {C["panel"]};
                    border: 1px solid {C["border"]};
                    border-radius: 7px;
                }}
            """
            )
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(0, 0, 0, 0)
            card_lay.addWidget(row)
            self.feat_list_layout.addWidget(card)

        self.feat_list_layout.addStretch()

    # ------------------------------------------------------------------
    # Mode management
    # ------------------------------------------------------------------

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

        # Paint scroll viewport and content widget explicitly so no grey bleeds through
        seg_vp = self._seg_scroll.viewport()
        feat_vp = self._feat_scroll.viewport()
        assert seg_vp is not None and feat_vp is not None
        seg_vp.setStyleSheet(f"background: {seg_bg};")
        self.seg_grid_widget.setStyleSheet(f"background: {seg_bg};")
        feat_vp.setStyleSheet(f"background: {feat_bg};")
        self.feat_list_widget.setStyleSheet(f"background: {feat_bg};")

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
        self._feat_title.setStyleSheet(
            f"color: {C['text'] if not is_s2f else C['text_dim']}; letter-spacing: 1.5px;"
        )
        self.seg_grid_widget.set_headers_active(is_s2f)

        for row in self._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)

        _clear_active = (
            f"color: {C['text']}; background: transparent;"
            f" border: 1px solid {C['border']}; border-radius: 5px; padding: 0 10px;"
        )
        _clear_inactive = (
            f"color: {C['text_dim']}; background: transparent;"
            f" border: 1px solid {C['border']}; border-radius: 5px; padding: 0 10px;"
        )
        self.clear_seg_btn.setStyleSheet(
            f"QPushButton {{ {_clear_active if is_s2f else _clear_inactive} }}"
            f" QPushButton:hover {{ color: {C['text']}; background: {C['bg']}; }}"
        )
        self.clear_feat_btn.setStyleSheet(
            f"QPushButton {{ {_clear_active if not is_s2f else _clear_inactive} }}"
            f" QPushButton:hover {{ color: {C['text']}; background: {C['panel']}; }}"
        )

        self._clear_segments(silent=True)
        self._clear_features(silent=True)
        self.analysis.clear()

        # Restore the saved state for the mode we just entered
        if is_s2f and self._saved_seg_state:
            for seg in self._saved_seg_state:
                if seg in self._seg_buttons:
                    self._selected_segments.append(seg)
                    self._seg_buttons[seg].set_state("selected")
                    self._seg_buttons[seg].setChecked(True)
            if self._selected_segments:
                self._update_seg_to_feat()
        elif not is_s2f and self._saved_feat_state:
            for feat, val in self._saved_feat_state.items():
                if feat in self._feat_rows:
                    self._selected_features[feat] = val
                    self._feat_rows[feat].restore_value(val)
            if self._selected_features:
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

    def eventFilter(self, obj, event):
        """Activate a panel on any mouse press anywhere inside it."""
        if event.type() == QEvent.Type.MouseButtonPress:
            w = obj
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
        return False  # never consume the event

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

    def _run_pending_update(self):
        """Fired by the debounce timer; dispatches to the active mode."""
        if self._mode == "seg_to_feat":
            self._update_seg_to_feat()
        else:
            self._update_feat_to_seg()

    # ------------------------------------------------------------------
    # Seg → Feat logic
    # ------------------------------------------------------------------

    def _compute_contrastive(self, segs: list) -> dict:
        """
        Return {feature: {'+': [segs...], '-': [segs...]}} for every feature
        where at least one segment is '+' and at least one is '-'.
        Features where some segs have '0' and others have '+'/'-' are excluded;
        only clean binary splits count as contrast.
        """
        assert self.engine is not None
        result = {}
        for feat in self.engine.features:
            plus_segs = [
                s
                for s in segs
                if self.engine.segments[s].get(feat, "0") == "+"
            ]
            minus_segs = [
                s
                for s in segs
                if self.engine.segments[s].get(feat, "0") == "-"
            ]
            if plus_segs and minus_segs:
                result[feat] = {"+": plus_segs, "-": minus_segs}
        return result

    def _update_seg_to_feat(self):
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
            self._show_single_segment_analysis(segs[0], feats)
        else:
            common = self.engine.common_features(segs)
            contrastive = self._compute_contrastive(segs)
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
                nc_extension = self.engine.find_segments(common)
                suggested = [s for s in nc_extension if s not in selected_set]

            suggested_set = set(suggested)
            for seg, btn in self._seg_buttons.items():
                if seg not in selected_set:
                    btn.set_state(
                        "suggested" if seg in suggested_set else "default"
                    )

            self._show_multi_segment_analysis(segs, common, contrastive, suggested)

    def _show_single_segment_analysis(self, seg: str, feats: dict):
        plus_feats = [f for f, v in feats.items() if v == "+"]
        minus_feats = [f for f, v in feats.items() if v == "-"]

        plus_tags = " ".join(self._tag(f"+{f}", "green") for f in plus_feats)
        minus_tags = " ".join(
            self._tag(f"\u2212{f}", "red") for f in minus_feats
        )

        html = (
            f"<p><b style='color:{C['text']}'>/{seg}/</b>"
            f" &nbsp;\u2014&nbsp; full feature bundle:</p>"
            f"<p>{plus_tags}</p>"
            f"<p>{minus_tags}</p>"
        )
        self.analysis.set_html(html)

    def _show_multi_segment_analysis(
        self, segs: list, common: dict, contrastive: dict, suggested: list
    ):
        assert self.engine is not None
        seg_tags = " ".join(self._tag(f"/{s}/", "blue") for s in segs)

        if common:
            c_tags = " ".join(
                self._tag(f"{v}{f}", "green" if v == "+" else "red")
                for f, v in common.items()
            )
            common_html = f"<p><b>Shared features:</b><br>{c_tags}</p>"
        else:
            common_html = (
                f"<p><b>Shared features:</b>"
                f" <i style='color:{C['text_dim']}'>none</i></p>"
            )

        if contrastive:
            rows = []
            for feat, groups in contrastive.items():
                plus_segs = " ".join(
                    self._tag(f"/{s}/", "blue") for s in groups["+"]
                )
                minus_segs = " ".join(
                    self._tag(f"/{s}/", "blue") for s in groups["-"]
                )
                minus_sign = chr(8722)
                clr_plus = C["plus"]
                clr_minus = C["minus"]
                rows.append(
                    f"{self._tag(feat, 'gray')}"
                    f" <span style='color:{clr_plus};font-weight:bold'>+</span>"
                    f" {plus_segs}"
                    f" &nbsp;"
                    f" <span style='color:{clr_minus};font-weight:bold'>{minus_sign}</span>"
                    f" {minus_segs}"
                )
            contrast_html = (
                "<p><b>Contrasting features:</b><br>"
                + "<br>".join(rows)
                + "</p>"
            )
        else:
            contrast_html = (
                f"<p><b>Contrasting features:</b>"
                f" <i style='color:{C['text_dim']}'>none \u2014 segments"
                " are featurally identical</i></p>"
            )

        is_nc, spec = self.engine.is_natural_class(segs)
        if is_nc:
            if spec:
                spec_tags = " ".join(
                    self._tag(f"{v}{f}", "green" if v == "+" else "red")
                    for f, v in spec.items()
                )
            else:
                spec_tags = self._tag(
                    "\u2205 (universal \u2014 all segments)", "gray"
                )
            nc_html = (
                f"<p><b>Natural class:</b> <span style='color:{C['plus']}'>Yes</span></p>"
                f"<p><b>Minimal specification:</b><br>{spec_tags}</p>"
            )
        else:
            if suggested:
                sug_tags = " ".join(
                    self._tag(f"/{s}/", "gray") for s in suggested
                )
                nc_html = (
                    "<p><b>Natural class:</b>"
                    f" <span style='color:{C['minus']}'>No</span>"
                    f" \u2014 add {len(suggested)} segment"
                    f"{'s' if len(suggested) != 1 else ''}"
                    f" to complete the minimal natural class:<br>{sug_tags}</p>"
                )
            else:
                nc_html = (
                    "<p><b>Natural class:</b>"
                    f" <span style='color:{C['minus']}'>No \u2014"
                    " these segments cannot be uniquely picked out by any"
                    " feature bundle in this inventory.</span></p>"
                )

        html = f"<p><b>Selected:</b> {seg_tags}</p>{common_html}{contrast_html}{nc_html}"
        self.analysis.set_html(html)

    # ------------------------------------------------------------------
    # Feat → Seg logic
    # ------------------------------------------------------------------

    def _update_feat_to_seg(self):
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

        self._show_feat_to_seg_analysis(selected_feats, matching)

    def _show_feat_to_seg_analysis(self, feature_dict: dict, matching: list):
        assert self.engine is not None
        feat_tags = " ".join(
            self._tag(f"{v}{f}", "green" if v == "+" else "red")
            for f, v in feature_dict.items()
        )

        if matching:
            seg_tags = " ".join(self._tag(f"/{s}/", "blue") for s in matching)
            segs_html = f"<p><b>Matching segments ({len(matching)}):</b><br>{seg_tags}</p>"
        else:
            segs_html = (
                "<p><b>Matching segments:</b>"
                f" <i style='color:{C['text_dim']}'>none \u2014 no segment"
                " satisfies all selected features.</i></p>"
            )

        html = f"<p><b>Query:</b> {feat_tags}</p>{segs_html}"
        self.analysis.set_html(html)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tag(self, text: str, colour: str) -> str:
        """Render a coloured inline chip."""
        bg, fg = _TAG_PALETTES.get(colour, (C["tag_gray"], C["tag_gray_text"]))
        return (
            f"<span style='"
            f"background:{bg}; color:{fg}; border-radius:4px;"
            f" padding:2px 7px; margin:2px; font-family:monospace;"
            f" font-size:10pt;'>{text}</span>"
        )

    def _reset_feature_display(self):
        for row in self._feat_rows.values():
            row.reset()

    def _clear_segments(self, silent=False):
        self._selected_segments.clear()
        for btn in self._seg_buttons.values():
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
            row.reset()
        for btn in self._seg_buttons.values():
            btn.set_state("default")
        if not silent:
            self._saved_seg_state = []
            self._saved_feat_state = {}
            self.analysis.clear()
