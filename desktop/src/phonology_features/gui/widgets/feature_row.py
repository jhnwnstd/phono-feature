"""Per-feature toggle row used by the desktop feature pane.

Two visual modes:

* **Query mode** (FEAT_TO_SEG): user clicks ``+``/``-`` to assemble
  a feature query. Row tints + bolds.
* **Display mode** (SEG_TO_FEAT): badge shows the analytical state
  derived from the shared view-model.

Stylesheet strings cached per theme at class level so a 30+ row
palette swap touches the f-strings once per theme, not once per
row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from phonology_features.gui._themed_style_cache import styles_for_active_theme
from phonology_features.gui.style_utils import set_css
from phonology_shared.presentation.layout import (
    FEAT_BADGE_W,
    FEAT_BADGE_W_COMPACT,
    FEAT_BTN_H,
    FEAT_BTN_H_COMPACT,
    FEAT_BTN_W,
    FEAT_BTN_W_COMPACT,
)
from phonology_shared.presentation.palette import C
from phonology_shared.presentation.view_models import (
    NEUTRAL_BADGE,
    feature_row_badge,
)


@dataclass(frozen=True, slots=True)
class _RowDensity:
    """Fixed-size sizing pack for a :py:class:`FeatureRow`.

    Two instances ship below: ``_DENSITY_NORMAL`` for the everyday
    case and ``_DENSITY_COMPACT`` for inventories that would
    otherwise overflow the typical 440-px feature panel. Frozen so
    the values can be referenced safely from class-level callsites.
    """

    btn_size: tuple[int, int]
    badge_size: tuple[int, int]
    margin_v: int
    row_h: int
    name_font: int
    btn_font: int


# Comfortable default: 30-px row stride, 28x24 buttons, 10-pt label.
# Pixel dimensions come from shared layout constants so the desktop
# and the generated CSS (--feat-btn-*, --feat-badge-w) cannot drift.
_DENSITY_NORMAL = _RowDensity(
    btn_size=(FEAT_BTN_W, FEAT_BTN_H),
    badge_size=(FEAT_BADGE_W, FEAT_BTN_H),
    margin_v=3,
    row_h=30,
    name_font=10,
    btn_font=11,
)
# Moderate shrink: ~4 px shorter per row than NORMAL. Keeps button
# and name fonts at the same point sizes so the visual feel stays
# consistent; only the vertical breathing room tightens. At this
# density the cards may still overflow on inventories near the
# 40-feature cap, in which case the panel's :py:class:`QScrollArea`
# takes over for the remainder.
_DENSITY_COMPACT = _RowDensity(
    btn_size=(FEAT_BTN_W_COMPACT, FEAT_BTN_H_COMPACT),
    badge_size=(FEAT_BADGE_W_COMPACT, FEAT_BTN_H_COMPACT),
    margin_v=2,
    row_h=26,
    name_font=10,
    btn_font=11,
)


def _feature_row_btn_qss(*, is_plus: bool) -> str:
    """QSS for one polarity of a FeatureRow's +/- toggle button.

    Shape is identical across rows; only the active/hover/checked
    colour family flips per polarity. Pulled out so
    :py:meth:`FeatureRow._compute_styles` can cache it alongside
    the other per-theme style strings, sparing each row's
    ``apply_theme`` from rebuilding the f-string for both buttons.
    """
    active_bg = C["plus_bg"] if is_plus else C["minus_bg"]
    active_text = C["plus"] if is_plus else C["minus"]
    border = C["plus"] if is_plus else C["minus"]
    return f"""
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


class FeatureRow(QWidget):
    """One feature row in the feature panel. Interactive mode shows
    +/- toggle buttons; display mode shows a coloured value badge.
    Style strings cached per theme at class level (see SegmentButton);
    ``apply_theme`` re-binds instance attrs on a live theme swap.

    The row pins a fixed height per active density. Without the pin,
    a feature-heavy inventory squeezes each row below the buttons'
    fixed 24 px height; the buttons are then drawn outside the row's
    allocated rect and overlap the adjacent row. Pinning the height
    + the panel's :py:class:`QScrollArea` together produce predictable
    geometry: rows render at their full size and the scroll area
    takes over when the content exceeds the viewport.
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
    _BTN_PLUS: str = ""
    _BTN_MINUS: str = ""

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
        # Reset-cache state: ``_panel_cache_valid`` says "the row has
        # been reset to neutral and the cache is fresh"; on a True
        # cache, ``_panel_cached_for`` records the ``panel_active``
        # value it was reset for so reset() can short-circuit when
        # nothing relevant has changed. Two named flags beat a
        # ``bool | None`` sentinel where ``None`` overloads
        # "no cache" with "force full reset".
        self._panel_cache_valid: bool = False
        self._panel_cached_for: bool = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(4)
        self.name_label = QLabel(feature_name, self)
        # Academic small-caps for feature labels: the initial cap
        # stays at full height and the rest of the lowercase
        # letters render as small caps. Matches the print
        # convention for citing features.
        _name_font = QFont("Noto Sans", 10)
        _name_font.setCapitalization(QFont.Capitalization.SmallCaps)
        self.name_label.setFont(_name_font)
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
        self.minus_btn = QPushButton("−", self)
        self.minus_btn.setFixedSize(28, 24)
        self.minus_btn.setCheckable(True)
        self.minus_btn.setFont(QFont("Noto Sans", 11, QFont.Weight.Bold))
        self._style_btn(self.minus_btn, "-")
        self.badge = QLabel("·", self)
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
        # Pin the row to its density's stride so Qt cannot squeeze it
        # below the buttons' fixed height. Owners flip density via
        # ``set_compact`` after they know the inventory's feature
        # count; the constructor starts in NORMAL.
        self._compact = False
        self.setFixedHeight(_DENSITY_NORMAL.row_h)

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
            # Per-polarity +/- button QSS. Identical across every
            # FeatureRow in the pool, so caching once per palette
            # version saves the f-string rebuild + attribute lookups
            # on every row's apply_theme. The setStyleSheet polish
            # cost itself is unavoidable on a theme change, but the
            # cache cuts the per-call CPU above the Qt boundary.
            "BTN_PLUS": _feature_row_btn_qss(is_plus=True),
            "BTN_MINUS": _feature_row_btn_qss(is_plus=False),
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
        self._panel_cache_valid = False
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
            self._panel_cache_valid = True
            self._panel_cached_for = self._panel_active

    def _style_btn(self, btn: QPushButton, polarity: str) -> None:
        # Stylesheet is shape-identical for every FeatureRow in the
        # pool; the per-polarity strings are cached at class level by
        # :py:meth:`_compute_styles` and bound on this instance via
        # :py:meth:`_build_styles`. Reading the precomputed attr
        # avoids rebuilding two ~350-char f-strings per row on every
        # theme/palette toggle (34 rows x 2 polarities = 68 rebuilds
        # per toggle on Hayes).
        qss = self._BTN_PLUS if polarity == "+" else self._BTN_MINUS
        set_css(btn, qss)

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
        self._panel_cache_valid = False
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

    def set_compact(self, yes: bool) -> None:
        """Switch the row between comfortable and compact density.

        Compact mode shrinks the buttons and tightens the margins so
        a feature-rich inventory (PanPhon-generated 24+ features,
        custom 30+ sets) fits in the typical 440-px feature panel
        without falling back on the scrollbar. The panel owner picks
        the threshold; this method only applies the chosen mode.

        Idempotent: a second call with the same value is a fast
        no-op so a bulk apply over the pool stays cheap on rapid
        inventory swaps.
        """
        if yes == self._compact:
            return
        self._compact = yes
        cfg = _DENSITY_COMPACT if yes else _DENSITY_NORMAL
        btn_w, btn_h = cfg.btn_size
        badge_w, badge_h = cfg.badge_size
        self.plus_btn.setFixedSize(btn_w, btn_h)
        self.minus_btn.setFixedSize(btn_w, btn_h)
        self.badge.setFixedSize(badge_w, badge_h)
        self.plus_btn.setFont(
            QFont("Noto Sans", cfg.btn_font, QFont.Weight.Bold)
        )
        self.minus_btn.setFont(
            QFont("Noto Sans", cfg.btn_font, QFont.Weight.Bold)
        )
        self.badge.setFont(QFont("Noto Sans", cfg.btn_font, QFont.Weight.Bold))
        _compact_name_font = QFont("Noto Sans", cfg.name_font)
        _compact_name_font.setCapitalization(QFont.Capitalization.SmallCaps)
        self.name_label.setFont(_compact_name_font)
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(8, cfg.margin_v, 8, cfg.margin_v)
        self.setFixedHeight(cfg.row_h)

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
                (`±` / `+` / U+2212 / `·`). Single source of truth so the
                desktop and web FeatureRow can never drift; QSS selection
                stays Qt-only below.
        """
        # Dedup: seg-mode updates re-run through every row even when the
        # state didn't change. Skip 3 setStyleSheet + 1 setText calls.
        state = (value, shared, contrastive)
        if self._last_display_state == state:
            return
        self._last_display_state = state
        self._panel_cache_valid = False
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
        3. Visual-dirty, value non-empty, or cache invalidated (set
           by ``apply_theme`` / ``_apply_query_style`` / ``set_display``
           when palette or query state may have moved): full reset.
        """
        visual_dirty = self._last_display_state is not None
        force_full = not self._panel_cache_valid
        if self._current_value == "" and not visual_dirty and not force_full:
            if self._panel_cached_for == self._panel_active:
                return
            name_style = (
                self._NAME_ACTIVE
                if self._panel_active
                else self._NAME_INACTIVE
            )
            set_css(self.name_label, name_style)
            self._panel_cache_valid = True
            self._panel_cached_for = self._panel_active
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
        self._panel_cache_valid = True
        self._panel_cached_for = self._panel_active
