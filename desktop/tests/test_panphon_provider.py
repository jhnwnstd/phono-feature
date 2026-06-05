"""Tests for :py:mod:`phonology_features.providers.panphon_provider`.

Skipped at collection time when the optional ``panphon`` package is
absent so a fresh install without the extra still passes the full
suite. The cases assert what the provider PROMISES about behaviour,
not the exact PanPhon numbers, so a minor PanPhon point release
that adds or renames a feature column does not break the tests.
"""

from __future__ import annotations

import pytest

# Skip the whole module when panphon is not installed. ``importorskip``
# raises ``Skipped`` at import time so the rest of the suite never
# constructs a provider it would only skip.
pytest.importorskip("panphon")

from phonology_features.providers.panphon_provider import (  # noqa: E402
    PANPHON_TO_APP_FEATURE,
    PanPhonFeatureProvider,
)
from phonology_shared.data.inventory import Inventory  # noqa: E402
from phonology_shared.editor.providers import blank_bundle  # noqa: E402


@pytest.fixture(scope="module")
def provider() -> PanPhonFeatureProvider:
    """One PanPhon instance per module. ``FeatureTable`` construction
    parses several CSVs; reusing the instance across tests keeps the
    module under a second."""
    return PanPhonFeatureProvider()


def test_provider_advertises_name_and_version(
    provider: PanPhonFeatureProvider,
) -> None:
    """``name`` is the stable identifier the dialog persists into
    inventory metadata; ``version`` is best-effort string from
    ``importlib.metadata`` so saved JSON records what produced it."""
    assert provider.name == "PanPhon"
    assert isinstance(provider.version, str) and provider.version


def test_display_label_is_just_name(
    provider: PanPhonFeatureProvider,
) -> None:
    """The dropdown entry shows the bare provider name; the parent
    label ("Features (delimited):") already conveys what picking it
    does, so a "(auto-generate)" suffix is redundant."""
    assert provider.display_label() == "PanPhon"


def test_feature_names_are_app_canonical(
    provider: PanPhonFeatureProvider,
) -> None:
    """``feature_names`` must be a subset of the canonical mapping's
    values; otherwise the bundles ``generate`` emits would not line
    up with the features the dialog declares."""
    names = provider.feature_names()
    assert len(names) >= 22
    for name in names:
        assert name in PANPHON_TO_APP_FEATURE.values()


def test_known_consonants_resolve_with_consonantal_plus(
    provider: PanPhonFeatureProvider,
) -> None:
    """``p`` and ``b`` should be -Syllabic +Consonantal. This pins
    the broad-stroke major-class assignment without depending on
    PanPhon's specific manner-feature values."""
    result = provider.generate(["p", "b"])
    assert result.unresolved == ()
    for seg in ("p", "b"):
        assert result.segments[seg]["Syllabic"] == "-"
        assert result.segments[seg]["Consonantal"] == "+"


def test_known_vowels_resolve_with_syllabic_plus(
    provider: PanPhonFeatureProvider,
) -> None:
    """``i`` and ``u`` should be +Syllabic, -Consonantal."""
    result = provider.generate(["i", "u"])
    assert result.unresolved == ()
    for seg in ("i", "u"):
        assert result.segments[seg]["Syllabic"] == "+"
        assert result.segments[seg]["Consonantal"] == "-"


def test_voicing_pair_b_voiced_p_voiceless(
    provider: PanPhonFeatureProvider,
) -> None:
    """The /p, b/ voicing pair is the smallest reliable contrast
    test. Pins that PanPhon's Voice column survives the mapping
    intact."""
    result = provider.generate(["p", "b"])
    assert result.segments["p"]["Voice"] == "-"
    assert result.segments["b"]["Voice"] == "+"


def test_velar_nasal_and_glottal_stop_resolve(
    provider: PanPhonFeatureProvider,
) -> None:
    """``ŋ`` and ``ʔ`` are the idea.md's regression targets for
    PanPhon support beyond plain alphabet letters."""
    result = provider.generate(["ŋ", "ʔ"])
    assert result.unresolved == ()
    assert result.segments["ŋ"]["Nasal"] == "+"
    # ʔ has +Constricted Glottis in PanPhon's table.
    assert result.segments["ʔ"]["ConstrGl"] == "+"


def test_tie_bar_affricate_resolves_as_single_segment(
    provider: PanPhonFeatureProvider,
) -> None:
    """The combining tie-bar (U+0361) is what makes PanPhon treat
    ``t͡ʃ`` as one segment. Pins that the dialog can pass
    affricates through and get a bundle back, not an unresolved
    entry."""
    result = provider.generate(["t͡ʃ"])
    assert result.unresolved == ()
    assert "t͡ʃ" in result.segments


def test_unrecognised_symbol_lands_in_unresolved(
    provider: PanPhonFeatureProvider,
) -> None:
    """An obviously-non-IPA token must never silently disappear or
    silently get a bundle. PanPhon parses ``customX`` as multiple
    sub-segments, which is the documented unresolved case."""
    result = provider.generate(["customX"])
    assert result.segments == {}
    assert "customX" in result.unresolved
    assert any("customX" in w for w in result.warnings)


def test_order_preserved_across_resolved_and_unresolved(
    provider: PanPhonFeatureProvider,
) -> None:
    """``generate`` keeps the input order in both ``segments`` (dict
    insertion order) and ``unresolved`` (list order) so the dialog
    can report stable per-segment status without re-sorting."""
    result = provider.generate(["p", "customX", "b"])
    assert list(result.segments.keys()) == ["p", "b"]
    assert result.unresolved == ("customX",)


def test_generated_payload_round_trips_through_inventory_from_grid(
    provider: PanPhonFeatureProvider,
) -> None:
    """A generated result must satisfy
    :py:meth:`Inventory.from_grid` so the builder can feed it
    through the same validation chokepoint as user-authored grids.
    Unresolved columns get seeded with :py:func:`blank_bundle`
    matching what the builder's setup-dialog branch does at
    integration time.
    """
    result = provider.generate(["p", "i", "customX"])
    segments_payload: dict[str, dict[str, str]] = {
        seg: dict(bundle) for seg, bundle in result.segments.items()
    }
    for sym in result.unresolved:
        segments_payload[sym] = blank_bundle(result.features)

    inv = Inventory.from_grid(
        name="PanPhon Round Trip",
        features=list(result.features),
        segments=segments_payload,
        metadata={
            "feature_source": provider.name,
            "feature_source_version": provider.version,
        },
    )
    assert inv.name == "PanPhon Round Trip"
    assert set(inv.segments) == {"p", "i", "customX"}
    assert inv.metadata.get("feature_source") == "PanPhon"
    assert inv.segments["i"]["Syllabic"] == "+"
    assert inv.segments["p"]["Syllabic"] == "-"
    # Unresolved column: every feature is "0" (missing in JSON).
    assert inv.segments["customX"].get("Syllabic", "0") == "0"


def test_empty_segment_list_returns_empty_result(
    provider: PanPhonFeatureProvider,
) -> None:
    """Edge case: no segments means no bundles to generate. The
    dialog's validation already rejects empty segment lists before
    this is called, but the provider should still be total.
    The full feature set is returned because there is no resolved
    bundle to filter against (the user gets every column to edit
    on the empty path)."""
    result = provider.generate([])
    assert result.segments == {}
    assert result.unresolved == ()
    assert result.warnings == ()
    assert len(result.features) >= 22


def test_unused_features_are_pruned_for_a_single_vowel(
    provider: PanPhonFeatureProvider,
) -> None:
    """A single ``/i/`` resolution must not pull in every feature
    PanPhon defines. Features the vowel does not specify
    ("0"-valued ones) get pruned from both ``features`` and the
    bundle so the user is not handed a sparse 24-column grid for
    a one-segment inventory. Pins the bloat-prevention behaviour
    the user requested.
    """
    result = provider.generate(["i"])
    full_count = len(provider.feature_names())
    assert len(result.features) < full_count
    # Every returned feature must actually be specified on ``i``.
    bundle = result.segments["i"]
    assert set(bundle.keys()) == set(result.features)
    assert all(v in ("+", "-") for v in bundle.values())


def test_pruning_preserves_canonical_feature_order(
    provider: PanPhonFeatureProvider,
) -> None:
    """The kept-features tuple stays in the canonical PanPhon order
    after filtering. Pins that the dialog and the builder see a
    stable column order regardless of which segments were
    submitted."""
    full = provider.feature_names()
    result = provider.generate(["p"])
    kept = result.features
    # Indices of kept features in the original order must be
    # strictly increasing; i.e. no reordering, just deletion.
    indices = [full.index(name) for name in kept]
    assert indices == sorted(indices)


def test_pruning_keeps_full_feature_set_when_nothing_resolves(
    provider: PanPhonFeatureProvider,
) -> None:
    """If every input symbol is unresolved (e.g. typos only), the
    pruning step has no resolved bundles to inspect and so cannot
    decide which features are "in use". Return the full feature
    set so the user still has a grid to edit by hand."""
    result = provider.generate(["customX"])
    assert result.segments == {}
    assert "customX" in result.unresolved
    assert result.features == provider.feature_names()


def test_registry_exposes_panphon_when_installed() -> None:
    """When panphon is installed, the desktop registry should report
    exactly one provider with name ``"PanPhon"``. Pins that the
    Builder can find the provider through the abstract registry,
    without importing ``PanPhonFeatureProvider`` directly."""
    from phonology_features.providers import (
        available_providers,
        provider_by_name,
    )

    providers = available_providers()
    assert len(providers) == 1
    assert providers[0].name == "PanPhon"
    looked_up = provider_by_name("PanPhon")
    assert looked_up is not None
    assert looked_up.name == "PanPhon"
    assert provider_by_name("DoesNotExist") is None
