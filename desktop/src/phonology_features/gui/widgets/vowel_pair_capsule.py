"""Segmented capsule container for a vowel PAIR.

A vowel pair (long / nasal / rhotic / phonation / tone mates that share
one vowel-space position) renders as ONE segmented capsule: a single
rounded outer frame + shared fill holding the two mates, split by a
faint vertical divider, so the pair reads as one articulatory position
with two variants rather than two floating buttons. This is the desktop
twin of the web ``.vowel-capsule`` CSS.

The two mates are the shared, pooled :class:`SegmentButton` widgets put
into "in-capsule" mode (flat, borderless, transparent) via
:meth:`SegmentButton.set_in_capsule`; this widget only paints the frame,
fill, and divider behind them, and masks its children to the rounded
outline (Qt's equivalent of the web's ``overflow: hidden``). It never
mutates the shared button style cache, so the same pooled buttons keep
their normal look when they return to the consonant grid.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRegion,
    QResizeEvent,
)
from PyQt6.QtWidgets import QWidget

from phonology_shared.presentation import chart_style as cs
from phonology_shared.presentation.palette import C
from phonology_shared.presentation.view_models import SegmentState


class VowelPairCapsule(QWidget):
    """Paints the rounded frame + shared fill + faint divider for a
    vowel pair; hosts the two in-capsule mate buttons."""

    def _frame_pen(self) -> QPen:
        """The outer-frame pen, whose LINE STYLE encodes the cells'
        dominant state (the colour-blind cue for the whole pill) so the
        segmented capsule reads as ONE unit: selected / matched -> solid
        accent, suggested -> dashed accent, unmatched -> dotted border,
        default -> solid border. Mirrors the web
        ``.vowel-capsule:has(> .seg-btn[data-state=...])`` frame rules;
        width stays constant so the box never resizes."""
        states = {
            st
            for kid in self.findChildren(QWidget)
            if kid.parent() is self
            and (st := getattr(kid, "_state", None)) is not None
        }
        color = C["border"]
        style = Qt.PenStyle.SolidLine
        if states & {SegmentState.SELECTED, SegmentState.MATCHED}:
            color, style = C["accent"], Qt.PenStyle.SolidLine
        elif SegmentState.SUGGESTED in states:
            color, style = C["accent"], Qt.PenStyle.DashLine
        elif SegmentState.UNMATCHED in states:
            color, style = C["border"], Qt.PenStyle.DotLine
        pen = QPen(QColor(color))
        pen.setWidthF(cs.BORDER_PX["std"])
        pen.setStyle(style)
        return pen

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The frame + fill are painted; the widget's own background is
        # transparent so it composes over the chart's flat field.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _radius(self) -> float:
        return float(cs.VOWEL_CAPSULE_RADIUS_PX)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        # Mask children to the rounded outline so a selected cell's
        # square fill can't poke past the capsule's rounded corners
        # (the desktop analogue of ``overflow: hidden``). The painted
        # frame below is anti-aliased on top, hiding the mask's aliased
        # edge.
        radius = self._radius()
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event: QPaintEvent | None) -> None:
        radius = self._radius()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Half-stroke inset so the frame stroke sits fully inside the box.
        rect = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        # Shared fill (kept at the default chip weight per the design).
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C["seg_default"]))
        painter.drawRoundedRect(rect, radius, radius)
        # Faint dividers between ADJACENT cells. Generic over the cell
        # arrangement: a 2-cell pair, an N-cell single-feature row, and
        # a 2x2 contrast grid all draw a line on each edge a cell shares
        # with a neighbour, so a partial grid's empty corner gets no
        # divider. Each shared edge is drawn once (from the right / lower
        # cell's side).
        divider = QColor(C["border"])
        divider.setAlphaF(cs.VOWEL_CAPSULE_DIVIDER_ALPHA)
        dpen = QPen(divider)
        dpen.setWidthF(1.0)
        painter.setPen(dpen)
        kids = [
            w
            for w in self.findChildren(QWidget)
            if w.parent() is self and w.isVisible()
        ]
        for kid in kids:
            g = kid.geometry()
            for other in kids:
                if other is kid:
                    continue
                og = other.geometry()
                shares_v = og.top() < g.bottom() and g.top() < og.bottom()
                shares_h = og.left() < g.right() and g.left() < og.right()
                if abs(og.right() + 1 - g.left()) <= 2 and shares_v:
                    x = g.left() - 0.5
                    painter.drawLine(
                        QPointF(x, float(max(g.top(), og.top()) + 1)),
                        QPointF(x, float(min(g.bottom(), og.bottom()) - 1)),
                    )
                if abs(og.bottom() + 1 - g.top()) <= 2 and shares_h:
                    y = g.top() - 0.5
                    painter.drawLine(
                        QPointF(float(max(g.left(), og.left()) + 1), y),
                        QPointF(float(min(g.right(), og.right()) - 1), y),
                    )
        # Outer frame stroke: one rounded border whose line style carries
        # the cells' dominant state (dashed = suggested, dotted =
        # unmatched, solid-accent = selected), instead of per-cell borders
        # that doubled at the dividers and clashed with the rounded ends.
        painter.setPen(self._frame_pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()
