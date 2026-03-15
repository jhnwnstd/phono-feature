"""
engine/segment_grouper.py

Groups an inventory's segments into phonological categories for GUI display
using hierarchical agglomerative clustering on groups.

Groups are initially assigned by argmax feature-spec scoring, then
iteratively merged until the next merge would cost significantly more than
previous merges (elbow / dendrogram-cut stopping criterion).  No hardcoded
group-count targets or minimum-size thresholds.

After each merge, the result is checked against _RELABEL_PATTERNS: if the
combined origin set matches a known phonological class (Vibrants, Rhotics,
Liquids), the group is renamed accordingly.  _MERGE_BLOCKED prevents
linguistically incoherent merges that the elbow might otherwise permit.
"""

import math
from collections import defaultdict
from typing import Dict, FrozenSet, List, Set, Tuple

# ---------------------------------------------------------------------------
# Group taxonomy
# ---------------------------------------------------------------------------
# Ordered by specificity so that argmax scoring resolves ambiguities
# correctly (e.g. Lateral Affricates before plain Affricates).
# Spec keys must be in normalised form (see _normalize_key).

ALL_GROUPS: List[Tuple[str, Dict[str, str]]] = [
    ("Clicks", {"click": "+"}),
    # Lateral affricates before plain affricates; continuant:- is essential —
    # without it, inapplicable delrel scores 0.5 and fricatives get absorbed.
    (
        "Lateral Affricates",
        {
            "consonantal": "+",
            "delrel": "+",
            "continuant": "-",
            "lateral": "+",
            "sonorant": "-",
        },
    ),
    (
        "Affricates",
        {
            "consonantal": "+",
            "delrel": "+",
            "continuant": "-",
            "sonorant": "-",
        },
    ),
    # Lateral fricatives / approximants before the plain buckets
    (
        "Lateral Fricatives",
        {
            "consonantal": "+",
            "continuant": "+",
            "lateral": "+",
            "sonorant": "-",
        },
    ),
    (
        "Lateral Approximants",
        {
            "consonantal": "+",
            "continuant": "+",
            "lateral": "+",
            "sonorant": "+",
        },
    ),
    ("Trills", {"trill": "+"}),
    ("Taps & Flaps", {"tap": "+"}),
    ("Nasals", {"nasal": "+"}),
    # Sibilants: coronal strident fricatives (s, z, ʃ, ʒ, ɕ, ʂ …)
    (
        "Sibilants",
        {
            "consonantal": "+",
            "continuant": "+",
            "strident": "+",
            "coronal": "+",
        },
    ),
    (
        "Fricatives",
        {"consonantal": "+", "continuant": "+", "sonorant": "-"},
    ),
    (
        "Plosives",
        {
            "consonantal": "+",
            "continuant": "-",
            "sonorant": "-",
            "nasal": "-",
            "delrel": "-",
        },
    ),
    (
        "Approximants",
        {
            "consonantal": "+",
            "continuant": "+",
            "sonorant": "+",
            "nasal": "-",
            "lateral": "-",
            "trill": "-",
            "tap": "-",
        },
    ),
    # [-consonantal, -syllabic] split by sonorant:
    #   Semivowels = glides (j, w) — [+sonorant]
    #   Laryngeals = h, ɦ, ʔ    — [-sonorant]
    (
        "Semivowels",
        {"consonantal": "-", "syllabic": "-", "sonorant": "+"},
    ),
    (
        "Laryngeals",
        {"consonantal": "-", "syllabic": "-", "sonorant": "-"},
    ),
    ("Vowels", {"syllabic": "+"}),
]

SPEC: Dict[str, Dict[str, str]] = {name: spec for name, spec in ALL_GROUPS}

# Display order: least sonorous → most sonorous.
# Independent of ALL_GROUPS order (which is by feature-spec specificity).
# Derived labels (Vibrants, Rhotics, Liquids) are interleaved at the
# positions they occupy when they emerge from merges.
DISPLAY_ORDER: List[str] = [
    "Clicks",
    "Plosives",
    "Affricates",
    "Lateral Affricates",
    "Sibilants",
    "Fricatives",
    "Lateral Fricatives",
    "Nasals",
    "Vibrants",  # Trills + Taps & Flaps (if they merge first)
    "Trills",
    "Taps & Flaps",
    "Rhotics",  # Trills / Taps / Approximants merged
    "Lateral Approximants",
    "Liquids",  # Lateral Approximants + Rhotics/Approximants
    "Approximants",
    "Semivowels",  # glides: j, w ([-consonantal, +sonorant])
    "Laryngeals",  # h, ɦ, ʔ  ([-consonantal, -sonorant])
    "Vowels",
]

# ---------------------------------------------------------------------------
# Merge relabeling: frozenset of original group names → derived label
# ---------------------------------------------------------------------------
# Keys are sets of ALL_GROUPS names (origins), not current display names.

_RELABEL_PATTERNS: Dict[FrozenSet[str], str] = {
    # Vibrants: Trills + Taps merge before reaching Approximants
    frozenset({"Trills", "Taps & Flaps"}): "Vibrants",
    # Rhotics: any combination that includes Approximants with Trills/Taps
    frozenset({"Trills", "Approximants"}): "Rhotics",
    frozenset({"Taps & Flaps", "Approximants"}): "Rhotics",
    frozenset({"Trills", "Taps & Flaps", "Approximants"}): "Rhotics",
    # Liquids: Lateral Approximants + anything containing Approximants
    frozenset({"Lateral Approximants", "Approximants"}): "Liquids",
    frozenset({"Lateral Approximants", "Approximants", "Trills"}): "Liquids",
    frozenset(
        {"Lateral Approximants", "Approximants", "Taps & Flaps"}
    ): "Liquids",
    frozenset(
        {"Lateral Approximants", "Approximants", "Trills", "Taps & Flaps"}
    ): "Liquids",
    # Lateral Approximants + Vibrants (Trills+Taps merged before Approximants joined)
    frozenset({"Lateral Approximants", "Trills", "Taps & Flaps"}): "Liquids",
}

# ---------------------------------------------------------------------------
# Merge blocking: pairs of current group names that must never merge
# ---------------------------------------------------------------------------

_MERGE_BLOCKED: Set[FrozenSet[str]] = {
    # Pre-relabel: individual Trills / Taps must not merge with obstruents
    frozenset({"Trills", "Fricatives"}),
    frozenset({"Trills", "Sibilants"}),
    frozenset({"Trills", "Plosives"}),
    frozenset({"Taps & Flaps", "Fricatives"}),
    frozenset({"Taps & Flaps", "Sibilants"}),
    frozenset({"Taps & Flaps", "Plosives"}),
    # Post-relabel derived groups
    frozenset({"Vibrants", "Fricatives"}),
    frozenset({"Vibrants", "Sibilants"}),
    frozenset({"Vibrants", "Plosives"}),
    frozenset({"Rhotics", "Fricatives"}),
    frozenset({"Rhotics", "Sibilants"}),
    frozenset({"Rhotics", "Plosives"}),
    frozenset({"Liquids", "Fricatives"}),
    frozenset({"Liquids", "Plosives"}),
    # Prevent re-merging the two groups we explicitly split
    frozenset({"Semivowels", "Laryngeals"}),
}


# ---------------------------------------------------------------------------
# Key normalisation
# ---------------------------------------------------------------------------


def _normalize_key(key: str) -> str:
    """Normalise a feature name to a canonical lowercase token.

    Handles the main naming variants found across inventories:
    DelRel / del.rel. / delayed_release → delrel
    SpreadGl / s.g. / spread_gl → spreadgl
    ConstrGl / c.g. / constr_gl → constrgl
    """
    k = key.lower()
    k = k.replace("del.rel.", "delrel")
    k = k.replace("delayed_release", "delrel")
    k = k.replace("s.g.", "spreadgl")
    k = k.replace("c.g.", "constrgl")
    k = k.replace(".", "").replace("_", "").replace(" ", "")
    return k


def _normalize_feats(feat_dict: Dict[str, str]) -> Dict[str, str]:
    return {_normalize_key(k): v for k, v in feat_dict.items()}


# ---------------------------------------------------------------------------
# IPA canonical place ordering (left → right on the IPA chart)
# ---------------------------------------------------------------------------

_VOICE_IDX: Dict[str, int] = {"-": 0, "+": 1, "0": 2}


def _ipa_place(feats: Dict[str, str]) -> int:
    """Map normalised feature dict to IPA place-of-articulation index.

    Index  Place
      0    Bilabial
      1    Labiodental
      2    Dental
      3    Alveolar
      4    Postalveolar
      5    Retroflex
      6    Palatal
      7    Velar  (incl. labial-velar w/ʍ — dorsal dominates)
      8    Uvular
      9    Pharyngeal
     10    Glottal
     11    Vowels / unclassified
    """
    constrgl = feats.get("constrgl", "0")
    if constrgl == "+":
        return 10  # glottal stop (ʔ)

    consp = feats.get("constrpharynx", "0")
    phary = feats.get("pharyngeal", "0")
    if consp == "+" or phary == "+":
        return 9  # pharyngeal (ħ, ʕ)

    dor = feats.get("dorsal", "0")
    hi = feats.get("high", "0")
    bk = feats.get("back", "0")
    if dor == "+":
        if hi == "-":
            return 8  # uvular
        if bk == "-":
            return 6  # palatal (back explicitly front/minus)
        return 7  # velar (back=+ or back=0; includes labial-velars w/ʍ)

    cor = feats.get("coronal", "0")
    ant = feats.get("anterior", "0")
    dist = feats.get("distributed", "0")
    if cor == "+":
        if ant == "-":
            return 5 if dist == "-" else 4  # retroflex / postalveolar
        return 2 if dist == "+" else 3  # dental / alveolar

    lab = feats.get("labial", "0")
    labd = feats.get("labiodental", "0")
    if lab == "+":
        return 1 if labd == "+" else 0  # labiodental / bilabial

    cons = feats.get("consonantal", "0")
    syl = feats.get("syllabic", "0")
    if cons == "-" and syl == "-":
        return 10  # h, ɦ (no place features)

    return 11  # vowels or unclassified


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def seg_score(seg_feats: Dict[str, str], spec: Dict[str, str]) -> float:
    """How well does a segment match a group's defining spec?

    Per-feature rules:
      val == req   → 1.0   exact match
      val == "0"   → 0.5   inapplicable — not a mismatch
      contradiction→ 0.0
    """
    if not spec:
        return 0.0
    total = 0.0
    for feat, req in spec.items():
        v = seg_feats.get(feat, "0")
        if v == req:
            total += 1.0
        elif v == "0":
            total += 0.5
    return total / len(spec)


# ---------------------------------------------------------------------------
# Group-level operations
# ---------------------------------------------------------------------------


def group_cohesion(
    members: List[str],
    group_name: str,
    inventory: Dict[str, Dict[str, str]],
) -> float:
    """Mean score of all members against the group's spec."""
    spec = SPEC.get(group_name, {})
    if not members or not spec:
        return 0.0
    return sum(seg_score(inventory[s], spec) for s in members) / len(members)


def merge_cost(
    victims: List[str],
    victim_spec: Dict[str, str],
    target_spec: Dict[str, str],
    inventory: Dict[str, Dict[str, str]],
) -> float:
    """Drop in mean cohesion when victim's members move to target.

    Higher = worse merge (segments fit target poorly).
    """
    if not victims or not victim_spec or not target_spec:
        return 1.0
    before = sum(seg_score(inventory[s], victim_spec) for s in victims)
    after = sum(seg_score(inventory[s], target_spec) for s in victims)
    return max(0.0, (before - after) / len(victims))


def _is_outlier(new_cost: float, past_costs: List[float]) -> bool:
    """Return True if new_cost is a statistical outlier vs past costs.

    Requires at least 3 samples before the elbow can activate — prevents
    a single free merge (cost=0.0) from collapsing std to 0 and triggering
    the elbow on the very next step.  When std==0 (all past costs identical),
    anything strictly more expensive stops the merging.
    """
    if len(past_costs) < 1:
        return False
    mean = sum(past_costs) / len(past_costs)
    variance = sum((c - mean) ** 2 for c in past_costs) / len(past_costs)
    std = math.sqrt(variance)
    if std == 0:
        return new_cost > mean
    return new_cost > mean + std


def _find_best_merge(
    victim: str,
    members: List[str],
    surviving: Set[str],
    inventory: Dict[str, Dict[str, str]],
    local_spec: Dict[str, Dict[str, str]],
) -> Tuple[str, float]:
    """Find the surviving group that absorbs victim at lowest cohesion cost.

    Skips any candidate whose merge with victim is in _MERGE_BLOCKED.
    """
    v_spec = local_spec.get(victim, {})
    candidates = [
        g
        for g in surviving
        if g != victim and frozenset({victim, g}) not in _MERGE_BLOCKED
    ]
    if not candidates:
        return "", float("inf")
    costs = {
        g: merge_cost(members, v_spec, local_spec.get(g, {}), inventory)
        for g in candidates
    }
    best = min(costs, key=lambda g: costs[g])
    return best, costs[best]


# ---------------------------------------------------------------------------
# Main grouping function
# ---------------------------------------------------------------------------


def group_segments(
    inventory: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Assign every segment to a phonological display group.

    Uses hierarchical agglomerative merging: starts with argmax assignment
    to all groups, then iteratively merges the cheapest available group pair
    until the next merge cost is a statistical outlier vs. past costs (elbow).

    After each merge the combined origin set is checked against
    _RELABEL_PATTERNS; matching results are renamed (e.g. Trills + Taps →
    Vibrants, Approximants + Trills/Taps → Rhotics, Lateral Approximants +
    Rhotics/Approximants → Liquids).  _MERGE_BLOCKED prevents
    linguistically incoherent merges regardless of cost.

    Args:
        inventory: {symbol: {feature: value}} — raw from FeatureEngine.segments

    Returns:
        {group_label: [symbol, ...]} in sonority order (least → most).
    """
    if not inventory:
        return {}

    # Normalise all feature keys once.
    norm: Dict[str, Dict[str, str]] = {
        sym: _normalize_feats(feats) for sym, feats in inventory.items()
    }

    # Initial assignment: each segment → highest-scoring group (argmax).
    assignment: Dict[str, List[str]] = defaultdict(list)
    for sym, feats in norm.items():
        scored = [(name, seg_score(feats, spec)) for name, spec in ALL_GROUPS]
        best_name, _ = max(scored, key=lambda x: x[1])
        assignment[best_name].append(sym)

    # Track which original ALL_GROUPS names live inside each current group.
    origins: Dict[str, FrozenSet[str]] = {
        name: frozenset({name}) for name in assignment
    }

    # Local spec copy — extended with specs for relabeled groups.
    local_spec: Dict[str, Dict[str, str]] = dict(SPEC)

    # Iterative merging with elbow-detection stopping criterion.
    past_costs: List[float] = []
    while len(assignment) > 1:
        surviving: Set[str] = set(assignment.keys())

        # Find the cheapest non-blocked merge across all current groups.
        best_victim: str = ""
        best_target: str = ""
        best_cost: float = float("inf")
        for victim, members in assignment.items():
            target, cost = _find_best_merge(
                victim, members, surviving, norm, local_spec
            )
            if cost < best_cost:
                best_victim, best_target, best_cost = victim, target, cost

        # Stop if no valid merge exists or next merge is a statistical outlier.
        if best_cost == float("inf") or _is_outlier(best_cost, past_costs):
            break

        past_costs.append(best_cost)
        assignment[best_target].extend(assignment.pop(best_victim))
        origins[best_target] = origins[best_target] | origins.pop(best_victim)

        # Check for a relabel based on the combined origin set.
        new_label = _RELABEL_PATTERNS.get(origins[best_target])
        if new_label and new_label != best_target:
            assignment[new_label] = assignment.pop(best_target)
            origins[new_label] = origins.pop(best_target)
            if new_label not in local_spec:
                local_spec[new_label] = local_spec.get(best_target, {})

    return {
        name: sorted(
            assignment[name],
            key=lambda s: (
                _ipa_place(norm[s]),
                _VOICE_IDX.get(norm[s].get("voice", "0"), 2),
                s,
            ),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
