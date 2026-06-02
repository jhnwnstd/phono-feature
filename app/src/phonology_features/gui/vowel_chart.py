"""IPA-style vowel trapezoid chart. Maps vowel segments onto a
height x backness x rounding grid using normalised phonological
features. A VowelProfile is computed per inventory so fallback logic
only fires when the inventory actually lacks the direct feature.
Each placement carries a confidence level and a reason string that
surface as tooltips on the buttons.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from phonology_features.gui.shared.palette import C
from phonology_features.gui.shared.vowel_layout import (
    ROW_LABELS,
    Confidence,
    VowelPlacement,
    VowelProfile,
)
from phonology_features.gui.shared.vowel_layout import (
    compute_placements as _compute_placements_shared,
)
from phonology_features.gui.shared.vowel_layout import (
    detect_vowel_profile as _detect_vowel_profile,
)

# Re-exports preserved for any external importer that read these
# from vowel_chart directly. Canonical definitions live in
# gui.vowel_layout so the web app sees the same values.
__all__ = [
    "VOWEL_LABEL_W",
    "Confidence",
    "VowelChartWidget",
    "VowelPlacement",
    "VowelProfile",
]

VOWEL_LABEL_W = 72
_ROW_LABELS = ROW_LABELS


class VowelChartWidget(QWidget):
    """Displays vowels in an IPA-style grid: height x backness x rounding."""

    _COL_HEADERS: ClassVar[tuple[str, ...]] = (
        "Front",
        "Central",
        "Back",
    )
    _ROW_HEADERS: ClassVar[tuple[str, ...]] = tuple(_ROW_LABELS)

    def __init__(
        self, parent: QWidget | None = None, *, btn_gap: int = 4
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QWidget] = {}
        self._header_labels: list[tuple[QLabel, bool]] = []
        self._cell_containers: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(btn_gap)
        self._grid.setContentsMargins(0, 0, 8, 0)
        # Cached header styles, rebuilt by apply_theme each toggle.
        self._HDR_ACTIVE = ""
        self._HDR_INACTIVE = ""
        self._ROW_ACTIVE = ""
        self._ROW_INACTIVE = ""
        self._rebuild_style_cache()
        # Last ``active`` value styled into the headers; cleared by
        # clear() and apply_theme() to force a re-style.
        self._last_headers_active: bool | None = None

    def _rebuild_style_cache(self) -> None:
        self._HDR_ACTIVE = f"color: {C['text']};"
        self._HDR_INACTIVE = f"color: {C['text_dim']};"
        self._ROW_ACTIVE = f"color: {C['text']}; padding-right: 4px;"
        self._ROW_INACTIVE = f"color: {C['text_dim']}; padding-right: 4px;"

    def apply_theme(self) -> None:
        """Re-style cached header strings against the active palette
        and force the next ``set_headers_active`` to re-apply.
        """
        self._rebuild_style_cache()
        self._last_headers_active = None

    def set_target_width(self, w: int) -> None:
        """Push the chart's width from the outside (the seg-pane
        controller in ``main_window``) instead of pulling via
        ``setFixedWidth`` once at construction. Width is decided by
        the shared :py:func:`layout.vowel_chart_width`; the chart
        itself doesn't re-measure on resize, which keeps the layout
        pass cheap when the user drags the splitter.
        """
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)

    def set_headers_active(self, active: bool) -> None:
        # Dedup is safe: clear() (called by set_vowels on
        # every inventory swap) resets ``_last_headers_active`` to None
        # when fresh labels replace the cached ones.
        if self._last_headers_active == active:
            return
        if active:
            header_style = self._HDR_ACTIVE
            row_style = self._ROW_ACTIVE
        else:
            header_style = self._HDR_INACTIVE
            row_style = self._ROW_INACTIVE
        for lbl, is_row in self._header_labels:
            if is_row:
                lbl.setStyleSheet(row_style)
            else:
                lbl.setStyleSheet(header_style)
        self._last_headers_active = active

    def clear(self) -> None:
        """Remove all buttons, labels, and collision containers.
        Buttons are detached (not destroyed) since they belong to the
        caller's pool. Detaching them BEFORE deleting cell containers
        is essential; otherwise destroying the container would take
        the children with it.
        """
        for btn in self._buttons.values():
            btn.setParent(None)
        self._buttons.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        for lbl, _ in self._header_labels:
            lbl.deleteLater()
        self._header_labels.clear()
        self._last_headers_active = None
        for container in self._cell_containers:
            container.deleteLater()
        self._cell_containers.clear()

    def set_vowels(
        self,
        segs: list[str],
        buttons: Mapping[str, QWidget],
        norm_feats: Mapping[str, Mapping[str, str]],
    ) -> None:
        """Lay out vowel buttons in the IPA chart grid."""
        self.clear()
        self._buttons = dict(buttons)
        profile = _detect_vowel_profile(segs, norm_feats)
        self._add_top_headers()
        occupied, placements = self._compute_placements(
            segs, profile, norm_feats
        )
        self._lay_out_rows(occupied, placements)

    def _add_top_headers(self) -> None:
        """VOWELS title (spanning all columns) + Front/Central/Back
        labels. Labels are parented at construction so they're never
        transient top-level widgets.
        """
        title = QLabel("VOWELS", self)
        title.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
            " padding: 2px 2px 0 2px;"
        )
        # Span the data columns only (skip col 0, the row-label gutter)
        # so the title sits flush with the vowel cells, not the row
        # labels.
        self._grid.addWidget(title, 0, 1, 1, 6)
        self._header_labels.append((title, False))
        for ci, label in enumerate(self._COL_HEADERS):
            lbl = QLabel(label, self)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(lbl, 1, 1 + ci * 2, 1, 2)
            self._header_labels.append((lbl, False))

    @staticmethod
    def _compute_placements(
        segs: list[str],
        profile: VowelProfile,
        norm_feats: Mapping[str, Mapping[str, str]],
    ) -> tuple[
        dict[tuple[int, int], list[str]],
        dict[str, VowelPlacement],
    ]:
        """Thin wrapper over the shared
        :py:func:`vowel_layout.compute_placements`.

        Kept as a staticmethod for the existing call site inside
        :py:meth:`set_vowels`; the canonical implementation lives in
        the shared module so the web bridge can use the same
        cell-grouping rule. Returns ``(occupied, placements)``.
        """
        return _compute_placements_shared(segs, profile, norm_feats)

    def _lay_out_rows(
        self,
        occupied: dict[tuple[int, int], list[str]],
        placements: dict[str, VowelPlacement],
    ) -> None:
        """For each height tier that has at least one vowel, add a row
        header on the left and place each cell's buttons in the grid."""
        grid_row = 2
        for ri, label in enumerate(self._ROW_HEADERS):
            if not any((ri, col) in occupied for col in range(6)):
                continue
            self._add_row_header(label, grid_row)
            for ci in range(6):
                cell_segs = occupied.get((ri, ci), [])
                if cell_segs:
                    self._place_cell(cell_segs, placements, grid_row, ci)
            grid_row += 1

    def _add_row_header(self, label: str, grid_row: int) -> None:
        lbl = QLabel(label, self)
        lbl.setFont(QFont("Noto Sans", 7))
        lbl.setStyleSheet(f"color: {C['text_dim']}; padding-right: 4px;")
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        lbl.setMinimumWidth(VOWEL_LABEL_W - 4)
        self._grid.addWidget(lbl, grid_row, 0)
        self._header_labels.append((lbl, True))

    def _place_cell(
        self,
        cell_segs: list[str],
        placements: dict[str, VowelPlacement],
        grid_row: int,
        ci: int,
    ) -> None:
        """Place one cell's button(s) in the grid. Single vowel: button
        goes straight in. Multiple vowels at the same (row, col): stack
        them in a transparent vbox container that we own.
        """
        if len(cell_segs) == 1:
            seg = cell_segs[0]
            btn = self._buttons.get(seg)
            if btn:
                self._prep_button(btn, seg, placements[seg])
                self._grid.addWidget(btn, grid_row, 1 + ci)
            return
        # Parented at construction so the container is never a
        # transient top-level widget during the brief gap before
        # ``self._grid.addWidget`` re-parents it.
        cell = QWidget(self)
        cell.setStyleSheet("background: transparent;")
        self._cell_containers.append(cell)
        vbox = QVBoxLayout(cell)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(1)
        added = False
        for seg in cell_segs:
            btn = self._buttons.get(seg)
            if btn:
                self._prep_button(btn, seg, placements[seg])
                vbox.addWidget(btn)
                added = True
        if added:
            self._grid.addWidget(cell, grid_row, 1 + ci)
        else:
            self._cell_containers.remove(cell)
            cell.deleteLater()

    @staticmethod
    def _prep_button(
        btn: QWidget, seg: str, placement: VowelPlacement
    ) -> None:
        """Set the tooltip + show. Shared by single + collision cells."""
        btn.setToolTip(
            f"/{seg}/  [{placement.confidence.name.lower()}]"
            f"  {placement.reason}"
        )
        btn.show()
