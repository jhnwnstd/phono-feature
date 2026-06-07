"""Wildcard-mode contract for ``complete_to_minimal_natural_class``.

Pins the public semantics of the wildcard match mode on the
completion API: when ``S`` is already a natural class under the
active mode, the result carries ``selected_minimal_bundles``;
otherwise ``additions`` carries the smallest set that closes the
class. The wildcard completion is always a subset of the strict
completion because wildcard's candidate space is strictly wider.
These tests cover the synthetic p/b/m demo case, parametrised
Hayes-inventory selections, and the keyword-only / empty-input
edge cases.
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
# Synthetic p/b/m inventory
#
# Voice and Nasal are the only features. /m/ is left UNDERSPECIFIED
# for Voice so that {b, m} fails strict natural-class membership
# (Voice="+" matches /b/ only, no shared explicit feature exists),
# while wildcard mode treats /m/'s "0" as compatible with Voice="+"
# and characterises {b, m} as a wildcard NC with bundle
# ``{Voice: "+"}``. This is the smallest inventory that distinguishes
# the two modes on the completion API and matches the contract
# example called out in the task description.
# ----------------------------------------------------------------------


@pytest.fixture
def pbm_engine() -> FeatureEngine:
    """Synthetic three-segment engine that distinguishes the modes.

    /m/'s Voice is "0" so that under STRICT the pair {b, m} shares
    no explicit feature value and is therefore not a natural class
    (completion must add /p/); under WILDCARD the pair satisfies
    ``{Voice: "+"}`` because "0" is compatible with the requested
    polarity, so {b, m} is already a natural class with no
    additions required.
    """
    inv = Inventory.from_grid(
        name="pbm",
        features=["Voice", "Nasal"],
        segments={
            "p": {"Voice": "-", "Nasal": "-"},
            "b": {"Voice": "+", "Nasal": "-"},
            "m": {"Voice": "0", "Nasal": "+"},
        },
    )
    return FeatureEngine(inv)


def test_pbm_strict_completes_bm_by_adding_p(
    pbm_engine: FeatureEngine,
) -> None:
    """Under STRICT, {b, m} share no explicit +/- value, so no
    strict bundle characterises the pair and the smallest containing
    natural class is the universal class. The solver returns the
    single missing segment /p/ in ``additions[0]``. Pinning this
    confirms the strict path falls through to the universal-class
    fallback when no candidate constraint exists.
    """
    result = pbm_engine.complete_to_minimal_natural_class(
        ["b", "m"], mode=MatchMode.STRICT
    )
    assert result.status == "one_minimal_completion"
    assert result.selected_minimal_bundles == ()
    assert len(result.additions) == 1
    assert set(result.additions[0]) == {"p"}


def test_pbm_wildcard_treats_bm_as_already_natural_class(
    pbm_engine: FeatureEngine,
) -> None:
    """Under WILDCARD, /m/'s underspecified Voice is compatible
    with Voice="+", so {b, m} is characterised by the wildcard
    bundle ``{Voice: "+"}`` and no additions are needed. Pinning
    this confirms wildcard widens the candidate space precisely
    enough to fold the underspecified segment into the class
    without enlarging the selection.
    """
    result = pbm_engine.complete_to_minimal_natural_class(
        ["b", "m"], mode=MatchMode.WILDCARD
    )
    assert result.status == "already_natural_class"
    assert result.additions == ()
    assert result.selected_minimal_bundles, (
        "wildcard NC must report at least one minimal bundle for " "{b, m}"
    )
    # Every reported bundle must round-trip under wildcard
    # matching to exactly {b, m}.
    for bundle in result.selected_minimal_bundles:
        recovered = pbm_engine.find_segments(
            dict(bundle), mode=MatchMode.WILDCARD
        )
        assert set(recovered) == {"b", "m"}, (
            f"wildcard bundle {dict(bundle)} did not round-trip to "
            f"{{b, m}}; got {recovered}"
        )


def test_pbm_wildcard_additions_subset_of_strict_for_bm(
    pbm_engine: FeatureEngine,
) -> None:
    """On the same input, the wildcard completion must be a subset
    of the strict completion. For {b, m} the strict completion adds
    {p}; the wildcard completion adds nothing. ``set() ⊆ {p}``
    holds. This pins the subset invariant on the smallest inventory
    that actually exercises both branches.
    """
    strict = pbm_engine.complete_to_minimal_natural_class(
        ["b", "m"], mode=MatchMode.STRICT
    )
    wild = pbm_engine.complete_to_minimal_natural_class(
        ["b", "m"], mode=MatchMode.WILDCARD
    )
    strict_set: set[str] = set()
    for adds in strict.additions:
        strict_set |= set(adds)
    wild_set: set[str] = set()
    for adds in wild.additions:
        wild_set |= set(adds)
    assert wild_set <= strict_set, (
        f"wildcard additions {wild_set} are not a subset of strict"
        f" additions {strict_set}"
    )


# ----------------------------------------------------------------------
# Wildcard-additions-subset-of-strict invariant, parametrised over
# realistic Hayes selections. The wildcard candidate set is a strict
# superset of the strict candidate set, so the wildcard smallest-
# containing-class is contained in the strict one, and therefore
# wildcard additions ⊆ strict additions.
# ----------------------------------------------------------------------


HAYES_SELECTIONS = [
    pytest.param(["b", "d", "ɡ"], id="voiced_stops"),
    pytest.param(["p", "t", "k"], id="voiceless_stops"),
    pytest.param(["m", "n", "ŋ"], id="nasals"),
    pytest.param(["f", "v", "s", "z"], id="fricatives_subset"),
    pytest.param(["l"], id="lateral_singleton"),
    pytest.param(["b", "m"], id="voiced_bilabials"),
    pytest.param(["p", "b"], id="bilabial_stops_pair"),
    pytest.param(["s", "z", "ʃ"], id="sibilants_mixed"),
    pytest.param(["i", "u"], id="high_vowels"),
]


@pytest.mark.parametrize("selection", HAYES_SELECTIONS)
def test_wildcard_additions_subset_of_strict(
    bundled_engine: Callable[[str], FeatureEngine],
    selection: list[str],
) -> None:
    """For any selection, the union of wildcard ``additions``
    segments must be a subset of the union of strict ``additions``
    segments. Wildcard candidates are a superset of strict ones,
    so the wildcard smallest-containing-class is a subset of the
    strict one, and the additions follow. Selections that are
    natural classes under either mode contribute empty addition
    sets, which trivially satisfy the subset property.
    """
    engine = bundled_engine("hayes")
    missing = [s for s in selection if s not in engine.segments]
    if missing:
        pytest.skip(
            f"selection {selection} references segments missing from"
            f" Hayes: {missing}"
        )
    strict = engine.complete_to_minimal_natural_class(
        selection, mode=MatchMode.STRICT
    )
    wild = engine.complete_to_minimal_natural_class(
        selection, mode=MatchMode.WILDCARD
    )
    strict_union: set[str] = set()
    for adds in strict.additions:
        strict_union |= set(adds)
    wild_union: set[str] = set()
    for adds in wild.additions:
        wild_union |= set(adds)
    assert wild_union <= strict_union, (
        f"selection {selection}: wildcard additions {wild_union} "
        f"are not a subset of strict additions {strict_union}"
    )


# ----------------------------------------------------------------------
# Already-an-NC shape symmetry: when ``S`` is a strict NC, both
# modes return ``already_natural_class`` with populated
# ``selected_minimal_bundles`` and empty ``additions``. The
# CONTENTS of the bundles differ (wildcard bundles are typically
# shorter), but the SHAPE of the result is identical.
# ----------------------------------------------------------------------


def test_already_strict_nc_same_shape_in_both_modes(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """When ``S`` is already a strict natural class, it is also a
    wildcard natural class (every strict bundle is a wildcard
    bundle). Both modes must therefore return
    ``already_natural_class`` with ``additions == ()`` and at
    least one minimal bundle in ``selected_minimal_bundles``; this
    pins the shape symmetry even though the bundle contents differ
    between modes.
    """
    engine = bundled_engine("hayes")
    if "l" not in engine.segments:
        pytest.skip("Hayes fixture missing /l/")
    # /l/ is a known strict NC in Hayes (see test_engine_api).
    selection = ["l"]
    is_nc, _ = engine.is_natural_class(selection, mode=MatchMode.STRICT)
    assert is_nc, (
        "test fixture assumption broken: /l/ is no longer a strict"
        " NC in the bundled Hayes inventory"
    )
    strict = engine.complete_to_minimal_natural_class(
        selection, mode=MatchMode.STRICT
    )
    wild = engine.complete_to_minimal_natural_class(
        selection, mode=MatchMode.WILDCARD
    )
    assert strict.status == "already_natural_class"
    assert wild.status == "already_natural_class"
    assert strict.additions == ()
    assert wild.additions == ()
    assert (
        strict.selected_minimal_bundles
    ), "strict /l/ NC must report at least one minimal bundle"
    assert (
        wild.selected_minimal_bundles
    ), "wildcard /l/ NC must report at least one minimal bundle"


# ----------------------------------------------------------------------
# Keyword-only enforcement: ``mode`` must be passed by name. This
# pins the API contract: a positional MatchMode after segments
# must raise TypeError so accidental positional drift cannot pass
# silently as some other meaning.
# ----------------------------------------------------------------------


def test_mode_is_keyword_only(pbm_engine: FeatureEngine) -> None:
    """The ``mode`` parameter on
    :py:meth:`complete_to_minimal_natural_class` is keyword-only.
    Passing it positionally must raise :py:class:`TypeError`. This
    pins the API to the documented signature and prevents callers
    from silently relying on a positional position that could drift.
    """
    with pytest.raises(TypeError):
        # Type-checker would also flag this; the runtime check is
        # the contract this test pins.
        pbm_engine.complete_to_minimal_natural_class(  # type: ignore[misc]
            ["b", "m"], MatchMode.WILDCARD
        )


# ----------------------------------------------------------------------
# Empty-input contract: both modes return ``already_natural_class``
# with empty bundles. The empty selection has no characterising
# bundle (the empty bundle's extent is the whole inventory, not
# ``∅``); the API encodes this as the "already" verdict with no
# data on either side rather than synthesising a definition.
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param(MatchMode.STRICT, id="strict"),
        pytest.param(MatchMode.WILDCARD, id="wildcard"),
    ],
)
def test_empty_input_returns_already_with_empty_bundles(
    pbm_engine: FeatureEngine, mode: MatchMode
) -> None:
    """The empty selection is treated identically by both modes:
    ``status == "already_natural_class"`` with both
    ``selected_minimal_bundles`` and ``additions`` empty. There is
    no characterising bundle (the empty bundle matches the whole
    inventory, not ``∅``), so the API does not invent one; the
    empty/empty shape is the documented contract for this edge
    case.
    """
    result = pbm_engine.complete_to_minimal_natural_class([], mode=mode)
    assert result.status == "already_natural_class"
    assert result.selected_minimal_bundles == ()
    assert result.additions == ()
