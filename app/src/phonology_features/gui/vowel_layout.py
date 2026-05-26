"""Pure-Python vowel-placement logic shared by the desktop GUI and
the web app.

Nothing in this module imports Qt or anything browser-specific. The
desktop's ``VowelChartWidget`` (in ``vowel_chart.py``) reads it
directly; the web app picks it up via the build script's renderer
relay (the file is copied into the Pyodide bundle and api.py exposes
it through the JS bridge).

Single source of truth for "given a vowel's feature bundle, which
cell of the IPA chart does it land in?" Edits to the placement
rules (fallback heuristics for inventories that omit ATR/Tense,
CORONAL-as-frontness backstop, etc.) propagate to both UIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# The six height tiers of the IPA vowel chart, in row order. Tuple
# is (label, +high, +low, +tense-or-atr): the feature bundle that
# canonically populates the row. Used by the chart widget to label
# rows and by tests to spot-check that placement maps correctly.
VOWEL_HEIGHT: list[tuple[str, str, str, str | None]] = [
    ("Close", "+", "-", "+"),
    ("Near-close", "+", "-", "-"),
    ("Close-mid", "-", "-", "+"),
    ("Open-mid", "-", "-", "-"),
    ("Near-open", "-", "+", "-"),
    ("Open", "-", "+", None),
]
ROW_LABELS: list[str] = [label for label, *_ in VOWEL_HEIGHT]

# Column labels in display order. The cells alternate
# (unrounded, rounded) per place-of-articulation triplet, so the
# rendered chart is 6 columns wide.
COL_LABELS: list[str] = ["Front", "Central", "Back"]


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

    Only fields actually consumed by the placement decisions are
    carried. Earlier versions tracked more (``has_back``, etc.) but
    nothing read them.
    """

    has_front: bool
    has_round: bool
    has_labial: bool
    has_atr: bool
    has_tense: bool
    has_coronal: bool

    @property
    def use_coronal_front_fallback(self) -> bool:
        """Use CORONAL as a proxy for frontness only when Front is absent."""
        return self.has_coronal and not self.has_front

    @property
    def has_height_sub_distinction(self) -> bool:
        """True if the inventory uses ATR or Tense to split height tiers."""
        return self.has_atr or self.has_tense

    @property
    def use_labial_round_fallback(self) -> bool:
        """Use LABIAL as a rounding proxy only when Round is absent."""
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


def _normalize_feat_keys(feats: dict) -> dict:
    """Lowercase every key in ``feats`` so downstream lookups by
    canonical IPA-feature name (``high``, ``low``, ``front``, etc.)
    work regardless of whether the caller passed raw PascalCase
    inventory keys or pre-normalized lowercase keys.

    The placement code is the only consumer that mandates canonical
    case (segment_grouper uses a similar convention); doing the
    lowercase pass HERE means call sites can't accidentally pass
    raw inventory feats and silently get every vowel placed in the
    "Open-mid Central" default cell.
    """
    return {k.lower(): v for k, v in feats.items()}


def detect_vowel_profile(segs: list[str], seg_feats: dict) -> VowelProfile:
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


def _fv(feats: dict, key: str) -> str:
    """Feature value, defaulting to '0'."""
    return feats.get(key, "0")


def _nonzero(val: str | None) -> str | None:
    """Return val only if it carries real feature information."""
    has_value = bool(val)
    is_unspecified = val == "0"
    if has_value and not is_unspecified:
        return val
    return None


def _infer_height(
    feats: dict, profile: VowelProfile
) -> tuple[int, Confidence, str]:
    """Return row, confidence, and reason."""
    hi = _fv(feats, "high")
    lo = _fv(feats, "low")
    tense_value = _nonzero(feats.get("tense"))
    atr_value = _nonzero(feats.get("atr"))
    atr_tn = tense_value or atr_value
    is_high_vowel = hi == "+" and lo == "-"
    is_low_vowel = hi == "-" and lo == "+"
    is_mid_vowel = hi == "-" and lo == "-"
    if is_high_vowel:
        is_near_close = profile.has_height_sub_distinction and atr_tn == "-"
        if is_near_close:
            return (
                1,
                Confidence.MEDIUM,
                "Near-close: [+high, -low, -tense/ATR]",
            )
        if atr_tn == "+":
            return 0, Confidence.HIGH, "Close: [+high, -low, +tense/ATR]"
        return 0, Confidence.HIGH, "Close: [+high, -low]"
    if is_low_vowel:
        is_near_open = profile.has_height_sub_distinction and atr_tn == "-"
        if is_near_open:
            return 4, Confidence.MEDIUM, "Near-open: [-high, +low, -tense/ATR]"
        return 5, Confidence.HIGH, "Open: [-high, +low]"
    if is_mid_vowel:
        if atr_tn == "+":
            return 2, Confidence.MEDIUM, "Close-mid: [-high, -low, +tense/ATR]"
        if atr_tn == "-":
            return 3, Confidence.MEDIUM, "Open-mid: [-high, -low, -tense/ATR]"
        return (
            3,
            Confidence.LOW,
            "Open-mid (default): [-high, -low], no tense/ATR",
        )
    return 3, Confidence.LOW, "Open-mid (default): underspecified height"


def _infer_backness(
    feats: dict, profile: VowelProfile
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
    if profile.use_coronal_front_fallback:
        cor = _nonzero(feats.get("coronal"))
        ant = feats.get("anterior", "0")
        is_coronal = cor == "+"
        is_retroflex_or_rhotic = ant == "-"
        if is_coronal and not is_retroflex_or_rhotic:
            return (
                "front",
                Confidence.LOW,
                "Front (inferred): CORONAL fallback",
            )
    return (
        "central",
        Confidence.LOW,
        "Central (default): no front/back specified",
    )


def _infer_rounding(feats: dict, profile: VowelProfile) -> tuple[bool, str]:
    has_rounding = _fv(feats, "round") == "+"
    if has_rounding:
        return True, "Rounded: [+round]"
    can_use_labial_fallback = profile.use_labial_round_fallback
    has_labial = _fv(feats, "labial") == "+"
    if can_use_labial_fallback and has_labial:
        return True, "Rounded (inferred): LABIAL fallback"
    return False, "Unrounded"


def vowel_grid_pos(feats: dict, profile: VowelProfile) -> VowelPlacement:
    """Return a VowelPlacement for a single vowel.

    Columns 0-5 map to (front-unr, front-rnd, central-unr,
    central-rnd, back-unr, back-rnd). Rows 0-5 map to ``ROW_LABELS``.

    ``feats`` is a single segment's feature bundle. Keys are
    case-normalized internally, so the caller may pass raw inventory
    feats (PascalCase keys like ``"High"``) or pre-normalized
    lowercase feats; both produce identical results.
    """
    feats = _normalize_feat_keys(feats)
    row, h_conf, h_reason = _infer_height(feats, profile)
    place, p_conf, p_reason = _infer_backness(feats, profile)
    rounded, r_reason = _infer_rounding(feats, profile)
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
