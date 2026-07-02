"""Single-segment toggle button.

``SegmentButton`` carries one IPA glyph. The closed set of visual
states it mutates between (selected, matched, unmatched, suggested,
default) lives on
:py:class:`phonology_shared.presentation.view_models.SegmentState`
and is re-exported below so widget consumers can keep importing
``SegmentState`` from this module. Stylesheet strings are cached per
theme at class level so a 140-segment palette swap pays the f-string
cost once per theme rather than once per button.
"""

from __future__ import annotations

from typing import ClassVar

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QFont
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget

from phonology_features.gui._themed_style_cache import styles_for_active_theme
from phonology_features.gui.style_utils import set_css
from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation.constants import MONO_FAMILIES
from phonology_shared.presentation.layout import (
    RADIUS_PX,
    REGION_CONSTRAINTS,
)
from phonology_shared.presentation.palette import C
from phonology_shared.presentation.view_models import SegmentState

__all__ = ["SegmentButton", "SegmentState"]


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

    # ``(theme, mode)`` to styles dict, shared across instances. Cache
    # rebuild semantics and the invalidation contract live in
    # :py:func:`_themed_style_cache.styles_for_active_theme`.
    _styles_cache: ClassVar[dict[tuple[str, str], dict[SegmentState, str]]] = (
        {}
    )

    @classmethod
    def _styles_for_active_theme(cls) -> dict[SegmentState, str]:
        return styles_for_active_theme(cls._styles_cache, cls._build_styles)

    def __init__(self, segment: str, parent: QWidget | None = None) -> None:
        super().__init__(segment, parent)
        self.segment = segment
        self._state: SegmentState = SegmentState.DEFAULT
        # Per-instance vowel-chart style overrides, applied ON TOP of the
        # shared per-theme cache WITHOUT mutating it (the cache is shared
        # with the consonant grid). ``_in_capsule`` swaps to the flat
        # segmented-capsule cell style; ``_chip_radius_px`` overrides the
        # corner radius for a single vowel chip. Both are reset when the
        # pooled button returns to the consonant grid.
        self._in_capsule: bool = False
        self._chip_radius_px: int | None = None
        self.setCheckable(True)
        # No tooltip. The button label already renders the segment,
        # and a hover bubble repeating ``/seg/`` is redundancy that
        # flickers every pointer pass. Removed in lockstep with the
        # web's matching change.
        # Fixed dimensions sourced from the constraint table so the web
        # (CSS ``--seg-btn-min-w`` / ``--seg-btn-min-h``) and the
        # desktop pull from one entry. ``setSizePolicy(Fixed)`` is
        # documentary: ``setFixedSize`` already pins both policies to
        # Fixed internally, but the explicit call makes the size
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
        # IPA-coverage font chain (same as the analysis pane) so
        # combining marks like the tie bar in d͡ʒ and ejectives like pʼ
        # render with the same glyphs everywhere they appear.
        # ``setFamilies`` keeps Qt's substitution rule intact; the 9pt
        # size matches the historic button typography.
        btn_font = QFont("Noto Sans", 9)
        btn_font.setFamilies(MONO_FAMILIES)
        self.setFont(btn_font)
        self._styles = self._styles_for_active_theme()
        set_css(self, self._styles[SegmentState.DEFAULT])

    def apply_theme(self) -> None:
        """Re-style against the active palette in place. Called by
        MainWindow on theme toggle so pooled buttons survive.

        Short-circuits when the cached theme dict already matches the
        one we'd apply. ``_styles_cache`` returns the same dict
        instance for repeated requests in the same theme, so the
        identity check is both correct and cheap. This lets the main
        theme loop safely call apply_theme on orphan pool entries
        without paying for widgets whose theme is already current.
        """
        new_styles = self._styles_for_active_theme()
        if new_styles is self._styles:
            return
        self._styles = new_styles
        self._refresh_css()

    @staticmethod
    def _build_styles() -> dict[SegmentState, str]:
        # Border thickness ladder and border-radius sourced from
        # ``chart_style`` so the desktop QSS and the web's
        # ``--border-{thin,std,thick}`` / ``--radius-lg`` tokens can't
        # drift. Before the relay, desktop hardcoded 1px, 1.5px, and
        # 2px borders plus an 8 px radius across every state.
        _thin = cs.BORDER_PX["thin"]
        _std = cs.BORDER_PX["std"]
        _thick = cs.BORDER_PX["thick"]
        _br = RADIUS_PX["lg"]
        return {
            SegmentState.SELECTED: f"""
                QPushButton {{
                    background-color: {C["seg_selected"]};
                    color: #FFFFFF;
                    border: {_thick}px solid {C["accent"]};
                    border-radius: {_br}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border: {_thick}px solid {C["text"]};
                }}
            """,
            SegmentState.MATCHED: f"""
                QPushButton {{
                    background-color: {C["seg_matched"]};
                    color: #FFFFFF;
                    border: {_thick}px solid {C["accent"]};
                    border-radius: {_br}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    border: {_thick}px solid {C["text"]};
                }}
            """,
            SegmentState.UNMATCHED: f"""
                QPushButton {{
                    background-color: {C["seg_unmatched"]};
                    color: {C["text_dim"]};
                    border: {_thin}px dotted {C["border"]};
                    border-radius: {_br}px;
                }}
                QPushButton:hover {{
                    background-color: {C["seg_default"]};
                    color: {C["text"]};
                    border: {_std}px solid {C["accent"]};
                }}
            """,
            SegmentState.SUGGESTED: f"""
                QPushButton {{
                    background-color: {C["accent_light"]};
                    color: {C["accent"]};
                    border: {_std}px dashed {C["accent"]};
                    border-radius: {_br}px;
                }}
                QPushButton:hover {{
                    border: {_thick}px dashed {C["accent"]};
                }}
            """,
            SegmentState.DEFAULT: f"""
                QPushButton {{
                    background-color: {C["seg_default"]};
                    color: {C["text"]};
                    border: {_std}px solid {C["border"]};
                    border-radius: {_br}px;
                }}
                QPushButton:hover {{
                    background-color: {C["accent_light"]};
                    border: {_std}px solid {C["accent"]};
                }}
                QPushButton:checked {{
                    background-color: {C["seg_selected"]};
                    color: #FFFFFF;
                    border: {_thick}px solid {C["accent"]};
                    font-weight: bold;
                }}
            """,
        }

    def set_state(self, state: SegmentState | str) -> None:
        """Set the button's visual state. Accepts the enum or its
        string value. The isinstance check avoids an enum lookup on the
        hot mode-toggle path where most callers already pass the enum.
        """
        if isinstance(state, SegmentState):
            new_state = state
        else:
            new_state = SegmentState(state)
        if self._state == new_state:
            return
        self._state = new_state
        self._refresh_css()

    def _capsule_style(self, state: SegmentState) -> str:
        """QSS for this button as a cell INSIDE a vowel pair capsule.

        The capsule container paints the outer frame + divider, so the
        cell drops its own border/radius and shares the capsule fill.
        The coloured states fill the cell and re-add the colour-blind
        cue (solid / dashed / dotted) as an INSET border drawn inside
        the fixed-size box, so state never resizes the chip. Built
        per-instance (capsule cells are the rare case, not worth a
        second theme cache).
        """
        _thin = cs.BORDER_PX["thin"]
        _std = cs.BORDER_PX["std"]
        _thick = cs.BORDER_PX["thick"]
        if state in (SegmentState.SELECTED, SegmentState.MATCHED):
            fill = (
                C["seg_selected"]
                if state == SegmentState.SELECTED
                else C["seg_matched"]
            )
            return (
                f"QPushButton {{ background-color: {fill}; color: #FFFFFF;"
                f" border: {_thick}px solid {C['accent']};"
                f" border-radius: 0px; font-weight: bold; }}"
            )
        if state == SegmentState.SUGGESTED:
            return (
                f"QPushButton {{ background-color: {C['accent_light']};"
                f" color: {C['accent']};"
                f" border: {_std}px dashed {C['accent']};"
                f" border-radius: 0px; }}"
            )
        if state == SegmentState.UNMATCHED:
            return (
                f"QPushButton {{ background-color: {C['seg_unmatched']};"
                f" color: {C['text_dim']};"
                f" border: {_thin}px dotted {C['border']};"
                f" border-radius: 0px; }}"
            )
        # DEFAULT: transparent so the capsule's shared fill shows
        # through; hover / click (:checked) read as the accent cue.
        return (
            f"QPushButton {{ background-color: transparent;"
            f" color: {C['text']}; border: none; border-radius: 0px; }}"
            f" QPushButton:hover {{"
            f" background-color: {C['accent_light']}; }}"
            f" QPushButton:checked {{"
            f" background-color: {C['seg_selected']}; color: #FFFFFF;"
            f" border: {_thick}px solid {C['accent']};"
            f" font-weight: bold; }}"
        )

    def _refresh_css(self) -> None:
        """Re-apply the current state's stylesheet, honouring the
        per-instance vowel-chart overrides (capsule mode / chip
        radius) on top of the shared per-theme cache."""
        if self._in_capsule:
            set_css(self, self._capsule_style(self._state))
            return
        css = self._styles[self._state]
        if self._chip_radius_px is not None:
            # Append a second rule so the later border-radius wins over
            # the cached base, without rebuilding the whole style.
            css = (
                f"{css}\nQPushButton {{"
                f" border-radius: {self._chip_radius_px}px; }}"
            )
        set_css(self, css)

    def set_in_capsule(self, in_capsule: bool) -> None:
        """Toggle the flat 'cell inside a pair capsule' styling. Reset
        to ``False`` when the pooled button returns to the consonant
        grid so it never renders borderless there."""
        if self._in_capsule == in_capsule:
            return
        self._in_capsule = in_capsule
        self._refresh_css()

    def set_chip_radius(self, radius_px: int | None) -> None:
        """Override the corner radius (a single vowel chip uses the
        larger vowel-scoped radius). ``None`` restores the shared
        default; reset on return to the consonant grid."""
        if self._chip_radius_px == radius_px:
            return
        self._chip_radius_px = radius_px
        self._refresh_css()

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
