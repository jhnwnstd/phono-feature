"""Segment grouper: assigns inventory segments to phonological display groups.

Architecture:
  1. Primary assignment into broad manner classes (Plosives, Fricatives,
     Affricates, Nasals, etc.) using only the most universal features.
  2. Derived breakouts split subgroups (Sibilants, Lateral Fricatives,
     Lateral Affricates) out of their parent class — only when the
     inventory supports the relevant features and enough segments qualify.
  3. Small-group merging collapses tiny groups into their explicit parent.
  4. Relabeling combines related groups (Vibrants, Rhotics, Liquids).
  5. Laryngeal rescue peels placeless spreadgl/constrgl segments into a
     dedicated Laryngeals class.

Heuristic notes:
- Fallback assignment is order-sensitive on ties: when two classes have
  the same contradiction and match counts, the earlier class in
  PRIMARY_GROUPS wins as a final tie-break.
- Minimum positive-match thresholds prevent underspecified segments
  from qualifying for classes they barely evidence.
"""

from collections import defaultdict
from typing import Dict, FrozenSet, List, Set, Tuple

# ---------------------------------------------------------------------------
# Primary groups — broad manner classes for initial assignment.
# Only uses the most universal, stable features.
# ---------------------------------------------------------------------------

PRIMARY_GROUPS: List[Tuple[str, Dict[str, str]]] = [
    ("Clicks", {"click": "+"}),
    (
        "Affricates",
        {
            "consonantal": "+",
            "delrel": "+",
            "continuant": "-",
            "sonorant": "-",
        },
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
        "Fricatives",
        {"consonantal": "+", "continuant": "+", "sonorant": "-"},
    ),
    ("Nasals", {"nasal": "+"}),
    ("Trills", {"trill": "+"}),
    ("Taps & Flaps", {"tap": "+"}),
    (
        "Lateral Approximants",
        {
            "consonantal": "+",
            "continuant": "+",
            "lateral": "+",
            "sonorant": "+",
            "tap": "-",
        },
    ),
    (
        "Central Approximants",
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
    (
        "Semivowels",
        {"consonantal": "-", "syllabic": "-", "sonorant": "+"},
    ),
    ("Vowels", {"syllabic": "+"}),
]

# Minimum positive feature matches required for membership.
# Prevents underspecified segments from qualifying on one lucky match.
_MIN_POSITIVE: Dict[str, int] = {
    "Plosives": 2,
    "Fricatives": 2,
    "Affricates": 2,
    "Lateral Approximants": 2,
    "Central Approximants": 2,
    "Semivowels": 2,
}

# ---------------------------------------------------------------------------
# Derived breakouts — split from a parent class after initial assignment.
# Only surfaced when the feature is active and enough segments qualify.
# (new_name, parent_name, extra_conditions)
# ---------------------------------------------------------------------------

DERIVED_BREAKOUTS: List[Tuple[str, str, Dict[str, str]]] = [
    ("Sibilants", "Fricatives", {"strident": "+", "coronal": "+"}),
    ("Lateral Fricatives", "Fricatives", {"lateral": "+"}),
    ("Lateral Affricates", "Affricates", {"lateral": "+"}),
]

# ---------------------------------------------------------------------------
# Explicit parent map for upward merging of small groups.
# When a group is too small, its members merge into this parent.
# ---------------------------------------------------------------------------

_MERGE_PARENT: Dict[str, str] = {
    "Lateral Affricates": "Affricates",
    "Sibilants": "Fricatives",
    "Lateral Fricatives": "Fricatives",
    "Trills": "Central Approximants",
    "Taps & Flaps": "Central Approximants",
}

# Groups exempt from upward merging.  Laryngeal rescue (Step 5) can still
# peel individual segments out.
_FROZEN_GROUPS: Set[str] = {"Plosives"}

# ---------------------------------------------------------------------------
# Display order: obstruents → sonorants → vowels
# ---------------------------------------------------------------------------

DISPLAY_ORDER: List[str] = [
    "Clicks",
    "Plosives",
    "Affricates",
    "Lateral Affricates",
    "Sibilants",
    "Fricatives",
    "Lateral Fricatives",
    "Nasals",
    "Vibrants",
    "Trills",
    "Taps & Flaps",
    "Rhotics",
    "Lateral Approximants",
    "Liquids",
    "Central Approximants",
    "Semivowels",
    "Laryngeals",
    "Vowels",
]

# ---------------------------------------------------------------------------
# Relabeling: frozenset of origin names → derived display label
# ---------------------------------------------------------------------------

_RELABEL_PATTERNS: Dict[FrozenSet[str], str] = {
    frozenset({"Trills", "Taps & Flaps"}): "Vibrants",
    frozenset({"Trills", "Central Approximants"}): "Rhotics",
    frozenset({"Taps & Flaps", "Central Approximants"}): "Rhotics",
    frozenset({"Trills", "Taps & Flaps", "Central Approximants"}): "Rhotics",
    frozenset({"Lateral Approximants", "Central Approximants"}): "Liquids",
    frozenset(
        {"Lateral Approximants", "Central Approximants", "Trills"}
    ): "Liquids",
    frozenset(
        {"Lateral Approximants", "Central Approximants", "Taps & Flaps"}
    ): "Liquids",
    frozenset(
        {
            "Lateral Approximants",
            "Central Approximants",
            "Trills",
            "Taps & Flaps",
        }
    ): "Liquids",
    frozenset({"Lateral Approximants", "Trills", "Taps & Flaps"}): "Liquids",
    frozenset({"Lateral Approximants", "Taps & Flaps"}): "Liquids",
    frozenset({"Lateral Approximants", "Trills"}): "Liquids",
}

_DERIVED_MERGES: List[Tuple[FrozenSet[str], str]] = [
    (frozenset({"Vibrants", "Liquids"}), "Liquids"),
    (frozenset({"Vibrants", "Lateral Approximants"}), "Liquids"),
    (frozenset({"Rhotics", "Lateral Approximants"}), "Liquids"),
]


# ---------------------------------------------------------------------------
# Key normalisation
# ---------------------------------------------------------------------------


def _normalize_key(key: str) -> str:
    """Normalise a feature name to a canonical lowercase token."""
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
# IPA place ordering (left → right on the IPA chart)
# ---------------------------------------------------------------------------

_VAL_ORD: Dict[str, int] = {"-": 0, "+": 1, "0": 2}

_SORT_KEYS: List[Tuple[str, Dict[str, int]]] = [
    ("sonorant", _VAL_ORD),
    ("lateral", _VAL_ORD),
    ("strident", _VAL_ORD),
    ("nasal", _VAL_ORD),
    ("continuant", _VAL_ORD),
    ("delrel", _VAL_ORD),
    ("front", {"+": 0, "-": 1, "0": 2}),
    ("back", _VAL_ORD),
    ("labial", _VAL_ORD),
    ("voice", {"-": 0, "+": 1, "0": 2}),
    ("spreadgl", _VAL_ORD),
    ("constrgl", _VAL_ORD),
    ("round", _VAL_ORD),
    ("high", {"+": 0, "-": 1, "0": 2}),
    ("low", _VAL_ORD),
    ("tense", _VAL_ORD),
    ("long", _VAL_ORD),
]


def _segment_sort_key(feats: Dict[str, str]) -> tuple:
    """Full feature-based sort key for a segment."""
    key: list = [_ipa_place(feats)]
    for feat, ordering in _SORT_KEYS:
        key.append(ordering.get(feats.get(feat, "0"), 2))
    return tuple(key)


def _ipa_place(feats: Dict[str, str]) -> int:
    """Return 0-11 index for IPA place of articulation."""
    if feats.get("constrgl", "0") == "+":
        return 10  # glottal

    if (
        feats.get("constrpharynx", "0") == "+"
        or feats.get("pharyngeal", "0") == "+"
    ):
        return 9  # pharyngeal

    dor = feats.get("dorsal", "0")
    if dor == "+":
        hi = feats.get("high", "0")
        bk = feats.get("back", "0")
        if hi == "-":
            return 8  # uvular
        if bk == "-":
            if feats.get("anterior", "0") == "-":
                return 6  # palatal
            return 7  # velar (incl. advanced)
        return 7  # velar

    cor = feats.get("coronal", "0")
    if cor == "+":
        ant = feats.get("anterior", "0")
        dist = feats.get("distributed", "0")
        if ant == "-":
            return 5 if dist == "-" else 4  # retroflex / postalveolar
        return 2 if dist == "+" else 3  # dental / alveolar

    lab = feats.get("labial", "0")
    if lab == "+":
        return 1 if feats.get("labiodental", "0") == "+" else 0

    if (
        feats.get("consonantal", "0") == "-"
        and feats.get("syllabic", "0") == "-"
    ):
        return 10  # h, ɦ

    return 11  # vowels / unclassified


# ---------------------------------------------------------------------------
# Main grouping function
# ---------------------------------------------------------------------------


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to display on its own."""
    return group_size < max(3, int(inventory_size * 0.05))


def _should_break_out(subgroup_size: int, inventory_size: int) -> bool:
    """True if a derived subgroup is large enough to display separately."""
    return subgroup_size >= max(3, int(inventory_size * 0.04))


def group_segments(
    inventory: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Assign every segment to a phonological display group.

    Returns {group_label: [symbol, ...]} in display order.
    """
    if not inventory:
        return {}

    norm: Dict[str, Dict[str, str]] = {
        sym: _normalize_feats(feats) for sym, feats in inventory.items()
    }

    # Step 0: Detect features active in this inventory.
    active_features: Set[str] = set()
    for feats in norm.values():
        for k, v in feats.items():
            if v != "0":
                active_features.add(k)

    # -- Helpers --

    def _positive_matches(
        seg_feats: Dict[str, str], spec: Dict[str, str]
    ) -> int:
        """Count features where the segment has an explicit matching value."""
        return sum(
            1
            for f in spec
            if f in active_features
            and seg_feats.get(f, "0") != "0"
            and seg_feats.get(f, "0") == spec[f]
        )

    def is_member(
        group_name: str, seg_feats: Dict[str, str], spec: Dict[str, str]
    ) -> bool:
        """Test membership with minimum-evidence threshold."""
        relevant = [f for f in spec if f in active_features]
        if not relevant:
            return False
        matched = 0
        for feat in relevant:
            val = seg_feats.get(feat, "0")
            if val == "0":
                continue
            if val != spec[feat]:
                return False
            matched += 1
        return matched >= _MIN_POSITIVE.get(group_name, 1)

    def best_primary(seg_feats: Dict[str, str]) -> str:
        """Find the best primary group by positive evidence, then specificity."""
        matches = [
            (
                name,
                _positive_matches(seg_feats, spec),
                sum(1 for f in spec if f in active_features),
            )
            for name, spec in PRIMARY_GROUPS
            if is_member(name, seg_feats, spec)
        ]
        if not matches:
            return ""
        matches.sort(key=lambda x: (-x[1], -x[2]))
        return matches[0][0]

    def fallback_assignment(seg_feats: Dict[str, str]) -> str:
        """Best-fit group by fewest contradictions, then most matches.

        On equal contradiction and match counts, the earlier group in
        PRIMARY_GROUPS wins as a final tie-break.
        """
        best_name = ""
        best_contras = float("inf")
        best_matches = -1
        for name, spec in PRIMARY_GROUPS:
            if name in _FROZEN_GROUPS:
                continue
            relevant = [f for f in spec if f in active_features]
            if not relevant:
                continue
            contras = 0
            matched = 0
            for feat in relevant:
                val = seg_feats.get(feat, "0")
                if val == "0":
                    continue
                if val == spec[feat]:
                    matched += 1
                else:
                    contras += 1
            if contras < best_contras or (
                contras == best_contras and matched > best_matches
            ):
                best_name, best_contras, best_matches = (
                    name,
                    contras,
                    matched,
                )
        return best_name

    # ==================================================================
    # Step 1: Assign to broad manner classes only.
    # ==================================================================
    assignment: Dict[str, List[str]] = defaultdict(list)

    for sym, feats in norm.items():
        group = best_primary(feats)
        if not group:
            group = fallback_assignment(feats)
        if group:
            assignment[group].append(sym)

    # ==================================================================
    # Step 2: Derived breakouts — split subgroups from parent classes.
    # Only when the feature is active and enough segments qualify.
    # ==================================================================
    for new_name, parent_name, cond in DERIVED_BREAKOUTS:
        if parent_name not in assignment:
            continue
        if not all(f in active_features for f in cond):
            continue

        subgroup = [
            s
            for s in assignment[parent_name]
            if all(norm[s].get(f, "0") == v for f, v in cond.items())
        ]
        if not subgroup:
            continue
        if not _should_break_out(len(subgroup), len(inventory)):
            continue

        for s in subgroup:
            assignment[parent_name].remove(s)
        assignment[new_name] = subgroup
        if not assignment[parent_name]:
            del assignment[parent_name]

    # ==================================================================
    # Step 3: Merge small groups into their explicit parent.
    # ==================================================================
    changed = True
    while changed:
        changed = False
        for gname in list(assignment.keys()):
            if gname in _FROZEN_GROUPS:
                continue
            if not _should_merge_up(len(assignment[gname]), len(inventory)):
                continue
            parent = _MERGE_PARENT.get(gname)
            if parent is not None and parent in assignment:
                assignment[parent].extend(assignment.pop(gname))
                changed = True

    # ==================================================================
    # Step 4: Relabel combined groups (Vibrants, Rhotics, Liquids).
    # ==================================================================

    # 4a: Merge small groups that match a relabel pattern.
    for origin_set, new_label in _RELABEL_PATTERNS.items():
        present = [g for g in origin_set if g in assignment]
        if len(present) < 2:
            continue
        if any(
            not _should_merge_up(len(assignment[g]), len(inventory))
            for g in present
        ):
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        merged: List[str] = []
        for g in present:
            merged.extend(assignment.pop(g))
        assignment.setdefault(new_label, []).extend(merged)

    # 4b: Relabel groups whose composition matches a known class.
    initial_group: Dict[str, str] = {}
    for gname, members in assignment.items():
        for sym in members:
            initial_group[sym] = gname

    for gname in list(assignment.keys()):
        if gname not in assignment:
            continue
        origin_set = frozenset(
            initial_group.get(sym, gname) for sym in assignment[gname]
        )
        relabel = _RELABEL_PATTERNS.get(origin_set)
        if relabel is not None and relabel != gname:
            members = assignment.pop(gname)
            assignment.setdefault(relabel, []).extend(members)

    # 4c: Merge derived groups that belong together.
    for pair, label in _DERIVED_MERGES:
        present = [g for g in pair if g in assignment]
        if len(present) < 2:
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        if not any(
            _should_merge_up(len(assignment[g]), len(inventory))
            for g in present
        ):
            continue
        merged = []
        for g in present:
            merged.extend(assignment.pop(g))
        assignment.setdefault(label, []).extend(merged)

    # ==================================================================
    # Step 5: Laryngeal rescue — peel placeless consonantal segments
    # with spreadgl:+ or constrgl:+ into Laryngeals.
    # ==================================================================
    _LARYNGEAL_FEATURES = {"spreadgl", "constrgl"}
    _PLACE_FEATURES = {
        "labial",
        "coronal",
        "dorsal",
        "pharyngeal",
        "constrpharynx",
    }

    def _is_laryngeal_candidate(feats: Dict[str, str]) -> bool:
        has_laryngeal = any(
            feats.get(f, "0") == "+" for f in _LARYNGEAL_FEATURES
        )
        has_place = any(feats.get(f, "0") == "+" for f in _PLACE_FEATURES)
        is_vowel = feats.get("syllabic", "0") == "+"
        is_click = feats.get("click", "0") == "+"
        return (
            has_laryngeal and not has_place and not is_vowel and not is_click
        )

    if _LARYNGEAL_FEATURES & active_features:
        laryngeal_segs: List[str] = []
        for gname in list(assignment.keys()):
            if gname == "Laryngeals":
                continue
            peeled = [
                sym
                for sym in assignment[gname]
                if _is_laryngeal_candidate(norm[sym])
            ]
            if peeled:
                for sym in peeled:
                    assignment[gname].remove(sym)
                laryngeal_segs.extend(peeled)
                if not assignment[gname]:
                    del assignment[gname]
        if laryngeal_segs:
            assignment.setdefault("Laryngeals", []).extend(laryngeal_segs)

    # ==================================================================
    # Step 6: Sort by display order and feature-based key.
    # ==================================================================
    return {
        name: sorted(
            assignment[name],
            key=lambda s: _segment_sort_key(norm[s]),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
