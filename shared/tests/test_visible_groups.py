"""View-layer class-visibility filter behind the hide-classes toggle."""

from __future__ import annotations

from phonology_shared.chart.consonants import visible_groups


def _groups() -> dict[str, list[str]]:
    return {
        "Plosives": ["p", "t", "k"],
        "Fricatives": ["s", "h"],
        "Nasals": ["m", "n"],
        "Vowels": ["i", "a", "u"],
    }


def test_empty_hidden_set_is_identity() -> None:
    g = _groups()
    assert visible_groups(g, set()) == g


def test_hidden_labels_are_dropped_order_preserved() -> None:
    out = visible_groups(_groups(), {"Fricatives", "Vowels"})
    assert list(out.keys()) == ["Plosives", "Nasals"]


def test_hiding_everything_yields_empty() -> None:
    g = _groups()
    assert visible_groups(g, set(g)) == {}


def test_returns_a_copy_not_a_view() -> None:
    g = _groups()
    out = visible_groups(g, set())
    out["Plosives"].append("b")
    # The source grouping must be untouched: the filter is display-only.
    assert g["Plosives"] == ["p", "t", "k"]


def test_unknown_hidden_label_is_ignored() -> None:
    g = _groups()
    assert visible_groups(g, {"Clicks"}) == g
