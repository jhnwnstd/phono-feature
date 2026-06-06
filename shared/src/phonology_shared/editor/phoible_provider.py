"""PHOIBLE 2.0-backed implementation of
:py:class:`InventoryProvider`.

Reads two JSON snapshots baked at build time by
:py:mod:`web.scripts.bake_phoible`:

* ``_phoible_index.generated.json`` — language list + inventory
  descriptors. Always loaded eagerly (95 KB gzipped).
* ``_phoible_data.generated.json`` — per-inventory segment
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
from importlib import resources
from pathlib import Path
from typing import Any

from phonology_shared.editor.inventory_providers import InventoryDescriptor
from phonology_shared.editor.providers import GeneratedInventory

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
        if not isinstance(raw_inventories, list):
            raise ValueError(
                "PHOIBLE index missing 'inventories' list; rerun "
                "bake_phoible to regenerate"
            )
        self._inventories: dict[str, InventoryDescriptor] = {}
        # Map language name (case-folded) -> list of inventory ids.
        self._by_language: dict[str, list[str]] = {}
        # Map ISO 639-3 code (case-folded) -> language name; the
        # autocomplete uses this so a user typing "kor" matches
        # "Korean" without needing the prefix-aware search to know
        # about ISO codes specifically.
        self._iso_to_language: dict[str, str] = {}
        for entry in raw_inventories:
            if not isinstance(entry, Mapping):
                continue
            inv_id = str(entry.get("id", ""))
            if not inv_id:
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
            )
            self._inventories[inv_id] = descriptor
            self._by_language.setdefault(
                descriptor.language_name.casefold(), []
            ).append(inv_id)
            if descriptor.iso_code:
                iso_key = descriptor.iso_code.casefold()
                existing_iso = self._iso_to_language.get(iso_key)
                # Same case-prefer rule the language-name dedup uses
                # below: keep the variant that has at least one
                # lowercase letter so the ISO hit surfaces
                # ``"Korean"`` instead of ``"KOREAN"``.
                if existing_iso is None or (
                    existing_iso.isupper()
                    and not descriptor.language_name.isupper()
                ):
                    self._iso_to_language[iso_key] = descriptor.language_name

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
        self._language_names: list[str] = sorted(
            by_folded.values(), key=lambda s: s.casefold()
        )

        # Optional data payload. ``_segments_by_inventory`` is the
        # decoded form keyed by inventory id; ``_feature_names``
        # is the canonical column list used to decode positional
        # bundle strings.
        self._feature_names: tuple[str, ...] = ()
        self._segments_by_inventory: dict[str, Mapping[str, str]] = {}
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
        self._feature_names = tuple(feature_names)
        n = len(self._feature_names)

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
        self._segments_by_inventory = decoded

        # Vowel diphthong secondary bundles. Sparse: most
        # inventories have none and stay absent from the map. The
        # field is optional in the bake schema for backward
        # compatibility with older snapshots that predate it.
        raw_secondary = data.get("vowel_secondary") or {}
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
        self._vowel_secondary_by_inventory = secondary_decoded

    # ------------------------------------------------------------------
    # InventoryProvider Protocol
    # ------------------------------------------------------------------

    def search_languages(
        self, query: str, limit: int = _DEFAULT_SEARCH_LIMIT
    ) -> list[str]:
        """Return language names matching ``query`` case-
        insensitively against the language name or ISO code.

        Empty query returns an empty list; the dialog should not
        request results before the user has typed at least one
        character. The list is capped at ``limit``; if the cap is
        hit, the caller can detect "more matches available" by
        comparing ``len(result)`` to ``limit``.
        """
        if not query:
            return []
        needle = query.casefold()
        # ISO-code shortcut: a 3-character query that matches an
        # ISO code directly bubbles the language name to the top.
        out: list[str] = []
        seen: set[str] = set()
        iso_hit = self._iso_to_language.get(needle)
        if iso_hit is not None:
            out.append(iso_hit)
            seen.add(iso_hit)
        for name in self._language_names:
            if name in seen:
                continue
            if needle in name.casefold():
                out.append(name)
                seen.add(name)
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

        # Decode the diphthong secondary bundles for this
        # inventory, if any, in the same pre-prune feature space.
        encoded_secondary = self._vowel_secondary_by_inventory.get(
            inventory_id, {}
        )
        secondary: dict[str, Mapping[str, str]] = {
            sym: dict(zip(features, encoded, strict=False))
            for sym, encoded in encoded_secondary.items()
            if sym in resolved
        }

        if resolved:
            used = {
                feat
                for bundle in resolved.values()
                for feat, value in bundle.items()
                if value in ("+", "-")
            }
            # Secondary bundles count as "used" too; otherwise a
            # diphthong that distinguishes itself only on the final
            # half (e.g. /aɪ/ where the initial vowel matches an
            # existing monophthong) would lose its discriminator.
            for bundle in secondary.values():
                for feat, value in bundle.items():
                    if value in ("+", "-"):
                        used.add(feat)
            features = tuple(feat for feat in features if feat in used)
            resolved = {
                seg: {
                    feat: val for feat, val in bundle.items() if feat in used
                }
                for seg, bundle in resolved.items()
            }
            secondary = {
                seg: {
                    feat: val for feat, val in bundle.items() if feat in used
                }
                for seg, bundle in secondary.items()
            }

        return GeneratedInventory(
            features=features,
            segments=resolved,
            unresolved=(),
            warnings=(),
            vowel_secondary=secondary,
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
