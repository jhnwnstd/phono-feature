"""Bridge behaviour for user-edited inventory source (metadata.source).

The web editor stages a source string in editorState and threads it
through ``commit_inventory_from_grid``; ``get_grid_state`` hands the
current source back so the editor can seed its box. These pin that the
value round-trips, that a pasted BibTeX entry is rendered to a plain
citation, that an empty source drops the key (no [Source] affordance),
and that ``source=None`` preserves whatever was carried.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phonology_shared.data import Inventory
from phonology_shared.presentation.source_link import classify_source
from phonology_shared.theory import FeatureEngine
from phonology_web import api as bridge

REPO_ROOT = Path(__file__).resolve().parents[2]
HAYES = str(REPO_ROOT / "desktop" / "inventories" / "hayes_features.json")


@pytest.fixture(autouse=True)
def _loaded_engine():
    inv = Inventory.load(HAYES)
    bridge._engine = FeatureEngine(inv)
    bridge._inventory_name = inv.name or "hayes"
    yield
    bridge._engine = None
    bridge._inventory_name = ""


def _commit(source):
    state = bridge.get_grid_state()
    return bridge.commit_inventory_from_grid(
        state["name"],
        state["features"],
        state["segments"],
        state["cells"],
        source,
    )


def test_get_grid_state_exposes_the_loaded_source():
    state = bridge.get_grid_state()
    assert state["source"] == bridge._engine.inventory.metadata["source"]
    assert state["source"].startswith("Hayes, Bruce")


def test_commit_sets_a_plain_citation():
    _commit("Blevins, Juliette (2025). Phonology I.")
    assert (
        bridge._engine.inventory.metadata["source"]
        == "Blevins, Juliette (2025). Phonology I."
    )


def test_commit_renders_a_pasted_bibtex_entry():
    entry = (
        "@book{h, author={Hayes, Bruce}, title={Introductory Phonology}, "
        "year={2009}, publisher={Wiley-Blackwell}}"
    )
    _commit(entry)
    stored = bridge._engine.inventory.metadata["source"]
    assert (
        stored
        == "Hayes, Bruce (2009). Introductory Phonology. Wiley-Blackwell."
    )
    assert classify_source(stored).kind == "citation"


def test_commit_empty_source_drops_the_key():
    _commit("   ")
    assert "source" not in bridge._engine.inventory.metadata


def test_commit_none_preserves_carried_source():
    original = bridge._engine.inventory.metadata["source"]
    _commit(None)
    assert bridge._engine.inventory.metadata["source"] == original


def test_source_round_trips_through_get_grid_state():
    _commit("https://phoible.org/")
    assert bridge.get_grid_state()["source"] == "https://phoible.org/"


def test_edited_source_survives_and_carries_other_metadata():
    # An inventory that carries a sibling metadata blob (``notes``)
    # alongside ``source``: editing source must not drop the sibling.
    # Built in-memory from a committed inventory with a notes key injected,
    # so the test depends on no gitignored fixture (CI has only the tracked
    # ``*_features.json`` set).
    raw = Inventory.load(HAYES).to_json_dict()
    raw.setdefault("metadata", {})
    raw["metadata"]["notes"] = "Field notes blob."
    raw["metadata"]["source"] = "Original source."
    inv = Inventory.parse(raw)
    bridge._engine = FeatureEngine(inv)
    assert "notes" in inv.metadata  # guard the fixture itself
    _commit("My own field notes, 2026.")
    meta = bridge._engine.inventory.metadata
    assert meta["source"] == "My own field notes, 2026."
    assert meta.get("notes") == "Field notes blob."
