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


def test_unclassifiable_contoid_routes_to_contoids_not_dropped() -> None:
    # A segment whose only feature is non-standard matches no manner /
    # place spec; a consonant-like one must land in the "Contoids"
    # catch-all (visible) rather than vanish from the grouped payload.
    from phonology_shared.chart.consonants import (
        CONTOID_GROUP_NAME,
        group_segments,
    )

    inv = {"x1": {"mystery": "+"}, "x2": {"weird": "-"}}
    grouped = group_segments(inv)
    placed = {s for segs in grouped.values() for s in segs}
    assert placed == set(inv)  # nothing dropped
    assert set(grouped[CONTOID_GROUP_NAME]) == set(inv)


def test_is_vocoid_distinguishes_vowels_glides_from_contoids() -> None:
    from phonology_shared.chart.consonants import _is_vocoid

    assert _is_vocoid({"syllabic": "+"}) is True  # a vowel
    assert (
        _is_vocoid(  # a glide: central oral resonant
            {"consonantal": "-", "sonorant": "+", "continuant": "+"}
        )
        is True
    )
    assert (
        _is_vocoid(  # a stop: contoid
            {"consonantal": "+", "sonorant": "-", "continuant": "-"}
        )
        is False
    )
    assert (
        _is_vocoid(  # a lateral is not a (central) vocoid
            {
                "consonantal": "-",
                "sonorant": "+",
                "continuant": "+",
                "lateral": "+",
            }
        )
        is False
    )
