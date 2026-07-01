"""Fluid grid of segment buttons. Re-flows on resize.

Owner pattern: the grid widget never constructs SegmentButtons; the
MainWindow pool feeds them via ``set_groups``. The widget owns
group HEADERS (created here) and the QGridLayout layout passes.
Spillover into a second column at the bottom is driven by the
shared ``layout.plan_seg_layout`` helper so the web grid uses the
same partition rules.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QFont, QResizeEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from phonology_features.gui.style_utils import set_css
from phonology_features.gui.widgets.segment_button import SegmentButton
from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation import layout as layout_mod
from phonology_shared.presentation.constants import BTN_GAP, BTN_W
from phonology_shared.presentation.layout import best_segment_n_cols
from phonology_shared.presentation.palette import C

# Per-button vertical stride used by ``SegmentGridWidget`` to estimate
# group natural heights ahead of Qt's own layout pass. The fixed values
# match what ``SegmentButton`` sets via ``setFixedSize(33, 26)`` and the
# 4-px row gap, plus the empirical 22-px header. Tweak together with the
# button or header style if either changes.
_SEG_BTN_H = 26
_SEG_HEADER_H = 22

# Live-resize debounce: a re-layout pass on a Hayes-sized grid is
# cheap (~5 ms) but Qt fires resizeEvent many times during a drag.
# 40 ms keeps re-flow responsive without burning cycles each tick.
_RESIZE_DEBOUNCE_MS = 40


class SegmentGridWidget(QWidget):
    """Fluid grid of segment buttons. Column count is recomputed from
    the current widget width on resize.
    """

    # Upper bound on segment-grid column count. Read from the shared
    # constant so the height predictor (``seg_pane_n_cols``) and Qt's
    # actual layout can't disagree on the cap.
    MAX_COLS = layout_mod.SEG_GRID_MAX_COLS

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: dict[str, list[str]] = {}
        self._buttons: dict[str, SegmentButton] = {}
        self._headers: list[QLabel] = []
        # Last value ``set_headers_active`` styled the headers with,
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
        # Horizontal: Preferred (parent splitter sets the bound).
        # Vertical: MinimumExpanding so the widget claims whatever
        # height ``left_wrap`` extends to (the seg-h-pair's tallest
        # member, typically the vowel chart). The spillover policy
        # uses that claimed height as its budget so dead space below
        # the natural consonant content turns into spillover room.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.MinimumExpanding,
        )
        self.setMinimumWidth(0)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._do_relayout)
        # ``set_groups`` runs during __init__ when the widget width is
        # ~0, so _compute_n_cols comes out as 1. The first post-show
        # resizeEvent must relayout SYNCHRONOUSLY so paint #1 already
        # shows the final column count; debouncing it would leave the
        # window flashing through the 1-col layout on startup. This
        # flag flips False after the first sync relayout; subsequent
        # resizes (live drag) keep the debounce.
        self._needs_sync_relayout = True
        # Cache so _do_relayout short-circuits when nothing
        # layout-relevant has changed. Saves the QGridLayout rebuild
        # and ~140 button setParent/show on every resize tick when the
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
        # Manner-class header chrome (font, weight, letter-spacing,
        # padding) lives in shared chart_style so the desktop QLabel
        # styling and the web's ``.seg-group-header`` CSS rule read
        # from one source. Before the relay, desktop used 8 pt Bold
        # with (4,2,1,2) padding while web used 11px / 600 with
        # (4,2,6,2).
        hdr_font = QFont("Noto Sans")
        hdr_font.setPixelSize(cs.SEG_GROUP_HEADER_FONT_PX)
        hdr_font.setWeight(QFont.Weight(cs.SEG_GROUP_HEADER_FONT_WEIGHT))
        for manner in groups:
            hdr = QLabel(manner.upper())
            hdr.setFont(hdr_font)
            set_css(hdr, self._header_style(C["text_dim"]))
            hdr.setParent(self)
            self._headers.append(hdr)
        self._n_cols = 0
        # The next resizeEvent should treat this as a fresh layout
        # (sync, not debounced) so a mid-app inventory swap doesn't
        # flash through a wrong column count either.
        self._needs_sync_relayout = True
        self._do_relayout()

    def apply_theme(self) -> None:
        """Invalidate the headers-active dedup cache so the next
        ``set_headers_active`` re-applies palette-dependent colors.
        """
        self._last_headers_active = None

    def _header_style(self, color: str) -> str:
        """Manner-class header QSS built from the relayed shared
        constants so ``set_groups`` and ``set_headers_active`` never
        drift on padding or letter-spacing.
        """
        pad = cs.SEG_GROUP_HEADER_PADDING_PX
        return (
            f"color: {color};"
            f" letter-spacing: {cs.SEG_GROUP_HEADER_LETTER_SPACING_PX}px;"
            f" padding: {pad[0]}px {pad[1]}px {pad[2]}px {pad[3]}px;"
        )

    def set_headers_active(self, active: bool) -> None:
        """Style headers for the given active state. Skips re-applying
        if the cached state matches; ``set_groups`` and ``apply_theme``
        both clear the cache to force a re-style.
        """
        if self._last_headers_active == active:
            return
        color = C["text"] if active else C["text_dim"]
        style = self._header_style(color)
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

    def request_sync_relayout(self) -> None:
        """Make the next resize relayout synchronously (no debounce).

        Used when a sibling's visibility change frees pane space the
        grid should reclaim immediately (e.g. the vowel chart hiding),
        so the spillover partition is not left stale until the next
        interaction-driven resize.
        """
        self._needs_sync_relayout = True

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        if self._needs_sync_relayout:
            self._needs_sync_relayout = False
            self._do_relayout()
            return
        self._resize_timer.start()

    def _clear_grid(self) -> None:
        """Empty the grid AND reset every row's minimum height.

        ``takeAt`` removes layout *items*, but ``setRowMinimumHeight``
        is a layout property that survives a rebuild and ``rowCount``
        never shrinks. Without zeroing the minimums, the inter-group
        spacer heights from a taller layout linger on rows a later,
        shorter layout leaves empty, padding the grid with phantom
        vertical gaps (e.g. swapping a large inventory for a small one).
        """
        while self._grid.count():
            self._grid.takeAt(0)
        for row in range(self._grid.rowCount()):
            self._grid.setRowMinimumHeight(row, 0)

    def _compute_n_cols(self) -> int:
        # Width-to-cols delegated to the shared layout helper so the
        # web's grid uses the same formula. The local
        # cap-at-group-size step stays here because it depends on the
        # widget's in-memory groups, which the pure-Python layout
        # module doesn't see.
        max_possible = layout_mod.seg_pane_n_cols(self.width())
        if not self._groups:
            return max_possible
        max_n = max(len(segs) for segs in self._groups.values())
        if max_n <= max_possible:
            return max_n
        return max_possible

    def _do_relayout(self) -> None:
        n_cols = self._compute_n_cols()
        available = self._available_pane_height()
        groups_items = list(self._groups.items())
        if not groups_items:
            self._n_cols = n_cols
            self._last_available_height = available
            self._last_main_count = 0
            self._clear_grid()
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
        # Geometry-aware layout plan: variable spillover column count
        # (driven by the widget's actual width) plus LPT bin-packing so
        # the spillover's bounding height is minimal. The
        # ``chart_rect=None`` path means spillover lives directly below
        # the main flow at this widget's bounds; the full "spillover
        # under the chart at full pane width" layout would move the
        # spillover to a separate sibling widget and is deferred.
        # ``min_col_w`` is the smallest column that hosts a half-width
        # pair so the existing visual stays familiar.
        slot_col_w = max(1, (n_cols - 1) // 2) * BTN_W + BTN_GAP
        group_widths = [
            best_segment_n_cols(len(segs), n_cols) * BTN_W
            + max(0, best_segment_n_cols(len(segs), n_cols) - 1) * BTN_GAP
            for (_, segs), _ in zip(groups_items, group_cols_main, strict=True)
        ]
        layout_plan = layout_mod.plan_seg_layout(
            [name for name, _ in groups_items],
            main_heights,
            group_widths,
            pane_w=max(self.width(), 0),
            pane_h=max(available, 0),
            chart_rect=None,
            min_col_w=slot_col_w,
        )
        # ``main_count`` is the number of groups in single-column main
        # flow at the top. Derived from the plan so the rest of the
        # rendering path stays the same.
        main_count = len(layout_plan.main_groups)
        # Short-circuit when the n_cols and partition decision both
        # match the previous layout; skips the rebuild on the
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
        self._clear_grid()

        grid_row = 0
        has_spillover = main_count < len(groups_items)
        hdr_iter = iter(self._headers)
        # Main flow. The header spans the full ``n_cols`` row so
        # headers align across groups, while each group's BUTTONS wrap
        # at the per-group ``group_cols_main`` count, which avoids
        # one-button orphan rows. Header span is intentionally
        # ``n_cols`` (not the per-group count) so the manner-class
        # titles line up along the same left edge.
        for main_idx, ((_manner, segs), g_cols) in enumerate(
            zip(
                groups_items[:main_count],
                group_cols_main[:main_count],
                strict=True,
            )
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
            # Reserve an extra-tall spacer row so the total vertical
            # distance between this group's last button and the next
            # group's header matches the web's ``.seg-group {
            # margin-bottom: var(--seg-group-gap); }``. The grid's
            # default row stride is ``BTN_GAP``; bumping this row to
            # ``SEG_GROUP_GAP_PX`` (8 px) adds the remaining 4 px.
            # Skipped after the very last main group when no spillover
            # follows, so the grid's bottom carries no trailing empty
            # spacer row.
            is_last_main = main_idx == main_count - 1
            extra = max(0, cs.SEG_GROUP_GAP_PX - BTN_GAP)
            if extra and not (is_last_main and not has_spillover):
                self._grid.setRowMinimumHeight(grid_row, extra)
                grid_row += 1

        # Spillover is ``layout_plan.n_spillover_cols`` columns wide,
        # with the LPT column assignment supplied per group. Groups
        # stack column-major: within each column they appear in source
        # order, top to bottom, and LPT determines which column each
        # lands in. Same QGridLayout as the main flow so a follow-up
        # "spillover under chart at full pane width" only needs to move
        # the widget, not the rendering scheme.
        spill = groups_items[main_count:]
        n_spill_cols = max(1, layout_plan.n_spillover_cols) if spill else 0
        col_assignment = layout_plan.spillover_column_assignment
        if spill:
            gap_cols = n_spill_cols - 1
            slot_cols = max(1, (n_cols - gap_cols) // n_spill_cols)
            column_next_row = [grid_row] * n_spill_cols
            for spill_idx, (_manner, segs) in enumerate(spill):
                col_idx = (
                    col_assignment[spill_idx]
                    if spill_idx < len(col_assignment)
                    else 0
                )
                col_idx = max(0, min(col_idx, n_spill_cols - 1))
                slot_row = column_next_row[col_idx]
                col_start = col_idx * (slot_cols + 1)
                hdr = next(hdr_iter)
                self._grid.addWidget(hdr, slot_row, col_start, 1, slot_cols)
                hdr.show()
                group_cols = best_segment_n_cols(len(segs), slot_cols)
                for seg_i, seg in enumerate(segs):
                    btn = self._buttons[seg]
                    br = slot_row + 1 + seg_i // max(group_cols, 1)
                    bc = col_start + (seg_i % max(group_cols, 1))
                    self._grid.addWidget(btn, br, bc)
                    btn.show()
                n_btn_rows = math.ceil(len(segs) / max(group_cols, 1))
                column_next_row[col_idx] = slot_row + 1 + n_btn_rows
            grid_row = max(column_next_row)

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
