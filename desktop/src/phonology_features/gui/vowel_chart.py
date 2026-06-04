"""Qt thin shell that renders the shared vowel chart geometry.

All placement decisions, collision grouping, and physical-
coordinate arithmetic live in
:py:mod:`phonology_shared.chart.vowels`. This module
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
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phonology_shared.chart.vowels import (
    COL_LABELS,
    ROW_LABELS,
    Confidence,
    VowelChartCell,
    VowelChartGeometry,
    VowelChartShape,
    VowelChartSilhouette,
    VowelPlacement,
    VowelProfile,
    build_vowel_chart_geometry,
    detect_vowel_profile,
    vowel_silhouette,
)
from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    REGION_CONSTRAINTS,
    VOWEL_PAIR_GAP_PX,
)
from phonology_shared.presentation.palette import C

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

    # Chrome dimensions for the outer rectangular UI space. The
    # title / column headers stack at the top; row labels sit on
    # the left; the trapezoidal data area takes the remaining
    # rectangle. The bottom and right paddings give the trapezoid
    # silhouette a small inset from the widget border so the cells
    # at the open / back edges have visible breathing room.
    _TITLE_H: ClassVar[int] = 20
    _COL_HEADER_H: ClassVar[int] = 18
    _PAD_R: ClassVar[int] = 12
    _PAD_B: ClassVar[int] = 10
    # Pixel gap between a row label's right edge and the silhouette's
    # slanted left edge at that row. Loose enough that the label and
    # the trapezoid read as separate elements; web mirrors this via
    # the ``--space-md`` token in ``style.css``.
    _ROW_LABEL_GAP_PX: ClassVar[int] = 10

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
        # Transparent so the enclosing seg-panel's surface color shows
        # through. Without this the widget paints an opaque palette
        # window (white) regardless of whether the seg pane is active
        # or inactive, leaving the trapezoid sitting on a white patch
        # against the inactive panel's grey bg.
        self.setStyleSheet("background: transparent;")
        # The widget owns these directly; no layout manager. Children
        # are positioned absolutely from ``_layout_children``, which
        # runs on ``set_vowels`` and on every ``resizeEvent`` so the
        # cells, headers, and row labels track the widget's size.
        self._buttons: dict[str, QWidget] = {}
        self._title_label: QLabel | None = None
        # Column / row labels with their normalised positions
        # (chart_x for columns, chart_y for rows) so resize can
        # re-place them without re-fetching the geometry.
        self._col_labels: list[tuple[QLabel, float]] = []
        self._row_labels: list[tuple[QLabel, float]] = []
        # Cell widgets (segment buttons or vbox stacks for collision
        # cells) carry their chart_x / chart_y plus a pair_side
        # signed multiplier (-1 / 0 / +1). The resize pass projects
        # them to pixel positions: the anchor follows the trapezoid
        # silhouette, then a FIXED pair shift in pixels keeps
        # rounded/unrounded mates exactly tangent regardless of how
        # narrow the row becomes. The back-line snap-to-button-centre
        # decision lives on the shared
        # ``VowelChartSilhouette.back_right_pixel_offset`` field so
        # the renderer does not need each cell's ``col``.
        self._cells: list[tuple[QWidget, float, float, int]] = []
        self._cell_containers: list[QWidget] = []
        # Cached header styles, rebuilt by apply_theme each toggle.
        self._HDR_ACTIVE = ""
        self._HDR_INACTIVE = ""
        self._ROW_ACTIVE = ""
        self._ROW_INACTIVE = ""
        self._rebuild_style_cache()
        # Last ``active`` value styled into the headers; cleared by
        # clear() and apply_theme() to force a re-style.
        self._last_headers_active: bool | None = None
        # Shape envelope. ``paintEvent`` consumes it to draw the
        # trapezoid or triangle silhouette behind the data area
        # only (not under the row labels or column headers).
        self._shape: VowelChartShape = VowelChartShape.TRAPEZOID
        # Silhouette corners for the current inventory. Populated
        # by :py:meth:`_render_geometry` from the shared
        # :py:attr:`VowelChartGeometry.silhouette` so the outline
        # adapts to the populated row range (e.g. a Spanish
        # inventory whose lowest row is Open uses the canonical
        # narrow bottom; one whose lowest row is Open-mid carries
        # a wider bottom edge). ``None`` before the first render.
        self._silhouette: VowelChartSilhouette | None = None
        # Floor for ``set_target_width``: the geometry's natural
        # data width plus this widget's chrome. Updated on every
        # :py:meth:`_render_geometry` call so external resize
        # requests below this floor are clamped, keeping cells
        # legible when an inventory needs more horizontal room than
        # the canonical ``layout.VOWEL_NATURAL_W``.
        self._natural_total_w: int = 0
        # Cell width hint used to inset the data rectangle so cells
        # placed at chart_x == 0 / 1 stay fully inside the trapezoid
        # instead of clipping at the left / right edge. Populated
        # from the first cell that lands inside, defaults to the
        # consonant button width as a sensible floor.
        self._cell_w_hint: int = 36

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
        ``setFixedWidth`` once at construction. The external target
        is clamped to ``self._natural_total_w``: if the current
        inventory needs more horizontal room than ``w`` to fit its
        cells side-by-side, the natural floor wins so callers can't
        squeeze the chart below its content's needs.
        """
        effective_w = max(w, self._natural_total_w)
        self.setMinimumWidth(effective_w)
        self.setMaximumWidth(effective_w)

    def set_headers_active(self, active: bool) -> None:
        # Dedup is safe: clear() (called by set_vowels on every
        # inventory swap) resets ``_last_headers_active`` to None
        # when fresh labels replace the cached ones.
        if self._last_headers_active == active:
            return
        header_style = self._HDR_ACTIVE if active else self._HDR_INACTIVE
        row_style = self._ROW_ACTIVE if active else self._ROW_INACTIVE
        if self._title_label is not None:
            self._title_label.setStyleSheet(
                f"color: {C['text' if active else 'text_dim']};"
                " letter-spacing: 1px; padding: 2px 2px 0 2px;"
            )
        for lbl, _ in self._col_labels:
            lbl.setStyleSheet(header_style)
        for lbl, _ in self._row_labels:
            lbl.setStyleSheet(row_style)
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
        if self._title_label is not None:
            self._title_label.deleteLater()
            self._title_label = None
        for lbl, _ in self._col_labels:
            lbl.deleteLater()
        self._col_labels.clear()
        for lbl, _ in self._row_labels:
            lbl.deleteLater()
        self._row_labels.clear()
        self._cells.clear()
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

        The geometry pass (placement, collision grouping, and
        physical-coordinate arithmetic) all happens in
        :py:mod:`vowel_layout`; this method only translates the
        result into widget calls.
        """
        self.clear()
        self._buttons = dict(buttons)
        profile = detect_vowel_profile(segs, norm_feats)
        geometry = build_vowel_chart_geometry(segs, profile, norm_feats)
        self._render_geometry(geometry)

    def _render_geometry(self, geometry: VowelChartGeometry) -> None:
        """Translate the shared geometry into Qt widgets.

        Builds title, column header labels, row labels, and one
        widget per data cell. None of them are laid out yet; the
        actual positions land in :py:meth:`_layout_children`, which
        also runs on every ``resizeEvent`` so the absolute-positioned
        children track the widget's size.
        """
        self._shape = geometry.shape
        self._silhouette = geometry.silhouette
        # Growth policy: when the inventory's natural data width
        # exceeds the canonical chart width that ``set_target_width``
        # would set, expand the widget so all cells stay legible
        # side-by-side. Stash the natural total so
        # :py:meth:`set_target_width` honors the floor on subsequent
        # external resize requests.
        chrome_w = VOWEL_LABEL_W + self._PAD_R
        self._natural_total_w = geometry.natural_data_width_px + chrome_w
        if self._natural_total_w > self.width():
            self.setMinimumWidth(self._natural_total_w)
            self.setMaximumWidth(self._natural_total_w)
        # Title (top, centred over the data area).
        title = QLabel(geometry.title, self)
        title.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {C['text_dim']}; letter-spacing: 1px;"
            " padding: 2px 2px 0 2px;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.adjustSize()
        title.show()
        self._title_label = title
        # Column headers: positioned at the backness anchor for
        # each column (front / central / back) so the labels line
        # up with the cells in the widest row of the trapezoid.
        for col in geometry.cols:
            lbl = QLabel(col.label, self)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(self._HDR_INACTIVE)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.adjustSize()
            lbl.show()
            self._col_labels.append((lbl, col.chart_x))
        # Row labels: positioned at chart_y on the left gutter.
        for row in geometry.rows:
            lbl = QLabel(row.label, self)
            lbl.setFont(QFont("Noto Sans", 7))
            lbl.setStyleSheet(self._ROW_INACTIVE)
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lbl.adjustSize()
            lbl.show()
            self._row_labels.append((lbl, row.chart_y))
        # Data cells: collected with their chart_x / chart_y; the
        # layout pass turns those into pixel positions.
        for cell in geometry.cells:
            widget = self._build_cell(cell)
            if widget is None:
                continue
            self._cells.append(
                (widget, cell.chart_x, cell.chart_y, cell.pair_side)
            )
        self._layout_children()
        self.update()

    def _build_cell(self, cell: VowelChartCell) -> QWidget | None:
        """Return the widget that represents ``cell`` -- a single
        button for the common case, a hbox pair when the cell
        carries a Long contrast (same vowel-space position, two
        durations), and a vbox stack otherwise. Returns ``None`` if
        none of the segments have a backing button (defensive;
        should not happen in normal flow).
        """
        if len(cell.entries) == 1:
            btn = self._buttons.get(cell.entries[0])
            if btn is None:
                return None
            btn.setParent(self)
            btn.show()
            return btn
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")
        self._cell_containers.append(container)
        if cell.is_long_pair:
            layout: QHBoxLayout | QVBoxLayout = QHBoxLayout(container)
            layout.setSpacing(VOWEL_PAIR_GAP_PX)
        else:
            layout = QVBoxLayout(container)
            layout.setSpacing(1)
        layout.setContentsMargins(0, 0, 0, 0)
        added = False
        for seg in cell.entries:
            btn = self._buttons.get(seg)
            if btn is not None:
                btn.show()
                layout.addWidget(btn)
                added = True
        if not added:
            self._cell_containers.remove(container)
            container.deleteLater()
            return None
        container.adjustSize()
        container.show()
        return container

    def _data_area_rect(self) -> tuple[int, int, int, int]:
        """``(x, y, width, height)`` of the trapezoidal segment
        display space inside the rectangular widget. The chrome
        (title, column headers, row label gutter, right / bottom
        padding) is excluded so labels sit OUTSIDE the silhouette.
        """
        x = VOWEL_LABEL_W
        y = self._TITLE_H + self._COL_HEADER_H
        w = max(0, self.width() - x - self._PAD_R)
        h = max(0, self.height() - y - self._PAD_B)
        return x, y, w, h

    def _layout_children(self) -> None:
        """Place title, headers, row labels, and cells.

        Headers and row labels go in the rectangular chrome; cells
        go inside the trapezoidal data area at their projected
        ``(chart_x, chart_y)``. Re-runs on every ``resizeEvent``.
        """
        dx, dy, dw, dh = self._data_area_rect()
        if self._title_label is not None:
            self._title_label.adjustSize()
            tw = self._title_label.width()
            self._title_label.move(dx + (dw - tw) // 2, 0)
        # Column headers: x in [0, 1] mapped across the data area,
        # then centred on each anchor.
        for lbl, x in self._col_labels:
            lbl.adjustSize()
            lw = lbl.width()
            px = dx + int(x * dw) - lw // 2
            lbl.move(px, self._TITLE_H)
        # Row labels: positioned at chart_y, right-aligned against
        # the silhouette's slanted left edge at this row so the label
        # follows the trapezoid inward as it shrinks. Falls back to
        # the data area's left gutter when no silhouette has been
        # rendered yet. The gap keeps the label off the slant stroke
        # so the two read as separate elements; web mirrors the value
        # in style.css.
        sil = self._silhouette
        label_gap_px = self._ROW_LABEL_GAP_PX
        for lbl, y in self._row_labels:
            lbl.adjustSize()
            lh = lbl.height()
            py = dy + int(y * dh) - lh // 2
            if sil is not None and sil.bottom_y > sil.top_y:
                t = (y - sil.top_y) / (sil.bottom_y - sil.top_y)
                t = max(0.0, min(1.0, t))
                left_norm = sil.top_left + (sil.bottom_left - sil.top_left) * t
                anchor_x = dx + int(left_norm * dw)
            else:
                anchor_x = dx
            px = anchor_x - lbl.width() - label_gap_px
            lbl.move(max(0, px), py)
        # Cells: position concern (anchor) + display concern (pair
        # shift). ``chart_x`` / ``chart_y`` are the backness anchor
        # already projected through the chart silhouette; the pair
        # shift is a FIXED pixel offset of half a button width plus
        # half the within-pair gap, multiplied by ``pair_side``
        # (-1 unrounded, 0 unknown, +1 rounded). Keeping the pair
        # shift in pixels means rounded/unrounded mates stay
        # exactly tangent at every row of the trapezoid.
        pair_shift_px = (BTN_W + VOWEL_PAIR_GAP_PX) // 2
        for widget, cx, cy, pair_side in self._cells:
            widget.adjustSize()
            ww = widget.width()
            wh = widget.height()
            if ww > self._cell_w_hint:
                self._cell_w_hint = ww
            px = dx + int(cx * dw) - ww // 2 + pair_side * pair_shift_px
            py = dy + int(cy * dh) - wh // 2
            widget.move(px, py)

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._layout_children()

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: D401
        """Paint the trapezoid (or triangle) silhouette behind the
        data area only.

        The chrome (title, column headers, row label gutter) sits
        in the rectangular outer space and is not covered by the
        silhouette, so the distinction between UI space and segment
        display space stays visible.
        """
        super().paintEvent(event)
        dx, dy, dw, dh = self._data_area_rect()
        if dw <= 0 or dh <= 0:
            return
        # Silhouette corners come from the geometry the bridge
        # built for this inventory (adapted to its populated row
        # range). Falls back to the canonical 7-row silhouette
        # before the first render so an empty widget paints
        # something sensible. The right edge sits on the back-
        # pair's outer extent (back vowels are flush against it)
        # and the left edge slants from the topmost row's front
        # position to the bottommost row's front position.
        sil = self._silhouette
        if sil is None:
            # No inventory rendered yet -- use the canonical silhouette
            # so a pre-load paint still shows the trapezoid outline.
            sil = vowel_silhouette(self._shape)
        top_y = dy + int(sil.top_y * dh)
        bottom_y = dy + int(sil.bottom_y * dh)
        top_left_x = dx + int(sil.top_left * dw)
        bottom_left_x = dx + int(sil.bottom_left * dw)
        # Back edge: ``top_right`` is the back ANCHOR (normalised);
        # the fixed-pixel ``back_right_pixel_offset`` captures the
        # rest. The same formula runs on the web (via the bridge
        # payload), so both UIs land the line at the same place
        # regardless of how wide the data area is rendered. The
        # asymmetric pull-in (snap to back-vowel centre rather than
        # the canonical pair-outer extent) is encoded in the offset
        # by ``build_vowel_chart_geometry``; the renderer just adds.
        back_right_x = (
            dx + int(sil.top_right * dw) + sil.back_right_pixel_offset
        )
        top_right_x = back_right_x
        bottom_right_x = back_right_x
        path = QPainterPath()
        path.moveTo(top_left_x, top_y)
        path.lineTo(top_right_x, top_y)
        path.lineTo(bottom_right_x, bottom_y)
        path.lineTo(bottom_left_x, bottom_y)
        path.closeSubpath()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Outline only, no painted fill: the trapezoid is a
        # structural guide, not a coloured region. Two-pixel stroke
        # in the standard ``border`` colour mirrors the web's
        # ``::before`` / ``::after`` outline-only treatment.
        pen = QPen(QColor(C["border"]))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()
