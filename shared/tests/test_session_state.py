"""Transitions for the frontend-agnostic :class:`SessionState`.

Pins the load / select / mode / clear semantics both frontends will
adopt, so a future migration of desktop or web onto this layer is a
mechanical rewrite, not a behaviour change.
"""

from __future__ import annotations

from collections.abc import Callable

from phonology_shared.application import SessionState
from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.mode_logic import Mode
from phonology_shared.theory.feature_engine import FeatureEngine, MatchMode


def test_starts_empty() -> None:
    s = SessionState()
    assert s.inventory is None and s.engine is None
    assert s.mode is Mode.SEG_TO_FEAT
    assert s.match_mode is MatchMode.STRICT
    assert s.selected_segments == [] and s.selected_features == {}
    assert s.hidden_segment_classes == set()
    assert s.source.kind == "none"


def test_load_inventory_builds_engine_and_classifies_source(
    bundled_inventory: Callable[[str], Inventory],
) -> None:
    s = SessionState()
    inv = bundled_inventory("hayes")
    s.load_inventory(inv)
    assert s.inventory is inv
    assert isinstance(s.engine, FeatureEngine)
    # Hayes ships a bibliographic ``metadata.source`` citation.
    assert s.source.kind == "citation"


def test_load_inventory_resets_per_inventory_state(
    bundled_inventory: Callable[[str], Inventory],
) -> None:
    s = SessionState()
    s.load_inventory(bundled_inventory("hayes"))
    seg = next(iter(s.engine.segments))
    s.toggle_segment(seg, True)
    s.set_feature("Voice", "+")
    s.set_class_hidden("Fricatives", True)
    # A swap clears selection + hidden classes (they don't carry over).
    s.load_inventory(bundled_inventory("hayes"))
    assert s.selected_segments == []
    assert s.selected_features == {}
    assert s.hidden_segment_classes == set()


def test_set_mode_and_match_mode_report_change() -> None:
    s = SessionState()
    assert s.set_mode(Mode.FEAT_TO_SEG) is True
    assert s.mode is Mode.FEAT_TO_SEG
    assert s.set_mode(Mode.FEAT_TO_SEG) is False  # no-op
    assert s.set_match_mode(MatchMode.WILDCARD) is True
    assert s.set_match_mode(MatchMode.WILDCARD) is False


def test_toggle_segment_is_ordered_and_idempotent() -> None:
    s = SessionState()
    s.toggle_segment("p", True)
    s.toggle_segment("b", True)
    s.toggle_segment("p", True)  # already selected -> no duplicate
    assert s.selected_segments == ["p", "b"]
    s.toggle_segment("z", False)  # absent -> no-op
    s.toggle_segment("p", False)
    assert s.selected_segments == ["b"]


def test_set_feature_sets_and_clears() -> None:
    s = SessionState()
    s.set_feature("Voice", "+")
    s.set_feature("Nasal", "-")
    assert s.selected_features == {"Voice": "+", "Nasal": "-"}
    s.set_feature("Voice", "0")  # cleared-cell sentinel removes it
    assert s.selected_features == {"Nasal": "-"}
    s.set_feature("Nasal", "")  # empty also clears
    assert s.selected_features == {}


def test_set_class_hidden_toggles() -> None:
    s = SessionState()
    s.set_class_hidden("Vowels", True)
    assert s.hidden_segment_classes == {"Vowels"}
    s.set_class_hidden("Vowels", False)
    assert s.hidden_segment_classes == set()


def test_reset_selection_leaves_mode_and_inventory(
    bundled_inventory: Callable[[str], Inventory],
) -> None:
    s = SessionState()
    s.load_inventory(bundled_inventory("hayes"))
    s.set_mode(Mode.FEAT_TO_SEG)
    s.toggle_segment("p", True)
    s.set_feature("Voice", "+")
    s.reset_selection()
    assert s.selected_segments == [] and s.selected_features == {}
    assert s.mode is Mode.FEAT_TO_SEG  # untouched
    assert s.inventory is not None and s.engine is not None
