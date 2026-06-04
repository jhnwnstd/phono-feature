"""Reusable GUI widgets: SegmentButton, FeatureRow, AnalysisPanel,
SegmentGridWidget. Each owns its own ``apply_theme`` for live theme
swaps; per-widget style dicts are cached per theme at class level.
"""

import math
from enum import StrEnum
from typing import ClassVar

from PyQt6.QtCore import QMimeData, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QFont, QResizeEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from phonology_features.gui._themed_style_cache import styles_for_active_theme
from phonology_features.gui.style_utils import (
    _LAST_HTML_ATTR,
    set_css,
    set_html,
)
from phonology_shared.presentation import layout as layout_mod
from phonology_shared.presentation.constants import (
    BTN_GAP,
    BTN_W,
    MONO_FAMILIES,
    scrollbar_style,
)
from phonology_shared.presentation.layout import (
    REGION_CONSTRAINTS,
    best_segment_n_cols,
    partition_groups_for_spillover,
)
from phonology_shared.presentation.mode_logic import expand_button_tooltip
from phonology_shared.presentation.palette import C
from phonology_shared.presentation.view_models import (
    NEUTRAL_BADGE,
    feature_row_badge,
)

# Per-button vertical stride used by ``SegmentGridWidget`` to estimate
# group natural heights ahead of Qt's own layout pass. The fixed values
# match what ``SegmentButton`` sets via ``setFixedSize(33, 26)`` and the
# 4-px row gap, plus the empirical 22-px header. Tweak together with
# the button / header style if either changes.
_SEG_BTN_H = 26
_SEG_HEADER_H = 22


def _class_state_stylesheet(class_state: str) -> str:
    """Compose the analysis pane's QTabBar stylesheet with an
    optional ``QTabBar::tab:first`` override that paints the Class
    tab green / red per the natural-class verdict. Shared by
    :py:class:`AnalysisPanel` and :py:class:`AnalysisPeekPopup` so
    both surfaces show the cue identically; previously they each
    had their own private copy and drifted on theme swaps.
    """
    base = f"""
        QTabWidget::pane {{
            border: 1px solid {C["border"]};
            border-radius: 6px;
        }}
        QTabBar::tab {{
            background: {C["bg"]};
            color: {C["text_dim"]};
            border: 1px solid {C["border"]};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 4px 14px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {C["panel"]};
            color: {C["text"]};
            font-weight: bold;
        }}
        QTabBar::tab:hover:!selected {{
            color: {C["text"]};
        }}
        QTabBar::tab:disabled {{
            color: {C["border"]};
        }}
    """
    if class_state == "natural":
        bg = C["plus_bg"]
        fg = C["plus"]
    elif class_state == "not_natural":
        bg = C["minus_bg"]
        fg = C["minus"]
    else:
        return base
    return base + f"""
        QTabBar::tab:first {{
            background: {bg};
            color: {fg};
        }}
        QTabBar::tab:first:selected {{
            background: {bg};
            color: {fg};
            font-weight: bold;
        }}
    """


class SegmentState(StrEnum):
    """Visual state of a SegmentButton."""

    SELECTED = "selected"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    SUGGESTED = "suggested"
    DEFAULT = "default"


class SegmentButton(QPushButton):
    """Toggleable button for a single phonological segment. Stylesheet
    dicts are cached per theme at class level so a 140-segment swap
    only does the f-string work once per theme; subsequent swaps back
    are a cache hit.
    """

    #: Emitted on right-click. MainWindow connects this to a clipboard
    #: copy handler so users can grab a segment symbol out of the grid
    #: without going through select-to-copy. Argument is ``self.segment``
    #: (the IPA string).
    right_clicked = pyqtSignal(str)

    # ``palette.theme_version`` -> styles dict, shared across
    # instances. Cache rebuild semantics live in
    # :py:func:`_themed_style_cache.styles_for_active_theme`; see
    # that module for the invalidation contract.
    _styles_cache: ClassVar[dict[int, dict[SegmentState, str]]] = {}

    @classmethod
    def _styles_for_active_theme(cls) -> dict[SegmentState, str]:
        return styles_for_active_theme(cls._styles_cache, cls._build_styles)

    def __init__(self, segment: str, parent: QWidget | None = None) -> None:
        super().__init__(segment, parent)
        self.segment = segment
        self._state: SegmentState = SegmentState.DEFAULT
        self.setCheckable(True)
        # Fixed dimensions are sourced from the constraint table so the
        # web (CSS ``--seg-btn-min-w`` / ``--seg-btn-min-h``) and the
        # desktop (here) pull from one entry. ``setSizePolicy(Fixed)``
        # is documentary: ``setFixedSize`` already pins both policies
        # to Fixed internally, but the explicit call makes the size
        # contract visible alongside the constraint citation.
        _seg_btn = REGION_CONSTRAINTS["seg_btn"]
        self.setFixedSize(
            _seg_btn.pref_w or _seg_btn.min_w,
            _seg_btn.pref_h or _seg_btn.min_h,
        )
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        # Apply the IPA-coverage font chain (same as the analysis pane)
        # so combining marks like the tie bar in d͡ʒ and ejectives
        # like pʼ render with the same glyphs everywhere they appear.
        # Using ``setFamilies`` keeps Qt's substitution rule intact;
        # the 9pt size matches the historic button typography.
        btn_font = QFont("Noto Sans", 9)
        btn_font.setFamilies(MONO_FAMILIES)
        self.setFont(btn_font)
        self._styles = self._styles_for_active_theme()
        set_css(self, self._styles[SegmentState.DEFAULT])

    def apply_theme(self) -> None:
        """Re-style against the active palette in place. Called by
        MainWindow on theme toggle so pooled buttons survive.

        Short-circuits when the cached theme dict is already the one
        we'd apply: ``_styles_cache`` returns the same dict instance
        for repeated requests in the same theme, so identity check
        is both correct and cheap. Lets the main theme loop safely
        call apply_theme on orphan pool entries without paying for
        widgets whose theme is already current.
        """
        new_styles = self._styles_for_active_theme()
        if new_styles is self._styles:
            return
        self._styles = new_styles
        set_css(self, self._styles[self._state])

    @staticmethod
    def _build_styles() -> dict[SegmentState, str]:
        return {
            SegmentState.SELECTED: f"""
                QPushButton {{
                    background-color: {C["seg_selected"]};
                    color: #FFFFFF;
                    border: 2px solid {C["accent"]};
                    border-radius: 8px;
                    font-weight: bold;
                }}
            """,
            SegmentState.MATCHED: f"""
                QPushButton {{
                    background-color: {C["seg_matched"]};
                    color: #FFFFFF;
                    border: 2px solid {C["accent"]};
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
                    color: #FFFFFF;
                    border: 2px solid {C["accent"]};
                    font-weight: bold;
                }}
            """,
        }

    def set_state(self, state: SegmentState | str) -> None:
        """Set the button's visual state. Accepts the enum or its string
        value; the isinstance check avoids an enum lookup on the hot
        mode-toggle path where most callers already pass the enum.
        """
        if isinstance(state, SegmentState):
            new_state = state
        else:
            new_state = SegmentState(state)
        if self._state == new_state:
            return
        self._state = new_state
        set_css(self, self._styles[new_state])

    def contextMenuEvent(self, event: QContextMenuEvent | None) -> None:
        """Emit ``right_clicked`` with the segment string. MainWindow
        decides whether to copy (only in SEG_TO_FEAT mode); doing the
        gating there keeps this button widget agnostic of the active
        UI mode.

        Overriding ``contextMenuEvent`` (rather than ``mousePressEvent``
        with a ``RightButton`` check) is the Qt-idiomatic way to react
        to right-click and additionally covers the keyboard /
        accessibility context-menu key. ``event.accept()`` suppresses
        the default no-op QPushButton context menu so the user doesn't
        see a phantom empty menu after the copy.
        """
        if event is not None:
            event.accept()
        self.right_clicked.emit(self.segment)


class FeatureRow(QWidget):
    """One feature row in the feature panel. Interactive mode shows
    +/- toggle buttons; display mode shows a coloured value badge.
    Style strings cached per theme at class level (see SegmentButton);
    ``apply_theme`` re-binds instance attrs on a live theme swap.
    """

    value_changed = pyqtSignal(str, str)
    # ``palette.theme_version`` -> styles dict (BADGE_*, ROW_*,
    # NAME_*). Shared invalidation contract with SegmentButton via
    # :py:func:`_themed_style_cache.styles_for_active_theme`.
    _styles_cache: ClassVar[dict[int, dict[str, str]]] = {}
    # Instance attrs populated by ``_build_styles`` via setattr from
    # the cached theme dict; declared here so mypy sees them.
    _BADGE_CONTRASTIVE: str = ""
    _NAME_CONTRASTIVE: str = ""
    _ROW_CONTRASTIVE: str = ""
    _BADGE_NEUTRAL: str = ""
    _NAME_DIM: str = ""
    _ROW_TRANSPARENT: str = ""
    _BADGE_PLUS: str = ""
    _ROW_PLUS: str = ""
    _BADGE_MINUS: str = ""
    _ROW_MINUS: str = ""
    _NAME_BOLD: str = ""
    _ROW_NEUTRAL: str = ""
    _NAME_ACTIVE: str = ""
    _NAME_INACTIVE: str = ""

    @classmethod
    def _styles_for_active_theme(cls) -> dict[str, str]:
        return styles_for_active_theme(cls._styles_cache, cls._compute_styles)

    def __init__(
        self, feature_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.feature = feature_name
        self._current_value = ""
        self._panel_active = False
        self._build_styles()
        # Dedup cache for set_display; cleared by reset / _apply_query_style
        # (both rewrite the same stylesheets without going through set_display).
        self._last_display_state: tuple[str, bool, bool] | None = None
        # Tracks the panel-active value the row was last reset for, so
        # repeat reset() calls during populate + mode-switch can
        # short-circuit. None forces the next reset to take the full path.
        self._reset_for_panel: bool | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(4)
        self.name_label = QLabel(feature_name, self)
        self.name_label.setFont(QFont("Noto Sans", 10))
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        set_css(self.name_label, f"color: {C['text']};")
        self.plus_btn = QPushButton("+", self)
        self.plus_btn.setFixedSize(28, 24)
        self.plus_btn.setCheckable(True)
        self.plus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.plus_btn, "+")
        self.minus_btn = QPushButton("\u2212", self)
        self.minus_btn.setFixedSize(28, 24)
        self.minus_btn.setCheckable(True)
        self.minus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.minus_btn, "-")
        self.badge = QLabel("\u00b7", self)
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
        set_css(self, self._ROW_NEUTRAL)

    def _build_styles(self) -> None:
        """Bind the active theme's style strings as instance attrs."""
        for k, v in self._styles_for_active_theme().items():
            setattr(self, f"_{k}", v)

    @staticmethod
    def _compute_styles() -> dict[str, str]:
        """Build all stylesheet strings against the *current* palette.

        Called once per theme; results are cached at class level
        (``_styles_cache``). The contrastive (``±``) badge reads
        from the ``neutral`` slot so colorblind mode can swap blue
        (which it reuses for "+") for purple without losing the
        familiar blue tint in standard mode (standard maps ``neutral``
        to the accent slot). The empty-state ``·`` badge stays gray
        in both modes; only the contrastive state changes hue.
        """
        return {
            "BADGE_CONTRASTIVE": (
                f"background: {C['neutral_bg']}; color: {C['neutral']};"
                " border-radius: 4px; font-weight: bold;"
            ),
            "NAME_CONTRASTIVE": f"color: {C['neutral']}; font-weight: bold;",
            "ROW_CONTRASTIVE": (
                f"background: {C['neutral_bg']}; border-radius: 6px;"
            ),
            "BADGE_NEUTRAL": (
                f"background: {C['tag_gray']}; color: {C['text_dim']};"
                " border-radius: 4px;"
            ),
            "NAME_DIM": f"color: {C['text_dim']};",
            "ROW_TRANSPARENT": "background: transparent; border-radius: 6px;",
            "BADGE_PLUS": (
                f"background: {C['plus_bg']}; color: {C['plus']};"
                " border-radius: 4px; font-weight: bold;"
            ),
            "ROW_PLUS": f"background: {C['shared_plus']}; border-radius: 6px;",
            "BADGE_MINUS": (
                f"background: {C['minus_bg']}; color: {C['minus']};"
                " border-radius: 4px; font-weight: bold;"
            ),
            "ROW_MINUS": (
                f"background: {C['shared_minus']}; border-radius: 6px;"
            ),
            "NAME_BOLD": f"color: {C['text']}; font-weight: bold;",
            "ROW_NEUTRAL": "background: transparent; border-radius: 6px;",
            "NAME_ACTIVE": f"color: {C['text']};",
            "NAME_INACTIVE": f"color: {C['text_dim']};",
        }

    def apply_theme(self) -> None:
        """Re-style this row against the active palette in place.

        A FeatureRow can be in one of three visual states:

        1. **Query mode**: the user clicked + or - on this row.
           ``_current_value`` is "+"/"-". The row background is tinted.
        2. **Display mode**: ``set_display`` painted the badge with a
           value derived from seg-mode analysis. ``_last_display_state``
           holds the args.
        3. **Neutral**: neither of the above. Badge shows "·" with the
           neutral palette colors. ``_last_display_state`` is None.

        Each state's visible styling was baked against the OLD palette
        and has to be re-applied. We handle the three cases explicitly
        rather than relying on a downstream caller (like the analysis
        update path) to refresh; that caller doesn't run when there
        are no selections, leaving neutral-state badges stale.

        Always re-styles the +/- buttons since they're visible in
        feat mode regardless of state.
        """
        saved_display = self._last_display_state
        saved_current_value = self._current_value
        self._build_styles()
        self._last_display_state = None
        self._reset_for_panel = None
        self._style_btn(self.plus_btn, "+")
        self._style_btn(self.minus_btn, "-")
        if saved_current_value:
            # State 1: query mode. Re-apply the +/- tint.
            self._apply_query_style(saved_current_value)
        elif saved_display is not None:
            # State 2: display mode. Replay the last set_display args
            # so the badge picks up the new palette.
            value, shared, contrastive = saved_display
            self.set_display(
                value,
                shared,
                contrastive=contrastive,
                badge=feature_row_badge(
                    value=value, shared=shared, contrastive=contrastive
                ),
            )
        else:
            # State 3: neutral. Directly re-apply the neutral styles
            # since neither of the above paths runs.
            set_css(self.badge, self._BADGE_NEUTRAL)
            self.badge.setText(NEUTRAL_BADGE)
            set_css(
                self.name_label,
                (
                    self._NAME_ACTIVE
                    if self._panel_active
                    else self._NAME_INACTIVE
                ),
            )
            set_css(self, self._ROW_NEUTRAL)
            self._reset_for_panel = self._panel_active

    def _style_btn(self, btn: QPushButton, polarity: str) -> None:
        is_plus = polarity == "+"
        active_bg = C["plus_bg"] if is_plus else C["minus_bg"]
        active_text = C["plus"] if is_plus else C["minus"]
        border = C["plus"] if is_plus else C["minus"]
        set_css(
            btn,
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
        """,
        )

    def _on_click(self, polarity: str) -> None:
        clicked_current_value = self._current_value == polarity
        if clicked_current_value:
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
        """Apply row tinting that matches the current query value.
        Invalidates both dedup caches since _on_click / restore_value
        bypass set_display and reset but rewrite the same stylesheets.
        """
        self._last_display_state = None
        self._reset_for_panel = None
        if value == "+":
            set_css(self, self._ROW_PLUS)
            set_css(self.name_label, self._NAME_BOLD)
            return
        if value == "-":
            set_css(self, self._ROW_MINUS)
            set_css(self.name_label, self._NAME_BOLD)
            return
        if self._panel_active:
            name_style = self._NAME_ACTIVE
        else:
            name_style = self._NAME_INACTIVE
        set_css(self, self._ROW_NEUTRAL)
        set_css(self.name_label, name_style)

    def set_interactive(self, yes: bool) -> None:
        # No need to stash ``yes`` on the instance: the +/- buttons'
        # visibility IS the source of truth for "interactive mode".
        # Anything that needs to query the state can check
        # plus_btn.isVisible().
        self.plus_btn.setVisible(yes)
        self.minus_btn.setVisible(yes)
        self.badge.setVisible(not yes)

    def set_display(
        self,
        value: str,
        shared: bool,
        contrastive: bool = False,
        *,
        badge: str,
    ) -> None:
        """Display a feature value in seg-to-feat mode.

        Args:
            value: "+", "-", or "" (empty when not shared).
            shared: all selected segments share this value.
            contrastive: selected segments split cleanly on this feature.
            badge: glyph from
                :py:func:`phonology_shared.presentation.view_models._feature_row_state`
                (`\u00b1` / `+` / U+2212 / `\u00b7`). Single source of truth so the
                desktop and web FeatureRow can never drift; QSS selection
                stays Qt-only below.
        """
        # Dedup: seg-mode updates re-run through every row even when the
        # state didn't change. Skip 3 setStyleSheet + 1 setText calls.
        state = (value, shared, contrastive)
        if self._last_display_state == state:
            return
        self._last_display_state = state
        self._reset_for_panel = None
        self.badge.setText(badge)
        if contrastive:
            set_css(self.badge, self._BADGE_CONTRASTIVE)
            set_css(self.name_label, self._NAME_CONTRASTIVE)
            set_css(self, self._ROW_CONTRASTIVE)
            return
        has_display_value = bool(value)
        if not has_display_value or not shared:
            set_css(self.badge, self._BADGE_NEUTRAL)
            set_css(self.name_label, self._NAME_DIM)
            set_css(self, self._ROW_TRANSPARENT)
            return
        set_css(self.name_label, self._NAME_BOLD)
        if value == "+":
            set_css(self.badge, self._BADGE_PLUS)
            set_css(self, self._ROW_PLUS)
        else:
            set_css(self.badge, self._BADGE_MINUS)
            set_css(self, self._ROW_MINUS)

    def restore_value(self, value: str) -> None:
        """Silently restore a saved plus or minus value."""
        self._current_value = value
        self.plus_btn.setChecked(value == "+")
        self.minus_btn.setChecked(value == "-")
        self._apply_query_style(value)

    def set_panel_active(self, active: bool) -> None:
        self._panel_active = active

    def reset(self) -> None:
        """Return the row to its neutral state. Three fast paths:
        1. Truly idempotent (value empty, no display dirt, panel
           matches): no-op.
        2. Clean-but-panel-changed: only name_label depends on the
           panel_active value when neutral, so rewrite just that.
        3. Visual-dirty, value non-empty, or ``_reset_for_panel is None``
           (the apply_theme sentinel meaning "palette may be stale,
           rebuild visible styles"): full reset.
        """
        visual_dirty = self._last_display_state is not None
        force_full = self._reset_for_panel is None
        if self._current_value == "" and not visual_dirty and not force_full:
            if self._reset_for_panel == self._panel_active:
                return
            name_style = (
                self._NAME_ACTIVE
                if self._panel_active
                else self._NAME_INACTIVE
            )
            set_css(self.name_label, name_style)
            self._reset_for_panel = self._panel_active
            return
        self._current_value = ""
        self._last_display_state = None
        self.plus_btn.setChecked(False)
        self.minus_btn.setChecked(False)
        self.badge.setText(NEUTRAL_BADGE)
        set_css(self.badge, self._BADGE_NEUTRAL)
        name_style = (
            self._NAME_ACTIVE if self._panel_active else self._NAME_INACTIVE
        )
        set_css(self.name_label, name_style)
        set_css(self, self._ROW_NEUTRAL)
        self._reset_for_panel = self._panel_active


class _CopyableTextEdit(QTextEdit):
    """``QTextEdit`` that normalises display-only characters back to
    their interchange forms at the clipboard boundary.

    The analysis pane renders feature minus values as U+2212 (`−`,
    MATHEMATICAL MINUS SIGN) for typographic symmetry with `+`. The
    rest of the ecosystem (JSON files, code, regex, most terminals)
    expects ASCII U+002D (`-`, HYPHEN-MINUS). Pasting `−Voice` into
    a JSON value silently does NOT match `"-"`.

    Translating at the copy boundary lets the display layer keep the
    nice typographic glyph and gives every paste target the byte
    they expect. Both the plain-text and HTML mime payloads get
    translated so rich-text targets (a doc editor) agree with
    plain-text targets (a code editor).
    """

    # ``str.maketrans`` precomputes the translation table at class
    # load. The dict literal is intentionally minimal: if we ever
    # add another display-only glyph (for example ``∅`` for
    # "universal"), add it here, not as scattered ``replace`` calls.
    _COPY_TRANSLATIONS = str.maketrans(
        {
            "−": "-",  # U+2212 MINUS SIGN -> ASCII hyphen-minus
        }
    )

    def createMimeDataFromSelection(self) -> QMimeData | None:
        original = super().createMimeDataFromSelection()
        if original is None:
            return original
        text = original.text()
        translated = text.translate(self._COPY_TRANSLATIONS)
        # Fast path: no display-only chars in the selection.
        if text == translated and not original.hasHtml():
            return original
        out = QMimeData()
        out.setText(translated)
        if original.hasHtml():
            # Apply the same translation to the HTML payload so a
            # rich-text paste target sees the ASCII form too. Without
            # this, copying to e.g. a docx editor would still produce
            # U+2212 because Qt prefers the HTML payload for those.
            out.setHtml(original.html().translate(self._COPY_TRANSLATIONS))
        return out


class AnalysisPanel(QWidget):
    """Analysis output pane. The tab labels (Class / Features /
    Contrasts) carry their own naming, so there's no top heading.

    Layout (single ``QGridLayout``):

    - Row 0, col 0 hosts the persistent selection label AND the
      expand/restore toggle in the same cell. The toggle uses
      ``AlignTop | AlignRight`` so it overlays the label's top-
      right corner; the label fills the cell normally. A reserved
      row minimum height keeps the toggle's pinning constant when
      the selection label is hidden (FEAT mode), so the visual
      ``y`` of the toggle does not depend on whether chips are
      currently displayed. The previous implementation positioned
      the toggle via ``resizeEvent`` + manual ``move()``; the cell-
      overlay form gives the same visual placement with explicit
      layout ownership.
    - Row 1 hosts the tab widget; it absorbs all vertical stretch.

    The toggle emits ``expand_toggled``; MainWindow owns the vsplit
    and handles the actual resize.
    """

    expand_toggled = pyqtSignal()

    # Index in ``self.tabs`` for the Contrasts tab, kept as a class
    # constant so ``set_sections`` can enable/disable it cleanly. Order
    # also matches the user's chosen reading order: Class first (the
    # analytical conclusion), then Features (raw spec), then Contrasts
    # (only meaningful for multi-segment SEG mode).
    _TAB_CLASS_IDX = 0
    _TAB_FEATURES_IDX = 1
    _TAB_CONTRASTS_IDX = 2

    # Reserved height for the top row (selection label + overlaid
    # toggle). 26 px = the 20-px button plus the 6-px top inset of
    # its previous manual position, so the toggle's ``y`` matches
    # the historical placement even when the selection label is
    # hidden and row 0 collapses to this minimum.
    _SELECTION_ROW_MIN_H = 26

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Pane absorbs leftover vertical space inside the vsplit and
        # stretches with the window horizontally. ``minimumSizeHint``
        # below pins the floor; ``REGION_CONSTRAINTS['analysis_panel']``
        # is the single source for both ends.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        # Expand/restore toggle. Text glyphs (not emoji) so the button
        # honors the active font and palette.
        self.expand_btn = QPushButton("⤢", self)
        self.expand_btn.setFlat(True)
        self.expand_btn.setFixedSize(24, 20)
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setToolTip(expand_button_tooltip(is_expanded=False))
        self.expand_btn.clicked.connect(self.expand_toggled.emit)
        self._is_expanded = False
        # Persistent header content: "Selected: /a/ /b/" or
        # "Query: +Voice −Nasal". Stays visible regardless of which
        # tab is active so the user always sees what they selected.
        self.selection_label = _CopyableTextEdit(self)
        self.selection_label.setReadOnly(True)
        self.selection_label.setFixedHeight(38)
        mono_font = QFont()
        mono_font.setFamilies(MONO_FAMILIES)
        mono_font.setPointSize(10)
        self.selection_label.setFont(mono_font)
        # The three analysis tabs. Each contains its own
        # ``_CopyableTextEdit`` so tab swaps are cheap (no re-render)
        # and the cached-HTML short-circuit in ``set_html`` still
        # applies per tab. The Contrasts tab gets disabled (greyed
        # out, not removed) when the current selection has nothing
        # to compare.
        self.tabs = QTabWidget(self)
        self._tab_class = _CopyableTextEdit(self.tabs)
        self._tab_features = _CopyableTextEdit(self.tabs)
        self._tab_contrasts = _CopyableTextEdit(self.tabs)
        for tab_widget in (
            self._tab_class,
            self._tab_features,
            self._tab_contrasts,
        ):
            tab_widget.setReadOnly(True)
            tab_widget.setFont(mono_font)
        self.tabs.addTab(self._tab_class, "Class")
        self.tabs.addTab(self._tab_features, "Features")
        self.tabs.addTab(self._tab_contrasts, "Contrasts")
        # Back-compat alias so the existing ``self.analysis.content``
        # references in tests + other code keep working; the Class
        # tab carries the most prominent analytical output so
        # ``.content`` lands there.
        self.content = self._tab_class
        self.content.setMinimumHeight(60)
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 2, 16, 8)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(2)
        # Row 0: selection label + overlaid expand toggle (same cell,
        # different alignments). The reserved minimum height keeps
        # the toggle anchored even when the label hides in FEAT mode.
        layout.setRowMinimumHeight(0, self._SELECTION_ROW_MIN_H)
        layout.addWidget(self.selection_label, 0, 0)
        layout.addWidget(
            self.expand_btn,
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(self.tabs, 1, 0)
        layout.setRowStretch(1, 1)
        # Selection label starts hidden. Empty selection / FEAT
        # mode shouldn't render chips. ``set_sections`` toggles
        # visibility based on whether the html payload actually
        # carries chips. The row 0 minimum height keeps the toggle
        # anchored when the label is gone.
        self.selection_label.setVisible(False)
        # Class-tab background-colour state (natural / not_natural /
        # neutral). ``apply_theme`` reads this when composing the
        # stylesheet so a theme swap mid-session keeps the cue.
        self._class_state: str = "neutral"
        self.apply_theme()

    def set_expanded(self, expanded: bool) -> None:
        """Update the toggle's visual state. MainWindow calls this
        after applying the splitter swap so the button glyph reflects
        the live state regardless of which path triggered the change
        (button click, keyboard shortcut, or user-drag detection).
        """
        if self._is_expanded == expanded:
            return
        self._is_expanded = expanded
        # U+2922 (diagonal arrows out) = expand, U+2923 (diagonal
        # arrows in) = restore.
        self.expand_btn.setText("⤣" if expanded else "⤢")
        self.expand_btn.setToolTip(expand_button_tooltip(is_expanded=expanded))

    def minimumSizeHint(self) -> QSize:
        """Sourced from ``REGION_CONSTRAINTS['analysis_panel']``. The
        Qt splitter and the vsplit fitting code consult this when
        deciding how much room the analysis pane can yield under
        resize pressure; the entry pins the bottom edge so future
        ``setMinimumHeight(0)`` paths can't silently collapse it."""
        constraint = REGION_CONSTRAINTS["analysis_panel"]
        return QSize(constraint.min_w, constraint.min_h)

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        set_css(
            self,
            f"background: {C['analysis_bg']};"
            f" border-top: 1px solid {C['border']};",
        )
        set_css(
            self.expand_btn,
            f"""
            QPushButton {{
                color: {C['text_dim']};
                background: transparent;
                border: none;
                font-size: 14px;
                padding: 0;
            }}
            QPushButton:hover {{ color: {C['text']}; }}
            """,
        )
        text_edit_css = f"""
            QTextEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 8px;
            }}
            """ + scrollbar_style()
        for tab in (self._tab_class, self._tab_features, self._tab_contrasts):
            set_css(tab, text_edit_css)
        # Persistent selection header: same colour palette as the
        # tab bodies but no border (it sits flush above the tabs).
        set_css(
            self.selection_label,
            f"""
            QTextEdit {{
                background: transparent;
                color: {C["text"]};
                border: none;
                padding: 0 2px;
            }}
            """,
        )
        set_css(self.tabs, _class_state_stylesheet(self._class_state))

    def set_html(self, html: str) -> None:
        """Legacy single-blob entry point. Routes the whole HTML to
        the Class tab so anything still calling this from outside the
        view-model layer keeps working. New call sites should use
        :py:meth:`set_sections` so the three tabs each carry their
        own content."""
        set_html(self._tab_class, html)
        self.selection_label.setHtml("")
        set_html(self._tab_features, "")
        set_html(self._tab_contrasts, "")

    def set_sections(
        self,
        selection_html: str,
        class_html: str,
        features_html: str,
        contrasts_html: str,
        *,
        contrasts_enabled: bool = True,
        class_state: str = "neutral",
    ) -> None:
        """Push the four analysis sections produced by the shared
        view-model into the persistent selection header + three tabs.

        ``contrasts_enabled=False`` greys out the Contrasts tab and
        prevents activation. Used for single-segment SEG selections
        and for FEAT mode, where contrasts aren't meaningful. If the
        currently-active tab is the disabled one, focus jumps back
        to the Class tab so the user lands on real content instead
        of a placeholder explaining why the tab is empty.

        ``class_state`` colours the Class tab text: ``"natural"``
        maps to palette ``plus`` (green), ``"not_natural"`` maps to
        palette ``minus`` (red), anything else uses the default text
        colour. The coloured tab replaces the previous "Natural
        class: Yes/No" text in the tab body.

        Empty ``selection_html`` hides the persistent selection
        label entirely (no reserved strip of space). Used in FEAT
        mode where the query is already explicit in the Features
        tab.
        """
        if selection_html:
            self.selection_label.setHtml(selection_html)
            self.selection_label.setVisible(True)
        else:
            self.selection_label.clear()
            self.selection_label.setVisible(False)
        set_html(self._tab_class, class_html)
        set_html(self._tab_features, features_html)
        set_html(self._tab_contrasts, contrasts_html)
        self.tabs.setTabEnabled(self._TAB_CONTRASTS_IDX, contrasts_enabled)
        if (
            not contrasts_enabled
            and self.tabs.currentIndex() == self._TAB_CONTRASTS_IDX
        ):
            self.tabs.setCurrentIndex(self._TAB_CLASS_IDX)
        self._apply_class_state(class_state)

    def _apply_class_state(self, state: str) -> None:
        """Colour the first tab (Class) per the natural-class verdict.

        Re-applies the full tab-bar stylesheet with a state-specific
        ``QTabBar::tab:first`` rule appended. Background colour is
        the cue (palette ``plus_bg`` for natural, ``minus_bg`` for
        not-natural, default for neutral); using background instead
        of text colour stays readable for users with reduced colour
        vision and is consistent with the web's ``data-class-state``
        styling.
        """
        if state == self._class_state:
            return
        self._class_state = state
        set_css(self.tabs, _class_state_stylesheet(state))

    def clear(self) -> None:
        """Reset the analysis pane to its post-construction state.

        Canonical full-reset sink. After this returns, every observable
        visual cue (tab bodies, tab colour, tab enable, active tab,
        chips strip) is back to its empty baseline. Any new display
        cue added later must reset here too, so a future regression
        breaks ``test_analysis_panel_clear`` instead of the UI.
        """
        self.selection_label.clear()
        self.selection_label.setVisible(False)
        for tab in (self._tab_class, self._tab_features, self._tab_contrasts):
            tab.clear()
            # set_html caches the last HTML string on the widget and
            # short-circuits duplicate calls. clear() resets the widget
            # but not the cache, so a later set_html(X) where X matches
            # the pre-clear value would no-op and leave the pane blank.
            if hasattr(tab, _LAST_HTML_ATTR):
                delattr(tab, _LAST_HTML_ATTR)
        if hasattr(self.selection_label, _LAST_HTML_ATTR):
            delattr(self.selection_label, _LAST_HTML_ATTR)
        self._apply_class_state("neutral")
        self.tabs.setTabEnabled(self._TAB_CONTRASTS_IDX, True)
        self.tabs.setCurrentIndex(self._TAB_CLASS_IDX)


class SegmentGridWidget(QWidget):
    """Fluid grid of segment buttons. Column count is recomputed from
    the current widget width on resize.
    """

    # Upper bound on segment-grid column count. Picked above the
    # largest manner-class group in any bundled inventory so every
    # group can fit on one row when the pane is wide enough.
    MAX_COLS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: dict[str, list[str]] = {}
        self._buttons: dict[str, SegmentButton] = {}
        self._headers: list[QLabel] = []
        # Last value ``set_headers_active`` styled the headers with;
        # cached so mode toggles short-circuit. Reset whenever fresh
        # header labels replace the old ones.
        self._last_headers_active: bool | None = None
        self._n_cols: int = 0
        self._grid = QGridLayout(self)
        self._grid.setSpacing(BTN_GAP)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        # The grid can shrink (its parent panel holds the real floor).
        # See ``REGION_CONSTRAINTS['seg_grid']`` for the contract.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumWidth(0)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)
        self._resize_timer.timeout.connect(self._do_relayout)
        # ``set_groups`` runs during __init__ when the widget width is
        # ~0, so _compute_n_cols comes out as 1. The first post-show
        # resizeEvent must relayout SYNCHRONOUSLY so paint #1 already
        # shows the final column count; debouncing it would leave the
        # window flashing through the 1-col layout on startup. The
        # flag flips True after the first sync relayout; subsequent
        # resizes (live drag) keep the debounce.
        self._needs_sync_relayout = True
        # Cache so _do_relayout short-circuits when nothing layout-
        # relevant has changed. Saves the QGridLayout rebuild +
        # ~140 button setParent/show on every resize tick when the
        # spillover partition stays the same.
        self._last_available_height: int = -1
        self._last_main_count: int = -1

    def set_groups(
        self,
        groups: dict[str, list[str]],
        buttons: dict[str, SegmentButton],
    ) -> None:
        """Replace all content.

        Old buttons are detached (not destroyed) since they belong to
        the caller's pool. Headers are recreated each swap.
        """
        while self._grid.count():
            self._grid.takeAt(0)
        for btn in self._buttons.values():
            btn.setParent(None)
        for hdr in self._headers:
            hdr.deleteLater()
        self._headers.clear()
        self._last_headers_active = None
        self._groups = groups
        self._buttons = buttons
        for manner in groups:
            hdr = QLabel(manner.upper())
            hdr.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
            set_css(
                hdr,
                f"color: {C['text_dim']};"
                " letter-spacing: 1px;"
                " padding: 4px 2px 1px 2px;",
            )
            hdr.setParent(self)
            self._headers.append(hdr)
        self._n_cols = 0
        # New content; the next resizeEvent should treat it as a fresh
        # layout (sync, not debounced) so a mid-app inventory swap
        # doesn't flash through a wrong column count either.
        self._needs_sync_relayout = True
        self._do_relayout()

    def apply_theme(self) -> None:
        """Invalidate the headers-active dedup cache so the next
        ``set_headers_active`` re-applies palette-dependent colors.
        """
        self._last_headers_active = None

    def set_headers_active(self, active: bool) -> None:
        """Style headers for the given active state. Skips re-applying
        if the cached state matches; ``set_groups`` and ``apply_theme``
        both clear the cache to force a re-style.
        """
        if self._last_headers_active == active:
            return
        color = C["text"] if active else C["text_dim"]
        style = (
            f"color: {color}; letter-spacing: 1px;"
            " padding: 4px 2px 1px 2px;"
        )
        for hdr in self._headers:
            set_css(hdr, style)
        self._last_headers_active = active

    def sizeHint(self) -> QSize:
        """Report the natural width (widest manner-class group on one
        row) instead of the layout's currently-rendered width.
        QGridLayout.sizeHint reflects the columns currently in use,
        which depends on this widget's width, so the parent splitter
        gets stuck on a squeezed value during inventory load. Reporting
        the natural width breaks that chicken-and-egg.
        """
        if not self._groups:
            return super().sizeHint()
        max_n = max(len(segs) for segs in self._groups.values())
        cols = min(max_n, self.MAX_COLS)
        natural_w = cols * BTN_W + (cols - 1) * BTN_GAP if cols > 0 else 0
        return QSize(natural_w, super().sizeHint().height())

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        if self._needs_sync_relayout:
            self._needs_sync_relayout = False
            self._do_relayout()
            return
        self._resize_timer.start()

    def _compute_n_cols(self) -> int:
        # Width-to-cols delegated to the shared layout helper so the
        # web's grid uses the same formula. The local cap-at-group-
        # size step stays here because it depends on the widget's
        # in-memory groups, which the pure-Python layout module
        # doesn't see.
        max_possible = layout_mod.seg_pane_n_cols(self.width())
        if not self._groups:
            return max_possible
        max_N = max(len(segs) for segs in self._groups.values())
        if max_N <= max_possible:
            return max_N
        return max_possible

    def _do_relayout(self) -> None:
        n_cols = self._compute_n_cols()
        available = self._available_pane_height()
        groups_items = list(self._groups.items())
        if not groups_items:
            self._n_cols = n_cols
            self._last_available_height = available
            self._last_main_count = 0
            while self._grid.count():
                self._grid.takeAt(0)
            return
        # ``best_segment_n_cols`` picks the largest column count
        # that leaves no row holding a single orphan button.
        group_cols_main = [
            best_segment_n_cols(len(segs), n_cols) for _, segs in groups_items
        ]
        per_btn_row = _SEG_BTN_H + BTN_GAP
        main_heights = [
            _SEG_HEADER_H + math.ceil(len(segs) / max(g_cols, 1)) * per_btn_row
            for (_, segs), g_cols in zip(
                groups_items, group_cols_main, strict=True
            )
        ]
        main_count = partition_groups_for_spillover(
            main_heights,
            available,
            n_spillover_cols=2,
        )
        # Short-circuit: same n_cols + partition decision means the
        # previous layout is still valid; skips the rebuild on the
        # multi-pixel jitter common during live window drags.
        if (
            n_cols == self._n_cols
            and main_count == self._last_main_count
            and available == self._last_available_height
        ):
            return
        self._n_cols = n_cols
        self._last_available_height = available
        self._last_main_count = main_count
        while self._grid.count():
            self._grid.takeAt(0)

        grid_row = 0
        hdr_iter = iter(self._headers)
        # Main flow: header spans the full ``n_cols`` row so headers
        # align across groups; each group's BUTTONS wrap at the
        # per-group ``group_cols_main`` count, which avoids one-button
        # orphan rows. Header span is intentionally ``n_cols`` (not
        # the per-group count) so the manner-class titles line up
        # along the same left edge.
        for (_manner, segs), g_cols in zip(
            groups_items[:main_count],
            group_cols_main[:main_count],
            strict=True,
        ):
            hdr = next(hdr_iter)
            self._grid.addWidget(hdr, grid_row, 0, 1, n_cols)
            hdr.show()
            grid_row += 1
            for col_i, seg in enumerate(segs):
                btn = self._buttons[seg]
                button_row = grid_row + col_i // g_cols
                button_col = col_i % g_cols
                self._grid.addWidget(btn, button_row, button_col)
                btn.show()
            grid_row += math.ceil(len(segs) / g_cols)

        # Spillover: pair-by-pair, each group gets a half-width slot.
        # Slot 0 in cols ``[0, slot_cols)``; col ``slot_cols`` is the
        # visible gap; slot 1 in ``[slot_cols + 1, 2 * slot_cols + 1)``.
        # Same QGridLayout as the main flow (nested-container version
        # tanked startup). Each group runs ``best_segment_n_cols`` for
        # its slot so spillover rows also avoid orphan buttons.
        slot_cols = max(1, (n_cols - 1) // 2)
        spill = groups_items[main_count:]
        for pair_start in range(0, len(spill), 2):
            pair = spill[pair_start : pair_start + 2]
            for slot, _ in enumerate(pair):
                hdr = next(hdr_iter)
                col_start = slot * (slot_cols + 1)
                self._grid.addWidget(hdr, grid_row, col_start, 1, slot_cols)
                hdr.show()
            pair_cols = [
                best_segment_n_cols(len(segs), slot_cols) for _, segs in pair
            ]
            max_btn_rows = max(
                math.ceil(len(segs) / g_cols)
                for (_, segs), g_cols in zip(pair, pair_cols, strict=True)
            )
            for slot, ((_, segs), g_cols) in enumerate(
                zip(pair, pair_cols, strict=True)
            ):
                col_start = slot * (slot_cols + 1)
                for col_i, seg in enumerate(segs):
                    btn = self._buttons[seg]
                    br = grid_row + 1 + col_i // g_cols
                    bc = col_start + (col_i % g_cols)
                    self._grid.addWidget(btn, br, bc)
                    btn.show()
            grid_row += 1 + max_btn_rows

    def _available_pane_height(self) -> int:
        """Viewport height of the QScrollArea ancestor: the budget the
        spillover partition treats as ``available``. Anything taller
        than this means the old all-in-one-column layout would force
        a scrollbar; the partition picks groups to pack into the
        2-col spillover instead.

        Returns 0 (and skips spillover) before the widget is parented
        under a QScrollArea (tests, early __init__ ticks). The
        partition function returns ``n`` for ``available_height <= 0``,
        so all groups stay in the main flow.
        """
        from PyQt6.QtWidgets import QScrollArea

        node = self.parent()
        while node is not None:
            if isinstance(node, QScrollArea):
                vp = node.viewport()
                return vp.height() if vp is not None else 0
            node = node.parent()
        return 0
