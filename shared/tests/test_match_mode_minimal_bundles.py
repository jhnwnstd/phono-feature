"""Wildcard-mode contract tests for ``find_all_minimal_bundles``.

Pins the behaviour added when :py:class:`MatchMode` introduced a
``WILDCARD`` option alongside the historical ``STRICT`` default.
Every assertion here exercises the wildcard path through
:py:meth:`FeatureEngine.find_all_minimal_bundles`; the existing
suite already covers strict semantics under the default. Covers:
the strict / wildcard size relationship for the same selection
across bundled inventories, the wildcard round-trip invariant,
candidate generation for features that are uniformly ``"0"`` on
the selection, the ``max_bundles`` cap honoured under both modes,
and the keyword-only nature of the ``mode`` parameter.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import (
    FeatureEngine,
    MatchMode,
)

# ---------------------------------------------------------------
# Size relationship between strict and wildcard minimal bundles
# ---------------------------------------------------------------
#
# Selections that are strict natural classes in their respective
# bundled inventories. Strict membership is the precondition for the
# comparison: when strict returns no bundle the size relationship is
# undefined, so the parametrised pair below is deliberately chosen
# so that both modes produce a bundle in the engine's current
# feature tables.

_SIZE_CASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hayes", ("s", "z")),
    ("english", ("b", "d", "ɡ")),
)


@pytest.mark.parametrize("inventory_name, selection", _SIZE_CASES)
def test_wildcard_bundle_length_vs_strict(
    bundled_engine: Callable[[str], FeatureEngine],
    inventory_name: str,
    selection: tuple[str, ...],
) -> None:
    """Pin the size relationship between strict and wildcard minimal
    bundles for the same selection. Each wildcard constraint is
    weaker than its strict twin (it excludes only the OPPOSITE-
    explicit outside segments, not the ``"0"`` ones strict also
    rules out), so once the selection is a natural class under both
    modes the wildcard minimum is at least as long as the strict
    minimum. Parametrised across the Hayes and English bundled
    inventories so the relationship is exercised against more than
    one feature table.
    """
    engine = bundled_engine(inventory_name)
    segs = list(selection)
    strict_bundles = engine.find_all_minimal_bundles(
        segs, mode=MatchMode.STRICT
    )
    wildcard_bundles = engine.find_all_minimal_bundles(
        segs, mode=MatchMode.WILDCARD
    )
    assert strict_bundles, (
        f"precondition: {selection!r} must be a strict natural "
        f"class in {inventory_name}"
    )
    assert wildcard_bundles, (
        f"precondition: {selection!r} must be a wildcard natural "
        f"class in {inventory_name}"
    )
    assert len(wildcard_bundles[0]) >= len(strict_bundles[0])


# ---------------------------------------------------------------
# Round-trip invariant under wildcard
# ---------------------------------------------------------------


@pytest.mark.parametrize("inventory_name, selection", _SIZE_CASES)
def test_wildcard_bundle_roundtrips_under_wildcard(
    bundled_engine: Callable[[str], FeatureEngine],
    inventory_name: str,
    selection: tuple[str, ...],
) -> None:
    """Every minimal bundle the engine emits under wildcard mode
    must round-trip through ``find_segments`` under the same mode:
    typing the bundle back into the feat pane has to reproduce
    exactly the original selection. This is the wildcard analogue
    of the strict round-trip invariant the analysis pane relies on
    when it surfaces a bundle to the user as a definition of their
    selection. Parametrised across both bundled inventories so the
    invariant is pinned against the live feature tables, not just a
    synthetic toy.
    """
    engine = bundled_engine(inventory_name)
    segs = list(selection)
    bundles = engine.find_all_minimal_bundles(segs, mode=MatchMode.WILDCARD)
    assert bundles
    expected = sorted(segs)
    for bundle in bundles:
        roundtrip = engine.find_segments(dict(bundle), mode=MatchMode.WILDCARD)
        assert roundtrip == expected


# ---------------------------------------------------------------
# All-"0" feature contributes BOTH polarities as wildcard candidates
# ---------------------------------------------------------------


def _dual_polarity_inventory() -> Inventory:
    """Synthetic inventory designed so selecting ``{a, b}`` leaves
    feature ``G`` uniformly ``"0"`` on the selection while feature
    ``F`` resolves the outside. ``c`` is the only ``+G`` segment,
    ``d`` the only ``-G``; both are outside, so the wildcard
    candidate generator must keep both ``(G, "+")`` and ``(G, "-")``
    on the table even though neither could ever be a strict
    candidate."""
    return Inventory.from_grid(
        name="dual_polarity",
        features=["F", "G"],
        segments={
            "a": {"F": "+", "G": "0"},
            "b": {"F": "+", "G": "0"},
            "c": {"F": "-", "G": "+"},
            "d": {"F": "-", "G": "-"},
        },
    )


def test_all_zero_feature_yields_both_polarity_candidates() -> None:
    """A feature whose value is ``"0"`` on every selected segment
    contributes BOTH ``(f, "+")`` and ``(f, "-")`` to the wildcard
    candidate pool. Neither polarity contradicts a ``"0"`` member,
    so the wildcard generator yields both; strict would silently
    drop the feature because no member is explicitly ``+`` or
    ``-``. Verified by inspecting
    :py:meth:`FeatureEngine._wildcard_candidate_constraints` on a
    synthetic inventory where feature ``G`` is uniformly ``"0"`` on
    the selection ``{a, b}``.
    """
    engine = FeatureEngine(_dual_polarity_inventory())
    pairs = engine._wildcard_candidate_constraints(frozenset({"a", "b"}))
    assert ("G", "+") in pairs
    assert ("G", "-") in pairs
    # F is +F on every member, so only the (+) polarity is
    # admissible; the (-) polarity would contradict the selection.
    assert ("F", "+") in pairs
    assert ("F", "-") not in pairs


@pytest.mark.parametrize(
    "outside_polarity, expected_constraint",
    [("-", ("G", "+")), ("+", ("G", "-"))],
)
def test_all_zero_feature_drives_wildcard_bundle(
    outside_polarity: str,
    expected_constraint: tuple[str, str],
) -> None:
    """Pin that an all-``"0"``-in-selection feature is not just an
    inert candidate but can be the SOLE constraint of a wildcard
    minimal bundle. Build a synthetic inventory whose only outside
    segment is distinguished from the selection by feature ``G``
    alone, flip the outside polarity between the two parametrised
    runs, and confirm that strict gives up (``G`` never enters its
    candidate pool because the selection is uniformly ``"0"``)
    while wildcard returns the opposite-polarity bundle and round-
    trips it cleanly.
    """
    segments = {
        "a": {"G": "0"},
        "b": {"G": "0"},
        "c": {"G": outside_polarity},
    }
    inv = Inventory.from_grid(
        name="all_zero_drives_wildcard",
        features=["G"],
        segments=segments,
    )
    engine = FeatureEngine(inv)
    strict = engine.find_all_minimal_bundles(["a", "b"], mode=MatchMode.STRICT)
    wildcard = engine.find_all_minimal_bundles(
        ["a", "b"], mode=MatchMode.WILDCARD
    )
    assert strict == ()
    assert len(wildcard) == 1
    assert dict(wildcard[0]) == dict([expected_constraint])
    roundtrip = engine.find_segments(
        dict(wildcard[0]), mode=MatchMode.WILDCARD
    )
    assert roundtrip == ["a", "b"]


# ---------------------------------------------------------------
# ``max_bundles`` cap honoured under both modes
# ---------------------------------------------------------------


def _many_bundles_inventory() -> Inventory:
    """Synthetic inventory where selecting ``{a}`` admits five
    independent minimum-size bundles. Each of the five features is
    ``"+"`` on ``a`` and ``"-"`` on the only outside segment ``b``,
    so each feature alone is a size-1 hitting set covering ``b``.
    Strict and wildcard generate the same five ``(Fi, "+")``
    candidates, so both modes produce the same five-bundle natural
    result and the cap applies identically."""
    features = ["F1", "F2", "F3", "F4", "F5"]
    return Inventory.from_grid(
        name="many_bundles",
        features=features,
        segments={
            "a": dict.fromkeys(features, "+"),
            "b": dict.fromkeys(features, "-"),
        },
    )


@pytest.mark.parametrize("mode", [MatchMode.STRICT, MatchMode.WILDCARD])
def test_max_bundles_truncates_under_both_modes(
    mode: MatchMode,
) -> None:
    """``max_bundles`` is a hard cap on the size of the returned
    tuple. Build a synthetic case where the unconstrained result is
    five independent size-1 bundles, request ``max_bundles=2``, and
    verify the cap is honoured under both strict and wildcard. The
    five bundles each satisfy the round-trip invariant; what the
    cap controls is how many of them the engine surfaces before
    bailing out of the hitting-set search.
    """
    # Sanity engine: confirm the synthetic case really does have
    # more than two minimum bundles when the search runs unbounded,
    # so the cap below is meaningful. ``_bundle_cache`` is keyed on
    # ``(selection, mode)`` and not on ``max_bundles``, so a fresh
    # engine per measurement is the simplest way to isolate the cap
    # behaviour from cache reuse.
    uncapped_engine = FeatureEngine(_many_bundles_inventory())
    uncapped = uncapped_engine.find_all_minimal_bundles(["a"], mode=mode)
    assert len(uncapped) == 5
    capped_engine = FeatureEngine(_many_bundles_inventory())
    capped = capped_engine.find_all_minimal_bundles(
        ["a"], mode=mode, max_bundles=2
    )
    assert len(capped) == 2
    # Each capped bundle is still a valid minimal bundle: round-
    # trip holds under the active mode.
    for bundle in capped:
        roundtrip = capped_engine.find_segments(dict(bundle), mode=mode)
        assert roundtrip == ["a"]


# ---------------------------------------------------------------
# ``mode`` is keyword-only
# ---------------------------------------------------------------


def test_mode_argument_is_keyword_only() -> None:
    """``mode`` must be a keyword argument. The signature pins it
    after a ``*`` so callers cannot accidentally pass a mode
    positionally and silently flip semantics; the engine module
    wires this guarantee into every match-bearing method. Verified
    on :py:meth:`FeatureEngine.find_all_minimal_bundles`; the same
    guarantee applies to :py:meth:`find_segments`,
    :py:meth:`is_natural_class`,
    :py:meth:`compute_natural_class`, and
    :py:meth:`complete_to_minimal_natural_class`.
    """
    engine = FeatureEngine(_many_bundles_inventory())
    with pytest.raises(TypeError):
        # Positional ``mode`` is rejected by the keyword-only
        # boundary in the signature.
        engine.find_all_minimal_bundles(
            ["a"], MatchMode.WILDCARD  # type: ignore[misc]
        )


def _contour_wildcard_inv() -> Inventory:
    """A(f+), C(f-), and contour B whose ``f`` runs ``+,-``: the shape
    where the wildcard EXCLUDERS and the wildcard MATCHER used to read
    different sets. B sits in both ``plus_segs[f]`` and
    ``minus_segs[f]`` (tier-true membership) but in NEITHER exclusive
    set, so no wildcard constraint can rule B out."""
    return Inventory.parse(
        {
            "features": ["F", "G"],
            "segments": {
                "A": {"F": "+", "G": "+"},
                "B": {"F": "+", "G": "-"},
                "C": {"F": "-", "G": "-"},
            },
            "metadata": {"segment_sequences": {"B": {"F": ["+", "-"]}}},
        }
    )


def test_wildcard_bundles_round_trip_with_contour_outside_segment():
    """EVERY bundle the wildcard search emits must round-trip: typing
    it back into ``find_segments`` under wildcard yields exactly the
    input selection. The old excluders read the full polarity sets, so
    for the selection {A} they counted the contour B as excludable by
    ``(F, '+')`` while the matcher (subtracting only the EXCLUSIVE
    sets) kept B, and the emitted ``{F: '+'}`` over-matched to {A, B}.
    Both halves of the query must share one membership relation. This
    test fails on the pre-fix excluders and pins the repaired
    round-trip."""
    eng = FeatureEngine(_contour_wildcard_inv())
    for selection in (["A"], ["B"], ["C"], ["A", "B"], ["B", "C"]):
        bundles = eng.find_all_minimal_bundles(
            selection, mode=MatchMode.WILDCARD
        )
        for bundle in bundles:
            matched = set(
                eng.find_segments(dict(bundle), mode=MatchMode.WILDCARD)
            )
            assert matched == set(selection), (
                f"wildcard bundle {dict(bundle)} for {selection} "
                f"over-matches to {sorted(matched)}"
            )


def test_wildcard_selection_indistinct_from_contour_is_not_a_class():
    """{A} alone cannot be a wildcard natural class in this inventory
    on ``F`` grounds: the contour B is compatible with either polarity
    of ``F``, so only ``G`` separates them. The emitted bundles must
    lean on ``G``, never on an ``F`` constraint that pretends to
    exclude B."""
    eng = FeatureEngine(_contour_wildcard_inv())
    bundles = eng.find_all_minimal_bundles(["A"], mode=MatchMode.WILDCARD)
    assert bundles, "G:+ separates A from B and C under wildcard"
    for bundle in bundles:
        spec = dict(bundle)
        if spec.get("F") == "+" and len(spec) == 1:
            raise AssertionError(
                f"{spec} cannot characterize {{A}}: contour B matches it"
            )


def test_strict_contour_singleton_is_the_class_its_minus_bundle_names():
    """{B} where B contours on F (A is exclusively +F): by the module's
    own definition ``{F: '-'}`` characterizes {B} exactly under strict
    (``minus_segs[F] == {B}``), so ``is_natural_class(['B'])`` must be
    True and the bundle must be emitted. The old candidate dict kept
    one pair per feature and the ``elif`` privileged ``+``, so the
    equally valid minus candidate was silently dropped and strict
    detection denied a class ``find_segments`` characterizes."""
    inv = Inventory.parse(
        {
            "features": ["F", "G"],
            "segments": {
                "A": {"F": "+", "G": "+"},
                "B": {"F": "+", "G": "+"},
            },
            "metadata": {"segment_sequences": {"B": {"F": ["+", "-"]}}},
        }
    )
    eng = FeatureEngine(inv)
    # ground truth the bundle language must recover:
    assert eng.find_segments({"F": "-"}, mode=MatchMode.STRICT) == ["B"]
    ok, bundles = eng.is_natural_class(["B"], mode=MatchMode.STRICT)
    assert ok, "strict detection denied a class find_segments characterizes"
    assert {"F": "-"} in [dict(b) for b in bundles]
    # and every emitted bundle round-trips exactly:
    for b in bundles:
        assert eng.find_segments(dict(b), mode=MatchMode.STRICT) == ["B"]


def test_bundle_never_collapses_both_polarities_of_one_feature():
    """A cover that needs BOTH (F,+) and (F,-) is not expressible in
    the dict bundle language (a dict holds one value per feature), so
    the search must reject it rather than emit a silently collapsed
    over-matching bundle. Here only conjoining both polarities of F
    would isolate the contour B (no G contrast exists), so {B} is
    correctly NOT a strict natural class in the bundle language."""
    inv = Inventory.parse(
        {
            "features": ["F"],
            "segments": {
                "A": {"F": "+"},
                "B": {"F": "+"},
                "C": {"F": "-"},
            },
            "metadata": {"segment_sequences": {"B": {"F": ["+", "-"]}}},
        }
    )
    eng = FeatureEngine(inv)
    ok, bundles = eng.is_natural_class(["B"], mode=MatchMode.STRICT)
    assert not ok, (
        f"emitted {bundles}; no single-valued F spec matches exactly B "
        f"(F:+ matches A,B; F:- matches B,C)"
    )
    for b in bundles:
        assert eng.find_segments(dict(b), mode=MatchMode.STRICT) == ["B"]
