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
