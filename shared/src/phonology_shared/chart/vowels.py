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
from phonology_shared.presentation.feature_metadata import (
    USE_VOWEL_PAIR,
    features_for_use,
)
from phonology_shared.presentation.layout import (
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


class VowelCellDisplayKind(StrEnum):
    """How a renderer should arrange the buttons inside a chart cell.

    The vowel chart's row + column place the cell on the (height,
    backness) grid; this enum chooses the layout INSIDE the cell
    once two or more vowels share the same slot.

    * ``STACK`` -- default: vertical stack, one button per row. Used
      when the entries differ on a non-display feature (or on no
      feature at all) so vertical stacking is the safe arrangement.
    * ``LONG_PAIR`` / ``NASAL_PAIR`` / ``RHOTIC_PAIR`` /
      ``PHONATION_PAIR`` / ``TONE_PAIR`` -- side-by-side: two
      buttons in a horizontal row, marked member on the right. The
      five PAIR kinds share the same physical layout; the kind
      records WHICH non-position feature drove the contrast so the
      renderer (or downstream tooling) can read it without
      re-deriving from the entries.
    * ``CONTRAST_SET`` -- 2x2 grid (for 3-4 entries) when the
      entries differ on more than one display feature (e.g. long x
      nasal). Renderer decides the 2D arrangement; ``entries`` is
      passed through in input order.

    StrEnum so the value serializes verbatim through the
    presentation bridge into the web payload.
    """

    STACK = "stack"
    LONG_PAIR = "long_pair"
    NASAL_PAIR = "nasal_pair"
    RHOTIC_PAIR = "rhotic_pair"
    PHONATION_PAIR = "phonation_pair"
    TONE_PAIR = "tone_pair"
    CONTRAST_SET = "contrast_set"


#: Feature names (canonical, post-:py:func:`normalize_feature_key`)
#: that the cell-display classifier treats as "in-cell contrasts":
#: two vowels differing only on one of these can share a slot and
#: be displayed side by side rather than stacked. Everything outside
#: this set is a position feature; cells whose entries differ on a
#: position feature fall through to ``STACK``.
#:
#: Derived from
#: :py:data:`phonology_shared.presentation.feature_metadata.FEATURE_REGISTRY`
#: entries tagged with ``USE_VOWEL_PAIR`` so the contrast roster
#: lives next to every other feature-name decision instead of being
#: duplicated here. The current set: ``{long, nasal, rhotic,
#: breathy, creaky, tone}``.
_DISPLAY_CONTRAST_FEATURES: frozenset[str] = features_for_use(USE_VOWEL_PAIR)


#: PAIR display kinds keyed by the single contrast feature that
#: produced them. Used in classification and in pair-ordering so
#: the "marked" (``+``-valued) entry consistently lands on the
#: right side of the rendered pair.
_PAIR_KIND_FOR_FEATURE: dict[str, VowelCellDisplayKind] = {
    "long": VowelCellDisplayKind.LONG_PAIR,
    "nasal": VowelCellDisplayKind.NASAL_PAIR,
    "rhotic": VowelCellDisplayKind.RHOTIC_PAIR,
    "tone": VowelCellDisplayKind.TONE_PAIR,
}


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

    ``REFINED`` marks a row or column that was nudged by a relative
    feature (``raised``/``lowered``/``advanced``/``retracted``/
    ``centralized``/``peripheral``) after the base inference. The
    base inference's flags propagate alongside it so the original
    evidence is still legible.

    ``SPLIT_SOURCE_DIVERGENCE`` fires when two of the height-split
    sources (``tense``, ``atr``, ``rtr``) are both present and point
    in opposite directions. Replaces the older ``ATR_TENSE``-only
    flag now that RTR is a third source.
    """

    DIRECT = "direct"
    FALLBACK = "fallback"
    PROFILE_GATED = "profile_gated"
    UNDERSPECIFIED = "underspecified"
    CONFLICT = "conflict"
    DEFAULT_ANCHOR = "default_anchor"
    NONSTANDARD = "nonstandard"
    REFINED = "refined"
    SPLIT_SOURCE_DIVERGENCE = "split_source_divergence"
    # The placement is one half of a diphthong; the partner cell is
    # on the same VowelPlacement under ``secondary``. Both the
    # primary placement and the inner secondary placement carry
    # this flag so renderers can detect the diphthong from either
    # endpoint.
    DIPHTHONG = "diphthong"


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
    #: Tongue-root retraction. Third height-split source after
    #: ``tense`` and ``atr``; inverted on the way into
    #: :py:func:`_height_split_value` because ``[+rtr]`` corresponds
    #: to ``[-atr]`` / ``[-tense]`` in feature systems that contrast
    #: the two roots.
    has_rtr: bool = False
    #: True iff the inventory has at least one ``+tense`` AND at
    #: least one ``-tense`` vowel. Same shape as
    #: :py:attr:`has_long_contrast`. The divergence detector
    #: ignores ``tense`` as a height-split source when this is
    #: False, because a uniform polarity (every vowel coded
    #: ``-tense`` in a no-tense-contrast inventory) carries no
    #: positive information about the split — PHOIBLE codes most
    #: non-tense-system vowels as ``tense=-`` by default, which
    #: under the old rule disagreed with the explicit ATR coding
    #: and fired SPLIT_SOURCE_DIVERGENCE on every vowel.
    has_tense_contrast: bool = False
    #: Same contract for ATR.
    has_atr_contrast: bool = False
    #: Same contract for RTR.
    has_rtr_contrast: bool = False
    #: Relative-articulation diacritics. Each lets the refinement
    #: layer nudge the base row or column one step in the
    #: corresponding direction.
    has_raised: bool = False
    has_lowered: bool = False
    has_advanced: bool = False
    has_retracted: bool = False
    has_centralized: bool = False
    has_peripheral: bool = False

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR, Tense, or RTR to split
        height tiers (the difference between Close and Near-close,
        or Close-mid and Open-mid).
        """
        return self.has_atr or self.has_tense or self.has_rtr


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
    #: Allow ``[rtr]`` to drive the height split when neither
    #: ``tense`` nor ``atr`` are present. ``[+rtr]`` is inverted
    #: (treated as ``[-atr]``-equivalent) so retracted-root vowels
    #: land on the Near-close / Open-mid side of each split.
    allow_rtr_split: bool = True
    #: Apply ``raised`` / ``lowered`` to nudge the resolved row
    #: one step (e.g. Close ``+lowered`` -> Near-close). Disabling
    #: this restores pre-extension behaviour where these features
    #: are silently ignored.
    allow_relative_height_refinement: bool = True
    #: Apply ``advanced`` / ``retracted`` / ``centralized`` to
    #: nudge the resolved column one step. Disabling restores
    #: pre-extension behaviour.
    allow_relative_backness_refinement: bool = True
    #: Allow ``peripheral`` to break ties on underspecified or
    #: fallback backness placements. Never overrides a DIRECT
    #: inference; only nudges already-uncertain placements.
    allow_peripheral_tiebreak: bool = True


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
    # Final-state placement for a diphthong; ``None`` for a
    # monophthong. When set, both this placement and the secondary
    # carry :py:attr:`PlacementFlag.DIPHTHONG`. Renderers draw a
    # curved arrow from the primary cell to ``secondary``'s cell;
    # the segment glyph stays in the primary only.
    secondary: VowelPlacement | None = None


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
    tense_polarities: set[str] = set()
    atr_polarities: set[str] = set()
    rtr_polarities: set[str] = set()
    for seg in segs:
        for feat, val in seg_feats.get(seg, {}).items():
            key = feat.lower()
            if val != "0":
                active.add(key)
            if key == "long" and val in ("+", "-"):
                long_polarities.add(val)
            elif key == "tense" and val in ("+", "-"):
                tense_polarities.add(val)
            elif key == "atr" and val in ("+", "-"):
                atr_polarities.add(val)
            elif key == "rtr" and val in ("+", "-"):
                rtr_polarities.add(val)
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
        has_rtr="rtr" in active,
        has_tense_contrast=("+" in tense_polarities)
        and ("-" in tense_polarities),
        has_atr_contrast=("+" in atr_polarities) and ("-" in atr_polarities),
        has_rtr_contrast=("+" in rtr_polarities) and ("-" in rtr_polarities),
        has_raised="raised" in active,
        has_lowered="lowered" in active,
        has_advanced="advanced" in active,
        has_retracted="retracted" in active,
        has_centralized="centralized" in active,
        has_peripheral="peripheral" in active,
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
#: rounded or unrounded button). The renderer subtracts this from
#: the front anchor to find the silhouette left edge (still
#: normalised; the front edge keeps the canonical extent).
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
        # ``top_right`` / ``bottom_right`` are the canonical back-
        # edge position in normalised x: the back anchor plus the
        # pair-outer extent so the line sits where a back-rounded
        # mate's outer right edge WOULD be. Renderers multiply by
        # the data-area width; on charts wider than the canonical
        # content width the line drifts slightly past the button,
        # which is the intended visual spacing.
        top_right=back + pair_outer,
        bottom_left=front_at_bottom - pair_outer,
        bottom_right=back + pair_outer,
        top_width=top_row_width,
        bottom_width=bottom_row_width,
        # Cell-extent fields (cascade source). Renderers position
        # the silhouette edges at ``anchor * dw ± cell_outer_extent_px``
        # so the silhouette wraps the outer cell edge flush at ANY
        # data width, not just the canonical 232 px.
        front_anchor_at_top=front_at_top,
        front_anchor_at_bottom=front_at_bottom,
        back_anchor=back,
        # Constant pixel offset from a paired cell's centre to its
        # outer edge: ``pair_shift`` (centre-to-mate-centre / 2)
        # plus half a button width. This is the px adjustment the
        # renderer adds to ``anchor * dw`` so the silhouette is
        # flush with the outer cell edge at ANY data width.
        cell_outer_extent_px=int(
            round((BTN_W + VOWEL_PAIR_GAP_PX) / 2.0 + BTN_W / 2.0)
        ),
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
    policy: PlacementPolicy | None = None,
    profile: VowelProfile | None = None,
) -> tuple[str | None, str, bool]:
    """Resolve the tense/ATR/RTR split that distinguishes adjacent
    height tiers (Close vs Near-close, Close-mid vs Open-mid).

    Returns ``(value, source, divergent)`` where ``value`` is
    ``"+"``, ``"-"``, or ``None`` (no specification), ``source``
    names which feature supplied the value, and ``divergent``
    is True when two of the three sources were specified but
    disagreed (so the placement object can attach the
    ``SPLIT_SOURCE_DIVERGENCE`` flag).

    Priority: ``tense`` -> ``atr`` -> ``rtr``. RTR is inverted on
    the way in (``[+rtr]`` is treated as ``[-atr]`` for split
    purposes) since the two roots are oppositely valued. Divergence
    is checked across all three sources whenever more than one is
    specified.

    Inventory-level contrast gating: a source is only counted
    when ``profile.has_<feat>_contrast`` is True. Inventories that
    encode every vowel ``tense=+`` (or every vowel ``atr=-``)
    without a real contrast carry no positive information on that
    feature; under the old "anywhere-non-zero counts as a source"
    rule, PHOIBLE inventories fired SPLIT_SOURCE_DIVERGENCE on
    every vowel because PHOIBLE stores the columns even where the
    contrast is absent. ``profile=None`` skips the gate (back-
    compat for callers that built a feature bundle by hand).

    Resolution policy: when several specified and agree (with RTR
    inverted), take it. When several disagree, prefer the highest-
    priority specified source and surface the conflict. When only
    one is specified, use it. When none is specified, return
    ``None``.
    """
    policy = policy or PlacementPolicy()
    tense = _nonzero(feats.get("tense"))
    atr = _nonzero(feats.get("atr"))
    rtr = _nonzero(feats.get("rtr"))
    # Asymmetric RTR -> ATR-equivalent inversion. ``+rtr``
    # (retracted tongue root) implies ``-atr`` because a vowel
    # can't be both advanced and retracted at the same time --
    # this drives a real claim about the ATR axis. ``-rtr`` (not
    # retracted) does NOT imply ``+atr``: a vowel can be neither
    # advanced nor retracted, so a negative RTR carries no positive
    # claim about ATR direction. The earlier symmetric rule
    # (``-rtr -> +atr-equiv``) fired SPLIT_SOURCE_DIVERGENCE on
    # every PHOIBLE vowel because PHOIBLE encodes most non-ATR-
    # system vowels as ``atr=- rtr=-``; under the old inversion
    # the synthesized ``+atr-equiv`` disagreed with the explicit
    # ``atr=-`` and the divergence detector counted it as a
    # source-disagreement.
    rtr_inverted = "-" if rtr == "+" else None

    def _has_disagreement(*vals: str | None) -> bool:
        present = [v for v in vals if v is not None]
        return len(present) >= 2 and len(set(present)) > 1

    # Inventory-level contrast gating for divergence DETECTION only.
    # The values are still used for placement resolution; the gating
    # only stops a uniform-polarity source from being counted as a
    # disagreement against the others. PHOIBLE codes most non-tense-
    # system vowels as ``tense=-`` uniformly (so reading ``tense=-``
    # alongside ``atr=-`` looks like agreement, not a real source).
    # The intent-coded Hayes inventories (Ilokano /e/ at Close-mid
    # via ``tense=+``) still resolve through value-resolution
    # because the value is read regardless of the contrast flag --
    # only the divergence flag is gated.
    tense_for_div = (
        tense if profile is None or profile.has_tense_contrast else None
    )
    atr_for_div = atr if profile is None or profile.has_atr_contrast else None
    rtr_inverted_for_div = (
        rtr_inverted if profile is None or profile.has_rtr_contrast else None
    )

    if tense is not None:
        divergent = _has_disagreement(
            tense_for_div, atr_for_div, rtr_inverted_for_div
        )
        if atr is not None:
            label = (
                "tense/ATR"
                if tense == atr
                and not _has_disagreement(tense_for_div, rtr_inverted_for_div)
                else (
                    "tense (overrides conflicting ATR/RTR)"
                    if divergent
                    else "tense/ATR"
                )
            )
        else:
            label = (
                "tense"
                if not divergent
                else "tense (overrides conflicting RTR)"
            )
        return tense, label, divergent
    if atr is not None:
        divergent = _has_disagreement(atr_for_div, rtr_inverted_for_div)
        label = "ATR" if not divergent else "ATR (overrides conflicting RTR)"
        return atr, label, divergent
    if rtr is not None and policy.allow_rtr_split:
        return rtr_inverted, "RTR", False
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
    split_value, split_source, split_divergent = _height_split_value(
        feats, policy, profile
    )
    base_flags: frozenset[PlacementFlag] = (
        frozenset({PlacementFlag.SPLIT_SOURCE_DIVERGENCE})
        if split_divergent
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


#: Single-step "lowered" move on the height axis: each key is the
#: base row, value is the row one step more open. Rows at the
#: bottom of the chart (``Open``) have no further lowering target.
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


def _refine_height_with_relative_features(
    base: AxisEvidence,
    feats: Mapping[str, str],
    policy: PlacementPolicy,
) -> AxisEvidence:
    """Nudge the base height row by ``raised`` / ``lowered``.

    Returns the input ``base`` unchanged when the refinement is
    disabled by policy, neither feature is specified, both are
    specified with conflicting positive values, or the target
    row is off the end of the chart (e.g. ``Open`` ``+lowered``
    has no destination).

    Adds :py:attr:`PlacementFlag.REFINED` to the returned evidence
    whenever a nudge actually fires so downstream tooling can tell
    direct from refined placements apart. A blocked nudge (target
    off-chart, ``+raised`` and ``+lowered`` both set) returns the
    base unchanged but unions :py:attr:`PlacementFlag.CONFLICT`
    when the block was driven by conflicting raised/lowered values.
    """
    if not policy.allow_relative_height_refinement:
        return base
    raised = _nonzero(feats.get("raised"))
    lowered = _nonzero(feats.get("lowered"))
    if raised is None and lowered is None:
        return base
    if raised == "+" and lowered == "+":
        return replace(
            base, flags=base.flags | frozenset({PlacementFlag.CONFLICT})
        )
    target: str | None = None
    direction: str | None = None
    if raised == "+":
        target = _HEIGHT_RAISED_STEP.get(base.value)
        direction = "+raised"
    elif lowered == "+":
        target = _HEIGHT_LOWERED_STEP.get(base.value)
        direction = "+lowered"
    if target is None or direction is None:
        return base
    new_reason = f"{target}: {base.value} refined by [{direction}]"
    new_source = f"{base.source}+relative-height"
    return AxisEvidence(
        value=target,
        confidence=base.confidence,
        source=new_source,
        reason=new_reason,
        flags=base.flags | frozenset({PlacementFlag.REFINED}),
    )


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


def _refine_backness_with_relative_features(
    base: AxisEvidence,
    feats: Mapping[str, str],
    policy: PlacementPolicy,
) -> AxisEvidence:
    """Nudge the base backness column by ``advanced`` /
    ``retracted`` / ``centralized`` / ``peripheral``.

    Conflict handling mirrors :py:func:`_refine_height_with_relative_features`:
    ``+advanced`` and ``+retracted`` both set drops the nudge and
    adds :py:attr:`PlacementFlag.CONFLICT`. ``centralized``
    collapses front and back to central but is a no-op on a base
    that is already central. ``peripheral`` is a TIEBREAK only and
    never overrides a base evidence carrying
    :py:attr:`PlacementFlag.DIRECT`; it nudges underspecified or
    fallback placements when ``-peripheral`` (toward central) or
    explicitly preserves edge placements when ``+peripheral``.
    """
    if not policy.allow_relative_backness_refinement:
        return base
    advanced = _nonzero(feats.get("advanced"))
    retracted = _nonzero(feats.get("retracted"))
    centralized = _nonzero(feats.get("centralized"))
    peripheral = _nonzero(feats.get("peripheral"))
    if advanced == "+" and retracted == "+":
        return replace(
            base, flags=base.flags | frozenset({PlacementFlag.CONFLICT})
        )
    target: str | None = None
    direction: str | None = None
    if advanced == "+":
        target = _BACKNESS_ADVANCED_STEP.get(base.value)
        direction = "+advanced"
    elif retracted == "+":
        target = _BACKNESS_RETRACTED_STEP.get(base.value)
        direction = "+retracted"
    elif centralized == "+":
        if base.value != "central":
            target = "central"
            direction = "+centralized"
    refined = base
    if target is not None and direction is not None:
        refined = AxisEvidence(
            value=target,
            confidence=base.confidence,
            source=f"{base.source}+relative-backness",
            reason=f"{target}: {base.value} refined by [{direction}]",
            flags=base.flags | frozenset({PlacementFlag.REFINED}),
        )
    if peripheral is not None and policy.allow_peripheral_tiebreak:
        is_direct = PlacementFlag.DIRECT in refined.flags
        if peripheral == "-" and not is_direct and refined.value != "central":
            refined = AxisEvidence(
                value="central",
                confidence=refined.confidence,
                source=f"{refined.source}+peripheral-tiebreak",
                reason="central: refined by [-peripheral] (tiebreak)",
                flags=refined.flags | frozenset({PlacementFlag.REFINED}),
            )
        elif peripheral == "+" and refined.value in ("front", "back"):
            refined = replace(
                refined,
                reason=f"{refined.reason}; +peripheral preserves edge",
            )
    return refined


def compute_placements(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
    policy: PlacementPolicy | None = None,
    vowel_secondary: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[dict[tuple[int, int], list[str]], dict[str, VowelPlacement]]:
    """Place every vowel and group by (row, col) cell.

    ``policy`` defaults to :py:class:`PlacementPolicy` with the
    module-level defaults; pass one explicitly to enable the
    paper-recommended stricter settings (``coronal_front``
    disabled, low-vowel split off, etc.).

    ``vowel_secondary`` carries final-state feature bundles for
    diphthong segments (PHOIBLE's contour rows). Segments that
    appear in this map get a non-null ``placement.secondary`` and
    both placements carry :py:attr:`PlacementFlag.DIPHTHONG`. The
    collision-cell map (``occupied``) only tracks PRIMARY
    placements; secondaries live purely as a rendering hint.

    Degenerate-secondary suppression: when the secondary projection
    collapses to the SAME ``(row, col)`` cell as the primary (PHOIBLE
    pharyngealised vowels like ``iˤ`` whose contour halves differ
    only on features the placement code does not read for grid
    position), the secondary is dropped and the segment is treated
    as a monophthong. Without this, the chart would render a
    zero-length diphthong arrow that reads as a stray dot,
    misleading the user about the segment's behaviour. Today this
    affects 84 segments across 20 PHOIBLE languages (ARCHI/UPSID,
    Northern Qiang/EA, !Xun/PHOIBLE, etc.). After this gate, every
    ``geom.diphthongs`` entry honours the contract that its primary
    and secondary cells are distinct, which the rendering stress
    suite asserts.

    Returns ``(occupied, placements)``. Cells are sorted by
    descending placement confidence (highest first); ties break on
    ascending segment string for stable ordering.
    """
    policy = policy or PlacementPolicy()
    secondary_feats = vowel_secondary or {}
    # Normalize the per-segment feature bundles ONCE up front so
    # the per-segment loop can call ``_vowel_grid_pos_normalized``
    # (skipping the per-call lowercase dict allocation). Most
    # callers pass ``engine.normalized_segment_feats`` whose keys
    # are already lowercase -- this pass is a fast pure-Python
    # dict-comp in that case -- but the tests pass raw inventory
    # feats (PascalCase from PHOIBLE), so the contract has to
    # tolerate both shapes.
    norm_cache: dict[str, dict[str, str]] = {
        seg: _normalize_feat_keys(norm_feats.get(seg, {})) for seg in segs
    }
    occupied: dict[tuple[int, int], list[str]] = {}
    placements: dict[str, VowelPlacement] = {}
    for seg in segs:
        placement = _vowel_grid_pos_normalized(
            norm_cache[seg], profile, policy
        )
        if seg in secondary_feats:
            secondary = vowel_grid_pos(secondary_feats[seg], profile, policy)
            # Suppress the secondary when it lands in the SAME
            # (row, col) cell as the primary; the arrow would be
            # zero-length. The segment then renders as a regular
            # monophthong.
            if (
                secondary.row != placement.row
                or secondary.col != placement.col
            ):
                secondary = replace(
                    secondary,
                    flags=(
                        secondary.flags | frozenset({PlacementFlag.DIPHTHONG})
                    ),
                )
                placement = replace(
                    placement,
                    flags=(
                        placement.flags | frozenset({PlacementFlag.DIPHTHONG})
                    ),
                    secondary=secondary,
                )
        placements[seg] = placement
        # Only MONOPHTHONGS occupy chart cells. Diphthongs render
        # exclusively as ARROWS + chip strip; their segment
        # button does NOT sit in any chart cell.
        #
        # Pre-fix: a diphthong like Korean /ia/ landed in the same
        # cell as /i/ (both at close-front). The cell stack showed
        # /i, ia, ie, iɛ, iʌ, iː/ together. User feedback called
        # this out -- the diphthong segments visually grouped with
        # the singleton /i/ inside the chart stack, AND toggling
        # diphthong-display mode hid the whole cell (so /i/
        # disappeared from the monophthong view too).
        #
        # Post-fix: cells contain only monophthong entries. The
        # diphthong's placement record stays in ``placements``
        # (so the arrow-build loop can read its primary +
        # secondary coords) but it does NOT add the segment to
        # ``occupied``, so no cell carries it. The chip strip below
        # the silhouette is the only place users SELECT diphthong
        # segments from.
        if PlacementFlag.DIPHTHONG not in placement.flags:
            occupied.setdefault((placement.row, placement.col), []).append(seg)
    # Confidence DESCENDING (via negated int), segment ASCENDING
    # within the same confidence tier. A single ``reverse=True``
    # would also flip the segment direction.
    for key in occupied:
        occupied[key].sort(key=lambda s: (-int(placements[s].confidence), s))
    return occupied, placements


# ---------------------------------------------------------------------------
# Render-ready chart geometry — extracted to
# ``phonology_shared.chart.vowels_layout`` so the trapezoid silhouette
# solver and per-cell positioning logic live in a single, greppable
# file. The re-export below preserves backward compatibility with
# existing imports that read these symbols directly from
# ``phonology_shared.chart.vowels``.
# ---------------------------------------------------------------------------

# Imported late so ``vowels_layout`` can import the inference-layer
# symbols above (avoids a circular import at module load).
from phonology_shared.chart import (  # noqa: E402
    vowels_layout as _vowels_layout,
)

VOWEL_CHART_TITLE = _vowels_layout.VOWEL_CHART_TITLE
PAIR_DISPLAY_KINDS = _vowels_layout.PAIR_DISPLAY_KINDS
VowelChartCell = _vowels_layout.VowelChartCell
VowelChartRow = _vowels_layout.VowelChartRow
VowelChartColHeader = _vowels_layout.VowelChartColHeader
VowelChartSilhouette = _vowels_layout.VowelChartSilhouette
VowelChartDiphthong = _vowels_layout.VowelChartDiphthong
VowelChartBand = _vowels_layout.VowelChartBand
VowelChartGeometry = _vowels_layout.VowelChartGeometry
build_vowel_chart_geometry = _vowels_layout.build_vowel_chart_geometry

# Layout-tier helpers + tunables, re-exported so existing tests that
# reach into the privates (test_vowel_silhouette_shrink) continue to
# work via the original import path.
_VOWEL_CELL_STACK_GAP_PX = _vowels_layout._VOWEL_CELL_STACK_GAP_PX
_VOWEL_ROW_GAP_PX = _vowels_layout._VOWEL_ROW_GAP_PX
_VOWEL_DATA_AREA_VERTICAL_PADDING_PX = (
    _vowels_layout._VOWEL_DATA_AREA_VERTICAL_PADDING_PX
)
_VOWEL_CONTENT_W_PX = _vowels_layout._VOWEL_CONTENT_W_PX
_VOWEL_SHRINK_FACTOR = _vowels_layout._VOWEL_SHRINK_FACTOR
_VOWEL_SLANT_CHANGE_CAP_FRAC = _vowels_layout._VOWEL_SLANT_CHANGE_CAP_FRAC
_VOWEL_MIN_CELL_GAP_NORM = _vowels_layout._VOWEL_MIN_CELL_GAP_NORM
_row_content_extent = _vowels_layout._row_content_extent
_min_row_width_for_meta = _vowels_layout._min_row_width_for_meta
_compute_shrunken_widths = _vowels_layout._compute_shrunken_widths
_stage1_uniform_shrink = _vowels_layout._stage1_uniform_shrink
_stage2_slant_tweak = _vowels_layout._stage2_slant_tweak
_silhouette_with_widths = _vowels_layout._silhouette_with_widths
_classify_vowel_cell_display = _vowels_layout._classify_vowel_cell_display
_order_pair_entries = _vowels_layout._order_pair_entries
_natural_data_area_size = _vowels_layout._natural_data_area_size


# Module-level so it isn't rebuilt per placement call. Maps the
# backness axis verdict to its unrounded-pair column index; the
# rounded mate is ``base + 1`` and the neutral-rounding row is
# ``6 + base // 2``.
_PLACE_TO_COLUMN: Mapping[str, int] = {"front": 0, "central": 2, "back": 4}


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

    Bulk callers (``compute_placements``) that already pass
    lowercase keys should use :py:func:`_vowel_grid_pos_normalized`
    directly to skip the per-call ``_normalize_feat_keys`` dict
    allocation.
    """
    return _vowel_grid_pos_normalized(
        _normalize_feat_keys(feats), profile, policy
    )


def _vowel_grid_pos_normalized(
    normalized: Mapping[str, str],
    profile: VowelProfile,
    policy: PlacementPolicy | None = None,
) -> VowelPlacement:
    """Placement core. Caller MUST pass already-lowercase keys --
    use :py:func:`vowel_grid_pos` for the safe wrapper that
    normalizes first.
    """
    policy = policy or PlacementPolicy()
    height = _infer_height(normalized, profile, policy)
    height = _refine_height_with_relative_features(height, normalized, policy)
    backness = _infer_backness(normalized, profile, policy)
    backness = _refine_backness_with_relative_features(
        backness, normalized, policy
    )
    rounding = _infer_rounding(normalized, profile, policy)

    row = _ROW_LABEL_TO_INDEX[height.value]
    base_col = _PLACE_TO_COLUMN[backness.value]
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
    # Bounds-check post-condition. Pinning these here surfaces a
    # placement bug at the placer with a clear segment-level
    # message, rather than letting it propagate into the renderer
    # where it would surface as either a clamped chart_xy or an
    # IndexError on ROW_LABELS / _col_to_anchor.
    assert 0 <= row < len(ROW_LABELS), (
        f"placement row out of bounds: row={row}, "
        f"ROW_LABELS={len(ROW_LABELS)}; reason={reason}"
    )
    # 9 logical columns: 0-5 pair slots, 6-8 neutral-round slots.
    assert 0 <= col < 9, (
        f"placement col out of bounds: col={col}, expected 0..8; "
        f"reason={reason}"
    )
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
