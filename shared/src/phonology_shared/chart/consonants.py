"""Assign inventory segments to phonological display groups.

Pipeline: primary manner-class assignment, derived breakouts (for
example Sibilants from Fricatives), relational relabeling (Rhotics,
Liquids), small-group merging, laryngeal rescue, then sort. Each step
is keyed to the active feature set so inventories that lack a feature
skip the related step.

Place of articulation is derived from distinctive features rather
than read as a primitive: there is no ``"velar"`` or ``"uvular"``
feature in standard feature theory; those are display categories
inferred from ``dorsal``/``high``/``back``/``front`` etc. The same
discipline applies elsewhere in the module: laryngeal / phonation
behaviour is derived from ``voice``/``spreadgl``/``constrgl`` plus a
small set of accepted convenience aliases (``ejective``,
``implosive``, ``breathy``, ``creaky``, ``slackvoice``,
``stiffvoice``); secondary articulation is derived from the
underlying place + ``round`` evidence, NOT from invented
``"velarized"`` / ``"palatalized"`` primitives.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from enum import IntEnum

from phonology_shared.data.inventory import normalize_feature_bundle

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
    "Sibilant Affricates",
    "Lateral Affricates",
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
    """Display-place ordering derived from distinctive features.

    Values are the IPA-conventional front-to-back order used by the
    grouper's sort key. The integer values are pinned: they enter the
    sort-key tuple directly via :py:func:`int`, so reshuffling them
    would change within-group display order across every inventory.

    Membership is DERIVED from distinctive features (``labial``,
    ``coronal``, ``dorsal``, ``pharyngeal``, ``constrpharynx``,
    ``radical``, plus their ``anterior`` / ``distributed`` /
    ``apical`` / ``high`` / ``back`` / ``front`` refiners). The
    inventory never declares a ``"uvular"`` or ``"retroflex"``
    feature; those are display labels :py:func:`derive_place`
    emits.

    :py:attr:`VOWEL_OR_UNKNOWN` is the catch-all bucket for
    segments that carry no place evidence the grouper can read --
    typically syllabic vowels (handled separately by the manner
    pass) or sparsely specified segments waiting on more features.
    """

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
    GLOTTAL = 10
    VOWEL_OR_UNKNOWN = 11


def derive_place(feats: dict[str, str]) -> PlaceRank:
    """Derive an IPA-style place rank from distinctive features.

    ``feats`` is a normalised feature bundle (the keys have already
    been folded through
    :py:func:`phonology_shared.data.inventory.normalize_feature_key`).
    Reads only conventional distinctive features --
    ``labial``/``labiodental``, ``coronal``/``anterior``/
    ``distributed``, ``dorsal``/``high``/``back``,
    ``pharyngeal``/``constrpharynx``, ``constrgl`` -- never any
    invented ``"uvular"``/``"retroflex"``/etc. primitives.

    Behaviour is intentionally identical to the pre-extension
    :py:func:`_ipa_place` integer helper so the snapshot pinned in
    :py:mod:`test_consonants_grouping_snapshot` stays byte-stable
    while the typed-fact infrastructure is introduced.  Richer
    derivations (palatal via ``+front``, uvular via
    ``+low,+back``, retroflex via ``+apical``, epiglottal via
    ``+radical,+constrpharynx,+RTR``) come in a follow-up step
    once the snapshot has been regenerated to capture the
    intentional changes.
    """
    if feats.get("constrgl", "0") == "+":
        return PlaceRank.GLOTTAL
    if (
        feats.get("constrpharynx", "0") == "+"
        or feats.get("pharyngeal", "0") == "+"
    ):
        return PlaceRank.PHARYNGEAL
    dor = feats.get("dorsal", "0")
    if dor == "+":
        hi = feats.get("high", "0")
        bk = feats.get("back", "0")
        if hi == "-":
            return PlaceRank.UVULAR
        if bk == "-":
            if feats.get("anterior", "0") == "-":
                return PlaceRank.PALATAL
            return PlaceRank.VELAR
        return PlaceRank.VELAR
    cor = feats.get("coronal", "0")
    if cor == "+":
        ant = feats.get("anterior", "0")
        dist = feats.get("distributed", "0")
        if ant == "-":
            return (
                PlaceRank.RETROFLEX if dist == "-" else PlaceRank.POSTALVEOLAR
            )
        return PlaceRank.DENTAL if dist == "+" else PlaceRank.ALVEOLAR
    lab = feats.get("labial", "0")
    if lab == "+":
        return (
            PlaceRank.LABIODENTAL
            if feats.get("labiodental", "0") == "+"
            else PlaceRank.BILABIAL
        )
    if (
        feats.get("consonantal", "0") == "-"
        and feats.get("syllabic", "0") == "-"
    ):
        # /h/, /ɦ/: laryngeal segments lacking oral place evidence.
        return PlaceRank.GLOTTAL
    return PlaceRank.VOWEL_OR_UNKNOWN


class LaryngealKind(IntEnum):
    """Laryngeal / phonation / airstream display kind, derived from
    the Laryngeal-node features ``voice`` / ``spreadgl`` / ``constrgl``
    plus a small set of accepted convenience aliases.

    Integer values are pinned because they enter the sort-key tuple
    via :py:func:`int`; reshuffling them would reorder
    voiceless-before-voiced inside every primary group. The ordering
    runs voiceless -> aspirated -> ejective -> voiced -> breathy ->
    implosive -> creaky, with :py:attr:`UNKNOWN` last so segments
    whose laryngeal evidence is genuinely missing sort to the tail
    of the group rather than fighting for a particular slot.
    """

    PLAIN_VOICELESS = 0
    ASPIRATED = 1
    EJECTIVE = 2
    PLAIN_VOICED = 3
    BREATHY = 4
    IMPLOSIVE = 5
    CREAKY = 6
    UNKNOWN = 7


def derive_laryngeal_kind(feats: dict[str, str]) -> LaryngealKind:
    """Derive a :py:class:`LaryngealKind` from one normalised
    feature bundle.

    Derivation order (per the advice's "conventional first, aliases
    only when underspecified" rule):

      1. The conventional path reads ``voice`` / ``spreadgl`` /
         ``constrgl`` and the manner context (``continuant`` /
         ``sonorant``) to distinguish ejectives, implosives,
         creaky-, breathy-, aspirated-, plain-voiced and
         plain-voiceless segments. Implosives require a stop
         obstruent base (``-continuant, -sonorant``); ejectives
         require an obstruent (``-sonorant``).
      2. When the conventional path lands on
         :py:attr:`LaryngealKind.UNKNOWN` (no laryngeal evidence at
         all, or contradictory ``+constrgl`` + ambiguous ``voice``
         / ``sonorant`` state), the optional descriptive aliases
         ``ejective`` / ``implosive`` / ``breathy`` / ``slackvoice``
         / ``creaky`` / ``stiffvoice`` are consulted as shortcuts.
         These never override a confident conventional result; they
         only fill in when the inventory does not supply enough
         standard Laryngeal-node evidence.

    Not wired into the grouper yet; introduced here so unit tests can
    pin the semantics before any group-output change is requested.
    """
    voice = feats.get("voice", "0")
    spread = feats.get("spreadgl", "0")
    constr = feats.get("constrgl", "0")
    is_stop = feats.get("continuant", "0") == "-"
    is_obstruent = feats.get("sonorant", "0") == "-"

    if constr == "+":
        if voice == "+" and is_stop and is_obstruent:
            return LaryngealKind.IMPLOSIVE
        if voice == "-" and is_obstruent:
            return LaryngealKind.EJECTIVE
        if voice == "+":
            return LaryngealKind.CREAKY
        # +constrgl with ambiguous voice/sonorant: fall through to
        # aliases. Returning a confident kind here would over-claim.
    elif spread == "+":
        if voice == "+":
            return LaryngealKind.BREATHY
        if voice == "-":
            return LaryngealKind.ASPIRATED
    else:
        if voice == "+":
            return LaryngealKind.PLAIN_VOICED
        if voice == "-":
            return LaryngealKind.PLAIN_VOICELESS

    # Alias fallback. ``slackvoice`` / ``stiffvoice`` are kept
    # distinct from ``breathy`` / ``creaky`` at the inventory layer
    # (no alias map in ``normalize_feature_key``), but here they
    # map to the same phonation display category because the
    # display surface does not distinguish them.
    if feats.get("implosive", "0") == "+":
        return LaryngealKind.IMPLOSIVE
    if feats.get("ejective", "0") == "+":
        return LaryngealKind.EJECTIVE
    if (
        feats.get("breathy", "0") == "+"
        or feats.get("slackvoice", "0") == "+"
    ):
        return LaryngealKind.BREATHY
    if (
        feats.get("creaky", "0") == "+"
        or feats.get("stiffvoice", "0") == "+"
    ):
        return LaryngealKind.CREAKY
    return LaryngealKind.UNKNOWN


_VAL_ORD: dict[str, int] = {"-": 0, "+": 1, "0": 2}
_SORT_KEYS: list[tuple[str, dict[str, int]]] = [
    ("sonorant", _VAL_ORD),
    ("lateral", _VAL_ORD),
    ("strident", _VAL_ORD),
    ("nasal", _VAL_ORD),
    ("continuant", _VAL_ORD),
    ("delrel", _VAL_ORD),
    # Mouth-position ordering: fronted -> unspecified -> retracted
    # (so X+ / X / X- cluster as fronted, base, retracted).
    ("front", {"+": 0, "0": 1, "-": 2}),
    ("back", {"-": 0, "0": 1, "+": 2}),
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


def _segment_sort_key(feats: dict[str, str]) -> tuple[int, ...]:
    """Full feature-based sort key for a segment."""
    key: list[int] = [_ipa_place(feats)]
    for feat, ordering in _SORT_KEYS:
        key.append(ordering.get(feats.get(feat, "0"), 2))
    return tuple(key)


def _ipa_place(feats: dict[str, str]) -> int:
    """Integer place rank for the sort-key tuple.

    Thin wrapper around :py:func:`derive_place` kept so the existing
    call in :py:func:`_segment_sort_key` does not change shape; the
    typed :py:class:`PlaceRank` is what new code should reach for.
    """
    return int(derive_place(feats))


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
    inventory: Mapping[str, Mapping[str, str]],
) -> dict[str, list[str]]:
    """Assign every segment to a phonological display group.

    Returns ``{group_label: [symbol, ...]}`` in ``DISPLAY_ORDER``.
    """
    if not inventory:
        return {}
    norm: dict[str, dict[str, str]] = {
        sym: normalize_feature_bundle(feats)
        for sym, feats in inventory.items()
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
        # max with a tuple key picks the highest positive match count,
        # tie-broken by specificity. O(n) and reads as intent, vs
        # sorting the whole list to throw away all but the first.
        return max(matches, key=lambda x: (x[1], x[2]))[0]

    def fallback_assignment(seg_feats: dict[str, str]) -> str:
        """Best-fit group by fewest mismatches, then most matches.

        Mismatch counts disagreement against a display-class spec,
        not phonological invalidity: the system is permissive and
        treats every spec as an inclination rather than a rule.
        On ties the earlier group in ``PRIMARY_GROUPS`` wins.
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
