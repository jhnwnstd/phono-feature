"""PHOIBLE 2.0-backed implementation of
:py:class:`InventoryProvider`.

Reads two JSON snapshots baked at build time by
:py:mod:`web.scripts.bake_phoible`:

* ``_phoible_index.generated.json``: language list + inventory
  descriptors. Always loaded eagerly (95 KB gzipped).
* ``_phoible_data.generated.json``: per-inventory segment
  bundles in positional encoding. Loaded eagerly on the desktop
  (disk read is free); the web bridge instead injects the bytes
  via :py:meth:`PhoibleProvider.load_data_payload` after a one-
  shot ``fetch`` so the cold Pyodide path is not penalised.

The provider is wire-stable: a stale developer checkout where
``web/scripts/bake_phoible.py`` has never run hits
:py:class:`PhoibleSnapshotNotAvailable` at construction; the
registry quietly drops it so the dialog falls back to the static
preset / PanPhon flows without crashing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from phonology_shared.data.inventory import (
    Inventory,
    canonicalize_segment_label,
)
from phonology_shared.editor.grid import enforce_class_caps
from phonology_shared.editor.inventory_providers import (
    InventoryDescriptor,
    InventoryProvider,
)
from phonology_shared.editor.providers import (
    GeneratedInventory,
    prune_unused_features,
    restrict_bundles,
)

_INDEX_FILENAME = "_phoible_index.generated.json"
_DATA_FILENAME = "_phoible_data.generated.json"

# Cap autocomplete result length so the picker stays responsive
# even when the user types a one-letter substring matching
# hundreds of languages. The dialog can request more by upping the
# ``limit`` parameter on :py:meth:`PhoibleProvider.search_languages`.
_DEFAULT_SEARCH_LIMIT = 20


class PhoibleSnapshotNotAvailable(RuntimeError):
    """Raised at construction when the bundled JSON snapshots are
    missing.

    Web users hit this when the lazy-loaded data file has not yet
    been ``fetch``-ed; desktop users hit it only on a stale
    checkout that has never run the bake script. The registry
    catches it and excludes the provider from the available list
    so the picker shows only static presets + PanPhon (if
    available).
    """


#: Number of IPA glyphs returned by the PHOIBLE preview payload
#: before the picker dialog asks the user to commit a load. Sized
#: so the picker's preview panel stays scannable; larger
#: inventories surface a "+N more" hint instead of the full list.
#: Single source so the web bridge slice and any future desktop
#: picker pagination read the same number.
PHOIBLE_PREVIEW_SEGMENT_LIMIT: int = 50


def _load_index_bytes() -> bytes:
    """Return the index JSON bytes from the package resources.

    Uses :py:func:`importlib.resources.files` so the lookup
    works across editable installs, zip-mounted bundles, and the
    Pyodide virtual filesystem mount.
    """
    pkg = resources.files("phonology_shared.editor")
    try:
        return (pkg / _INDEX_FILENAME).read_bytes()
    except OSError as exc:
        # OSError covers FileNotFoundError (the stale-checkout case)
        # plus PermissionError and the zipimport "member not found"
        # path inside the Pyodide bundle.
        raise PhoibleSnapshotNotAvailable(
            f"baked PHOIBLE index not found at {_INDEX_FILENAME}; "
            "run `python web/scripts/bake_phoible.py` to produce it"
        ) from exc


def _try_load_data_bytes() -> bytes | None:
    """Return the data JSON bytes from package resources if
    present, else ``None``.

    Desktop: data ships alongside the index, so this succeeds.
    Web: data ships as a separate ``web/dist/`` static asset and
    is mounted into the Pyodide FS later via
    :py:meth:`PhoibleProvider.load_data_payload`; this returns
    ``None`` on the cold path and the provider waits for the
    explicit load call.
    """
    pkg = resources.files("phonology_shared.editor")
    try:
        return (pkg / _DATA_FILENAME).read_bytes()
    except OSError:
        # OSError covers both the absent file and zipimport's
        # "member not found"; either way we return None so the
        # web bridge can lazy-load the data later.
        return None


class PhoibleProvider:
    """Search PHOIBLE 2.0 by language name and materialise a
    chosen inventory as a :py:class:`GeneratedInventory`.

    Implements :py:class:`InventoryProvider`. Eager-decoded at
    construction: the index is parsed once and indexed by
    language name so search and list_inventories are O(1) lookups
    against pre-built dicts. The 5 MB data file is also parsed
    once when available (~200 ms) and dict-cached.
    """

    name: str = "PHOIBLE"

    def __init__(
        self,
        *,
        index_table: Mapping[str, Any] | None = None,
        data_table: Mapping[str, Any] | None = None,
    ) -> None:
        """Construct from pre-loaded tables (testing override) or
        from the packaged snapshots.

        When ``data_table`` is ``None`` the provider operates in
        "index-only" mode: search and list_inventories work, but
        :py:meth:`generate` raises until
        :py:meth:`load_data_payload` provides the data JSON. This
        is the web bridge's expected boot state.
        """
        if index_table is None:
            index_table = json.loads(_load_index_bytes())
        if not isinstance(index_table, Mapping):
            raise TypeError(
                f"PHOIBLE index must be a mapping at top level; "
                f"got {type(index_table).__name__}"
            )

        self.version: str = str(index_table.get("version", "PHOIBLE 2.0"))
        self._citation: str = str(index_table.get("citation", ""))
        self._license: str = str(index_table.get("license", ""))
        self._source_url: str = str(index_table.get("source_url", ""))

        # Materialise the descriptor list and a language-name index
        # for O(1) lookups during the dialog flow. ``language_index``
        # carries case-folded keys so the autocomplete matches
        # behave consistently regardless of input case.
        raw_inventories = index_table.get("inventories")
        if raw_inventories is None:
            raise ValueError(
                "PHOIBLE index has no 'inventories' key; rerun "
                "bake_phoible to regenerate"
            )
        if not isinstance(raw_inventories, list):
            raise ValueError(
                "PHOIBLE index 'inventories' is "
                f"{type(raw_inventories).__name__!s}, expected list; "
                "rerun bake_phoible to regenerate"
            )
        self._inventories: dict[str, InventoryDescriptor] = {}
        self._by_language: dict[str, list[str]] = {}
        skipped_no_id = 0
        for entry in raw_inventories:
            if not isinstance(entry, Mapping):
                skipped_no_id += 1
                continue
            inv_id = str(entry.get("id", ""))
            if not inv_id:
                skipped_no_id += 1
                continue
            descriptor = InventoryDescriptor(
                id=inv_id,
                language_name=str(entry.get("language_name", "")),
                glottocode=entry.get("glottocode"),
                iso_code=entry.get("iso"),
                dialect=entry.get("dialect"),
                source_short=str(entry.get("source_short", "PHOIBLE")),
                source_description=str(entry.get("source_description", "")),
                segment_count=int(entry.get("segment_count", 0)),
                source_url=str(entry.get("source_page_url", "")),
            )
            self._inventories[inv_id] = descriptor
            self._by_language.setdefault(
                descriptor.language_name.casefold(), []
            ).append(inv_id)
        if skipped_no_id and not self._inventories:
            raise ValueError(
                f"PHOIBLE index has {skipped_no_id} entries but none "
                "have a usable 'id' field; rerun bake_phoible"
            )

        # Sorted language-name list for fast prefix/substring scan.
        # PHOIBLE ships some language names in multiple case forms
        # (e.g. ``"Korean"`` from PH + SPA + UPSID, ``"KOREAN"``
        # from the EA source); folder dedup keeps one canonical
        # form, preferring the variant that contains at least one
        # lowercase letter so the picker shows ``"Korean"`` not
        # ``"KOREAN"``. Both surface the SAME ``list_inventories``
        # result because the by-language index keys on casefolded
        # names already.
        raw_languages = index_table.get("languages") or []
        by_folded: dict[str, str] = {}
        for entry in raw_languages:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("name", ""))
            if not name:
                continue
            key = name.casefold()
            existing = by_folded.get(key)
            if existing is None or (existing.isupper() and not name.isupper()):
                by_folded[key] = name
        # ``(folded, display)`` pairs sorted by the folded key (the
        # display form's own casefold, so the order matches the old
        # display-sorted list). The folds were already computed for
        # the dedup map above; keeping them means every debounced
        # autocomplete keystroke scans precomputed folds instead of
        # re-casefolding all ~2,700 names per query.
        self._language_search_index: list[tuple[str, str]] = sorted(
            by_folded.items()
        )

        # Optional data payload. ``_segments_by_inventory`` is the
        # decoded form keyed by inventory id; ``_feature_names``
        # is the canonical column list used to decode positional
        # bundle strings. All three attributes are initialized here
        # so the index-only boot state (web bridge before the lazy
        # data fetch lands) is a fully-constructed object; the
        # invariant must not depend on a completed ingest.
        self._feature_names: tuple[str, ...] = ()
        self._segments_by_inventory: dict[str, Mapping[str, str]] = {}
        self._segment_secondary_by_inventory: dict[str, Mapping[str, str]] = {}
        if data_table is None:
            raw_data = _try_load_data_bytes()
            if raw_data is not None:
                data_table = json.loads(raw_data)
        if data_table is not None:
            self._ingest_data(data_table)

    @classmethod
    def from_path(
        cls,
        index_path: str | Path,
        data_path: str | Path | None = None,
    ) -> PhoibleProvider:
        """Construct from explicit file paths.

        Convenience entry point for tests that ship a hand-built
        snapshot; production callers use the no-arg constructor
        which reads the packaged JSON.
        """
        with Path(index_path).open("r", encoding="utf-8") as f:
            index = json.load(f)
        data: dict[str, Any] | None = None
        if data_path is not None:
            with Path(data_path).open("r", encoding="utf-8") as f:
                data = json.load(f)
        return cls(index_table=index, data_table=data)

    def load_data_payload(
        self, payload: str | bytes | Mapping[str, Any]
    ) -> None:
        """Ingest a previously-deferred data JSON payload.

        Used by the web bridge after the lazy ``fetch`` of
        ``phoible_data.<hash>.json`` lands. Idempotent: re-loading
        the same payload is cheap and overwrites the dict in place
        so a hot-swap of the data file (impossible in practice,
        but cheap to support) does not leave a stale cache.
        """
        if isinstance(payload, (str, bytes)):
            data = json.loads(payload)
        else:
            data = payload
        self._ingest_data(data)

    def _ingest_data(self, data: Mapping[str, Any]) -> None:
        feature_names = data.get("feature_names")
        if not isinstance(feature_names, list) or not all(
            isinstance(n, str) for n in feature_names
        ):
            raise ValueError(
                "PHOIBLE data table missing 'feature_names' "
                "list-of-strings; rerun bake_phoible to regenerate"
            )
        names = tuple(feature_names)
        n = len(names)

        raw_invs = data.get("inventories")
        if not isinstance(raw_invs, Mapping):
            raise ValueError(
                "PHOIBLE data table missing 'inventories' object; "
                "rerun bake_phoible to regenerate"
            )
        decoded: dict[str, Mapping[str, str]] = {}
        for inv_id, segments in raw_invs.items():
            if not isinstance(segments, Mapping):
                continue
            bundles: dict[str, str] = {}
            for sym, encoded in segments.items():
                if not isinstance(sym, str) or not isinstance(encoded, str):
                    continue
                if len(encoded) != n:
                    # Forward-compat: skip rather than raise so a
                    # snapshot with extra columns from a future
                    # bake doesn't crash a runtime that knows
                    # fewer columns.
                    continue
                bundles[sym] = encoded
            decoded[str(inv_id)] = bundles

        # Vowel diphthong secondary bundles. Sparse: most
        # inventories have none and stay absent from the map. The
        # field is optional in the bake schema for backward
        # compatibility with older snapshots that predate it.
        raw_secondary = data.get("segment_secondary") or {}
        secondary_decoded: dict[str, Mapping[str, str]] = {}
        if isinstance(raw_secondary, Mapping):
            for inv_id, segments in raw_secondary.items():
                if not isinstance(segments, Mapping):
                    continue
                bundles = {}
                for sym, encoded in segments.items():
                    if not isinstance(sym, str) or not isinstance(
                        encoded, str
                    ):
                        continue
                    if len(encoded) != n:
                        continue
                    bundles[sym] = encoded
                if bundles:
                    secondary_decoded[str(inv_id)] = bundles

        # Assign all three together only after validation and
        # decoding fully succeeded. Assigning piecemeal above would
        # let a failed ingest leave the provider half-loaded: new
        # feature names zipped against the old segment table
        # silently mis-assigns every value on the next generate(),
        # and ``has_data`` would gate open on a broken payload.
        self._feature_names = names
        self._segments_by_inventory = decoded
        self._segment_secondary_by_inventory = secondary_decoded

    # ------------------------------------------------------------------
    # InventoryProvider Protocol
    # ------------------------------------------------------------------

    def search_languages(
        self, query: str, limit: int = _DEFAULT_SEARCH_LIMIT
    ) -> list[str]:
        """Return language names matching ``query`` case-
        insensitively against the language name.

        Empty query returns an empty list; the dialog should not
        request results before the user has typed at least one
        character. The list is capped at ``limit``; if the cap is
        hit, the caller can detect "more matches available" by
        comparing ``len(result)`` to ``limit``.
        """
        if not query:
            return []
        needle = query.casefold()
        out: list[str] = []
        for folded, display in self._language_search_index:
            if needle in folded:
                out.append(display)
                if len(out) >= limit:
                    break
        return out

    def list_inventories(
        self, language_name: str
    ) -> list[InventoryDescriptor]:
        """Return every inventory descriptor for the named
        language, sorted by source label for stable rendering.

        Unknown language names return an empty list; the picker
        should treat that as "no inventories for this language".
        """
        ids = self._by_language.get(language_name.casefold(), [])
        descriptors = [self._inventories[i] for i in ids]
        descriptors.sort(key=lambda d: (d.source_short, d.id))
        return descriptors

    def generate(self, inventory_id: str) -> GeneratedInventory:
        """Materialise the named inventory into a
        :py:class:`GeneratedInventory`.

        Drops feature columns that no resolved segment specifies
        with ``"+"`` / ``"-"`` (mirrors PanPhon's behaviour: a
        small inventory should not carry every PHOIBLE column the
        bake step emits). The full feature set is retained when
        no segments resolve (e.g. an empty inventory descriptor)
        so the editor has columns to show.

        Raises :py:class:`KeyError` for an unknown
        ``inventory_id`` so the caller's bridge translator
        surfaces the failure as a ``ValidationError``.
        """
        if not self._feature_names:
            raise PhoibleSnapshotNotAvailable(
                "PHOIBLE data payload not loaded; web callers must "
                "call load_data_payload first, desktop callers "
                "should not see this branch"
            )
        if inventory_id not in self._inventories:
            raise KeyError(f"unknown PHOIBLE inventory id {inventory_id!r}")
        encoded_bundles = self._segments_by_inventory.get(inventory_id, {})

        features: tuple[str, ...] = self._feature_names
        resolved: dict[str, Mapping[str, str]] = {}
        for sym, encoded in encoded_bundles.items():
            # Pair feature_names positionally with the encoded
            # value vector. The bundle is shipped as a string of
            # one char per feature for compactness; decoding is a
            # single ``zip`` per segment.
            resolved[sym] = dict(zip(features, encoded, strict=False))

        # Pre-prune feature space so secondaries align with primaries
        # when the column-pruning step below drops sparse features.
        encoded_secondary = self._segment_secondary_by_inventory.get(
            inventory_id, {}
        )
        secondary: dict[str, Mapping[str, str]] = {
            sym: dict(zip(features, encoded, strict=False))
            for sym, encoded in encoded_secondary.items()
            if sym in resolved
        }

        if resolved:
            features = prune_unused_features(
                features, resolved, extra_bundles=secondary.values()
            )
            resolved = restrict_bundles(resolved, features)
            secondary = restrict_bundles(secondary, features)

        return GeneratedInventory(
            features=features,
            segments=resolved,
            unresolved=(),
            warnings=(),
            segment_secondary=secondary,
        )

    # ------------------------------------------------------------------
    # Convenience accessors used by the dialog + bridge layers
    # ------------------------------------------------------------------

    @property
    def citation(self) -> str:
        """The PHOIBLE 2.0 citation string from the index payload.

        Shown in the dialog's compact disclaimer chip so the user
        knows what they are looking at and how to cite it.
        """
        return self._citation

    @property
    def license(self) -> str:
        return self._license

    @property
    def source_url(self) -> str:
        return self._source_url

    @property
    def has_data(self) -> bool:
        """``True`` once the data payload is loaded.

        The dialog can use this to delay enabling the "Create
        Grid" button until the lazy fetch lands.
        """
        return bool(self._feature_names)

    def descriptor(self, inventory_id: str) -> InventoryDescriptor | None:
        """Look up an inventory descriptor by id, or ``None`` if
        unknown. Used by the picker preview without needing a full
        :py:meth:`list_inventories` call.
        """
        return self._inventories.get(inventory_id)


def materialize_phoible_inventory(
    provider: InventoryProvider, inventory_id: str
) -> Inventory:
    """Compose a fully-formed :py:class:`Inventory` from a PHOIBLE
    inventory id, ready to feed into a fresh
    :py:class:`~phonology_shared.theory.feature_engine.FeatureEngine`.

    Pure logic shared by both the web bridge's
    ``load_phoible_inventory`` endpoint and the desktop's PHOIBLE
    picker dialog so the two surfaces stay in lock-step: a future
    bake schema change, name-composition tweak, or metadata stamp
    flows through here once.

    Single-source-of-truth contract:

    * The inventory name follows the
      ``"<language> [(<dialect>)] [<source_short>]"`` template so
      the toolbar shows what the user just loaded.
    * ``feature_source`` metadata records the PHOIBLE provenance
      ("PHOIBLE 2.0 / Korean / SPA") so a saved file is debuggable;
      the field is plain text and the user can edit or delete it.
    * Contour secondary bundles (vowel diphthongs and obstruent
      affricates) get stamped under ``segment_secondary`` so the
      vowel chart can draw diphthong arrows and the engine can read
      affricate phases, without a new bridge endpoint or parameter.

    Raises :py:class:`KeyError` for an unknown ``inventory_id``;
    callers translate the failure into whatever the platform's
    error surface expects (``ValidationError`` on web,
    ``QMessageBox`` on desktop).
    """
    descriptor = provider.descriptor(inventory_id)
    if descriptor is None:
        raise KeyError(f"unknown PHOIBLE inventory id {inventory_id!r}")
    generated = provider.generate(inventory_id)

    name = descriptor.language_name
    if descriptor.dialect:
        name = f"{name} ({descriptor.dialect})"
    name = f"{name} [{descriptor.source_short}]"

    metadata: dict[str, Any] = {
        "feature_source": (
            f"{provider.version} / {descriptor.language_name}"
            f" / {descriptor.source_short}"
        ),
        # Plain-text informational stamps, like ``feature_source``:
        # the status-bar composer reads these so it can show the
        # language and source without re-parsing the display name
        # (which carries the full dialect parenthetical). Not a
        # database lock; the user can edit or delete them.
        "phoible_language": descriptor.language_name,
        "phoible_source": descriptor.source_short,
    }
    if descriptor.source_url:
        # phoible.org page documenting this inventory's source(s),
        # surfaced as a "Source" link beside the loaded-inventory
        # summary on both UIs. Plain-text informational stamp.
        metadata["phoible_source_url"] = descriptor.source_url
    if generated.segment_secondary:
        # Canonicalise BOTH the diphthong segment key AND the
        # feature bundle keys through the engine's normalisation
        # (NFC for the segment, ``normalize_feature_key`` for the
        # feature names). PHOIBLE ships ~26% of inventories with
        # NFD-form segments (nasal vowels like ``ã`` arrive as
        # ``a + U+0303``); the engine NFC-folds them at parse so
        # a raw-key copy here means ``segment_secondary['ãi']``
        # (NFD) misses ``inventory.segments['ãi']`` (NFC) on the
        # lookup inside ``compute_placements``. Result pre-fix:
        # nasal diphthongs silently lost their secondary
        # placement and rendered as monophthongs.
        #
        # The feature-key normalisation defends against the same
        # bug shape for FEATURE keys: if PHOIBLE ever shipped a
        # feature name in NFD (or PascalCase, or with a delimiter
        # variant), the lookup inside ``vowel_grid_pos`` would
        # quietly miss and the segment would place at the
        # default Open-mid-Central cell.
        from phonology_shared.data.inventory import normalize_feature_key

        metadata["segment_secondary"] = {
            canonicalize_segment_label(seg): {
                normalize_feature_key(k): v for k, v in bundle.items()
            }
            for seg, bundle in generated.segment_secondary.items()
        }

    inventory = Inventory.from_grid(
        name=name,
        features=list(generated.features),
        segments={seg: dict(b) for seg, b in generated.segments.items()},
        metadata=metadata,
    )
    # Defensive guard: every packaged PHOIBLE inventory is within the
    # per-class caps by construction (So is the densest vowel set at
    # exactly MAX_VOWELS; !Xoo the densest consonant set, under the
    # cap), so this never fires today. It stays so a future snapshot
    # refresh that introduces an over-class inventory fails loudly at
    # materialization rather than rendering a broken chart.
    enforce_class_caps(inventory.segments)
    return inventory


@lru_cache(maxsize=1)
def default_phoible_provider() -> PhoibleProvider:
    """Process-wide memoized provider built from the packaged
    snapshot.

    Construction parses the ~830 KB index plus the ~5 MB data
    snapshot and ingests ~3,000 inventories (roughly 100-200 ms on
    a fast machine, several times that under Pyodide), so callers
    on interactive paths must not construct per use: the desktop's
    PHOIBLE picker opens at toolbar-click time and used to re-pay
    the full parse on every open. The web bridge keeps its own
    memoized registry; this accessor gives the desktop the same
    provider lifetime so the two surfaces share one pattern.

    Raises :py:class:`PhoibleSnapshotNotAvailable` when the index
    is not packaged; the exception is not cached, so a retry after
    an install repair gets a fresh attempt.
    """
    return PhoibleProvider()


def phoible_loaded_message(inventory: Inventory) -> str:
    """Terse status-bar line for a just-loaded PHOIBLE inventory.

    The materialised display name carries the full dialect
    parenthetical (useful in the dropdown and on save), but a
    status line built from it reads as clutter:
    "Loaded Korean (Standard Korean (spoken in and around Seoul))
    [PHOIBLE] (48 segments, 37 features)." This composes the
    essentials only: language, source, and the counts. Shared so
    both status bars render the identical line.
    """
    language = str(
        inventory.metadata.get("phoible_language") or inventory.name
    )
    source = str(inventory.metadata.get("phoible_source") or "PHOIBLE")
    return (
        f"{language} [{source}]: "
        f"{len(inventory.segments)} segments × "
        f"{len(inventory.features)} features"
    )
