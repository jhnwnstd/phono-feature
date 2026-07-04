"""Scaffold for the DEFERRED multi-membership pass (group_segments
partition -> multiset). These assertions ENCODE the end state so the
implementation becomes wiring against tests that already exist, per the
staged plan. The multiset-dependent cases are ``xfail`` until the flip
lands (today a contour consonant sits in the provisional
``Contour Consonants`` tag, not in every class it reaches); they flip to
``xpass`` when group_segments becomes a multiset, at which point the
``xfail`` marks come off in the same commit that retires the tag.

The END STATE (substance-free): a segment renders in EVERY manner class
its tiers existentially reach, driven by the engine's quantified
membership, never by a privileged phase. `mb` reaches a nasal spec in one
phase and an oral-stop spec in another, so it renders in Nasals AND
Plosives. The frozen fixture ``fixtures/contour_tag_reach.json`` is the
validated ground truth for which classes each currently-tagged segment
must appear in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart.consonants import CONTOUR_GROUP_NAME
from phonology_shared.data.inventory import Inventory
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    materialize_phoible_inventory,
)
from phonology_shared.theory.feature_engine import FeatureEngine

_FIXTURES = Path(__file__).parent / "fixtures"
_FIXTURE = json.loads((_FIXTURES / "contour_tag_reach.json").read_text())

def _mb_engine() -> FeatureEngine:
    feats = ["Consonantal", "Sonorant", "Continuant", "Nasal", "Syllabic"]
    segs = {
        "mb": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "b": {
            "Consonantal": "+",
            "Sonorant": "-",
            "Continuant": "-",
            "Nasal": "-",
            "Syllabic": "-",
        },
        "m": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "n": {
            "Consonantal": "+",
            "Sonorant": "+",
            "Continuant": "-",
            "Nasal": "+",
            "Syllabic": "-",
        },
        "a": {
            "Consonantal": "-",
            "Sonorant": "+",
            "Continuant": "+",
            "Nasal": "-",
            "Syllabic": "+",
        },
    }
    return FeatureEngine(
        Inventory.from_grid(
            name="t",
            features=feats,
            segments=segs,
            metadata={
                "segment_sequences": {
                    "mb": {"Sonorant": ["+", "-"], "Nasal": ["+", "-"]}
                }
            },
        )
    )


def _members(groups: dict[str, list[str]], seg: str) -> set[str]:
    return {name for name, segs in groups.items() if seg in segs}


def test_prenasalized_stop_renders_in_nasals_and_plosives() -> None:
    """END STATE: `mb` appears in BOTH Nasals and Plosives (∃-nasal,
    ∃-oral-stop), and in NO provisional tag."""
    groups = _mb_engine().grouped_segments
    assert "mb" in groups.get("Nasals", [])
    assert "mb" in groups.get("Plosives", [])
    assert CONTOUR_GROUP_NAME not in groups


def test_no_contour_tag_group_survives_the_multiset() -> None:
    """END STATE: the provisional tag group is gone; multi-membership
    replaces it everywhere."""
    assert CONTOUR_GROUP_NAME not in _mb_engine().grouped_segments


def test_single_phase_segments_stay_in_exactly_one_class() -> None:
    """INVARIANT (holds now AND after): a single-phase consonant has one
    coarse manner membership; the multiset must not scatter it. This is a
    standing regression guard, NOT xfail — the multiset changes only the
    genuinely multi-phase (contour) segments."""
    groups = _mb_engine().grouped_segments
    for seg in ("b", "m", "n"):
        # exactly one consonant manner class (Vowels/Tones excluded)
        homes = _members(groups, seg)
        assert len(homes) == 1, (seg, homes)


def test_full_corpus_multiset_membership_equals_fixture_reach() -> None:
    """END STATE: over PHOIBLE, every currently-tagged glyph renders in
    exactly the manner classes the frozen ∃-reach fixture records for it
    (and never in the tag). This is the fixture doing its job as the
    multiset's validated ground truth."""
    editor = Path(__file__).resolve().parents[1] / "src"
    editor = editor / "phonology_shared" / "editor"
    if not (editor / "_phoible_data.generated.json").exists():
        pytest.skip("baked PHOIBLE snapshot absent")
    idx = json.loads((editor / "_phoible_index.generated.json").read_text())
    dat = json.loads((editor / "_phoible_data.generated.json").read_text())
    provider = PhoibleProvider(index_table=idx, data_table=dat)
    recorded = _FIXTURE["segments"]
    checked = 0
    for entry in idx["inventories"][:80]:
        inv = materialize_phoible_inventory(provider, entry["id"])
        groups = FeatureEngine(inv).grouped_segments
        assert CONTOUR_GROUP_NAME not in groups
        for glyph in recorded:
            if glyph in inv.segments:
                assert _members(groups, glyph) == set(recorded[glyph]), glyph
                checked += 1
    assert checked >= 20
