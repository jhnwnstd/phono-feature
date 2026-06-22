"""End-to-end contract for the PHOIBLE -> builder -> save flow.

The single most important PHOIBLE integration property: a user can
load a database inventory, edit it in the builder, and save it
locally without silently losing anything. The historical failure
mode was metadata: the grid cannot edit stamps like the PHOIBLE
provenance or the diphthong ``vowel_secondary`` bundles, and the
commit path used to drop them, so a builder round-trip erased the
diphthong arrows from the saved file.
"""

from __future__ import annotations

import os

import pytest

import phonology_web.api as api
from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.view_models import build_inventory_summary
from phonology_shared.theory.feature_engine import FeatureEngine


@pytest.fixture()
def korean_with_diphthongs() -> dict:
    """Load a Korean PHOIBLE source whose chart has diphthong arrows."""
    if not api.phoible_is_available():
        pytest.skip("PHOIBLE snapshot not baked on this checkout")
    for descriptor in api.phoible_list_inventories("Korean"):
        info = api.load_phoible_inventory(descriptor["id"])
        if info["vowel_chart"].get("diphthongs"):
            return info
    pytest.skip("no Korean source with diphthongs in this snapshot")


def test_phoible_load_status_is_terse(korean_with_diphthongs: dict) -> None:
    """The status line shows language, source, and counts; not the
    full dialect-bearing display name."""
    status = korean_with_diphthongs["status"]
    assert status.startswith("Korean [")
    assert "segments ×" in status and "features" in status
    # The dialect parenthetical stays out of the status line.
    assert "(Korean" not in status


def test_builder_roundtrip_preserves_diphthongs_and_provenance(
    korean_with_diphthongs: dict, tmp_path: object
) -> None:
    info = korean_with_diphthongs
    n_arrows = len(info["vowel_chart"]["diphthongs"])
    assert n_arrows > 0

    # Builder open: grid state from the live engine; user edits one
    # cell and renames the inventory.
    grid = api.get_grid_state()
    cells = grid["cells"]
    for row in cells:
        for c, value in enumerate(row):
            if value == "0":
                row[c] = "+"
                break
        else:
            continue
        break
    summary = api.commit_inventory_from_grid(
        "My Korean (edited)", grid["features"], grid["segments"], cells
    )
    assert len(summary["vowel_chart"]["diphthongs"]) == n_arrows

    # Save locally, reload through the file path, and confirm the
    # arrows and provenance survived the round-trip.
    inv = api._engine.inventory
    assert "vowel_secondary" in inv.metadata
    assert inv.metadata.get("phoible_language") == "Korean"
    path = os.path.join(str(tmp_path), "my_korean.json")
    inv.write_atomic(path)
    reloaded = Inventory.load(path)
    engine = FeatureEngine(reloaded)
    summary2 = build_inventory_summary(
        engine, reloaded.name, "file", mode=api._match_mode
    )
    assert len(summary2["vowel_chart"]["diphthongs"]) == n_arrows
    assert reloaded.metadata.get("feature_source")
    assert reloaded.name == "My Korean (edited)"
