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
    LaryngealKind,
    PlaceRank,
    derive_laryngeal_kind,
    derive_place,
)

# ---------------------------------------------------------------------------
# derive_place: each example describes one articulatory target.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# derive_laryngeal_kind: conventional-first, aliases fill in the gaps.
# ---------------------------------------------------------------------------


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
    """Conventional path: ``-voice, +constrgl, -sonorant`` ->
    EJECTIVE."""
    assert (
        derive_laryngeal_kind({"voice": "-", "constrgl": "+", "sonorant": "-"})
        == LaryngealKind.EJECTIVE
    )


def test_laryngeal_implosive_requires_stop_obstruent_base() -> None:
    """Conventional path: ``+voice, +constrgl, -continuant,
    -sonorant`` -> IMPLOSIVE."""
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
    explicit guidance: aliases fill in *when underspecified*).
    Here, ``+voice -constrgl -spreadgl`` derives PLAIN_VOICED and
    that result is final even though ``+ejective`` is also set."""
    assert (
        derive_laryngeal_kind({"voice": "+", "ejective": "+"})
        == LaryngealKind.PLAIN_VOICED
    )
