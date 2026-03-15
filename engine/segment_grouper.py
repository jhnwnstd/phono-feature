"""
engine/segment_grouper.py

Groups an inventory's segments into phonological categories for GUI display
using hierarchical agglomerative clustering on groups.

Groups are initially assigned by argmax feature-spec scoring, then
iteratively merged until the next merge would cost significantly more than
previous merges (elbow / dendrogram-cut stopping criterion).  No hardcoded
group-count targets or minimum-size thresholds.
"""

import math
from collections import defaultdict
from typing import Dict, List, Set, Tuple

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
    # [-consonantal, -syllabic]: glides (j, w) and laryngeals (h, ʔ)
    ("Laryngeals", {"consonantal": "-", "syllabic": "-"}),
    ("Vowels", {"syllabic": "+"}),
]

SPEC: Dict[str, Dict[str, str]] = {name: spec for name, spec in ALL_GROUPS}

# Display order: least sonorous → most sonorous.
# Independent of ALL_GROUPS order (which is by feature-spec specificity).
DISPLAY_ORDER: List[str] = [
    "Clicks",
    "Plosives",
    "Affricates",
    "Lateral Affricates",
    "Sibilants",
    "Fricatives",
    "Lateral Fricatives",
    "Nasals",
    "Trills",
    "Taps & Flaps",
    "Lateral Approximants",
    "Approximants",
    "Laryngeals",
    "Vowels",
]


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
    victim_name: str,
    target_name: str,
    inventory: Dict[str, Dict[str, str]],
) -> float:
    """Drop in mean cohesion when victim's members move to target.

    Higher = worse merge (segments fit target poorly).
    """
    spec_v = SPEC.get(victim_name, {})
    spec_t = SPEC.get(target_name, {})
    if not victims or not spec_v or not spec_t:
        return 1.0
    before = sum(seg_score(inventory[s], spec_v) for s in victims)
    after = sum(seg_score(inventory[s], spec_t) for s in victims)
    return max(0.0, (before - after) / len(victims))


def _is_outlier(new_cost: float, past_costs: List[float]) -> bool:
    """Return True if new_cost is > mean + 1 std of past costs."""
    if len(past_costs) < 1:
        return False
    mean = sum(past_costs) / len(past_costs)
    variance = sum((c - mean) ** 2 for c in past_costs) / len(past_costs)
    std = math.sqrt(variance)
    return new_cost > mean + std


def _find_best_merge(
    victim: str,
    members: List[str],
    surviving: Set[str],
    inventory: Dict[str, Dict[str, str]],
) -> Tuple[str, float]:
    """Find the surviving group that absorbs victim at lowest cohesion cost."""
    candidates = [g for g in surviving if g != victim]
    if not candidates:
        return "", float("inf")
    costs = {g: merge_cost(members, victim, g, inventory) for g in candidates}
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

    # Iterative merging with elbow-detection stopping criterion.
    past_costs: List[float] = []
    while len(assignment) > 1:
        surviving: Set[str] = set(assignment.keys())

        # Find the cheapest merge across all current groups.
        best_victim: str = ""
        best_target: str = ""
        best_cost: float = float("inf")
        for victim, members in assignment.items():
            target, cost = _find_best_merge(victim, members, surviving, norm)
            if cost < best_cost:
                best_victim, best_target, best_cost = victim, target, cost

        # Stop when next merge is a statistical outlier vs. prior merges.
        if _is_outlier(best_cost, past_costs):
            break

        past_costs.append(best_cost)
        assignment[best_target].extend(assignment.pop(best_victim))

    _voice_order = {"-": 0, "+": 1, "0": 2}
    return {
        name: sorted(
            assignment[name],
            key=lambda s: (_voice_order.get(norm[s].get("voice", "0"), 2), s),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
