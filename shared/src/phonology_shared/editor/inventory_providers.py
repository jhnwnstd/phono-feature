"""Search-driven inventory providers for the New-inventory flow.

Sibling abstraction to :py:mod:`providers` (the
:py:class:`FeatureProvider` Protocol). The distinction:

* :py:class:`~providers.FeatureProvider` takes a list of segments
  the user typed and returns feature bundles. Segments come from
  the dialog's textarea; features come from the provider.
* :py:class:`InventoryProvider` (here) provides BOTH the segments
  AND the features for a curated inventory the user picks by name.
  Today the only implementation is PHOIBLE; future implementations
  could wrap LAPSyD, Wikipedia inventories, or in-house corpora.

The two abstractions share :py:class:`~providers.GeneratedInventory`
as the return type so the rest of the pipeline (``from_grid``,
validation, save) does not branch on provider kind.

The picker flow is three-step:

  1. ``search_languages(query)`` -> list of language names matching
     the user's autocomplete input.
  2. ``list_inventories(language_name)`` -> list of
     :py:class:`InventoryDescriptor` (one per source/dialect
     variant the database holds for that language).
  3. ``generate(inventory_id)`` -> a
     :py:class:`~providers.GeneratedInventory` ready to drop into
     the grid editor.

Pure Python, stdlib-only imports so the module stays Pyodide-safe.
Concrete providers live in client-specific packages; this module
only pins the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from phonology_shared.editor.providers import GeneratedInventory

__all__ = [
    "GeneratedInventory",
    "InventoryDescriptor",
    "InventoryProvider",
]


@dataclass(frozen=True, slots=True)
class InventoryDescriptor:
    """Lightweight metadata for the inventory-picker UI.

    Carries only the fields the picker needs to disambiguate
    between multiple inventories that share a language name (the
    common PHOIBLE case: one language, several sources). The full
    segment + feature payload comes later via
    :py:meth:`InventoryProvider.generate`.

    Attributes:
        id: Provider-internal stable identifier. The provider uses
            this verbatim in :py:meth:`generate`; the picker round-
            trips it through the bridge unchanged.
        language_name: Human-readable language name (``"Korean"``).
            Used as the autocomplete match key.
        glottocode: Glottolog code if known (``"kore1280"``); for
            metadata stamping and cross-database lookups. ``None``
            for sources without one.
        iso_code: ISO 639-3 code if known (``"kor"``); same role
            as ``glottocode``.
        dialect: Specific-dialect label when the source recorded
            one (``"Seoul Korean"``); ``None`` is typical.
        source_short: Short label that the picker shows as the
            primary heading for the entry (``"SPA"``, ``"UPSID"``,
            ``"Eurasian Phonologies"``). Provider composes from its
            own source vocabulary.
        source_description: Long form that expands opaque
            acronyms in the secondary line (``"Stanford Phonology
            Archive"`` for SPA). Empty when the short label already
            says everything.
        segment_count: Number of segments in this inventory.
            Picker uses this to default-select the median sized
            entry so a stray marginal source does not become the
            user's first impression.
        source_url: Optional URL to the provider's web page
            documenting this inventory's bibliographic source(s)
            (for PHOIBLE, a phoible.org source or inventory page).
            Empty when the provider exposes no such page.
    """

    id: str
    language_name: str
    glottocode: str | None
    iso_code: str | None
    dialect: str | None
    source_short: str
    source_description: str
    segment_count: int
    source_url: str = ""


@runtime_checkable
class InventoryProvider(Protocol):
    """Search a curated database of phonological inventories and
    materialise a chosen one as a :py:class:`GeneratedInventory`.

    Implementations live in client-specific packages so the shared
    layer stays free of provider-specific dependencies. The dialog
    code only sees this Protocol.
    """

    #: Short identifier used in metadata provenance (``"PHOIBLE"``).
    #: Stable across versions of the underlying source.
    name: str

    #: Version string of the underlying source (e.g. ``"PHOIBLE
    #: 2.0"``). Recorded in inventory metadata alongside
    #: :py:attr:`name`. ``"unknown"`` is acceptable.
    version: str

    # The live default is DEFAULT_SEARCH_LIMIT in phoible_provider.py;
    # kept as a literal here so the Protocol stays decoupled from any
    # concrete provider module.
    def search_languages(self, query: str, limit: int = 20) -> list[str]:
        """Return language names matching ``query``.

        Match is provider-defined: PHOIBLE uses case-insensitive
        substring against ``LanguageName`` and ``ISO6393``. Results
        are deduplicated and ordered for stable autocomplete
        rendering. ``limit`` caps the response so the picker stays
        responsive; the caller can detect "more matches available"
        by checking ``len(result) == limit``.

        Empty ``query`` may return an empty list or a curated
        sample (provider's call); the dialog is expected to show
        results only after a non-empty input.
        """
        ...

    def list_inventories(
        self, language_name: str
    ) -> list[InventoryDescriptor]:
        """Return every inventory the database holds for the named
        language.

        Order is provider-defined but stable across calls; the
        picker may sort or filter further (e.g. default-select the
        median-segment-count entry).
        """
        ...

    def generate(self, inventory_id: str) -> GeneratedInventory:
        """Materialise the inventory ``inventory_id`` (from a
        prior :py:meth:`list_inventories` call).

        Returns a :py:class:`GeneratedInventory` with the full
        segment + feature payload. ``unresolved`` and ``warnings``
        are typically empty for curated databases; they may carry
        per-segment warnings for normalization edge cases (e.g.
        contour features collapsed to ``"0"``).

        May raise :py:class:`KeyError` for an unknown
        ``inventory_id``; the dialog reports the failure in the
        status bar without aborting the New flow.
        """
        ...

    def descriptor(self, inventory_id: str) -> InventoryDescriptor | None:
        """Return the :py:class:`InventoryDescriptor` for a known
        ``inventory_id``, or ``None`` for an unknown one.

        Part of the contract because the shared materialisation
        helper (``materialize_phoible_inventory``) reads the
        descriptor to compose the inventory's display name and
        provenance metadata; a provider without it would type-check
        against the picker flow and then crash at materialise time.
        """
        ...
