"""Pin the mode-keyed bundle cache contract on FeatureEngine.

When :py:class:`MatchMode` shipped, the engine's bundle cache key
shape widened from ``frozenset[str]`` to ``(frozenset[str],
MatchMode)`` so the same selection cached under strict semantics
cannot satisfy a later wildcard lookup (and vice versa). This file
pins that contract end-to-end on a synthetic ``p``/``b``/``m``
inventory where the predicted bundles are short and easy to read.

The tests reach into ``FeatureEngine._bundle_cache`` directly to
inspect key shape; that attribute is engine-internal, so the
assertions are INTERNAL CONTRACT checks. If the cache shape is
refactored on purpose, this file is the one to update deliberately.
"""

from __future__ import annotations

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import (
    FeatureEngine,
    MatchMode,
)


def _pbm_engine() -> FeatureEngine:
    """Build the synthetic p/b/m engine the cache tests run against.

    Three segments, three features, no ``"0"`` cells anywhere, so
    every minimal bundle is predictable and both modes return
    non-empty results for the selections used below.
    """
    features = ["Consonantal", "Sonorant", "Voice"]
    segments = {
        "p": {"Consonantal": "+", "Sonorant": "-", "Voice": "-"},
        "b": {"Consonantal": "+", "Sonorant": "-", "Voice": "+"},
        "m": {"Consonantal": "+", "Sonorant": "+", "Voice": "+"},
    }
    inv = Inventory.from_grid(
        name="pbm",
        features=features,
        segments=segments,
    )
    return FeatureEngine(inv)


def test_strict_call_writes_strict_keyed_cache_entry() -> None:
    """A strict ``find_all_minimal_bundles`` call writes its result
    under a ``(frozenset(segs), MatchMode.STRICT)`` key. This pins
    the key shape: a future cache refactor that drops the mode
    component must edit this test deliberately.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    assert eng._bundle_cache == {}

    eng.find_all_minimal_bundles(selection, mode=MatchMode.STRICT)

    strict_key = (frozenset(selection), MatchMode.STRICT)
    assert strict_key in eng._bundle_cache
    # No accidental wildcard entry from the strict-only call.
    wildcard_key = (frozenset(selection), MatchMode.WILDCARD)
    assert wildcard_key not in eng._bundle_cache


def test_wildcard_call_does_not_hit_strict_cache_entry() -> None:
    """A wildcard call on the same selection that was just resolved
    in strict mode must NOT short-circuit on the strict cache entry.
    Both keys coexist in ``_bundle_cache``, and each stores the
    bundles produced under its own semantics. Pins the separation
    that lets the UI toggle between modes without leaking results
    across the boundary.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    strict_bundles = eng.find_all_minimal_bundles(
        selection, mode=MatchMode.STRICT
    )
    wildcard_bundles = eng.find_all_minimal_bundles(
        selection, mode=MatchMode.WILDCARD
    )

    strict_key = (frozenset(selection), MatchMode.STRICT)
    wildcard_key = (frozenset(selection), MatchMode.WILDCARD)
    assert strict_key in eng._bundle_cache
    assert wildcard_key in eng._bundle_cache
    # Each mode's cached payload matches its own returned tuple,
    # confirming the wildcard call did not just hand back the
    # strict-cached tuple.
    assert eng._bundle_cache[strict_key] is strict_bundles
    assert eng._bundle_cache[wildcard_key] is wildcard_bundles


def test_second_strict_call_returns_same_tuple_identity() -> None:
    """The second strict call on the same selection returns the
    SAME tuple object (``is`` identity). This is the cache-hit
    behaviour callers rely on: a hot click loop reuses the cached
    tuple without paying the hitting-set search again, and the
    Mapping views inside the tuple stay valid across calls.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    first = eng.find_all_minimal_bundles(selection, mode=MatchMode.STRICT)
    second = eng.find_all_minimal_bundles(selection, mode=MatchMode.STRICT)
    assert first is second


def test_second_wildcard_call_returns_same_tuple_identity() -> None:
    """Symmetric to the strict identity check: the wildcard cache
    must also return the SAME tuple object on a repeat call so
    wildcard-mode repeats are zero-allocation too.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    first = eng.find_all_minimal_bundles(selection, mode=MatchMode.WILDCARD)
    second = eng.find_all_minimal_bundles(selection, mode=MatchMode.WILDCARD)
    assert first is second


@pytest.mark.parametrize(
    "mode",
    [MatchMode.STRICT, MatchMode.WILDCARD],
    ids=["strict", "wildcard"],
)
def test_repeated_calls_in_each_mode_are_consistent(
    mode: MatchMode,
) -> None:
    """Repeated calls in either mode on the same engine and same
    selection return tuples whose dict-equivalent payloads match.
    Guards against a future refactor that swaps the cached value
    for a stale or differently-ordered shape on the second hit.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    first = eng.find_all_minimal_bundles(selection, mode=mode)
    second = eng.find_all_minimal_bundles(selection, mode=mode)
    third = eng.find_all_minimal_bundles(selection, mode=mode)
    as_dicts_first = [dict(b) for b in first]
    as_dicts_second = [dict(b) for b in second]
    as_dicts_third = [dict(b) for b in third]
    assert as_dicts_first == as_dicts_second == as_dicts_third


def test_strict_and_wildcard_keys_coexist_for_same_selection() -> None:
    """After calling both modes on one selection, ``_bundle_cache``
    holds exactly the two expected keys for that selection and no
    others. This pins the per-mode partitioning of the cache:
    crossing the mode boundary always adds an entry, never replaces
    one. Pinned as a sanity check against a future "single shared
    entry per selection" optimisation that would silently corrupt
    one mode's results.
    """
    eng = _pbm_engine()
    selection = ["p", "b"]
    eng.find_all_minimal_bundles(selection, mode=MatchMode.STRICT)
    eng.find_all_minimal_bundles(selection, mode=MatchMode.WILDCARD)

    expected_keys = {
        (frozenset(selection), MatchMode.STRICT),
        (frozenset(selection), MatchMode.WILDCARD),
    }
    assert set(eng._bundle_cache.keys()) == expected_keys


def test_cache_key_tuple_shape_is_frozenset_and_matchmode() -> None:
    """Every key in ``_bundle_cache`` is a 2-tuple of
    ``(frozenset[str], MatchMode)``. This is the INTERNAL CONTRACT
    the engine's mode-keying rests on. If a future refactor changes
    the key shape (for example to a dataclass or to a 3-tuple
    including a version stamp), this assertion must be updated
    deliberately rather than accidentally.
    """
    eng = _pbm_engine()
    eng.find_all_minimal_bundles(["p", "b"], mode=MatchMode.STRICT)
    eng.find_all_minimal_bundles(["p", "b"], mode=MatchMode.WILDCARD)
    eng.find_all_minimal_bundles(["b", "m"], mode=MatchMode.STRICT)

    assert eng._bundle_cache, "expected at least one cache entry"
    for key in eng._bundle_cache:
        assert isinstance(key, tuple)
        assert len(key) == 2
        selection_part, mode_part = key
        assert isinstance(selection_part, frozenset)
        assert all(isinstance(s, str) for s in selection_part)
        assert isinstance(mode_part, MatchMode)
