"""Wildcard-mode contract tests for ``FeatureEngine.is_natural_class``.

The engine recently gained a ``mode=MatchMode.WILDCARD`` keyword on
its match-bearing methods. The strict-mode behaviour is already
pinned by the existing 949-test suite; this file pins the wildcard
verdict on the natural-class decision question and the bundle-level
round-trip rule that wildcard NCs must satisfy. The strict default
is exercised here only as a comparison baseline so the
"wildcard is a superset of strict" invariant is testable in one place.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import (
    FeatureEngine,
    MatchMode,
)

# ----------------------------------------------------------------------
# Synthetic three-segment inventory used by the targeted cases below.
# ``m`` is voiced but carries ``Voice: "0"``; under strict {b, m} is
# not a natural class (Voice splits + and 0), but under wildcard
# ``{Voice: "+"}`` matches both because "0" is compatible with any
# polarity.
# ----------------------------------------------------------------------
_FEATURES = ["Voice", "Nasal"]
_SEGMENTS = {
    "p": {"Voice": "-", "Nasal": "-"},
    "b": {"Voice": "+", "Nasal": "-"},
    "m": {"Voice": "0", "Nasal": "+"},
}


def _synthetic_engine() -> FeatureEngine:
    """Build the canonical p/b/m engine used across the synthetic
    cases. Constructed per-test (engines are cheap to build) so a
    test mutating cache state cannot leak into a sibling test."""
    inv = Inventory.from_grid(
        name="synthetic_pbm",
        features=_FEATURES,
        segments=_SEGMENTS,
    )
    return FeatureEngine(inv)


# ----------------------------------------------------------------------
# Targeted contract on the synthetic p/b/m inventory.
# ----------------------------------------------------------------------


def test_synthetic_strict_nc_for_singleton_b() -> None:
    """{b} is a strict natural class on the p/b/m inventory: Voice
    is ``+`` on b and not ``+`` on p or m, so ``{Voice: '+'}`` (or
    a Nasal-augmented bundle) characterises b alone under strict
    matching. This baseline keeps the wildcard cases below honest:
    if the strict path ever stops returning True here, the wildcard
    superset invariant in the parametrised test loses meaning.
    """
    eng = _synthetic_engine()
    is_nc, bundles = eng.is_natural_class(["b"], mode=MatchMode.STRICT)
    assert is_nc is True
    assert bundles, "strict {b} must return at least one minimal bundle"
    for bundle in bundles:
        assert set(eng.find_segments(dict(bundle))) == {"b"}


def test_synthetic_strict_not_nc_for_b_and_m() -> None:
    """{b, m} is NOT a strict natural class on the p/b/m inventory.
    Voice on m is ``"0"``, so no shared explicit ``+``/``-`` value
    on Voice covers both; Nasal splits the pair (``-`` on b,
    ``+`` on m). The strict verdict must be False with an empty
    bundle tuple. Pinning this is what gives the wildcard verdict
    below something genuinely new to assert.
    """
    eng = _synthetic_engine()
    is_nc, bundles = eng.is_natural_class(["b", "m"], mode=MatchMode.STRICT)
    assert is_nc is False
    assert bundles == ()


def test_synthetic_wildcard_nc_for_b_and_m() -> None:
    """{b, m} IS a wildcard natural class on the p/b/m inventory.
    Under wildcard matching ``{Voice: '+'}`` matches every segment
    that is not explicitly ``-Voice`` — that's b (explicitly ``+``)
    and m (``"0"``, compatible with either polarity), while p is
    ruled out (explicitly ``-Voice``). This is the headline
    semantic shift wildcard mode brings to ``is_natural_class``.
    """
    eng = _synthetic_engine()
    is_nc, bundles = eng.is_natural_class(["b", "m"], mode=MatchMode.WILDCARD)
    assert is_nc is True
    assert bundles, "wildcard {b, m} must return at least one bundle"


def test_synthetic_wildcard_bundle_for_b_and_m_is_voice_plus() -> None:
    """The wildcard minimal bundle for {b, m} on the p/b/m
    inventory must be exactly ``{Voice: '+'}`` — one feature,
    minimal, and the only one that distinguishes {b, m} from p
    under wildcard rules. Any bundle that adds Nasal (or another
    feature) would not be minimal; any bundle without Voice would
    fail to exclude p. Pinning the exact bundle shape catches
    regressions in the wildcard candidate-generation logic that a
    coarse "is_nc True" assertion would silently tolerate.
    """
    eng = _synthetic_engine()
    _, bundles = eng.is_natural_class(["b", "m"], mode=MatchMode.WILDCARD)
    assert (
        len(bundles) == 1
    ), f"expected exactly one minimal wildcard bundle, got {bundles!r}"
    assert dict(bundles[0]) == {"Voice": "+"}


# ----------------------------------------------------------------------
# Bundle-level round-trip: every wildcard bundle re-matches the
# input selection under wildcard semantics. This is the wildcard
# analogue of the strict-mode round-trip rule that
# ``find_all_minimal_bundles`` rests on.
# ----------------------------------------------------------------------


def test_synthetic_wildcard_bundles_round_trip() -> None:
    """Every bundle returned for the wildcard {b, m} verdict must,
    when fed back into ``find_segments(mode=WILDCARD)``, recover
    exactly {b, m}. The synthetic inventory's bundle list is short
    enough to assert this directly; the real-inventory parametrised
    test below extends the same round-trip rule to a fan of Hayes
    selections.
    """
    eng = _synthetic_engine()
    _, bundles = eng.is_natural_class(["b", "m"], mode=MatchMode.WILDCARD)
    for bundle in bundles:
        recovered = set(
            eng.find_segments(dict(bundle), mode=MatchMode.WILDCARD)
        )
        assert recovered == {"b", "m"}, (
            f"wildcard round-trip failed for bundle {dict(bundle)}: "
            f"recovered={recovered}"
        )


# ----------------------------------------------------------------------
# Empty-selection contract: under BOTH modes the empty list is not
# a natural class. This matches the contract pinned by the
# existing empty-segments tests for the strict path; wildcard must
# not silently flip that verdict.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [MatchMode.STRICT, MatchMode.WILDCARD],
    ids=["strict", "wildcard"],
)
def test_empty_selection_is_not_nc_in_either_mode(
    mode: MatchMode,
) -> None:
    """An empty selection returns ``(False, ())`` regardless of
    mode. No bundle B satisfies ``find_segments(B) == set()`` —
    even the universal-class empty bundle matches every segment,
    so the empty set has no characterising spec. Wildcard does not
    change the candidate space here; the empty-input early-return
    in ``find_all_minimal_bundles`` short-circuits both modes.
    """
    eng = _synthetic_engine()
    is_nc, bundles = eng.is_natural_class([], mode=mode)
    assert is_nc is False
    assert bundles == ()


# ----------------------------------------------------------------------
# Wildcard NC is a superset of strict NC: any selection that is a
# strict NC must also be a wildcard NC. Fanned out across a list
# of Hayes selections covering singletons, pairs, and small groups.
# Selections were chosen so that every one is a strict NC under
# the bundled Hayes inventory (verified at authoring time); if a
# selection ever stops being a strict NC, the strict baseline
# assertion will surface the change before the wildcard claim runs.
# ----------------------------------------------------------------------


_HAYES_STRICT_NC_SELECTIONS = [
    ["p"],
    ["b"],
    ["m"],
    ["n"],
    ["l"],
    ["i"],
    ["u"],
    ["p", "b"],
    ["s", "z"],
]


@pytest.mark.parametrize(
    "selection",
    _HAYES_STRICT_NC_SELECTIONS,
    ids=lambda s: "+".join(s),
)
def test_strict_nc_implies_wildcard_nc(
    bundled_engine: Callable[[str], FeatureEngine],
    selection: list[str],
) -> None:
    """If ``is_natural_class(S, mode=STRICT)`` is True, then
    ``is_natural_class(S, mode=WILDCARD)`` is True for any
    featurally-rich inventory.

    Reason: the wildcard candidate generator emits at least one
    of ``(f, '+')`` or ``(f, '-')`` for every feature that doesn't
    have a contradictory member in ``S``. For a strict NC, those
    candidates plus the additional ``(f, opposite)`` candidates
    (where ``S`` has no explicit value on ``f``) typically combine
    to a wildcard bundle that excludes every outside segment via
    its opposite-explicit value. Hayes is rich enough to satisfy
    this — every segment carries an explicit value for the
    contrastive features. The implication CAN fail on
    pathologically underspec inventories where some outside segment
    is uniformly ``0`` and no constraint can exclude it; those
    cases would surface here as a test failure, prompting either a
    bug fix or a deliberate documentation update.
    """
    eng = bundled_engine("hayes")
    strict_is_nc, _ = eng.is_natural_class(selection, mode=MatchMode.STRICT)
    assert strict_is_nc, (
        f"baseline drift: {selection} is no longer a strict NC on "
        f"bundled Hayes; update _HAYES_STRICT_NC_SELECTIONS"
    )
    wildcard_is_nc, wildcard_bundles = eng.is_natural_class(
        selection, mode=MatchMode.WILDCARD
    )
    assert wildcard_is_nc, (
        f"superset invariant broken: {selection} is a strict NC "
        f"but wildcard returned False"
    )
    assert wildcard_bundles, (
        f"superset invariant broken: {selection} is a wildcard NC "
        f"but no bundles were returned"
    )


@pytest.mark.parametrize(
    "selection",
    _HAYES_STRICT_NC_SELECTIONS,
    ids=lambda s: "+".join(s),
)
def test_hayes_wildcard_bundles_round_trip(
    bundled_engine: Callable[[str], FeatureEngine],
    selection: list[str],
) -> None:
    """Every bundle the wildcard verdict returns for a Hayes
    selection must round-trip: feeding ``dict(bundle)`` back into
    ``find_segments(mode=WILDCARD)`` recovers exactly the input
    selection set. This is the wildcard analogue of the strict
    round-trip rule the analysis pane's bundle rendering rests on;
    a wildcard bundle that displays one extent and selects another
    is the same class of bug.
    """
    eng = bundled_engine("hayes")
    _, bundles = eng.is_natural_class(selection, mode=MatchMode.WILDCARD)
    assert bundles, (
        f"no wildcard bundles returned for {selection}; round-trip "
        f"check has nothing to verify"
    )
    expected = set(selection)
    for bundle in bundles:
        recovered = set(
            eng.find_segments(dict(bundle), mode=MatchMode.WILDCARD)
        )
        assert recovered == expected, (
            f"wildcard round-trip failed for {selection}: bundle "
            f"{dict(bundle)} recovered {recovered}"
        )
