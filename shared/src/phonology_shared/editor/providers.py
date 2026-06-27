"""Feature-provider abstraction for the New-inventory setup flow.

A :py:class:`FeatureProvider` derives feature-value bundles for a
list of user-supplied segment symbols. The desktop builder calls
``provider.generate(segments)`` after the setup dialog accepts; the
returned :py:class:`GeneratedInventory` carries the canonical
feature list, the per-segment bundles, and any unresolved symbols
the user needs to edit by hand.

This module is pure Python with stdlib-only imports so it stays
Pyodide-safe. Concrete providers (``PanPhonFeatureProvider`` on
desktop, ``LookupTableProvider`` and ``PhoibleProvider`` shared
between both UIs) live in client-specific packages because they
may depend on optional dependencies the shared layer cannot assume.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class GeneratedInventory:
    """Result of :py:meth:`FeatureProvider.generate`.

    Shape mirrors what
    :py:meth:`phonology_shared.data.inventory.Inventory.from_grid`
    consumes, so the dialog can hand the result straight through
    without reshaping.

    Attributes:
        features: Canonical, ordered feature list the provider
            emits. The dialog uses this verbatim as the inventory's
            feature axis; the user can add or rename features in
            the grid editor afterward.
        segments: Per-segment ``{feature: "+"/"-"/"0"}`` bundles for
            every successfully resolved symbol. Unresolved symbols
            are NOT present here; the builder seeds them with
            :py:func:`blank_bundle` so the grid still shows a
            column for the user to edit.
        unresolved: Symbols the provider could not resolve, in
            input order. The builder surfaces the count in the
            status bar so unresolved cases never disappear
            silently.
        warnings: Human-readable per-symbol diagnostics. Each entry
            is meant for a log line, not a modal; the dialog reports
            the unresolved count and routes the detail to the log.
        segment_secondary: Optional secondary feature bundles for
            vowel diphthongs. Sparse: only PHOIBLE diphthong
            segments populate this; PanPhon and curated bundles
            leave it empty. Keys are the same segment strings as in
            ``segments``; values are the final-state bundle the
            vowel glides toward. The placement code reads it to
            draw a diphthong arrow between two cells; consumers
            that ignore the field still get a sensible single-vowel
            placement from the primary ``segments`` bundle.
    """

    features: tuple[str, ...]
    segments: Mapping[str, Mapping[str, str]]
    unresolved: tuple[str, ...]
    warnings: tuple[str, ...]
    segment_secondary: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )


@runtime_checkable
class FeatureProvider(Protocol):
    """Generate a starting feature table from a list of IPA symbols.

    Implementations live in client-specific packages so optional
    dependencies do not leak into the shared layer. The dialog and
    the builder only see this Protocol.
    """

    #: Short identifier used in metadata provenance and in the
    #: dialog dropdown lookup. Stable across versions of the
    #: underlying source.
    name: str

    #: Optional version string of the underlying source (e.g.
    #: ``panphon.__version__``). Recorded in inventory metadata
    #: alongside :py:attr:`name`. ``"unknown"`` is acceptable.
    version: str

    def display_label(self) -> str:
        """Label shown in the setup-dialog preset dropdown.

        Defaults to ``f"{self.name} (auto-generate)"`` for
        providers that have not overridden it; the dialog calls
        this once at populate time.
        """
        ...

    def feature_names(self) -> tuple[str, ...]:
        """Canonical feature list the provider will emit.

        Called by the dialog before any segments are entered so the
        user can see what feature set they are opting into. Must be
        consistent with the ``features`` field of every
        :py:class:`GeneratedInventory` this provider returns.
        """
        ...

    def generate(self, segments: list[str]) -> GeneratedInventory:
        """Resolve ``segments`` to feature bundles.

        Never raises for unresolved symbols; they go into
        :py:attr:`GeneratedInventory.unresolved` with a per-symbol
        warning. The provider may raise for catastrophic failures
        (data file missing, etc.); the dialog reports these in the
        status bar without aborting the New-inventory flow.
        """
        ...


def prune_unused_features(
    features: tuple[str, ...],
    resolved: Mapping[str, Mapping[str, str]],
    *,
    extra_bundles: Iterable[Mapping[str, str]] = (),
) -> tuple[str, ...]:
    """Feature columns at least one resolved bundle specifies with
    ``"+"`` or ``"-"``, in their original order.

    The single pruning rule every provider's ``generate`` applies
    (mirrors PanPhon's behaviour: a small inventory should not
    carry every column the source ships). Returns ``features``
    unchanged when ``resolved`` is empty so an empty inventory
    still has columns to show. ``extra_bundles`` lets the PHOIBLE
    provider count its diphthong secondary bundles as used;
    otherwise a diphthong distinguished only by its final half
    would lose its discriminator.
    """
    if not resolved:
        return features
    used = {
        feat
        for bundle in resolved.values()
        for feat, value in bundle.items()
        if value in ("+", "-")
    }
    for bundle in extra_bundles:
        for feat, value in bundle.items():
            if value in ("+", "-"):
                used.add(feat)
    return tuple(feat for feat in features if feat in used)


def restrict_bundles(
    bundles: Mapping[str, Mapping[str, str]],
    features: tuple[str, ...],
) -> dict[str, Mapping[str, str]]:
    """Project every bundle onto the (post-prune) ``features``."""
    keep = set(features)
    out: dict[str, Mapping[str, str]] = {
        seg: {feat: val for feat, val in bundle.items() if feat in keep}
        for seg, bundle in bundles.items()
    }
    return out


def blank_bundle(features: tuple[str, ...]) -> dict[str, str]:
    """Return ``{feature: "0"}`` for every feature.

    Used by the builder to seed grid columns for symbols the
    provider could not resolve, so the user can edit the cells in
    place instead of re-typing the symbol after a manual fix.
    """
    return {feature: "0" for feature in features}


def decode_positional_bundle(
    features: tuple[str, ...] | list[str], encoded: str
) -> dict[str, str]:
    """Pair ``features`` with a positionally-encoded value string.

    A baked bundle ships as one character per feature (``"+-0..."``)
    for compactness; decoding is a positional ``zip``. ``strict=False``
    tolerates a value string shorter or longer than ``features`` (the
    callers validate length separately and skip mismatches), so a
    snapshot baked against a slightly different column set degrades to
    a partial bundle instead of raising. Single definition of the
    positional-encoding contract shared by every provider that loads
    baked tables.
    """
    return dict(zip(features, encoded, strict=False))


def _filter_encoded_bundles(
    segments: Mapping[object, object], n: int
) -> dict[str, str]:
    """Select the usable survivors from one inventory's baked segment
    map: ``{sym: encoded}`` for every entry that is a ``str`` symbol
    mapped to a ``str`` value of exactly ``n`` characters.

    Entries failing either check are skipped: a non-str key/value, or a
    length mismatch from a snapshot baked against a different column
    count (a forward-compat skip, not a raise, so a snapshot with extra
    columns from a newer bake doesn't crash an older runtime). The
    single definition of "which baked entries are usable", shared by
    the PHOIBLE primary + secondary ingests and the PanPhon lookup
    table loader.
    """
    return {
        sym: encoded
        for sym, encoded in segments.items()
        if isinstance(sym, str)
        and isinstance(encoded, str)
        and len(encoded) == n
    }
