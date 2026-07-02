"""Qt thin shell that renders the shared vowel chart geometry.

All placement decisions, collision grouping, and physical
coordinate arithmetic live in
:py:mod:`phonology_shared.chart.vowels`. This module walks the
pre-built :py:class:`~vowel_layout.VowelChartGeometry` and emits Qt
widgets: labels for headers and rows, buttons (single cells) or vbox
stacks (collision cells) for the data cells.

The web counterpart (``web/main.js:_buildVowelChart``) is the analogous
thin shell on the browser side; both consume the same geometry object
from the bridge.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import ClassVar

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phonology_features.gui.widgets.segment_button import SegmentButton
from phonology_features.gui.widgets.vowel_pair_capsule import (
    VowelPairCapsule,
)
from phonology_shared.chart.vowel_geometry import (
    PAIR_DISPLAY_KINDS,
    VowelChartCell,
    VowelChartGeometry,
    VowelChartSilhouette,
    build_vowel_chart_geometry,
    effective_button_height_px,
    inset_silhouette_for_draw,
    label_midpoint_norm,
    silhouette_for_data_width,
    silhouette_left_at_y,
    vowel_silhouette,
)
from phonology_shared.chart.vowel_space import (
    COL_LABELS,
    ROW_LABELS,
)
from phonology_shared.chart.vowels import (
    VowelCellDisplayKind,
    VowelChartShape,
    detect_vowel_profile,
)
from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation.constants import (
    BTN_GAP,
    VOWEL_CHART_ACCESSIBLE_NAME,
)
from phonology_shared.presentation.layout import (
    MIN_VOWEL_CHART_W_PX,
    REGION_CONSTRAINTS,
    SEG_BTN_H,
)
from phonology_shared.presentation.palette import C

# Public surface. The placement-layer types (Confidence,
# VowelPlacement, VowelProfile) are NOT re-exported; importers
# pull them directly from ``phonology_shared.chart.vowels``.
__all__ = [
    "VOWEL_LABEL_W",
    "VowelChartWidget",
]

# Width floor for the row-label gutter. Lives in shared
# ``chart_style.VOWEL_CHART_ROW_LABEL_GUTTER_PX`` so the web's CSS
# grid-template-columns and desktop's gutter math read the same value.
# Re-exported here for any existing importer.
VOWEL_LABEL_W = cs.VOWEL_CHART_ROW_LABEL_GUTTER_PX

# Desktop's platform adjustment to the shared canonical chart-width floor
# (``MIN_VOWEL_CHART_W_PX`` in layout.py). The shared layer owns the
# canonical math; each renderer adds its own platform-specific offset to
# land at the rendered floor for its platform.
#
# A desktop-specific adjustment exists because Qt's frame rendering (the
# splitter handle reserves border pixels), QFont metrics rounding,
# QPainter sub-pixel anti-aliasing, and QSizePolicy integer enforcement
# all shift the rendered width. Tune this (not the shared constant) when
# the rendered desktop chart needs a few px more (positive) or less
# (negative) than the canonical. Set to 0 when no adjustment is needed.
#
# The rendered chart width is
#   max(MIN_VOWEL_CHART_W_PX + DESKTOP_VOWEL_CHART_W_ADJ,
#       natural_data_width_px + chrome)
# so the floor still steps aside for inventories whose content needs more
# horizontal room.
DESKTOP_VOWEL_CHART_W_ADJ: int = 0
VOWEL_CHART_W_FLOOR: int = MIN_VOWEL_CHART_W_PX + DESKTOP_VOWEL_CHART_W_ADJ


class FlowLayout(QLayout):
    """Left-packed, line-wrapping layout.

    Lays its items out left to right at their natural size and wraps to a
    new line when the next item would overflow the available width, every
    line packed flush left with a fixed ``gap`` between items and between
    lines. This is the Qt counterpart of the web diphthong strip's
    ``display: flex; flex-wrap: wrap``, so both UIs pack chips identically
    (tight, left-aligned, wrapping) rather than the old grid's
    stretch-to-fill columns.

    The layout reflows on every ``setGeometry`` (on resize) and reports
    :py:meth:`heightForWidth`, so the owning widget can reserve exactly
    the height the wrapped lines need. The old fixed-grid placement froze
    each chip's row and column at build time and then disagreed with a
    later width-based height estimate, which made dense diphthong
    inventories overlap.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        gap: int = 0,
        center: bool = False,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._gap = gap
        # When True each wrapped line is centered horizontally in the
        # available width, so a small set of chips sits balanced rather
        # than packed against the left edge.
        self._center = center
        self.setContentsMargins(0, 0, 0, 0)

    # QLayout plumbing
    def addItem(self, item: QLayoutItem | None) -> None:  # noqa: D102
        if item is not None:
            self._items.append(item)

    def count(self) -> int:  # noqa: D102
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: D102
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: D102
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: D102
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: D102
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: D102
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: D102
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: D102
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: D102
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    # core flow
    def _do_layout(self, rect: QRect, *, apply: bool) -> int:
        """Place items (when ``apply``) or just measure; return the total
        wrapped height in pixels. Items are grouped into lines first so
        each line can be placed (left-packed or centered) once its full
        width is known."""
        lines: list[tuple[list[tuple[QLayoutItem, QSize]], int, int]] = []
        cur: list[tuple[QLayoutItem, QSize]] = []
        cur_w = 0
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            add_w = hint.width() if not cur else self._gap + hint.width()
            if cur and cur_w + add_w > rect.width():
                lines.append((cur, cur_w, line_height))
                cur = []
                cur_w = 0
                line_height = 0
                add_w = hint.width()
            cur.append((item, hint))
            cur_w += add_w
            line_height = max(line_height, hint.height())
        if cur:
            lines.append((cur, cur_w, line_height))

        y = rect.y()
        total = 0
        for items, width, height in lines:
            if apply:
                offset = (rect.width() - width) // 2 if self._center else 0
                x = rect.x() + max(0, offset)
                for item, hint in items:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                    x += hint.width() + self._gap
            total = (y + height) - rect.y()
            y += height + self._gap
        return total


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

    # Chrome dimensions for the outer rectangular UI space. The title and
    # column headers stack at the top; row labels sit on the left; the
    # trapezoidal data area takes the rest. Wired through chart_style so
    # the web's ``--vowel-chart-*`` CSS vars and these constants cannot
    # drift.
    _TITLE_H: ClassVar[int] = cs.VOWEL_CHART_TITLE_H_PX
    _COL_HEADER_H: ClassVar[int] = cs.VOWEL_CHART_COL_HEADER_H_PX
    _PAD_R: ClassVar[int] = cs.VOWEL_CHART_PAD_R_PX
    _PAD_B: ClassVar[int] = cs.VOWEL_CHART_PAD_B_PX
    _ROW_LABEL_GAP_PX: ClassVar[int] = cs.VOWEL_CHART_ROW_LABEL_GAP_PX
    # Vertical gap between the "Diphthongs" label and the chip strip
    # below it.
    _FOOTER_GAP_PX: ClassVar[int] = 2

    def __init__(self, parent: QWidget | None = None) -> None:
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
        # through. Without this the widget paints an opaque palette window
        # (white) regardless of whether the seg pane is active or inactive,
        # leaving the trapezoid sitting on a white patch against the
        # inactive panel's grey bg.
        self.setStyleSheet("background: transparent;")
        # Shared constant so the web's ``aria-label="IPA vowel chart"`` and
        # desktop's ``setAccessibleName`` stay in sync.
        self.setAccessibleName(VOWEL_CHART_ACCESSIBLE_NAME)
        # The widget owns these directly; no layout manager. Children are
        # positioned absolutely from ``_layout_children``, which runs on
        # ``set_vowels`` and on every ``resizeEvent`` so the cells, headers,
        # and row labels track the widget's size.
        self._buttons: dict[str, SegmentButton] = {}
        self._title_label: QLabel | None = None
        # Column / row labels with their normalised positions
        # (chart_x for columns, chart_y for rows) so resize can
        # re-place them without re-fetching the geometry.
        self._col_labels: list[tuple[QLabel, float, float]] = []
        # Per-row tuple: (label, chart_y, tier). The row-label
        # layout derives the silhouette's actual LEFT edge per
        # render via the dw-corrected cascade
        # (``silhouette_for_data_width`` + ``silhouette_left_at_y``);
        # the baked per-row value on the shared geometry is the
        # canonical-width approximation the web consumes directly.
        # ``tier`` shifts the label by half a button on top / bottom
        # rows so it centres on the anchor button row like the
        # middle labels do (those rows' cells anchor an EDGE on
        # chart_y and grow inward).
        self._row_labels: list[tuple[QLabel, float, str, int]] = []
        # Cell widgets (segment buttons or vbox stacks for collision cells)
        # carry their chart_x / chart_y plus a pair_side signed multiplier
        # (-1 / 0 / +1). The resize pass projects them to pixel positions:
        # the anchor follows the trapezoid silhouette, then a fixed pair
        # shift in pixels keeps rounded/unrounded mates exactly tangent no
        # matter how narrow the row becomes. The back-line
        # snap-to-button-centre decision lives on the shared
        # ``VowelChartSilhouette.back_right_pixel_offset`` field so the
        # renderer does not need each cell's ``col``.
        # ``tier`` is the row's anchor semantic from
        # :py:class:`VowelChartRow`: ``"top"`` / ``"bottom"`` /
        # ``"middle"`` / ``"only"``. The layout pass uses it to decide
        # whether the cell's stack hangs down from chart_y (top), rises up
        # to chart_y (bottom), or centres on chart_y (middle / only). Web
        # CSS expresses the same decision via ``data-row-tier`` rules with
        # ``translate(..., 0%)`` / ``-100%`` / ``-50%``.
        # Per-cell tuple:
        #   (widget, chart_x, chart_y, pair_side, tier, row, col,
        #    canonical_segment, pair_shift_px, nudge_px)
        # ``canonical_segment`` is ``entries[0]`` of the source
        # ``VowelChartCell`` (entries are sorted by descending placement
        # confidence).
        self._cells: list[
            tuple[
                QWidget,
                float,
                float,
                int,
                str,
                int,
                int,
                str,
                float,
                float,
            ]
        ] = []
        self._cell_containers: list[QWidget] = []
        # Stack cells registered for the render-time slot clamp:
        # (container, buttons, depth, slot_height_norm). The layout
        # pass derives each stack's per-button height from its row's
        # slot budget at the CURRENT rendered height, so a chart
        # rendered shorter than its natural request shrinks the deep
        # stacks (down to the shared legibility floor) instead of
        # letting them invade the neighbouring rows.
        self._stack_cells: list[tuple[QWidget, list[QWidget], int, float]] = []
        # Row -> slot_height_norm from the current geometry; read by
        # ``_fill_stack_layout`` when registering stack cells.
        self._slot_norm_by_row: dict[int, float] = {}
        # Cached header styles, rebuilt by apply_theme each toggle.
        self._HDR_ACTIVE = ""
        self._HDR_INACTIVE = ""
        self._ROW_ACTIVE = ""
        self._ROW_INACTIVE = ""
        self._DIPH_ACTIVE = ""
        self._DIPH_INACTIVE = ""
        self._rebuild_style_cache()
        # Last ``active`` value styled into the headers; cleared by
        # clear() and apply_theme() to force a re-style.
        self._last_headers_active: bool | None = None
        # Shape envelope. ``paintEvent`` consumes it to draw the
        # trapezoid or triangle silhouette behind the data area
        # only (not under the row labels or column headers).
        self._shape: VowelChartShape = VowelChartShape.TRAPEZOID
        # Silhouette corners for the current inventory. Populated by
        # :py:meth:`_render_geometry` from the shared
        # :py:attr:`VowelChartGeometry.silhouette` so the outline adapts to
        # the populated row range (e.g. a Spanish inventory whose lowest
        # row is Open uses the canonical narrow bottom; one whose lowest
        # row is Open-mid carries a wider bottom edge). ``None`` before the
        # first render.
        self._silhouette: VowelChartSilhouette | None = None
        # Diphthong segment names for the current inventory. They are
        # NOT placed in the trapezoid; the chip strip below the chart
        # lists them. Empty for monophthong-only inventories.
        self._diphthongs: tuple[str, ...] = ()
        # "Diphthongs" section header above the chip strip, styled like the
        # segment-class headers (title-case, semibold, tracked) via the
        # shared SEG_GROUP_HEADER_* tokens so it reads as a peer of the
        # other class labels instead of incidental grey text. Shown only
        # when the inventory has diphthongs.
        diph_font = QFont("Noto Sans")
        diph_font.setPixelSize(cs.SEG_GROUP_HEADER_FONT_PX)
        diph_font.setWeight(QFont.Weight(cs.SEG_GROUP_HEADER_FONT_WEIGHT))
        self._diphthong_label = QLabel("Diphthongs", self)
        self._diphthong_label.setFont(diph_font)
        # Left-aligned so the header sits flush with the chart's left
        # edge, directly above the chip row that fills left-to-right
        # under it. Matches the segment-class headers, left-aligned too.
        self._diphthong_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._diphthong_label.setStyleSheet(self._DIPH_INACTIVE)
        self._diphthong_label.hide()
        # Chip strip below the silhouette listing the inventory's
        # diphthong segments as selectable buttons. Empty (hidden)
        # when the inventory has no diphthongs.
        self._diphthong_chip_strip = QWidget(self)
        self._diphthong_chip_strip.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        # FlowLayout packs the chips tight and left-aligned and wraps to
        # new lines when the strip isn't wide enough, mirroring the web
        # strip's ``flex-wrap``. It reflows on resize and reports
        # ``heightForWidth``, so the reserved footer height always matches
        # the laid-out lines (dense inventories no longer overlap).
        # ``BTN_GAP`` matches the segment grid's spacing so the chips share
        # the seg-button rhythm.
        self._chip_strip_layout = FlowLayout(
            self._diphthong_chip_strip, gap=BTN_GAP, center=False
        )
        self._diphthong_chip_strip.hide()
        # Floor for ``set_target_width``: the geometry's natural data width
        # plus this widget's chrome. Updated on every
        # :py:meth:`_render_geometry` call so external resize requests below
        # this floor are clamped, keeping cells legible when an inventory
        # needs more horizontal room than the canonical
        # ``layout.VOWEL_NATURAL_W``.
        self._natural_total_w: int = 0

    def _rebuild_style_cache(self) -> None:
        # Letter-spacing on the column headers pinned to
        # ``chart_style.VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX`` so desktop
        # and web both render Front / Central / Back with the same tracking.
        _col_ls = (
            f"letter-spacing: "
            f"{cs.VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX}px;"
        )
        self._HDR_ACTIVE = f"color: {C['text']}; {_col_ls}"
        self._HDR_INACTIVE = f"color: {C['text_dim']}; {_col_ls}"
        # Row labels: no inline padding-right. The gap to the silhouette
        # comes entirely from ``chart_style.VOWEL_CHART_ROW_LABEL_GAP_PX``
        # applied at position time (web uses the same
        # ``--vowel-chart-row-label-gap`` value via its CSS
        # ``right: calc(...)`` rule). Pre-relay desktop's extra 4 px
        # padding-right stacked on top of the 10 px gap, leaving labels
        # 14 px from the silhouette while web stayed at 10 px.
        self._ROW_ACTIVE = f"color: {C['text']};"
        self._ROW_INACTIVE = f"color: {C['text_dim']};"
        # "DIPHTHONGS" header: same segment-class-header tracking +
        # padding, and the SAME active/inactive colour swap as the
        # column headers so it brightens with the pane instead of
        # sitting permanently dimmer than the other class names.
        _diph_pad = cs.SEG_GROUP_HEADER_PADDING_PX
        _diph_fmt = (
            f" letter-spacing: "
            f"{cs.SEG_GROUP_HEADER_LETTER_SPACING_PX}px;"
            f" padding: {_diph_pad[0]}px {_diph_pad[1]}px"
            f" {_diph_pad[2]}px {_diph_pad[3]}px;"
        )
        self._DIPH_ACTIVE = f"color: {C['text']};{_diph_fmt}"
        self._DIPH_INACTIVE = f"color: {C['text_dim']};{_diph_fmt}"

    def apply_theme(self) -> None:
        """Re-style cached header strings against the active palette
        and force the next ``set_headers_active`` to re-apply.
        """
        self._rebuild_style_cache()
        # Repaint the diphthong header immediately for the current
        # active state; the other headers re-apply on the forced
        # ``set_headers_active`` triggered by clearing the dedup below.
        self._diphthong_label.setStyleSheet(
            self._DIPH_ACTIVE
            if self._last_headers_active
            else self._DIPH_INACTIVE
        )
        self._last_headers_active = None

    def set_target_width(self, w: int) -> None:
        """Width is content-driven via ``natural_data_width_px``.

        The ``w`` argument is accepted so the seg-pane controller
        can cue a repaint but is not used for sizing.
        """
        del w
        effective_w = max(VOWEL_CHART_W_FLOOR, self._natural_total_w)
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
            # Color is the only active-state difference; padding comes from
            # the relayed constant and letter-spacing already lives on the
            # QFont (a stylesheet copy would double-apply it).
            _pad = cs.VOWEL_CHART_TITLE_PADDING_PX
            self._title_label.setStyleSheet(
                f"color: {C['text' if active else 'text_dim']}; "
                f"padding: {_pad[0]}px {_pad[1]}px {_pad[2]}px {_pad[3]}px;"
            )
        for lbl, *_ in self._col_labels:
            lbl.setStyleSheet(header_style)
        for lbl, *_ in self._row_labels:
            lbl.setStyleSheet(row_style)
        self._diphthong_label.setStyleSheet(
            self._DIPH_ACTIVE if active else self._DIPH_INACTIVE
        )
        self._last_headers_active = active

    def _populate_diphthong_chip_strip(self) -> None:
        """Refill the chip strip with the pooled ``SegmentButton`` for
        each unique diphthong segment in the current inventory.

        Each chip IS the segment's pooled button (the same instance the
        rest of the app tracks for selection), so selection, analysis
        repaint, theme, and Clear all flow through one source of truth.
        Diphthongs are never placed in the trapezoid, so the strip is
        their only on-screen home; a separate button here would latch
        its own checked state and drift out of sync with the real
        selection on Clear.

        The FlowLayout wraps the chips to new lines on its own when
        the strip isn't wide enough, so this method only has to add
        them in order; placement and wrapping happen at layout time.
        """
        layout = self._chip_strip_layout
        # Detach (never destroy) any previously placed chips; they are the
        # caller's pooled buttons, owned by the MainWindow.
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
        seen: set[str] = set()
        unique_diphs: list[str] = []
        for seg in self._diphthongs:
            if not seg or seg in seen:
                continue
            seen.add(seg)
            unique_diphs.append(seg)
        for segment in unique_diphs:
            chip = self._buttons.get(segment)
            if chip is None:
                continue
            chip.setParent(self._diphthong_chip_strip)
            chip.setToolTip(f"Select /{segment}/")
            chip.show()
            layout.addWidget(chip)

    def clear(self) -> None:
        """Remove all buttons, labels, and collision containers.
        Buttons are detached (not destroyed) since they belong to
        the caller's pool. Detaching them BEFORE deleting cell
        containers is essential; otherwise destroying the container
        would take the children with it.

        Transient display state (the natural-width pin) resets too so
        a wide-to-narrow inventory swap releases the prior pin.
        """
        for btn in self._buttons.values():
            # Drop the per-instance capsule override before detaching, so a
            # pooled button reused by the consonant grid never renders
            # flat/borderless. (Corner radius is uniform across all seg
            # buttons now, so there is nothing else to reset.)
            btn.set_in_capsule(False)
            btn.setParent(None)
        self._buttons.clear()
        if self._title_label is not None:
            self._title_label.deleteLater()
            self._title_label = None
        for lbl, *_ in self._col_labels:
            lbl.deleteLater()
        self._col_labels.clear()
        for lbl, *_ in self._row_labels:
            lbl.deleteLater()
        self._row_labels.clear()
        self._cells.clear()
        self._stack_cells.clear()
        self._slot_norm_by_row.clear()
        self._last_headers_active = None
        for container in self._cell_containers:
            container.deleteLater()
        self._cell_containers.clear()
        self._diphthongs = ()
        self._diphthong_label.hide()
        self._diphthong_chip_strip.hide()
        self._natural_total_w = 0
        # Release the prior render's width pin so the next inventory
        # can pick its own size; without this, switching from a wide
        # PHOIBLE inventory (700 px) to a narrow bundled one keeps
        # the chart frozen at 700 px and visually collapses the
        # data area inside. The post-clear pin lives in
        # ``_render_geometry``.
        self.setMinimumWidth(0)
        self.setMaximumWidth(16_777_215)  # QWIDGETSIZE_MAX
        self.setMinimumHeight(REGION_CONSTRAINTS["vowel_chart"].min_h)

    def set_vowels(
        self,
        segs: list[str],
        buttons: Mapping[str, SegmentButton],
        norm_feats: Mapping[str, Mapping[str, str]],
        segment_secondary: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        """Build the shared geometry, then render it as Qt widgets.

        The geometry pass (placement, collision grouping, and
        physical-coordinate arithmetic) all happens in
        :py:mod:`vowel_layout`. This method only translates the
        result into widget calls.

        ``segment_secondary`` carries final-state feature bundles for
        PHOIBLE diphthong segments. When present, those segments are
        listed as chips below the chart (they are not placed in the
        trapezoid).
        """
        self.clear()
        self._buttons = dict(buttons)
        profile = detect_vowel_profile(segs, norm_feats)
        geometry = build_vowel_chart_geometry(
            segs, profile, norm_feats, segment_secondary=segment_secondary
        )
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
        self._diphthongs = tuple(geometry.diphthongs)
        # Show the "Diphthongs" label + chip strip only when the
        # inventory actually has diphthongs (mirrors the web guard).
        has_diphthongs = bool(self._diphthongs)
        self._populate_diphthong_chip_strip()
        self._diphthong_label.setVisible(has_diphthongs)
        self._diphthong_chip_strip.setVisible(has_diphthongs)
        # Width is content-driven (natural + chrome) with a floor;
        # min == max is unconditional so wide-to-narrow swaps
        # shrink instead of leaving the widget unsized.
        chrome_w = VOWEL_LABEL_W + self._PAD_R
        # The diphthong footer (label + chip strip) is reserved ON TOP
        # of the trapezoid's natural height, so the data area keeps its
        # full height and the vowel cells never get squeezed into
        # overlap when the inventory has diphthongs.
        chrome_h = (
            self._TITLE_H
            + self._COL_HEADER_H
            + self._PAD_B
            + self._footer_height()
        )
        self._natural_total_w = geometry.natural_data_width_px + chrome_w
        effective_w = max(VOWEL_CHART_W_FLOOR, self._natural_total_w)
        natural_total_h = max(
            REGION_CONSTRAINTS["vowel_chart"].min_h,
            geometry.natural_data_height_px + chrome_h,
        )
        self.setMinimumWidth(effective_w)
        self.setMaximumWidth(effective_w)
        self.setMinimumHeight(natural_total_h)
        # Letter-spacing must live on the QFont, not the stylesheet:
        # QFontMetrics only includes spacing set on the font, so a
        # stylesheet rule would undersize adjustSize() and clip
        # the first glyph.
        title = QLabel(geometry.title, self)
        title_font = QFont("Noto Sans")
        title_font.setPixelSize(cs.VOWEL_CHART_TITLE_FONT_PX)
        title_font.setWeight(QFont.Weight(cs.VOWEL_CHART_TITLE_FONT_WEIGHT))
        title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing,
            cs.VOWEL_CHART_TITLE_LETTER_SPACING_PX,
        )
        title.setFont(title_font)
        _pad = cs.VOWEL_CHART_TITLE_PADDING_PX
        title.setStyleSheet(
            f"color: {C['text_dim']}; "
            f"padding: {_pad[0]}px {_pad[1]}px {_pad[2]}px {_pad[3]}px;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.adjustSize()
        title.show()
        self._title_label = title
        # Column headers: positioned at the backness anchor for each column
        # (front / central / back) so the labels line up with the cells in
        # the widest row of the trapezoid. They carry the title-tier weight
        # (DemiBold) so they read as section headings; row labels stay
        # regular, so the two tiers distinguish header from axis-label
        # rhythm. Mirrors the web's 600/500 font-weight split on
        # ``.vowel-chart-col-label`` vs ``.vowel-chart-row-label``.
        # Col / row label fonts use chart_style.py so the desktop's Qt
        # setPixelSize and the web's CSS font-size read the same number.
        col_font = QFont("Noto Sans")
        col_font.setPixelSize(cs.VOWEL_CHART_COL_LABEL_FONT_PX)
        col_font.setWeight(QFont.Weight.DemiBold)
        for col in geometry.cols:
            lbl = QLabel(col.label, self)
            lbl.setFont(col_font)
            lbl.setStyleSheet(self._HDR_INACTIVE)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.adjustSize()
            lbl.show()
            self._col_labels.append((lbl, col.chart_x, col.chart_x_bottom))
        # Row labels: positioned at chart_y on the left gutter. Weight 500
        # (Medium) per chart_style.py so axis labels read lighter than the
        # col-header headings; the 600/500 axis-vs-heading split the web
        # docstring describes now applies on desktop too.
        row_font = QFont("Noto Sans")
        row_font.setPixelSize(cs.VOWEL_CHART_ROW_LABEL_FONT_PX)
        row_font.setWeight(QFont.Weight(cs.VOWEL_CHART_ROW_LABEL_FONT_WEIGHT))
        for row in geometry.rows:
            lbl = QLabel(row.label, self)
            lbl.setFont(row_font)
            lbl.setStyleSheet(self._ROW_INACTIVE)
            lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            lbl.adjustSize()
            lbl.show()
            self._row_labels.append(
                (lbl, row.chart_y, row.tier, row.content_height_px)
            )
        # Data cells: collected with their chart_x / chart_y; the
        # layout pass turns those into pixel positions. The cell's
        # row tier (read from the shared ``VowelChartRow``) decides
        # whether the cell anchors its top / centre / bottom on
        # chart_y; mirrors the web's ``data-row-tier`` CSS.
        tier_by_row = {row.logical_row: row.tier for row in geometry.rows}
        # Slot budgets for the render-time clamp; must be populated
        # BEFORE the cells are built so ``_fill_stack_layout`` can
        # register each stack with its row's share of the span.
        self._slot_norm_by_row = {
            row.logical_row: row.slot_height_norm for row in geometry.rows
        }
        for cell in geometry.cells:
            widget = self._build_cell(cell)
            if widget is None:
                continue
            self._cells.append(
                (
                    widget,
                    cell.chart_x,
                    cell.chart_y,
                    cell.pair_side,
                    tier_by_row.get(cell.row, "middle"),
                    cell.row,
                    cell.col,
                    cell.entries[0] if cell.entries else "",
                    cell.pair_shift_px,
                    cell.nudge_px,
                )
            )
        self._layout_children()
        self.update()

    def _build_cell(self, cell: VowelChartCell) -> QWidget | None:
        """Return the widget that represents ``cell``.

        Dispatches on ``cell.display_kind``:

        * Single entry: the raw button (no container).
        * PAIR kind (long / nasal / rhotic / phonation / tone):
          horizontal hbox with the two entries side-by-side, marked
          member on the right per the shared classifier's ordering
          convention.
        * CONTRAST_SET: 2-column grid (3 entries: first spans both
          columns on row 0; 4 entries: 2x2 in entry order).
        * STACK (default): vertical vbox with all entries.

        Returns ``None`` if none of the segments have a backing
        button (defensive; should not happen in normal flow).
        """
        # Buttons are pooled across renders, so an earlier render's
        # density-tier ``setFixedHeight`` would otherwise leak into
        # the current render. Reset every cell's buttons to the
        # canonical height before dispatching; ``_fill_stack_layout``
        # re-shrinks for dense / ultra stacks as needed.
        # Also reset the pooled buttons' per-instance vowel-chart style
        # overrides (capsule mode / chip radius) so a button that was a
        # pair member or a single chip last render renders correctly in
        # its new role this render.
        for seg in cell.entries:
            pooled = self._buttons.get(seg)
            if pooled is not None:
                pooled.setFixedHeight(SEG_BTN_H)
                pooled.set_in_capsule(False)
        if len(cell.entries) == 1:
            btn = self._buttons.get(cell.entries[0])
            if btn is None:
                return None
            # Single vowel chip: no per-instance radius override needed;
            # every seg button already uses the shared SEG_BTN_RADIUS_PX.
            btn.setParent(self)
            btn.show()
            return btn
        if cell.display_kind in PAIR_DISPLAY_KINDS:
            capsule = VowelPairCapsule(self)
            self._cell_containers.append(capsule)
            return self._fill_pair_layout(capsule, cell)
        if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
            capsule = VowelPairCapsule(self)
            self._cell_containers.append(capsule)
            return self._fill_contrast_set_layout(capsule, cell)
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")
        self._cell_containers.append(container)
        return self._fill_stack_layout(container, cell)

    def _fill_pair_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Lay the two entries side-by-side inside a segmented capsule.
        Marked member sits on the right per the classifier. The buttons
        run flat + borderless (``set_in_capsule``); the capsule frame,
        shared fill, and divider are painted by
        :class:`VowelPairCapsule`."""
        layout = QHBoxLayout(container)
        # No inter-cell gap: the capsule's painted divider separates the
        # two variants. A small margin keeps the buttons off the frame
        # stroke so the rounded outline reads cleanly.
        layout.setSpacing(0)
        margin = round(cs.BORDER_PX["std"])
        layout.setContentsMargins(margin, margin, margin, margin)
        added = False
        for seg in cell.entries:
            btn = self._buttons.get(seg)
            if btn is not None:
                btn.set_in_capsule(True)
                btn.show()
                layout.addWidget(btn)
                added = True
        return self._finalize_container(container, added)

    def _fill_contrast_set_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Lay a two-feature variant group as a gridded capsule: each
        entry sits at its ``cell.grid`` ``(col, row)``. A complete 4-entry
        set is a feature-aligned 2x2; a partial set with a base form is a
        single HORIZONTAL row with the base centred and its variants
        flanking it (``var | base | var``). The cells run flat + borderless
        inside the capsule; the frame + dividers are painted by
        :class:`VowelPairCapsule`.
        """
        layout = QGridLayout(container)
        # No gaps: the capsule's painted dividers separate the cells.
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(0)
        margin = round(cs.BORDER_PX["std"])
        layout.setContentsMargins(margin, margin, margin, margin)
        added = False
        grid = cell.grid or ()
        for idx, seg in enumerate(cell.entries):
            btn = self._buttons.get(seg)
            if btn is None:
                continue
            if idx < len(grid):
                col, row = grid[idx]
            else:  # defensive fallback: row-major
                col, row = idx % 2, idx // 2
            btn.set_in_capsule(True)
            btn.show()
            layout.addWidget(btn, row, col)
            added = True
        return self._finalize_container(container, added)

    def _fill_stack_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Default vertical-stack layout for STACK display kinds.

        Density-tier-aware: when the stack reaches
        :py:data:`DENSITY_TIER_DENSE_THRESHOLD` (5+) or
        :py:data:`DENSITY_TIER_ULTRA_THRESHOLD` (10+) entries,
        every button gets its height reduced via
        :py:func:`effective_button_height_px` to match the web's
        ``data-cell-density`` CSS rules.
        """
        layout = QVBoxLayout(container)
        layout.setSpacing(cs.VOWEL_CELL_STACK_GAP_PX)
        layout.setContentsMargins(0, 0, 0, 0)
        per_btn_h = effective_button_height_px(len(cell.entries))
        added = False
        btns: list[QWidget] = []
        for seg in cell.entries:
            btn = self._buttons.get(seg)
            if btn is not None:
                btn.setFixedHeight(per_btn_h)
                btn.show()
                layout.addWidget(btn)
                btns.append(btn)
                added = True
        if added:
            # Register for the slot clamp in ``_layout_children``:
            # the tier height set above is the natural-size value;
            # the layout pass re-derives it from the row's slot
            # budget whenever the rendered height differs.
            self._stack_cells.append(
                (
                    container,
                    btns,
                    len(btns),
                    self._slot_norm_by_row.get(cell.row, 0.0),
                )
            )
        # Dense / ultra cells visually shrink their buttons; without a
        # tooltip, users read the packing as a rendering bug. Mirror the
        # web's title attribute on the container so hovering anywhere over
        # the stack explains the count.
        if len(cell.entries) >= 5:
            container.setToolTip(
                f"{len(cell.entries)} segments share this cell: "
                + " ".join(cell.entries)
            )
        return self._finalize_container(container, added)

    def _finalize_container(
        self, container: QWidget, added: bool
    ) -> QWidget | None:
        """Shared tail: drop empty containers, otherwise size + show."""
        if not added:
            self._cell_containers.remove(container)
            container.deleteLater()
            return None
        container.adjustSize()
        container.show()
        return container

    def _diphthong_left_inset(self, dw: int) -> int:
        """Horizontal px from the data area's left edge to the
        trapezoid's BOTTOM-LEFT corner (where the slanted front edge
        meets the bottom edge), so the diphthong footer starts flush
        under the silhouette's front slant instead of the data area's
        left edge.

        Reads the SAME width-corrected ``bottom_left`` the outline
        paints its bottom-left corner from (the ``paintEvent``
        cascade), so the footer and that corner land on the same pixel
        at every width. Width-only, so it is safe to call from
        :py:meth:`_chip_strip_height` without the footer-height
        circularity.
        """
        if dw <= 0:
            return 0
        sil = self._silhouette
        if sil is None:
            sil = vowel_silhouette(self._shape)
        sil = silhouette_for_data_width(sil, dw)
        # The diphthong strip starts under the DRAWN (inset) front slant,
        # so shift its left inset outward with the outline.
        inset_norm = cs.VOWEL_SILHOUETTE_INSET_PX / dw if dw > 0 else 0.0
        return max(0, round((sil.bottom_left - inset_norm) * dw))

    def _chip_strip_height(self) -> int:
        """Vertical pixels the diphthong chip strip needs. Zero when
        the inventory has no diphthongs; otherwise the exact height
        the FlowLayout wraps into at the data-area width, so dense
        inventories (Korean PHOIBLE, 12 diphthongs) get precisely the
        room they occupy and never overlap."""
        if not self._diphthongs:
            return 0
        # The data-area width does not depend on the footer height (only
        # the data-area height does), so this is the same width the chip
        # strip is laid out at, with no circular call back into
        # ``_data_area_rect``. Asking the FlowLayout itself for
        # ``heightForWidth`` keeps the reserved height and the actual
        # wrapped lines in lock-step (the old grid estimate could disagree
        # with the built layout and overlap).
        strip_w = max(0, self.width() - VOWEL_LABEL_W - self._PAD_R)
        # The strip starts at the trapezoid's bottom-left corner, so it is
        # narrower than the full data width. Measure the wrap at that
        # narrower width or dense inventories (Korean PHOIBLE, 12
        # diphthongs) under-reserve height and overflow the footer.
        strip_w = max(0, strip_w - self._diphthong_left_inset(strip_w))
        if strip_w <= 0:
            return SEG_BTN_H
        return max(SEG_BTN_H, self._chip_strip_layout.heightForWidth(strip_w))

    def _footer_height(self) -> int:
        """Total height reserved below the trapezoid for the diphthong
        footer (the "Diphthongs" label + the chip strip). Zero for
        monophthong-only inventories. Reserved on top of the data
        area's natural height so the vowel cells never get squeezed."""
        if not self._diphthongs:
            return 0
        label_h = self._diphthong_label.sizeHint().height()
        return label_h + self._FOOTER_GAP_PX + self._chip_strip_height()

    def _data_area_rect(self) -> tuple[int, int, int, int]:
        """``(x, y, width, height)`` of the trapezoidal segment
        display space inside the rectangular widget. The chrome
        (title, column headers, row label gutter, right / bottom
        padding, diphthong footer) is excluded so labels sit OUTSIDE
        the silhouette.
        """
        x = VOWEL_LABEL_W
        y = self._TITLE_H + self._COL_HEADER_H
        w = max(0, self.width() - x - self._PAD_R)
        h = max(
            0,
            self.height() - y - self._PAD_B - self._footer_height(),
        )
        return x, y, w, h

    def _layout_children(self) -> None:
        """Place title, headers, row labels, and cells.

        Headers and row labels go in the rectangular chrome; cells
        go inside the trapezoidal data area at their projected
        ``(chart_x, chart_y)``. Re-runs on every ``resizeEvent``.
        """
        dx, dy, dw, dh = self._data_area_rect()
        # Diphthong footer: a "Diphthongs" label then the chip strip,
        # stacked in the band BELOW the data area (which
        # ``_data_area_rect`` already reserved via ``_footer_height``).
        # Absent when the inventory has no diphthongs.
        if self._diphthongs:
            strip_h = self._chip_strip_height()
            label_h = self._diphthong_label.sizeHint().height()
            footer_top = self.height() - self._PAD_B - self._footer_height()
            # Start the footer at the trapezoid's bottom-left corner (the
            # foot of the front slant), not the data area's left edge, so
            # the label and chips sit flush under the silhouette's
            # bottom-left edge. The width shrinks to match, so chips still
            # wrap at the data area's right (back) edge. Mirrors the web
            # ``--vowel-diph-indent``.
            footer_left = dx + self._diphthong_left_inset(dw)
            footer_w = max(0, dx + dw - footer_left)
            self._diphthong_label.setGeometry(
                footer_left, footer_top, footer_w, label_h
            )
            self._diphthong_chip_strip.setGeometry(
                footer_left,
                footer_top + label_h + self._FOOTER_GAP_PX,
                footer_w,
                strip_h,
            )
        if self._title_label is not None:
            # Give the title the full data-area box and let its AlignCenter
            # centre the text. This mirrors the web (the title is grid
            # column 2, centred over the data area) and is positionally
            # stable: the box is always ``[dx, dx + dw]``, so the heading
            # sits at the same place for every inventory of a given chart
            # width instead of drifting with the label's measured advance
            # width. The full-width box also leaves ample slack on both
            # sides, so the first glyph's side bearing (the 'V' of "VOWELS")
            # is never clipped, which is what the earlier adjustSize-based
            # placement got wrong.
            self._title_label.setGeometry(dx, 0, dw, self._TITLE_H)
        # Column headers: x in [0, 1] mapped across the data area, then
        # centred on each anchor. Uses round-to-nearest (not int truncate)
        # so sub-pixel positions don't bias every cell leftward vs the web's
        # fractional CSS percentages. Bottom-anchored in the header strip a
        # modest gap above the data area, so most of the strip's height
        # becomes breathing room between the labels and the "VOWELS" title
        # above.
        col_label_y = (
            self._TITLE_H
            + self._COL_HEADER_H
            - cs.VOWEL_CHART_COL_LABEL_GAP_BOTTOM_PX
        )
        for lbl, x, _x_bottom in self._col_labels:
            lbl.adjustSize()
            lw = lbl.width()
            px = dx + round(x * dw) - lw // 2
            lbl.move(px, col_label_y - lbl.height())
        # Row labels: positioned at chart_y, right-aligned against the
        # silhouette's slanted left edge at this row so the label follows
        # the trapezoid inward as it shrinks. Falls back to the data area's
        # left gutter when no silhouette has been rendered yet. The gap
        # keeps the label off the slant stroke so the two read as separate
        # elements; web mirrors the value in style.css.
        label_gap_px = self._ROW_LABEL_GAP_PX
        # Compute silhouette_left per render using the dw-corrected
        # silhouette. The baked per-row field on the shared geometry is
        # exact at the canonical 232 px content width, but the rendered
        # chart is content-driven (~228 to 320 px). The cascade helper keeps
        # the label flush against the silhouette at any rendered width.
        sil_for_dw = (
            silhouette_for_data_width(self._silhouette, dw)
            if self._silhouette is not None
            else vowel_silhouette(self._shape)
        )
        # Row labels stay at the FLUSH cell edge (not the outset outline)
        # so they keep sitting in the gutter; the inset only pushes the
        # drawn outline out past them (the label-to-stroke gap tightens by
        # the inset, which is why the inset is kept below the label gap).
        for lbl, y, tier, content_h in self._row_labels:
            lbl.adjustSize()
            lh = lbl.height()
            # Centre the label on its anchor button row via the shared
            # ``label_midpoint_norm`` (top / bottom tiers anchor their
            # cells' edge on chart_y and grow inward, so an unshifted label
            # would sit on the stack edge, not the button row). Recomputed
            # against the live ``dh`` each layout pass since the desktop
            # chart resizes; the same function bakes the web's
            # ``row.label_y`` at the natural height. The silhouette edge is
            # then evaluated at the label's own y so the label-to-outline
            # gap stays constant, divorcing label placement from where the
            # row's buttons land.
            label_y = label_midpoint_norm(y, tier, dh, content_h or SEG_BTN_H)
            py = dy + round(label_y * dh) - lh // 2
            silhouette_left = silhouette_left_at_y(sil_for_dw, label_y)
            anchor_x = dx + round(silhouette_left * dw)
            px = anchor_x - lbl.width() - label_gap_px
            lbl.move(max(0, px), py)
        # Render-time slot clamp. The geometry's row-fit invariant
        # guarantees every slot covers its stack at natural size; when the
        # rendered data area is shorter, the density-tier height would
        # overflow the slot and invade the rows below (top tiers hang down)
        # or above (bottom tiers rise up). Re-derive each stack's per-button
        # height from its row's slot budget at the current ``dh``, floored
        # at the shared legibility minimum; past the floor, the pane's
        # scrolling absorbs the overflow. Mirrors the web's ``--cell-btn-h``
        # resize pass.
        for container, btns, depth, slot_norm in self._stack_cells:
            if slot_norm <= 0.0 or depth <= 0:
                continue
            tier_h = effective_button_height_px(depth)
            budget = (
                slot_norm * dh - (depth - 1) * cs.VOWEL_CELL_STACK_GAP_PX
            ) / depth
            h = max(cs.VOWEL_BTN_MIN_H_PX, min(tier_h, int(budget)))
            if btns[0].height() != h:
                for btn in btns:
                    btn.setFixedHeight(h)
                container.adjustSize()
        # Cells combine a position concern (anchor) with a display concern
        # (pair shift). ``chart_x`` / ``chart_y`` are the backness anchor
        # already projected through the chart silhouette; the pair shift is
        # a fixed pixel offset of half a button width plus half the
        # within-pair gap, multiplied by ``pair_side`` (-1 unrounded,
        # 0 unknown, +1 rounded). Keeping the pair shift in pixels means
        # rounded/unrounded mates stay exactly tangent at every row of the
        # trapezoid. Per-cell ``pair_shift_px`` always carries the
        # effective value (canonical for unconflicted cells, elevated when
        # the geometry build resolved a same-anchor collision), so the
        # renderer reads it unconditionally.
        for (
            widget,
            cx,
            cy,
            pair_side,
            tier,
            _r,
            _c,
            _s,
            cell_ps,
            cell_nudge,
        ) in self._cells:
            widget.adjustSize()
            ww = widget.width()
            wh = widget.height()
            # ``cell_nudge`` is the shared hard-boundary confinement
            # offset, applied with the pair shift so the box stays inside
            # the outline exactly as the geometry computed. Round-to-nearest
            # so sub-pixel positions don't bias cells leftward / upward vs
            # the web's float % CSS.
            px = (
                dx
                + round(cx * dw)
                - ww // 2
                + int(round(pair_side * cell_ps + cell_nudge))
            )
            # Tier-aware y-anchor. Mirrors the web CSS at
            # ``web/style.css`` ``[data-row-tier]`` rules:
            #   top    -> stack hangs down from chart_y (anchor top)
            #   bottom -> stack rises up to chart_y (anchor bottom)
            #   middle / only -> centre on chart_y
            # Without this, a 7-deep Close (top) row stack centred on
            # chart_y=0.08 extends half-stack above the silhouette top edge;
            # one of the divergences vs the web for Korean PHOIBLE and other
            # tall-stack inventories.
            cy_px = dy + round(cy * dh)
            if tier == "top":
                py = cy_px
            elif tier == "bottom":
                py = cy_px - wh
            else:
                py = cy_px - wh // 2
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
        # Silhouette corners come from the geometry the bridge built for
        # this inventory (adapted to its populated row range). Falls back to
        # the canonical 7-row silhouette before the first render so an empty
        # widget paints something sensible. The right edge sits on the
        # back-pair's outer extent (back vowels are flush against it) and
        # the left edge slants from the topmost row's front position to the
        # bottommost row's front position.
        sil = self._silhouette
        if sil is None:
            # No inventory rendered yet; use the canonical silhouette
            # so a pre-load paint still shows the trapezoid outline.
            sil = vowel_silhouette(self._shape)
        # Recompute the silhouette corners from the cell extent fields
        # (front_anchor_at_*, back_anchor, cell_outer_extent_px) for the
        # actual data width. This guarantees the silhouette wraps the
        # outermost cells flush no matter how wide the chart renders.
        # Pre-cascade the corners were computed once at the canonical 232 px
        # content width and drifted ~1 px at the rendered 228 / 320 px
        # widths.
        sil = silhouette_for_data_width(sil, dw)
        # Push the DRAWN outline (and the guide clip below) a fixed inset
        # BEYOND the flush cell extent, so the chips float inside a quiet
        # field instead of touching the stroke. Draw-only: cell
        # confinement (in the shared pipeline) keeps using the flush
        # ``silhouette_for_data_width`` result, so the cells do not move.
        sil = inset_silhouette_for_draw(
            sil, dw, dh, cs.VOWEL_SILHOUETTE_INSET_PX
        )
        top_y = dy + round(sil.top_y * dh)
        bottom_y = dy + round(sil.bottom_y * dh)
        top_left_x = dx + round(sil.top_left * dw)
        bottom_left_x = dx + round(sil.bottom_left * dw)
        # Back edge: now derived from ``back_anchor + extent_px / dw``
        # via ``silhouette_for_data_width``; the legacy
        # ``back_right_pixel_offset`` escape hatch still applies for
        # any per-inventory tweak (default 0; the cascade math
        # already enforces flush).
        back_right_x = (
            dx + round(sil.top_right * dw) + sil.back_right_pixel_offset
        )
        top_right_x = back_right_x
        bottom_right_x = back_right_x
        path = self._build_rounded_silhouette_path(
            top_left_x,
            top_y,
            top_right_x,
            top_y,
            bottom_right_x,
            bottom_y,
            bottom_left_x,
            bottom_y,
            dw,
            dh,
        )
        painter = QPainter(self)
        # ``end()`` in a finally so a raise mid-paint can't leave the
        # QPainter active on the widget (Qt then warns and can corrupt the
        # next paint pass).
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Flat, ultra-faint interior wash so the vowel space reads as
            # a distinct "map" surface the chips sit on (figure-ground),
            # not the former per-tier GRADIENT (which read as uneven
            # banding). Painted first so the guides + outline + chips
            # render on top. Mirrors the web's ``color-mix`` tint on
            # ``.vowel-chart-data::after``.
            field_tint = QColor(C["border"])
            field_tint.setAlphaF(cs.VOWEL_FIELD_TINT_ALPHA)
            painter.fillPath(path, field_tint)
            # The rest of the field is quiet: only the dotted row/column
            # guides encode structure (height tiers + backness columns).
            self._paint_guides(painter, path, dx, dy, dw, dh)
            # Outline only, no painted fill. The trapezoid is a structural
            # guide, not a coloured region. A 1 px alpha-blended stroke
            # softens the silhouette so the cells inside carry the visual
            # weight; mirrors the web's muted
            # ``color-mix(in srgb, var(--border) 70%, transparent)``
            # treatment on ``.vowel-chart-data::before``.
            outline_color = QColor(C["border"])
            # Alpha from chart_style.VOWEL_SILHOUETTE_ALPHA so web's
            # color-mix(70%) and desktop's setAlpha pick the same value.
            outline_color.setAlphaF(cs.VOWEL_SILHOUETTE_ALPHA)
            pen = QPen(outline_color)
            pen.setWidthF(cs.VOWEL_SILHOUETTE_STROKE_PX)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        finally:
            painter.end()

    def _paint_guides(
        self,
        painter: QPainter,
        path: "QPainterPath",
        dx: int,
        dy: int,
        dw: int,
        dh: int,
    ) -> None:
        """Faint dotted row + column guides inside the silhouette so the
        eye can trace each height tier and backness column. Clipped to
        the trapezoid and drawn at very low alpha (under the cells) so
        the structure reads without competing with the glyphs."""
        guide = QColor(C["border"])
        guide.setAlphaF(cs.VOWEL_GUIDE_ALPHA)
        pen = QPen(guide)
        pen.setWidthF(cs.VOWEL_GUIDE_STROKE_PX)
        pen.setStyle(Qt.PenStyle.DotLine)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(pen)
        for _lbl, chart_y, tier, content_h in self._row_labels:
            # Trace the row-content midpoint, not the raw ``chart_y`` anchor:
            # top / bottom tiers anchor their cells' edge on ``chart_y`` and
            # grow inward, so an unshifted guide would miss the content
            # centre. Uses the same ``label_midpoint_norm`` (with the row's
            # content height) the row label placement uses, so guide and
            # label stay aligned even for a 2-row contrast set or a stack.
            y = dy + round(
                label_midpoint_norm(chart_y, tier, dh, content_h or SEG_BTN_H)
                * dh
            )
            painter.drawLine(dx, y, dx + dw, y)
        # Column guides SLANT to follow their backness column, not a
        # naive vertical drop. The shared geometry bakes each column's
        # anchor projected at BOTH the top and bottom silhouette edges
        # (``chart_x`` / ``chart_x_bottom``); the cells in that column
        # migrate toward the vertical back edge as the rows narrow, so a
        # vertical guide would only touch the top cell and drift left of
        # every lower one. Draw the line through the two baked endpoints so
        # it passes through the column's true centres. Back-column anchor ==
        # the projection's fixed point, so its two values match and the
        # guide is vertical by construction.
        sil = self._silhouette
        if sil is not None:
            span = (sil.bottom_y - sil.top_y) or 1.0
            for _lbl, chart_x, chart_x_bottom in self._col_labels:
                # Extrapolate the (top_y, bottom_y) segment to the full
                # data-area height so the clip trims it flush to the
                # outline instead of stopping short at the inset edges.
                slope = (chart_x_bottom - chart_x) / span
                x0 = chart_x - slope * sil.top_y
                x1 = chart_x_bottom + slope * (1.0 - sil.bottom_y)
                painter.drawLine(
                    dx + round(x0 * dw), dy, dx + round(x1 * dw), dy + dh
                )
        painter.restore()

    @staticmethod
    def _build_rounded_silhouette_path(
        tl_x: float,
        tl_y: float,
        tr_x: float,
        tr_y: float,
        br_x: float,
        br_y: float,
        bl_x: float,
        bl_y: float,
        dw: float,
        dh: float,
    ) -> QPainterPath:
        """Construct the silhouette ``QPainterPath`` with rounded
        corners. Each corner is approximated by a quadratic Bezier
        whose two endpoint "inset" points sit
        ``VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC`` along each adjacent
        edge from the corner; the corner itself is the control
        point. Mirrors the web's
        ``rounded_silhouette_polygon_points`` Bezier-per-corner
        approximation so the desktop's outline matches the web's
        ``clip-path: polygon(var(--vowel-<shape>-rounded-points))``
        edge-for-edge.
        """
        corners = (
            (tl_x, tl_y),
            (bl_x, bl_y),
            (br_x, br_y),
            (tr_x, tr_y),
        )
        # Radius in pixels. The web's polygon points apply the same
        # ``radius_frac`` uniformly to normalised x and y coords; mirror
        # that by scaling by dw / dh respectively so the rounding looks
        # identical on both UIs even when the chart's aspect ratio is
        # non-square.
        r_x = cs.VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC * dw
        r_y = cs.VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC * dh
        # Inset points per corner; the path is then
        # ``moveTo(p_in_0) [ lineTo(p_in_next) quadTo(curr_next,
        # p_out_next) ]* closeSubpath``.
        n = len(corners)
        inset_in: list[tuple[float, float]] = []
        inset_out: list[tuple[float, float]] = []
        for i in range(n):
            prev = corners[(i - 1) % n]
            curr = corners[i]
            nxt = corners[(i + 1) % n]
            dx_in = prev[0] - curr[0]
            dy_in = prev[1] - curr[1]
            dx_out = nxt[0] - curr[0]
            dy_out = nxt[1] - curr[1]
            len_in = math.hypot(dx_in, dy_in) or 1.0
            len_out = math.hypot(dx_out, dy_out) or 1.0
            # Inset by the per-axis radius (x by r_x, y by r_y). Clamp to
            # 45 % of the edge length so a tiny edge doesn't overlap the
            # adjacent corner's arc.
            scale_in = min(1.0, len_in * 0.45 / max(r_x, r_y))
            scale_out = min(1.0, len_out * 0.45 / max(r_x, r_y))
            ix_in = curr[0] + scale_in * r_x * (dx_in / len_in)
            iy_in = curr[1] + scale_in * r_y * (dy_in / len_in)
            ix_out = curr[0] + scale_out * r_x * (dx_out / len_out)
            iy_out = curr[1] + scale_out * r_y * (dy_out / len_out)
            inset_in.append((ix_in, iy_in))
            inset_out.append((ix_out, iy_out))
        path = QPainterPath()
        # Start at the first corner's outgoing (post-arc) inset, then line
        # and arc around the polygon.
        path.moveTo(inset_out[0][0], inset_out[0][1])
        for i in range(n):
            nxt_idx = (i + 1) % n
            path.lineTo(inset_in[nxt_idx][0], inset_in[nxt_idx][1])
            # Arc through the next corner via quadratic Bezier.
            path.quadTo(
                corners[nxt_idx][0],
                corners[nxt_idx][1],
                inset_out[nxt_idx][0],
                inset_out[nxt_idx][1],
            )
        path.closeSubpath()
        return path
