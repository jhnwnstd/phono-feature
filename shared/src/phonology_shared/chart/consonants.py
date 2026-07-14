# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""Assign inventory segments to phonological display groups.

Pipeline: existential-reach routing (``reached_classes`` over the
tiers decides Stage 1: a plain affricate takes its specific class, a
segment reaching several coarse classes renders in EVERY one of them
as a multiset, a single reach takes that class), derived breakouts
(for example Sibilants from Fricatives), relational relabeling
(Rhotics, Liquids), small-group merging, laryngeal rescue, the
substance-free pin (multi-membership segments are restored to exactly
their reach after the population-based covers run), then sort. Each
step is keyed to the active feature set so inventories that lack a
feature skip the related step.

Place of articulation is derived from distinctive features rather
than read as a primitive. There is no ``"velar"`` or ``"uvular"``
feature in standard feature theory; those are display categories
inferred from ``dorsal``/``high``/``back``/``front`` etc.

The same discipline governs the optional descriptive primitives an
inventory author may supply. Standard distinctive-feature evidence is
consulted FIRST, and a small set of primitive aliases is accepted
only when the standard bundle cannot establish the display category.

  * Laryngeal / phonation reads ``voice``/``spreadgl``/``constrgl``
    first, then the ``ejective`` / ``implosive`` / ``breathy`` /
    ``creaky`` / ``slackvoice`` / ``stiffvoice`` aliases.
  * Secondary articulation reads ``round`` / ``secondary*`` place
    evidence first, then the optional ``labialized`` / ``palatalized``
    / ``velarized`` / ``pharyngealized`` aliases.
  * The relational classes accept explicit ``rhotic`` (a declared
    ``Rhotics`` member, since rhoticity is not recoverable from
    features), ``liquid`` (the ``Liquids`` cover when nothing more
    specific claims the segment), and ``flap`` (folded into ``Taps &
    Flaps``).

All of these are display-grouping reads only. They do not change
feature-query behaviour beyond the inventory simply containing the
feature.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from phonology_shared.data.inventory import normalize_feature_bundle

#: Display-group name for vowels, emitted verbatim by
#: :py:func:`group_segments`. Exported so consumers that split vowels
#: out of the grouping (presentation + desktop) compare against this
#: one constant instead of an ad-hoc ``manner.lower() == "vowels"``,
#: which silently assumed a case the grouper never produces.
VOWEL_GROUP_NAME = "Vowels"

#: Display-group name for suprasegmental tone letters, emitted verbatim
#: by :py:func:`group_segments`. Exported alongside
#: :py:data:`VOWEL_GROUP_NAME` so the cap counter
#: (:py:func:`~phonology_shared.chart.segment_classes.count_segment_classes`)
#: and the ``is_member`` tone-phoneme guard compare against this one
#: symbol rather than a bare ``"Tones"`` literal that a group-label
#: rename would silently desync (zeroing the tone class's hard cap).
TONES_GROUP_NAME = "Tones"

#: Catch-all display groups for segments that match no manner/place
#: class (reachable with sparse / custom inventories whose features
#: don't carry the usual manner+place columns). The fallthrough is
#: split by Pike's vocoid/contoid distinction so each lands near its
#: kin: a vowel-like segment that fits no class is a VOCOID (rendered
#: as a flat list under the vowel chart); anything else is a CONTOID
#: (a flat list under the consonants). Routing them here keeps them
#: visible and the on-screen count honest rather than silently dropping
#: them while they still appear in the flat segment list.
CONTOID_GROUP_NAME = "Contoids"
VOCOID_GROUP_NAME = "Vocoids"

# A consonant that reaches SEVERAL manner classes across its phases (a
# prenasalized stop ``mb`` is existentially a nasal and an oral stop, and
# universally neither) now renders in EVERY class it reaches: the multiset
# in ``group_segments`` puts it in each, driven by ``reached_classes`` off
# the tiers. It briefly sat in a provisional "Contour Consonants" bucket
# while the frontends learned to render multi-membership; that placeholder
# is retired now that both do.

# Broad manner classes for the initial assignment pass. Specs use only
# universal features so they apply across diverse inventories.
PRIMARY_GROUPS: list[tuple[str, dict[str, str]]] = [
    ("Clicks", {"click": "+"}),
    # Affricates are NOT a spec here: a single ``[-continuant, +delrel]``
    # bundle cannot tell PHOIBLE's two affricate encodings apart, and it
    # would wrongly admit a stop that releases into a sonorant. They are
    # assigned by ``reached_classes``' affricate ∃-rule (some phase is an
    # oral stop closure AND some phase carries ``+delrel``), which Stage 1
    # of :py:func:`group_segments` routes on directly.
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
    (VOWEL_GROUP_NAME, {"syllabic": "+"}),
    # Suprasegmental tone letters (Chao ``˥˦˧˨˩`` plus combining tone
    # diacritics). PHOIBLE ships these as standalone segments carrying
    # only the generic ``tone`` marker and no consonant / vowel
    # features; before this group existed, the fallback assigner routed
    # them to Affricates by document order. Membership is the
    # tone-phoneme guard in ``is_member``, not this spec, since a tone
    # letter is marked by the generic ``tone`` (PHOIBLE) OR the
    # ``hightone`` level (PanPhon) and one spec cannot express either.
    # Hayes records no standalone tone letters so the group stays empty
    # on Hayes inventories.
    (TONES_GROUP_NAME, {"tone": "+"}),
]
# Minimum positive matches required for membership; prevents barely
# specified segments from qualifying for classes by default.
_MIN_POSITIVE: dict[str, int] = {
    "Plosives": 2,
    "Fricatives": 2,
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

# Fact-based breakouts populated after :py:class:`LaryngealKind` is
# declared (further down). The table is a list of
# ``(display name, parent group, target laryngeal kind)``; see
# :py:data:`_FACT_BREAKOUTS` for the actual entries.
_MERGE_PARENT: dict[str, str] = {
    "Sibilant Affricates": "Affricates",
    "Lateral Affricates": "Affricates",
    "Sibilants": "Fricatives",
    "Lateral Fricatives": "Fricatives",
    "Lateral Flaps": "Taps & Flaps",
    # No entry for Trills or Taps & Flaps: those ARE coarse reached
    # classes, not refinements of one, so a small trill row keeps its
    # own reach-labeled identity rather than escaping into a
    # population cover (rhoticity is not recoverable from the
    # features, and display membership never leaves a segment's
    # reached-class subtree).
    "Implosives": "Plosives",
    "Ejective Plosives": "Plosives",
    "Ejective Fricatives": "Fricatives",
    "Ejective Affricates": "Affricates",
}
# Exempt from upward merging.
_FROZEN_GROUPS: set[str] = {"Plosives"}
# Groups whose membership is a HARD per-segment gate (a click, a vowel
# phoneme, a tone letter), decided by ``best_primary`` / ``is_member``,
# never by spec similarity. ``fallback_assignment`` must never route a
# leftover INTO one of these: a segment that failed the gate is by
# definition not a member, yet its gate feature being UNSPECIFIED (a
# consonant with ``tone`` / ``syllabic`` / ``click`` = 0) reads as zero
# mismatches and would otherwise let the gated group win by default.
# This is what stranded a bare ``/h/`` (tone unspecified) in Tones.
_GATED_GROUPS: set[str] = {
    "Clicks",
    VOWEL_GROUP_NAME,
    TONES_GROUP_NAME,
}
DISPLAY_ORDER: list[str] = [
    "Clicks",
    "Plosives",
    "Implosives",
    "Ejective Plosives",
    "Fricatives",
    "Sibilants",
    "Lateral Fricatives",
    "Ejective Fricatives",
    "Affricates",
    "Sibilant Affricates",
    "Lateral Affricates",
    "Ejective Affricates",
    "Nasals",
    "Trills",
    "Taps & Flaps",
    "Lateral Flaps",
    "Rhotics",
    "Lateral Approximants",
    "Liquids",
    "Central Approximants",
    "Semivowels",
    # Consonant-area catch-all: renders at the end of the consonant
    # section (before vowels) so an unclassifiable contoid stays visible.
    CONTOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
    # Vowel-area catch-all: renders right after the vowel chart so an
    # unclassifiable vocoid stays visible beneath it.
    VOCOID_GROUP_NAME,
    # Tones render after the segmental classes so the chart reads
    # consonants first, then vowels, then the suprasegmental tier.
    TONES_GROUP_NAME,
]


@dataclass(frozen=True, slots=True)
class ConsonantProfile:
    """Inventory-level facts about which conventions a bundle uses.

    Mirrors :py:class:`phonology_shared.chart.vowels.VowelProfile` in
    spirit: per-segment derivations look up the bundle's
    convention-flag rather than guessing at runtime. The flags are
    discovered once per inventory via :py:func:`detect_consonant_profile`
    and threaded through the grouper / sort pipeline so a Hayes-style
    inventory and a general-feature-system inventory both produce the
    IPA-correct display labels.

    Today the only field is :py:attr:`dorsals_use_anterior`, the
    palatal-versus-velar discriminator. Add new fields as similar
    "this inventory encodes X using convention Y" facts surface.
    """

    #: True iff at least one ``+dorsal`` segment in the inventory
    #: carries an explicit (``+`` or ``-``) ``anterior`` value.
    #: Hayes-style inventories use the ``-anterior`` value on
    #: dorsals to mark palatal stops (``c`` / ``ɉ``) and the absent
    #: / ``0anterior`` value on advanced velars (``k+`` / ``ɡ+``).
    #: When the flag is True, :py:func:`derive_place` discriminates
    #: palatal from velar via ``anterior``. When False, the inventory
    #: follows the general rule (``+dorsal +high -back`` or
    #: ``+dorsal +high +front`` -> palatal regardless of anterior).
    dorsals_use_anterior: bool = False


def detect_consonant_profile(
    norm_feats: Mapping[str, Mapping[str, str]],
) -> ConsonantProfile:
    """Scan ``norm_feats`` (segment label -> normalised feature
    bundle) for inventory-level convention flags.

    A single ``+dorsal`` segment carrying an explicit ``anterior``
    value is enough to flip :py:attr:`ConsonantProfile.dorsals_use_anterior`
    to True: feature theory inventories use anterior consistently
    within a system, so partial evidence is reliable.
    """
    dorsals_use_anterior = any(
        f.get("dorsal", "0") == "+" and f.get("anterior", "0") in ("+", "-")
        for f in norm_feats.values()
    )
    return ConsonantProfile(dorsals_use_anterior=dorsals_use_anterior)


class PlaceRank(IntEnum):
    """Display-place ordering derived from distinctive features.

    Values are the IPA-conventional front-to-back order used by the
    grouper's sort key. The integer values are pinned: they enter the
    sort-key tuple directly via :py:func:`int`, so reshuffling them
    would change within-group display order across every inventory.

    Membership is DERIVED from conventional distinctive features
    (``labial`` + ``labiodental``; ``coronal`` + ``anterior`` +
    ``distributed``; ``dorsal`` + ``high`` + ``back``; plus
    ``pharyngeal`` / ``constrpharynx`` / (``radical`` + ``rtr``)
    for pharyngeal evidence). Apical-versus-laminal coronal
    distinctions are encoded by ``distributed``: ``[+distributed]``
    aligns with laminal dental and postalveolar contacts and
    ``[-distributed]`` aligns with apical alveolar and retroflex
    contacts; the derivation does not require literal
    ``apical`` / ``laminal`` primitives. The inventory never
    declares a ``"uvular"`` or ``"retroflex"`` feature; those are
    display labels :py:func:`derive_place` emits.

    :py:attr:`VOWEL_OR_UNKNOWN` is the catch-all bucket for
    segments that carry no place evidence the grouper can read,
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
    EPIGLOTTAL = 10
    GLOTTAL = 11
    VOWEL_OR_UNKNOWN = 12


def _is_pharyngeal_like(feats: dict[str, str]) -> bool:
    """Conventional pharyngeal-evidence patterns.

    Three encodings are recognised because different feature systems
    write the pharyngeals ``ħ`` / ``ʕ`` differently:
      * an explicit ``+pharyngeal`` primitive (Modern Standard Arabic),
      * an explicit ``+constrpharynx`` or ``+radical +rtr`` (Blevins /
        McCarthy guttural encodings),
      * the retracted low-back dorsal pattern ``+dorsal +low +back
        +rtr`` that Hayes and PHOIBLE use, WITH ``+rtr`` as the
        discriminator: a plain uvular is ``+dorsal +low? -rtr`` and a
        low back vowel is ``+syllabic``, so both are excluded. Without
        this branch the low-back dorsal fell through to the ``-high ->
        UVULAR`` rule and every PHOIBLE ``ħ`` / ``ʕ`` sorted as a uvular.
    """
    return (
        feats.get("pharyngeal", "0") == "+"
        or feats.get("constrpharynx", "0") == "+"
        or (feats.get("radical", "0") == "+" and feats.get("rtr", "0") == "+")
        or (
            feats.get("dorsal", "0") == "+"
            and feats.get("low", "0") == "+"
            and feats.get("back", "0") == "+"
            and feats.get("rtr", "0") == "+"
            and feats.get("syllabic", "0") != "+"
        )
    )


def _is_epiglottal_like(feats: dict[str, str]) -> bool:
    """Conventional epiglottal-evidence patterns: PHOIBLE's
    ``+epilaryngealsource`` (the feature it actually stamps on the
    epiglottals ``ʡ`` / ``ʜ`` / ``ʢ``), the explicit whole-larynx
    features (``+epilaryngeal`` / ``+aryepiglottic``) that
    hand-authored inventories use, or the ``+radical +constrpharynx
    +rtr`` triple Moisik / Esling-style inventories use to mark the
    aryepiglottic stricture mechanism. Without the
    ``epilaryngealsource`` branch every PHOIBLE ``ʡ`` fell through to
    UNKNOWN and ``ʜ`` / ``ʢ`` (both ``-consonantal``) collapsed onto
    GLOTTAL. The ``epilaryngealsource`` branch is gated to
    non-vowels so an epiglottalized VOWEL (``aᴱ`` / ``oᴱ`` / ``uᴱ``,
    ``+syllabic +epilaryngealsource``) is not handed a consonant
    place rank; it stays a vowel and sorts among the vowels. The
    triple is a strict superset of the pharyngeal ``+radical +rtr``
    pattern, so :py:func:`derive_place` must call this BEFORE
    :py:func:`_is_pharyngeal_like` to avoid the broader pharyngeal
    rule absorbing every epiglottal candidate.
    """
    return (
        (
            feats.get("epilaryngealsource", "0") == "+"
            and feats.get("syllabic", "0") != "+"
        )
        or feats.get("epilaryngeal", "0") == "+"
        or feats.get("aryepiglottic", "0") == "+"
        or (
            feats.get("radical", "0") == "+"
            and feats.get("constrpharynx", "0") == "+"
            and feats.get("rtr", "0") == "+"
        )
    )


def derive_place(
    feats: dict[str, str],
    profile: ConsonantProfile | None = None,
) -> PlaceRank:
    """Derive an IPA-style place rank from distinctive features.

    ``feats`` is a normalised feature bundle (the keys have already
    been folded through
    :py:func:`phonology_shared.data.inventory.normalize_feature_key`).
    Reads only conventional distinctive features:
    ``labial``/``labiodental``, ``coronal``/``anterior``/
    ``distributed``, ``dorsal``/``high``/``back``/``low``/``front``,
    ``pharyngeal``/``constrpharynx``/``radical``/``rtr``,
    ``epilaryngeal``/``aryepiglottic``, ``constrgl``; never any
    invented ``"uvular"``/``"retroflex"``/etc. primitives.

    Check order matters: epiglottal evidence is detected BEFORE
    pharyngeal because the ``+radical +constrpharynx +rtr`` triple
    is a strict superset of the pharyngeal ``+radical +rtr``
    pattern. The dorsal branch recognises uvular via the
    conventional ``+dorsal -high`` AND the alternative
    ``+dorsal +back +low`` pattern (the lowered-tongue-body uvular
    used in some whole-larynx inventories).

    ``profile`` switches the palatal-versus-velar discrimination on
    ``+dorsal +high -back`` segments. The function mirrors the
    vowel-chart pattern (``coronal`` as a ``+front`` fallback when
    the inventory lacks the ``Front`` feature): the inventory's
    convention is detected once, then applied per-segment.

    * When ``profile`` is ``None`` or
      :py:attr:`ConsonantProfile.dorsals_use_anterior` is True
      (Hayes-style inventories), ``anterior`` is the discriminator:
      ``+dorsal +high -back -anterior`` -> PALATAL, all other
      ``+dorsal +high -back`` -> VELAR. This protects advanced
      velars like Hayes ``k+`` (``+dorsal +high -back +front
      0anterior``) from being mis-classified as palatals.

    * When :py:attr:`ConsonantProfile.dorsals_use_anterior` is
      False (general feature systems), the rule honours ``+front``
      and ``-back`` as palatal evidence regardless of anterior:
      ``+dorsal +high (+front OR -back)`` -> PALATAL. Spanish
      ``ʝ`` / ``ɲ`` / ``ʎ`` and Hindi ``ɲ`` lift into PALATAL
      here; they were silently routed to VELAR by the old
      anterior-only check.

    Apical-versus-laminal coronal distinctions stay encoded
    through ``distributed``, never through literal ``apical`` /
    ``laminal`` primitives.
    """
    if _is_epiglottal_like(feats):
        return PlaceRank.EPIGLOTTAL
    if _is_pharyngeal_like(feats):
        return PlaceRank.PHARYNGEAL
    dor = feats.get("dorsal", "0")
    if dor == "+":
        hi = feats.get("high", "0")
        bk = feats.get("back", "0")
        lo = feats.get("low", "0")
        front = feats.get("front", "0")
        if hi == "-":
            return PlaceRank.UVULAR
        if bk == "+" and lo == "+":
            return PlaceRank.UVULAR
        # Hayes-style inventories: anterior is the palatal/velar
        # discriminator. Default to this when no profile is given
        # so the function stays backward-compatible at every
        # call site that has not yet been profile-threaded.
        hayes_style = profile is None or profile.dorsals_use_anterior
        if hayes_style:
            if bk == "-":
                # A ``+dorsal +high -back`` GLIDE (the palatal semivowel
                # /j/, /ɥ/: explicit -consonantal, -syllabic) is palatal.
                # It carries no ``anterior`` value, so the anterior-only
                # rule would mislabel it VELAR. The clause requires an
                # EXPLICIT ``-consonantal`` (not merely absent) so a true
                # advanced velar (Hayes ``k+`` = +consonantal +dorsal +high
                # -back +front 0anterior) and any under-specified dorsal
                # both stay VELAR; and it is gated to non-syllabic so it
                # does NOT reach front VOWELS (also -consonantal), whose
                # within-chart ordering must stay put.
                if feats.get("anterior", "0") == "-" or (
                    feats.get("consonantal", "0") == "-"
                    and feats.get("syllabic", "0") != "+"
                ):
                    return PlaceRank.PALATAL
                return PlaceRank.VELAR
            return PlaceRank.VELAR
        # General feature systems: +high + (-back OR +front)
        # marks palatal regardless of anterior. The advice's rule
        # without the anterior caveat.
        if hi == "+" and (bk == "-" or front == "+"):
            return PlaceRank.PALATAL
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
    # ``constrgl`` is a LARYNGEAL feature, not a place: an ejective,
    # implosive, tense/fortis, or glottalized consonant keeps the oral
    # place resolved above. Only a [+constrgl] segment with NO oral
    # place evidence is a glottal stop (/ʔ/). Checked here, after the
    # oral-place branches, so the oral place wins (Korean /p͈ t͈ k͈/ stay
    # bilabial / alveolar / velar, ejectives /pʼ tʼ kʼ/ likewise),
    # rather than the whole [+constrgl] series collapsing to GLOTTAL.
    if feats.get("constrgl", "0") == "+":
        return PlaceRank.GLOTTAL
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
    :py:attr:`FORTIS` is appended after ``UNKNOWN`` (rather than
    inserted) so the pinned ranks above are unchanged; in practice a
    fortis segment coexists with the plain/aspirated members of its
    place, so within a plosive place it still reads plain, aspirated,
    fortis.
    """

    PLAIN_VOICELESS = 0
    ASPIRATED = 1
    EJECTIVE = 2
    PLAIN_VOICED = 3
    BREATHY = 4
    IMPLOSIVE = 5
    CREAKY = 6
    UNKNOWN = 7
    #: Tense / fortis voiceless obstruent: ``[-voice, +constricted
    #: glottis]`` WITHOUT positive ejective evidence (no raised-larynx
    #: airstream feature, no declared ``ejective``). The Korean tense
    #: stops /p͈ t͈ k͈/. Has no fact-breakout, so it stays with its manner
    #: class (Plosives) rather than peeling into an Ejective row.
    FORTIS = 8


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
         require an obstruent (``-sonorant``) AND positive ejective
         evidence (``raisedlarynxejective`` or a declared ``ejective``),
         since ``+constrgl`` alone also marks tense/fortis obstruents
         (returned as :py:attr:`LaryngealKind.FORTIS`).
      2. When the conventional path lands on
         :py:attr:`LaryngealKind.UNKNOWN` (no laryngeal evidence at
         all, or contradictory ``+constrgl`` + ambiguous ``voice``
         / ``sonorant`` state), the optional descriptive aliases
         ``ejective`` / ``implosive`` / ``breathy`` / ``slackvoice``
         / ``creaky`` / ``stiffvoice`` are consulted as shortcuts.
         These never override a confident conventional result; they
         only fill in when the inventory does not supply enough
         standard Laryngeal-node evidence.

    Wired into the grouper: the fact-based breakouts
    (:py:data:`_FACT_BREAKOUTS`, applied by
    :py:func:`_break_out_by_laryngeal_kind`) call this per segment, so
    a change to the derivation changes which display sub-groups the
    Ejective / Implosive breakouts form.
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
            # [+constricted glottis] alone does NOT establish an
            # ejective: it equally encodes tense/fortis (Korean
            # /p͈ t͈ k͈/) and other glottalized voiceless obstruents.
            # Name it ejective only with positive ejective evidence
            # (PHOIBLE's raised-larynx-ejective airstream feature, or a
            # declared ``ejective``); otherwise it is a fortis obstruent
            # that stays with its manner class instead of peeling into an
            # Ejective breakout.
            if (
                feats.get("raisedlarynxejective", "0") == "+"
                or feats.get("ejective", "0") == "+"
            ):
                return LaryngealKind.EJECTIVE
            return LaryngealKind.FORTIS
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
    if feats.get("breathy", "0") == "+" or feats.get("slackvoice", "0") == "+":
        return LaryngealKind.BREATHY
    if feats.get("creaky", "0") == "+" or feats.get("stiffvoice", "0") == "+":
        return LaryngealKind.CREAKY
    return LaryngealKind.UNKNOWN


# Fact-based breakouts driven by :py:func:`derive_laryngeal_kind`
# rather than a flat feature spec. Run AFTER
# :py:data:`DERIVED_BREAKOUTS` so the more specific spec classes
# (Sibilants, Lateral Fricatives, etc.) absorb their members first;
# a sibilant ejective lands in Sibilants, NOT Ejective Fricatives.
# Each tuple is (display name, parent group, target laryngeal kind);
# the breakout fires when at least
# :py:func:`_should_break_out`-many parent members match the kind.
_FACT_BREAKOUTS: list[tuple[str, str, LaryngealKind]] = [
    ("Implosives", "Plosives", LaryngealKind.IMPLOSIVE),
    ("Ejective Plosives", "Plosives", LaryngealKind.EJECTIVE),
    ("Ejective Fricatives", "Fricatives", LaryngealKind.EJECTIVE),
    ("Ejective Affricates", "Affricates", LaryngealKind.EJECTIVE),
]


class SecondaryKind(StrEnum):
    """Secondary articulation display facts.

    Derived from real distinctive features, never from an invented
    ``"velarized"`` / ``"palatalized"`` primitive: there is no
    ``velarized`` feature in standard distinctive feature theory.
    The flat names below are typed display facts kept for renderers
    to consume, never the input vocabulary; the grouping pipeline does
    not currently emit them (only the unit tests read the derivation).

    Evidence the derivation accepts:

      * ``LABIALIZED``: explicit ``+secondarylabial``, OR
        ``+round`` on a non-vowel (the practical labialisation cue),
        OR the optional ``+labialized`` alias when an inventory
        supplies it.
      * ``PALATALIZED``: explicit ``+secondarydorsal`` combined
        with ``+high`` and front-leaning evidence (``+front`` or
        ``-back``), OR the optional ``+palatalized`` alias. A bare
        primary ``+dorsal`` segment is NOT treated as secondarily
        palatalised; the inventory must declare secondary place.
      * ``VELARIZED``: explicit ``+secondarydorsal`` combined
        with ``+high +back``, OR the optional ``+velarized`` alias.
        Same discipline as palatalised: no inference from primary
        ``+dorsal`` alone.
      * ``PHARYNGEALIZED``: explicit ``+secondarypharyngeal`` or
        ``+secondaryradical``, OR pharyngeal evidence (
        ``+pharyngeal`` / ``+constrpharynx`` / ``+radical +rtr``)
        layered onto a segment whose primary place is already an
        ORAL place (so a primary pharyngeal is not also tagged as
        secondarily pharyngealised), OR the optional
        ``+pharyngealized`` alias.

    The set is empty for vowels: secondary articulation is a
    consonantal display fact in this grouper.
    """

    LABIALIZED = "labialized"
    PALATALIZED = "palatalized"
    VELARIZED = "velarized"
    PHARYNGEALIZED = "pharyngealized"


def derive_secondary_articulations(
    feats: dict[str, str],
    place: PlaceRank,
) -> frozenset[SecondaryKind]:
    """Derive secondary articulation display facts.

    Always returns an empty set for vowels (``+syllabic``); the
    grouper does not surface secondary articulation on vowel
    cells. For consonants, the function reads ``feats`` against
    the rules documented on :py:class:`SecondaryKind` and returns
    every applicable kind.

    ``place`` is the result of :py:func:`derive_place` on the same
    bundle; the pharyngealisation branch needs it to refuse the
    label on a segment whose primary place is already pharyngeal
    or glottal (no point flagging "secondarily pharyngealised" on
    a primary pharyngeal).
    """
    if feats.get("syllabic", "0") == "+":
        return frozenset()

    out: set[SecondaryKind] = set()

    # LABIALIZED
    if (
        feats.get("secondarylabial", "0") == "+"
        or feats.get("round", "0") == "+"
        or feats.get("labialized", "0") == "+"
    ):
        out.add(SecondaryKind.LABIALIZED)

    secondary_dorsal = feats.get("secondarydorsal", "0") == "+"
    high = feats.get("high", "0")
    back = feats.get("back", "0")
    front = feats.get("front", "0")

    # PALATALIZED: only from explicit secondary-dorsal evidence
    # (or alias), never from primary +dorsal alone.
    if (
        secondary_dorsal and high == "+" and (front == "+" or back == "-")
    ) or feats.get("palatalized", "0") == "+":
        out.add(SecondaryKind.PALATALIZED)

    # VELARIZED: same discipline as palatalised.
    if (secondary_dorsal and high == "+" and back == "+") or feats.get(
        "velarized", "0"
    ) == "+":
        out.add(SecondaryKind.VELARIZED)

    # PHARYNGEALIZED. Three accepted paths: explicit secondary place,
    # pharyngeal evidence layered onto a primary ORAL place (so we
    # don't tag a primary pharyngeal as secondarily pharyngealised),
    # or the explicit alias.
    has_secondary_pharyngeal = (
        feats.get("secondarypharyngeal", "0") == "+"
        or feats.get("secondaryradical", "0") == "+"
    )
    has_oral_primary_place = place in {
        PlaceRank.BILABIAL,
        PlaceRank.LABIODENTAL,
        PlaceRank.DENTAL,
        PlaceRank.ALVEOLAR,
        PlaceRank.POSTALVEOLAR,
        PlaceRank.RETROFLEX,
        PlaceRank.PALATAL,
        PlaceRank.VELAR,
        PlaceRank.UVULAR,
    }
    if (
        has_secondary_pharyngeal
        or (has_oral_primary_place and _is_pharyngeal_like(feats))
        or feats.get("pharyngealized", "0") == "+"
    ):
        out.add(SecondaryKind.PHARYNGEALIZED)

    return frozenset(out)


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


def _segment_sort_key(
    feats: dict[str, str],
    profile: ConsonantProfile | None = None,
) -> tuple[int, ...]:
    """Full feature-based sort key for a segment.

    Slot order: place rank -> legacy :py:data:`_SORT_KEYS` columns
    (manner -> place sub-variant -> phonation -> rounding ->
    height -> length). The legacy column sequence is what keeps
    voiceless / voiced pairs CLUSTERED at each place sub-variant
    (Hayes-style ``k+ / ɡ+``, ``k / ɡ``, ``k͡p / ɡ͡b``, ``k- / ɡ-``):
    front / back / labial sort BEFORE voice, so each place
    sub-variant's pair stays adjacent.

    ``profile`` is threaded into :py:func:`derive_place` so the
    place rank reflects the inventory's palatal/velar convention.
    Without it, the function falls back to Hayes-style behaviour
    (compatible with every call site that has not yet been
    profile-threaded).

    An earlier attempt inserted a typed
    :py:class:`LaryngealKind` slot right after place rank. That
    made phonation dominate the sub-place discriminators and
    split every voiceless / voiced pair across the entire VELAR
    cluster; a regression versus the IPA-conventional pair
    display. The typed-fact infrastructure (PlaceRank,
    LaryngealKind, SecondaryKind) is still consumed by the
    fact-based breakouts and by future renderers; the
    within-group SORT ORDER stays driven by the legacy column
    sequence that demonstrably reads as the IPA chart.
    """
    key: list[int] = [int(derive_place(feats, profile))]
    for feat, ordering in _SORT_KEYS:
        key.append(ordering.get(feats.get(feat, "0"), 2))
    return tuple(key)


def _should_merge_up(group_size: int, inventory_size: int) -> bool:
    """True if a group is too small to stand alone in the display."""
    return group_size < max(3, int(inventory_size * 0.05))


def _should_break_out(subgroup_size: int, inventory_size: int) -> bool:
    """True if a derived subgroup is large enough to display separately.

    At least as strict as ``_should_merge_up`` to prevent
    create-then-destroy churn.
    """
    return subgroup_size >= max(3, int(inventory_size * 0.05))


def _apply_breakout(
    assignment: dict[str, list[str]],
    new_name: str,
    parent_name: str,
    member_pred: Callable[[str], bool],
    inventory_size: int,
    *,
    allow_whole: bool = False,
) -> bool:
    """Peel the parent's members matching ``member_pred`` into
    ``new_name`` and leave the rest under the parent. Returns whether a
    child group was created.

    No-op unless the parent exists and the subgroup is non-empty and
    clears the breakout threshold. When some members do NOT match, the
    subgroup splits off and the rest stay under the parent. When they
    ALL match, the group is homogeneous: it is relabelled to
    ``new_name`` only if ``allow_whole`` is set, which the spec pass
    turns on once a sibling subclass has already split from this parent
    (so a contrasting residue, e.g. the lateral affricates left when the
    sibilant affricates peeled off, gets its specific name while an
    uncontrasted whole group keeps the general one). Shared scaffold for
    the spec-based and fact-based breakout passes; only the membership
    predicate differs between them.
    """
    if parent_name not in assignment:
        return False
    parent_members = list(assignment[parent_name])
    subgroup = [s for s in parent_members if member_pred(s)]
    if not subgroup:
        return False
    if not _should_break_out(len(subgroup), inventory_size):
        return False
    remainder = [s for s in parent_members if s not in subgroup]
    if remainder:
        assignment[parent_name] = remainder
        assignment[new_name] = subgroup
        return True
    if not allow_whole:
        return False
    del assignment[parent_name]
    assignment[new_name] = subgroup
    return True


def _is_vocoid(feats: dict[str, str]) -> bool:
    """Pike's vocoid test for the no-class catch-all routing only.

    A vocoid is a syllabic segment, or a central oral resonant
    (``-consonantal +sonorant +continuant``, non-lateral) i.e. a vowel
    or glide; everything else is a contoid. This only decides which
    catch-all an UNclassifiable segment falls into (vocoids under the
    vowel chart, contoids under the consonants); it does not affect any
    segment a manner/place spec already claimed.
    """
    if feats.get("syllabic", "0") == "+":
        return True
    return (
        feats.get("consonantal", "0") != "+"
        and feats.get("sonorant", "0") == "+"
        and feats.get("continuant", "0") == "+"
        and feats.get("lateral", "0") != "+"
    )


# --------------------------------------------------------------------
# Grouping pipeline stages.
#
# ``group_segments`` runs these in order: assign every segment to a
# primary group, then reshape the group set with the stages below.
# Each stage takes the running ``assignment`` (``{group: [symbol]}``)
# plus the read-only context it needs (the normalised bundles, the set
# of features the inventory actually uses, the inventory size, the
# convention profile) and mutates ``assignment`` in place, except the
# final sort which returns the display payload. Keeping each stage a
# named function lets the pipeline in ``group_segments`` read as a
# sequence of steps rather than one long block of inline loops.
# --------------------------------------------------------------------


def _break_out_by_spec(
    assignment: dict[str, list[str]],
    norm: Mapping[str, dict[str, str]],
    seqs: Mapping[str, Mapping[str, Sequence[str]]],
    active_features: set[str],
    n: int,
    multi_segs: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Peel spec-defined subclasses off their manner parents.

    Each :data:`DERIVED_BREAKOUTS` entry names a child group, its
    parent, and the feature spec a member must match (Sibilants off
    Fricatives, Lateral Fricatives / Sibilant Affricates / Lateral
    Affricates / Lateral Flaps off their manner homes). The skip-guard
    keeps a split from firing when the inventory does not carry every
    feature the condition needs, so an inventory silent on ``strident``
    never grows an empty Sibilants row.

    The match reads a feature's whole value SEQUENCE, an existential
    test with no privileged phase: the Lateral-Affricates split fires
    when SOME phase carries ``[+lateral]`` (for a lateral affricate the
    source happens to write it on the fricated phase, but the test
    never asks which). For a non-contour feature the sequence is one
    value, so this is identical to a plain value test.
    """
    spawned_from: set[str] = set()
    for new_name, parent_name, cond in DERIVED_BREAKOUTS:
        if not all(f in active_features for f in cond):
            continue

        def _spec_match(s: str, cond: dict[str, str] = cond) -> bool:
            if s in multi_segs:
                # A multi-membership segment stays in each coarse class it
                # reaches; peeling it into an onset-derived sub-class would
                # privilege a phase.
                return False
            for f, v in cond.items():
                tier = seqs.get(s, {}).get(f)
                vals = set(tier) if tier else {norm[s].get(f, "0")}
                if v not in vals:
                    return False
            return True

        created = _apply_breakout(
            assignment,
            new_name,
            parent_name,
            _spec_match,
            n,
            allow_whole=parent_name in spawned_from,
        )
        if created:
            spawned_from.add(parent_name)


def _break_out_by_laryngeal_kind(
    assignment: dict[str, list[str]],
    norm: Mapping[str, dict[str, str]],
    n: int,
    multi_segs: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Peel Implosives / Ejective {Plosives, Fricatives, Affricates}
    off their manner parents using the typed :class:`LaryngealKind`
    derived per segment.

    Runs AFTER :func:`_break_out_by_spec` so the more specific spec
    classes (Sibilants, Lateral Fricatives, Sibilant Affricates,
    Lateral Affricates) absorb their members first; a sibilant ejective
    therefore lands in Sibilants, not Ejective Fricatives.

    No syllabic-vowel guard is needed: the consonant-group invariant in
    ``is_member`` already rejected vowels from every parent in
    ``PRIMARY_GROUPS``, so the breakouts only see consonants. The
    relabel passes and laryngeal rescue below inherit the same
    guarantee.

    Unlike :func:`_break_out_by_spec` this reads the COLLAPSED bundle
    (``derive_laryngeal_kind(norm[s])``), not the tiers. That is a
    deliberate economy, not an oversight: the source never contours a
    laryngeal feature (verified corpus-wide: zero laryngeal tiers
    longer than one), so the collapsed value IS the tier singleton for
    every feature this read consults. If a future source encodes
    laryngeal contours, lift this to the same ``set(tier)`` existential
    read the spec breakout uses.
    """
    for new_name, parent_name, target_kind in _FACT_BREAKOUTS:

        def _kind_match(s: str, kind: LaryngealKind = target_kind) -> bool:
            if s in multi_segs:
                return False
            return derive_laryngeal_kind(norm[s]) == kind

        _apply_breakout(assignment, new_name, parent_name, _kind_match, n)


def _fold_small_groups_into_parents(
    assignment: dict[str, list[str]],
    n: int,
) -> None:
    """Iteratively fold each too-small group into its
    :data:`_MERGE_PARENT` until nothing else qualifies.

    A group under the merge threshold is absorbed into its parent (a
    lone Sibilants group folds back into Fricatives); every
    ``_MERGE_PARENT`` edge points a tier-driven refinement at its
    reach parent, so folding only coarsens granularity and never moves
    a segment off its reached-class subtree. The loop repeats so a
    fold that leaves the parent itself small can cascade. Frozen
    groups (Plosives) never fold.
    """
    changed = True
    while changed:
        changed = False
        for gname in list(assignment.keys()):
            if gname in _FROZEN_GROUPS:
                continue
            if not _should_merge_up(len(assignment[gname]), n):
                continue
            parent = _MERGE_PARENT.get(gname)
            if parent is not None:
                assignment.setdefault(parent, []).extend(assignment.pop(gname))
                changed = True


def _sort_into_display_order(
    assignment: Mapping[str, list[str]],
    norm: Mapping[str, dict[str, str]],
    profile: ConsonantProfile,
) -> dict[str, list[str]]:
    """Emit ``{group: [symbol, ...]}`` in ``DISPLAY_ORDER``, each
    group's symbols sorted by :func:`_segment_sort_key` (place first,
    then the manner / laryngeal / secondary tiebreakers). Empty groups
    are dropped."""
    return {
        name: sorted(
            # dedup WITHIN a group (a segment may appear in several groups
            # under the multiset, but never twice in one), order-stable
            # via the sort key below
            dict.fromkeys(assignment[name]),
            key=lambda s: _segment_sort_key(norm[s], profile),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }


# Pulmonic-obstruent specs a click's oral closure must NOT satisfy: a
# click is its own (velaric) airstream, so it reaches Clicks, never
# Plosives/Fricatives. Nasality/sonorance ARE orthogonal (a nasal click
# IS nasal), so those specs still see a click phase.
_CLICK_EXCLUDES: frozenset[str] = frozenset({"Plosives", "Fricatives"})

# The coarse manner specs the ∃-reach considers: PRIMARY_GROUPS minus the
# hard-gated Clicks / Vowels / Tones. Clicks are handled by an explicit
# ∃click test (best_primary hard-gates click:+ to Clicks); Vowels/Tones
# are the major-class split, not a consonant manner reached here.
#: ``(name, spec, min_pos, excludes_clicks)`` per coarse class. The
#: positive-evidence floor and the click exclusion depend only on the
#: class NAME, so they are resolved once here instead of once per
#: segment per spec on the grouping hot path.
_REACH_SPECS: list[tuple[str, dict[str, str], int, bool]] = [
    (name, spec, _MIN_POSITIVE.get(name, 1), name in _CLICK_EXCLUDES)
    for name, spec in PRIMARY_GROUPS
    if name not in ("Clicks", VOWEL_GROUP_NAME, TONES_GROUP_NAME)
]


def _reach_phase_bundles(
    tiers: Mapping[str, tuple[str, ...]],
) -> list[dict[str, str]]:
    """Every phase of a segment as a ``{feature: value}`` bundle. Aligned
    tiers give their columns; a ragged (Misaligned) segment gives its two
    total anchors (onset + offset), the endpoints the source pins even
    when the interior has no derivable alignment."""
    varying = {f: t for f, t in tiers.items() if len(t) > 1}
    lengths = {len(t) for t in varying.values()}
    if len(lengths) > 1:
        onset = {f: t[0] for f, t in tiers.items()}
        offset = {f: t[-1] for f, t in tiers.items()}
        return [onset, offset]
    n = lengths.pop() if lengths else 1
    return [
        {f: (t[i] if len(t) == n else t[0]) for f, t in tiers.items()}
        for i in range(n)
    ]


def _reach_bundle_matches(
    bundle: Mapping[str, str], spec: dict[str, str], min_pos: int
) -> bool:
    """is_member's positive-evidence test on one phase bundle: count spec
    features the bundle states matching, require >= min_pos. The major
    class is guarded by the caller."""
    matched = 0
    for feat, want in spec.items():
        val = bundle.get(feat, "0")
        if val == "0":
            continue
        if val != want:
            return False
        matched += 1
    return matched >= min_pos


def reached_classes(
    norm_bundle: Mapping[str, str],
    seg_seqs: Mapping[str, Sequence[str]],
) -> set[str]:
    """The set of COARSE manner classes a segment EXISTENTIALLY reaches:
    some phase satisfies the class's is_member test (plus the affricate
    ∃-rule and the click gate). This is the substance-free membership the
    multiset display renders; a genuinely multi-phase segment reaches
    several classes and no phase is privileged. ``mb`` reaches Nasals (its
    nasal phase) and Plosives (its oral-stop phase).

    ``norm_bundle`` is the segment's normalized single-value bundle and
    ``seg_seqs`` its contour sequences, both keyed by the engine's
    canonical feature name (so ``Velaric`` reads as ``click``). Reads the
    tiers only; never a group label or a chosen phase. This is the ONE
    source of truth, shared with the ∃-reach fixture generator.
    """
    phases: Sequence[Mapping[str, str]]
    if any(len(t) > 1 for t in seg_seqs.values()):
        tiers: dict[str, tuple[str, ...]] = {
            f: (v,) for f, v in norm_bundle.items()
        }
        for feat, seq in seg_seqs.items():
            tiers[feat] = tuple(str(v) for v in seq)
        phases = _reach_phase_bundles(tiers)
        delrel_plus = "+" in tiers.get("delrel", ())
    else:
        # No genuine contour (every tier is a single value; ~96% of
        # segments, since ``_sequences_by_seg`` hands every segment a
        # bundle of singletons and only true contours are longer). The
        # one phase IS the normalized bundle: a singleton sequence value
        # always equals the normalized value (both read the same raw
        # cell, and normalization folds only the key, never the value),
        # so overlaying the singletons onto the norm-derived tiers is a
        # no-op and the tiers -> _reach_phase_bundles round-trip reduces
        # to exactly this bundle. Skip both allocations.
        phases = (norm_bundle,)
        delrel_plus = norm_bundle.get("delrel", "0") == "+"
    reached: set[str] = set()
    if any(b.get("click") == "+" for b in phases):
        reached.add("Clicks")
    has_closure = any(
        b.get("consonantal") == "+"
        and b.get("sonorant") != "+"
        and b.get("continuant") == "-"
        and b.get("click") != "+"
        for b in phases
    )
    if has_closure and delrel_plus:
        reached.add("Affricates")
    # Per-PHASE major-class facts are properties of the phase alone, so
    # they are computed once here rather than re-derived for every one
    # of the ~15 specs below (the guards used to run spec-times per
    # phase). A vowel or tone phase never satisfies a consonant manner
    # spec and drops out entirely; a click phase survives but is barred
    # from the pulmonic-obstruent classes.
    consonant_phases: list[tuple[Mapping[str, str], bool]] = []
    for bundle in phases:
        consonantal = bundle.get("consonantal")
        if bundle.get("syllabic") == "+" and consonantal != "+":
            continue  # vowel phase
        if (
            bundle.get("tone") == "+"
            and consonantal != "+"
            and bundle.get("syllabic") != "+"
        ):
            continue  # tone phase
        consonant_phases.append((bundle, bundle.get("click") == "+"))
    for name, spec, min_pos, excludes_clicks in _REACH_SPECS:
        for bundle, is_click in consonant_phases:
            if is_click and excludes_clicks:
                continue  # a click closure is not a pulmonic obstruent
            if _reach_bundle_matches(bundle, spec, min_pos):
                reached.add(name)
                break
    return reached


def group_segments(
    inventory: Mapping[str, Mapping[str, str]],
    *,
    normalized: Mapping[str, dict[str, str]] | None = None,
    sequences: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    place_sorted: bool = True,
) -> dict[str, list[str]]:
    """Assign every segment to a phonological display group.

    Returns ``{group_label: [symbol, ...]}`` in ``DISPLAY_ORDER``.

    ``normalized`` optionally carries the per-segment bundles
    already passed through :py:func:`normalize_feature_bundle`.
    Callers that hold the engine's cached
    ``normalized_segment_feats`` pass it so the inventory is not
    re-normalized on every grouping (this sits on the interactive
    inventory-switch path).

    ``sequences`` optionally maps each segment to its per-feature VALUE
    SEQUENCES, already keyed in the grouper's namespace (the release of
    an affricate; the later qualities of a di/triphthong). A feature's
    value across the whole segment is the SET of values in its sequence.
    This is what identifies an affricate uniformly: an obstruent is an
    affricate when some position is ``[-continuant]`` (a stop closure)
    AND some position is ``[+delayed release]`` (a fricated release),
    which catches both the ``DelRel`` collapse and the ``continuant``
    contour PHOIBLE uses for the same segments, and separates a true
    affricate from a stop that merely releases into a sonorant. The sequence's
    ``lateral`` / ``strident`` values then tell a lateral affricate
    from a sibilant one (the source happens to write them on the
    fricated phase; the test is existential and never asks which).
    Reading each feature's own sequence is faithful for ragged
    segments too and matches the query membership cache. A
    caller that passes nothing sees every segment as single-valued (its
    primary bundle), so collapse-encoded affricates still classify; only
    the contour-encoded ones lose their affricate reading.
    """
    if not inventory:
        return {}
    norm: Mapping[str, dict[str, str]] = (
        normalized
        if normalized is not None
        else {
            sym: normalize_feature_bundle(feats)
            for sym, feats in inventory.items()
        }
    )
    seqs: Mapping[str, Mapping[str, Sequence[str]]] = sequences or {}

    def phase_values(sym: str, feat: str) -> set[str]:
        """The set of values ``feat`` takes across ``sym``'s whole value
        sequence. A non-contour feature yields ``{primary_value}``; a
        contour feature yields every value it traverses, so a membership
        test (``"+" in phase_values(...)``) reads the whole segment."""
        tier = seqs.get(sym, {}).get(feat)
        if tier:
            return set(tier)
        return {norm[sym].get(feat, "0")}

    active_features: set[str] = set()
    for feats in norm.values():
        for k, v in feats.items():
            if v != "0":
                active_features.add(k)
    for seg_seqs in seqs.values():
        for k, tier in seg_seqs.items():
            if any(v != "0" for v in tier):
                active_features.add(k)
    # Inventory-level convention flags discovered once and threaded
    # into the per-segment sort key. Mirrors the vowel chart's
    # VowelProfile pattern so a Hayes-style inventory and a general
    # feature-system inventory both produce IPA-correct place
    # rankings without per-segment guesswork.
    profile = detect_consonant_profile(norm)

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
        group_name: str,
        seg_feats: dict[str, str],
        spec: dict[str, str],
        is_vowel_phoneme: bool,
        is_tone_phoneme: bool,
    ) -> bool:
        """Test whether a segment matches a group spec.

        Universal major-class invariant: the matcher partitions
        segments into three disjoint phoneme classes:

        - **Vowel-phonemes**: ``Syllabic=+`` AND ``Consonantal!=+``
          (true vowels including nasalised vowels like ``ã``)
        - **Tone-phonemes**: a positive tone marker (generic
          ``tone`` as PHOIBLE states it, or ``hightone`` as PanPhon
          does) AND no positive consonant/vowel major-class features
          (Chao tone letters ``˥˦˧˨˩`` shipped by PHOIBLE)
        - **Consonants**: everything else, including syllabic
          consonants like ``m̩``/``n̩``

        Each phoneme class lives in exactly one home group
        (``Vowels``, ``Tones``, or a consonant manner class) and
        is rejected from the other two. Without these guards:

        - The bare ``Nasals`` spec (``{nasal: +}``) absorbs
          nasalised vowels (the original bug for Acehnese ``ã``).
        - Standalone tone letters fall through ``is_member`` (no
          consonant features match) and the fallback assigner
          routes them to Affricates by document order; this
          previously affected ~860 PHOIBLE inventories.

        The guards live in the matcher so the property is inherent
        to the pipeline rather than something every group spec has
        to remember to encode, and they stay feature-set agnostic:
        Hayes, PHOIBLE, and PanPhon all share ``Syllabic``,
        ``Consonantal``, and ``HighTone`` columns under the same
        canonical app names.

        Syllabic consonants (``Syllabic=+, Consonantal=+``, e.g.
        Lomongo's ``m̩``/``n̩``/``ŋ̩``) are NOT vowel-phonemes
        under this dichotomy, so they keep their manner-class
        membership (e.g. Nasals). That matches the IPA convention
        and the bundled-inventory snapshot.
        """
        # ``is_vowel_phoneme`` / ``is_tone_phoneme`` are per-SEGMENT
        # major-class facts (independent of group / spec), so the
        # caller computes them once per segment and threads them in
        # rather than this matcher recomputing them for every group
        # it is tested against.
        if group_name == VOWEL_GROUP_NAME:
            if not is_vowel_phoneme:
                return False
        elif group_name == TONES_GROUP_NAME:
            # Membership IS the tone-phoneme fact; the spec cannot be
            # matched because different sources mark tonality with
            # different features (generic ``tone`` vs ``hightone``).
            return is_tone_phoneme
        else:
            if is_vowel_phoneme or is_tone_phoneme:
                return False
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

        Three optional declared-class primitives are honoured for
        consonants, since the standard feature bundle cannot recover
        them and an inventory author may state them outright:

          * ``rhotic:+`` routes to ``Rhotics``. The declared specific
            class beats feature-inferred manner (rhoticity is not
            derivable from the symbol or place). Gated to consonants:
            ``rhotic`` is also a vowel feature (``ɚ``/``ɝ``).
          * ``flap:+`` folds into ``Taps & Flaps`` (some inventories
            split tap and flap; the display groups them together).
          * ``liquid:+`` anchors the ``Liquids`` cover, yielding only
            to a more specific lateral approximant (``+lateral`` falls
            through to the manner match -> Lateral Approximants).
            Without the anchor a declared liquid, being itself a
            sonorant continuant, would always be claimed by the generic
            Central Approximants spec.

        These are read only here, in display grouping; they do not
        change feature-query behaviour (a query against ``liquid`` or
        ``rhotic`` still behaves like any other inventory feature).
        """
        if seg_feats.get("click", "0") == "+":
            return "Clicks"
        # Per-segment major-class facts: computed ONCE here and passed
        # into every ``is_member`` test for this segment (the matcher
        # used to recompute them per group, the hottest redundancy on
        # the inventory-switch path).
        consonantal = seg_feats.get("consonantal", "0")
        syllabic = seg_feats.get("syllabic", "0")
        is_vowel_phoneme = syllabic == "+" and consonantal != "+"
        is_tone_phoneme = (
            (
                seg_feats.get("tone", "0") == "+"
                or seg_feats.get("hightone", "0") == "+"
            )
            and consonantal != "+"
            and syllabic != "+"
        )
        is_consonant = not is_vowel_phoneme and not is_tone_phoneme
        if is_consonant:
            # Explicit declared-class primitives beat inferred manner.
            # Precedence rhotic > flap > liquid: the most specific
            # declaration wins, with the broad liquid cover checked
            # last (and itself yielding to a lateral approximant).
            if seg_feats.get("rhotic", "0") == "+":
                return "Rhotics"
            if seg_feats.get("flap", "0") == "+":
                return "Taps & Flaps"
            # ``liquid:+`` anchors Liquids, but a lateral approximant is
            # the more specific group (the one the policy names), so a
            # ``+lateral`` segment falls through to the manner match.
            if (
                seg_feats.get("liquid", "0") == "+"
                and seg_feats.get("lateral", "0") != "+"
            ):
                return "Liquids"
        matches = [
            (
                name,
                positive_matches(seg_feats, spec),
                sum(1 for f in spec if f in active_features),
            )
            for name, spec in PRIMARY_GROUPS
            if is_member(
                name, seg_feats, spec, is_vowel_phoneme, is_tone_phoneme
            )
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
            if name in _FROZEN_GROUPS or name in _GATED_GROUPS:
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
        # Require POSITIVE evidence. A segment whose only "win" is zero
        # mismatches with zero matches (every relevant feature left
        # unspecified) resembles no class; hand it to the caller's
        # Contoid / Vocoid catch-all instead of the first group that
        # happened to reference a feature the segment never specifies.
        if best_matches < 1:
            return ""
        return best_name

    # Stage 1: assign every segment to its display group(s). ONE
    # membership computation drives every routing decision here:
    # ``reached_classes``, the same existential read over the tiers the
    # ∃-reach fixture generator uses. No collapsed-bundle gate sits in
    # front of it. (The old ``affricate_group`` pre-check read the
    # COLLAPSED ``sonorant``, so a prenasalized affricate whose collapse
    # kept the obstruent value was swallowed into Affricates and never
    # reached Nasals: membership decided by a collapse convention
    # instead of the tiers.) A vowel-like segment (reaching
    # ``[+syllabic]`` in some phase, e.g. a rising diphthong) stays on
    # the single-pick path so it routes to the vowel area, not into
    # consonant manner rows; a declared class primitive (``rhotic`` /
    # ``flap`` / ``liquid``), which ``best_primary`` honours as a
    # definite single class the standard bundle cannot recover, is not
    # scattered across manner rows. Everything else routes by its reach:
    # exactly-an-affricate takes the specific class, several classes
    # take the multiset, one class takes that class, and a reach the
    # specs cannot name falls to the positive-evidence ``best_primary``,
    # the mismatch-minimising fallback, then the Contoid / Vocoid
    # catch-all so nothing vanishes.
    assignment: dict[str, list[str]] = defaultdict(list)
    multi_reach: dict[str, set[str]] = {}
    for sym, feats in norm.items():
        reached = reached_classes(feats, seqs.get(sym, {}))
        # A PLAIN affricate is a segment whose reach beyond Plosives /
        # Fricatives is exactly Affricates. Its closure phase
        # necessarily satisfies the Plosives spec and a fricated
        # release the Fricatives spec, but those are the affricate's
        # OWN phases (the structure the ∃-rule is defined by), not
        # further memberships, so it displays as the single specific
        # class rather than scattering. Any OTHER class alongside
        # Affricates (a nasal onset ``ndz``, a tap release ``d-ʒɾ``)
        # is genuinely disjoint and routes through the multiset below,
        # whatever the collapsed bundle happens to say.
        if reached - {"Plosives", "Fricatives"} == {"Affricates"}:
            assignment["Affricates"].append(sym)
            continue
        is_vowelish = "+" in phase_values(sym, "syllabic")
        declared = (
            feats.get("rhotic", "0") == "+"
            or feats.get("flap", "0") == "+"
            or feats.get("liquid", "0") == "+"
        )
        if not is_vowelish and not declared:
            if len(reached) > 1:
                # Genuine multi-membership (``mb`` reaches Nasals AND
                # Plosives; a nasal click reaches Clicks AND Nasals):
                # appended to EVERY class it reaches, never a
                # privileged phase.
                multi_reach[sym] = reached
                for group in reached:
                    assignment[group].append(sym)
                continue
            if len(reached) == 1:
                # Single existential reach: the tiers name the class
                # directly. For a single-phase segment this is provably
                # the ``best_primary`` answer (same specs, same
                # values); for a manner contour it keeps the pick on
                # the tiers where the collapsed bundle could disagree.
                assignment[next(iter(reached))].append(sym)
                continue
        group = best_primary(feats) or fallback_assignment(feats)
        if not group:
            group = (
                VOCOID_GROUP_NAME if _is_vocoid(feats) else CONTOID_GROUP_NAME
            )
        assignment[group].append(sym)

    # Stages 2-8: reshape the group set. Each stage is a named function
    # above; read them top-to-bottom to trace how the raw per-segment
    # assignment becomes the final class list. The breakouts SKIP the
    # multi-membership segments (``multi_segs``): a segment that reaches
    # several coarse classes stays in each of them and must not be
    # peeled into a sub-class, which would privilege a phase and diverge
    # from its existential reach.
    #
    # Display membership is REACH-FAITHFUL: every label a segment
    # displays under is a coarse class it existentially reaches, a
    # tier-driven refinement of one (the breakouts), or the fold of
    # such a refinement back into its reach parent. Population size
    # may decide GRANULARITY (whether a reach class is subdivided or
    # folded back), never MEMBERSHIP: the retired population covers
    # (Trills+Taps -> Vibrants -> Rhotics relabels, the derived-pair
    # Liquids merges, the laryngeal rescue) moved single-membership
    # segments off their reached-class subtree by inventory-dependent
    # co-occurrence, so the same trill displayed under different
    # labels in different inventories. Rhotics / Liquids / Taps &
    # Flaps remain reachable ONLY through the declared primitives
    # (``rhotic`` / ``liquid`` / ``flap``), which are source
    # assertions, not covers.
    n = len(inventory)
    multi_segs = frozenset(multi_reach)
    _break_out_by_spec(assignment, norm, seqs, active_features, n, multi_segs)
    _break_out_by_laryngeal_kind(assignment, norm, n, multi_segs)
    _fold_small_groups_into_parents(assignment, n)

    # Pin every multi-membership segment to EXACTLY its coarse ∃-reach
    # classes. The pin runs AFTER every surviving display stage (the
    # breakouts and the parent folds), so no stage, present or future,
    # can move a multi-answer segment off the classes its tiers
    # determine: a multi segment follows the set theory, never a
    # display convenience. This is the substance-free pin
    # (Bale & Reiss 2018; Reiss 2021) and keeps the multiset stable.
    for sym, target in multi_reach.items():
        for name in list(assignment):
            if name not in target and sym in assignment[name]:
                assignment[name] = [s for s in assignment[name] if s != sym]
        for name in target:
            if sym not in assignment[name]:
                assignment[name].append(sym)

    # Stage 9: emit in display order, each group place-sorted.
    # ``place_sorted=False`` keeps the identical group MEMBERSHIP
    # (same dedup, same DISPLAY_ORDER, same empty-drop) but skips the
    # per-segment place sort, which is pure display ordering: the
    # class-cap counter reads only membership, and sorting for it was
    # a fifth of the grouping phase spent on an order nobody consumes.
    if not place_sorted:
        return {
            name: list(dict.fromkeys(assignment[name]))
            for name in DISPLAY_ORDER
            if assignment.get(name)
        }
    return _sort_into_display_order(assignment, norm, profile)


# Per-class cap counting and validation moved to
# ``chart.segment_classes``: that is application cap POLICY, not the
# grouping algorithm this module owns. ``segment_classes`` imports
# ``group_segments`` from here.


def visible_groups(
    groups: Mapping[str, list[str]],
    hidden: Collection[str],
) -> dict[str, list[str]]:
    """Drop hidden class labels from a grouping, order preserved.

    The display-side filter behind the segment-class visibility
    toggle. It does NOT touch :py:func:`group_segments` (the canonical
    grouping is unchanged); it only removes whole classes the user has
    chosen to hide so each UI reflows over the remaining classes and
    reclaims the freed space. Kept here, beside the grouping it
    filters, so the desktop and the web apply identical semantics
    (the web mirrors this filter in JS over the same payload).
    """
    hidden_set = frozenset(hidden)
    return {
        label: list(segs)
        for label, segs in groups.items()
        if label not in hidden_set
    }
