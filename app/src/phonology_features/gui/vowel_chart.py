"""Qt thin shell that renders the shared vowel chart geometry.

All placement decisions, collision grouping, tooltip formatting,
and physical-coordinate arithmetic live in
:py:mod:`phonology_shared.render.vowel_layout`. This module
walks the pre-built :py:class:`~vowel_layout.VowelChartGeometry`
and emits Qt widgets: labels for headers + rows, buttons (single
cells) or vbox stacks (collision cells) for the data cells.

The web counterpart (``web/main.js:_buildVowelChart``) is the
analogous thin shell on the browser side; both consume the same
geometry object from the bridge.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phonology_shared.render.layout import (
    REGION_CONSTRAINTS,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)
from phonology_shared.render.palette import C
from phonology_shared.render.vowel_layout import (
    COL_LABELS,
    ROW_LABELS,
    Confidence,
    VowelChartCell,
    VowelChartCellEntry,
    VowelChartGeometry,
    VowelChartRow,
    VowelPlacement,
    VowelProfile,
    build_vowel_chart_geometry,
    detect_vowel_profile,
)

# Re-exports preserved for any external importer that read these
# from vowel_chart directly. Canonical definitions live in
# vowel_layout.py so the web app sees the same values.
__all__ = [
    "VOWEL_LABEL_W",
    "Confidence",
    "VowelChartWidget",
    "VowelPlacement",
    "VowelProfile",
]

# Width floor for the row-label gutter. Qt-only; the web sets its
# row-label column via CSS ``minmax(60px, auto)``.
VOWEL_LABEL_W = 72


class VowelChartWidget(QWidget):
    """Renders the shared :py:class:`VowelChartGeometry` as Qt
    widgets.

    The widget owns its row-label / header QLabels and any
    collision-cell containers it creates; segment buttons are
    detached on :py:meth:`clear` because they belong to the
    caller's button pool.
    """

    _COL_HEADERS: ClassVar[tuple[str, ...]] = COL_LABELS
    _ROW_HEADERS: ClassVar[tuple[str, ...]] = ROW_LABELS

    def __init__(
        self, parent: QWidget | None = None, *, btn_gap: int = 4
    ) -> None:
        super().__init__(parent)
        # Width is externally clamped by ``set_target_width`` to the
        # constraint table's fixed value; height grows with row count.
        _constraint = REGION_CONSTRAINTS["vowel_chart"]
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        self.setMinimumHeight(_constraint.min_h)
        self._buttons: dict[str, QWidget] = {}
        self._header_labels: list[tuple[QLabel, bool]] = []
        self._cell_containers: list[QWidget] = []
        self._grid = QGridLayout(self)
        # Asymmetric column spacing: the horizontal gap is the tight
        # within-pair value, and the two spacer columns (3, 6) get
        # the inter-pair separator as a minimum width. Vertical gap
        # stays at ``btn_gap`` so row-to-row breathing room matches
        # the consonant grid.
        self._grid.setHorizontalSpacing(VOWEL_PAIR_GAP_PX)
        self._grid.setVerticalSpacing(btn_gap)
        # Spacer columns between front<->central and central<->back
        # pairs. Logical 0..5 from the placement code map to physical
        # grid columns 1, 2, 4, 5, 7, 8 (with row labels at column 0
        # and spacers at columns 3, 6).
        self._grid.setColumnMinimumWidth(3, VOWEL_PAIR_SEPARATOR_PX)
        self._grid.setColumnMinimumWidth(6, VOWEL_PAIR_SEPARATOR_PX)
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
        # Dedup is safe: clear() (called by set_vowels on every
        # inventory swap) resets ``_last_headers_active`` to None
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
        Buttons are detached (not destroyed) since they belong to
        the caller's pool. Detaching them BEFORE deleting cell
        containers is essential; otherwise destroying the container
        would take the children with it.
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
        """Build the shared geometry, then render it as Qt widgets.

        The geometry pass (placement, collision grouping, tooltip
        formatting, physical-coordinate arithmetic) all happens in
        :py:mod:`vowel_layout`; this method only translates the
        result into widget calls.
        """
        self.clear()
        self._buttons = dict(buttons)
        profile = detect_vowel_profile(segs, norm_feats)
        geometry = build_vowel_chart_geometry(segs, profile, norm_feats)
        self._render_geometry(geometry)

    def _render_geometry(self, geometry: VowelChartGeometry) -> None:
        """Walk the geometry and emit one Qt widget per item.

        Order: title row, col headers, then per row a row label
        followed by per-cell buttons (or a vbox stack for collision
        cells).
        """
        self._add_title_and_col_headers(geometry.cols)
        for row in geometry.rows:
            self._add_row_header(row)
        for cell in geometry.cells:
            self._add_cell(cell)

    def _add_title_and_col_headers(self, cols: tuple[str, ...]) -> None:
        """VOWELS title (spanning all data columns) + Front /
        Central / Back labels. Parented at construction so they're
        never transient top-level widgets.
        """
        title = QLabel("VOWELS", self)
        title.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
            " padding: 2px 2px 0 2px;"
        )
        # Span every data column (including the two spacer columns)
        # so the title sits flush with the vowel cells, not the row
        # labels. Physical columns: 1..8 (front 1-2, spacer 3,
        # central 4-5, spacer 6, back 7-8).
        self._grid.addWidget(title, 0, 1, 1, 8)
        self._header_labels.append((title, False))
        for ci, label in enumerate(cols):
            lbl = QLabel(label, self)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(f"color: {C['text_dim']};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Each backness header straddles its pair: ci=0 (Front)
            # at col 1 span 2, ci=1 (Central) at col 4 span 2,
            # ci=2 (Back) at col 7 span 2.
            self._grid.addWidget(lbl, 1, 1 + ci * 3, 1, 2)
            self._header_labels.append((lbl, False))

    def _add_row_header(self, row: VowelChartRow) -> None:
        lbl = QLabel(row.label, self)
        lbl.setFont(QFont("Noto Sans", 7))
        lbl.setStyleSheet(f"color: {C['text_dim']}; padding-right: 4px;")
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        lbl.setMinimumWidth(VOWEL_LABEL_W - 4)
        self._grid.addWidget(lbl, row.grid_row, 0)
        self._header_labels.append((lbl, True))

    def _add_cell(self, cell: VowelChartCell) -> None:
        """Single entry: button straight in. Multiple entries:
        stack them in a transparent vbox container."""
        if len(cell.entries) == 1:
            entry = cell.entries[0]
            btn = self._buttons.get(entry.seg)
            if btn:
                self._prep_button(btn, entry)
                self._grid.addWidget(btn, cell.grid_row, cell.grid_col)
            return
        # Parented at construction so the container is never a
        # transient top-level widget during the brief gap before
        # ``self._grid.addWidget`` re-parents it.
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")
        self._cell_containers.append(container)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(1)
        added = False
        for entry in cell.entries:
            btn = self._buttons.get(entry.seg)
            if btn:
                self._prep_button(btn, entry)
                vbox.addWidget(btn)
                added = True
        if added:
            self._grid.addWidget(container, cell.grid_row, cell.grid_col)
        else:
            self._cell_containers.remove(container)
            container.deleteLater()

    @staticmethod
    def _prep_button(btn: QWidget, entry: VowelChartCellEntry) -> None:
        """Attach the prebaked tooltip + show. The tooltip string is
        formatted by the shared :py:func:`vowel_layout.vowel_tooltip`
        so the desktop and web read the same text."""
        btn.setToolTip(entry.tooltip)
        btn.show()
