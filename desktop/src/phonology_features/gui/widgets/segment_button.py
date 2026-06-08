"""Single-segment toggle button.

``SegmentButton`` carries one IPA glyph; the closed set of visual
states it mutates between (selected / matched / unmatched /
suggested / default) lives on
:py:class:`phonology_shared.presentation.view_models.SegmentState`
and is re-exported below so widget consumers can keep importing
``SegmentState`` from this module. Stylesheet strings cached per
theme at class level so a 140-segment palette swap pays the
f-string cost once per theme rather than once per button.
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
        # No tooltip: the button label already renders the segment,
        # and a hover bubble repeating ``/seg/`` is pure redundancy
        # that flickers every pointer pass. Removed in lockstep
        # with the web's matching change.
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
        # Border thickness ladder + border-radius sourced from
        # ``chart_style`` so the desktop QSS and the web's
        # ``--border-{thin,std,thick}`` / ``--radius-lg`` tokens
        # cannot drift. Pre-relay desktop hardcoded 1px / 1.5px /
        # 2px borders + 8 px radius across every state.
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
            """,
            SegmentState.MATCHED: f"""
                QPushButton {{
                    background-color: {C["seg_matched"]};
                    color: #FFFFFF;
                    border: {_thick}px solid {C["accent"]};
                    border-radius: {_br}px;
                    font-weight: bold;
                }}
            """,
            SegmentState.UNMATCHED: f"""
                QPushButton {{
                    background-color: {C["seg_unmatched"]};
                    color: {C["text_dim"]};
                    border: {_thin}px solid {C["border"]};
                    border-radius: {_br}px;
                }}
            """,
            SegmentState.SUGGESTED: f"""
                QPushButton {{
                    background-color: {C["accent_light"]};
                    color: {C["accent"]};
                    border: {_std}px dashed {C["accent"]};
                    border-radius: {_br}px;
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
