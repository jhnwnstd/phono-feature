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
from PyQt6.QtGui import (
    QCursor,
    QFont,
    QGuiApplication,
    QScreen,
    QStandardItemModel,
)
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
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from engine.feature_engine import FeatureEngine
from engine.inventory_validator import validate_inventory
from engine.segment_grouper import group_segments
from gui.palette import C

# ---------------------------------------------------------------------------
# Colour palette (defined in gui/palette.py, re-exported here)
# ---------------------------------------------------------------------------


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

_BTN_W = 33  # SegmentButton fixed width  (must match setFixedSize in __init__)
_BTN_H = 26  # SegmentButton fixed height
_BTN_GAP = 4  # QGridLayout spacing
_VOWEL_LABEL_W = 72  # px — fits "Near-close" at 7pt with padding

# ---------------------------------------------------------------------------
# Canonical feature display order (linguistically motivated hierarchy)
# Features absent from this list appear at the end in their original order.
# ---------------------------------------------------------------------------

_FEATURE_ORDER: list = [
    # Major class
    "Syllabic",
    "Consonantal",
    "Sonorant",
    "Approximant",
    # Laryngeal
    "Voice",
    "SpreadGl",
    "ConstrGl",
    # Manner
    "Continuant",
    "Strident",
    "DelRel",
    "Nasal",
    "Lateral",
    "Trill",
    "Tap",
    "Click",
    # Place — LABIAL node + dependents
    "LABIAL",
    "Round",
    "Labiodental",
    # Place — CORONAL node + dependents
    "CORONAL",
    "Anterior",
    "Distributed",
    # Place — DORSAL node + dependents
    "DORSAL",
    "High",
    "Low",
    "Back",
    "Front",
    "Tense",
    # Pharyngeal / advanced tongue root
    "ConstrPharynx",
    "Pharyngeal",
    "ATR",
    # Prosodic
    "Long",
    "Stress",
    "Tone",
    "UpperRegister",
]

_FEATURE_ORDER_INDEX: dict = {f: i for i, f in enumerate(_FEATURE_ORDER)}

# Feature groups for the two-column panel layout.
# First 3 groups → left column; last 3 → right column.
_FEATURE_GROUPS: list = [
    ("Major Class", ["Syllabic", "Consonantal", "Sonorant", "Approximant"]),
    ("Laryngeal", ["Voice", "SpreadGl", "ConstrGl"]),
    (
        "Manner",
        [
            "Continuant",
            "Strident",
            "DelRel",
            "Nasal",
            "Lateral",
            "Trill",
            "Tap",
            "Click",
        ],
    ),
    (
        "Place",
        [
            "LABIAL",
            "Round",
            "Labiodental",
            "CORONAL",
            "Anterior",
            "Distributed",
            "DORSAL",
            "High",
            "Low",
            "Back",
            "Front",
        ],
    ),
    (
        "Tongue-Root / Pharyngeal",
        ["ConstrPharynx", "Pharyngeal", "ATR", "Tense"],
    ),
    ("Prosodic", ["Long", "Stress", "Tone", "UpperRegister"]),
]


def _sort_features(features: list) -> list:
    """Return features in canonical phonological order; unknowns trail in original order."""
    n = len(_FEATURE_ORDER)
    return sorted(features, key=lambda f: _FEATURE_ORDER_INDEX.get(f, n))


def _sort_spec(spec: dict) -> dict:
    """Return a feature bundle dict with keys in canonical phonological order."""
    return {f: spec[f] for f in _sort_features(list(spec.keys()))}


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

    # Pre-computed stylesheets — avoids f-string interpolation on every state change
    _STYLES: dict = {
        "selected": f"""
            QPushButton {{
                background-color: {C["seg_selected"]};
                color: #FFFFFF;
                border: 2px solid #1D4ED8;
                border-radius: 8px;
                font-weight: bold;
            }}
        """,
        "matched": f"""
            QPushButton {{
                background-color: {C["seg_matched"]};
                color: #FFFFFF;
                border: 2px solid #1D4ED8;
                border-radius: 8px;
                font-weight: bold;
            }}
        """,
        "unmatched": f"""
            QPushButton {{
                background-color: {C["seg_unmatched"]};
                color: {C["text_dim"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """,
        "suggested": f"""
            QPushButton {{
                background-color: {C["accent_light"]};
                color: {C["accent"]};
                border: 1.5px dashed {C["accent"]};
                border-radius: 8px;
            }}
        """,
        "default": f"""
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
        """,
    }

    def __init__(self, segment: str, parent=None):
        super().__init__(segment, parent)
        self.segment = segment
        self.setCheckable(True)
        self.setFixedSize(33, 26)
        self.setFont(QFont("Noto Sans", 9))
        self._state = "default"
        self.setStyleSheet(self._STYLES["default"])

    def set_state(self, state: str):
        if self._state != state:
            self._state = state
            self.setStyleSheet(self._STYLES[state])


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
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(4)

        self.name_label = QLabel(feature_name)
        self.name_label.setFont(QFont("Noto Sans", 10))
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.name_label.setStyleSheet(f"color: {C['text']};")

        self.plus_btn = QPushButton("+")
        self.plus_btn.setFixedSize(28, 24)
        self.plus_btn.setCheckable(True)
        self.plus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.plus_btn, "+")

        self.minus_btn = QPushButton("\u2212")
        self.minus_btn.setFixedSize(28, 24)
        self.minus_btn.setCheckable(True)
        self.minus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.minus_btn, "-")

        self.badge = QLabel("\u00b7")
        self.badge.setFixedSize(30, 24)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self.badge.hide()

        layout.addWidget(self.name_label)
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

    _BADGE_NEUTRAL = (
        f"background: {C['tag_gray']};"
        f" color: {C['tag_gray_text']}; border-radius: 4px;"
    )
    _ROW_NEUTRAL = "background: transparent; border-radius: 6px;"
    _NAME_ACTIVE = f"color: {C['text']};"
    _NAME_INACTIVE = f"color: {C['text_dim']};"

    def reset(self):
        self._current_value = ""
        self.plus_btn.setChecked(False)
        self.minus_btn.setChecked(False)
        self.badge.setText("\u00b7")
        self.badge.setStyleSheet(self._BADGE_NEUTRAL)
        self.name_label.setStyleSheet(
            self._NAME_ACTIVE if self._panel_active else self._NAME_INACTIVE
        )
        self.setStyleSheet(self._ROW_NEUTRAL)

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
        self.content.setMinimumHeight(60)

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

        # Allow the widget to shrink freely — prevents feedback loop where
        # grid content sets a minimum width that blocks resize.
        self.setMinimumWidth(0)

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

    MAX_COLS = 12

    def _compute_n_cols(self) -> int:
        stride = _BTN_W + _BTN_GAP
        max_possible = min(
            max(1, (self.width() + _BTN_GAP) // stride), self.MAX_COLS
        )
        if not self._groups:
            return max_possible
        max_N = max(len(segs) for segs in self._groups.values())
        if max_N <= max_possible:
            return max_N
        return max_possible

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
# VowelChartWidget — IPA-style vowel trapezoid
# ---------------------------------------------------------------------------

_VOWEL_HEIGHT: list = [
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
    ("Open-mid", "-", "-", "-"),
    ("Open", "-", "+", None),
]


def _vowel_grid_pos(feats: dict) -> tuple:
    """Return (row, col) for a vowel in the IPA chart grid.

    Columns: 0=front-unround, 1=front-round, 2=central-unround,
             3=central-round, 4=back-unround, 5=back-round.
    """
    hi = feats.get("high", "0")
    lo = feats.get("low", "0")
    tn = feats.get("tense") or feats.get("atr") or "0"
    fr = feats.get("front") or feats.get("coronal") or "0"
    bk = feats.get("back", "0")
    rn = feats.get("round", "0")

    row = 3
    for i, (_, h, l, t) in enumerate(_VOWEL_HEIGHT):
        if hi == h and lo == l and (t is None or tn == t):
            row = i
            break

    if fr == "+":
        col = 0 if rn != "+" else 1
    elif bk == "+":
        col = 4 if rn != "+" else 5
    else:
        col = 2 if rn != "+" else 3

    return row, col


class VowelChartWidget(QWidget):
    """Displays vowels in an IPA-style grid: height x backness x rounding."""

    _COL_HEADERS = ["Front", "Central", "Back"]
    _ROW_HEADERS = [label for label, *_ in _VOWEL_HEIGHT]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict = {}
        self._header_labels: list = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(_BTN_GAP)
        self._grid.setContentsMargins(0, 0, 8, 0)

    _HDR_ACTIVE = f"color: {C['text']};"
    _HDR_INACTIVE = f"color: {C['text_dim']};"
    _ROW_ACTIVE = f"color: {C['text']}; padding-right: 4px;"
    _ROW_INACTIVE = f"color: {C['text_dim']}; padding-right: 4px;"

    def set_headers_active(self, active: bool):
        hdr = self._HDR_ACTIVE if active else self._HDR_INACTIVE
        row = self._ROW_ACTIVE if active else self._ROW_INACTIVE
        for lbl, is_row in self._header_labels:
            lbl.setStyleSheet(row if is_row else hdr)

    def clear(self):
        """Remove all buttons and labels."""
        while self._grid.count():
            self._grid.takeAt(0)
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        for lbl, _ in self._header_labels:
            lbl.deleteLater()
        self._header_labels.clear()

    def set_vowels(self, segs: list, buttons: dict, norm_feats: dict):
        """Lay out vowel buttons in the IPA chart grid."""
        self.clear()
        self._buttons = buttons

        hdr_font = QFont("Noto Sans", 8, QFont.Weight.Bold)

        title = QLabel("VOWELS")
        title.setFont(hdr_font)
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
            " padding: 2px 2px 0 2px;"
        )
        self._grid.addWidget(title, 0, 0, 1, 7)
        self._header_labels.append((title, False))

        for ci, label in enumerate(self._COL_HEADERS):
            lbl = QLabel(label)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(lbl, 1, 1 + ci * 2, 1, 2)
            self._header_labels.append((lbl, False))

        occupied: dict = {}
        for seg in segs:
            feats = norm_feats.get(seg, {})
            r, c = _vowel_grid_pos(feats)
            occupied.setdefault((r, c), []).append(seg)

        grid_row = 2
        for ri, label in enumerate(self._ROW_HEADERS):
            if not any((ri, c) in occupied for c in range(6)):
                continue
            lbl = QLabel(label)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']}; padding-right: 4px;")
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lbl.setMinimumWidth(_VOWEL_LABEL_W - 4)
            max_stack = max(
                (len(occupied.get((ri, c), [])) for c in range(6)), default=1
            )
            self._grid.addWidget(lbl, grid_row, 0, max_stack, 1)
            self._header_labels.append((lbl, True))

            for ci in range(6):
                for si, seg in enumerate(occupied.get((ri, ci), [])):
                    btn = self._buttons.get(seg)
                    if btn:
                        btn.show()
                        self._grid.addWidget(btn, grid_row + si, 1 + ci)

            grid_row += max(1, max_stack)


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
        # Exact state of each mode when leaving it; projected into the other
        # mode as a convenience pre-fill on switch.
        self._saved_seg_state: list = []
        self._saved_feat_state: dict = {}
        self._current_path: Optional[str] = None
        self._did_first_show = False

        self.setWindowTitle("Language Doodad")
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
        assert isinstance(app, QApplication)
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

        builder_btn = QPushButton("Builder")
        builder_btn.setFont(QFont("Noto Sans", 10))
        builder_btn.setFixedHeight(32)
        builder_btn.setStyleSheet(
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

        # Match segment and feature content widths (including margins)
        _stride = _BTN_W + _BTN_GAP
        _seg_w = (
            SegmentGridWidget.MAX_COLS * _stride
            + 12
            + _VOWEL_LABEL_W
            + 6 * _stride
            + 28
        )
        splitter.setSizes([_seg_w + 30, 430])
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
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._seg_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._seg_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }" + _SCROLLBAR_STYLE
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
            _VOWEL_LABEL_W + 6 * (_BTN_W + _BTN_GAP)
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

    def _target_screen(self) -> Optional[QScreen]:
        """Return the screen under the cursor, falling back to primaryScreen."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        return QGuiApplication.screenAt(QCursor.pos()) or app.primaryScreen()

    def _ensure_visible_on_screen(self) -> None:
        """
        Run after the first show via QTimer so the WM has decorated the window.
        Clamps the framed window onto a real screen if it landed off-screen or
        was restored to a bad position.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        frame = self.frameGeometry()
        on_screen = any(s.geometry().intersects(frame) for s in app.screens())

        if on_screen and frame.width() >= 300 and frame.height() >= 200:
            self.raise_()
            self.activateWindow()
            return

        screen = self._target_screen()
        if screen is None:
            return

        avail = screen.availableGeometry()
        w = min(max(self.width(), 900), avail.width() - 40)
        h = min(max(self.height(), 680), avail.height() - 40)
        self.resize(w, h)

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

    def _restore_settings(self, startup_path: Optional[str]) -> None:
        """Restore window size/position, mode, and last inventory on launch."""
        # Drop the old binary geometry blob — it encodes absolute positions that
        # can place the window off-screen after a display config change.
        self._settings.remove("geometry")

        size = self._settings.value("window_size")
        pos = self._settings.value("window_pos")
        screen = self._target_screen()

        if size is not None:
            self.resize(size)
        else:
            # Width: consonant grid at MAX_COLS + vowel chart + features
            _stride = _BTN_W + _BTN_GAP
            _seg_w = (
                SegmentGridWidget.MAX_COLS * _stride
                + 12  # HBox spacing
                + _VOWEL_LABEL_W
                + 6 * _stride
                + 28
            )  # panel margins
            _feat_w = 430  # two feature columns + margins + buffer
            _default_w = (
                _seg_w + 30 + _feat_w + 1
            )  # +30 seg breathing room, +1 splitter
            _default_h = 950  # fits tallest feature set + analysis
            if screen is not None:
                avail = screen.availableGeometry()
                self.resize(
                    min(_default_w, max(900, avail.width() - 40)),
                    min(_default_h, max(680, avail.height() - 40)),
                )
            else:
                self.resize(_default_w, _default_h)

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

    def _open_builder(self):
        from gui.inventory_builder import InventoryBuilder

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

        # Cache grouping on the engine so auto-reload skips recomputation
        if not hasattr(self.engine, "_cached_groups"):
            from engine.segment_grouper import _normalize_feats

            self.engine._cached_groups = group_segments(self.engine.segments)
            self.engine._cached_norm_feats = {
                seg: _normalize_feats(self.engine.segments[seg])
                for seg in self.engine.segments
            }

        groups = dict(self.engine._cached_groups)  # shallow copy — pop mutates
        norm_feats = self.engine._cached_norm_feats
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
    ) -> Optional[QFrame]:
        """Build a labelled group card for the given features. Returns None if no features are active."""
        active = [f for f in features if f in self._feat_rows]
        if not active:
            return None

        group_frame = QFrame()
        group_frame.setStyleSheet(
            f"""
            QFrame {{
                background: {C["panel"]};
                border: 1px solid {C["border"]};
                border-radius: 7px;
            }}
        """
        )
        glay = QVBoxLayout(group_frame)
        glay.setContentsMargins(0, 6, 0, 6)
        glay.setSpacing(1)

        title_label = QLabel(title)
        title_label.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        title_label.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px; background: transparent; border: none; padding: 0 8px 2px 8px;"
        )
        glay.addWidget(title_label)

        for feat in active:
            glay.addWidget(self._feat_rows[feat])

        return group_frame

    def _populate_features(self):
        assert self.engine is not None

        active_feature_set = {
            f
            for f in self.engine.features
            if any(
                seg.get(f, "0") != "0" for seg in self.engine.segments.values()
            )
        }

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
        for _, feats in _FEATURE_GROUPS:
            grouped_features.update(feats)
        unknown_active = _sort_features(
            [f for f in active_feature_set if f not in grouped_features]
        )

        # Build cards and count active features per group
        all_groups = list(_FEATURE_GROUPS)
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

    def _rebalance_vsplit(self) -> None:
        """Size the top panel so segments/features don't need scrollbars.

        Priority: avoid scrollbars in the content panels.  The analysis
        panel gets whatever vertical space remains, down to a hard floor
        of ``_min_analysis_h``.
        """
        QApplication.processEvents()
        total = self._vsplit.height()
        if total <= 0:
            return

        feat_content = self._feat_scroll.widget()
        feat_h = feat_content.sizeHint().height() if feat_content else 0
        chrome = 80
        needed = feat_h + chrome

        # Give the top panel what it needs; analysis gets the rest.
        top_h = min(needed, total - self._min_analysis_h)
        top_h = max(top_h, 200)
        analysis_h = total - top_h

        self._vsplit.setSizes([top_h, analysis_h])

    def _apply_mode_to_new_widgets(self):
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
        self._feat_title.setStyleSheet(
            f"color: {C['text'] if not is_s2f else C['text_dim']}; letter-spacing: 1.5px;"
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

    def eventFilter(self, a0, a1):
        """Activate a panel on any mouse press anywhere inside it."""
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

            self._show_multi_segment_analysis(
                segs, common, contrastive, suggested
            )

    def _show_single_segment_analysis(self, seg: str, feats: dict):
        assert self.engine is not None
        plus_feats = _sort_features([f for f, v in feats.items() if v == "+"])
        minus_feats = _sort_features([f for f, v in feats.items() if v == "-"])

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

        is_nc, specs = self.engine.is_natural_class([seg])
        if not is_nc:
            # Expand to equivalence class: all segments identical except
            # for underspecified features (e.g. ŋ → {ŋ, ŋ+, ŋ˗}).
            non_zero = {f: v for f, v in feats.items() if v != "0"}
            equiv = self.engine.find_segments(
                non_zero, underspec_compatible=True
            )
            if len(equiv) > 1:
                is_nc, specs = self.engine.is_natural_class(equiv)
        if is_nc and specs:
            html += self._render_spec_list(specs)

        self.analysis.set_html(html)

    def _show_multi_segment_analysis(
        self, segs: list, common: dict, contrastive: dict, suggested: list
    ):
        assert self.engine is not None
        seg_tags = " ".join(self._tag(f"/{s}/", "blue") for s in segs)

        if common:
            c_tags = " ".join(
                self._tag(f"{v}{f}", "green" if v == "+" else "red")
                for f, v in _sort_spec(common).items()
            )
            common_html = f"<p><b>Shared features:</b><br>{c_tags}</p>"
        else:
            common_html = (
                f"<p><b>Shared features:</b>"
                f" <i style='color:{C['text_dim']}'>none</i></p>"
            )

        if contrastive:
            rows = []
            for feat in _sort_features(list(contrastive)):
                groups = contrastive[feat]
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
            # Check if segments differ only in underspecification (0 vs +/-)
            has_underspec_diff = False
            for feat in self.engine.features:
                vals = {self.engine.segments[s].get(feat, "0") for s in segs}
                if len(vals) > 1 and "0" in vals:
                    has_underspec_diff = True
                    break
            if has_underspec_diff:
                contrast_html = (
                    f"<p><b>Contrasting features:</b>"
                    f" <i style='color:{C['text_dim']}'>none \u2014 segments"
                    " differ only in underspecification</i></p>"
                )
            else:
                contrast_html = (
                    f"<p><b>Contrasting features:</b>"
                    f" <i style='color:{C['text_dim']}'>none \u2014 segments"
                    " are featurally identical</i></p>"
                )

        is_nc, specs = self.engine.is_natural_class(segs)
        spec_html = ""
        if is_nc:
            nc_html = f"<p><b>Natural class:</b> <span style='color:{C['plus']}'>Yes</span></p>"
            if not specs or not specs[0]:
                _univ = "\u2205 (universal \u2014 all segments)"
                spec_html = (
                    f"<p><b>Minimal specification:</b>"
                    f" {self._tag(_univ, 'gray')}</p>"
                )
            else:
                spec_html = self._render_spec_list(specs)
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
                    f" to complete the smallest shared-feature class:<br>{sug_tags}</p>"
                )
            else:
                nc_html = (
                    "<p><b>Natural class:</b>"
                    f" <span style='color:{C['minus']}'>No \u2014"
                    " these segments cannot be uniquely picked out by any"
                    " feature bundle in this inventory.</span></p>"
                )

        html = f"<p><b>Selected:</b> {seg_tags}</p>{nc_html}{common_html}{spec_html}{contrast_html}"
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
            for f, v in _sort_spec(feature_dict).items()
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

    def _render_spec_list(self, specs: list) -> str:
        """Render a deduplicated list of minimal specifications as HTML.

        Underspecified features (value "0") are hidden from display;
        specs that become identical after filtering are collapsed.
        """
        seen: set = set()
        rows: list = []
        for spec in specs:
            filtered = {f: v for f, v in _sort_spec(spec).items() if v != "0"}
            if not filtered:
                continue
            key = tuple(sorted(filtered.items()))
            if key in seen:
                continue
            seen.add(key)
            row_tags = " ".join(
                self._tag(f"{v}{f}", "green" if v == "+" else "red")
                for f, v in filtered.items()
            )
            rows.append(
                f"<span style='color:{C['text_dim']}'>{len(rows) + 1}.</span> {row_tags}"
            )
        if not rows:
            return ""
        if len(rows) == 1:
            content = rows[0].split("</span> ", 1)[1]
            return f"<p><b>Minimal specification:</b><br>{content}</p>"
        return (
            f"<p><b>Minimal specifications ({len(rows)}):</b><br>"
            + "<br>".join(rows)
            + "</p>"
        )

    def _reset_feature_display(self):
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
