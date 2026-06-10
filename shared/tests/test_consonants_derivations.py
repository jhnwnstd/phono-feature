"""Pin :py:func:`derive_place` and :py:func:`derive_laryngeal_kind`.

These two derivations are the typed-fact entry points for the
consonants grouper expansion. They read only conventional
distinctive features (Laryngeal-node, place-node, place refiners),
never invented ``"velar"`` / ``"velarized"`` / etc. primitives, per
the design discipline documented at the top of
:py:mod:`phonology_shared.chart.consonants`.

Tests are example-based: small feature bundles describing a specific
articulatory profile, asserting the returned :py:class:`PlaceRank` /
:py:class:`LaryngealKind`. They cover the conventional derivation
paths AND the alias-fallback paths so a future refactor that breaks
either kind shows up here before reaching :py:func:`group_segments`.
"""

from __future__ import annotations

from phonology_shared.chart.consonants import (
    ConsonantProfile,
    LaryngealKind,
    PlaceRank,
    SecondaryKind,
    derive_laryngeal_kind,
    derive_place,
    derive_secondary_articulations,
    detect_consonant_profile,
)

# derive_place: each example describes one articulatory target.


def test_place_bilabial_from_labial_only() -> None:
    assert (
        derive_place({"labial": "+", "labiodental": "-"}) == PlaceRank.BILABIAL
    )


def test_place_labiodental_requires_both_labial_and_labiodental() -> None:
    assert (
        derive_place({"labial": "+", "labiodental": "+"})
        == PlaceRank.LABIODENTAL
    )


def test_place_dental_from_anterior_plus_distributed() -> None:
    assert (
        derive_place({"coronal": "+", "anterior": "+", "distributed": "+"})
        == PlaceRank.DENTAL
    )


def test_place_alveolar_from_anterior_minus_distributed() -> None:
    assert (
        derive_place({"coronal": "+", "anterior": "+", "distributed": "-"})
        == PlaceRank.ALVEOLAR
    )


def test_place_postalveolar_from_minus_anterior_plus_distributed() -> None:
    assert (
        derive_place({"coronal": "+", "anterior": "-", "distributed": "+"})
        == PlaceRank.POSTALVEOLAR
    )


def test_place_retroflex_from_minus_anterior_minus_distributed() -> None:
    assert (
        derive_place({"coronal": "+", "anterior": "-", "distributed": "-"})
        == PlaceRank.RETROFLEX
    )


def test_place_palatal_from_dorsal_minus_back_minus_anterior() -> None:
    assert (
        derive_place(
            {"dorsal": "+", "high": "+", "back": "-", "anterior": "-"}
        )
        == PlaceRank.PALATAL
    )


def test_place_velar_from_dorsal_plus_back() -> None:
    assert (
        derive_place({"dorsal": "+", "high": "+", "back": "+"})
        == PlaceRank.VELAR
    )


def test_place_uvular_from_dorsal_minus_high() -> None:
    assert (
        derive_place({"dorsal": "+", "high": "-", "back": "+"})
        == PlaceRank.UVULAR
    )


def test_place_uvular_from_dorsal_plus_low_plus_back() -> None:
    """Alternative uvular evidence pattern from the whole-larynx
    feature traditions: ``+dorsal +back +low``. Snapshot-stable
    because no bundled inventory uses it today; the rule lands
    here so an inventory that DOES adopt the pattern routes
    correctly."""
    assert (
        derive_place({"dorsal": "+", "high": "0", "low": "+", "back": "+"})
        == PlaceRank.UVULAR
    )


def test_place_epiglottal_from_radical_constrpharynx_rtr_triple() -> None:
    """Moisik / Esling-style epiglottal evidence: the
    ``+radical +constrpharynx +rtr`` triple maps to EPIGLOTTAL.
    The check must run BEFORE the pharyngeal-like rule because
    that rule's ``+radical +rtr`` pattern is a strict subset; an
    inverted order would absorb every epiglottal candidate into
    PHARYNGEAL."""
    assert (
        derive_place({"radical": "+", "constrpharynx": "+", "rtr": "+"})
        == PlaceRank.EPIGLOTTAL
    )


def test_place_epiglottal_from_explicit_epilaryngeal() -> None:
    assert derive_place({"epilaryngeal": "+"}) == PlaceRank.EPIGLOTTAL


def test_place_epiglottal_from_explicit_aryepiglottic() -> None:
    assert derive_place({"aryepiglottic": "+"}) == PlaceRank.EPIGLOTTAL


def test_place_pharyngeal_subset_does_not_match_epiglottal() -> None:
    """``+radical +rtr`` without ``+constrpharynx`` stays at the
    pharyngeal rule; the epiglottal triple is strict."""
    assert derive_place({"radical": "+", "rtr": "+"}) == PlaceRank.PHARYNGEAL


def test_place_pharyngeal_from_pharyngeal_feature() -> None:
    assert derive_place({"pharyngeal": "+"}) == PlaceRank.PHARYNGEAL


def test_place_pharyngeal_from_constrpharynx_feature() -> None:
    assert derive_place({"constrpharynx": "+"}) == PlaceRank.PHARYNGEAL


def test_place_glottal_from_constrgl_feature() -> None:
    """``+constrgl`` alone marks glottal place regardless of other
    evidence; this matches the conventional treatment of ʔ."""
    assert derive_place({"constrgl": "+"}) == PlaceRank.GLOTTAL


def test_place_glottal_from_non_consonantal_non_syllabic_fallback() -> None:
    """``/h/`` and ``/ɦ/``: non-consonantal, non-syllabic, no oral
    place evidence. The fallback branch routes them to glottal."""
    assert (
        derive_place({"consonantal": "-", "syllabic": "-"})
        == PlaceRank.GLOTTAL
    )


def test_place_vowel_or_unknown_for_syllabic_vowel() -> None:
    assert derive_place({"syllabic": "+"}) == PlaceRank.VOWEL_OR_UNKNOWN


def test_place_constrgl_overrides_oral_evidence() -> None:
    """Per the current derivation, ``+constrgl`` short-circuits to
    glottal before any oral-place check; verified so a future
    re-ordering surfaces here."""
    assert derive_place({"constrgl": "+", "labial": "+"}) == PlaceRank.GLOTTAL


# derive_laryngeal_kind: conventional-first, aliases fill in the gaps.


def test_laryngeal_plain_voiceless_from_voice_minus_only() -> None:
    assert (
        derive_laryngeal_kind({"voice": "-"}) == LaryngealKind.PLAIN_VOICELESS
    )


def test_laryngeal_plain_voiced_from_voice_plus_only() -> None:
    assert derive_laryngeal_kind({"voice": "+"}) == LaryngealKind.PLAIN_VOICED


def test_laryngeal_aspirated_from_spreadgl_plus_voice_minus() -> None:
    assert (
        derive_laryngeal_kind({"spreadgl": "+", "voice": "-"})
        == LaryngealKind.ASPIRATED
    )


def test_laryngeal_breathy_from_spreadgl_plus_voice_plus() -> None:
    assert (
        derive_laryngeal_kind({"spreadgl": "+", "voice": "+"})
        == LaryngealKind.BREATHY
    )


def test_laryngeal_creaky_from_constrgl_plus_voice_plus_non_stop() -> None:
    """``+constrgl, +voice`` on a continuant or sonorant lands at
    creaky; only stop obstruents go to implosive."""
    assert (
        derive_laryngeal_kind(
            {"constrgl": "+", "voice": "+", "continuant": "+"}
        )
        == LaryngealKind.CREAKY
    )


def test_laryngeal_ejective_requires_obstruent_base() -> None:
    """Conventional path: ``-voice, +constrgl, -sonorant`` to
    EJECTIVE."""
    assert (
        derive_laryngeal_kind({"voice": "-", "constrgl": "+", "sonorant": "-"})
        == LaryngealKind.EJECTIVE
    )


def test_laryngeal_implosive_requires_stop_obstruent_base() -> None:
    """Conventional path: ``+voice, +constrgl, -continuant,
    -sonorant`` to IMPLOSIVE."""
    assert (
        derive_laryngeal_kind(
            {
                "voice": "+",
                "constrgl": "+",
                "continuant": "-",
                "sonorant": "-",
            }
        )
        == LaryngealKind.IMPLOSIVE
    )


def test_laryngeal_implosive_not_inferred_for_nasal_with_constrgl() -> None:
    """A nasal (``-continuant, +sonorant``) carrying
    ``+constrgl, +voice`` is creaky, not implosive: implosive requires
    a stop obstruent base. The current path correctly drops to creaky
    when the obstruent test fails."""
    assert (
        derive_laryngeal_kind(
            {
                "voice": "+",
                "constrgl": "+",
                "continuant": "-",
                "sonorant": "+",
                "nasal": "+",
            }
        )
        == LaryngealKind.CREAKY
    )


def test_laryngeal_ejective_alias_fills_in_when_constrgl_absent() -> None:
    """An inventory that declares ``+ejective`` without the
    conventional ``+constrgl`` should still display as ejective;
    the alias path catches the gap."""
    assert derive_laryngeal_kind({"ejective": "+"}) == LaryngealKind.EJECTIVE


def test_laryngeal_implosive_alias_fills_in_when_constrgl_absent() -> None:
    assert derive_laryngeal_kind({"implosive": "+"}) == LaryngealKind.IMPLOSIVE


def test_laryngeal_breathy_alias_via_slackvoice() -> None:
    """``slackvoice`` is the convention for breathy in some
    inventories; the alias path treats it identically to ``breathy``
    for display purposes."""
    assert derive_laryngeal_kind({"slackvoice": "+"}) == LaryngealKind.BREATHY


def test_laryngeal_creaky_alias_via_stiffvoice() -> None:
    assert derive_laryngeal_kind({"stiffvoice": "+"}) == LaryngealKind.CREAKY


def test_laryngeal_unknown_when_no_evidence() -> None:
    assert derive_laryngeal_kind({}) == LaryngealKind.UNKNOWN


def test_laryngeal_conventional_wins_over_alias() -> None:
    """When both the conventional features and an alias are
    present, the conventional path takes precedence (the user's
    explicit guidance: aliases fill in when underspecified).
    Here, ``+voice -constrgl -spreadgl`` derives PLAIN_VOICED and
    that result is final even though ``+ejective`` is also set."""
    assert (
        derive_laryngeal_kind({"voice": "+", "ejective": "+"})
        == LaryngealKind.PLAIN_VOICED
    )


# derive_secondary_articulations: derive from real features only, never
# from invented "velarized" / "palatalized" primitives.


def test_secondary_empty_for_vowels() -> None:
    """Secondary articulation is a consonantal display fact in this
    grouper. A syllabic segment always returns an empty set."""
    assert (
        derive_secondary_articulations(
            {"syllabic": "+", "round": "+"}, PlaceRank.VOWEL_OR_UNKNOWN
        )
        == frozenset()
    )


def test_secondary_labialized_from_round_on_consonant() -> None:
    """``+round`` on a non-vowel is the practical labialisation
    cue, per the advice. No ``+labialized`` primitive needed."""
    assert SecondaryKind.LABIALIZED in derive_secondary_articulations(
        {"syllabic": "-", "round": "+"}, PlaceRank.VELAR
    )


def test_secondary_labialized_from_secondarylabial_explicit() -> None:
    """When the inventory supplies ``+secondarylabial`` directly,
    that's the cleanest signal and fires regardless of ``round``."""
    assert SecondaryKind.LABIALIZED in derive_secondary_articulations(
        {"syllabic": "-", "secondarylabial": "+"}, PlaceRank.BILABIAL
    )


def test_secondary_labialized_via_labialized_alias() -> None:
    """The optional descriptive alias ``+labialized`` is honored
    when the inventory uses it."""
    assert SecondaryKind.LABIALIZED in derive_secondary_articulations(
        {"syllabic": "-", "labialized": "+"}, PlaceRank.VELAR
    )


def test_secondary_palatalized_requires_secondarydorsal_not_primary_dorsal() -> (
    None
):
    """A bare primary ``+dorsal`` segment is NOT secondarily
    palatalised: that would over-claim every dorsal consonant. The
    derivation requires explicit ``+secondarydorsal`` evidence (or
    the alias)."""
    primary_dorsal_only = derive_secondary_articulations(
        {"syllabic": "-", "dorsal": "+", "high": "+", "back": "-"},
        PlaceRank.PALATAL,
    )
    assert SecondaryKind.PALATALIZED not in primary_dorsal_only

    explicit_secondary = derive_secondary_articulations(
        {
            "syllabic": "-",
            "secondarydorsal": "+",
            "high": "+",
            "back": "-",
        },
        PlaceRank.VELAR,
    )
    assert SecondaryKind.PALATALIZED in explicit_secondary


def test_secondary_palatalized_via_palatalized_alias() -> None:
    """The optional descriptive alias still works when the
    inventory declares ``+palatalized`` directly."""
    assert SecondaryKind.PALATALIZED in derive_secondary_articulations(
        {"syllabic": "-", "palatalized": "+"}, PlaceRank.VELAR
    )


def test_secondary_velarized_requires_secondarydorsal_with_back() -> None:
    explicit_secondary = derive_secondary_articulations(
        {
            "syllabic": "-",
            "secondarydorsal": "+",
            "high": "+",
            "back": "+",
        },
        PlaceRank.ALVEOLAR,
    )
    assert SecondaryKind.VELARIZED in explicit_secondary

    bare_primary_dorsal = derive_secondary_articulations(
        {"syllabic": "-", "dorsal": "+", "high": "+", "back": "+"},
        PlaceRank.VELAR,
    )
    assert SecondaryKind.VELARIZED not in bare_primary_dorsal


def test_secondary_velarized_via_velarized_alias() -> None:
    assert SecondaryKind.VELARIZED in derive_secondary_articulations(
        {"syllabic": "-", "velarized": "+"}, PlaceRank.ALVEOLAR
    )


def test_secondary_pharyngealized_from_pharyngeal_layered_on_oral_place() -> (
    None
):
    """Pharyngeal evidence layered on a segment whose primary
    place is ORAL (here alveolar via the primary ``+coronal``)
    triggers PHARYNGEALIZED. The primary stays alveolar; the
    pharyngealisation is the secondary fact."""
    # +radical +rtr triggers pharyngeal evidence per the centralised
    # helper, layered onto an alveolar primary to pharyngealized.
    feats = {
        "syllabic": "-",
        "coronal": "+",
        "anterior": "+",
        "distributed": "-",
        "radical": "+",
        "rtr": "+",
    }
    assert SecondaryKind.PHARYNGEALIZED in derive_secondary_articulations(
        feats, PlaceRank.ALVEOLAR
    )


def test_secondary_pharyngealized_not_on_primary_pharyngeal() -> None:
    """A segment whose primary place is already PHARYNGEAL is NOT
    also tagged as secondarily pharyngealised; the secondary
    label only makes sense layered onto another oral place."""
    feats = {"syllabic": "-", "pharyngeal": "+"}
    assert SecondaryKind.PHARYNGEALIZED not in derive_secondary_articulations(
        feats, PlaceRank.PHARYNGEAL
    )


def test_secondary_pharyngealized_via_secondarypharyngeal_explicit() -> None:
    feats = {"syllabic": "-", "secondarypharyngeal": "+"}
    assert SecondaryKind.PHARYNGEALIZED in derive_secondary_articulations(
        feats, PlaceRank.ALVEOLAR
    )


def test_secondary_pharyngealized_via_pharyngealized_alias() -> None:
    feats = {"syllabic": "-", "pharyngealized": "+"}
    assert SecondaryKind.PHARYNGEALIZED in derive_secondary_articulations(
        feats, PlaceRank.ALVEOLAR
    )


def test_secondary_multiple_kinds_coexist() -> None:
    """A labialised, pharyngealised alveolar (e.g. an emphatic
    rounded coronal) carries both LABIALIZED and PHARYNGEALIZED in
    the same set; they refine the same segment independently."""
    feats = {
        "syllabic": "-",
        "coronal": "+",
        "anterior": "+",
        "distributed": "-",
        "round": "+",
        "radical": "+",
        "rtr": "+",
    }
    kinds = derive_secondary_articulations(feats, PlaceRank.ALVEOLAR)
    assert {
        SecondaryKind.LABIALIZED,
        SecondaryKind.PHARYNGEALIZED,
    } <= kinds


def test_secondary_no_inference_from_just_dorsal_features() -> None:
    """The most important non-regression of the previous attempt:
    a plain dorsal consonant does NOT pick up palatalised or
    velarised display facts just because it has dorsal/high/back/
    front evidence. Secondary articulation requires explicit
    secondary-place features (or an alias) or, in the
    pharyngealisation case, layered pharyngeal evidence."""
    feats = {
        "syllabic": "-",
        "dorsal": "+",
        "high": "+",
        "back": "+",
    }
    assert (
        derive_secondary_articulations(feats, PlaceRank.VELAR) == frozenset()
    )


# Profile-aware palatal/velar discrimination.
#
# Mirrors the vowel-chart pattern where ``+coronal`` substitutes for
# ``+front`` only when the inventory's profile shows ``+front`` is not in
# active use. Here the discriminator is ``+anterior`` on dorsals: a
# Hayes-style inventory uses ``-anterior`` to mark palatal stops (``c`` /
# ``ɉ``) and the absent value for advanced velars (``k+`` / ``ɡ+``); a
# general feature-system inventory uses ``+front`` and ``-back`` alone.
# Without the profile, ``derive_place`` defaults to Hayes-style behaviour
# so every existing call site keeps working.


_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR = {
    "dorsal": "+",
    "high": "+",
    "back": "-",
    "front": "+",
}


def test_detect_consonant_profile_flags_hayes_style_inventory() -> None:
    """A single ``+dorsal`` segment carrying an explicit ``anterior``
    value flips the flag. Feature theory inventories use anterior
    consistently within a system, so partial evidence is reliable."""
    feats = {
        "c": {"dorsal": "+", "high": "+", "back": "-", "anterior": "-"},
        "i": {"dorsal": "+", "syllabic": "+"},
    }
    assert detect_consonant_profile(feats).dorsals_use_anterior is True


def test_detect_consonant_profile_general_style_default_off() -> None:
    """An inventory whose dorsal segments leave ``anterior``
    unspecified (or set to ``0``) is treated as general-feature-
    system style."""
    feats = {
        "k": {"dorsal": "+", "high": "+", "back": "+"},
        "i": {"dorsal": "+", "syllabic": "+"},
        "n": {"coronal": "+", "anterior": "+"},
    }
    assert detect_consonant_profile(feats).dorsals_use_anterior is False


def test_derive_place_palatal_via_front_when_general_profile() -> None:
    """A general-style inventory: ``+dorsal +high -back +front``
    is enough for PALATAL, no ``-anterior`` required. The Spanish
    ``ʝ`` / ``ɲ`` / ``ʎ`` case becomes IPA-correct."""
    general = ConsonantProfile(dorsals_use_anterior=False)
    assert (
        derive_place(_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR, general)
        == PlaceRank.PALATAL
    )


def test_derive_place_velar_via_anterior_zero_when_hayes_profile() -> None:
    """A Hayes-style inventory: the same ``+dorsal +high -back +front``
    bundle (with ``anterior`` unspecified, i.e. an advanced velar
    like ``k+``) lands at VELAR. The anterior discriminator
    protects against conflating palatal stops with advanced velars."""
    hayes = ConsonantProfile(dorsals_use_anterior=True)
    assert (
        derive_place(_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR, hayes)
        == PlaceRank.VELAR
    )


def test_derive_place_palatal_via_anterior_minus_when_hayes_profile() -> None:
    """Same Hayes-style inventory, but the segment is a true palatal
    (carries ``-anterior``, like Hayes ``c``)."""
    feats = dict(_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR)
    feats["anterior"] = "-"
    hayes = ConsonantProfile(dorsals_use_anterior=True)
    assert derive_place(feats, hayes) == PlaceRank.PALATAL


def test_derive_place_default_profile_is_hayes_style() -> None:
    """Calling ``derive_place`` without a profile preserves the
    pre-extension Hayes-style behaviour: every existing call site
    that has not been profile-threaded keeps working."""
    assert (
        derive_place(_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR) == PlaceRank.VELAR
    )
    feats_with_anterior_minus = dict(_AMBIGUOUS_PALATAL_OR_ADVANCED_VELAR)
    feats_with_anterior_minus["anterior"] = "-"
    assert derive_place(feats_with_anterior_minus) == PlaceRank.PALATAL


def test_derive_place_general_profile_minus_back_alone_is_palatal() -> None:
    """``+dorsal +high -back`` (no ``+front``) still triggers
    PALATAL under general-style logic; the rule is ``+high AND
    (+front OR -back)``, either alone is enough."""
    general = ConsonantProfile(dorsals_use_anterior=False)
    feats = {"dorsal": "+", "high": "+", "back": "-"}
    assert derive_place(feats, general) == PlaceRank.PALATAL


def test_derive_place_general_profile_plus_back_is_velar() -> None:
    """``+dorsal +high +back`` lands at VELAR under both profiles;
    no palatal evidence, so the discriminator never matters."""
    general = ConsonantProfile(dorsals_use_anterior=False)
    feats = {"dorsal": "+", "high": "+", "back": "+"}
    assert derive_place(feats, general) == PlaceRank.VELAR
