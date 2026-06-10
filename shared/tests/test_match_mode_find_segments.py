"""Wildcard-mode contract tests for ``FeatureEngine.find_segments``.

Pins the public semantics of the ``mode`` keyword introduced on
``find_segments``: STRICT keeps the legacy "request value must
literally match the segment value" rule, while WILDCARD treats a
``"0"`` cell as compatible with either polarity and treats a
requested ``"0"`` as a no-op constraint. Synthetic three-segment
inventories exercise each (request, segment-value) cell; the
bundled Hayes inventory pins the superset relation for any
``+``/``-`` request fan. Validation of unknown values is also
pinned to remain mode-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import (
    FeatureEngine,
    MatchMode,
)


def _voice_engine() -> FeatureEngine:
    """Three-segment inventory: p (-Voice), b (+Voice), m (0Voice).

    The (-, +, 0) trio is the smallest input that exercises every
    cell of the strict-vs-wildcard truth table on a single feature.
    """
    inv = Inventory.from_grid(
        name="synthetic_voice",
        features=["Voice"],
        segments={
            "p": {"Voice": "-"},
            "b": {"Voice": "+"},
            "m": {"Voice": "0"},
        },
    )
    return FeatureEngine(inv)


def test_strict_plus_voice_returns_only_explicit_plus() -> None:
    """STRICT ``{Voice: +}`` returns only the explicit ``+Voice``
    segment. Pins the historical contract: an explicit-value request
    matches only segments carrying that explicit value, never a
    ``"0"`` cell. This is the round-trip semantic that
    ``find_all_minimal_bundles`` relies on."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "+"}, mode=MatchMode.STRICT) == ["b"]


def test_wildcard_plus_voice_includes_zero_voice() -> None:
    """WILDCARD ``{Voice: +}`` matches every segment except the
    explicit ``-Voice`` segment. Pins the wildcard rule that a
    ``"0"`` cell is compatible with either polarity, so ``m`` is
    returned alongside ``b``."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "+"}, mode=MatchMode.WILDCARD) == [
        "b",
        "m",
    ]


def test_strict_minus_voice_returns_only_explicit_minus() -> None:
    """STRICT ``{Voice: -}`` returns only the explicit ``-Voice``
    segment. Symmetric to the strict-plus pin; ``m`` is excluded
    because its ``"0"`` is not the same value as ``"-"``."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "-"}, mode=MatchMode.STRICT) == ["p"]


def test_wildcard_minus_voice_includes_zero_voice() -> None:
    """WILDCARD ``{Voice: -}`` matches every segment except the
    explicit ``+Voice`` segment. Symmetric to the wildcard-plus pin;
    ``m`` qualifies because nothing about its ``"0"`` cell
    contradicts a ``-Voice`` request."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "-"}, mode=MatchMode.WILDCARD) == [
        "m",
        "p",
    ]


def test_strict_zero_voice_returns_only_unspecified() -> None:
    """STRICT ``{Voice: 0}`` returns only the segment whose Voice
    cell is literally ``"0"``. Pins that ``"0"`` is its OWN value
    under strict matching, not a wildcard."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "0"}, mode=MatchMode.STRICT) == ["m"]


def test_wildcard_zero_voice_is_no_op() -> None:
    """WILDCARD ``{Voice: 0}`` carries no constraint and therefore
    returns every segment. Pins the documented re-reading of a
    requested ``"0"`` as "I don't care about this feature." Users
    who want the explicit-underspec query stay in strict mode."""
    eng = _voice_engine()
    assert eng.find_segments({"Voice": "0"}, mode=MatchMode.WILDCARD) == [
        "b",
        "m",
        "p",
    ]


def test_empty_spec_returns_universe_under_both_modes() -> None:
    """An empty spec is the universal class under either mode; no
    feature is constrained, so every segment matches. Pins that the
    no-constraint path does not diverge between modes (the wildcard
    rewrite touches only how non-empty constraints filter)."""
    eng = _voice_engine()
    expected = ["b", "m", "p"]
    assert eng.find_segments({}, mode=MatchMode.STRICT) == expected
    assert eng.find_segments({}, mode=MatchMode.WILDCARD) == expected


def test_absent_key_segment_matches_like_explicit_zero() -> None:
    """A segment that omits a feature must behave identically to a
    segment whose value is the explicit string ``"0"``. The
    inventory parser collapses both on read, so the engine cannot
    distinguish them under either mode; this pin guards against a
    future regression where one path special-cases the absent key.
    """
    inv = Inventory.from_grid(
        name="synthetic_absent_key",
        features=["Voice"],
        segments={
            "p": {"Voice": "-"},
            "b": {"Voice": "+"},
            # ``m`` omits Voice entirely; the engine must treat
            # this as a ``"0"`` cell.
            "m": {},
        },
    )
    eng = FeatureEngine(inv)
    assert eng.find_segments({"Voice": "+"}, mode=MatchMode.STRICT) == ["b"]
    assert eng.find_segments({"Voice": "+"}, mode=MatchMode.WILDCARD) == [
        "b",
        "m",
    ]
    assert eng.find_segments({"Voice": "-"}, mode=MatchMode.STRICT) == ["p"]
    assert eng.find_segments({"Voice": "-"}, mode=MatchMode.WILDCARD) == [
        "m",
        "p",
    ]
    assert eng.find_segments({"Voice": "0"}, mode=MatchMode.STRICT) == ["m"]
    assert eng.find_segments({"Voice": "0"}, mode=MatchMode.WILDCARD) == [
        "b",
        "m",
        "p",
    ]


# A representative fan of ``+``/``-`` specs over the bundled Hayes
# inventory. The superset invariant only holds for requests that
# stick to explicit polarities (a requested ``"0"`` becomes a no-op
# under wildcard but a real filter under strict, so wildcard would
# be a SUPERSET; that direction is already covered by the
# synthetic table above and excluded here to keep the parametrise
# focused on the headline property).
_HAYES_SUPERSET_SPECS: list[dict[str, str]] = [
    {"Voice": "+"},
    {"Voice": "-"},
    {"Continuant": "-"},
    {"Continuant": "+"},
    {"Voice": "+", "Continuant": "-"},
    {"Voice": "-", "Continuant": "-"},
    {"Voice": "+", "Sonorant": "+"},
    {"Nasal": "+"},
    {"Nasal": "+", "Voice": "+"},
    {"Sonorant": "-", "Continuant": "+"},
]


@pytest.mark.parametrize("spec", _HAYES_SUPERSET_SPECS)
def test_wildcard_is_superset_of_strict_for_plusminus_specs(
    bundled_engine: Callable[[str], FeatureEngine],
    spec: dict[str, str],
) -> None:
    """For any spec that uses only ``+``/``-`` requests, the
    wildcard result must be a (non-strict) superset of the strict
    result. Pins the directional invariant: wildcard only relaxes
    constraints, so every segment a strict query returns must also
    appear in the wildcard result. Parametrised over a
    representative fan of single- and multi-feature specs against
    the bundled Hayes inventory."""
    eng = bundled_engine("hayes")
    strict = set(eng.find_segments(spec, mode=MatchMode.STRICT))
    wildcard = set(eng.find_segments(spec, mode=MatchMode.WILDCARD))
    assert strict <= wildcard, (
        f"strict {sorted(strict)} not a subset of "
        f"wildcard {sorted(wildcard)} for spec {spec}"
    )


@pytest.mark.parametrize("mode", [MatchMode.STRICT, MatchMode.WILDCARD])
def test_invalid_value_raises_under_both_modes(
    mode: MatchMode,
) -> None:
    """A request value outside ``VALID_VALUES`` must raise
    ``ValueError`` regardless of the active mode. Validation runs
    before the mode-specific arithmetic; pins that the wildcard
    rewrite did not accidentally bypass the value check on its
    branch."""
    eng = _voice_engine()
    with pytest.raises(ValueError):
        eng.find_segments({"Voice": "?"}, mode=mode)
