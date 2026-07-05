"""Pin the optional declared-class primitives in
:py:func:`phonology_shared.chart.consonants.group_segments`.

An inventory author may state ``rhotic`` / ``liquid`` / ``flap``
outright when the standard feature bundle cannot recover the display
category. These are read ONLY by the grouper (display); they do not
change feature-query behaviour. The base-routing tests disable the
cover-merge cascade so the group ``best_primary`` routes a single
segment to is observable directly; the conflict tests exercise the
full pipeline including the ``liquid:-`` merge gate.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart import consonants
from phonology_shared.chart.consonants import group_segments


def _cons(**kw: str) -> dict[str, str]:
    base = {
        "consonantal": "+",
        "sonorant": "+",
        "continuant": "+",
        "syllabic": "-",
    }
    base.update(kw)
    return base


def _group_of(inv: dict[str, dict[str, str]], seg: str) -> str | None:
    groups = group_segments(inv)
    return next((g for g, segs in groups.items() if seg in segs), None)


@pytest.fixture
def no_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the parent folds so a single segment's BASE group (what
    ``best_primary`` routes it to) is observable without the
    granularity fold collapsing a tiny test inventory. (The population
    covers this fixture also used to blank are retired: display
    membership never leaves the reached-class subtree now.)"""
    monkeypatch.setattr(consonants, "_MERGE_PARENT", {})


def test_explicit_rhotic_consonant_routes_to_rhotics(no_merges: None) -> None:
    assert _group_of({"r": _cons(rhotic="+", trill="+")}, "r") == "Rhotics"


def test_rhotic_beats_an_also_declared_liquid(no_merges: None) -> None:
    assert _group_of({"r": _cons(rhotic="+", liquid="+")}, "r") == "Rhotics"


def test_rhotic_vowel_is_not_routed_to_consonant_rhotics(
    no_merges: None,
) -> None:
    # ``rhotic`` is also a vowel feature (ɚ / ɝ); the consonant gate
    # must keep a rhotic vowel in Vowels, never the Rhotics group.
    vowel = {
        "rhotic": "+",
        "syllabic": "+",
        "consonantal": "-",
        "sonorant": "+",
    }
    assert _group_of({"ɚ": vowel}, "ɚ") == "Vowels"


def test_explicit_flap_folds_into_taps_and_flaps(no_merges: None) -> None:
    assert _group_of({"ɾ": _cons(flap="+")}, "ɾ") == "Taps & Flaps"


def test_explicit_liquid_anchors_liquids_over_central_approximant(
    no_merges: None,
) -> None:
    # A liquid is itself a sonorant continuant, so it always matches
    # the generic Central Approximants spec; the anchor must win.
    assert _group_of({"ɫ": _cons(liquid="+")}, "ɫ") == "Liquids"


def test_liquid_yields_to_a_more_specific_lateral_approximant(
    no_merges: None,
) -> None:
    seg = _cons(liquid="+", lateral="+", approximant="+", tap="-")
    assert _group_of({"l": seg}, "l") == "Lateral Approximants"


def test_liquid_vowel_is_not_routed_to_consonant_liquids(
    no_merges: None,
) -> None:
    vowel = {
        "liquid": "+",
        "syllabic": "+",
        "consonantal": "-",
        "sonorant": "+",
    }
    assert _group_of({"x": vowel}, "x") == "Vowels"


def test_rhotic_minus_liquid_is_not_forced_into_liquids() -> None:
    # +rhotic -liquid alongside a lateral approximant: the explicit
    # liquid:- declaration blocks the Rhotics -> Liquids cover merge.
    inv = {
        "r": _cons(rhotic="+", liquid="-", trill="+"),
        "l": _cons(lateral="+", approximant="+", tap="-"),
    }
    groups = group_segments(inv)
    assert "r" in groups.get("Rhotics", [])
    assert "l" in groups.get("Lateral Approximants", [])
    assert "Liquids" not in groups


def test_declared_classes_survive_beside_other_small_groups() -> None:
    """A declared rhotic stays in Rhotics even when a small lateral
    group co-occurs: the population merge that used to fold the pair
    into a Liquids cover is retired (display membership never leaves
    the reached-class subtree; ``Liquids`` remains reachable only
    through the declared ``liquid`` primitive, per
    ``test_explicit_liquid_anchors_liquids_over_central_approximant``)."""
    inv = {
        "r": _cons(rhotic="+", liquid="+", trill="+"),
        "l": _cons(lateral="+", approximant="+", tap="-"),
    }
    groups = group_segments(inv)
    assert "r" in groups.get("Rhotics", [])
    assert "l" in groups.get("Lateral Approximants", [])
    assert "Liquids" not in groups
