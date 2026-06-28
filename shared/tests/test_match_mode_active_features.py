"""Contract tests for ``FeatureEngine.active_features_for_mode``.

Pins the mode-aware active-feature roster the feature pane reads
when the user toggles "Allow underspecified" on. STRICT must
mirror the legacy ``active_features`` property (drop features
that are uniformly ``"0"`` because they cannot match anything in
strict mode); WILDCARD must surface the full inventory roster,
because wildcard treats a uniformly-``"0"`` feature as queryable
(a ``+f`` request matches every segment when nothing contradicts).
The bundled Hindi case pins the user's original complaint:
``LowerLarynx`` is invisible in strict mode and surfaces in
wildcard mode.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import (
    FeatureEngine,
    MatchMode,
)


def _phantom_engine() -> FeatureEngine:
    """Synthetic inventory where ``PhantomFeat`` is uniformly ``0``.

    Shared between the strict-drop and wildcard-include tests so
    both assertions point at the exact same construction; if the
    editor ever stops accepting the shape, both tests fail
    together rather than drifting.
    """
    features = ["Voice", "Sonorant", "PhantomFeat"]
    segments = {
        "p": {"Voice": "-", "Sonorant": "-", "PhantomFeat": "0"},
        "b": {"Voice": "+", "Sonorant": "-", "PhantomFeat": "0"},
        "m": {"Voice": "+", "Sonorant": "+", "PhantomFeat": "0"},
    }
    inv = Inventory.from_grid(
        name="synthetic",
        features=features,
        segments=segments,
    )
    return FeatureEngine(inv)


@pytest.mark.parametrize(
    "mode",
    [MatchMode.STRICT, MatchMode.WILDCARD],
)
def test_active_features_for_mode_returns_tuple(mode: MatchMode) -> None:
    """Both modes return a ``tuple[str, ...]`` rather than a list or
    a view; downstream callers (the feature pane, the renderer) treat
    the return as a stable hashable sequence so the type pin matters."""
    eng = _phantom_engine()
    result = eng.active_features_for_mode(mode)
    assert isinstance(result, tuple)
    assert all(isinstance(f, str) for f in result)


def test_strict_mode_mirrors_active_features_property() -> None:
    """``active_features_for_mode(STRICT)`` must equal the legacy
    ``active_features`` property exactly (same tuple, same order).
    The property is the existing source of truth for the feature
    pane in strict mode; the new method must not alter it."""
    eng = _phantom_engine()
    assert (
        eng.active_features_for_mode(MatchMode.STRICT) == eng.active_features
    )


def test_wildcard_mode_returns_full_feature_roster() -> None:
    """``active_features_for_mode(WILDCARD)`` must equal the full
    inventory feature roster (``engine.features``), preserving
    declaration order. Wildcard mode treats every feature as
    queryable, including features that are uniformly ``"0"``."""
    eng = _phantom_engine()
    assert eng.active_features_for_mode(MatchMode.WILDCARD) == eng.features


def test_phantom_feature_strict_drops_wildcard_keeps() -> None:
    """The crux of the wildcard contract on a synthetic inventory:
    a feature that is ``"0"`` across every segment is dropped by
    the strict active list (a ``+PhantomFeat`` request would return
    the empty set), but is included in the wildcard active list
    (a ``+PhantomFeat`` request is compatible with every segment
    because nothing contradicts it)."""
    eng = _phantom_engine()
    strict = eng.active_features_for_mode(MatchMode.STRICT)
    wildcard = eng.active_features_for_mode(MatchMode.WILDCARD)
    assert "PhantomFeat" not in strict
    assert "PhantomFeat" in wildcard


@pytest.mark.parametrize(
    "feat,present_in_strict",
    [
        ("Voice", True),
        ("Sonorant", True),
        ("PhantomFeat", False),
    ],
)
def test_synthetic_strict_membership_parametrized(
    feat: str, present_in_strict: bool
) -> None:
    """Per-feature strict membership pin on the synthetic inventory:
    ``Voice`` and ``Sonorant`` carry explicit ``+``/``-`` so they
    survive the strict filter; ``PhantomFeat`` is uniformly ``"0"``
    so it does not. Documents the strict-filter rule one row at a
    time so a regression names the offending feature."""
    eng = _phantom_engine()
    strict = eng.active_features_for_mode(MatchMode.STRICT)
    assert (feat in strict) is present_in_strict


@pytest.mark.parametrize(
    "feat",
    ["Voice", "Sonorant", "PhantomFeat"],
)
def test_synthetic_wildcard_includes_every_declared_feature(
    feat: str,
) -> None:
    """Per-feature wildcard membership pin on the synthetic inventory:
    every declared feature (including the uniformly-``"0"``
    ``PhantomFeat``) must appear in the wildcard active list. The
    parametrisation documents that NO declared feature is filtered
    out under wildcard mode."""
    eng = _phantom_engine()
    wildcard = eng.active_features_for_mode(MatchMode.WILDCARD)
    assert feat in wildcard


def test_bundled_hindi_lower_larynx_strict_drops_wildcard_keeps(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """The user's original complaint on the real Hindi inventory.

    Hindi has no implosives, so ``LowerLarynx`` is ``"0"`` for
    every segment. Strict mode drops it (a ``+LowerLarynx``
    request returns the empty set, so the feature pane hides it);
    wildcard mode keeps it (a ``+LowerLarynx`` request matches
    every Hindi segment because nothing contradicts it). The pane
    must surface the feature once the user opts into wildcard,
    otherwise the toggle has no observable effect for the user's
    motivating case.
    """
    eng = bundled_engine("hindi")
    strict = eng.active_features_for_mode(MatchMode.STRICT)
    wildcard = eng.active_features_for_mode(MatchMode.WILDCARD)
    assert "LowerLarynx" not in strict
    assert "LowerLarynx" in wildcard


def test_bundled_hindi_wildcard_equals_full_roster(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Stronger pin on Hindi: the wildcard active list is the full
    feature roster, not just strict-plus-LowerLarynx. Documents that
    wildcard mode does not invent its own filter; it simply returns
    ``engine.features`` so the renderer sees every declared row."""
    eng = bundled_engine("hindi")
    assert eng.active_features_for_mode(MatchMode.WILDCARD) == eng.features


def test_bundled_hindi_strict_equals_active_features_property(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """On the real Hindi inventory the strict mode return must equal
    the existing ``active_features`` property. Pins that the new
    method preserves backward compatibility for the feature pane's
    default render."""
    eng = bundled_engine("hindi")
    assert (
        eng.active_features_for_mode(MatchMode.STRICT) == eng.active_features
    )


def test_wildcard_superset_of_strict_on_bundled_hindi(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """Set-level invariant: every strict-active feature is also
    wildcard-active. Wildcard's roster is a (non-strict) superset
    of strict's because wildcard only ADDS the uniformly-``"0"``
    features that strict filters out; it never drops a feature
    that strict kept."""
    eng = bundled_engine("hindi")
    strict = set(eng.active_features_for_mode(MatchMode.STRICT))
    wildcard = set(eng.active_features_for_mode(MatchMode.WILDCARD))
    assert strict <= wildcard


def test_wildcard_preserves_feature_declaration_order() -> None:
    """The wildcard return must preserve inventory feature
    declaration order. The feature pane renders rows in that
    order; reordering would shuffle the UI without any user
    action and break the strict/wildcard visual parity for the
    overlapping subset of rows."""
    eng = _phantom_engine()
    wildcard = eng.active_features_for_mode(MatchMode.WILDCARD)
    assert list(wildcard) == list(eng.features)
