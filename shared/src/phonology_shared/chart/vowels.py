"""Chart-placement policy for vowel segments.

Pure-Python, shared by the desktop :py:class:`VowelChartWidget` and
the web app's vowel chart renderer (relayed into the Pyodide bundle
by the web build).

**Scope.** This module is chart placement policy, not a general theory
of vowel phonology. Given a segment's feature bundle, it resolves the
best available display position in a vowel chart. The resolved position
may be rendered as a square grid cell, a trapezoid point, a triangle
point, or another chart geometry. The phonological evidence and the
screen geometry are separate concerns: this module first interprets
height, backness, and rounding evidence, then the renderer projects
that evidence into a visible chart.

**Theory-neutrality limits.** This module is intentionally feature-first.
It does not infer features from IPA symbols, and it does not require a
particular phonological theory. It does, however, make limited
display-oriented assumptions when a feature system supplies enough
evidence for a useful chart placement.

* `[+high, -low]` identifies the high vowel region. A split feature
  such as `[tense]` or `[ATR]` may refine this into close versus
  near-close when the inventory uses that distinction.

* `[-high, -low]` identifies the mid vowel region. A split feature
  such as `[tense]` or `[ATR]` may refine this into close-mid
  versus open-mid. A policy may optionally treat `0` on the split
  feature as true mid, but that is a chart convention, not a universal
  interpretation of underspecification.

* `[-high, +low]` identifies the low vowel region. A policy may
  refine this into near-open versus open, but low-vowel splitting is
  theory-sensitive and should be flagged or documented when enabled.

* `[+front]` -> front and `[+back]` -> back are direct readings.
  `[-front, -back]` -> central is a direct reading when both features
  are explicitly present with negative values.

* `[-back]` without `[front]` is not automatically equivalent to
  `[+front]`. It may be used as a frontness fallback only when the
  inventory lacks a `Front` feature altogether. If the inventory uses
  `Front` elsewhere, segment-level absence of `front` is treated as
  underspecification and anchored conservatively.

* `[-front]` without `[back]` is ambiguous between central and back
  in many binary systems. This module anchors it centrally with LOW
  confidence unless a more specific inventory policy is supplied.

* `[+round]` -> rounded and `[-round]` -> unrounded are direct
  readings. `0round` or absent `round` does not mean unrounded by
  default in all theories; it may be rendered as neutral, default
  unrounded, or low-confidence unrounded according to policy.

* `[+labial]` -> rounded is only a profile-gated fallback when the
  inventory has `Labial` and lacks `Round`. Some feature geometries
  associate vowel rounding with Labial, but this is not safe as a
  universal inference.

* `[+coronal]` -> front is a last-resort, nonstandard fallback. It is
  disabled by default, enabled only by policy, and should always be
  marked LOW confidence / NONSTANDARD when used.

* `[tense]` and `[ATR]` are not universally equivalent. When both
  are present and disagree, this module follows the configured policy
  and records the divergence in the placement evidence so the choice is
  auditable.

* Fine IPA distinctions such as near-front, near-back, centralized,
  raised, lowered, advanced, retracted, compressed, and protruded
  require explicit features or explicit chart heuristics. They should
  not be inferred silently from a coarse bundle such as
  `[+high, +back, +round]`.

**Underspecification.** Underspecified or conflicting evidence produces
a low-confidence anchor, not a phonological claim. For example, a vowel
may be displayed near the central mid area because the chart needs a
stable location, not because the segment is asserted to be phonetically
or phonologically central mid. Callers should use `confidence`,
`reason`, and `flags` to surface this distinction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import IntEnum, StrEnum

from phonology_shared.presentation.constants import BTN_W
from phonology_shared.presentation.layout import (
    SEG_BTN_H,
    VOWEL_PAIR_GAP_PX,
    VOWEL_PAIR_SEPARATOR_PX,
)

# The seven height tiers of the maximalist vowel chart, in row
# order. Tuple is (label, +high, +low, +tense-or-atr): the feature
# bundle that canonically populates the row. The ``Mid`` row sits
# between Close-mid and Open-mid as a Tier 2 display slot for
# [-high, -low] vowels whose tense/ATR is unspecified (display
# inference only; engine logic still treats those as
# underspecified). Used by the chart widget to label rows and by
# tests to spot-check that placement maps correctly. Immutable so
# importers cannot mutate the shared singleton.
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


class Confidence(IntEnum):
    """Placement confidence ranks. Higher value = higher confidence;
    ``min(a, b)`` picks the weaker of two placement signals (used
    when height and backness disagree). IntEnum so direct comparison
    and ``min``/``max`` work without a lookup table.
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3


class VowelChartShape(StrEnum):
    """Visual envelope the renderer paints around the vowel chart.

    The placement decisions (height, backness, rounding) are the
    same across both shapes; only the chart's outer outline
    changes. :py:attr:`TRAPEZOID` matches the IPA vowel
    quadrilateral convention and is the default (the bottom row
    sits narrower than the top because open vowels carry less
    front/back distinction). :py:attr:`TRIANGLE` collapses the
    bottom edge to a near-point and is appropriate for inventories
    that lack any front/back contrast.

    :py:func:`infer_vowel_shape` picks one from a
    :py:class:`VowelProfile`; the choice is a cosmetic envelope
    hint, so a future user policy can override it without
    changing any placement.
    """

    TRAPEZOID = "trapezoid"
    TRIANGLE = "triangle"


class FeatureState(StrEnum):
    """Four-state value model for a feature on a segment.

    Hayes (2009) treats ``"0"`` as a deliberate "don't care" value,
    distinct from a missing key (feature not in the inventory or
    not supplied for this segment). Collapsing the two erases the
    author's intent on underspecification. Inference paths that
    need the distinction route through :py:func:`_feature_state`;
    paths that only care about "any explicit value" still get away
    with ``feats.get(key, "0")``.
    """

    POS = "+"
    NEG = "-"
    ZERO = "0"
    ABSENT = "absent"


class PlacementFlag(StrEnum):
    """Tags on a placement decision that the renderer can read
    without parsing the free-text reason string.

    The four anchor-related flags are how the placement code keeps
    "central by ``[-front, -back]`` specification" distinct from
    "central as a conflict anchor" distinct from "central because no
    usable evidence existed". Same screen position, three different
    semantics; the flags let downstream code surface that honestly.
    """

    DIRECT = "direct"
    FALLBACK = "fallback"
    PROFILE_GATED = "profile_gated"
    UNDERSPECIFIED = "underspecified"
    CONFLICT = "conflict"
    DEFAULT_ANCHOR = "default_anchor"
    NONSTANDARD = "nonstandard"
    ATR_TENSE_DIVERGENCE = "atr_tense_divergence"


@dataclass(frozen=True)
class VowelProfile:
    """Which vowel-relevant features are actively used in this
    inventory. Pure inventory facts; theory-laden choices live on
    :py:class:`PlacementPolicy`.

    Fields default ``False`` so existing call sites that construct
    a partial profile (most test fixtures predate the expansion)
    keep working; :py:func:`detect_vowel_profile` populates the
    full set from real inventory data.
    """

    has_front: bool = False
    has_back: bool = False
    has_high: bool = False
    has_low: bool = False
    has_round: bool = False
    has_labial: bool = False
    has_atr: bool = False
    has_tense: bool = False
    has_coronal: bool = False
    has_syllabic: bool = False
    has_consonantal: bool = False
    has_long: bool = False
    #: True iff the inventory has at least one ``Long+`` vowel AND
    #: at least one ``Long-`` vowel. Distinguishes inventories that
    #: USE Long as a contrast (e.g. Arabic ``/i/`` vs ``/iː/``) from
    #: inventories where ``Long-`` is just the default polarity on
    #: every vowel (English's ``Long-`` everywhere does not mean the
    #: inventory contrasts length). The Long-based Tier 3 height
    #: refinement only fires when this flag is True so non-contrastive
    #: inventories keep their canonical placements.
    has_long_contrast: bool = False

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR or Tense to split height
        tiers (the difference between Close and Near-close, or
        Close-mid and Open-mid).
        """
        return self.has_atr or self.has_tense


@dataclass(frozen=True)
class PlacementPolicy:
    """Knobs for theory-laden inference decisions.

    Defaults preserve the module's pre-policy behavior so existing
    inventories keep their placements; per-inventory overrides let
    callers opt into the paper-recommended stricter defaults
    (``allow_coronal_front_fallback=False``,
    ``split_low_by_tense=False``).
    """

    #: Allow ``[+labial]`` to infer rounding when the inventory has
    #: no ``Round`` feature. Sagey-tradition fallback; tagged
    #: ``FALLBACK | PROFILE_GATED`` on the rounding evidence.
    allow_labial_round_fallback: bool = True
    #: Allow ``[+coronal]`` to infer frontness when the inventory
    #: has no ``Front`` feature. Last-resort backstop the paper
    #: recommends keeping off; tagged ``NONSTANDARD`` when fired.
    allow_coronal_front_fallback: bool = False
    #: Apply the ATR/tense split to low vowels (Near-open vs Open).
    #: Hayes treats low vowels as ``[0tense]`` and notes the
    #: ATR-vs-tense identification is unsettled; the paper
    #: recommends defaulting off. Kept True here to preserve
    #: pre-policy placements on bundled inventories.
    split_low_by_tense: bool = True


@dataclass(frozen=True)
class AxisEvidence:
    """One axis's contribution to a placement: the resolved value
    plus the evidence that produced it.

    Three of these (height, backness, rounding) feed
    :py:class:`VowelPlacement`. The renderer reads ``flags`` to
    decide visual affordances (badges, opacity, etc.) without
    re-parsing the free-text reason string.
    """

    value: str
    confidence: Confidence
    source: str
    reason: str
    flags: frozenset[PlacementFlag] = field(default_factory=frozenset)


@dataclass(frozen=True)
class VowelPlacement:
    """A vowel's position in the IPA chart.

    Carries two representations of the same placement decision so a
    future shape-projection layer (trapezoid, triangle) has the
    data it needs without re-deriving anything:

    * ``row`` / ``col``: discrete grid coordinates the current
      desktop and web renderers consume. ``row`` is the height
      tier (index into :py:data:`ROW_LABELS`); ``col`` is the
      column index (front-unr, front-rnd, central-unr,
      central-rnd, back-unr, back-rnd, 0-5; plus front-neutral,
      central-neutral, back-neutral, 6-8). Neutral cols apply to
      Tier 2 ``0round`` placements that sit at the backness
      anchor centre with no L/R pair shift.
    * ``x`` / ``y`` / ``pair_offset``: normalized continuous
      coordinates in abstract vowel space. ``x`` is the backness
      anchor (0.0 front, 0.5 central, 1.0 back), ``y`` is the
      height anchor (0.0 close, 1.0 open), and ``pair_offset`` is
      the small signed shift within a rounded/unrounded pair
      (negative for unrounded, positive for rounded, zero when
      rounding is unknown). A future renderer that wants a
      trapezoid or triangle reads these floats and projects them;
      the current grid renderer ignores them.

    Per-axis ``height`` / ``backness`` / ``rounding`` carry the
    evidence each placement decision was made from. Top-level
    ``confidence`` and ``reason`` are derived summaries kept for
    backward compatibility with existing consumers.
    """

    row: int
    col: int
    x: float
    y: float
    pair_offset: float
    confidence: Confidence
    reason: str
    height: AxisEvidence | None = None
    backness: AxisEvidence | None = None
    rounding: AxisEvidence | None = None
    flags: frozenset[PlacementFlag] = field(default_factory=frozenset)


def _feature_state(feats: Mapping[str, str], key: str) -> FeatureState:
    """Resolve ``feats[key]`` into the four-state value model.
    ``ABSENT`` is distinct from ``ZERO``: the former means the
    feature is not in this bundle (typically inventory does not use
    it), the latter is an explicit "don't care" the author marked.
    Any unrecognised string value is folded to ZERO defensively.
    """
    if key not in feats:
        return FeatureState.ABSENT
    raw = feats[key]
    if raw == "+":
        return FeatureState.POS
    if raw == "-":
        return FeatureState.NEG
    return FeatureState.ZERO


#: Reverse of ``ROW_LABELS`` so axis evidence carrying a row label
#: ("Close", "Open-mid", ...) can be turned back into a row index
#: without an O(n) scan on every placement.
# Normalized abstract-vowel-space coordinates exposed on
# :py:class:`VowelPlacement`. Seven rows distributed at uniform
# 0.14 spacing across [0.08, 0.92] so the top button at Close and
# the bottom button at Open never clip against the data area's
# top or bottom edge, and the silhouette has visible padding above
# and below the cells. ``Mid`` sits midway at 0.50 between
# Close-mid and Open-mid.
_HEIGHT_Y: dict[str, float] = {
    "Close": 0.08,
    "Near-close": 0.22,
    "Close-mid": 0.36,
    "Mid": 0.50,
    "Open-mid": 0.64,
    "Near-open": 0.78,
    "Open": 0.92,
}


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
    content_w = 3 * backness_w + 2 * VOWEL_PAIR_SEPARATOR_PX
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
    (BTN_W + VOWEL_PAIR_GAP_PX)
    / 2.0
    / (3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX)
)


_ROW_LABEL_TO_INDEX: dict[str, int] = {
    label: i for i, label in enumerate(ROW_LABELS)
}


def _normalize_feat_keys(feats: Mapping[str, str]) -> dict[str, str]:
    """Lowercase every key in ``feats`` so downstream lookups by
    canonical name (``high``, ``low``, ``front``, etc.) work
    regardless of whether the caller passed raw PascalCase
    inventory keys or pre-normalized lowercase keys.

    The placement code is the only consumer that mandates canonical
    case (segment_grouper uses a similar convention); doing the
    lowercase pass HERE means call sites cannot accidentally pass
    raw inventory feats and silently get every vowel placed in the
    Open-mid Central default cell.
    """
    return {k.lower(): v for k, v in feats.items()}


def detect_vowel_profile(
    segs: list[str], seg_feats: Mapping[str, Mapping[str, str]]
) -> VowelProfile:
    """Scan the vowel segments to determine which features are in play.

    ``seg_feats`` maps each segment to its feature bundle. Keys
    inside each bundle are case-normalized internally, so callers
    may pass raw PascalCase inventory feats (``{"High": "+", ...}``)
    or pre-normalized lowercase feats (``{"high": "+", ...}``).
    """
    active: set[str] = set()
    long_polarities: set[str] = set()
    for seg in segs:
        for feat, val in seg_feats.get(seg, {}).items():
            if val != "0":
                active.add(feat.lower())
            if feat.lower() == "long" and val in ("+", "-"):
                long_polarities.add(val)
    return VowelProfile(
        has_front="front" in active,
        has_back="back" in active,
        has_high="high" in active,
        has_low="low" in active,
        has_round="round" in active,
        has_labial="labial" in active,
        has_atr="atr" in active,
        has_tense="tense" in active,
        has_coronal="coronal" in active,
        has_syllabic="syllabic" in active,
        has_consonantal="consonantal" in active,
        has_long="long" in active,
        has_long_contrast=("+" in long_polarities)
        and ("-" in long_polarities),
    )


#: Width of the trapezoid's bottom edge as a fraction of its top
#: edge. Derived (:py:func:`_derive_backness_anchors`) from the
#: pixel constants so the bottom row has just enough room for two
#: backness columns plus the inter-column separator.
TRAPEZOID_BOTTOM_WIDTH: float = _DERIVED_BOTTOM_WIDTH
#: Triangle bottom edge: one backness column wide. Derived from
#: the same pixel constants so the lowest row of a triangle chart
#: still has finite horizontal extent for a single vowel pair.
TRIANGLE_BOTTOM_WIDTH: float = (2 * BTN_W + VOWEL_PAIR_GAP_PX) / (
    3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX
)
#: Outer envelope of a single backness pair, expressed as a
#: fraction of the canonical content width (i.e. the distance
#: from the pair's anchor centre to the outer edge of either
#: rounded or unrounded button). The renderer adds this to the
#: back anchor to find the silhouette right edge, and subtracts
#: it from the front anchor to find the silhouette left edge.
_PAIR_OUTER_EXTENT: float = ((BTN_W + VOWEL_PAIR_GAP_PX) / 2 + BTN_W / 2) / (
    3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX
)


def vowel_silhouette(
    shape: VowelChartShape,
    top_logical_row: int = 0,
    bottom_logical_row: int | None = None,
) -> VowelChartSilhouette:
    """Compute the silhouette for an inventory whose populated
    rows span ``top_logical_row`` to ``bottom_logical_row``
    (inclusive, indices into :py:data:`ROW_LABELS`).

    Defaults reproduce the canonical 7-row Close-to-Open silhouette
    (used by :py:func:`web/scripts/build.py` to bake fallback CSS
    variables). Inventory-adaptive callers pass the actual
    populated row range so the silhouette top and bottom widths
    track the IPA narrowness of the rows actually rendered: an
    inventory whose lowest row is Open-mid carries a wider bottom
    edge than one with a true Open vowel.

    The silhouette top edge always sits at the Close anchor
    (``_HEIGHT_Y["Close"]``) and the bottom edge at the Open anchor
    (``_HEIGHT_Y["Open"]``) so the data area is fully used
    regardless of which rows are populated; the
    inventory-adaptive part is only the widths at those edges.
    """
    if bottom_logical_row is None:
        bottom_logical_row = len(ROW_LABELS) - 1
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    bottom_width_canonical = (
        TRIANGLE_BOTTOM_WIDTH
        if shape == VowelChartShape.TRIANGLE
        else TRAPEZOID_BOTTOM_WIDTH
    )
    top_logical_y = _HEIGHT_Y[ROW_LABELS[top_logical_row]]
    bottom_logical_y = _HEIGHT_Y[ROW_LABELS[bottom_logical_row]]
    top_row_width = 1.0 - (1.0 - bottom_width_canonical) * top_logical_y
    bottom_row_width = 1.0 - (1.0 - bottom_width_canonical) * bottom_logical_y
    front_at_top = back + top_row_width * (front - back)
    front_at_bottom = back + bottom_row_width * (front - back)
    y_anchor_top = _HEIGHT_Y["Close"]
    y_anchor_bottom = _HEIGHT_Y["Open"]
    return VowelChartSilhouette(
        shape=shape,
        top_y=y_anchor_top,
        bottom_y=y_anchor_bottom,
        top_left=front_at_top - pair_outer,
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_row_width,
        bottom_width=bottom_row_width,
    )


def vowel_trapezoid_corners(
    shape: VowelChartShape,
    top_logical_row: int = 0,
    bottom_logical_row: int | None = None,
) -> dict[str, float]:
    """Legacy corners-as-dict helper. Returns the same six values
    (``top_left``, ``top_right``, ``bottom_left``, ``bottom_right``,
    ``top_y``, ``bottom_y``) that pre-silhouette callers consumed,
    derived via :py:func:`vowel_silhouette` so inventory-adaptive
    parameters work transparently. New callers should prefer
    :py:func:`vowel_silhouette` and access the dataclass fields
    directly.
    """
    sil = vowel_silhouette(shape, top_logical_row, bottom_logical_row)
    return {
        "top_left": sil.top_left,
        "top_right": sil.top_right,
        "bottom_left": sil.bottom_left,
        "bottom_right": sil.bottom_right,
        "top_y": sil.top_y,
        "bottom_y": sil.bottom_y,
    }


def project_to_chart_xy(
    x: float,
    y: float,
    pair_offset: float,
    shape: VowelChartShape,
) -> tuple[float, float]:
    """Project an abstract-vowel-space point onto the chart's
    silhouette.

    ``x`` (0.0 front, 1.0 back), ``y`` (0.0 close, 1.0 open), and
    ``pair_offset`` (signed within-pair shift) come from
    :py:class:`VowelPlacement`. Returns ``(chart_x, chart_y)``
    where both values land in ``[0, 1]`` for renderers that drop
    cells via ``left: calc(chart_x * 100%)`` / ``top: calc(chart_y
    * 100%)``.

    The projection is **back-anchored**: the back column sits at
    a constant ``chart_x`` across every row (so the silhouette's
    right edge can be drawn as a single vertical line that the
    back vowels are flush against). Cells to the left of the back
    anchor migrate toward it as the row narrows; the front column
    migrates the most. The formula is

        chart_x = back + row_width * (x - back)

    so ``x = back`` is a fixed point and ``x < back`` shifts right
    by ``(1 - row_width) * (back - x)`` as ``y`` grows. ``x``
    values to the right of the back anchor (i.e. positions inside
    the back pair's pixel envelope) ride the same formula but
    contract slightly so the back pair's outer extent also stays
    flush with the silhouette right edge.

    Pair offset is included for backward compatibility but is now
    applied by the renderer in pixels (see
    :py:class:`VowelChartCell.pair_side`); call this method with
    ``pair_offset = 0.0`` to obtain the pure backness-anchor
    projection.
    """
    if shape == VowelChartShape.TRIANGLE:
        bottom_width = TRIANGLE_BOTTOM_WIDTH
    else:
        bottom_width = TRAPEZOID_BOTTOM_WIDTH
    row_width = 1.0 - (1.0 - bottom_width) * y
    back = _BACKNESS_X["back"]
    chart_x = back + row_width * (x + pair_offset - back)
    return chart_x, y


def infer_vowel_shape(profile: VowelProfile) -> VowelChartShape:
    """Pick a chart shape from inventory facts.

    :py:attr:`VowelChartShape.TRAPEZOID` is the default: it matches
    the IPA vowel-quadrilateral convention, where the open-vowel
    row sits narrower than the close-vowel row. A
    near-rectangular trapezoid (small narrowing) is still a
    trapezoid; the projector's bottom-edge width controls how
    visually obvious the narrowing is.

    :py:attr:`VowelChartShape.TRIANGLE` fires only when the
    inventory has no front/back contrast at all. Without backness,
    the chart collapses to a single column of heights and a
    triangular envelope reads more honestly than a trapezoid that
    would imply an unused front/back axis.
    """
    if not (profile.has_front or profile.has_back):
        return VowelChartShape.TRIANGLE
    return VowelChartShape.TRAPEZOID


def _nonzero(val: str | None) -> str | None:
    """``val`` if it carries real feature information, else ``None``."""
    return val if val and val != "0" else None


def _height_split_value(
    feats: Mapping[str, str],
) -> tuple[str | None, str, bool]:
    """Resolve the tense/ATR split that distinguishes adjacent
    height tiers (Close vs Near-close, Close-mid vs Open-mid).

    Returns ``(value, source, divergent)`` where ``value`` is
    ``"+"``, ``"-"``, or ``None`` (no specification), ``source``
    names which feature supplied the value, and ``divergent``
    is True when both ``tense`` and ``atr`` were specified but
    disagreed (so the placement object can attach the
    ``ATR_TENSE_DIVERGENCE`` flag).

    Resolution policy: when both specified and agree, take it.
    When both specified and disagree, prefer ``tense`` and surface
    the conflict in the source string. When only one is specified,
    use it. When neither is specified, return ``None``.
    """
    tense = _nonzero(feats.get("tense"))
    atr = _nonzero(feats.get("atr"))
    if tense is not None and atr is not None:
        if tense == atr:
            return tense, "tense/ATR", False
        return tense, "tense (overrides conflicting ATR)", True
    if tense is not None:
        return tense, "tense", False
    if atr is not None:
        return atr, "ATR", False
    return None, "none", False


def _infer_height(
    feats: Mapping[str, str],
    profile: VowelProfile,
    policy: PlacementPolicy,
) -> AxisEvidence:
    """Resolve the vowel's height tier to a row label and confidence.

    The returned :py:class:`AxisEvidence` carries a row-label
    ``value`` (one of :py:data:`ROW_LABELS`) plus flags marking the
    placement as direct, conflicted, or default-anchored. The
    caller maps the label back to a row index via
    :py:data:`_ROW_LABEL_TO_INDEX`.
    """
    hi = feats.get("high", "0")
    lo = feats.get("low", "0")
    split_value, split_source, atr_tense_divergent = _height_split_value(feats)
    base_flags: frozenset[PlacementFlag] = (
        frozenset({PlacementFlag.ATR_TENSE_DIVERGENCE})
        if atr_tense_divergent
        else frozenset()
    )
    is_high_vowel = hi == "+" and lo == "-"
    is_low_vowel = hi == "-" and lo == "+"
    is_mid_vowel = hi == "-" and lo == "-"
    if is_high_vowel:
        if profile.has_height_sub_distinction and split_value == "-":
            return AxisEvidence(
                "Near-close",
                Confidence.MEDIUM,
                "height",
                f"Near-close: [+high, -low, -{split_source}]",
                base_flags | {PlacementFlag.DIRECT},
            )
        if split_value == "+":
            return AxisEvidence(
                "Close",
                Confidence.HIGH,
                "height",
                f"Close: [+high, -low, +{split_source}]",
                base_flags | {PlacementFlag.DIRECT},
            )
        return AxisEvidence(
            "Close",
            Confidence.HIGH,
            "height",
            "Close: [+high, -low]",
            base_flags | {PlacementFlag.DIRECT},
        )
    if is_low_vowel:
        near_open = (
            policy.split_low_by_tense
            and profile.has_height_sub_distinction
            and split_value == "-"
        )
        if near_open:
            return AxisEvidence(
                "Near-open",
                Confidence.MEDIUM,
                "height",
                f"Near-open: [-high, +low, -{split_source}]",
                base_flags | {PlacementFlag.DIRECT},
            )
        return AxisEvidence(
            "Open",
            Confidence.HIGH,
            "height",
            "Open: [-high, +low]",
            base_flags | {PlacementFlag.DIRECT},
        )
    if is_mid_vowel:
        if split_value == "+":
            return AxisEvidence(
                "Close-mid",
                Confidence.MEDIUM,
                "height",
                f"Close-mid: [-high, -low, +{split_source}]",
                base_flags | {PlacementFlag.DIRECT},
            )
        if split_value == "-":
            return AxisEvidence(
                "Open-mid",
                Confidence.MEDIUM,
                "height",
                f"Open-mid: [-high, -low, -{split_source}]",
                base_flags | {PlacementFlag.DIRECT},
            )
        # Tier 2 display policy: explicit [-high, -low] with no
        # tense/ATR specification places the vowel on the Mid row
        # midway between Close-mid and Open-mid. The engine still
        # treats tense/ATR as underspecified; only the display
        # inference uses the absence as positional evidence.
        return AxisEvidence(
            "Mid",
            Confidence.MEDIUM,
            "height",
            "Mid: [-high, -low], no tense/ATR",
            base_flags | {PlacementFlag.DIRECT},
        )
    return AxisEvidence(
        "Open-mid",
        Confidence.LOW,
        "default",
        "Open-mid (default): underspecified height",
        base_flags
        | {PlacementFlag.UNDERSPECIFIED, PlacementFlag.DEFAULT_ANCHOR},
    )


def _infer_backness(
    feats: Mapping[str, str],
    profile: VowelProfile,
    policy: PlacementPolicy,
) -> AxisEvidence:
    """Resolve the vowel's place (front/central/back).

    The paper-recommended tightening: ``[-back]`` only infers front
    when the inventory has no ``Front`` feature at all. When the
    inventory uses ``Front`` elsewhere but this segment leaves it
    absent, anchor central with ``UNDERSPECIFIED`` rather than
    pretending ``[-back]`` is sufficient evidence on its own.
    """
    fr_state = _feature_state(feats, "front")
    bk_state = _feature_state(feats, "back")
    fr = _nonzero(feats.get("front"))
    bk = _nonzero(feats.get("back"))
    if fr == "+" and bk != "+":
        return AxisEvidence(
            "front",
            Confidence.HIGH,
            "front",
            "Front: [+front]",
            frozenset({PlacementFlag.DIRECT}),
        )
    if bk == "+" and fr != "+":
        return AxisEvidence(
            "back",
            Confidence.HIGH,
            "back",
            "Back: [+back]",
            frozenset({PlacementFlag.DIRECT}),
        )
    if fr == "+" and bk == "+":
        return AxisEvidence(
            "central",
            Confidence.LOW,
            "conflict",
            "Central (conflict): [+front, +back]",
            frozenset({PlacementFlag.CONFLICT, PlacementFlag.DEFAULT_ANCHOR}),
        )
    # Explicit [-front] with [-back]: standard central spec.
    if fr == "-" and bk == "-":
        return AxisEvidence(
            "central",
            Confidence.HIGH,
            "front/back",
            "Central: [-front, -back]",
            frozenset({PlacementFlag.DIRECT}),
        )
    # Front-absent + [-back]: only fire the fallback when the
    # INVENTORY has no Front feature at all. When Front exists
    # elsewhere, treat this segment's missing Front as honest
    # underspecification and anchor central. This was the paper's
    # diagnosed bug: the old rule fired on segment-level absence,
    # which over-infers Front on sparse inventories.
    if fr_state == FeatureState.ABSENT and bk == "-":
        if not profile.has_front:
            return AxisEvidence(
                "front",
                Confidence.MEDIUM,
                "back-fallback",
                "Front inferred from [-back] in inventory lacking [front]",
                frozenset(
                    {PlacementFlag.FALLBACK, PlacementFlag.PROFILE_GATED}
                ),
            )
        return AxisEvidence(
            "central",
            Confidence.LOW,
            "default",
            "Central anchor: [-back] alone, but inventory has [front]",
            frozenset(
                {
                    PlacementFlag.UNDERSPECIFIED,
                    PlacementFlag.DEFAULT_ANCHOR,
                }
            ),
        )
    # Explicit [-front] alone: ambiguous between central and back;
    # conservative central anchor with the ambiguity surfaced.
    if fr == "-" and bk_state == FeatureState.ABSENT:
        return AxisEvidence(
            "central",
            Confidence.LOW,
            "default",
            "Central or back unresolved from [-front] alone",
            frozenset(
                {
                    PlacementFlag.UNDERSPECIFIED,
                    PlacementFlag.DEFAULT_ANCHOR,
                }
            ),
        )
    if (
        policy.allow_coronal_front_fallback
        and profile.has_coronal
        and not profile.has_front
    ):
        cor = _nonzero(feats.get("coronal"))
        ant = feats.get("anterior", "0")
        is_coronal = cor == "+"
        is_retroflex_or_rhotic = ant == "-"
        if is_coronal and not is_retroflex_or_rhotic:
            return AxisEvidence(
                "front",
                Confidence.LOW,
                "coronal-fallback",
                "Front (inferred): CORONAL fallback (inventory convention)",
                frozenset(
                    {
                        PlacementFlag.FALLBACK,
                        PlacementFlag.PROFILE_GATED,
                        PlacementFlag.NONSTANDARD,
                    }
                ),
            )
    return AxisEvidence(
        "central",
        Confidence.LOW,
        "default",
        "Central (default): no front/back specified",
        frozenset(
            {PlacementFlag.UNDERSPECIFIED, PlacementFlag.DEFAULT_ANCHOR}
        ),
    )


def _infer_rounding(
    feats: Mapping[str, str],
    profile: VowelProfile,
    policy: PlacementPolicy,
) -> AxisEvidence:
    """Resolve rounding. ``value`` is ``"rounded"`` or ``"unrounded"``
    so renderers can switch on it without re-reading the reason
    string; column math reads the same fact via ``value == "rounded"``.
    """
    rnd = _nonzero(feats.get("round"))
    if rnd == "+":
        return AxisEvidence(
            "rounded",
            Confidence.HIGH,
            "round",
            "Rounded: [+round]",
            frozenset({PlacementFlag.DIRECT}),
        )
    can_use_labial_fallback = (
        policy.allow_labial_round_fallback
        and profile.has_labial
        and not profile.has_round
    )
    has_labial = feats.get("labial", "0") == "+"
    if can_use_labial_fallback and has_labial:
        return AxisEvidence(
            "rounded",
            Confidence.MEDIUM,
            "labial-fallback",
            "Rounded (inferred): LABIAL fallback (inventory convention)",
            frozenset({PlacementFlag.FALLBACK, PlacementFlag.PROFILE_GATED}),
        )
    if rnd == "-":
        return AxisEvidence(
            "unrounded",
            Confidence.HIGH,
            "round",
            "Unrounded: [-round]",
            frozenset({PlacementFlag.DIRECT}),
        )
    # Tier 2 display policy: an inventory that has the Round
    # feature, with a vowel that leaves it unspecified, displays
    # the cell on the backness anchor centre rather than offset
    # toward the unrounded side (the schwa / ɐ pattern). Falls
    # back to "unrounded" when the inventory has no Round feature
    # at all so the historical default still applies there.
    if profile.has_round:
        return AxisEvidence(
            "neutral",
            Confidence.MEDIUM,
            "default",
            "Neutral round: no round specified",
            frozenset({PlacementFlag.DIRECT}),
        )
    return AxisEvidence(
        "unrounded",
        Confidence.LOW,
        "default",
        "Unrounded: no round specified",
        frozenset(
            {PlacementFlag.UNDERSPECIFIED, PlacementFlag.DEFAULT_ANCHOR}
        ),
    )


def compute_placements(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None = None,
) -> tuple[dict[tuple[int, int], list[str]], dict[str, VowelPlacement]]:
    """Place every vowel and group by (row, col) cell.

    ``policy`` defaults to :py:class:`PlacementPolicy` with the
    module-level defaults; pass one explicitly to enable the
    paper-recommended stricter settings (``coronal_front``
    disabled, low-vowel split off, etc.).

    Returns ``(occupied, placements)``. Cells are sorted by
    descending placement confidence (highest first); ties break on
    ascending segment string for stable ordering.
    """
    policy = policy or PlacementPolicy()
    occupied: dict[tuple[int, int], list[str]] = {}
    placements: dict[str, VowelPlacement] = {}
    for seg in segs:
        placement = vowel_grid_pos(norm_feats.get(seg, {}), profile, policy)
        placements[seg] = placement
        occupied.setdefault((placement.row, placement.col), []).append(seg)
    # Confidence DESCENDING (via negated int), segment ASCENDING
    # within the same confidence tier. A single ``reverse=True``
    # would also flip the segment direction.
    for key in occupied:
        occupied[key].sort(key=lambda s: (-int(placements[s].confidence), s))
    return occupied, placements


# ---------------------------------------------------------------------------
# Render-ready chart geometry.
#
# The dataclasses and ``build_vowel_chart_geometry`` below are the
# single source of truth that both the desktop Qt widget and the web
# Pyodide bridge consume. After the geometry is built, each renderer
# is a thin walk of the structure: emit a label per row, a button per
# cell entry. No frontend duplicates placement decisions or
# physical-coordinate arithmetic.
# ---------------------------------------------------------------------------

# Grid-coordinate constants. Both UIs lay out the chart as:
#   row 0 = "VOWELS" title spanning every data column
#   row 1 = Front / Central / Back column headers
#   row 2..  = data rows (only populated ones, in display order)
# and:
#   col 0 = row labels (Close, Near-close, ...)
#   cols 1..8 = the six logical columns interleaved with two
#               spacer tracks at physical cols 3 and 6.
# The numbers are 0-based (Qt convention); CSS-side renderers add 1
# when assigning ``grid-row`` / ``grid-column`` (1-indexed).
VOWEL_TITLE_GRID_ROW: int = 0
VOWEL_COL_HEADER_GRID_ROW: int = 1
VOWEL_FIRST_DATA_GRID_ROW: int = 2
VOWEL_LABEL_GRID_COL: int = 0
# First grid column after the row-label gutter; each backness pair
# (unr/rnd) occupies two consecutive tracks; a one-track spacer
# separates each pair from the next.
VOWEL_FIRST_DATA_GRID_COL: int = VOWEL_LABEL_GRID_COL + 1
#: Title shown above the chart on both UIs. Centralised so a
#: future rename (e.g. localisation) touches one constant.
VOWEL_CHART_TITLE: str = "VOWELS"
#: How many physical grid tracks the title spans (covers every
#: data column plus the two spacer tracks).
VOWEL_TITLE_GRID_COL_SPAN: int = 8
#: Each backness header straddles its pair (unrounded + rounded).
VOWEL_COL_HEADER_GRID_COL_SPAN: int = 2


def logical_col_offset(col: int) -> int:
    """Offset of a logical column 0..5 from the row-label column.

    Logical 0..5 maps to physical offsets 1, 2, 4, 5, 7, 8 from the
    row-label column (the spacer tracks at offsets 3 and 6 are
    skipped). Add ``VOWEL_LABEL_GRID_COL + col_offset`` to land on
    the physical Qt grid column; CSS renderers further add 1 to
    translate to 1-indexed ``grid-column`` lines.
    """
    return col + (col >> 1) + 1


@dataclass(frozen=True)
class VowelChartCell:
    """A populated chart cell with its position resolved.

    The cell carries two ORTHOGONAL pieces of information so the
    renderer can keep "where in the trapezoid does this cell
    belong" (a position concern) cleanly separate from "how far
    apart should paired mates sit visually" (a display concern):

    * ``chart_x`` / ``chart_y``: normalised ``[0, 1]`` floats for
      the cell's BACKNESS ANCHOR projected through the chart's
      :py:class:`VowelChartShape`. Both unrounded and rounded
      mates at the same backness share the same anchor, so the
      paired-mate spacing does NOT change with chart width or
      with how narrow a low row becomes inside the trapezoid.
      Renderers drop the cell at
      ``left: calc(chart_x * 100%)`` / ``top: calc(chart_y * 100%)``
      (web) or the equivalent ``move()`` (Qt).
    * ``pair_side``: ``-1`` for the unrounded mate, ``+1`` for the
      rounded mate, ``0`` for an unrounded/rounded-unknown cell.
      The renderer applies a FIXED PIXEL shift of
      ``pair_side * (BTN_W + VOWEL_PAIR_GAP_PX) / 2`` on top of
      the anchor so paired mates are always exactly tangent
      regardless of the row's effective width.

    ``grid_row`` / ``grid_col`` remain for callers that still use
    the legacy rectangular grid layout. ``row`` / ``col`` are the
    abstract logical placement (0..5 each). ``entries`` is the
    segments occupying this cell, ordered by descending placement
    confidence (ties broken by ascending segment string).

    ``is_long_pair`` is True when the cell carries exactly two
    segments whose feature bundles differ only on ``Long`` (one
    ``Long+``, one ``Long-``). Renderers use this hint to lay the
    two buttons SIDE-BY-SIDE inside the cell instead of stacking
    them vertically: length is a display-layer attribute on the
    same vowel-space position, not two separate positions, and
    side-by-side reads more honestly than a vertical pair would.
    Other collision groups (three or more segments, or two
    segments that differ on something besides Long) keep the
    default vertical-stack layout.
    """

    row: int
    col: int
    grid_row: int
    grid_col: int
    chart_x: float
    chart_y: float
    pair_side: int
    entries: tuple[str, ...]
    is_long_pair: bool = False


@dataclass(frozen=True)
class VowelChartRow:
    """A row to render. ``logical_row`` indexes into ``ROW_LABELS``;
    ``grid_row`` is the Qt 0-based physical row the renderer drops
    the row label into for the legacy grid layout. ``chart_y`` is
    the row's normalised vertical position inside the trapezoid
    data area so a row-label renderer can vertically align the
    label with the row's data cells via
    ``top: calc(chart_y * 100%)``."""

    logical_row: int
    label: str
    grid_row: int
    chart_y: float


@dataclass(frozen=True)
class VowelChartColHeader:
    """A backness column header (Front / Central / Back) with its
    placement already resolved.

    Carries two coordinate systems for parity with
    :py:class:`VowelChartCell`:

    * ``grid_col`` / ``grid_col_span``: physical grid coordinates
      for the legacy rectangular grid layout. Web adds 1 for
      CSS's 1-indexed grid.
    * ``chart_x``: the column's backness ANCHOR as a normalised
      ``[0, 1]`` fraction of the data-area width. The renderer
      should sit each header at ``chart_x * 100%`` so the header
      lines up over the centre of the cells in its column at the
      widest (top) row of the trapezoid.
    """

    label: str
    grid_col: int
    grid_col_span: int
    chart_x: float


@dataclass(frozen=True)
class VowelChartSilhouette:
    """The outline of the chart's data area, adapted to the
    inventory's populated rows.

    Position vs display split: ``top_y`` / ``bottom_y`` are the
    DISPLAY positions of the silhouette's top and bottom edges in
    the data area's normalised ``[0, 1]`` coordinate space (the
    silhouette always spans the full data area vertically so cells
    fill the available room). ``top_left`` / ``top_right`` /
    ``bottom_left`` / ``bottom_right`` are the four corners'
    horizontal positions, derived from the POSITIONAL identity of
    the topmost and bottommost populated logical rows (an
    inventory whose lowest row is Close-mid carries a much wider
    bottom edge than one whose lowest row is Open).

    Renderers draw the outline straight between these corners and
    project each cell's ``chart_x`` by linearly interpolating
    between ``top_width`` and ``bottom_width`` at the cell's
    ``chart_y`` so cells sit on the silhouette slant by
    construction.

    ``top_width`` / ``bottom_width`` are the row widths (full
    content-area fraction) at the two edges, exposed as
    independent data so the renderer can interpolate without
    re-deriving from the corners.
    """

    shape: VowelChartShape
    top_y: float
    bottom_y: float
    top_left: float
    top_right: float
    bottom_left: float
    bottom_right: float
    top_width: float
    bottom_width: float


@dataclass(frozen=True)
class VowelChartGeometry:
    """Complete render-ready description of a vowel chart.

    Both Qt and the web bridge consume this verbatim: emit one row
    label per :py:attr:`rows` entry, one cell per :py:attr:`cells`
    entry, and one button per segment in each cell.

    :py:attr:`shape` is the visual envelope the renderer paints
    around the chart (trapezoid by default, triangle for
    inventories without a backness contrast). The placement
    coordinates inside the chart do not change with shape; only
    the chart's outer outline does.

    :py:attr:`silhouette` carries the inventory-adapted silhouette
    corners so the renderer can paint the outline and confirm
    every cell sits on its slant.

    :py:attr:`natural_data_width_px` and
    :py:attr:`natural_data_height_px` are the data-area's preferred
    pixel dimensions, derived from the inventory's content: the
    width grows with the widest row's button + gap requirements,
    and the height grows with row count + per-row vertical-stack
    depth. Renderers should treat these as the chart container's
    PREFERRED natural size and add chrome (title, row labels,
    column headers, padding) on top.

    Empty rows (no vowels in any column at that height tier) are
    OMITTED from :py:attr:`rows`; renderers iterate the list as-is
    without a "is this row populated" check.
    """

    title: str
    title_grid_col_span: int
    shape: VowelChartShape
    silhouette: VowelChartSilhouette
    cols: tuple[VowelChartColHeader, ...]
    rows: tuple[VowelChartRow, ...]
    cells: tuple[VowelChartCell, ...]
    natural_data_width_px: int
    natural_data_height_px: int


#: Gap between vertically stacked segment buttons inside a single
#: cell. Smaller than the inter-row gap because the stack reads as
#: one cell, not several.
_VOWEL_CELL_STACK_GAP_PX: int = 1

#: Vertical breathing room between adjacent populated rows. Picked
#: to read as a row break without overweighting the chart's chrome.
_VOWEL_ROW_GAP_PX: int = 6

#: Vertical padding (top + bottom combined) around the row content
#: so the silhouette's top edge can cut through the Close row's
#: button centres without clipping their tops.
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX: int = SEG_BTN_H

#: Reference content width (px) used to convert cell pixel sizes
#: into the normalised ``[0, 1]`` coordinate space the silhouette
#: lives in. Matches the canonical anchor derivation in
#: :py:func:`_derive_backness_anchors` so cell-extent math stays
#: consistent with chart_x.
_VOWEL_CONTENT_W_PX: float = float(
    3 * (2 * BTN_W + VOWEL_PAIR_GAP_PX) + 2 * VOWEL_PAIR_SEPARATOR_PX
)

#: How aggressively the silhouette's top_width and bottom_width
#: shrink toward each row's minimum-required width. ``0.0`` keeps
#: the canonical widths; ``1.0`` would consume all per-row slack.
#: The shrink is uniform across top and bottom so the trapezoid
#: keeps its canonical proportions while pulling inward toward the
#: content. Both the silhouette outline and the back-anchored cell
#: projection use these widths, so cells follow the silhouette by
#: construction with no drift.
_VOWEL_SHRINK_FACTOR: float = 0.3

#: Minimum visual separation between adjacent cells in the same
#: row (expressed as a fraction of the canonical content width).
#: Matches the inter-pair separator on the canonical 3-slot
#: layout, so two pinched-together slots end up with the same
#: comfortable gap as canonical adjacent pairs.
_VOWEL_MIN_CELL_GAP_NORM: float = VOWEL_PAIR_SEPARATOR_PX / _VOWEL_CONTENT_W_PX


def _row_content_extent(
    cells: tuple[VowelChartCell, ...],
    row: int,
) -> tuple[float, float] | None:
    """Leftmost and rightmost normalised x extent of the cells at
    ``row``. Returns ``None`` when the row has no cells.

    Cell widths are taken as the rendered button or Long-pair-
    container size, converted to normalised coords via the
    canonical content-width reference.
    """
    row_cells = [c for c in cells if c.row == row]
    if not row_cells:
        return None
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    single_half = (BTN_W / 2.0) / _VOWEL_CONTENT_W_PX
    long_pair_half = (
        (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    )
    lefts: list[float] = []
    rights: list[float] = []
    for cell in row_cells:
        half = long_pair_half if cell.is_long_pair else single_half
        center = cell.chart_x + cell.pair_side * pair_shift
        lefts.append(center - half)
        rights.append(center + half)
    return min(lefts), max(rights)


def _min_row_width_for_meta(
    row_cells: list[tuple[int, int, bool]],
) -> float:
    """Lower bound on ``row_width`` such that the row's cells do
    not overlap given back-anchored projection.

    Each tuple is ``(col, pair_side, is_long_pair)``; the cell's
    horizontal extent is its half-width plus its pair-side offset
    from the row's projected anchor. With back-anchored projection
    ``chart_x = back + W * (anchor - back)``, the distance between
    two cells at adjacent anchors scales linearly with ``W``; this
    function solves for the minimum ``W`` such that every adjacent
    pair has at least ``_VOWEL_MIN_CELL_GAP_NORM`` between them
    (zero if a single cell occupies the row).
    """
    if len(row_cells) < 2:
        return 0.0
    canonical_anchor: dict[int, float] = {
        0: _BACKNESS_X["front"],
        1: _BACKNESS_X["front"],
        6: _BACKNESS_X["front"],
        2: _BACKNESS_X["central"],
        3: _BACKNESS_X["central"],
        7: _BACKNESS_X["central"],
        4: _BACKNESS_X["back"],
        5: _BACKNESS_X["back"],
        8: _BACKNESS_X["back"],
    }
    pair_shift = (BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    single_half = (BTN_W / 2.0) / _VOWEL_CONTENT_W_PX
    long_pair_half = (
        (2 * BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 / _VOWEL_CONTENT_W_PX
    )
    sorted_meta = sorted(row_cells, key=lambda c: canonical_anchor[c[0]])
    min_w = 0.0
    for (col_a, ps_a, lp_a), (col_b, ps_b, lp_b) in zip(
        sorted_meta, sorted_meta[1:]
    ):
        anchor_a = canonical_anchor[col_a]
        anchor_b = canonical_anchor[col_b]
        if anchor_b <= anchor_a:
            # Same backness slot -- pair_side handles separation.
            continue
        half_a = long_pair_half if lp_a else single_half
        half_b = long_pair_half if lp_b else single_half
        # Center distance at row_width=W = W*(anchor_b - anchor_a)
        # + (ps_b - ps_a) * pair_shift. For non-overlap with a
        # min visible gap, this must be >= half_a + half_b + gap.
        required = (
            _VOWEL_MIN_CELL_GAP_NORM
            + half_a
            + half_b
            - (ps_b - ps_a) * pair_shift
        )
        w_req = required / (anchor_b - anchor_a)
        if w_req > min_w:
            min_w = w_req
    return max(0.0, min(1.0, min_w))


def _compute_shrunken_widths(
    cells_meta_by_row: dict[int, list[tuple[int, int, bool]]],
    display_y_by_row: dict[int, float],
    top_y: float,
    bottom_y: float,
    canonical_top_width: float,
    canonical_bottom_width: float,
) -> tuple[float, float]:
    """Compute shrunken silhouette ``(top_width, bottom_width)``
    that satisfy every populated row's minimum required width.

    Concurrent shrink: both widths shrink by the same amount,
    set by the most-constrained row's slack between its canonical
    row_width and its minimum-required row_width. The trapezoid
    keeps its canonical proportions while pulling inward as a
    whole; the close/front angle stays constant.
    """
    if _VOWEL_SHRINK_FACTOR <= 0.0:
        return canonical_top_width, canonical_bottom_width
    span = bottom_y - top_y
    if span <= 0:
        return canonical_top_width, canonical_bottom_width
    min_slack = float("inf")
    for r, meta in cells_meta_by_row.items():
        if r not in display_y_by_row:
            continue
        t = (display_y_by_row[r] - top_y) / span
        canonical_row_w = (
            canonical_top_width * (1.0 - t) + canonical_bottom_width * t
        )
        min_w = _min_row_width_for_meta(meta)
        slack = canonical_row_w - min_w
        if slack < min_slack:
            min_slack = slack
    if min_slack <= 0 or min_slack == float("inf"):
        return canonical_top_width, canonical_bottom_width
    consume = _VOWEL_SHRINK_FACTOR * min_slack
    return (
        max(0.0, canonical_top_width - consume),
        max(0.0, canonical_bottom_width - consume),
    )


def _silhouette_with_widths(
    silhouette: VowelChartSilhouette,
    top_width: float,
    bottom_width: float,
) -> VowelChartSilhouette:
    """Recompute silhouette corners for new ``top_width`` /
    ``bottom_width`` while keeping shape and y bounds. Back edge
    stays vertical at ``back + pair_outer``.
    """
    front = _BACKNESS_X["front"]
    back = _BACKNESS_X["back"]
    pair_outer = _PAIR_OUTER_EXTENT
    front_at_top = back + top_width * (front - back)
    front_at_bottom = back + bottom_width * (front - back)
    return replace(
        silhouette,
        top_left=front_at_top - pair_outer,
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_width,
        bottom_width=bottom_width,
    )


def _natural_data_area_size(
    cells: tuple[VowelChartCell, ...],
) -> tuple[int, int]:
    """Derive the chart data area's preferred pixel size from the
    inventory's content.

    The chart grows along both axes so the rendered cells have room
    to breathe:

    * Width is set by the widest populated row's button + gap
      requirements. Each backness slot (front / central / back)
      contributes ``N * BTN_W + (N - 1) * VOWEL_PAIR_GAP_PX`` where
      ``N`` is the slot's button count (a side-by-side Long pair
      contributes 2 buttons, a regular single contributes 1). Slot
      widths are separated by ``VOWEL_PAIR_SEPARATOR_PX``.
    * Height is set by the populated rows' content height: each
      row contributes ``max_stack * SEG_BTN_H + (max_stack - 1) *
      stack_gap`` where ``max_stack`` is the row's deepest vertical
      collision-stack. Long-pair cells count as 1 (they grow
      horizontally, not vertically). Rows are separated by
      ``_VOWEL_ROW_GAP_PX`` and the silhouette adds vertical
      padding above the top row and below the bottom row.
    """
    if not cells:
        # Fall back to a single canonical pair slot.
        return (
            2 * BTN_W + VOWEL_PAIR_GAP_PX,
            SEG_BTN_H + _VOWEL_DATA_AREA_VERTICAL_PADDING_PX,
        )

    # col -> backness slot (front=0, central=1, back=2).
    col_to_slot: dict[int, int] = {
        0: 0,
        1: 0,
        6: 0,
        2: 1,
        3: 1,
        7: 1,
        4: 2,
        5: 2,
        8: 2,
    }

    rows_in_use: set[int] = {c.row for c in cells}
    max_row_w = 2 * BTN_W + VOWEL_PAIR_GAP_PX
    for ri in rows_in_use:
        # Buttons per backness slot at this row.
        slot_buttons: dict[int, int] = {0: 0, 1: 0, 2: 0}
        for c in cells:
            if c.row != ri:
                continue
            slot = col_to_slot[c.col]
            slot_buttons[slot] += 2 if c.is_long_pair else 1
        populated_slots = [s for s, n in slot_buttons.items() if n > 0]
        if not populated_slots:
            continue
        slot_widths = [
            slot_buttons[s] * BTN_W
            + max(0, slot_buttons[s] - 1) * VOWEL_PAIR_GAP_PX
            for s in populated_slots
        ]
        row_w = sum(slot_widths) + (len(populated_slots) - 1) * (
            VOWEL_PAIR_SEPARATOR_PX
        )
        max_row_w = max(max_row_w, row_w)

    # Height: per-row max stack depth, plus inter-row gaps and
    # vertical padding for the silhouette's top/bottom offset.
    row_heights: list[int] = []
    for ri in sorted(rows_in_use):
        depth = 1
        for c in cells:
            if c.row != ri:
                continue
            cell_depth = 1 if c.is_long_pair else len(c.entries)
            if cell_depth > depth:
                depth = cell_depth
        row_heights.append(
            depth * SEG_BTN_H + max(0, depth - 1) * _VOWEL_CELL_STACK_GAP_PX
        )

    total_h = sum(row_heights) + (len(row_heights) - 1) * _VOWEL_ROW_GAP_PX
    total_h += _VOWEL_DATA_AREA_VERTICAL_PADDING_PX
    return max_row_w, total_h


def build_vowel_chart_geometry(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None = None,
) -> VowelChartGeometry:
    """End-to-end: compute placements and produce a render-ready
    chart geometry for both UIs.

    Steps:
      1. Delegate to :py:func:`compute_placements` for the per-vowel
         cell + collision-grouping decision.
      2. For each populated cell, build a :py:class:`VowelChartCell`
         carrying its occupants.
      3. For each populated height tier, build a
         :py:class:`VowelChartRow` with the assigned physical grid
         row.

    Renderers attach the result directly: no placement decisions
    and no coordinate arithmetic happen at the UI layer.
    """
    occupied, _ = compute_placements(segs, profile, norm_feats, policy)

    populated_logical_rows = sorted({row for (row, _) in occupied})
    logical_row_to_grid_row = {
        ri: VOWEL_FIRST_DATA_GRID_ROW + display_index
        for display_index, ri in enumerate(populated_logical_rows)
    }

    shape = infer_vowel_shape(profile)
    # Silhouette: position logic (top/bottom widths) comes from the
    # populated logical row range; display logic (top_y/bottom_y)
    # always spans the full data area so cells use every pixel
    # regardless of which rows are present.
    silhouette = vowel_silhouette(
        shape,
        top_logical_row=populated_logical_rows[0],
        bottom_logical_row=populated_logical_rows[-1],
    )

    # Display y per populated row: evenly distributed in the
    # silhouette's vertical span. This is the DISPLAY logic. A
    # single-row inventory parks the row at the vertical midpoint
    # so the silhouette is not a degenerate horizontal line.
    if len(populated_logical_rows) == 1:
        display_y_by_row = {
            populated_logical_rows[0]: (silhouette.top_y + silhouette.bottom_y)
            / 2
        }
    else:
        span = silhouette.bottom_y - silhouette.top_y
        denom = len(populated_logical_rows) - 1
        display_y_by_row = {
            ri: silhouette.top_y + span * (i / denom)
            for i, ri in enumerate(populated_logical_rows)
        }

    rows = tuple(
        VowelChartRow(
            logical_row=ri,
            label=ROW_LABELS[ri],
            grid_row=logical_row_to_grid_row[ri],
            chart_y=display_y_by_row[ri],
        )
        for ri in populated_logical_rows
    )

    def _width_at_display_y(y: float) -> float:
        """Linear interp between silhouette top and bottom widths
        at the given display y. Unifies position (silhouette) and
        display (cell y) at the cell projection step so cells lie
        on the silhouette slant by construction.
        """
        if silhouette.bottom_y == silhouette.top_y:
            return silhouette.top_width
        t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
        return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t

    back = _BACKNESS_X["back"]

    # Map ``col`` to its backness anchor. Pair side (unrounded vs
    # rounded) is handled separately by the renderer as a fixed
    # pixel shift so the within-pair gap stays constant regardless
    # of how narrow a row becomes inside the trapezoid. Cols 6..8
    # are the neutral-round slots that sit on the anchor centre
    # with no L/R shift.
    _col_to_anchor: dict[int, float] = {
        0: _BACKNESS_X["front"],
        1: _BACKNESS_X["front"],
        2: _BACKNESS_X["central"],
        3: _BACKNESS_X["central"],
        4: _BACKNESS_X["back"],
        5: _BACKNESS_X["back"],
        6: _BACKNESS_X["front"],
        7: _BACKNESS_X["central"],
        8: _BACKNESS_X["back"],
    }
    # Legacy rectangular grid_col mapping for the neutral slots:
    # snap onto the unrounded physical track of the matching
    # backness so existing grid-col consumers stay on a non-spacer
    # column (1, 4, or 7).
    _neutral_col_to_grid_col: dict[int, int] = {
        6: VOWEL_LABEL_GRID_COL + logical_col_offset(0),
        7: VOWEL_LABEL_GRID_COL + logical_col_offset(2),
        8: VOWEL_LABEL_GRID_COL + logical_col_offset(4),
    }

    def _is_long_pair_display(entries: list[str]) -> bool:
        """True iff the cell carries exactly two segments whose
        normalised feature bundles differ only on ``Long`` (one
        ``Long+``, one ``Long-``). Renderers use this to lay the
        pair out side-by-side instead of stacking them.
        """
        if len(entries) != 2:
            return False
        a, b = (
            _normalize_feat_keys(norm_feats.get(entries[0], {})),
            _normalize_feat_keys(norm_feats.get(entries[1], {})),
        )
        long_a, long_b = a.get("long"), b.get("long")
        if {long_a, long_b} != {"+", "-"}:
            return False
        # Compare all keys except ``long`` for equality. Skip keys
        # whose values are both ``None`` so a one-sided ``"0"``
        # doesn't count as a difference.
        for key in set(a) | set(b):
            if key == "long":
                continue
            if a.get(key) != b.get(key):
                return False
        return True

    open_row_index = _ROW_LABEL_TO_INDEX["Open"]
    # Open-row front-pair cells (cols 0 / 1) take priority for the
    # bottom-left of the trapezoid. When they are empty, the Open
    # central pair migrates leftward to occupy that visual slot
    # (a one-low-vowel inventory's central /a/ should not sit at
    # the geometric midpoint of the narrowed bottom edge). When
    # the front pair IS populated, central stays at its true
    # central anchor so the two cells do not collide.
    open_front_populated = (open_row_index, 0) in occupied or (
        open_row_index,
        1,
    ) in occupied

    # First pass: resolve each cell's metadata (col, pair_side,
    # is_long_pair). The display layer needs these to size the
    # silhouette before it can fix cell ``chart_x`` positions.
    # No phonology re-decisions happen below this point -- the
    # cell COL/row are already final; only their pixel-space
    # position is still pending.
    cell_meta: list[tuple[int, int, tuple[str, ...], bool, int, int]] = []
    cells_meta_by_row: dict[int, list[tuple[int, int, bool]]] = {}
    for ri, ci in sorted(occupied):
        entries = tuple(occupied[(ri, ci)])
        is_long_pair = _is_long_pair_display(list(entries))
        if ci >= 6:
            pair_side = 0
            grid_col = _neutral_col_to_grid_col[ci]
        else:
            sibling_ci = ci ^ 1
            has_sibling = (ri, sibling_ci) in occupied
            if is_long_pair and not has_sibling:
                pair_side = 0
            else:
                pair_side = 1 if ci % 2 else -1
            grid_col = VOWEL_LABEL_GRID_COL + logical_col_offset(ci)
        cell_meta.append((ri, ci, entries, is_long_pair, pair_side, grid_col))
        cells_meta_by_row.setdefault(ri, []).append(
            (ci, pair_side, is_long_pair)
        )

    # Shrink silhouette widths so the trapezoid tracks the actual
    # content. With back-anchored cell projection, the shrunken
    # widths also pull cell anchors inward by the same factor, so
    # the silhouette and the cells stay aligned by construction.
    shrunken_top_w, shrunken_bot_w = _compute_shrunken_widths(
        cells_meta_by_row,
        display_y_by_row,
        silhouette.top_y,
        silhouette.bottom_y,
        silhouette.top_width,
        silhouette.bottom_width,
    )
    if (
        shrunken_top_w != silhouette.top_width
        or shrunken_bot_w != silhouette.bottom_width
    ):
        silhouette = _silhouette_with_widths(
            silhouette, shrunken_top_w, shrunken_bot_w
        )

    # Second pass: project cells using the final silhouette
    # widths. Long pairs without an opposite-rounding sibling
    # render centred on their anchor (pair_side=0); regular pairs
    # and lone Long pairs with a sibling keep canonical pair_side.
    cells: list[VowelChartCell] = []
    for ri, ci, entries, is_long_pair, pair_side, grid_col in cell_meta:
        if ri == open_row_index and ci in (2, 3) and not open_front_populated:
            anchor_x = _BACKNESS_X["front"]
        else:
            anchor_x = _col_to_anchor[ci]
        cell_display_y = display_y_by_row[ri]
        row_width = _width_at_display_y(cell_display_y)
        chart_x = back + row_width * (anchor_x - back)
        cells.append(
            VowelChartCell(
                row=ri,
                col=ci,
                grid_row=logical_row_to_grid_row[ri],
                grid_col=grid_col,
                chart_x=chart_x,
                chart_y=cell_display_y,
                pair_side=pair_side,
                entries=entries,
                is_long_pair=is_long_pair,
            )
        )

    # Column headers sit at the silhouette's top edge so they line
    # up with the topmost populated row's cells. Their chart_x is
    # the topmost row's projected backness anchor (front migrates
    # inward as the silhouette narrows; central shifts toward the
    # back anchor too; back stays flush with the vertical right
    # edge).
    _col_label_to_anchor_key = ("front", "central", "back")
    top_row_width = silhouette.top_width
    col_headers = tuple(
        VowelChartColHeader(
            label=label,
            grid_col=(VOWEL_FIRST_DATA_GRID_COL + ci * 3),
            grid_col_span=VOWEL_COL_HEADER_GRID_COL_SPAN,
            chart_x=back
            + top_row_width
            * (_BACKNESS_X[_col_label_to_anchor_key[ci]] - back),
        )
        for ci, label in enumerate(COL_LABELS)
    )

    natural_w, natural_h = _natural_data_area_size(tuple(cells))
    return VowelChartGeometry(
        title=VOWEL_CHART_TITLE,
        title_grid_col_span=VOWEL_TITLE_GRID_COL_SPAN,
        shape=shape,
        silhouette=silhouette,
        cols=col_headers,
        rows=rows,
        cells=tuple(cells),
        natural_data_width_px=natural_w,
        natural_data_height_px=natural_h,
    )


def vowel_grid_pos(
    feats: Mapping[str, str],
    profile: VowelProfile,
    policy: PlacementPolicy | None = None,
) -> VowelPlacement:
    """Return a :py:class:`VowelPlacement` for a single vowel.

    Columns 0-5 map to (front-unr, front-rnd, central-unr,
    central-rnd, back-unr, back-rnd). Rows 0-5 map to
    :py:data:`ROW_LABELS`. ``feats`` keys are case-normalized
    internally so the caller may pass raw inventory feats
    (PascalCase) or pre-normalized lowercase feats; both produce
    identical results.

    Length (the ``Long`` feature) is deliberately NOT consulted:
    it is a display-layer concern, not a vowel-space position.
    Two segments that differ only in ``Long`` resolve to the same
    row and column here, and the renderer is responsible for
    presenting the length contrast visually.

    Top-level ``confidence`` and ``reason`` are derived summaries
    over the per-axis evidence. ``flags`` is the union of every
    axis's flag set so a renderer can short-circuit on the presence
    of (for example) ``CONFLICT`` without inspecting each axis.
    """
    policy = policy or PlacementPolicy()
    normalized = _normalize_feat_keys(feats)
    height = _infer_height(normalized, profile, policy)
    backness = _infer_backness(normalized, profile, policy)
    rounding = _infer_rounding(normalized, profile, policy)

    row = _ROW_LABEL_TO_INDEX[height.value]
    place_to_column = {"front": 0, "central": 2, "back": 4}
    base_col = place_to_column[backness.value]
    # Cols 0..5 = (front-unr, front-rnd, central-unr, central-rnd,
    # back-unr, back-rnd). Cols 6..8 are the neutral-round slots
    # (front, central, back) the renderer drops at the backness
    # anchor centre with no L/R pair shift.
    if rounding.value == "neutral":
        col = 6 + (base_col // 2)
    elif rounding.value == "rounded":
        col = base_col + 1
    else:
        col = base_col

    # Normalized abstract-vowel-space coordinates. Same decision as
    # ``row`` / ``col`` but expressed as floats so a future trapezoid
    # or triangle projector can read them without having to recover
    # axis semantics from a grid index. ``pair_offset`` is signed:
    # rounded sits to the right of its unrounded mate.
    y = _HEIGHT_Y[height.value]
    x = _BACKNESS_X[backness.value]
    if rounding.value == "rounded":
        pair_offset = _PAIR_OFFSET_HALF
    elif rounding.value == "unrounded":
        pair_offset = -_PAIR_OFFSET_HALF
    else:
        pair_offset = 0.0

    # IntEnum orders by int; min picks the weakest of the three
    # axes. Including rounding here is more honest than the prior
    # height-and-backness-only summary: a vowel with unspecified
    # rounding shouldn't read as HIGH confidence overall.
    confidence = min(
        height.confidence, backness.confidence, rounding.confidence
    )
    reason = f"{height.reason}; {backness.reason}; {rounding.reason}"
    flags = height.flags | backness.flags | rounding.flags
    return VowelPlacement(
        row=row,
        col=col,
        x=x,
        y=y,
        pair_offset=pair_offset,
        confidence=confidence,
        reason=reason,
        height=height,
        backness=backness,
        rounding=rounding,
        flags=flags,
    )
