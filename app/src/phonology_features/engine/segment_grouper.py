"""Assign inventory segments to phonological display groups.

Pipeline: primary manner-class assignment, derived breakouts (e.g.
Sibilants from Fricatives), relational relabeling (Rhotics, Liquids),
small-group merging, laryngeal rescue, then sort. Each step is keyed to
the active feature set so inventories that lack a feature skip the
related step.
"""

from collections import defaultdict
from functools import lru_cache

# Broad manner classes for the initial assignment pass. Specs use only
# universal features so they apply across diverse inventories.
PRIMARY_GROUPS: list[tuple[str, dict[str, str]]] = [
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
# Minimum positive matches required for membership; prevents barely
# specified segments from qualifying for classes by default.
_MIN_POSITIVE: dict[str, int] = {
    "Plosives": 2,
    "Fricatives": 2,
    "Affricates": 2,
    "Lateral Approximants": 2,
    "Central Approximants": 2,
    "Semivowels": 2,
}
DERIVED_BREAKOUTS: list[tuple[str, str, dict[str, str]]] = [
    ("Sibilants", "Fricatives", {"strident": "+", "coronal": "+"}),
    ("Lateral Fricatives", "Fricatives", {"lateral": "+"}),
    ("Lateral Affricates", "Affricates", {"lateral": "+"}),
]
_MERGE_PARENT: dict[str, str] = {
    "Lateral Affricates": "Affricates",
    "Sibilants": "Fricatives",
    "Lateral Fricatives": "Fricatives",
    "Trills": "Central Approximants",
    "Taps & Flaps": "Central Approximants",
}
# Exempt from upward merging; laryngeal rescue can still peel members.
_FROZEN_GROUPS: set[str] = {"Plosives"}
DISPLAY_ORDER: list[str] = [
    "Clicks",
    "Plosives",
    "Fricatives",
    "Sibilants",
    "Lateral Fricatives",
    "Affricates",
    "Lateral Affricates",
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
# Origin-set -> display label for relational relabeling.
_RELABEL_PATTERNS: dict[frozenset[str], str] = {
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
_DERIVED_MERGES: list[tuple[frozenset[str], str]] = [
    (frozenset({"Vibrants", "Liquids"}), "Liquids"),
    (frozenset({"Vibrants", "Lateral Approximants"}), "Liquids"),
    (frozenset({"Rhotics", "Lateral Approximants"}), "Liquids"),
]


@lru_cache(maxsize=512)
def _normalize_key(key: str) -> str:
    """Normalise a feature name to a canonical lowercase token.

    Memoized because the same handful of feature names are reused
    across all segments and inventory reloads; the cache turns
    thousands of calls per load into one per unique name.
    """
    k = key.lower()
    k = k.replace("del.rel.", "delrel")
    k = k.replace("delayed_release", "delrel")
    k = k.replace("s.g.", "spreadgl")
    k = k.replace("c.g.", "constrgl")
    return k.replace(".", "").replace("_", "").replace(" ", "")


def _normalize_feats(feat_dict: dict[str, str]) -> dict[str, str]:
    return {_normalize_key(k): v for k, v in feat_dict.items()}


_VAL_ORD: dict[str, int] = {"-": 0, "+": 1, "0": 2}
_SORT_KEYS: list[tuple[str, dict[str, int]]] = [
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


def _segment_sort_key(feats: dict[str, str]) -> tuple:
    """Full feature-based sort key for a segment."""
    key: list = [_ipa_place(feats)]
    for feat, ordering in _SORT_KEYS:
        key.append(ordering.get(feats.get(feat, "0"), 2))
    return tuple(key)


def _ipa_place(feats: dict[str, str]) -> int:
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
        return 10  # h, ɦ (voiced glottal fricative)
    return 11  # vowels / unclassified


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to stand alone in the display."""
    return group_size < max(3, int(inventory_size * 0.05))


def _should_break_out(subgroup_size: int, inventory_size: int) -> bool:
    """True if a derived subgroup is large enough to display separately.

    At least as strict as ``_should_merge_up`` to prevent
    create-then-destroy churn.
    """
    return subgroup_size >= max(3, int(inventory_size * 0.05))


_LARYNGEAL_FEATURES: set[str] = {"spreadgl", "constrgl"}
_PLACE_FEATURES: set[str] = {
    "labial",
    "coronal",
    "dorsal",
    "pharyngeal",
    "constrpharynx",
}


def _is_laryngeal_candidate(feats: dict[str, str]) -> bool:
    has_laryngeal = any(feats.get(f, "0") == "+" for f in _LARYNGEAL_FEATURES)
    has_place = any(feats.get(f, "0") == "+" for f in _PLACE_FEATURES)
    is_vowel = feats.get("syllabic", "0") == "+"
    is_click = feats.get("click", "0") == "+"
    return has_laryngeal and not has_place and not is_vowel and not is_click


def group_segments(
    inventory: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """Assign every segment to a phonological display group.

    Returns ``{group_label: [symbol, ...]}`` in ``DISPLAY_ORDER``.
    """
    if not inventory:
        return {}
    norm: dict[str, dict[str, str]] = {
        sym: _normalize_feats(feats) for sym, feats in inventory.items()
    }
    active_features: set[str] = set()
    for feats in norm.values():
        for k, v in feats.items():
            if v != "0":
                active_features.add(k)

    def positive_matches(
        seg_feats: dict[str, str], spec: dict[str, str]
    ) -> int:
        return sum(
            1
            for f in spec
            if f in active_features
            and seg_feats.get(f, "0") != "0"
            and seg_feats.get(f, "0") == spec[f]
        )

    def is_member(
        group_name: str, seg_feats: dict[str, str], spec: dict[str, str]
    ) -> bool:
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

    def best_primary(seg_feats: dict[str, str]) -> str:
        """Best primary group by positive evidence, then specificity.

        ``click:+`` always wins regardless of how many other features
        match broader obstruent classes.
        """
        if seg_feats.get("click", "0") == "+":
            return "Clicks"
        matches = [
            (
                name,
                positive_matches(seg_feats, spec),
                sum(1 for f in spec if f in active_features),
            )
            for name, spec in PRIMARY_GROUPS
            if is_member(name, seg_feats, spec)
        ]
        if not matches:
            return ""
        matches.sort(key=lambda x: (-x[1], -x[2]))
        return matches[0][0]

    def fallback_assignment(seg_feats: dict[str, str]) -> str:
        """Best-fit group by fewest contradictions, then most matches.

        On ties the earlier group in ``PRIMARY_GROUPS`` wins.
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
                best_name, best_contras, best_matches = name, contras, matched
        return best_name

    assignment: dict[str, list[str]] = defaultdict(list)
    for sym, feats in norm.items():
        group = best_primary(feats) or fallback_assignment(feats)
        if group:
            assignment[group].append(sym)
    for new_name, parent_name, cond in DERIVED_BREAKOUTS:
        if parent_name not in assignment:
            continue
        if not all(f in active_features for f in cond):
            continue
        parent_members = list(assignment[parent_name])
        subgroup = [
            s
            for s in parent_members
            if all(norm[s].get(f, "0") == v for f, v in cond.items())
        ]
        remainder = [s for s in parent_members if s not in subgroup]
        if not subgroup or not remainder:
            continue
        if not _should_break_out(len(subgroup), len(inventory)):
            continue
        assignment[parent_name] = remainder
        assignment[new_name] = subgroup
    # Relabel pattern iteration uses sorted(origin_set); frozensets
    # randomize order under PYTHONHASHSEED and we want deterministic
    # internal merge order across runs.
    for origin_set, new_label in _RELABEL_PATTERNS.items():
        present = [g for g in sorted(origin_set) if g in assignment]
        if len(present) < 2:
            continue
        if any(
            not _should_merge_up(len(assignment[g]), len(inventory))
            for g in present
        ):
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        merged: list[str] = []
        for g in present:
            merged.extend(assignment.pop(g))
        assignment.setdefault(new_label, []).extend(merged)
    initial_group: dict[str, str] = {}
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
    for pair, label in _DERIVED_MERGES:
        present = [g for g in sorted(pair) if g in assignment]
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
    changed = True
    while changed:
        changed = False
        for gname in list(assignment.keys()):
            if gname in _FROZEN_GROUPS:
                continue
            if not _should_merge_up(len(assignment[gname]), len(inventory)):
                continue
            parent = _MERGE_PARENT.get(gname)
            if parent is not None:
                assignment.setdefault(parent, []).extend(assignment.pop(gname))
                changed = True
    if _LARYNGEAL_FEATURES & active_features:
        laryngeal_segs: list[str] = []
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
    return {
        name: sorted(
            assignment[name], key=lambda s: _segment_sort_key(norm[s])
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }
