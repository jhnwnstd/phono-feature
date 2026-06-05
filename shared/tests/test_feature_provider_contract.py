"""Contract tests for the :py:mod:`phonology_shared.editor.providers`
abstraction.

PanPhon (or any future provider) plugs in via the
:py:class:`FeatureProvider` Protocol; these tests pin the Protocol
shape and the round-trip from a generator output through
:py:meth:`Inventory.from_grid` and back, without depending on the
optional PanPhon dependency. A stub provider stands in for the
real implementations so the contract is exercised even on CI
runners that do not install ``panphon``.
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.data.inventory import Inventory
from phonology_shared.editor.grid import grid_to_inventory
from phonology_shared.editor.providers import (
    FeatureProvider,
    GeneratedInventory,
    blank_bundle,
)


class _StubProvider:
    """Hand-built :py:class:`FeatureProvider` for the contract test.

    Resolves any segment whose first character is in the configured
    ``known`` set; everything else lands in ``unresolved``. The
    feature set is the two major-class features so the test pins
    the smallest interesting shape.
    """

    name = "Stub"
    version = "1.0"
    _features: tuple[str, ...] = ("Syllabic", "Consonantal")
    _known: frozenset[str] = frozenset({"p", "b", "i", "u"})

    def display_label(self) -> str:
        return f"{self.name} (auto-generate)"

    def feature_names(self) -> tuple[str, ...]:
        return self._features

    def generate(self, segments: list[str]) -> GeneratedInventory:
        resolved: dict[str, Mapping[str, str]] = {}
        unresolved: list[str] = []
        warnings: list[str] = []
        for sym in segments:
            head = sym[:1]
            if head in self._known:
                # Vowels: +Syllabic, -Consonantal. Consonants: opposite.
                is_vowel = head in {"i", "u"}
                resolved[sym] = {
                    "Syllabic": "+" if is_vowel else "-",
                    "Consonantal": "-" if is_vowel else "+",
                }
            else:
                unresolved.append(sym)
                warnings.append(
                    f"{sym!r}: stub does not recognise this symbol"
                )
        return GeneratedInventory(
            features=self._features,
            segments=resolved,
            unresolved=tuple(unresolved),
            warnings=tuple(warnings),
        )


def test_stub_provider_satisfies_protocol() -> None:
    """``isinstance(provider, FeatureProvider)`` must hold for any
    duck-typed implementation that supplies ``name``, ``version``,
    ``display_label``, ``feature_names``, and ``generate``.
    """
    provider: FeatureProvider = _StubProvider()
    assert isinstance(provider, FeatureProvider)
    assert provider.name == "Stub"
    assert provider.version == "1.0"
    assert provider.display_label().endswith("(auto-generate)")


def test_blank_bundle_returns_all_zero_per_feature() -> None:
    """The unresolved-segment seed is exactly ``"0"`` per declared
    feature; the builder relies on this to surface unresolved
    columns as visibly-empty without raising at parse time."""
    features = ("Syllabic", "Consonantal", "Voice")
    bundle = blank_bundle(features)
    assert set(bundle.keys()) == set(features)
    assert all(v == "0" for v in bundle.values())


def test_generated_bundles_round_trip_through_inventory_from_grid() -> None:
    """The generator output must satisfy
    :py:meth:`Inventory.from_grid` without reshaping. The dialog
    relies on this so the New-inventory path stays a single
    validation chokepoint regardless of how the bundles were
    sourced.
    """
    provider = _StubProvider()
    result = provider.generate(["p", "i", "customX"])
    assert "p" in result.segments
    assert "i" in result.segments
    assert result.unresolved == ("customX",)

    # Seed the unresolved column with a blank bundle, matching what
    # the builder will do at integration time.
    segments_payload: dict[str, dict[str, str]] = {
        seg: dict(bundle) for seg, bundle in result.segments.items()
    }
    for sym in result.unresolved:
        segments_payload[sym] = blank_bundle(result.features)

    inv = Inventory.from_grid(
        name="Provider Round Trip",
        features=list(result.features),
        segments=segments_payload,
    )
    assert inv.name == "Provider Round Trip"
    assert set(inv.segments) == {"p", "i", "customX"}
    # +Syllabic for the vowel, -Syllabic for the consonant, "0"
    # (missing) for the unresolved column.
    assert inv.segments["i"]["Syllabic"] == "+"
    assert inv.segments["p"]["Syllabic"] == "-"
    assert inv.segments["customX"]["Syllabic"] == "0"


def test_grid_to_inventory_stamps_metadata_provenance() -> None:
    """The ``metadata`` kwarg added to :py:func:`grid_to_inventory`
    must surface verbatim on the resulting inventory's ``metadata``
    mapping so the builder can record provider provenance on save.
    """
    cells: list[list[str]] = [
        ["+", "-"],  # Syllabic: vowel +, consonant -
        ["-", "+"],  # Consonantal: vowel -, consonant +
    ]
    inv = grid_to_inventory(
        name="Provenance Test",
        features=["Syllabic", "Consonantal"],
        segments=["i", "p"],
        cells=cells,
        metadata={
            "feature_source": "Stub",
            "feature_source_version": "1.0",
        },
    )
    assert inv.metadata.get("feature_source") == "Stub"
    assert inv.metadata.get("feature_source_version") == "1.0"
    # The explicit ``name`` argument wins even if ``metadata``
    # supplies its own; tested in
    # ``test_from_grid_metadata_does_not_overwrite_name`` below.


def test_from_grid_metadata_does_not_overwrite_name() -> None:
    """If a caller mistakenly puts ``name`` in the ``metadata`` map,
    the explicit ``name=`` argument still wins. Pins the one-source-
    of-truth invariant the docstring promises.
    """
    inv = Inventory.from_grid(
        name="Explicit Name",
        features=["Syllabic"],
        segments={"i": {"Syllabic": "+"}},
        metadata={"name": "Should Be Ignored", "feature_source": "Stub"},
    )
    assert inv.name == "Explicit Name"
    assert inv.metadata.get("feature_source") == "Stub"
