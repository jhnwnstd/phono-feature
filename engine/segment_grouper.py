"""
engine/segment_grouper.py

Groups an inventory's segments into phonological categories for GUI display
using discrete membership testing and specificity-based assignment.

Each segment is tested against every group's defining spec with a hard
boolean membership test (exact match required, inapplicable features
treated as compatible).  The segment is assigned to the *most specific*
group it qualifies for — the one with the most testable features in its
spec.

Features absent from the inventory entirely (no segment carries a non-zero
value) are distinguished from features inapplicable to a particular
segment (value "0").  Absent features are skipped during membership
testing; inapplicable features are treated as compatible.

After initial assignment, singleton / very small groups are merged upward
through the specificity hierarchy: each member moves to its next-best
matching group until all groups meet a minimum size or no further parent
exists.  Plosives are frozen after initial assignment.

Combined groups are checked against _RELABEL_PATTERNS and renamed when
they match a known phonological class (Vibrants, Rhotics, Liquids).
"""

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
            "tap": "-",
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
    # Lateral Approximants + Taps (no Trills/Approximants in inventory)
    frozenset({"Lateral Approximants", "Taps & Flaps"}): "Liquids",
    # Lateral Approximants + Trills (no Taps/Approximants in inventory)
    frozenset({"Lateral Approximants", "Trills"}): "Liquids",
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
_FEAT_IDX: Dict[str, int] = {"-": 0, "+": 1, "0": 2}


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
# Main grouping function
# ---------------------------------------------------------------------------

# Groups frozen after initial assignment: never dissolve, never accept
# overflow from singleton merging.
_FROZEN_GROUPS: Set[str] = {"Plosives", "Laryngeals"}


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to display on its own.

    A group needs at least ~5% of the inventory OR at least 3 segments,
    whichever is larger — so small inventories get more aggressive merging
    and large inventories preserve more fine-grained distinctions.
    """
    min_absolute = 3
    min_relative = max(min_absolute, int(inventory_size * 0.05))
    return group_size < min_relative


def group_segments(
    inventory: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Assign every segment to a phonological display group.

    Uses discrete membership testing:

    1. **Feature detection** — identify which features are active in the
       inventory (at least one segment carries a non-zero value).

    2. **Hard membership** — a segment qualifies for a group if every
       spec feature *present in the inventory* either matches exactly or
       is inapplicable ("0") to the segment.  Spec features absent from
       the inventory are skipped (the group is only testable on features
       the data actually provides).

    3. **Specificity assignment** — each segment is placed in the most
       specific matching group (the one with the most testable features).
       Segments matching no group fall back to fewest-contradictions.

    4. **Singleton merging** — groups smaller than _MIN_GROUP_SIZE have
       their members moved to each member's next-best group in its
       membership chain.  _FROZEN_GROUPS are exempt.

    5. **Relabeling** — combined groups are checked against
       _RELABEL_PATTERNS and renamed (e.g. Trills + Taps → Vibrants).

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

    # ---- Step 0: Detect features active in this inventory ----

    active_features: Set[str] = set()
    for feats in norm.values():
        for k, v in feats.items():
            if v != "0":
                active_features.add(k)

    # ---- Helpers ----

    def is_member(seg_feats: Dict[str, str], spec: Dict[str, str]) -> bool:
        """True if segment satisfies all spec features present in inventory."""
        relevant = [f for f in spec if f in active_features]
        if not relevant:
            return False  # spec has no testable features in this inventory
        for feat in relevant:
            val = seg_feats.get(feat, "0")
            if val == "0":
                continue  # inapplicable: compatible
            if val != spec[feat]:
                return False  # contradiction: excluded
        return True

    def specificity(spec: Dict[str, str]) -> int:
        """Count of spec features present in inventory."""
        return sum(1 for f in spec if f in active_features)

    def membership_chain(seg_feats: Dict[str, str]) -> List[str]:
        """All matching groups, most specific first."""
        matches = [
            (name, specificity(spec))
            for name, spec in ALL_GROUPS
            if is_member(seg_feats, spec)
        ]
        matches.sort(key=lambda x: -x[1])
        return [name for name, _ in matches]

    def fallback_assignment(seg_feats: Dict[str, str]) -> str:
        """For segments matching no group: fewest contradictions wins."""
        best_name = ""
        best_contras = float("inf")
        best_matches = -1
        for name, spec in ALL_GROUPS:
            if name in _FROZEN_GROUPS:
                continue  # fallback never assigns to frozen groups
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

    # ---- Step 1: Assign to most specific matching group ----

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

    # Record each segment's initial group for origin tracking.
    initial_group: Dict[str, str] = {}
    for gname, members in assignment.items():
        for sym in members:
            initial_group[sym] = gname

    # ---- Step 2: Merge small groups upward ----
    # Members of small groups move to their next-best group in the
    # membership chain.  Only principled moves (the segment actually
    # qualifies for the parent group) are made.

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
                    (c for c in chain
                     if c != gname
                     and c in assignment
                     and c not in _FROZEN_GROUPS),
                    None,
                )
                if parent is not None:
                    assignment[gname].remove(sym)
                    assignment[parent].append(sym)
                    changed = True
            if not assignment[gname]:
                del assignment[gname]

    # ---- Step 2b: Merge related singletons via relabel patterns ----
    # If two small groups are both present and their combination matches
    # a _RELABEL_PATTERNS entry, merge them under the derived label.
    # This handles cases like singleton Taps + singleton Laterals → Liquids
    # where neither segment has the other's group in its membership chain.

    for origin_set, new_label in _RELABEL_PATTERNS.items():
        present = [g for g in origin_set if g in assignment]
        if len(present) < 2:
            continue
        # Only merge if ALL participating groups are small.
        if any(not _should_merge_up(len(assignment[g]), len(inventory)) for g in present):
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        # Pick the first present group as the merge target, then relabel.
        target = present[0]
        for g in present[1:]:
            assignment[target].extend(assignment.pop(g))
        assignment[new_label] = assignment.pop(target)

    # ---- Step 3: Relabeling ----

    for gname in list(assignment.keys()):
        origin_set = frozenset(initial_group[sym] for sym in assignment[gname])
        new_label = _RELABEL_PATTERNS.get(origin_set)
        if new_label and new_label != gname:
            assignment[new_label] = assignment.pop(gname)

    # ---- Step 3b: Merge derived groups that belong together ----
    # After relabeling, Vibrants and Liquids may coexist when the two
    # halves of "Rhotics" ended up in different derived groups.  If either
    # is below threshold, combine them under Liquids.

    _DERIVED_MERGES: List[Tuple[FrozenSet[str], str]] = [
        (frozenset({"Vibrants", "Liquids"}), "Liquids"),
        (frozenset({"Vibrants", "Lateral Approximants"}), "Liquids"),
        (frozenset({"Rhotics", "Lateral Approximants"}), "Liquids"),
    ]
    for pair, label in _DERIVED_MERGES:
        present = [g for g in pair if g in assignment]
        if len(present) < 2:
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        # Merge if at least one participating group is below threshold.
        if not any(
            _should_merge_up(len(assignment[g]), len(inventory))
            for g in present
        ):
            continue
        target = present[0]
        for g in present[1:]:
            assignment[target].extend(assignment.pop(g))
        if label != target:
            assignment[label] = assignment.pop(target)

    # ---- Step 4: Sort by display order and IPA place ----

    return {
        name: sorted(
            assignment[name],
            key=lambda s: (
                _ipa_place(norm[s]),
                _FEAT_IDX.get(norm[s].get("lateral", "0"), 2),
                _FEAT_IDX.get(norm[s].get("strident", "0"), 2),
                _VOICE_IDX.get(norm[s].get("voice", "0"), 2),
                s,
            ),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
