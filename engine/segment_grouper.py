"""Segment grouper: assigns inventory segments to phonological display groups.

Uses discrete membership testing with specificity-based assignment.
Absent inventory features are skipped; inapplicable segment values ("0")
are treated as compatible.  Small groups merge upward through the
specificity hierarchy.  Combined groups are relabeled when they match
known phonological classes (Vibrants, Rhotics, Liquids).

Heuristic notes:
- Fallback assignment is order-sensitive on ties: when two classes have
  the same contradiction and match counts, the earlier class in ALL_GROUPS
  wins.  This is intentional — taxonomy ordering encodes specificity
  priority.
- Laryngeal rescue (Step 3c) scans all groups, not just Semivowels,
  to catch placeless spreadgl/constrgl segments wherever they landed.
- Underspecified segments ("0" on most features) can qualify for specific
  classes if they don't contradict. The matched_any guard prevents pure-
  zero membership, but a segment with just one matching feature can still
  land in a highly specific class.
"""

from collections import defaultdict
from typing import Dict, FrozenSet, List, Set, Tuple

# ---------------------------------------------------------------------------
# Group taxonomy — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

ALL_GROUPS: List[Tuple[str, Dict[str, str]]] = [
    ("Clicks", {"click": "+"}),
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
            "tap": "-",
        },
    ),
    ("Trills", {"trill": "+"}),
    ("Taps & Flaps", {"tap": "+"}),
    ("Nasals", {"nasal": "+"}),
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
    # Laryngeals is NOT a primary group — it is populated by the global
    # laryngeal rescue (Step 3c) which peels placeless spreadgl/constrgl
    # segments out of whatever group they initially landed in.
    ("Vowels", {"syllabic": "+"}),
]

# Display order: least sonorous -> most sonorous.
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
# Merge relabeling: frozenset of origin names -> derived label
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

# Post-relabel merges for derived groups that belong together.
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
# IPA place ordering (left -> right on the IPA chart)
# ---------------------------------------------------------------------------

_VAL_ORD: Dict[str, int] = {"-": 0, "+": 1, "0": 2}

# Feature-based sort order for segments within a group.
# Tuple of (feature_name, value_ordering) pairs applied in sequence.
# value_ordering maps feature values to sort indices.
_SORT_KEYS: List[Tuple[str, Dict[str, int]]] = [
    # 1. Place of articulation (handled by _ipa_place, prepended separately)
    # 2. Manner sub-features within same place
    ("sonorant", _VAL_ORD),  # obstruents before sonorants
    ("lateral", _VAL_ORD),  # non-lateral before lateral
    ("strident", _VAL_ORD),  # non-strident before strident
    ("nasal", _VAL_ORD),  # oral before nasal
    ("continuant", _VAL_ORD),  # stops before fricatives
    ("delrel", _VAL_ORD),  # non-affricate before affricate
    # 3. Sub-place refinement: keeps fronted/retracted/plain variants together
    ("front", {"+": 0, "-": 1, "0": 2}),
    ("back", _VAL_ORD),
    ("labial", _VAL_ORD),  # plain before labial-coarticulated (k before k͡p)
    # 4. Laryngeal: voicing pairs adjacent at each sub-place
    ("voice", {"-": 0, "+": 1, "0": 2}),
    ("spreadgl", _VAL_ORD),  # plain before aspirated
    ("constrgl", _VAL_ORD),  # plain before ejective
    # 5. Secondary articulations
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
            # True palatals (c, ɉ) have anterior:-;
            # advanced velars (k+, ɡ+) have anterior:0.
            if feats.get("anterior", "0") == "-":
                return 6  # palatal
            return 7  # advanced velar → groups with plain velars
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

_FROZEN_GROUPS: Set[str] = {"Plosives"}


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to display on its own."""
    return group_size < max(3, int(inventory_size * 0.05))


def group_segments(
    inventory: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Assign every segment to a phonological display group.

    Returns {group_label: [symbol, ...]} in sonority order.
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

    def is_member(seg_feats: Dict[str, str], spec: Dict[str, str]) -> bool:
        relevant = [f for f in spec if f in active_features]
        if not relevant:
            return False
        matched_any = False
        for feat in relevant:
            val = seg_feats.get(feat, "0")
            if val == "0":
                continue
            if val != spec[feat]:
                return False
            matched_any = True
        return matched_any

    def specificity(spec: Dict[str, str]) -> int:
        return sum(1 for f in spec if f in active_features)

    def membership_chain(seg_feats: Dict[str, str]) -> List[str]:
        matches = [
            (name, specificity(spec))
            for name, spec in ALL_GROUPS
            if is_member(seg_feats, spec)
        ]
        matches.sort(key=lambda x: -x[1])
        return [name for name, _ in matches]

    def fallback_assignment(seg_feats: Dict[str, str]) -> str:
        """Best-fit group by fewest contradictions, then most matches.

        On ties, the earlier group in ALL_GROUPS wins — this is intentional
        as taxonomy ordering encodes specificity priority.
        """
        best_name = ""
        best_contras = float("inf")
        best_matches = -1
        for name, spec in ALL_GROUPS:
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
                best_name, best_contras, best_matches = name, contras, matched
        return best_name

    # Step 1: Assign to most specific matching group.
    assignment: Dict[str, List[str]] = defaultdict(list)
    chains: Dict[str, List[str]] = {}

    for sym, feats in norm.items():
        chain = membership_chain(feats)
        if chain:
            assignment[chain[0]].append(sym)
            chains[sym] = chain
        else:
            fb = fallback_assignment(feats)
            if fb:
                assignment[fb].append(sym)
            chains[sym] = [fb] if fb else []

    initial_group: Dict[str, str] = {}
    for gname, members in assignment.items():
        for sym in members:
            initial_group[sym] = gname

    # Step 2: Merge small groups upward through membership chains.
    changed = True
    while changed:
        changed = False
        for gname in list(assignment.keys()):
            if gname in _FROZEN_GROUPS:
                continue
            if not _should_merge_up(len(assignment[gname]), len(inventory)):
                continue
            for sym in list(assignment[gname]):
                chain = chains.get(sym, [])
                parent = next(
                    (
                        c
                        for c in chain
                        if c != gname
                        and c in assignment
                        and c not in _FROZEN_GROUPS
                    ),
                    None,
                )
                if parent is not None:
                    assignment[gname].remove(sym)
                    assignment[parent].append(sym)
                    changed = True
            if not assignment[gname]:
                del assignment[gname]

    # Step 2b: Merge small groups that match a relabel pattern.
    # Uses setdefault+extend to avoid overwriting an existing group.
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

    # Step 3: Relabel groups whose origin set matches a known class.
    for gname in list(assignment.keys()):
        if gname not in assignment:
            continue
        origin_set = frozenset(initial_group[sym] for sym in assignment[gname])
        relabel: str | None = _RELABEL_PATTERNS.get(origin_set)
        if relabel is not None and relabel != gname:
            members = assignment.pop(gname)
            assignment.setdefault(relabel, []).extend(members)

    # Step 3b: Merge derived groups that belong together.
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

    # Step 3c: Global laryngeal rescue — peel placeless segments with
    # spreadgl:+ or constrgl:+ out of ANY group into Laryngeals.
    # This catches h/ɦ/ʔ regardless of where they initially landed
    # (Semivowels, Fricatives, etc.).
    _LARYNGEAL_FEATURES = {"spreadgl", "constrgl"}
    _PLACE_FEATURES = {"labial", "coronal", "dorsal", "pharyngeal"}
    if _LARYNGEAL_FEATURES & active_features:
        laryngeal_segs: List[str] = []
        for gname in list(assignment.keys()):
            if gname == "Laryngeals":
                continue
            peeled = [
                sym
                for sym in assignment[gname]
                if any(
                    norm[sym].get(f, "0") == "+" for f in _LARYNGEAL_FEATURES
                )
                and not any(
                    norm[sym].get(f, "0") == "+" for f in _PLACE_FEATURES
                )
            ]
            if peeled:
                for sym in peeled:
                    assignment[gname].remove(sym)
                laryngeal_segs.extend(peeled)
                if not assignment[gname]:
                    del assignment[gname]
        if laryngeal_segs:
            assignment.setdefault("Laryngeals", []).extend(laryngeal_segs)

    # Step 4: Sort by display order and feature-based key.
    return {
        name: sorted(
            assignment[name],
            key=lambda s: _segment_sort_key(norm[s]),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
