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

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import ClassVar

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
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
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from phonology_shared.chart.vowels import (
    COL_LABELS,
    PAIR_DISPLAY_KINDS,
    ROW_LABELS,
    VowelCellDisplayKind,
    VowelChartCell,
    VowelChartDiphthong,
    VowelChartGeometry,
    VowelChartShape,
    VowelChartSilhouette,
    build_vowel_chart_geometry,
    detect_vowel_profile,
    vowel_silhouette,
)
from phonology_shared.chart.vowels_layout import (
    effective_button_height_px,
)
from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation.constants import (
    DIPHTHONG_TOGGLE_LABEL,
    VOWEL_CHART_ACCESSIBLE_NAME,
    VOWEL_CHART_MODE_TOOLTIP_DIPHTHONG_ACTIVE,
    VOWEL_CHART_MODE_TOOLTIP_MONO_ACTIVE,
)
from phonology_shared.presentation.layout import (
    REGION_CONSTRAINTS,
    SEG_BTN_H,
    VOWEL_NATURAL_W,
    VOWEL_PAIR_GAP_PX,
)
from phonology_shared.presentation.palette import C, VowelChartMode

# Public surface. The placement-layer types (Confidence,
# VowelPlacement, VowelProfile) are NOT re-exported -- importers
# pull them directly from ``phonology_shared.chart.vowels``.
__all__ = [
    "VOWEL_LABEL_W",
    "VowelChartWidget",
]

# Width floor for the row-label gutter. Lives in shared
# ``chart_style.VOWEL_CHART_ROW_LABEL_GUTTER_PX`` so the web's CSS
# grid-template-columns and desktop's gutter math read the same
# value. Re-exported here for any existing importer.
VOWEL_LABEL_W = cs.VOWEL_CHART_ROW_LABEL_GUTTER_PX


class _DiphthongOverlay(QWidget):
    """Transparent overlay that paints the diphthong arrows ON TOP
    of the chart's cell widgets.

    Qt paints a widget's ``paintEvent`` BEFORE its child widgets
    paint. If the diphthong arrows were drawn in the chart's own
    ``paintEvent``, the cell buttons (children of the chart) would
    render OVER the arrows and hide them. This overlay is the LAST
    sibling appended to the chart, so it paints AFTER all the
    cells and labels -- arrows stay visible above the buttons.

    The overlay is transparent for mouse events so clicks pass
    through to the cell buttons below.
    """

    def __init__(self, parent: VowelChartWidget) -> None:
        super().__init__(parent)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._chart = parent

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: D401
        # Skip arrow painting entirely when the chart is in
        # monophthong mode: the diphthong cells are hidden so
        # arrows have nothing to attach to and would point into
        # empty silhouette space.
        if self._chart._display_mode != VowelChartMode.DIPHTHONG:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Paint into the overlay's own coordinate system, which
        # matches the parent chart's (overlay fills the chart
        # rect). The chart's data-area rect is computed once and
        # forwarded so the arrow math runs in the same coords the
        # cell widgets use.
        dx, dy, dw, dh = self._chart._data_area_rect()
        # Clip arrows to the silhouette so a curved diphthong
        # can't stray outside the trapezoid (e.g. into the
        # row-label gutter). Mirrors the web's
        # ``.vowel-diphthong-arrows { clip-path: polygon(...) }``
        # rule.
        silhouette_path = self._chart._build_silhouette_path_for_clip(
            dx, dy, dw, dh
        )
        if silhouette_path is not None:
            painter.setClipPath(silhouette_path)
        self._chart._paint_diphthong_arrows(painter, dx, dy, dw, dh)
        painter.end()


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
    # All chrome dimensions wired through chart_style.py so the web's
    # CSS ``--vowel-chart-*`` vars and these Qt class constants
    # cannot drift. Pre-relay each was a desktop-only literal.
    _TITLE_H: ClassVar[int] = cs.VOWEL_CHART_TITLE_H_PX
    _COL_HEADER_H: ClassVar[int] = cs.VOWEL_CHART_COL_HEADER_H_PX
    _PAD_R: ClassVar[int] = cs.VOWEL_CHART_PAD_R_PX
    _PAD_B: ClassVar[int] = cs.VOWEL_CHART_PAD_B_PX
    _ROW_LABEL_GAP_PX: ClassVar[int] = cs.VOWEL_CHART_ROW_LABEL_GAP_PX
    # Height reserved below the silhouette for the diphthong chip
    # strip (always-visible row of inline chips listing the
    # inventory's diphthongs). When the inventory has no
    # diphthongs the strip is hidden and the data area reclaims
    # this space via :py:meth:`_chip_strip_height`.
    _CHIP_STRIP_H_PX: ClassVar[int] = 30

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
        # Accessible name for screen readers. Shared constant so the
        # web's ``aria-label="IPA vowel chart"`` and desktop's
        # ``setAccessibleName`` stay in sync.
        self.setAccessibleName(VOWEL_CHART_ACCESSIBLE_NAME)
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
        # ``tier`` is the row's anchor semantic from
        # :py:class:`VowelChartRow` -- ``"top"`` / ``"bottom"`` /
        # ``"middle"`` / ``"only"``. The layout pass uses it to
        # decide whether the cell's stack hangs down from chart_y
        # (top), rises up to chart_y (bottom), or centres on
        # chart_y (middle / only). Web CSS expresses the same
        # decision via ``data-row-tier`` rules with
        # ``translate(..., 0%)`` / ``-100%`` / ``-50%``.
        # Per-cell tuple:
        #   (widget, chart_x, chart_y, pair_side, tier, row, col,
        #    canonical_segment, is_diphthong)
        # ``canonical_segment`` is ``entries[0]`` of the source
        # ``VowelChartCell`` (entries are sorted by descending
        # placement confidence). Diphthong arrows targeting this
        # cell as a secondary endpoint land on this segment's
        # button so the arrowhead hits the visually canonical
        # target rather than the cell's geometric centre.
        # ``is_diphthong`` mirrors ``VowelChartCell.is_diphthong``
        # so ``_apply_display_mode_filter`` can flip per-cell
        # visibility without re-traversing the geometry.
        self._cells: list[
            tuple[QWidget, float, float, int, str, int, int, str, bool]
        ] = []
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
        # Diphthong overlay. ``_diphthongs`` carries the pre-projected
        # primary/secondary chart coordinates per arrow; the paint
        # pass reads them directly with no anchor-lookup dict.
        self._diphthongs: tuple[VowelChartDiphthong, ...] = ()
        # Currently hovered / focused vowel seg, or None when the
        # mouse is outside every cell. In diphthong mode this
        # drives the per-arrow focus highlight (focused arrow at
        # full opacity, others dimmed); in monophthong mode no
        # arrows render so this stays decorative.
        self._focused_seg: str | None = None
        # Vowel chart display mode: which class of vowel segments
        # the chart's silhouette area renders. The diphthong chip
        # strip below the silhouette always shows the inventory's
        # diphthongs regardless of mode; this field only decides
        # what fills the trapezoid.
        self._display_mode: VowelChartMode = VowelChartMode.MONOPHTHONG
        # Vowel-chart display-mode toggle button. Mirrors the
        # web's ``.vowel-diphthong-toggle``: mounted in the title
        # row when the inventory has any diphthongs, hidden when
        # ``self._diphthongs`` is empty. Click flips between
        # monophthong and diphthong modes; persisted via
        # ``VOWEL_CHART_MODE`` in QSettings (the chart widget
        # emits ``display_mode_changed`` so the owning
        # MainWindow can write the setting).
        self._diphthong_toggle = QPushButton(self)
        self._diphthong_toggle.setCheckable(True)
        self._diphthong_toggle.setText(DIPHTHONG_TOGGLE_LABEL)
        self._diphthong_toggle.setToolTip(VOWEL_CHART_MODE_TOOLTIP_MONO_ACTIVE)
        self._diphthong_toggle.setAccessibleName(
            DIPHTHONG_TOGGLE_LABEL,
        )
        self._diphthong_toggle.toggled.connect(
            self._on_diphthong_toggle_clicked,
        )
        # Compact chip look so it matches the web's
        # ``.vowel-diphthong-toggle``: small lowercase pill in the
        # chart corner, not a full-size toolbar button. Sized to
        # the label's natural width.
        self._diphthong_toggle.setStyleSheet(
            "QPushButton {"
            f" font-size: {cs.VOWEL_CHART_COL_LABEL_FONT_PX}px;"
            " padding: 2px 8px;"
            " border-radius: 8px;"
            f" border: 1px solid {C['border']};"
            f" color: {C['text_dim']};"
            f" background: {C['bg']};"
            " }"
            "QPushButton:hover {"
            f" color: {C['text']};"
            f" border-color: {C['accent']};"
            " }"
            "QPushButton:checked {"
            f" color: {C['accent']};"
            f" border-color: {C['accent']};"
            " }"
        )
        self._diphthong_toggle.hide()
        # Always-visible chip strip below the silhouette listing
        # the inventory's diphthong segments. Visible in BOTH
        # display modes so users always see + can select the
        # diphthongs (in monophthong mode the trapezoid hides
        # diphthong cells; the strip is the only on-chart
        # affordance). Empty when the inventory has no
        # diphthongs.
        self._diphthong_chip_strip = QWidget(self)
        self._diphthong_chip_strip.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        # Keep a typed reference to the layout so subsequent
        # populate/clear cycles don't need to call ``layout()``
        # (which returns ``QLayout | None`` and forces a guard).
        self._chip_strip_layout: QHBoxLayout = QHBoxLayout(
            self._diphthong_chip_strip
        )
        self._chip_strip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_strip_layout.setSpacing(4)
        self._chip_strip_layout.addStretch(1)
        self._diphthong_chip_strip.hide()
        # Diphthong-arrow overlay: a transparent sibling child
        # widget that paints the arrows AFTER all the cell
        # buttons (Qt paints child widgets after the parent's
        # paintEvent; cells then occlude anything drawn inside
        # the chart's paintEvent). The overlay is sized to fill
        # the chart in ``_layout_children`` and raised to the
        # top of the sibling stack so its paintEvent runs last.
        self._diphthong_overlay = _DiphthongOverlay(self)
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
        # Letter-spacing on the column headers pinned to
        # ``chart_style.VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX`` so
        # desktop and web both render Front / Central / Back with
        # the same tracking. Pre-relay desktop used 0 (no spacing).
        _col_ls = (
            f"letter-spacing: "
            f"{cs.VOWEL_CHART_COL_LABEL_LETTER_SPACING_PX}px;"
        )
        self._HDR_ACTIVE = f"color: {C['text']}; {_col_ls}"
        self._HDR_INACTIVE = f"color: {C['text_dim']}; {_col_ls}"
        # Row labels: NO inline padding-right -- the gap to the
        # silhouette comes entirely from
        # ``chart_style.VOWEL_CHART_ROW_LABEL_GAP_PX`` applied at
        # position time (web uses the same ``--vowel-chart-row-label-gap``
        # value via its CSS ``right: calc(...)`` rule). Pre-relay
        # desktop's extra 4 px padding-right stacked on top of the
        # 10 px gap, leaving labels 14 px from the silhouette while
        # web stayed at 10 px.
        self._ROW_ACTIVE = f"color: {C['text']};"
        self._ROW_INACTIVE = f"color: {C['text_dim']};"

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

    # PyQt6 signal for display-mode changes. The owning
    # MainWindow connects to this to persist the user's choice
    # via QSettings ``VOWEL_CHART_MODE``. Declared at class scope
    # via ``pyqtSignal`` -- but that import requires PyQt6.QtCore.
    # Connection lives in main_window.py.
    display_mode_changed = pyqtSignal(str)

    def set_display_mode(self, mode: VowelChartMode | str) -> None:
        """Switch the vowel chart between monophthong and diphthong
        display modes. The trapezoid renders monophthong cells in
        MONOPHTHONG mode (diphthong cells + arrows hidden) and
        diphthong cells + their trajectory arrows in DIPHTHONG
        mode (monophthong cells hidden). The chip strip below the
        silhouette ALWAYS shows the inventory's diphthongs
        regardless of mode."""
        if isinstance(mode, str) and not isinstance(mode, VowelChartMode):
            try:
                mode = VowelChartMode(mode)
            except ValueError:
                mode = VowelChartMode.MONOPHTHONG
        if self._display_mode == mode:
            return
        self._display_mode = mode
        is_diphthong = mode == VowelChartMode.DIPHTHONG
        # Keep the toggle button's checked state in sync if the
        # mode was flipped programmatically (e.g., persisted
        # value restored at startup). ``blockSignals`` prevents
        # re-entry via the toggled signal.
        self._diphthong_toggle.blockSignals(True)
        self._diphthong_toggle.setChecked(is_diphthong)
        self._diphthong_toggle.setToolTip(
            VOWEL_CHART_MODE_TOOLTIP_DIPHTHONG_ACTIVE
            if is_diphthong
            else VOWEL_CHART_MODE_TOOLTIP_MONO_ACTIVE
        )
        self._diphthong_toggle.blockSignals(False)
        # Apply the cell-visibility filter and repaint.
        self._apply_display_mode_filter()
        self.update()

    def _on_diphthong_toggle_clicked(self, checked: bool) -> None:
        """Click handler: flip the display mode based on the
        button's new checked state. Calls ``set_display_mode``
        and emits the change signal so MainWindow can persist."""
        next_mode = (
            VowelChartMode.DIPHTHONG if checked else VowelChartMode.MONOPHTHONG
        )
        self.set_display_mode(next_mode)
        self.display_mode_changed.emit(str(next_mode))

    # PyQt signal fired when a chip in the diphthong chip strip
    # is clicked. The MainWindow connects to this and routes the
    # click through the standard segment-selection flow so the
    # chip behaves identically to a click on the segment's
    # SegmentButton in any other surface.
    segment_clicked = pyqtSignal(str)

    def _populate_diphthong_chip_strip(self) -> None:
        """Refill the chip strip with one chip per unique
        diphthong segment in the current inventory. Chip click
        emits ``segment_clicked(seg)`` -- the owning MainWindow
        routes that through the same handler the pooled
        SegmentButton's ``clicked`` signal uses, so the chip is
        a thin shortcut, not a parallel selection path."""
        layout = self._chip_strip_layout
        # Clear prior chips. The trailing stretch (index 0 after
        # clear-and-readd) keeps the row left-aligned.
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        seen: set[str] = set()
        chip_style = (
            "QPushButton {"
            f" font-size: {cs.VOWEL_CHART_COL_LABEL_FONT_PX}px;"
            " padding: 2px 8px;"
            " border-radius: 8px;"
            f" border: 1px solid {C['border']};"
            f" color: {C['text']};"
            f" background: {C['bg']};"
            " }"
            "QPushButton:hover {"
            f" border-color: {C['accent']};"
            f" color: {C['accent']};"
            " }"
        )
        for d in self._diphthongs:
            if not d.segment or d.segment in seen:
                continue
            seen.add(d.segment)
            chip = QPushButton(d.segment, self._diphthong_chip_strip)
            chip.setStyleSheet(chip_style)
            chip.setFlat(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Select /{d.segment}/")
            chip.clicked.connect(
                lambda _checked=False, s=d.segment: (
                    self.segment_clicked.emit(s)
                )
            )
            layout.addWidget(chip)
        layout.addStretch(1)

    def _apply_display_mode_filter(self) -> None:
        """Show / hide cells based on the active display mode.
        Cells with ``is_diphthong`` matching the mode render;
        others are hidden via ``setVisible(False)``. The pooled
        button instances stay alive; selection state is preserved
        across mode switches because it's segment-keyed, not
        widget-keyed."""
        show_diphthong = self._display_mode == VowelChartMode.DIPHTHONG
        for widget, *_, is_diphthong_cell in self._cells:
            # ``widget`` may be the bare seg-button (single-entry
            # cell) or a container (stack / pair / contrast set).
            # ``setVisible(False)`` collapses Qt's layout pass
            # painlessly in either case.
            widget.setVisible(is_diphthong_cell == show_diphthong)
        # The overlay reads the mode directly in its paintEvent
        # to decide whether to paint arrows.

    def eventFilter(  # noqa: D401
        self, watched: QObject | None, event: QEvent | None
    ) -> bool:
        """Track which vowel seg-btn the cursor / keyboard focus
        is on so :py:meth:`_paint_diphthong_arrows` knows which
        arrow to paint. The chart installs this filter on every
        button it lands during :py:meth:`_render_geometry`."""
        if event is None or watched is None:
            return super().eventFilter(watched, event)
        kind = event.type()
        seg = getattr(watched, "segment", None)
        if not isinstance(seg, str):
            return super().eventFilter(watched, event)
        if kind in (QEvent.Type.HoverEnter, QEvent.Type.FocusIn):
            if self._focused_seg != seg:
                self._focused_seg = seg
                self.update()
        elif kind in (QEvent.Type.HoverLeave, QEvent.Type.FocusOut):
            if self._focused_seg == seg:
                self._focused_seg = None
                self.update()
        return super().eventFilter(watched, event)

    def clear(self) -> None:
        """Remove all buttons, labels, and collision containers.
        Buttons are detached (not destroyed) since they belong to
        the caller's pool. Detaching them BEFORE deleting cell
        containers is essential; otherwise destroying the container
        would take the children with it.

        Transient display state (focus, natural-width pin) resets
        too so a wide-to-narrow inventory swap releases the prior
        pin and a hovered seg does not persist across loads. The
        persistent ``_display_mode`` preference is preserved.
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
        self._diphthongs = ()
        self._focused_seg = None
        # ``_display_mode`` persists across inventory loads (it's
        # a UI preference, not inventory data). Reset only the
        # transient focus + cell state above.
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
        buttons: Mapping[str, QWidget],
        norm_feats: Mapping[str, Mapping[str, str]],
        vowel_secondary: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        """Build the shared geometry, then render it as Qt widgets.

        The geometry pass (placement, collision grouping, and
        physical-coordinate arithmetic) all happens in
        :py:mod:`vowel_layout`; this method only translates the
        result into widget calls.

        ``vowel_secondary`` carries final-state feature bundles for
        PHOIBLE diphthong segments. When present, the per-diphthong
        endpoints are stored on the widget so :py:meth:`paintEvent`
        can draw a curved arrow between the two cells.
        """
        self.clear()
        self._buttons = dict(buttons)
        profile = detect_vowel_profile(segs, norm_feats)
        geometry = build_vowel_chart_geometry(
            segs, profile, norm_feats, vowel_secondary=vowel_secondary
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
        # Show the diphthong toggle button + chip strip only when
        # the inventory actually has diphthongs (mirrors the web's
        # ``_appendVowelDiphthongToggle`` / chip-strip guards).
        has_diphthongs = bool(self._diphthongs)
        self._diphthong_toggle.setVisible(has_diphthongs)
        self._populate_diphthong_chip_strip()
        self._diphthong_chip_strip.setVisible(has_diphthongs)
        # Sizing policy: always pin width to
        # ``max(VOWEL_NATURAL_W, natural)`` so the chart never falls
        # below the canonical 440 px floor and grows for inventories
        # that need more horizontal room. Always pin height to
        # ``max(min_h, natural)`` for the same reason on the vertical
        # axis. The pin is unconditional so wide-to-narrow swaps
        # actually shrink down to canonical (the conditional version
        # left the widget unpinned between clear() and the next
        # ``set_target_width`` call and Qt's default sizeHint
        # collapsed the chart visually).
        chrome_w = VOWEL_LABEL_W + self._PAD_R
        chrome_h = self._TITLE_H + self._COL_HEADER_H + self._PAD_B
        self._natural_total_w = geometry.natural_data_width_px + chrome_w
        effective_w = max(VOWEL_NATURAL_W, self._natural_total_w)
        natural_total_h = max(
            REGION_CONSTRAINTS["vowel_chart"].min_h,
            geometry.natural_data_height_px + chrome_h,
        )
        self.setMinimumWidth(effective_w)
        self.setMaximumWidth(effective_w)
        self.setMinimumHeight(natural_total_h)
        # Title (top, centred over the data area). Font + padding +
        # letter-spacing all from chart_style.py so the web's CSS and
        # the desktop's Qt read the same numbers. Letter-spacing
        # lives on the ``QFont`` (not in the stylesheet) because
        # Qt's QFontMetrics width calculation only includes spacing
        # when set on the font itself; CSS-level letter-spacing
        # rendered fine but the label's ``adjustSize()`` would
        # undersize the bounding rect, clipping the first letter
        # ("V" in "Vowels") on some inventories.
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
        # Column headers: positioned at the backness anchor for
        # each column (front / central / back) so the labels line
        # up with the cells in the widest row of the trapezoid.
        # Column headers carry the title-tier weight (DemiBold) so
        # they read as section headings; row labels stay regular
        # so the two tiers distinguish header from axis-label rhythm.
        # Mirrors the web's 600/500 font-weight split on
        # ``.vowel-chart-col-label`` vs ``.vowel-chart-row-label``.
        # Col / row label fonts use chart_style.py so the desktop's
        # Qt setPixelSize and the web's CSS font-size read the same
        # number. Pre-relay desktop used 7pt Qt (~9 px at 96 DPI)
        # while web used 11 px.
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
            self._col_labels.append((lbl, col.chart_x))
        # Row labels: positioned at chart_y on the left gutter.
        # Weight 500 (Medium) per chart_style.py so axis labels
        # read lighter than the col-header headings -- the
        # 600/500 axis-vs-heading split the web docstring
        # describes now applies on desktop too.
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
            self._row_labels.append((lbl, row.chart_y))
        # Data cells: collected with their chart_x / chart_y; the
        # layout pass turns those into pixel positions. The cell's
        # row tier (read from the shared ``VowelChartRow``) decides
        # whether the cell anchors its top / centre / bottom on
        # chart_y -- mirrors the web's ``data-row-tier`` CSS.
        tier_by_row = {row.logical_row: row.tier for row in geometry.rows}
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
                    cell.is_diphthong,
                )
            )
            # Wire focus tracking on every seg button this cell
            # exposes so the hover-gated diphthong arrow overlay
            # knows which segment the user is attending to. The
            # event filter is idempotent via the WA_Hover attribute
            # + a single ``installEventFilter`` per button instance.
            for seg in cell.entries:
                btn = self._buttons.get(seg)
                if btn is None:
                    continue
                btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                btn.installEventFilter(self)
        # Show/hide cells based on the active display mode; must
        # run AFTER cells are appended to ``self._cells`` and
        # BEFORE the first paint so the layout pass sees the
        # final visibility state.
        self._apply_display_mode_filter()
        self._layout_children()
        self.update()

    def _build_cell(self, cell: VowelChartCell) -> QWidget | None:
        """Return the widget that represents ``cell``.

        Dispatches on ``cell.display_kind``:

        * Single entry -> the raw button (no container).
        * PAIR kind (long / nasal / rhotic / phonation / tone) ->
          horizontal hbox with the two entries side-by-side, marked
          member on the right per the shared classifier's ordering
          convention.
        * CONTRAST_SET -> 2-column grid (3 entries: first spans both
          columns on row 0; 4 entries: 2x2 in entry order).
        * STACK (default) -> vertical vbox with all entries.

        Returns ``None`` if none of the segments have a backing
        button (defensive; should not happen in normal flow).
        """
        # Buttons are pooled across renders, so an earlier render's
        # density-tier ``setFixedHeight`` would otherwise leak into
        # the current render. Reset every cell's buttons to the
        # canonical height before dispatching; ``_fill_stack_layout``
        # re-shrinks for dense / ultra stacks as needed.
        for seg in cell.entries:
            pooled = self._buttons.get(seg)
            if pooled is not None:
                pooled.setFixedHeight(SEG_BTN_H)
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
        if cell.display_kind in PAIR_DISPLAY_KINDS:
            return self._fill_pair_layout(container, cell)
        if cell.display_kind == VowelCellDisplayKind.CONTRAST_SET:
            return self._fill_contrast_set_layout(container, cell)
        return self._fill_stack_layout(container, cell)

    def _fill_pair_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Lay the two entries side-by-side in a horizontal box.
        Marked member sits on the right per the classifier."""
        layout = QHBoxLayout(container)
        layout.setSpacing(VOWEL_PAIR_GAP_PX)
        layout.setContentsMargins(0, 0, 0, 0)
        added = False
        for seg in cell.entries:
            btn = self._buttons.get(seg)
            if btn is not None:
                btn.show()
                layout.addWidget(btn)
                added = True
        return self._finalize_container(container, added)

    def _fill_contrast_set_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Lay 3-4 entries in a 2-column grid.

        Three entries: entry 0 spans columns 0+1 on row 0; entries 1
        and 2 land on row 1, columns 0 and 1. Four entries: pure 2x2
        in entry order, row-major.
        """
        layout = QGridLayout(container)
        layout.setHorizontalSpacing(VOWEL_PAIR_GAP_PX)
        # Vertical gap pinned via chart_style.py so desktop and web
        # render the 2x2 grid with the same row-axis spacing.
        # Pre-relay desktop used 1 px, web used 2 px.
        layout.setVerticalSpacing(cs.VOWEL_CHART_CONTRAST_SET_ROW_GAP_PX)
        layout.setContentsMargins(0, 0, 0, 0)
        added = False
        entries = list(cell.entries)
        if len(entries) == 3:
            slots: list[tuple[str, int, int, int]] = [
                (entries[0], 0, 0, 2),
                (entries[1], 1, 0, 1),
                (entries[2], 1, 1, 1),
            ]
            for seg, row, col, span in slots:
                btn = self._buttons.get(seg)
                if btn is not None:
                    btn.show()
                    layout.addWidget(btn, row, col, 1, span)
                    added = True
        else:
            for idx, seg in enumerate(entries):
                row = idx // 2
                col = idx % 2
                btn = self._buttons.get(seg)
                if btn is not None:
                    btn.show()
                    layout.addWidget(btn, row, col)
                    added = True
        return self._finalize_container(container, added)

    def _fill_stack_layout(
        self, container: QWidget, cell: VowelChartCell
    ) -> QWidget | None:
        """Default vertical-stack layout for STACK display kinds.

        Density-tier-aware: when the stack reaches
        :py:data:`_DENSITY_TIER_DENSE_THRESHOLD` (5+) or
        :py:data:`_DENSITY_TIER_ULTRA_THRESHOLD` (10+) entries,
        every button gets its height reduced via
        :py:func:`effective_button_height_px` so the stack fits in
        the slot the shared geometry allocated. Pre-fix the
        desktop kept every button at the canonical ``SEG_BTN_H``
        regardless of stack depth -- the web's CSS
        ``data-cell-density`` rules shrank to 22 / 18 px while
        desktop stayed at 26 px, making Korean PHOIBLE's 7-deep
        Close-Front stack render 28 px taller on desktop and
        throwing off the whole chart layout.
        """
        layout = QVBoxLayout(container)
        # Gap pinned to chart_style.VOWEL_CELL_STACK_GAP_PX so the
        # web's CSS ``gap`` and desktop's setSpacing read the same
        # value. Same source the geometry's natural-height math
        # uses, so stacks size identically across both UIs.
        layout.setSpacing(cs.VOWEL_CELL_STACK_GAP_PX)
        layout.setContentsMargins(0, 0, 0, 0)
        per_btn_h = effective_button_height_px(len(cell.entries))
        added = False
        for seg in cell.entries:
            btn = self._buttons.get(seg)
            if btn is not None:
                btn.setFixedHeight(per_btn_h)
                btn.show()
                layout.addWidget(btn)
                added = True
        # Affordance: dense / ultra cells visually shrink their
        # buttons; without a tooltip, users read the packing as a
        # rendering bug. Mirror the web's title attribute on the
        # container so hovering anywhere over the stack explains
        # the count.
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

    def _chip_strip_height(self) -> int:
        """Vertical pixels reserved for the diphthong chip strip
        below the silhouette. Zero when the current inventory has
        no diphthongs (chip strip hidden); ``_CHIP_STRIP_H_PX``
        otherwise. Called by ``_data_area_rect`` so the
        trapezoid shrinks to make room."""
        if not self._diphthongs:
            return 0
        return self._CHIP_STRIP_H_PX

    def _data_area_rect(self) -> tuple[int, int, int, int]:
        """``(x, y, width, height)`` of the trapezoidal segment
        display space inside the rectangular widget. The chrome
        (title, column headers, row label gutter, right / bottom
        padding, chip strip) is excluded so labels sit OUTSIDE
        the silhouette.
        """
        x = VOWEL_LABEL_W
        y = self._TITLE_H + self._COL_HEADER_H
        w = max(0, self.width() - x - self._PAD_R)
        h = max(
            0,
            self.height() - y - self._PAD_B - self._chip_strip_height(),
        )
        return x, y, w, h

    def _layout_children(self) -> None:
        """Place title, headers, row labels, and cells.

        Headers and row labels go in the rectangular chrome; cells
        go inside the trapezoidal data area at their projected
        ``(chart_x, chart_y)``. Re-runs on every ``resizeEvent``.
        """
        dx, dy, dw, dh = self._data_area_rect()
        # Diphthong-arrow overlay: cover the entire chart so the
        # arrow painter can map cell coords in the chart's own
        # coordinate system. Raised LAST so it sits at the top of
        # the sibling stack and paints OVER every cell button.
        if self._diphthong_overlay is not None:
            self._diphthong_overlay.setGeometry(
                0, 0, self.width(), self.height()
            )
        # Diphthong chip strip: sits in the band BELOW the data
        # area (above ``_PAD_B``). Spans the full data-area
        # width. Hidden when the inventory has no diphthongs --
        # ``_data_area_rect`` already accounted for the missing
        # band via ``_chip_strip_height``.
        if self._diphthong_chip_strip.isVisible():
            strip_h = self._CHIP_STRIP_H_PX
            strip_y = self.height() - self._PAD_B - strip_h
            self._diphthong_chip_strip.setGeometry(dx, strip_y, dw, strip_h)
        if self._title_label is not None:
            self._title_label.adjustSize()
            tw = self._title_label.width()
            self._title_label.move(dx + (dw - tw) // 2, 0)
        # Diphthong-arrows toggle button (visible iff diphthongs
        # exist on the current inventory). Sits in the right-edge
        # corner of the title row, mirroring the web's
        # ``.vowel-diphthong-toggle`` position above the data area.
        if self._diphthong_toggle.isVisible():
            self._diphthong_toggle.adjustSize()
            tw_btn = self._diphthong_toggle.width()
            th_btn = self._diphthong_toggle.height()
            self._diphthong_toggle.move(
                dx + dw - tw_btn,
                (self._TITLE_H - th_btn) // 2,
            )
            self._diphthong_toggle.raise_()
        # Column headers: x in [0, 1] mapped across the data area,
        # then centred on each anchor. Uses round-to-nearest (not
        # int truncate) so sub-pixel positions don't bias every
        # cell leftward vs the web's fractional CSS percentages.
        for lbl, x in self._col_labels:
            lbl.adjustSize()
            lw = lbl.width()
            px = dx + round(x * dw) - lw // 2
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
            py = dy + round(y * dh) - lh // 2
            if sil is not None and sil.bottom_y > sil.top_y:
                t = (y - sil.top_y) / (sil.bottom_y - sil.top_y)
                t = max(0.0, min(1.0, t))
                left_norm = sil.top_left + (sil.bottom_left - sil.top_left) * t
                anchor_x = dx + round(left_norm * dw)
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
        # Pair-shift derived from chart_style so the formula lives
        # in one place. CSS reads the same value via
        # ``--vowel-pair-shift``; pre-relay both sides re-derived
        # ``(BTN_W + VOWEL_PAIR_GAP_PX) / 2`` independently.
        pair_shift_px = int(cs.VOWEL_PAIR_SHIFT_PX)
        for widget, cx, cy, pair_side, tier, _r, _c, _s, _d in self._cells:
            widget.adjustSize()
            ww = widget.width()
            wh = widget.height()
            if ww > self._cell_w_hint:
                self._cell_w_hint = ww
            # round-to-nearest so sub-pixel positions don't bias
            # cells leftward / upward vs the web's float % CSS.
            px = dx + round(cx * dw) - ww // 2 + pair_side * pair_shift_px
            # Tier-aware y-anchor. Mirrors the web CSS at
            # ``web/style.css`` ``[data-row-tier]`` rules:
            #   top    -> stack hangs DOWN from chart_y (anchor top)
            #   bottom -> stack rises UP to chart_y (anchor bottom)
            #   middle / only -> centre on chart_y
            # Without this, a 7-deep Close (top) row stack centred on
            # chart_y=0.08 extends half-stack ABOVE the silhouette
            # top edge -- one of the divergences vs. the web for
            # Korean PHOIBLE and other tall-stack inventories.
            cy_px = dy + round(cy * dh)
            if tier == "top":
                py = cy_px
            elif tier == "bottom":
                py = cy_px - wh
            else:
                py = cy_px - wh // 2
            widget.move(px, py)
        # Raise the diphthong overlay LAST so it paints on top of
        # all the cells / labels we just positioned. ``raise_()``
        # moves the widget to the top of the sibling z-order;
        # Qt then paints it last. Without this the overlay was
        # added in __init__ before the cells, so cells sat on top.
        if self._diphthong_overlay is not None:
            self._diphthong_overlay.raise_()

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
        # Round-to-nearest (not int truncate) so the silhouette
        # corners align as closely as possible with the web's
        # CSS clip-path coordinates, which use fractional
        # percentages browser-resolved to sub-pixel positions.
        top_y = dy + round(sil.top_y * dh)
        bottom_y = dy + round(sil.bottom_y * dh)
        top_left_x = dx + round(sil.top_left * dw)
        bottom_left_x = dx + round(sil.bottom_left * dw)
        # Back edge: ``top_right`` is the back ANCHOR (normalised);
        # the fixed-pixel ``back_right_pixel_offset`` captures the
        # rest. The same formula runs on the web (via the bridge
        # payload), so both UIs land the line at the same place
        # regardless of how wide the data area is rendered. The
        # asymmetric pull-in (snap to back-vowel centre rather than
        # the canonical pair-outer extent) is encoded in the offset
        # by ``build_vowel_chart_geometry``; the renderer just adds.
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # "Soft modern" interior: single top->bottom gradient
        # instead of the alternating per-band tints. Paints first
        # so the silhouette outline + diphthong arrows render on
        # top. Active-state cue lives on the labels (text-dim ->
        # text colour transition); the silhouette outline stays
        # the same in both states.
        self._paint_gradient_interior(painter, path)
        # Outline only, no painted fill: the trapezoid is a
        # structural guide, not a coloured region. A 1 px alpha-
        # blended stroke softens the silhouette so the cells inside
        # carry the visual weight; mirrors the web's muted
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
        painter.end()
        # Diphthong arrows are painted by ``_diphthong_overlay``
        # (a sibling child widget) so they render ON TOP of cell
        # buttons. Qt paints a parent's ``paintEvent`` BEFORE its
        # child widgets paint; painting arrows here would put
        # them BEHIND the seg-button cells. Triggering an update
        # on the overlay ensures it repaints in sync with the
        # silhouette refresh.
        if self._diphthong_overlay is not None:
            self._diphthong_overlay.update()

    def _build_silhouette_path_for_clip(
        self,
        dx: int,
        dy: int,
        dw: int,
        dh: int,
    ) -> QPainterPath | None:
        """Return the silhouette outline as a closed
        ``QPainterPath`` (rounded corners, same shape as the
        silhouette pseudo-element on web). Used by the
        diphthong-arrow overlay to clip arrows that would
        otherwise curve outside the trapezoid into the row-label
        gutter. Returns ``None`` when there's no silhouette to
        clip against yet (initial paint before any inventory has
        rendered)."""
        sil = self._silhouette
        if sil is None:
            sil = vowel_silhouette(self._shape)
        top_y = dy + round(sil.top_y * dh)
        bottom_y = dy + round(sil.bottom_y * dh)
        top_left_x = dx + round(sil.top_left * dw)
        bottom_left_x = dx + round(sil.bottom_left * dw)
        back_right_x = (
            dx + round(sil.top_right * dw) + sil.back_right_pixel_offset
        )
        return self._build_rounded_silhouette_path(
            top_left_x,
            top_y,
            back_right_x,
            top_y,
            back_right_x,
            bottom_y,
            bottom_left_x,
            bottom_y,
            dw,
            dh,
        )

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
        # Radius in pixels: web's polygon points use the same
        # ``radius_frac`` applied uniformly to normalised x and y
        # coords. Mirror that: scale by dw / dh respectively so
        # the rounding looks identical on both UIs even when the
        # chart's aspect ratio is non-square.
        r_x = cs.VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC * dw
        r_y = cs.VOWEL_SILHOUETTE_CORNER_RADIUS_FRAC * dh
        # Compute the inset points per corner; the path is then
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
            # Inset by the per-axis radius: x by r_x, y by r_y.
            # Clamp to 45 % of the edge length so a tiny edge
            # doesn't overlap the adjacent corner's arc.
            scale_in = min(1.0, len_in * 0.45 / max(r_x, r_y))
            scale_out = min(1.0, len_out * 0.45 / max(r_x, r_y))
            ix_in = curr[0] + scale_in * r_x * (dx_in / len_in)
            iy_in = curr[1] + scale_in * r_y * (dy_in / len_in)
            ix_out = curr[0] + scale_out * r_x * (dx_out / len_out)
            iy_out = curr[1] + scale_out * r_y * (dy_out / len_out)
            inset_in.append((ix_in, iy_in))
            inset_out.append((ix_out, iy_out))
        path = QPainterPath()
        # Start at the first corner's "outgoing" inset (post-arc
        # point), then line+arc around the polygon.
        path.moveTo(inset_out[0][0], inset_out[0][1])
        for i in range(n):
            nxt_idx = (i + 1) % n
            # Line from this corner's outgoing inset to the next
            # corner's incoming inset.
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

    def _paint_gradient_interior(
        self,
        painter: QPainter,
        silhouette_path: QPainterPath,
    ) -> None:
        """Fill the silhouette interior with a single very-faint
        top->bottom linear gradient. Replaces the pre-redesign
        alternating per-band tints (which read as uneven graph
        paper on irregular inventories). Mirrors the web's CSS
        rule on ``.vowel-chart-row-bands`` -- both renderers paint
        ``border @ 4 % alpha`` at the top, ``border @ 14 % alpha``
        at the bottom, suggesting tongue lowering without adding
        visual noise.
        """
        bounds = silhouette_path.boundingRect()
        if bounds.height() <= 0:
            return
        top_color = QColor(C["border"])
        top_color.setAlphaF(0.04)
        bottom_color = QColor(C["border"])
        bottom_color.setAlphaF(0.14)
        gradient = QLinearGradient(
            bounds.x(),
            bounds.y(),
            bounds.x(),
            bounds.y() + bounds.height(),
        )
        gradient.setColorAt(0.0, top_color)
        gradient.setColorAt(1.0, bottom_color)
        painter.save()
        painter.fillPath(silhouette_path, gradient)
        painter.restore()

    def _paint_diphthong_arrows(
        self,
        painter: QPainter,
        dx: int,
        dy: int,
        dw: int,
        dh: int,
    ) -> None:
        """Overlay one curved arrow per diphthong from primary to
        secondary endpoint. Endpoints land on the cell widget's
        VISUAL centre when the (row, col) maps to a populated
        cell; otherwise fall back to the shared geometry's
        ``primary_chart_x`` / ``primary_chart_y`` anchor (e.g.,
        PHOIBLE diphthongs whose secondary slot isn't populated).
        Pre-fix the endpoints used the shared anchors directly,
        which ignored the pair-shift and the row-tier
        positioning, so arrows pointed to / from points that
        didn't match where the cells were drawn.
        """
        if not self._diphthongs:
            return
        # (row, col) -> (cell_widget, canonical_segment) so the
        # arrow target lookup can find the cell's CANONICAL
        # SEGMENT button (entries[0], highest-confidence
        # placement). Pre-fix the secondary endpoint landed on the
        # cell's geometric centre, which for a multi-entry stack
        # could sit 30+ px from the actual target button (e.g. /a/
        # in a stack of /a, aː, ã, a̰/).
        cell_by_pos: dict[tuple[int, int], tuple[QWidget, str]] = {}
        for (
            widget,
            _cx,
            _cy,
            _ps,
            _tier,
            row,
            col,
            canon_seg,
            _d,
        ) in self._cells:
            cell_by_pos[(row, col)] = (widget, canon_seg)

        def _widget_centre_and_size(
            target: QWidget,
        ) -> tuple[float, float, float, float]:
            """Return ``(centre_x, centre_y, width, height)`` for
            the target widget in THIS (VowelChartWidget) widget's
            coordinate system."""
            rect = target.rect()
            centre = target.mapTo(self, rect.center())
            return (
                float(centre.x()),
                float(centre.y()),
                float(rect.width()),
                float(rect.height()),
            )

        def _primary_target(
            row: int,
            col: int,
            segment: str,
            chart_x: float,
            chart_y: float,
        ) -> tuple[float, float, float, float]:
            # Specific segment-button INSIDE the cell takes
            # precedence so each diphthong's arrow originates at
            # its own button rather than the stack/pair
            # container's centre. A stack of six /i/-family
            # diphthongs at one cell has six buttons; the arrow
            # for /ia/ must start at the /ia/ button.
            btn = self._buttons.get(segment)
            if btn is not None and btn.isVisible():
                return _widget_centre_and_size(btn)
            entry = cell_by_pos.get((row, col))
            if entry is not None:
                return _widget_centre_and_size(entry[0])
            return (dx + chart_x * dw, dy + chart_y * dh, 0.0, 0.0)

        def _secondary_target(
            row: int,
            col: int,
            chart_x: float,
            chart_y: float,
        ) -> tuple[float, float, float, float]:
            # Aim for the cell's CANONICAL segment button
            # (entries[0]) so the arrowhead lands on the
            # canonical-vowel button rather than the cell's
            # geometric centre. For Korean /ia/ -> secondary cell
            # holds /a, aː/; arrow now points to /a/ specifically.
            entry = cell_by_pos.get((row, col))
            if entry is not None:
                cell_widget, canon_seg = entry
                btn = self._buttons.get(canon_seg)
                if btn is not None and btn.isVisible():
                    return _widget_centre_and_size(btn)
                return _widget_centre_and_size(cell_widget)
            return (dx + chart_x * dw, dy + chart_y * dh, 0.0, 0.0)

        def _rect_edge_offset(
            w: float, h: float, ux: float, uy: float
        ) -> tuple[float, float]:
            """Offset from a rectangle's centre to where a ray in
            unit direction ``(ux, uy)`` exits the rectangle of
            size ``w * h``. Used so arrows start/end at the
            button's visible edge rather than its centre -- the
            arrowhead now sits OUTSIDE the source button and the
            tip touches the target button's edge."""
            if w <= 0 or h <= 0:
                return (0.0, 0.0)
            hw = w / 2.0
            hh = h / 2.0
            tx = float("inf") if abs(ux) < 1e-9 else hw / abs(ux)
            ty = float("inf") if abs(uy) < 1e-9 else hh / abs(uy)
            t = min(tx, ty)
            return (t * ux, t * uy)

        # Group arrows by their (primary, secondary) cell pair so
        # the fan-out distributes shared-pair arrows around the
        # chord (mirrors the web SVG overlay's C3 fan-out math).
        groups: dict[
            tuple[tuple[int, int], tuple[int, int]],
            list[VowelChartDiphthong],
        ] = defaultdict(list)
        for d in self._diphthongs:
            groups[
                (
                    (d.primary_row, d.primary_col),
                    (d.secondary_row, d.secondary_col),
                )
            ].append(d)

        # Two opacity tiers in diphthong mode (the only mode in
        # which arrows render at all):
        # - default: every arrow paints at focused alpha (the chart
        #   IS the arrows in this mode -- nothing else to gate on)
        # - hover/focus: matching arrow stays at focused alpha,
        #   non-matching arrows dim so the user can follow a
        #   single trajectory cleanly in a busy cluster
        focused = self._focused_seg
        # When any arrow's segment is currently focused, dim the
        # others so the user can follow a single trajectory in a
        # busy cluster.
        has_focus = focused is not None and any(
            d.segment == focused for arrows in groups.values() for d in arrows
        )
        for arrows in groups.values():
            n = len(arrows)
            for i, d in enumerate(arrows):
                is_focus = d.segment == focused
                ax_c, ay_c, aw, ah = _primary_target(
                    d.primary_row,
                    d.primary_col,
                    d.segment,
                    d.primary_chart_x,
                    d.primary_chart_y,
                )
                bx_c, by_c, bw, bh = _secondary_target(
                    d.secondary_row,
                    d.secondary_col,
                    d.secondary_chart_x,
                    d.secondary_chart_y,
                )
                # Edge offset: start the arrow at the source
                # button's EDGE (not its centre) in the chord
                # direction; terminate at the target button's
                # EDGE. The chord (centre->centre) gives the
                # direction; ``_rect_edge_offset`` returns the
                # vector from centre to the rectangle's exit
                # point along that direction. Arrows now visibly
                # emerge from the source button and end with the
                # arrowhead touching the target button.
                chord_dx = bx_c - ax_c
                chord_dy = by_c - ay_c
                chord_len = math.hypot(chord_dx, chord_dy) or 1.0
                ux_chord = chord_dx / chord_len
                uy_chord = chord_dy / chord_len
                off_ax, off_ay = _rect_edge_offset(aw, ah, ux_chord, uy_chord)
                off_bx, off_by = _rect_edge_offset(
                    bw, bh, -ux_chord, -uy_chord
                )
                ax = ax_c + off_ax
                ay = ay_c + off_ay
                bx = bx_c + off_bx
                by = by_c + off_by
                # Fan-out factor: -1, 0, +1 for n=3; -1, +1 for n=2;
                # 0 for solo arrows. Outer arrows arc more than the
                # inner ones to keep the bundle readable.
                signed = (i / (n - 1)) * 2 - 1 if n > 1 else 1.0
                mx = (ax + bx) / 2
                my = (ay + by) / 2
                chord = math.hypot(bx - ax, by - ay) or 1.0
                base_lift = min(
                    dw * cs.DIPHTHONG_LIFT_WIDTH_FRAC_CAP,
                    chord * cs.DIPHTHONG_LIFT_CHORD_FRAC,
                )
                # Fan-out: outer arrows arc 1.3x base lift (0.5 +
                # 0.8 * 1.0); inner arrows arc 0.5x.
                lift = base_lift * signed * (0.5 + 0.8 * abs(signed))
                nx = -(by - ay) / chord
                ny = (bx - ax) / chord
                cx = mx + nx * lift
                cy = my + ny * lift
                arrow_color = QColor(C["accent"])
                # Default: focused-alpha. When ANOTHER arrow is
                # hovered, dim this one so the focused arrow
                # stands out. Mirrors the web's `:has(...)`
                # selector behaviour.
                if has_focus and not is_focus:
                    arrow_color.setAlphaF(0.25)
                else:
                    arrow_color.setAlphaF(cs.DIPHTHONG_ARROW_FOCUSED_ALPHA)
                pen = QPen(arrow_color)
                pen.setWidthF(cs.DIPHTHONG_ARROW_STROKE_PX)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                # Tangent at the terminus approximated by the
                # control-point-to-endpoint direction. Arrowhead
                # tip sits at the terminus -- which is already at
                # the target button's edge thanks to the edge
                # offset above, so no extra tip-inset is needed.
                tx = bx - cx
                ty = by - cy
                tlen = math.hypot(tx, ty) or 1.0
                ux = tx / tlen
                uy = ty / tlen
                path = QPainterPath()
                path.moveTo(ax, ay)
                path.quadTo(cx, cy, bx, by)
                painter.drawPath(path)
                # Arrowhead at the terminus, oriented along the
                # tangent. Length + half-width scale with chart
                # width so the head stays proportional.
                head_len = dw * cs.DIPHTHONG_ARROWHEAD_LEN_FRAC
                head_half = dw * cs.DIPHTHONG_ARROWHEAD_HALF_FRAC
                base_x = bx - ux * head_len
                base_y = by - uy * head_len
                left_x = base_x + (-uy) * head_half
                left_y = base_y + ux * head_half
                right_x = base_x - (-uy) * head_half
                right_y = base_y - ux * head_half
                head = QPainterPath()
                head.moveTo(bx, by)
                head.lineTo(left_x, left_y)
                head.lineTo(right_x, right_y)
                head.closeSubpath()
                painter.fillPath(head, arrow_color)
