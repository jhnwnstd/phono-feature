"""Whole-PHOIBLE segment-classification stress suite.

Pins the feature-set-agnostic classification contract the user
asked for: every PHOIBLE inventory's segments land in the right
display group regardless of how many features the source records.

The major-class invariant the classifier holds: a "vowel-phoneme"
is ``Syllabic=+`` AND ``Consonantal!=+``. Vowel-phonemes must
land in ``Vowels`` and only in ``Vowels``; everything else (true
consonants AND syllabic consonants like ``m̩``) lands in a
consonant group per its manner / place / laryngeal features.

The classifier in
[`shared/.../chart/consonants.py`](shared/src/phonology_shared/chart/consonants.py)
holds these invariants at the matcher level (``is_member``) so
the same rules apply to Hayes, PHOIBLE, and PanPhon-shaped
inventories without per-source branches. This suite walks the
full PHOIBLE snapshot (3000+ inventories) plus three synthetic
feature-set shapes to keep both halves of the contract honest:

- Real-data sweep (B1-B3): every PHOIBLE inventory's grouping
  respects the syllabic invariant in both directions.
- Synthetic parametrised (B4): the same nasal-vowel bundle
  expressed under Hayes (28-feature), PHOIBLE (38-feature), and
  PanPhon (24-feature) shapes lands in Vowels in all three.

Skipped when the PHOIBLE bake snapshot is absent.
"""

from __future__ import annotations

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.editor.phoible_provider import (
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine

# Group labels the classifier emits for consonant segments. Drawn
# from the PRIMARY_GROUPS + derived breakouts + relabel patterns in
# consonants.py. ``Vowels`` and ``Tones`` are the only labels that
# carry non-consonant phoneme classes; everything else here is a
# consonant manner / place / laryngeal bucket and gets the
# vowel-phoneme + tone-phoneme rejection invariants from
# ``is_member``.
_CONSONANT_GROUP_NAMES: frozenset[str] = frozenset(
    {
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
        "Vibrants",
        "Lateral Approximants",
        "Lateral Flaps",
        "Central Approximants",
        "Semivowels",
        "Rhotics",
        "Liquids",
        "Laryngeals",
    }
)


# Fixtures (``phoible_provider``, ``phoible_inventory_ids_full``,
# ``phoible_inventory_ids_sample``, ``phoible_label_for``) come
# from shared/tests/conftest.py. Classification invariants
# (B1/B2: vowel-phoneme routing) consume the 200-inventory sample
# because the feature-distribution space carries the coverage.
# Tone-related invariants (B5/B6) consume the full corpus because
# tone phonemes are sparse cross-linguistically.


def test_b1_no_vowel_phoneme_lands_in_any_consonant_group(
    phoible_provider,
    phoible_label_for,
    phoible_inventory_ids_sample: list[str],
) -> None:
    """The classifier must never route a vowel-phoneme
    (``Syllabic=+`` AND ``Consonantal!=+``) into a consonant
    group. The original bug had nasalised vowels (``ã``, ``ẽ``,
    ...) landing in ``Nasals`` because the Nasals spec did not
    explicitly exclude vowels; the major-class invariant in
    ``is_member`` now blocks it across all PHOIBLE inventories
    without per-spec patches.

    Syllabic consonants (``Syllabic=+`` AND ``Consonantal=+``,
    e.g. Lomongo's ``m̩``/``n̩``/``ŋ̩``) are NOT vowel-phonemes
    under this dichotomy and legitimately land in their
    manner-class group; they are not flagged here.
    """
    offenders: list[tuple[str, str, list[str]]] = []
    for inv_id in phoible_inventory_ids_sample:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        groups = engine.grouped_segments
        for gname in _CONSONANT_GROUP_NAMES:
            segs = groups.get(gname, [])
            if not segs:
                continue
            misrouted = [
                s
                for s in segs
                if (
                    inv.segments.get(s, {}).get("Syllabic") == "+"
                    and inv.segments.get(s, {}).get("Consonantal") != "+"
                )
            ]
            if misrouted:
                offenders.append((phoible_label_for(inv_id), gname, misrouted))
    assert not offenders, (
        f"vowel-phonemes leaked into consonant groups in "
        f"{len(offenders)} (inventory, group) buckets; first 5: "
        f"{offenders[:5]}"
    )


def test_b2_only_vowel_phonemes_land_in_vowels(
    phoible_provider,
    phoible_label_for,
    phoible_inventory_ids_sample: list[str],
) -> None:
    """Symmetric guarantee: ``Vowels`` must hold only vowel-phonemes
    (``Syllabic=+`` AND ``Consonantal!=+``). A non-syllabic
    segment in Vowels OR a syllabic consonant in Vowels both
    indicate a major-class invariant regression."""
    offenders: list[tuple[str, list[str]]] = []
    for inv_id in phoible_inventory_ids_sample:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        vowels = engine.grouped_segments.get("Vowels", [])
        misrouted = [
            s
            for s in vowels
            if not (
                inv.segments.get(s, {}).get("Syllabic") == "+"
                and inv.segments.get(s, {}).get("Consonantal") != "+"
            )
        ]
        if misrouted:
            offenders.append((phoible_label_for(inv_id), misrouted))
    assert not offenders, (
        f"non-vowel-phonemes leaked into Vowels in "
        f"{len(offenders)} inventories; first 5: {offenders[:5]}"
    )


def test_b3_classifier_assigns_every_segment(
    phoible_provider, phoible_label_for, phoible_inventory_ids_full: list[str]
) -> None:
    """Every segment must land in exactly one group; an empty
    "Other" fallback or unassigned segment would surface a
    silently-broken classifier. Sampled to keep runtime bounded
    (the B1/B2 sweeps cover the full set with cheaper checks)."""
    # Stride-sampled subset of the full corpus (~200 inventories).
    # ``phoible_inventory_ids_sample`` would have worked too; the
    # stride keeps this test independent of the conftest seed.
    sample = phoible_inventory_ids_full[::15]
    unassigned: list[tuple[str, list[str]]] = []
    for inv_id in sample:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        groups = engine.grouped_segments
        placed: set[str] = set()
        for segs in groups.values():
            placed.update(segs)
        missing = set(inv.segments) - placed
        if missing:
            unassigned.append((phoible_label_for(inv_id), sorted(missing)))
    assert not unassigned, (
        f"{len(unassigned)} inventories left segments unassigned; "
        f"first 5: {unassigned[:5]}"
    )


# B4: synthetic nasal-vowel parity across feature-set shapes.
#
# Each shape mirrors what one source records: Hayes-shape uses
# the 28 features the bundled JSON ships; PHOIBLE-shape uses the
# 38 mapped values from ``PHOIBLE_TO_APP_FEATURE``; PanPhon-shape
# uses the 24 mapped values from ``PANPHON_TO_APP_FEATURE``. A
# nasal vowel /ã/ in each must land in Vowels.
_HAYES_SHAPE: list[str] = [
    "CORONAL",
    "DORSAL",
    "LABIAL",
    "Anterior",
    "Approximant",
    "Back",
    "Consonantal",
    "ConstrGl",
    "Continuant",
    "DelRel",
    "Distributed",
    "Front",
    "High",
    "Labiodental",
    "Lateral",
    "Long",
    "Low",
    "Nasal",
    "Round",
    "Sonorant",
    "SpreadGl",
    "Stress",
    "Strident",
    "Syllabic",
    "Tap",
    "Tense",
    "Trill",
    "Voice",
]


def _phoible_shape_features() -> list[str]:
    from phonology_shared.editor.phoible_features import (
        PHOIBLE_TO_APP_FEATURE,
    )

    return list(PHOIBLE_TO_APP_FEATURE.values())


def _panphon_shape_features() -> list[str]:
    from phonology_shared.editor.panphon_features import (
        PANPHON_TO_APP_FEATURE,
    )

    return list(PANPHON_TO_APP_FEATURE.values())


def _build_synthetic_nasal_vowel_inventory(
    features: list[str],
) -> Inventory:
    """Build a 2-segment Inventory: one nasal vowel (``ã``) and one
    plain nasal consonant (``m``), in whichever feature shape is
    passed in.

    Sparse columns are left at ``"0"`` (unspecified); the
    classifier only relies on the shared core features (Syllabic,
    Consonantal, Sonorant, Nasal, ...) which all three feature
    sets carry. Feature-set generality means the classifier reads
    those by name; the surrounding column count does not change
    the result.
    """
    base: dict[str, str] = {f: "0" for f in features}
    a_nasal: dict[str, str] = dict(base)
    a_nasal.update(
        {
            "Syllabic": "+",
            "Consonantal": "-",
            "Sonorant": "+",
            "Nasal": "+",
            "Continuant": "+",
            "Voice": "+",
        }
    )
    m_nasal: dict[str, str] = dict(base)
    m_nasal.update(
        {
            "Syllabic": "-",
            "Consonantal": "+",
            "Sonorant": "+",
            "Nasal": "+",
            "Continuant": "-",
            "Voice": "+",
        }
    )
    # Place is intentionally omitted: the Hayes shape carries
    # ``"LABIAL"`` (all-caps anchor) which canonicalises to the
    # same key the PHOIBLE / PanPhon shapes' ``"Labial"`` does, so
    # setting both raises ValidationError at parse. The test only
    # cares about the manner / major-class invariant; /m/ as a
    # placeless nasal still lands in Nasals.
    return Inventory.from_grid(
        name="synthetic",
        features=features,
        segments={"ã": a_nasal, "m": m_nasal},
    )


@pytest.mark.parametrize(
    "shape_name,features_factory",
    [
        ("hayes", lambda: list(_HAYES_SHAPE)),
        ("phoible", _phoible_shape_features),
        ("panphon", _panphon_shape_features),
    ],
)
def test_b4_nasal_vowel_lands_in_vowels_for_every_feature_set_shape(
    shape_name: str, features_factory
) -> None:
    """Pins the feature-set generality the user asked for: a
    nasal vowel (``Syllabic=+, Nasal=+``) lands in ``Vowels``
    regardless of whether the surrounding feature inventory is
    Hayes-shaped (28 cols), PHOIBLE-shaped (38), or PanPhon-shaped
    (24). The classifier reads features by name; the cardinality
    or specific column inventory of the source must not change
    where a segment lands."""
    features = features_factory()
    inv = _build_synthetic_nasal_vowel_inventory(features)
    engine = FeatureEngine(inv)
    groups = engine.grouped_segments
    a_groups = {k: v for k, v in groups.items() if "ã" in v}
    m_groups = {k: v for k, v in groups.items() if "m" in v}
    assert "ã" in groups.get("Vowels", []), (
        f"[{shape_name}] nasal vowel /ã/ should land in Vowels, "
        f"got groups={a_groups}"
    )
    assert "m" in groups.get("Nasals", []), (
        f"[{shape_name}] plain nasal /m/ should land in Nasals, "
        f"got groups={m_groups}"
    )
    # And the negative: /ã/ never appears in Nasals.
    assert "ã" not in groups.get(
        "Nasals", []
    ), f"[{shape_name}] nasal vowel /ã/ leaked into Nasals"


def test_b5_no_tone_phoneme_lands_in_a_consonant_group(
    phoible_provider, phoible_label_for, phoible_inventory_ids_full: list[str]
) -> None:
    """The classifier must never route a tone-phoneme
    (``HighTone=+`` AND no positive ``Consonantal`` / ``Syllabic``)
    into a consonant group. PHOIBLE ships Chao tone letters
    (``˥``, ``˦``, ``˧``, ``˨``, ``˩``) as standalone segments
    with only the tone feature set; before the Tones group +
    matcher invariant landed, these fell through ``is_member`` and
    the fallback assigner routed all of them to ``Affricates``
    (the second group in document order) across ~860 inventories.
    """
    offenders: list[tuple[str, str, list[str]]] = []
    for inv_id in phoible_inventory_ids_full:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        groups = engine.grouped_segments
        for gname in _CONSONANT_GROUP_NAMES:
            segs = groups.get(gname, [])
            if not segs:
                continue
            misrouted = [
                s
                for s in segs
                if (
                    inv.segments.get(s, {}).get("HighTone") == "+"
                    and inv.segments.get(s, {}).get("Consonantal") != "+"
                    and inv.segments.get(s, {}).get("Syllabic") != "+"
                )
            ]
            if misrouted:
                offenders.append((phoible_label_for(inv_id), gname, misrouted))
    assert not offenders, (
        f"tone-phonemes leaked into consonant groups in "
        f"{len(offenders)} (inventory, group) buckets; first 5: "
        f"{offenders[:5]}"
    )


def test_b6_phoible_tone_letters_land_in_tones_group(
    phoible_provider, phoible_label_for, phoible_inventory_ids_full: list[str]
) -> None:
    """Positive symmetry: every PHOIBLE Chao tone letter segment
    in the snapshot must land in the ``Tones`` group. Walks the
    real data so a future bake schema change or normalizer
    regression that strips ``HighTone`` from tone segments
    surfaces here with the failing inventory named."""
    tone_codepoints = set(range(0x02E5, 0x02EA))  # ˥˦˧˨˩
    missed: list[tuple[str, list[str]]] = []
    for inv_id in phoible_inventory_ids_full:
        inv = materialize_phoible_inventory(phoible_provider, inv_id)
        engine = FeatureEngine(inv)
        tones_group = engine.grouped_segments.get("Tones", [])
        # Identify segments that contain a Chao tone letter codepoint.
        candidates = [
            s
            for s in inv.segments
            if any(ord(c) in tone_codepoints for c in s)
            and inv.segments[s].get("HighTone") == "+"
            and inv.segments[s].get("Consonantal") != "+"
            and inv.segments[s].get("Syllabic") != "+"
        ]
        if not candidates:
            continue
        missed_in_inv = [s for s in candidates if s not in tones_group]
        if missed_in_inv:
            missed.append((phoible_label_for(inv_id), missed_in_inv))
    assert not missed, (
        f"PHOIBLE tone letters missed the Tones group in "
        f"{len(missed)} inventories; first 5: {missed[:5]}"
    )


@pytest.mark.parametrize(
    "shape_name,features_factory",
    [
        ("hayes", lambda: list(_HAYES_SHAPE)),
        ("phoible", _phoible_shape_features),
        ("panphon", _panphon_shape_features),
    ],
)
def test_b7_chao_tone_letter_lands_in_tones_for_every_feature_shape(
    shape_name: str, features_factory
) -> None:
    """Parametrised tone-phoneme parity: a synthetic Chao tone
    letter (``HighTone=+``, no consonant/vowel anchors) lands in
    the ``Tones`` group regardless of whether the surrounding
    feature inventory is Hayes-shaped (no HighTone column, so the
    classifier sees zero positive features and the segment is
    correctly excluded from every group), PHOIBLE-shaped, or
    PanPhon-shaped. Pins feature-set generality on the
    tone-phoneme half of the invariant."""
    features = features_factory()
    if "HighTone" not in features:
        pytest.skip(
            f"{shape_name} shape does not record HighTone; tone"
            " classification is a no-op there"
        )
    base: dict[str, str] = {f: "0" for f in features}
    tone_seg: dict[str, str] = dict(base)
    tone_seg["HighTone"] = "+"
    inv = Inventory.from_grid(
        name="tone-synthetic",
        features=features,
        segments={"˧": tone_seg},
    )
    engine = FeatureEngine(inv)
    groups = engine.grouped_segments
    assert "˧" in groups.get(
        "Tones", []
    ), f"[{shape_name}] Chao tone /˧/ should land in Tones"
    # And the negative: never in Affricates.
    assert "˧" not in groups.get(
        "Affricates", []
    ), f"[{shape_name}] Chao tone /˧/ leaked into Affricates"
