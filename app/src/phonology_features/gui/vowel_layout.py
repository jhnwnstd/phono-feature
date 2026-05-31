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
from dataclasses import dataclass
from enum import IntEnum

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


@dataclass(frozen=True)
class VowelProfile:
    """Which vowel-relevant features are actively used in this inventory.

    The placement code reads these to decide whether an
    inventory-conventional fallback applies. Fields are kept
    minimal: only what the placement decisions actually consume.
    """

    has_front: bool
    has_round: bool
    has_labial: bool
    has_atr: bool
    has_tense: bool
    has_coronal: bool

    @property
    def use_coronal_front_fallback(self) -> bool:
        """Use ``[+coronal]`` as evidence for frontness only when
        the inventory has no ``Front`` feature. An engineering
        backstop, not standard phonology; see the module docstring.
        """
        return self.has_coronal and not self.has_front

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR or Tense to split height
        tiers (the difference between Close and Near-close, or
        Close-mid and Open-mid).
        """
        return self.has_atr or self.has_tense

    @property
    def use_labial_round_fallback(self) -> bool:
        """Use ``[+labial]`` as evidence for rounding only when the
        inventory has no ``Round`` feature. An inventory convention
        following the Sagey feature geometry tradition; see the
        module docstring for when this can overgenerate.
        """
        return self.has_labial and not self.has_round


@dataclass(frozen=True)
class VowelPlacement:
    """A vowel's cell in the IPA chart. ``row`` is the height tier
    (index into ``ROW_LABELS``); ``col`` is the 6-column index
    (front-unr, front-rnd, central-unr, central-rnd, back-unr,
    back-rnd, 0-5)."""

    row: int
    col: int
    confidence: Confidence
    reason: str


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
        has_round="round" in active,
        has_labial="labial" in active,
        has_atr="atr" in active,
        has_tense="tense" in active,
        has_coronal="coronal" in active,
    )


def _fv(feats: Mapping[str, str], key: str) -> str:
    """Feature value, defaulting to '0'."""
    return feats.get(key, "0")


def _nonzero(val: str | None) -> str | None:
    """Return val only if it carries real feature information."""
    has_value = bool(val)
    is_unspecified = val == "0"
    if has_value and not is_unspecified:
        return val
    return None


def _height_split_value(
    feats: Mapping[str, str],
) -> tuple[str | None, str]:
    """Resolve the tense/ATR split that distinguishes adjacent
    height tiers (Close vs Near-close, Close-mid vs Open-mid).

    Returns ``(value, source)`` where ``value`` is ``"+"``,
    ``"-"``, or ``None`` (no specification), and ``source`` names
    which feature supplied the value. The two features sometimes
    co-occur in an inventory; this helper makes the resolution
    explicit:

    * Only one specified: use it.
    * Both specified and agree: use it, note both as the source.
    * Both specified and disagree: prefer ``tense``, the reason
      string records "tense overrides ATR" so callers can audit
      the choice. Phonological theory does not settle whether
      tense and ATR are the same feature; this is a policy choice.
    * Neither specified: ``None``, source is "none".
    """
    tense = _nonzero(feats.get("tense"))
    atr = _nonzero(feats.get("atr"))
    if tense is not None and atr is not None:
        if tense == atr:
            return tense, "tense/ATR"
        return tense, "tense (overrides conflicting ATR)"
    if tense is not None:
        return tense, "tense"
    if atr is not None:
        return atr, "ATR"
    return None, "none"


def _infer_height(
    feats: Mapping[str, str], profile: VowelProfile
) -> tuple[int, Confidence, str]:
    """Return row, confidence, and reason."""
    hi = _fv(feats, "high")
    lo = _fv(feats, "low")
    split_value, split_source = _height_split_value(feats)
    is_high_vowel = hi == "+" and lo == "-"
    is_low_vowel = hi == "-" and lo == "+"
    is_mid_vowel = hi == "-" and lo == "-"
    if is_high_vowel:
        is_near_close = (
            profile.has_height_sub_distinction and split_value == "-"
        )
        if is_near_close:
            return (
                1,
                Confidence.MEDIUM,
                f"Near-close: [+high, -low, -{split_source}]",
            )
        if split_value == "+":
            return (
                0,
                Confidence.HIGH,
                f"Close: [+high, -low, +{split_source}]",
            )
        return 0, Confidence.HIGH, "Close: [+high, -low]"
    if is_low_vowel:
        is_near_open = (
            profile.has_height_sub_distinction and split_value == "-"
        )
        if is_near_open:
            return (
                4,
                Confidence.MEDIUM,
                f"Near-open: [-high, +low, -{split_source}]",
            )
        return 5, Confidence.HIGH, "Open: [-high, +low]"
    if is_mid_vowel:
        if split_value == "+":
            return (
                2,
                Confidence.MEDIUM,
                f"Close-mid: [-high, -low, +{split_source}]",
            )
        if split_value == "-":
            return (
                3,
                Confidence.MEDIUM,
                f"Open-mid: [-high, -low, -{split_source}]",
            )
        return (
            3,
            Confidence.LOW,
            "Open-mid (default): [-high, -low], no tense/ATR",
        )
    return 3, Confidence.LOW, "Open-mid (default): underspecified height"


def _infer_backness(
    feats: Mapping[str, str], profile: VowelProfile
) -> tuple[str, Confidence, str]:
    """Return place, confidence, and reason."""
    fr = _nonzero(feats.get("front"))
    bk = _nonzero(feats.get("back"))
    has_positive_front = fr == "+"
    has_positive_back = bk == "+"
    if has_positive_front and not has_positive_back:
        return "front", Confidence.HIGH, "Front: [+front]"
    if has_positive_back and not has_positive_front:
        return "back", Confidence.HIGH, "Back: [+back]"
    if has_positive_front and has_positive_back:
        return "central", Confidence.LOW, "Central (conflict): [+front, +back]"
    has_no_front_value = fr is None
    has_negative_back = bk == "-"
    if has_no_front_value and has_negative_back:
        return "front", Confidence.MEDIUM, "Front (inferred): [-back]"
    # Explicit [-front] with [-back]: standard central spec.
    if fr == "-" and bk == "-":
        return "central", Confidence.HIGH, "Central: [-front, -back]"
    # Explicit [-front] alone: genuinely ambiguous between central
    # and back. Conservative default to central with LOW confidence
    # and a reason that surfaces the ambiguity to the UI.
    if fr == "-" and bk is None:
        return (
            "central",
            Confidence.LOW,
            "Central or back unresolved from [-front] alone",
        )
    if profile.use_coronal_front_fallback:
        cor = _nonzero(feats.get("coronal"))
        ant = feats.get("anterior", "0")
        is_coronal = cor == "+"
        is_retroflex_or_rhotic = ant == "-"
        if is_coronal and not is_retroflex_or_rhotic:
            return (
                "front",
                Confidence.LOW,
                "Front (inferred): CORONAL fallback (inventory convention)",
            )
    return (
        "central",
        Confidence.LOW,
        "Central (default): no front/back specified",
    )


def _infer_rounding(
    feats: Mapping[str, str], profile: VowelProfile
) -> tuple[bool, str]:
    rnd = _nonzero(feats.get("round"))
    if rnd == "+":
        return True, "Rounded: [+round]"
    can_use_labial_fallback = profile.use_labial_round_fallback
    has_labial = _fv(feats, "labial") == "+"
    if can_use_labial_fallback and has_labial:
        return (
            True,
            "Rounded (inferred): LABIAL fallback (inventory convention)",
        )
    if rnd == "-":
        return False, "Unrounded: [-round]"
    return False, "Unrounded: no round specified"


def compute_placements(
    segs: list[str],
    profile: VowelProfile,
    norm_feats: Mapping[str, Mapping[str, str]],
) -> tuple[dict[tuple[int, int], list[str]], dict[str, VowelPlacement]]:
    """Place every vowel and group by (row, col) cell.

    Returns ``(occupied, placements)``:

    * ``occupied[(row, col)]`` is the list of segments mapping to
      that chart cell, sorted by descending placement confidence
      so the highest-confidence vowel ends up first. Ties on
      confidence are broken by ascending segment-string order so
      collision-cell ordering is stable and predictable.
    * ``placements[seg]`` is the full :py:class:`VowelPlacement`
      for that vowel.

    Pure-Python and shared between the desktop's
    :py:class:`VowelChartWidget` and the web bridge's chart builder,
    so cell collisions (typical case: ə, ɜ, ɚ all landing in the
    open-mid central cell of the General inventory) are grouped the
    same way on both frontends.
    """
    occupied: dict[tuple[int, int], list[str]] = {}
    placements: dict[str, VowelPlacement] = {}
    for seg in segs:
        placement = vowel_grid_pos(norm_feats.get(seg, {}), profile)
        placements[seg] = placement
        occupied.setdefault((placement.row, placement.col), []).append(seg)
    # Confidence DESCENDING (via negated int), segment ASCENDING
    # within the same confidence tier. A single ``reverse=True`` on
    # the tuple would also flip the segment direction, so we negate
    # the confidence component instead to keep secondary order
    # predictable.
    for key in occupied:
        occupied[key].sort(key=lambda s: (-int(placements[s].confidence), s))
    return occupied, placements


def vowel_grid_pos(
    feats: Mapping[str, str], profile: VowelProfile
) -> VowelPlacement:
    """Return a VowelPlacement for a single vowel.

    Columns 0-5 map to (front-unr, front-rnd, central-unr,
    central-rnd, back-unr, back-rnd). Rows 0-5 map to ``ROW_LABELS``.

    ``feats`` is a single segment's feature bundle. Keys are
    case-normalized internally, so the caller may pass raw inventory
    feats (PascalCase keys like ``"High"``) or pre-normalized
    lowercase feats; both produce identical results.
    """
    normalized = _normalize_feat_keys(feats)
    row, h_conf, h_reason = _infer_height(normalized, profile)
    place, p_conf, p_reason = _infer_backness(normalized, profile)
    rounded, r_reason = _infer_rounding(normalized, profile)
    place_to_column = {"front": 0, "central": 2, "back": 4}
    base_col = place_to_column[place]
    col = base_col + 1 if rounded else base_col
    # IntEnum orders by underlying int, so min picks the weaker
    # signal directly; no lookup table needed.
    confidence = min(h_conf, p_conf)
    reason = f"{h_reason}; {p_reason}; {r_reason}"
    return VowelPlacement(
        row=row, col=col, confidence=confidence, reason=reason
    )
