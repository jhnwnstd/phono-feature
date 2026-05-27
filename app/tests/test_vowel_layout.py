"""Vowel-chart placement contract tests.

The placement code looks up canonical lowercase feature names
(``high``, ``low``, ``front``, etc.) inside each feature bundle.
Inventory JSON typically uses PascalCase keys (``High``, ``Low``).
``gui.vowel_layout`` is case-insensitive at its entry, so callers
can pass either form. These tests lock that contract in:

* PascalCase and lowercase inputs MUST produce identical placements
  for every vowel of every bundled inventory.

* On the real English inventory, no vowel may collapse to the
  Open-mid Central default cell unless the inventory genuinely
  underspecifies that vowel. This catches the original "all vowels
  fall through to default" regression where wrong-case keys made
  the entire vowel chart degenerate to a single cell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.vowel_layout import (
    VowelProfile,
    compute_placements,
    detect_vowel_profile,
    vowel_grid_pos,
)

INVENTORIES_DIR = (
    Path(__file__).resolve().parents[1] / "inventories"
)


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    if not path.exists():
        pytest.skip(f"inventory not present: {name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments
        if engine.segments[s].get("Syllabic") == "+"
    ]


@pytest.mark.parametrize(
    "inv_filename",
    [
        "english_features.json",
        "general_features.json",
        "hayes_features.json",
    ],
)
def test_vowel_placement_case_insensitive(inv_filename: str) -> None:
    """vowel_grid_pos and detect_vowel_profile must produce the
    same output whether the caller passes raw (PascalCase) feats or
    normalized (lowercase) feats."""
    engine = _engine(inv_filename)
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip(f"{inv_filename} has no vowels")
    raw_feats = {s: dict(engine.segments[s]) for s in vowels}
    lower_feats = {
        s: {k.lower(): v for k, v in bundle.items()}
        for s, bundle in raw_feats.items()
    }
    raw_profile = detect_vowel_profile(vowels, raw_feats)
    lower_profile = detect_vowel_profile(vowels, lower_feats)
    assert raw_profile == lower_profile, (
        f"profile differs between raw and normalized keys: "
        f"{raw_profile} vs {lower_profile}"
    )
    for seg in vowels:
        raw_p = vowel_grid_pos(raw_feats[seg], raw_profile)
        lower_p = vowel_grid_pos(lower_feats[seg], lower_profile)
        assert raw_p == lower_p, (
            f"/{seg}/ placement differs: raw={raw_p}, lower={lower_p}"
        )


def test_english_vowels_not_all_in_default_cell() -> None:
    """Regression: with case-insensitive lookup wired correctly, the
    English vowel chart MUST spread vowels across multiple cells.
    The original bug had every vowel landing in (row=3, col=2) =
    Open-mid Central because the lookups missed PascalCase keys.
    """
    engine = _engine("english_features.json")
    vowels = _vowel_segs(engine)
    assert vowels, "English should have vowels"
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    placements = [
        vowel_grid_pos(seg_feats[s], profile) for s in vowels
    ]
    unique_cells = {(p.row, p.col) for p in placements}
    # English has ~13 vowels spanning ~9 cells in the IPA chart.
    # Anything under 4 unique cells means the case-sensitivity bug
    # is back (or the bundled inventory was rewritten unrecognizably).
    assert len(unique_cells) >= 4, (
        f"English vowels collapsed into {len(unique_cells)} cell(s); "
        f"case-insensitive placement appears broken. Cells: {unique_cells}"
    )


# compute_placements: shared cell-grouping helper

def test_compute_placements_groups_collisions_general():
    """The General inventory's ə, ɜ, ɚ all map to the open-mid
    central cell (3, 2). The shared compute_placements groups them
    so both the desktop and the web render them stacked rather
    than overlapping at the same CSS-grid coordinates.
    """
    engine = _engine("general_features.json")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(vowels, profile, seg_feats)
    assert (3, 2) in occupied
    cell_segs = occupied[(3, 2)]
    assert set(cell_segs) == {"ə", "ɜ", "ɚ"}
    # Every segment in the cell has a corresponding placement entry.
    for s in cell_segs:
        assert s in placements


def test_compute_placements_orders_by_confidence_desc():
    """Within a collision cell, the highest-confidence vowel sorts
    first so the desktop renders it on top and the web stacks it at
    the top of the visible stack."""
    engine = _engine("general_features.json")
    vowels = _vowel_segs(engine)
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    occupied, placements = compute_placements(vowels, profile, seg_feats)
    for key, segs_in_cell in occupied.items():
        if len(segs_in_cell) < 2:
            continue
        confidences = [placements[s].confidence for s in segs_in_cell]
        # Sorted in DESCENDING confidence order.
        assert confidences == sorted(confidences, reverse=True), (
            f"cell {key} not sorted by confidence desc: {confidences}"
        )


# Constants: immutability

def test_module_constants_are_tuples():
    """ROW_LABELS / COL_LABELS / VOWEL_HEIGHT are exported as
    tuples so importers cannot mutate the shared singletons."""
    import phonology_features.gui.vowel_layout as vl

    assert isinstance(vl.ROW_LABELS, tuple)
    assert isinstance(vl.COL_LABELS, tuple)
    assert isinstance(vl.VOWEL_HEIGHT, tuple)
    # Spot-check shape so a future re-shape is a deliberate break.
    assert len(vl.ROW_LABELS) == 6
    assert vl.COL_LABELS == ("Front", "Central", "Back")


# PascalCase normalization

def test_pascal_case_feats_match_lowercase(profile):
    """The placement code accepts either PascalCase or lowercase
    keys; both must produce identical results so callers passing
    raw inventory feats are not silently routed to the default
    cell."""
    pascal = vowel_grid_pos(
        {"High": "+", "Low": "-", "Front": "+", "Round": "-"},
        profile,
    )
    lower = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "round": "-"},
        profile,
    )
    assert pascal == lower


# compute_placements: sort order within a collision cell

def test_compute_placements_sort_segment_ascending_within_tier(profile):
    """Within a confidence tier, segments sort in ASCENDING string
    order so collision-cell ordering is stable and predictable.
    The prior implementation used ``reverse=True`` on the whole
    sort tuple, which silently reversed segment order too."""
    # Three vowels at the same placement, same confidence: alphabetical
    # ASCending order must come out of compute_placements.
    feats = {
        "a": {"high": "-", "low": "+"},   # Open central
        "b": {"high": "-", "low": "+"},
        "c": {"high": "-", "low": "+"},
    }
    occupied, _placements = compute_placements(
        ["c", "a", "b"], profile, feats
    )
    # All three should land in the same cell.
    [cell] = occupied.values()
    assert cell == ["a", "b", "c"], (
        f"expected alphabetical ASC within tier, got {cell}"
    )


# _infer_rounding: distinct reasons for [-round] vs no round


def test_inferred_rounding_reason_distinguishes_explicit_negative(profile):
    """An explicit ``[-round]`` should produce a different reason
    string than an entirely absent Round feature, so audits / UI
    tooltips can tell the difference between "explicitly unrounded"
    and "unspecified for rounding"."""
    explicit_neg = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "round": "-"},
        profile,
    )
    no_round = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+"},
        profile,
    )
    assert "[-round]" in explicit_neg.reason
    assert "no round specified" in no_round.reason
    assert explicit_neg.reason != no_round.reason


# _infer_backness: explicit [-front] handling


def test_negative_front_with_no_back_marks_low_confidence(profile):
    """``[-front]`` alone is ambiguous between central and back.
    Conservative default to central with LOW confidence and a
    reason that surfaces the ambiguity, matching the documented
    chart-placement policy."""
    placement = vowel_grid_pos(
        {"high": "-", "low": "-", "front": "-"},
        profile,
    )
    assert "[-front]" in placement.reason
    # Either "unresolved" or "ambiguous" wording; the test names
    # the policy intent rather than the exact string.
    assert "unresolved" in placement.reason or "ambiguous" in placement.reason


def test_negative_front_with_negative_back_is_more_confident_than_front_alone(profile):
    """``[-front, -back]`` is the canonical central spec; ``[-front]``
    alone is genuinely ambiguous between central and back. Pin
    height unambiguously so the overall placement confidence
    reflects only the backness inference."""
    both = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "-", "back": "-"},
        profile,
    )
    front_only = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "-"},
        profile,
    )
    assert both.confidence > front_only.confidence
    # And the explicit-both case lands at central (col 2), not back.
    assert both.col == 2


# _height_split_value: tense/ATR conflict handling


def test_tense_atr_agreement_uses_either(profile):
    """When tense and ATR are both present and agree, the close
    placement applies and the reason notes the source."""
    p_tense = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+"},
        profile,
    )
    p_atr = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "atr": "+"},
        profile,
    )
    p_both = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+", "atr": "+"},
        profile,
    )
    # All three land at Close (row 0).
    assert p_tense.row == p_atr.row == p_both.row == 0


def test_tense_overrides_conflicting_atr(profile):
    """When tense and ATR disagree, tense wins (a documented
    inventory-policy choice) and the reason string records the
    override so the choice is auditable."""
    placement = vowel_grid_pos(
        {"high": "+", "low": "-", "front": "+", "tense": "+", "atr": "-"},
        profile,
    )
    # tense=+, atr=- -> tense wins -> Close (row 0)
    assert placement.row == 0
    assert "overrides" in placement.reason


@pytest.fixture
def profile():
    """Default profile with every feature considered active. Tests
    that don't care about the fallback gating can use this."""
    return VowelProfile(
        has_front=True,
        has_round=True,
        has_labial=True,
        has_atr=True,
        has_tense=True,
        has_coronal=True,
    )
