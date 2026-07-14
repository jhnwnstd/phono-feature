# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QPainter,
    QPaintEvent,
)
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget

from phonology_features.gui._themed_style_cache import styles_for_active_theme
from phonology_features.gui.style_utils import set_css
from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation.constants import MONO_FAMILIES
from phonology_shared.presentation.layout import (
    REGION_CONSTRAINTS,
    SEG_BTN_RADIUS_PX,
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
        # Per-instance vowel-chart style override, applied ON TOP of the
        # shared per-theme cache WITHOUT mutating it (the cache is shared
        # with the consonant grid). ``_in_capsule`` swaps to the flat
        # segmented-capsule cell style; it is reset when the pooled button
        # returns to the consonant grid.
        self._in_capsule: bool = False
        # Which OUTER corners this cell rounds when it is an END cell of a
        # capsule ("left" / "right" / "" for a middle cell). Rounding the
        # end cells' outer corners to the frame's inner radius lets a
        # selected cell's FILL meet the rounded frame crisply instead of a
        # square fill the capsule mask clips at the corner, which left a
        # faint seam of the shared fill (the "smudge"). Reset alongside
        # ``_in_capsule`` when the pooled button returns to the grid.
        self._capsule_corner: str = ""
        # Number of manner classes this glyph renders in (a display count
        # from the producer's grouping): >1 marks a multi-membership
        # consonant so ``paintEvent`` can annotate that it is ONE segment
        # reaching several classes, not duplicates. NEVER fed back into
        # membership; the engine decides which classes a glyph reaches.
        self._multiclass_count: int = 1
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
        # Border thickness ladder and border-radius sourced from shared
        # constants so the desktop QSS and the web's
        # ``--border-{thin,std,thick}`` / ``--seg-btn-radius`` tokens
        # can't drift. Before the relay, desktop hardcoded 1px, 1.5px,
        # and 2px borders plus the radius across every state.
        # ``SEG_BTN_RADIUS_PX`` is the one radius every segment button
        # shares (consonant, vowel chip, diphthong / vocoid chip).
        _thin = cs.BORDER_PX["thin"]
        _std = cs.BORDER_PX["std"]
        _thick = cs.BORDER_PX["thick"]
        _br = SEG_BTN_RADIUS_PX
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
                    border: {_std}px solid {C["accent"]};
                    border-radius: {_br}px;
                }}
                QPushButton:hover {{
                    border: {_thick}px solid {C["accent"]};
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
        # A state change repaints via the QSS refresh, which does not
        # redraw the corner cue on its own; force it when a count is shown
        # so the cue's colour tracks the new state.
        if self._multiclass_count > 1:
            self.update()
        self._refresh_css()

    def set_multiclass_count(self, count: int) -> None:
        """Record how many manner classes this glyph reaches (>1 draws the
        corner cue). A DISPLAY count from the producer's grouping; it never
        feeds back into membership."""
        count = max(1, int(count))
        if count == self._multiclass_count:
            return
        self._multiclass_count = count
        self.update()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Paint the button, then a small corner count when the glyph
        reaches several manner classes (the multi-membership cue). Drawn
        over the QSS-styled button, so its colour is matched to the state's
        text colour to stay legible; muted via alpha so it reads as a quiet
        annotation, not a second glyph. Not a tooltip (removed on both
        platforms)."""
        super().paintEvent(a0)
        if self._multiclass_count <= 1:
            return
        painter = QPainter(self)
        font = QFont(self.font())
        font.setPointSizeF(6.0)
        font.setBold(True)
        painter.setFont(font)
        # selected / matched paint white text on the accent fill; the rest
        # use the standard text colour (mirrors the QSS ``color``).
        if self._state in (SegmentState.SELECTED, SegmentState.MATCHED):
            color = QColor("#FFFFFF")
        else:
            color = QColor(C["text"])
        color.setAlphaF(0.6)
        painter.setPen(color)
        painter.drawText(
            self.rect().adjusted(0, 1, -2, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            str(self._multiclass_count),
        )
        painter.end()

    def _capsule_style(self, state: SegmentState) -> str:
        """QSS for this button as a cell INSIDE a vowel pair capsule.

        Each cell paints ITS OWN slice of the pill outline (top + bottom,
        plus the rounded end cap on an END cell) via
        :meth:`_capsule_border_css`, coloured by THIS cell's state, so
        only a stated cell reads selected; the pill is never painted as
        one selected unit. The shared boundary between two cells is left
        to the capsule's faint divider (see :class:`VowelPairCapsule`), so
        a selected cell's blue stops at the divider instead of bleeding
        onto its neighbour. Fill (+ text colour / weight) is the primary
        state cue; selected / matched / suggested all read as one SOLID
        blue edge (suggested is told apart by its lighter fill, not a
        frayed dashed line). Built per-instance (capsule cells are the
        rare case, not worth a second theme cache).
        """
        radius = self._capsule_radius_css()
        border = self._capsule_border_css(state)
        if state in (SegmentState.SELECTED, SegmentState.MATCHED):
            fill = (
                C["seg_selected"]
                if state == SegmentState.SELECTED
                else C["seg_matched"]
            )
            return (
                f"QPushButton {{ background-color: {fill}; color: #FFFFFF;"
                f" {border} {radius} font-weight: bold; }}"
            )
        if state == SegmentState.SUGGESTED:
            # Natural-class COMPLETION: this cell's own accent_light fill
            # plus a SOLID accent edge on its own outline (below). Solid,
            # not dashed: a dashed stroke frayed on the pill's rounded cap;
            # the lighter fill, not the line style, sets it apart from a
            # hard selection.
            return (
                f"QPushButton {{ background-color: {C['accent_light']};"
                f" color: {C['accent']}; {border} {radius} }}"
            )
        if state == SegmentState.UNMATCHED:
            return (
                f"QPushButton {{ background-color: {C['seg_unmatched']};"
                f" color: {C['text_dim']};"
                f" {border} {radius} }}"
            )
        # DEFAULT: transparent so the capsule's shared fill shows
        # through; hover / click (:checked) read as the accent cue.
        return (
            f"QPushButton {{ background-color: transparent;"
            f" color: {C['text']}; {border} {radius} }}"
            f" QPushButton:hover {{"
            f" background-color: {C['accent_light']}; }}"
            f" QPushButton:checked {{"
            f" background-color: {C['seg_selected']}; color: #FFFFFF;"
            f" font-weight: bold; }}"
        )

    def _capsule_border_css(self, state: SegmentState) -> str:
        """Per-side border QSS for this capsule cell's own outline.

        Top and bottom are always drawn; the OUTER end cap is drawn only
        on an END cell (``_capsule_corner`` "left" / "right"); the side
        that faces a neighbour draws NO border, leaving that shared edge
        to the capsule's faint divider so adjacent cells never double a
        line there. The colour-blind cue rides the LINE: solid accent for
        selected / matched / suggested, dotted for unmatched, solid
        neutral for default; constant ``--border-std`` width in every
        state so a state change never resizes the cell.
        """
        std = f"{cs.BORDER_PX['std']:g}px"
        if state in (
            SegmentState.SELECTED,
            SegmentState.MATCHED,
            SegmentState.SUGGESTED,
        ):
            spec = f"{std} solid {C['accent']}"
        elif state == SegmentState.UNMATCHED:
            spec = f"{std} dotted {C['border']}"
        else:
            spec = f"{std} solid {C['border']}"
        parts = [f"border-top: {spec};", f"border-bottom: {spec};"]
        # The end cap goes on the OUTER side; the inner (divider) side is
        # left to the capsule's faint divider.
        left = spec if self._capsule_corner == "left" else "none"
        right = spec if self._capsule_corner == "right" else "none"
        parts.append(f"border-left: {left};")
        parts.append(f"border-right: {right};")
        return " ".join(parts)

    def _capsule_radius_css(self) -> str:
        """Border-radius QSS for this capsule cell. Middle cells stay
        square; an END cell rounds only its two OUTER corners to the
        frame's INNER radius (capsule radius minus the frame stroke) so
        its fill curves to meet the rounded frame cleanly. Inner (divider)
        corners stay square so the group still reads as one pill."""
        if self._capsule_corner not in ("left", "right"):
            return "border-radius: 0px;"
        r = cs.VOWEL_CAPSULE_RADIUS_PX - cs.BORDER_PX["std"]
        side = "left" if self._capsule_corner == "left" else "right"
        other = "right" if side == "left" else "left"
        return (
            f"border-top-{side}-radius: {r:g}px;"
            f" border-bottom-{side}-radius: {r:g}px;"
            f" border-top-{other}-radius: 0px;"
            f" border-bottom-{other}-radius: 0px;"
        )

    def _refresh_css(self) -> None:
        """Re-apply the current state's stylesheet, honouring the
        per-instance capsule-mode override on top of the shared
        per-theme cache. In capsule mode each cell paints its OWN
        state-coloured outline, so setting its stylesheet repaints
        everything a state change touches; the capsule frame no longer
        reflects state, so no parent repaint is needed."""
        if self._in_capsule:
            set_css(self, self._capsule_style(self._state))
            return
        set_css(self, self._styles[self._state])

    def set_in_capsule(self, in_capsule: bool) -> None:
        """Toggle the flat 'cell inside a pair capsule' styling. Reset
        to ``False`` when the pooled button returns to the consonant
        grid so it never renders borderless there."""
        if not in_capsule:
            self._capsule_corner = ""
        if self._in_capsule == in_capsule:
            return
        self._in_capsule = in_capsule
        self._refresh_css()

    def set_capsule_corner(self, corner: str) -> None:
        """Set which OUTER corners this END cell rounds inside a capsule
        ("left" / "right" / "" for a middle cell)."""
        if self._capsule_corner == corner:
            return
        self._capsule_corner = corner
        if self._in_capsule:
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
