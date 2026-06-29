"""The abstract vowel-space coordinate system (chart foundation).

This module defines the COORDINATE SYSTEM the vowel chart is drawn
on, independent of any particular inventory: the discrete height and
backness axes, their normalized ``[0, 1]`` anchor positions, the
trapezoid widths, and the axis-adjacency tables. None of it depends
on which segments an inventory contains; it is pure structure
derived once from the layout's pixel constants.

It is the LOW layer two higher layers sit on:

* :py:mod:`phonology_shared.chart.vowels` (inference) reads this
  structure to place feature bundles onto the axes.
* :py:mod:`phonology_shared.chart.vowel_geometry` (rendering) reads
  it to solve the silhouette and position cells.

Keeping it separate is what lets both of those import the same
coordinate definitions without the rendering layer reaching up into
the inference module for them.

NATURAL CONSTRAINTS this module upholds:

* All anchors are normalized fractions in ``[0, 1]``: backness x
  (:py:data:`_BACKNESS_X`) and height y (:py:data:`_HEIGHT_Y`).
* The axes are fixed-size: 7 height rows (:py:data:`ROW_LABELS`),
  3 backness columns (:py:data:`COL_LABELS`), and the rendered grid
  is 9 logical columns (0/1, 2/3, 4/5 pair slots + 6/7/8 neutral),
  mapped to backness by :py:data:`_BACKNESS_GROUP_BY_COL`.
* Every fraction is DERIVED from the layout pixel constants
  (``BTN_W``, ``VOWEL_PAIR_GAP_PX``, ``VOWEL_PAIR_SEPARATOR_PX``)
  via :py:func:`_derive_backness_anchors`; there are no hand-picked
  magic fractions.

This module imports ONLY presentation pixel constants. It must not
import :py:mod:`~phonology_shared.chart.vowels`,
:py:mod:`~phonology_shared.chart.vowel_geometry`, or
:py:mod:`~phonology_shared.chart.consonants`; those sit above it.
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

# Height axis: each row's label plus its canonical (high, low,
# tense) signature. The tense column distinguishes the tense/lax
# split within a height tier (None where the row carries no tense
# convention). The label column is the row axis; the feature
# columns are the canonical signature the inference layer compares
# against. Immutable so importers cannot mutate the shared
# singleton.
VOWEL_HEIGHT: tuple[tuple[str, str, str, str | None], ...] = (
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
    ("Mid", "-", "-", None),
    ("Open-mid", "-", "-", "-"),
    ("Near-open", "-", "+", "-"),
    ("Open", "-", "+", None),
)
ROW_LABELS: tuple[str, ...] = tuple(label for label, *_ in VOWEL_HEIGHT)

# Column labels in display order. The rendered chart is 6 columns
# wide because each place alternates (unrounded, rounded).
COL_LABELS: tuple[str, ...] = ("Front", "Central", "Back")

# Normalized abstract-vowel-space coordinates exposed on
# :py:class:`phonology_shared.chart.vowels.VowelPlacement`. Seven
# rows distributed at uniform 0.15 spacing across [0.05, 0.95] so
# the top button at Close and the bottom button at Open never clip
# against the data area's top or bottom edge, and the silhouette has
# a small visible padding above and below the cells. The padding is
# deliberately modest (0.05, not a larger fraction) so the trapezoid
# top sits close to the Front / Central / Back column labels rather
# than floating a wide empty band below them. ``Mid`` sits midway at
# 0.50 between Close-mid and Open-mid.
_HEIGHT_Y: dict[str, float] = {
    "Close": 0.05,
    "Near-close": 0.20,
    "Close-mid": 0.35,
    "Mid": 0.50,
    "Open-mid": 0.65,
    "Near-open": 0.80,
    "Open": 0.95,
}


#: Canonical content width in pixels: three backness pair slots
#: (each an unrounded + rounded button pair) plus the two
#: inter-slot separators. The single definition every normalised
#: fraction below divides by; the outline module re-exports it as
#: ``_VOWEL_CONTENT_W_PX``.
_CANONICAL_CONTENT_W_PX: float = float(
    3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX
)


def _derive_backness_anchors() -> tuple[dict[str, float], float]:
    """Derive backness anchors and the trapezoid bottom-width from
    real layout pixels.

    The TOP row of the chart needs to fit three backness columns
    (front, central, back), each holding an unrounded + rounded
    pair of segment buttons, plus a separator between adjacent
    backness columns. The BOTTOM row of the trapezoid needs to fit
    at least two backness columns + one separator so a typical
    open-row inventory (front + back, no central) still has room
    for its cells.

    Returns:
        ``(anchors, bottom_width)`` where ``anchors`` maps
        ``"front"`` / ``"central"`` / ``"back"`` to a normalised
        x in ``[0, 1]`` (the column centre for the TOP, widest
        row), and ``bottom_width`` is the trapezoid's bottom edge
        as a fraction of the top edge.

    The numbers fall out of the existing pixel constants
    (``BTN_W``, ``VOWEL_PAIR_GAP_PX``, ``VOWEL_PAIR_SEPARATOR_PX``):
    no hand-picked fractions, no magic numbers.
    """
    backness_w = 2 * BTN_W + VOWEL_PAIR_GAP_PX
    content_w = _CANONICAL_CONTENT_W_PX
    front_centre = backness_w / 2.0
    central_centre = backness_w + VOWEL_PAIR_SEPARATOR_PX + backness_w / 2.0
    back_centre = content_w - backness_w / 2.0
    anchors = {
        "front": front_centre / content_w,
        "central": central_centre / content_w,
        "back": back_centre / content_w,
    }
    min_bottom_content = 2 * backness_w + VOWEL_PAIR_SEPARATOR_PX
    bottom_width = min_bottom_content / content_w
    return anchors, bottom_width


_BACKNESS_X, _DERIVED_BOTTOM_WIDTH = _derive_backness_anchors()

#: Half-width of the signed offset that separates the rounded
#: mate from its unrounded partner inside a backness anchor.
#: Derived from the pixel constants so the two mates are exactly
#: one button-width apart centre-to-centre on the widest row of
#: the trapezoid (no overlap, no gratuitous gap). Signed so a
#: renderer can apply ``x + pair_offset`` directly.
_PAIR_OFFSET_HALF: float = (
    (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _CANONICAL_CONTENT_W_PX
)


# Reverse of ROW_LABELS so a row label ("Close", "Open-mid", ...) maps
# back to its row index without an O(n) scan on every placement.
_ROW_LABEL_TO_INDEX: dict[str, int] = {
    label: i for i, label in enumerate(ROW_LABELS)
}


#: Width of the trapezoid's bottom edge as a fraction of its top
#: edge. Derived (:py:func:`_derive_backness_anchors`) from the
#: pixel constants so the bottom row has just enough room for two
#: backness columns plus the inter-column separator.
TRAPEZOID_BOTTOM_WIDTH: float = _DERIVED_BOTTOM_WIDTH
#: Triangle bottom edge: one backness column wide. Derived from
#: the same pixel constants so the lowest row of a triangle chart
#: still has finite horizontal extent for a single vowel pair.
TRIANGLE_BOTTOM_WIDTH: float = (
    2 * BTN_W + VOWEL_PAIR_GAP_PX
) / _CANONICAL_CONTENT_W_PX
#: Outer envelope of a single backness pair, expressed as a
#: fraction of the canonical content width (i.e. the distance
#: from the pair's anchor centre to the outer edge of either
#: rounded or unrounded button). The renderer subtracts this from
#: the front anchor to find the silhouette left edge (still
#: normalised; the front edge keeps the canonical extent).
_PAIR_OUTER_EXTENT: float = (
    (BTN_W + VOWEL_PAIR_GAP_PX) / 2 + BTN_W / 2
) / _CANONICAL_CONTENT_W_PX


#: Single-step "lowered" move on the height axis: each key is the
#: base row, value is the row one step more open. Rows at the
#: bottom of the chart (``Open``) have no further lowering target.
#: This is the discrete adjacency of the height axis; the inference
#: layer's relative-feature refinement walks it.
_HEIGHT_LOWERED_STEP: dict[str, str] = {
    "Close": "Near-close",
    "Near-close": "Close-mid",
    "Close-mid": "Mid",
    "Mid": "Open-mid",
    "Open-mid": "Near-open",
    "Near-open": "Open",
}

#: Inverse of :py:data:`_HEIGHT_LOWERED_STEP` ("raised" goes one
#: step more close). Computed once so the refinement helper does
#: not rebuild the table on every call.
_HEIGHT_RAISED_STEP: dict[str, str] = {
    v: k for k, v in _HEIGHT_LOWERED_STEP.items()
}


#: Single-step "advance" move on the backness axis: each key is the
#: base column, value is the column one step more front. ``front``
#: has no further advancement target.
_BACKNESS_ADVANCED_STEP: dict[str, str] = {
    "back": "central",
    "central": "front",
}

#: Inverse of :py:data:`_BACKNESS_ADVANCED_STEP` ("retracted" goes
#: one step more back).
_BACKNESS_RETRACTED_STEP: dict[str, str] = {
    v: k for k, v in _BACKNESS_ADVANCED_STEP.items()
}


#: Logical grid column -> backness group. The rendered grid is 9
#: columns: 0/1 front pair, 2/3 central pair, 4/5 back pair, and
#: 6/7/8 the neutral-rounding column for each backness. The single
#: source mapping a column index back to its backness slot.
_BACKNESS_GROUP_BY_COL: Mapping[int, str] = {
    0: "front",
    1: "front",
    6: "front",
    2: "central",
    3: "central",
    7: "central",
    4: "back",
    5: "back",
    8: "back",
}


#: Backness axis verdict -> its unrounded-pair column index; the
#: rounded mate is ``base + 1`` and the neutral-rounding row is
#: ``6 + base // 2``. Module-level so it isn't rebuilt per placement
#: call.
_PLACE_TO_COLUMN: Mapping[str, int] = {"front": 0, "central": 2, "back": 4}
