"""Assign inventory segments to phonological display groups.

Pipeline: primary manner-class assignment, derived breakouts (for
example Sibilants from Fricatives), derived-fact breakouts
(Implosives / Ejectives), relational relabeling (Rhotics, Liquids),
small-group merging, laryngeal rescue, then sort. Each step is keyed
to the active feature set or to facts derived from the active feature
set, so inventories that lack a feature skip the related step.

The public return shape remains ``{group_label: [symbol, ...]}``.
Internally, normalized feature bundles are compiled once into
``SegmentFacts`` so later passes operate on stable derived place,
laryngeal, secondary-articulation, and sort facts instead of
re-interpreting raw feature dictionaries at every step.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from phonology_shared.data.inventory import normalize_feature_bundle


# Broad manner classes for the initial assignment pass. Specs use only
# general distinctive features so they apply across diverse inventories.
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

# Breakouts driven directly by declared feature specifications.
DERIVED_BREAKOUTS: list[tuple[str, str, dict[str, str]]] = [
    ("Sibilants", "Fricatives", {"strident": "+", "coronal": "+"}),
    ("Lateral Fricatives", "Fricatives", {"lateral": "+"}),
    ("Sibilant Affricates", "Affricates", {"strident": "+", "coronal": "+"}),
    ("Lateral Affricates", "Affricates", {"lateral": "+"}),
    ("Lateral Flaps", "Taps & Flaps", {"lateral": "+"}),
]

_MERGE_PARENT: dict[str, str] = {
    "Sibilant Affricates": "Affricates",
    "Lateral Affricates": "Affricates",
    "Sibilants": "Fricatives",
    "Lateral Fricatives": "Fricatives",
    "Lateral Flaps": "Taps & Flaps",
    "Implosives": "Plosives",
    "Ejective Plosives": "Plosives",
    "Ejective Fricatives": "Fricatives",
    "Ejective Affricates": "Affricates",
    "Trills": "Central Approximants",
    "Taps & Flaps": "Central Approximants",
}

# Exempt from upward merging; laryngeal rescue can still peel members.
_FROZEN_GROUPS: set[str] = {"Plosives"}

DISPLAY_ORDER: list[str] = [
    "Clicks",
    "Plosives",
    "Implosives",
    "Ejectives",
    "Fricatives",
    "Sibilants",
    "Lateral Fricatives",
    "Ejective Fricatives",
    "Affricates",
    "Sibilant Affricates",
    "Lateral Affricates",
    "Ejective Affricates",
    "Nasals",
    "Vibrants",
    "Trills",
    "Taps & Flaps",
    "Lateral Flaps",
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


class PlaceRank(IntEnum):
    """IPA-like place order derived from distinctive feature bundles."""

    BILABIAL = 0
    LABIODENTAL = 1
    DENTAL = 2
    ALVEOLAR = 3
    POSTALVEOLAR = 4
    RETROFLEX = 5
    PALATAL = 6
    VELAR = 7
    UVULAR = 8
    PHARYNGEAL = 9
    EPIGLOTTAL = 10
    GLOTTAL = 11
    VOWEL_OR_UNKNOWN = 12


class LaryngealKind(IntEnum):
    """Laryngeal / airstream ordering for within-group display."""

    PLAIN_VOICELESS = 0
    ASPIRATED = 1
    EJECTIVE = 2
    PLAIN_VOICED = 3
    BREATHY = 4
    IMPLOSIVE = 5
    CREAKY = 6
    UNKNOWN = 7


class SecondaryKind(StrEnum):
    """Secondary articulations that keep related segments adjacent."""

    PALATALIZED = "palatalized"
    LABIALIZED = "labialized"
    VELARIZED = "velarized"
    PHARYNGEALIZED = "pharyngealized"


@dataclass(frozen=True, slots=True)
class SegmentFacts:
    """Compiled display facts for one segment.

    ``feats`` is the normalized feature bundle. ``place``,
    ``laryngeal``, and ``secondary`` are derived once and then reused
    by grouping, breakout, laryngeal rescue, and sorting.
    """

    symbol: str
    feats: dict[str, str]
    place: PlaceRank
    laryngeal: LaryngealKind
    secondary: frozenset[SecondaryKind]
    sort_key: tuple[int, ...]


FactPredicate = Callable[[SegmentFacts], bool]


@dataclass(frozen=True, slots=True)
class FactBreakout:
    """Derived breakout driven by compiled facts rather than a raw spec."""

    name: str
    parent: str
    predicate: FactPredicate


_VAL_ORD: dict[str, int] = {"-": 0, "+": 1, "0": 2}

_SORT_KEYS: list[tuple[str, dict[str, int]]] = [
    ("sonorant", _VAL_ORD),
    ("lateral", _VAL_ORD),
    ("strident", _VAL_ORD),
    ("nasal", _VAL_ORD),
    ("continuant", _VAL_ORD),
    ("delrel", _VAL_ORD),
    ("apical", _VAL_ORD),
    ("laminal", _VAL_ORD),
    # Mouth-position ordering: fronted -> unspecified -> retracted
    # (so X+ / X / X- cluster as fronted, base, retracted).
    ("front", {"+": 0, "0": 1, "-": 2}),
    ("back", {"-": 0, "0": 1, "+": 2}),
    ("labial", _VAL_ORD),
    ("round", _VAL_ORD),
    ("voice", {"-": 0, "+": 1, "0": 2}),
    ("spreadgl", _VAL_ORD),
    ("constrgl", _VAL_ORD),
    ("breathy", _VAL_ORD),
    ("creaky", _VAL_ORD),
    ("high", {"+": 0, "-": 1, "0": 2}),
    ("low", _VAL_ORD),
    ("tense", _VAL_ORD),
    ("long", _VAL_ORD),
]

_LARYNGEAL_FEATURES: frozenset[str] = frozenset(
    {"voice", "spreadgl", "constrgl", "breathy", "creaky"}
)
_PLACE_FEATURES: frozenset[str] = frozenset(
    {
        "labial",
        "labiodental",
        "coronal",
        "dorsal",
        "pharyngeal",
        "constrpharynx",
        "radical",
        "epilaryngeal",
        "aryepiglottic",
    }
)

_SECONDARY_ORDER: dict[SecondaryKind, int] = {
    SecondaryKind.PALATALIZED: 1,
    SecondaryKind.LABIALIZED: 2,
    SecondaryKind.VELARIZED: 3,
    SecondaryKind.PHARYNGEALIZED: 4,
}


def _has_pos(feats: dict[str, str], feat: str) -> bool:
    return feats.get(feat, "0") == "+"


def _has_oral_place(feats: dict[str, str]) -> bool:
    return any(_has_pos(feats, f) for f in _PLACE_FEATURES)


def _is_pharyngeal_like(feats: dict[str, str]) -> bool:
    return (
        _has_pos(feats, "pharyngeal")
        or _has_pos(feats, "constrpharynx")
        or (_has_pos(feats, "radical") and _has_pos(feats, "rtr"))
    )


def _is_epiglottal_like(feats: dict[str, str]) -> bool:
    return (
        _has_pos(feats, "epilaryngeal")
        or _has_pos(feats, "aryepiglottic")
        or (
            _has_pos(feats, "radical")
            and _has_pos(feats, "constrpharynx")
            and _has_pos(feats, "rtr")
        )
    )


def _is_glottal_like(feats: dict[str, str]) -> bool:
    has_laryngeal = any(_has_pos(feats, f) for f in _LARYNGEAL_FEATURES)
    return has_laryngeal and not _has_oral_place(feats)


def derive_place(feats: dict[str, str]) -> PlaceRank:
    """Derive an IPA-like place rank from distinctive features.

    Places such as uvular, palatal, retroflex, and pharyngeal are
    derived from feature combinations. Explicit whole-larynx style
    features are accepted when an inventory supplies them.
    """
    if _is_glottal_like(feats):
        return PlaceRank.GLOTTAL
    if _is_epiglottal_like(feats):
        return PlaceRank.EPIGLOTTAL
    if _is_pharyngeal_like(feats):
        return PlaceRank.PHARYNGEAL

    if _has_pos(feats, "dorsal"):
        high = feats.get("high", "0")
        low = feats.get("low", "0")
        back = feats.get("back", "0")
        front = feats.get("front", "0")

        if (high == "-" or low == "+") and back == "+":
            return PlaceRank.UVULAR
        if high == "+" and (front == "+" or back == "-"):
            return PlaceRank.PALATAL
        return PlaceRank.VELAR

    if _has_pos(feats, "coronal"):
        anterior = feats.get("anterior", "0")
        distributed = feats.get("distributed", "0")
        apical = feats.get("apical", "0")
        laminal = feats.get("laminal", "0")

        if anterior == "-":
            if distributed == "-" or apical == "+":
                return PlaceRank.RETROFLEX
            return PlaceRank.POSTALVEOLAR
        if distributed == "+" or laminal == "+":
            return PlaceRank.DENTAL
        return PlaceRank.ALVEOLAR

    if _has_pos(feats, "labial"):
        if _has_pos(feats, "labiodental"):
            return PlaceRank.LABIODENTAL
        return PlaceRank.BILABIAL

    return PlaceRank.VOWEL_OR_UNKNOWN


def _ipa_place(feats: dict[str, str]) -> int:
    """Compatibility wrapper: return an integer place rank."""
    return int(derive_place(feats))


def derive_laryngeal_kind(feats: dict[str, str]) -> LaryngealKind:
    """Derive laryngeal / airstream display kind.

    Convenience features such as ``ejective`` or ``implosive`` are
    honored when present. Otherwise the kind is derived from
    ``voice``, ``spreadgl``, ``constrgl``, and broad manner context.
    """
    voice = feats.get("voice", "0")
    spread = feats.get("spreadgl", "0")
    constr = feats.get("constrgl", "0")
    is_stop_like = feats.get("continuant", "0") == "-"
    is_obstruent = feats.get("sonorant", "0") == "-"

    if _has_pos(feats, "implosive"):
        return LaryngealKind.IMPLOSIVE
    if _has_pos(feats, "ejective"):
        return LaryngealKind.EJECTIVE
    if _has_pos(feats, "breathy") or _has_pos(feats, "slackvoice"):
        return LaryngealKind.BREATHY
    if _has_pos(feats, "creaky") or _has_pos(feats, "stiffvoice"):
        return LaryngealKind.CREAKY

    if constr == "+" and voice == "+" and is_stop_like:
        return LaryngealKind.IMPLOSIVE
    if constr == "+" and voice == "-" and is_obstruent:
        return LaryngealKind.EJECTIVE
    if constr == "+" and voice == "+":
        return LaryngealKind.CREAKY
    if spread == "+" and voice == "+":
        return LaryngealKind.BREATHY
    if spread == "+" and voice == "-":
        return LaryngealKind.ASPIRATED
    if voice == "+":
        return LaryngealKind.PLAIN_VOICED
    if voice == "-":
        return LaryngealKind.PLAIN_VOICELESS
    return LaryngealKind.UNKNOWN


def derive_secondary_articulations(
    feats: dict[str, str],
    place: PlaceRank,
) -> frozenset[SecondaryKind]:
    """Derive secondary articulation display facts.

    These facts refine ordering inside a primary group. They do not
    replace the primary manner group.
    """
    out: set[SecondaryKind] = set()
    is_vowel = _has_pos(feats, "syllabic")
    has_primary_oral_place = place not in {
        PlaceRank.GLOTTAL,
        PlaceRank.PHARYNGEAL,
        PlaceRank.EPIGLOTTAL,
        PlaceRank.VOWEL_OR_UNKNOWN,
    }

    if _has_pos(feats, "palatalized"):
        out.add(SecondaryKind.PALATALIZED)
    if _has_pos(feats, "labialized"):
        out.add(SecondaryKind.LABIALIZED)
    if _has_pos(feats, "velarized"):
        out.add(SecondaryKind.VELARIZED)

    if not is_vowel and _has_pos(feats, "round"):
        out.add(SecondaryKind.LABIALIZED)
    if has_primary_oral_place and _is_pharyngeal_like(feats):
        out.add(SecondaryKind.PHARYNGEALIZED)

    return frozenset(out)


def _secondary_sort_rank(secondary: frozenset[SecondaryKind]) -> int:
    if not secondary:
        return 0
    return min(_SECONDARY_ORDER[s] for s in secondary)


def _segment_sort_key_from_facts(facts: SegmentFacts) -> tuple[int, ...]:
    key: list[int] = [
        int(facts.place),
        _secondary_sort_rank(facts.secondary),
        int(facts.laryngeal),
    ]
    for feat, ordering in _SORT_KEYS:
        key.append(ordering.get(facts.feats.get(feat, "0"), 2))
    return tuple(key)


def _segment_sort_key(feats: dict[str, str]) -> tuple[int, ...]:
    """Compatibility helper for older tests that pass a feature dict."""
    place = derive_place(feats)
    facts = SegmentFacts(
        symbol="",
        feats=feats,
        place=place,
        laryngeal=derive_laryngeal_kind(feats),
        secondary=derive_secondary_articulations(feats, place),
        sort_key=(),
    )
    return _segment_sort_key_from_facts(facts)


def _compile_segment_facts(
    inventory: Mapping[str, Mapping[str, str]],
) -> dict[str, SegmentFacts]:
    out: dict[str, SegmentFacts] = {}
    for sym, raw_feats in inventory.items():
        feats = normalize_feature_bundle(raw_feats)
        place = derive_place(feats)
        facts = SegmentFacts(
            symbol=sym,
            feats=feats,
            place=place,
            laryngeal=derive_laryngeal_kind(feats),
            secondary=derive_secondary_articulations(feats, place),
            sort_key=(),
        )
        out[sym] = SegmentFacts(
            symbol=facts.symbol,
            feats=facts.feats,
            place=facts.place,
            laryngeal=facts.laryngeal,
            secondary=facts.secondary,
            sort_key=_segment_sort_key_from_facts(facts),
        )
    return out


def _active_features(facts: Mapping[str, SegmentFacts]) -> set[str]:
    active: set[str] = set()
    for segment in facts.values():
        for k, v in segment.feats.items():
            if v != "0":
                active.add(k)
    return active


def _positive_matches(
    seg_feats: dict[str, str],
    spec: dict[str, str],
    active_features: set[str],
) -> int:
    return sum(
        1
        for f in spec
        if f in active_features
        and seg_feats.get(f, "0") != "0"
        and seg_feats.get(f, "0") == spec[f]
    )


def _is_member(
    group_name: str,
    seg_feats: dict[str, str],
    spec: dict[str, str],
    active_features: set[str],
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


def _best_primary(seg_feats: dict[str, str], active_features: set[str]) -> str:
    """Best primary group by positive evidence, then specificity.

    ``click:+`` always wins regardless of how many other features
    match broader obstruent classes.
    """
    if seg_feats.get("click", "0") == "+":
        return "Clicks"
    matches = [
        (
            name,
            _positive_matches(seg_feats, spec, active_features),
            sum(1 for f in spec if f in active_features),
        )
        for name, spec in PRIMARY_GROUPS
        if _is_member(name, seg_feats, spec, active_features)
    ]
    if not matches:
        return ""
    return max(matches, key=lambda x: (x[1], x[2]))[0]


def _fallback_assignment(
    seg_feats: dict[str, str],
    active_features: set[str],
) -> str:
    """Best-fit group by fewest mismatches, then most matches.

    Mismatch counts disagreement against a display-class spec, not
    phonological invalidity: the system is permissive and treats
    every spec as an inclination rather than a rule. On ties the
    earlier group in ``PRIMARY_GROUPS`` wins.
    """
    best_name = ""
    best_mismatches = float("inf")
    best_matches = -1
    for name, spec in PRIMARY_GROUPS:
        if name in _FROZEN_GROUPS:
            continue
        relevant = [f for f in spec if f in active_features]
        if not relevant:
            continue
        mismatches = 0
        matched = 0
        for feat in relevant:
            val = seg_feats.get(feat, "0")
            if val == "0":
                continue
            if val == spec[feat]:
                matched += 1
            else:
                mismatches += 1
        if mismatches < best_mismatches or (
            mismatches == best_mismatches and matched > best_matches
        ):
            best_name = name
            best_mismatches = mismatches
            best_matches = matched
    return best_name


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to stand alone in the display."""
    return group_size < max(3, int(inventory_size * 0.05))


def _should_break_out(subgroup_size: int, inventory_size: int) -> bool:
    """True if a derived subgroup is large enough to display separately.

    At least as strict as ``_should_merge_up`` to prevent
    create-then-destroy churn.
    """
    return subgroup_size >= max(3, int(inventory_size * 0.05))


def _assign_primary_groups(
    facts: Mapping[str, SegmentFacts],
    active_features: set[str],
) -> dict[str, list[str]]:
    assignment: dict[str, list[str]] = defaultdict(list)
    for sym, seg_facts in facts.items():
        group = _best_primary(seg_facts.feats, active_features)
        if not group:
            group = _fallback_assignment(seg_facts.feats, active_features)
        if group:
            assignment[group].append(sym)
    return assignment


def _apply_spec_breakouts(
    assignment: dict[str, list[str]],
    facts: Mapping[str, SegmentFacts],
    active_features: set[str],
) -> None:
    for new_name, parent_name, cond in DERIVED_BREAKOUTS:
        if parent_name not in assignment:
            continue
        if not all(f in active_features for f in cond):
            continue
        parent_members = list(assignment[parent_name])
        subgroup = [
            s
            for s in parent_members
            if all(facts[s].feats.get(f, "0") == v for f, v in cond.items())
        ]
        remainder = [s for s in parent_members if s not in subgroup]
        if not subgroup or not remainder:
            continue
        if not _should_break_out(len(subgroup), len(facts)):
            continue
        assignment[parent_name] = remainder
        assignment[new_name] = subgroup


_FACT_BREAKOUTS: tuple[FactBreakout, ...] = (
    FactBreakout(
        "Implosives",
        "Plosives",
        lambda f: f.laryngeal == LaryngealKind.IMPLOSIVE,
    ),
    FactBreakout(
        "Ejective Plosives",
        "Plosives",
        lambda f: f.laryngeal == LaryngealKind.EJECTIVE,
    ),
    FactBreakout(
        "Ejective Fricatives",
        "Fricatives",
        lambda f: f.laryngeal == LaryngealKind.EJECTIVE,
    ),
    FactBreakout(
        "Ejective Affricates",
        "Affricates",
        lambda f: f.laryngeal == LaryngealKind.EJECTIVE,
    ),
)


def _apply_fact_breakouts(
    assignment: dict[str, list[str]],
    facts: Mapping[str, SegmentFacts],
) -> None:
    for breakout in _FACT_BREAKOUTS:
        if breakout.parent not in assignment:
            continue
        parent_members = list(assignment[breakout.parent])
        subgroup = [s for s in parent_members if breakout.predicate(facts[s])]
        remainder = [s for s in parent_members if s not in subgroup]
        if not subgroup or not remainder:
            continue
        if not _should_break_out(len(subgroup), len(facts)):
            continue
        assignment[breakout.parent] = remainder
        assignment[breakout.name] = subgroup


def _apply_relational_relabels(
    assignment: dict[str, list[str]],
) -> None:
    # Relabel pattern iteration uses sorted(origin_set); frozensets
    # randomize order under PYTHONHASHSEED and deterministic internal
    # merge order is useful across runs.
    for origin_set, new_label in _RELABEL_PATTERNS.items():
        present = [g for g in sorted(origin_set) if g in assignment]
        if len(present) < 2:
            continue
        if any(
            not _should_merge_up(len(assignment[g]), sum(map(len, assignment.values())))
            for g in present
        ):
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        merged: list[str] = []
        for g in present:
            merged.extend(assignment.pop(g))
        assignment.setdefault(new_label, []).extend(merged)


def _apply_origin_relabels(
    assignment: dict[str, list[str]],
) -> None:
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


def _apply_derived_merges(
    assignment: dict[str, list[str]],
) -> None:
    inventory_size = sum(map(len, assignment.values()))
    for pair, label in _DERIVED_MERGES:
        present = [g for g in sorted(pair) if g in assignment]
        if len(present) < 2:
            continue
        if any(g in _FROZEN_GROUPS for g in present):
            continue
        if not any(
            _should_merge_up(len(assignment[g]), inventory_size)
            for g in present
        ):
            continue
        merged = []
        for g in present:
            merged.extend(assignment.pop(g))
        assignment.setdefault(label, []).extend(merged)


def _merge_small_groups(assignment: dict[str, list[str]]) -> None:
    inventory_size = sum(map(len, assignment.values()))
    changed = True
    while changed:
        changed = False
        for gname in list(assignment.keys()):
            if gname in _FROZEN_GROUPS:
                continue
            if not _should_merge_up(len(assignment[gname]), inventory_size):
                continue
            parent = _MERGE_PARENT.get(gname)
            if parent is not None:
                assignment.setdefault(parent, []).extend(assignment.pop(gname))
                changed = True


def _is_laryngeal_candidate(facts_or_feats: SegmentFacts | dict[str, str]) -> bool:
    """True for glottal / laryngeal segments with no oral place.

    Accepts ``SegmentFacts`` for the main pipeline and ``dict`` for
    compatibility with older tests.
    """
    if isinstance(facts_or_feats, SegmentFacts):
        facts = facts_or_feats
    else:
        feats = facts_or_feats
        place = derive_place(feats)
        facts = SegmentFacts(
            symbol="",
            feats=feats,
            place=place,
            laryngeal=derive_laryngeal_kind(feats),
            secondary=derive_secondary_articulations(feats, place),
            sort_key=(),
        )
    is_vowel = facts.feats.get("syllabic", "0") == "+"
    is_click = facts.feats.get("click", "0") == "+"
    return facts.place == PlaceRank.GLOTTAL and not is_vowel and not is_click


def _rescue_laryngeals(
    assignment: dict[str, list[str]],
    facts: Mapping[str, SegmentFacts],
    active_features: set[str],
) -> None:
    if not (_LARYNGEAL_FEATURES & active_features):
        return
    laryngeal_segs: list[str] = []
    for gname in list(assignment.keys()):
        if gname == "Laryngeals":
            continue
        peeled = [
            sym for sym in assignment[gname] if _is_laryngeal_candidate(facts[sym])
        ]
        if peeled:
            for sym in peeled:
                assignment[gname].remove(sym)
            laryngeal_segs.extend(peeled)
            if not assignment[gname]:
                del assignment[gname]
    if laryngeal_segs:
        assignment.setdefault("Laryngeals", []).extend(laryngeal_segs)


def _to_display_ordered_groups(
    assignment: Mapping[str, list[str]],
    facts: Mapping[str, SegmentFacts],
) -> dict[str, list[str]]:
    return {
        name: sorted(assignment[name], key=lambda s: facts[s].sort_key)
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }


def group_segments(
    inventory: Mapping[str, Mapping[str, str]],
) -> dict[str, list[str]]:
    """Assign every segment to a phonological display group.

    Returns ``{group_label: [symbol, ...]}`` in ``DISPLAY_ORDER``.
    """
    if not inventory:
        return {}

    facts = _compile_segment_facts(inventory)
    active = _active_features(facts)

    assignment = _assign_primary_groups(facts, active)
    _apply_spec_breakouts(assignment, facts, active)
    _apply_fact_breakouts(assignment, facts)
    _apply_relational_relabels(assignment)
    _apply_origin_relabels(assignment)
    _apply_derived_merges(assignment)
    _merge_small_groups(assignment)
    _rescue_laryngeals(assignment, facts, active)

    return _to_display_ordered_groups(assignment, facts)