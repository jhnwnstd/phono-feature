"""Assign inventory segments to phonological display groups.

Pipeline: primary manner-class assignment, derived breakouts (for
example Sibilants from Fricatives), relational relabeling (Rhotics,
Liquids), small-group merging, laryngeal rescue, then sort. Each step
is keyed to the active feature set so inventories that lack a feature
skip the related step.

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
from collections.abc import Mapping
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
    (VOWEL_GROUP_NAME, {"syllabic": "+"}),
    # Suprasegmental tone letters (Chao ``˥˦˧˨˩`` plus combining
    # tone diacritics). PHOIBLE ships these as standalone segments
    # with only ``HighTone=+`` and no consonant / vowel features;
    # before this group existed, the fallback assigner routed them
    # to Affricates by document order. The ``is_member`` invariant
    # below (the tone-phoneme guard) gates this group symmetrically
    # to the vowel-phoneme guard. Feature-set general: PHOIBLE maps
    # ``tone`` -> ``HighTone`` and PanPhon maps ``hitone`` ->
    # ``HighTone``; Hayes does not record standalone tone letters
    # so the group simply stays empty on Hayes inventories.
    (TONES_GROUP_NAME, {"hightone": "+"}),
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
    # A small Trills or Taps group merges up into Vibrants (the
    # feature-justified trill+tap cover), NOT Central Approximants: a
    # trill/tap is not an approximant, and routing it through Central
    # Approximants was the path that let a place-blind trill (e.g. the
    # bilabial /ʙ/) drift on into a Liquids relabel. Rhoticity is not
    # recoverable from the features, so Trills/Taps never imply liquid.
    "Trills": "Vibrants",
    "Taps & Flaps": "Vibrants",
    "Implosives": "Plosives",
    "Ejective Plosives": "Plosives",
    "Ejective Fricatives": "Fricatives",
    "Ejective Affricates": "Affricates",
}
# Exempt from upward merging; laryngeal rescue can still peel members.
_FROZEN_GROUPS: set[str] = {"Plosives"}
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
    VOWEL_GROUP_NAME,
    # Tones render after the segmental classes so the chart reads
    # consonants first, then vowels, then the suprasegmental tier.
    TONES_GROUP_NAME,
]
# Origin-set -> display label for relational relabeling.
#
# "Liquids" only forms when Central Approximants participate. A central
# approximant is the best feature-system proxy for an r-like rhotic
# approximant, so its presence is what licenses calling a lateral +
# vibrant cluster a liquid system. The features establish "trill",
# "tap", and "lateral approximant"; they do NOT establish that a trill
# or tap is rhotic. So "Lateral Approximants + Trills" (and the tap and
# trill+tap variants) are deliberately absent here: relabeling those to
# Liquids with no central-approximant anchor is what swept the place-
# blind bilabial trill /ʙ/ into Liquids. Trills + Taps still merge to
# the feature-justified "Vibrants" below.
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
}
_DERIVED_MERGES: list[tuple[frozenset[str], str]] = [
    # Vibrants fold into an EXISTING Liquids (which only forms when a
    # central approximant participated, see _RELABEL_PATTERNS), and
    # Rhotics (already central-approximant-anchored) fold into Liquids
    # with laterals. There is deliberately NO Vibrants + Lateral
    # Approximants -> Liquids merge: that is "any lateral + any vibrant
    # -> liquid" with nothing establishing rhoticity, the path that
    # re-leaked /ʙ/ into Liquids after the relabel pass produced a
    # Vibrants group.
    (frozenset({"Vibrants", "Liquids"}), "Liquids"),
    (frozenset({"Rhotics", "Lateral Approximants"}), "Liquids"),
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
    EPIGLOTTAL = 10
    GLOTTAL = 11
    VOWEL_OR_UNKNOWN = 12


def _is_pharyngeal_like(feats: dict[str, str]) -> bool:
    """Conventional pharyngeal-evidence patterns: explicit
    ``+pharyngeal``, explicit ``+constrpharynx``, or the
    ``+radical +rtr`` combination characteristic of pharyngeal
    constrictions made with tongue-root retraction.
    """
    return (
        feats.get("pharyngeal", "0") == "+"
        or feats.get("constrpharynx", "0") == "+"
        or (feats.get("radical", "0") == "+" and feats.get("rtr", "0") == "+")
    )


def _is_epiglottal_like(feats: dict[str, str]) -> bool:
    """Conventional epiglottal-evidence patterns: explicit
    whole-larynx features (``+epilaryngeal`` /
    ``+aryepiglottic``), or the ``+radical +constrpharynx +rtr``
    triple Moisik / Esling-style inventories use to mark the
    aryepiglottic stricture mechanism. The triple is a strict
    superset of the pharyngeal ``+radical +rtr`` pattern, so
    :py:func:`derive_place` must call this BEFORE
    :py:func:`_is_pharyngeal_like` to avoid the broader pharyngeal
    rule absorbing every epiglottal candidate.
    """
    return (
        feats.get("epilaryngeal", "0") == "+"
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
    Reads only conventional distinctive features --
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
                if feats.get("anterior", "0") == "-":
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
    The flat names below are the DISPLAY labels the grouper emits,
    not the input vocabulary.

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
    # Tone-phonemes (Chao tone letters, possibly with phonation
    # diacritics like ``˥˧̰``) belong in the Tones group regardless
    # of their laryngeal-feature surface; without this guard the
    # laryngeal rescue below would pull a creaky-toned segment out
    # of Tones into Laryngeals. Mirrors the tone-phoneme guard in
    # ``is_member``.
    is_tone = (
        feats.get("hightone", "0") == "+"
        and feats.get("consonantal", "0") != "+"
        and not is_vowel
    )
    return (
        has_laryngeal
        and not has_place
        and not is_vowel
        and not is_click
        and not is_tone
    )


def group_segments(
    inventory: Mapping[str, Mapping[str, str]],
    *,
    normalized: Mapping[str, dict[str, str]] | None = None,
    contour_feats: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, list[str]]:
    """Assign every segment to a phonological display group.

    Returns ``{group_label: [symbol, ...]}`` in ``DISPLAY_ORDER``.

    ``normalized`` optionally carries the per-segment bundles
    already passed through :py:func:`normalize_feature_bundle`.
    Callers that hold the engine's cached
    ``normalized_segment_feats`` pass it so the inventory is not
    re-normalized on every grouping (this sits on the interactive
    inventory-switch path).

    ``contour_feats`` optionally maps each segment to the
    (normalized) feature names that take BOTH ``+`` and ``-`` across
    its phases, i.e. the features that contour within the segment.
    It identifies affricates that carry no ``DelRel`` feature: an
    obstruent whose ``continuant`` contours (stop -> fricative) is an
    affricate even when nothing marks delayed release. The engine
    derives it from :py:meth:`Inventory.segment_phases`; callers that
    pass nothing simply lose contour-based affricate inference (the
    ``DelRel`` spec path is unaffected).
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
    active_features: set[str] = set()
    for feats in norm.values():
        for k, v in feats.items():
            if v != "0":
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
        - **Tone-phonemes**: ``HighTone=+`` AND no positive
          consonant/vowel major-class features (Chao tone letters
          ``˥˦˧˨˩`` shipped by PHOIBLE)
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
            if not is_tone_phoneme:
                return False
        else:
            if is_vowel_phoneme or is_tone_phoneme:
                return False
        # Affrication needs a positive signal. With ``DelRel`` active,
        # the spec's ``delrel: +`` is that signal (a plain stop carries
        # ``delrel: -`` and is rejected below). With no ``DelRel`` in
        # the inventory the spec degenerates to a bare stop spec
        # (``consonantal +, continuant -, sonorant -``) and, sitting
        # earlier than Plosives, would claim every stop. Refuse the
        # spec entirely in that case: the only affricates an inventory
        # without delayed release can name are the ones a ``continuant``
        # contour marks, handled by ``affricate_by_contour`` below.
        if group_name == "Affricates" and "delrel" not in active_features:
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
            seg_feats.get("hightone", "0") == "+"
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

    contours = contour_feats or {}

    def affricate_by_contour(sym: str, seg_feats: dict[str, str]) -> str:
        """``Affricates`` when ``continuant`` contours within an
        obstruent, regardless of ``DelRel``.

        Linguists routinely write an affricate as a single segment
        whose ``continuant`` holds both values (``-`` for the stop
        closure, ``+`` for the fricative release). That contour is
        the affrication, so a ``+consonantal`` non-sonorant carrying
        it is an affricate even with no ``DelRel`` column. The
        obstruent gate keeps the rule off vowels, sonorants, and
        clicks; ``DelRel``-bearing affricates still go through the
        spec path in ``best_primary`` so this only adds the
        delrel-free case rather than changing the existing one.
        """
        if "continuant" not in contours.get(sym, frozenset()):
            return ""
        if seg_feats.get("consonantal", "0") != "+":
            return ""
        if seg_feats.get("sonorant", "0") == "+":
            return ""
        if seg_feats.get("click", "0") == "+":
            return ""
        return "Affricates"

    assignment: dict[str, list[str]] = defaultdict(list)
    for sym, feats in norm.items():
        group = (
            affricate_by_contour(sym, feats)
            or best_primary(feats)
            or fallback_assignment(feats)
        )
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

    # Fact-based breakouts: peel Implosives / Ejective {Plosives,
    # Fricatives, Affricates} off their manner parents using the
    # typed :py:class:`LaryngealKind` derived per segment. Runs
    # AFTER the spec-based breakouts so the more specific spec
    # classes (Sibilants, Lateral Fricatives, Sibilant Affricates,
    # Lateral Affricates) absorb their members first; a sibilant
    # ejective therefore lands in Sibilants, not Ejective
    # Fricatives.
    #
    # No syllabic-vowel guard needed here: the consonant-group
    # invariant in :py:func:`is_member` already rejected vowels
    # from every parent in ``PRIMARY_GROUPS``, so the breakouts
    # only see consonants. The relabel patterns and laryngeal
    # rescue below inherit the same guarantee.
    for new_name, parent_name, target_kind in _FACT_BREAKOUTS:
        if parent_name not in assignment:
            continue
        parent_members = list(assignment[parent_name])
        subgroup = [
            s
            for s in parent_members
            if derive_laryngeal_kind(norm[s]) == target_kind
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
    # Relabel-by-origin happens ONLY in the pass above, which fires
    # when every origin group is simultaneously small. Groups
    # combined later by _MERGE_PARENT keep the parent's label: a
    # small Trills group absorbed up displays as Vibrants (its
    # _MERGE_PARENT), never as Liquids. The place-aware pass below then
    # relabels a non-labial, non-lateral Vibrants cover to Rhotics (the
    # cases recoverable from place features), leaving the neutral
    # Vibrants label only for labial (/ʙ/, /ⱱ/) or lateral vibrants. A
    # second origin-set relabel pass used to sit here, but it rebuilt
    # its origin map from the already-merged assignment, so it could
    # never fire; the bundled-inventory grouping snapshot pins this.
    for pair, label in _DERIVED_MERGES:
        present = [g for g in sorted(pair) if g in assignment]
        if label == "Liquids":
            # An explicit ``liquid:-`` on every member of a group is a
            # declaration that they are NOT liquids; never force such a
            # group (e.g. a declared +rhotic -liquid set) into the
            # Liquids cover. This is a no-op for any inventory whose
            # segments do not carry an explicit ``liquid`` feature.
            present = [
                g
                for g in present
                if not all(
                    norm[s].get("liquid", "0") == "-" for s in assignment[g]
                )
            ]
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
    # Place-aware rhotic relabel. Both the trill+tap cover relabel above
    # and the lone-trill/tap _MERGE_PARENT fold land in the place-neutral
    # "Vibrants" group, because a trill or tap is not rhotic by manner
    # alone: a bilabial trill /ʙ/ or labiodental flap /ⱱ/ is a vibrant,
    # not a rhotic. But a Vibrants cover whose members are ALL non-labial
    # and non-lateral IS a rhotic system (coronal/uvular trills, taps,
    # flaps), and that is recoverable from the standard place features
    # without a declared ``rhotic`` primitive. Relabel such a cover to
    # "Rhotics"; a cover that includes any labial vibrant (/ʙ/, /ⱱ/) or a
    # lateral flap (/ɺ/) keeps the neutral "Vibrants" label. This runs
    # AFTER the merge passes, so a feature-derived rhotic system stays its
    # own row (e.g. Hindi: "Rhotics" beside "Lateral Approximants")
    # instead of folding into the Liquids cover, which remains reserved
    # for the declared / central-approximant-anchored path above.
    vibrants = assignment.get("Vibrants")
    if vibrants and all(
        norm[s].get("labial", "0") != "+"
        and norm[s].get("lateral", "0") != "+"
        for s in vibrants
    ):
        assignment.setdefault("Rhotics", []).extend(assignment.pop("Vibrants"))
    if _LARYNGEAL_FEATURES & active_features:
        # The "Laryngeals" row (h / ɦ / ʔ pulled out of their manner
        # classes) is a convenience regroup, so it must not make the
        # display WORSE by leaving a singleton behind. Two guards, in
        # the spirit of the ``_should_break_out`` discipline the manner
        # breakouts already use:
        #   * stranding: never peel a group's laryngeals if that would
        #     leave the group with exactly one member. A lone /ɦ/ reads
        #     better beside the other fricatives than stranding /f/
        #     alone in a singleton Fricatives row (the Hindi case).
        #     Emptying the group (it was all laryngeal) is fine.
        #   * worthwhileness: only raise the row once >= 2 members
        #     qualify; a single laryngeal stays in its manner home.
        # When a guard blocks the peel the laryngeals stay where they
        # are (h/ɦ among the fricatives, ʔ among the plosives), which
        # is the standard manner-by-place chart layout anyway.
        peelable: dict[str, list[str]] = {}
        for gname in list(assignment.keys()):
            if gname == "Laryngeals":
                continue
            members = assignment[gname]
            cands = [s for s in members if _is_laryngeal_candidate(norm[s])]
            if cands and len(members) - len(cands) != 1:
                peelable[gname] = cands
        if sum(len(c) for c in peelable.values()) >= 2:
            laryngeal_segs: list[str] = []
            for gname, cands in peelable.items():
                for sym in cands:
                    assignment[gname].remove(sym)
                laryngeal_segs.extend(cands)
                if not assignment[gname]:
                    del assignment[gname]
            assignment.setdefault("Laryngeals", []).extend(laryngeal_segs)
    return {
        name: sorted(
            assignment[name],
            key=lambda s: _segment_sort_key(norm[s], profile),
        )
        for name in DISPLAY_ORDER
        if assignment.get(name)
    }


# Per-class cap counting and validation moved to
# ``chart.segment_classes``: that is application cap POLICY, not the
# grouping algorithm this module owns. ``segment_classes`` imports
# ``group_segments`` from here.
