"""Reusable GUI widgets: SegmentButton, FeatureRow, AnalysisPanel,
SegmentGridWidget. Each owns its own ``apply_theme`` for live theme
swaps; per-widget style dicts are cached per theme at class level.
"""

import math
from enum import StrEnum
from typing import ClassVar

from PyQt6.QtCore import QMimeData, QSize, Qt, QTimer, pyqtSignal
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

from phonology_features.gui.constants import (
    BTN_GAP,
    BTN_W,
    MONO_FAMILIES,
    scrollbar_style,
)
from phonology_features.gui.palette import C
from phonology_features.gui.style_utils import (
    _LAST_HTML_ATTR,
    set_css,
    set_html,
)


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

    # theme name -> styles dict, shared across instances.
    _styles_cache: ClassVar[dict[str, dict]] = {}

    @classmethod
    def _styles_for_active_theme(cls) -> dict:
        from phonology_features.gui.palette import get_theme_name

        theme = get_theme_name()
        cached = cls._styles_cache.get(theme)
        if cached is None:
            cached = cls._build_styles()
            cls._styles_cache[theme] = cached
        return cached

    def __init__(self, segment: str, parent=None):
        super().__init__(segment, parent)
        self.segment = segment
        self._state: SegmentState = SegmentState.DEFAULT
        self.setCheckable(True)
        self.setFixedSize(33, 26)
        self.setFont(QFont("Noto Sans", 9))
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


class FeatureRow(QWidget):
    """One feature row in the feature panel. Interactive mode shows
    +/- toggle buttons; display mode shows a coloured value badge.
    Style strings cached per theme at class level (see SegmentButton);
    ``apply_theme`` re-binds instance attrs on a live theme swap.
    """

    value_changed = pyqtSignal(str, str)
    # theme name -> styles dict (BADGE_*, ROW_*, NAME_*).
    _styles_cache: ClassVar[dict[str, dict[str, str]]] = {}
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
        from phonology_features.gui.palette import get_theme_name

        theme = get_theme_name()
        cached = cls._styles_cache.get(theme)
        if cached is None:
            cached = cls._compute_styles()
            cls._styles_cache[theme] = cached
        return cached

    def __init__(self, feature_name: str, parent=None):
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
        (``_styles_cache``). ``text_dim`` for the neutral badge text
        (not ``tag_gray_text``) so the badge matches the dim feature
        name and the inactive +/- button text on the same row.
        """
        return {
            "BADGE_CONTRASTIVE": (
                f"background: {C['accent_light']}; color: {C['accent']};"
                " border-radius: 4px; font-weight: bold;"
            ),
            "NAME_CONTRASTIVE": f"color: {C['accent']}; font-weight: bold;",
            "ROW_CONTRASTIVE": (
                f"background: {C['accent_light']}; border-radius: 6px;"
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
        1. **Query mode** -- the user clicked + or - on this row.
           ``_current_value`` is "+"/"-". The row background is tinted.
        2. **Display mode** -- ``set_display`` painted the badge with
           a value derived from seg-mode analysis. ``_last_display_state``
           holds the args.
        3. **Neutral** -- neither of the above. Badge shows "·" with
           the neutral palette colors. ``_last_display_state`` is None.

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
            self.set_display(value, shared, contrastive=contrastive)
        else:
            # State 3: neutral. Directly re-apply the neutral styles
            # since neither of the above paths runs.
            set_css(self.badge, self._BADGE_NEUTRAL)
            self.badge.setText("·")
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

    def _style_btn(self, btn: QPushButton, polarity: str):
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

    def _on_click(self, polarity: str):
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

    def set_interactive(self, yes: bool):
        # No need to stash ``yes`` on the instance: the +/- buttons'
        # visibility IS the source of truth for "interactive mode".
        # Anything that needs to query the state can check
        # plus_btn.isVisible().
        self.plus_btn.setVisible(yes)
        self.minus_btn.setVisible(yes)
        self.badge.setVisible(not yes)

    def set_display(self, value: str, shared: bool, contrastive: bool = False):
        """Display a feature value in seg-to-feat mode.

        Args:
            value: "+", "-", or "" (empty when not shared).
            shared: all selected segments share this value.
            contrastive: selected segments split cleanly on this feature.
        """
        # Dedup: seg-mode updates re-run through every row even when the
        # state didn't change. Skip 3 setStyleSheet + 1 setText calls.
        state = (value, shared, contrastive)
        if self._last_display_state == state:
            return
        self._last_display_state = state
        self._reset_for_panel = None
        if contrastive:
            self.badge.setText("\u00b1")
            set_css(self.badge, self._BADGE_CONTRASTIVE)
            set_css(self.name_label, self._NAME_CONTRASTIVE)
            set_css(self, self._ROW_CONTRASTIVE)
            return
        has_display_value = bool(value)
        if not has_display_value or not shared:
            self.badge.setText("\u00b7")
            set_css(self.badge, self._BADGE_NEUTRAL)
            set_css(self.name_label, self._NAME_DIM)
            set_css(self, self._ROW_TRANSPARENT)
            return
        self.badge.setText(value)
        set_css(self.name_label, self._NAME_BOLD)
        if value == "+":
            set_css(self.badge, self._BADGE_PLUS)
            set_css(self, self._ROW_PLUS)
        else:
            set_css(self.badge, self._BADGE_MINUS)
            set_css(self, self._ROW_MINUS)

    def restore_value(self, value: str):
        """Silently restore a saved plus or minus value."""
        self._current_value = value
        self.plus_btn.setChecked(value == "+")
        self.minus_btn.setChecked(value == "-")
        self._apply_query_style(value)

    def set_panel_active(self, active: bool):
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
        self.badge.setText("\u00b7")
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
    MATHEMATICAL MINUS SIGN) for typographic symmetry with `+`. But
    the rest of the ecosystem -- JSON files, code, regex, most
    terminals -- expects ASCII U+002D (`-`, HYPHEN-MINUS). Pasting
    `−Voice` into a JSON value silently does NOT match `"-"`.

    Translating at the copy boundary lets the display layer keep the
    nice typographic glyph and gives every paste target the byte
    they expect. Both the plain-text and HTML mime payloads get
    translated so rich-text targets (a doc editor) agree with
    plain-text targets (a code editor).
    """

    # ``str.maketrans`` precomputes the translation table at class
    # load. The dict literal is intentionally minimal -- if we ever
    # add another display-only glyph (e.g. ``∅`` for "universal"),
    # add it here, not as scattered ``replace`` calls.
    _COPY_TRANSLATIONS = str.maketrans(
        {
            "−": "-",  # U+2212 MINUS SIGN -> ASCII hyphen-minus
        }
    )

    def createMimeDataFromSelection(self):
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel("Analysis", self)
        self.title.setFont(QFont("Noto Sans", 10, QFont.Weight.Bold))
        self.content = _CopyableTextEdit(self)
        self.content.setReadOnly(True)
        # Explicit family chain rather than ``QFont("Noto Sans Mono")``:
        # Noto Sans Mono isn't on every system, and QFont's single-family
        # constructor silently falls back to the platform default (which
        # may have poor IPA / combining-mark coverage). ``setFamilies``
        # gives Qt an ordered list to try.
        mono_font = QFont()
        mono_font.setFamilies(MONO_FAMILIES)
        mono_font.setPointSize(10)
        self.content.setFont(mono_font)
        self.content.setMinimumHeight(60)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        layout.addWidget(self.title)
        layout.addWidget(self.content)
        self.apply_theme()

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        set_css(
            self,
            f"background: {C['analysis_bg']};"
            f" border-top: 1px solid {C['border']};",
        )
        set_css(
            self.title,
            f"color: {C['text_dim']}; letter-spacing: 1px;",
        )
        set_css(
            self.content,
            f"""
            QTextEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 8px;
            }}
            """ + scrollbar_style(),
        )

    def set_html(self, html: str):
        set_html(self.content, html)

    def clear(self) -> None:
        self.content.clear()
        # set_html caches the last HTML string on the widget and
        # short-circuits duplicate calls. clear() resets the widget
        # but not the cache, so a later set_html(X) where X matches
        # the pre-clear value would no-op and leave the pane blank.
        # Invalidate the cache here so the next set_html always
        # re-paints.
        if hasattr(self.content, _LAST_HTML_ATTR):
            delattr(self.content, _LAST_HTML_ATTR)


class SegmentGridWidget(QWidget):
    """Fluid grid of segment buttons. Column count is recomputed from
    the current widget width on resize.
    """

    MAX_COLS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: dict = {}
        self._buttons: dict = {}
        self._headers: list = []
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

    def set_groups(self, groups: dict, buttons: dict):
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

    def set_headers_active(self, active: bool):
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

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        if self._needs_sync_relayout:
            self._needs_sync_relayout = False
            self._do_relayout()
            return
        self._resize_timer.start()

    def _compute_n_cols(self) -> int:
        stride = BTN_W + BTN_GAP
        width_slots = (self.width() + BTN_GAP) // stride
        width_slots = max(1, width_slots)
        max_possible = min(width_slots, self.MAX_COLS)
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
                button_row = grid_row + col_i // n_cols
                button_col = col_i % n_cols
                self._grid.addWidget(btn, button_row, button_col)
                btn.show()
            group_rows = math.ceil(len(segs) / n_cols)
            grid_row += group_rows
