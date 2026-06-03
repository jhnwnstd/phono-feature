"""Chart-placement policy for vowel segments.

Pure-Python, shared by the desktop :py:class:`VowelChartWidget` and
the web app's vowel chart renderer (relayed into the Pyodide bundle
by the web build).

**Scope.** This module is *chart placement policy*, not phonological
theory. Given a vowel's feature bundle, it decides which cell of the
IPA chart to render the vowel in. The categories (height tiers,
front/central/back columns, rounded/unrounded split) are real
phonological dimensions, but several of the placement rules below
are inventory-conventional heuristics, not universally agreed
phonological inferences. The :py:class:`VowelProfile` gates each
fallback on whether the relevant feature is actually used by the
inventory, so an inventory that has no Coronal or no Labial does
not get tagged with the corresponding fallback semantics.

**Theory-neutrality limits.**

* ``[+high, -low]`` -> close / near-close, ``[-high, -low]`` -> mid,
  ``[-high, +low]`` -> open / near-open. Standard binary-feature
  decomposition of vowel height.
* ``[+back]`` -> back, ``[+front]`` -> front. Direct read.
* ``[+round]`` -> rounded. Direct read.
* ``[-back]`` with no ``[front]`` -> inferred front. Defensible in
  most feature systems where ``front == not back`` is a working
  approximation for chart display.
* ``[-front]`` alone with no ``[back]`` -> defaults to central. In
  feature systems where ``[-front, -back]`` means central and
  ``[-front, +back]`` means back, ``[-front]`` alone is genuinely
  ambiguous; central is the conservative default and we mark the
  confidence LOW so the UI can surface the uncertainty.
* ``[+labial]`` -> rounded when ``[round]`` is absent. Inventory
  convention, not a universal phonological inference: some feature
  geometries (Sagey) place ``[round]`` under Labial, but other
  systems treat all vowels and glides as ``[+labial]``, which would
  overgenerate rounded vowels under this fallback. We only enable
  it when the inventory has ``Labial`` AND lacks ``Round``.
* ``[+coronal]`` -> front. Not standard phonology (Coronal is
  typically a consonant place node); enabled only when the
  inventory has ``Coronal`` AND lacks ``Front``, and tagged with
  LOW confidence so callers know it is a backstop. Real
  phonological analysis would not use this rule.
* ``[tense]`` vs ``[ATR]``. Some traditions treat these as the same
  feature; there is no settled consensus. When both are present and
  disagree, this module prefers ``tense`` and the reason string
  records the override so the choice is auditable. Inventories that
  use only one of the two are unaffected.

**Underspecification** lands at "Open-mid Central" with LOW
confidence. The UI uses ``confidence`` and ``reason`` to expose this
to the user; the default is a placement choice, not a claim that the
vowel is genuinely open-mid central.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

# The six height tiers of the IPA vowel chart, in row order. Tuple
# is (label, +high, +low, +tense-or-atr): the feature bundle that
# canonically populates the row. Used by the chart widget to label
# rows and by tests to spot-check that placement maps correctly.
# Immutable so importers cannot mutate the shared singleton.
VOWEL_HEIGHT: tuple[tuple[str, str, str, str | None], ...] = (
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
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
    """Tags on a placement decision that the renderer (or a tooltip
    formatter) can read without parsing the free-text reason string.

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
    """A vowel's cell in the IPA chart. ``row`` is the height tier
    (index into ``ROW_LABELS``); ``col`` is the 6-column index
    (front-unr, front-rnd, central-unr, central-rnd, back-unr,
    back-rnd, 0-5).

    Per-axis ``height`` / ``backness`` / ``rounding`` carry the
    evidence each placement decision was made from. The top-level
    ``confidence`` and ``reason`` are derived summaries kept for
    backward compatibility with existing consumers.
    """

    row: int
    col: int
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
    for seg in segs:
        for feat, val in seg_feats.get(seg, {}).items():
            if val != "0":
                active.add(feat.lower())
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
    )


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
        return AxisEvidence(
            "Open-mid",
            Confidence.LOW,
            "default",
            "Open-mid (default): [-high, -low], no tense/ATR",
            base_flags
            | {PlacementFlag.UNDERSPECIFIED, PlacementFlag.DEFAULT_ANCHOR},
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
# cell entry, attach the prebaked tooltip string. No frontend
# duplicates placement decisions, tooltip formatting, or physical-
# coordinate arithmetic.
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


def vowel_tooltip(seg: str, confidence_name: str, reason: str) -> str:
    """One-line tooltip string used on every vowel-chart button.

    ``confidence_name`` is the lowercased ``Confidence.name``
    (``"high"`` / ``"medium"`` / ``"low"``). Both frontends consume
    the same string; baking the format here means a future tweak
    (extra whitespace, different brackets, an icon glyph) flows to
    both UIs from one edit.
    """
    return f"/{seg}/  [{confidence_name}]  {reason}"


@dataclass(frozen=True)
class VowelChartCellEntry:
    """One vowel inside a chart cell, fully resolved.

    The ``tooltip`` field is the prebaked output of
    :py:func:`vowel_tooltip` so renderers attach it verbatim.
    """

    seg: str
    confidence: str  # lowercased Confidence.name
    reason: str
    tooltip: str


@dataclass(frozen=True)
class VowelChartCell:
    """A populated chart cell with its position resolved.

    ``row`` / ``col`` are the logical placement (0..5 each). ``grid_row``
    and ``grid_col`` are the Qt 0-based physical coordinates the
    renderer drops the cell into; CSS-side code adds 1 to each.
    ``entries`` is ordered by descending placement confidence (ties
    broken by ascending segment string).
    """

    row: int
    col: int
    grid_row: int
    grid_col: int
    entries: tuple[VowelChartCellEntry, ...]


@dataclass(frozen=True)
class VowelChartRow:
    """A row to render. ``logical_row`` indexes into ``ROW_LABELS``;
    ``grid_row`` is the Qt 0-based physical row the renderer drops the
    row label into."""

    logical_row: int
    label: str
    grid_row: int


@dataclass(frozen=True)
class VowelChartColHeader:
    """A backness column header (Front / Central / Back) with its
    physical placement already resolved. Both renderers consume the
    grid coordinates verbatim; web adds 1 for CSS's 1-indexed grid.
    """

    label: str
    grid_col: int
    grid_col_span: int


@dataclass(frozen=True)
class VowelChartGeometry:
    """Complete render-ready description of a vowel chart.

    Both Qt and the web bridge consume this verbatim: emit one row
    label per :py:attr:`rows` entry, one cell per :py:attr:`cells`
    entry, and one button per cell entry with the prebaked tooltip.

    Empty rows (no vowels in any column at that height tier) are
    OMITTED from :py:attr:`rows`; renderers iterate the list as-is
    without a "is this row populated" check.
    """

    title: str
    title_grid_col_span: int
    cols: tuple[VowelChartColHeader, ...]
    rows: tuple[VowelChartRow, ...]
    cells: tuple[VowelChartCell, ...]


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
         with prebaked tooltip strings on every entry.
      3. For each populated height tier, build a
         :py:class:`VowelChartRow` with the assigned physical grid
         row.

    Renderers attach the result directly: no placement decisions,
    no string formatting, no coordinate arithmetic happens at the
    UI layer.
    """
    occupied, placements = compute_placements(
        segs, profile, norm_feats, policy
    )

    populated_logical_rows = sorted({row for (row, _) in occupied})
    logical_row_to_grid_row = {
        ri: VOWEL_FIRST_DATA_GRID_ROW + display_index
        for display_index, ri in enumerate(populated_logical_rows)
    }

    rows = tuple(
        VowelChartRow(
            logical_row=ri,
            label=ROW_LABELS[ri],
            grid_row=logical_row_to_grid_row[ri],
        )
        for ri in populated_logical_rows
    )

    cells: list[VowelChartCell] = []
    for ri, ci in sorted(occupied):
        entries: list[VowelChartCellEntry] = []
        for seg in occupied[(ri, ci)]:
            placement = placements[seg]
            confidence_name = placement.confidence.name.lower()
            entries.append(
                VowelChartCellEntry(
                    seg=seg,
                    confidence=confidence_name,
                    reason=placement.reason,
                    tooltip=vowel_tooltip(
                        seg,
                        confidence_name,
                        placement.reason,
                    ),
                )
            )
        cells.append(
            VowelChartCell(
                row=ri,
                col=ci,
                grid_row=logical_row_to_grid_row[ri],
                grid_col=VOWEL_LABEL_GRID_COL + logical_col_offset(ci),
                entries=tuple(entries),
            )
        )

    col_headers = tuple(
        VowelChartColHeader(
            label=label,
            grid_col=(VOWEL_FIRST_DATA_GRID_COL + ci * 3),
            grid_col_span=VOWEL_COL_HEADER_GRID_COL_SPAN,
        )
        for ci, label in enumerate(COL_LABELS)
    )

    return VowelChartGeometry(
        title=VOWEL_CHART_TITLE,
        title_grid_col_span=VOWEL_TITLE_GRID_COL_SPAN,
        cols=col_headers,
        rows=rows,
        cells=tuple(cells),
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
    col = base_col + 1 if rounding.value == "rounded" else base_col

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
        confidence=confidence,
        reason=reason,
        height=height,
        backness=backness,
        rounding=rounding,
        flags=flags,
    )
