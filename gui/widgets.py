"""
gui/widgets.py
Reusable UI widgets: SegmentButton, FeatureRow, AnalysisPanel, SegmentGridWidget.
"""

import math
from enum import StrEnum
from typing import ClassVar

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.constants import BTN_GAP, BTN_W, SCROLLBAR_STYLE
from gui.palette import C

# ---------------------------------------------------------------------------
# SegmentButton
# ---------------------------------------------------------------------------


class SegmentState(StrEnum):
    """Visual state of a SegmentButton. StrEnum members compare equal to
    their string values, so existing comparisons against bare strings keep
    working transparently."""

    SELECTED = "selected"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    SUGGESTED = "suggested"
    DEFAULT = "default"


class SegmentButton(QPushButton):
    """Toggleable button for a single phonological segment."""

    # Pre-computed stylesheets — avoids f-string interpolation on every state change
    _STYLES: ClassVar[dict[SegmentState, str]] = {
        SegmentState.SELECTED: f"""
            QPushButton {{
                background-color: {C["seg_selected"]};
                color: #FFFFFF;
                border: 2px solid #1D4ED8;
                border-radius: 8px;
                font-weight: bold;
            }}
        """,
        SegmentState.MATCHED: f"""
            QPushButton {{
                background-color: {C["seg_matched"]};
                color: #FFFFFF;
                border: 2px solid #1D4ED8;
                border-radius: 8px;
                font-weight: bold;
            }}
        """,
        SegmentState.UNMATCHED: f"""
            QPushButton {{
                background-color: {C["seg_unmatched"]};
                color: {C["text_dim"]};
                border: 1px solid {C["border"]};
                border-radius: 8px;
            }}
        """,
        SegmentState.SUGGESTED: f"""
            QPushButton {{
                background-color: {C["accent_light"]};
                color: {C["accent"]};
                border: 1.5px dashed {C["accent"]};
                border-radius: 8px;
            }}
        """,
        SegmentState.DEFAULT: f"""
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
        self._state: SegmentState = SegmentState.DEFAULT
        self.setStyleSheet(self._STYLES[SegmentState.DEFAULT])

    def set_state(self, state: SegmentState | str) -> None:
        state = SegmentState(state)
        if self._state != state:
            self._state = state
            self.setStyleSheet(self._STYLES[state])


# ---------------------------------------------------------------------------
# FeatureRow
# ---------------------------------------------------------------------------


class FeatureRow(QWidget):
    """
    One feature row in the feature panel.

    In INTERACTIVE mode (Feat -> Seg): shows [+] [-] toggle buttons.
    In DISPLAY mode (Seg -> Feat): shows a coloured value badge.
    """

    value_changed = pyqtSignal(str, str)  # feature_name, value ('+'/'-'/'')

    # Pre-computed stylesheets for set_display() — avoids f-string per call
    _BADGE_CONTRASTIVE = (
        f"background: {C['accent_light']}; color: {C['accent']};"
        " border-radius: 4px; font-weight: bold;"
    )
    _NAME_CONTRASTIVE = f"color: {C['accent']}; font-weight: bold;"
    _ROW_CONTRASTIVE = f"background: {C['accent_light']}; border-radius: 6px;"

    _BADGE_NEUTRAL = f"background: {C['tag_gray']}; color: {C['tag_gray_text']}; border-radius: 4px;"
    _NAME_DIM = f"color: {C['text_dim']};"
    _ROW_TRANSPARENT = "background: transparent; border-radius: 6px;"

    _BADGE_PLUS = (
        f"background: {C['plus_bg']}; color: {C['plus']};"
        " border-radius: 4px; font-weight: bold;"
    )
    _ROW_PLUS = f"background: {C['shared_plus']}; border-radius: 6px;"

    _BADGE_MINUS = (
        f"background: {C['minus_bg']}; color: {C['minus']};"
        " border-radius: 4px; font-weight: bold;"
    )
    _ROW_MINUS = f"background: {C['shared_minus']}; border-radius: 6px;"

    _NAME_BOLD = f"color: {C['text']}; font-weight: bold;"

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
        btn.setStyleSheet(f"""
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
        """)

    def _on_click(self, polarity: str):
        if self._current_value == polarity:
            self._current_value = ""
            self.plus_btn.setChecked(False)
            self.minus_btn.setChecked(False)
        else:
            self._current_value = polarity
            self.plus_btn.setChecked(polarity == "+")
            self.minus_btn.setChecked(polarity == "-")
        self._apply_query_style(self._current_value)
        self.value_changed.emit(self.feature, self._current_value)

    def _apply_query_style(self, value: str) -> None:
        """Mirror the +/-/neutral row tinting used in seg-mode so the feat-mode
        query state is visually consistent with the seg-mode informational state.
        Badge styling is unchanged here; the badge is hidden while interactive.
        """
        if value == "+":
            self.setStyleSheet(self._ROW_PLUS)
            self.name_label.setStyleSheet(self._NAME_BOLD)
        elif value == "-":
            self.setStyleSheet(self._ROW_MINUS)
            self.name_label.setStyleSheet(self._NAME_BOLD)
        else:
            self.setStyleSheet(self._ROW_NEUTRAL)
            self.name_label.setStyleSheet(
                self._NAME_ACTIVE
                if self._panel_active
                else self._NAME_INACTIVE
            )

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
        Display a feature value in Seg->Feat mode.
        value: '+', '-', or '' (inapplicable / mixed across segments)
        shared: whether this value is consistent across all selected segs
        contrastive: True when segments split cleanly on + vs - for this feature
        """
        if contrastive:
            self.badge.setText("\u00b1")
            self.badge.setStyleSheet(self._BADGE_CONTRASTIVE)
            self.name_label.setStyleSheet(self._NAME_CONTRASTIVE)
            self.setStyleSheet(self._ROW_CONTRASTIVE)
        elif not value or not shared:
            self.badge.setText("\u00b7")
            self.badge.setStyleSheet(self._BADGE_NEUTRAL)
            self.name_label.setStyleSheet(self._NAME_DIM)
            self.setStyleSheet(self._ROW_TRANSPARENT)
        else:
            self.badge.setText(value)
            if value == "+":
                self.badge.setStyleSheet(self._BADGE_PLUS)
                self.setStyleSheet(self._ROW_PLUS)
            else:
                self.badge.setStyleSheet(self._BADGE_MINUS)
                self.setStyleSheet(self._ROW_MINUS)
            self.name_label.setStyleSheet(self._NAME_BOLD)

    def restore_value(self, value: str):
        """Silently restore a saved +/- value (no signal emitted)."""
        self._current_value = value
        self.plus_btn.setChecked(value == "+")
        self.minus_btn.setChecked(value == "-")
        self._apply_query_style(value)

    def set_panel_active(self, active: bool):
        self._panel_active = active

    _ROW_NEUTRAL = "background: transparent; border-radius: 6px;"
    _NAME_ACTIVE = f"color: {C['text']};"
    _NAME_INACTIVE = f"color: {C['text_dim']};"

    def reset(self) -> None:
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
        self.content.setStyleSheet(f"""
            QTextEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 8px;
            }}
        """ + SCROLLBAR_STYLE)
        self.content.setMinimumHeight(60)

        layout.addWidget(self.title)
        layout.addWidget(self.content)

    def set_html(self, html: str):
        self.content.setHtml(html)

    def clear(self) -> None:
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
      - If the largest group fits in one row  -> use exactly that many cols
        (every group in a single row, no scroll needed).
      - Otherwise -> target ceil(max_N / 2) cols so the largest group splits
        into two even rows; cap at max_possible_cols when the panel is narrow.
    """

    MAX_COLS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: dict = {}  # manner -> [seg, ...]
        self._buttons: dict = (
            {}
        )  # seg    -> SegmentButton  (owned by this widget)
        self._headers: list = []  # QLabel per manner group
        self._n_cols: int = 0  # column count currently in use

        self._grid = QGridLayout(self)
        self._grid.setSpacing(BTN_GAP)
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

    def _compute_n_cols(self) -> int:
        stride = BTN_W + BTN_GAP
        max_possible = min(
            max(1, (self.width() + BTN_GAP) // stride), self.MAX_COLS
        )
        if not self._groups:
            return max_possible
        max_N = max(len(segs) for segs in self._groups.values())
        if max_N <= max_possible:
            return max_N
        return max_possible

    def _do_relayout(self) -> None:
        n_cols = self._compute_n_cols()
        if n_cols == self._n_cols:
            return
        self._n_cols = n_cols

        # Remove all items from layout without deleting the widgets
        while self._grid.count():
            self._grid.takeAt(0)

        grid_row = 0
        hdr_iter = iter(self._headers)
        for segs in self._groups.values():
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
