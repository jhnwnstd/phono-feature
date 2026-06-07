"""Contract tests for :py:class:`PhoibleProvider`.

Uses hand-built stub tables so the suite does not depend on the
build-baked snapshot (which CI machines without the PHOIBLE cache
wouldn't have access to before the bake step runs). The byte-
identical parity check against the real PHOIBLE table is done as
a smoke check in the bake script's output; this module pins the
runtime behaviour of the lookup + search logic itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.editor.inventory_providers import (
    InventoryDescriptor,
    InventoryProvider,
)
from phonology_shared.editor.phoible_provider import (
    PhoibleProvider,
    PhoibleSnapshotNotAvailable,
)

# Minimal-but-realistic stub. Two features (Syllabic, Consonantal),
# three languages with overlapping inventories so we exercise the
# multi-inventory-per-language code path.
_STUB_INDEX: dict[str, object] = {
    "version": "PHOIBLE 2.0",
    "citation": "Moran & McCloy 2019",
    "license": "CC BY-SA 3.0",
    "source_url": "https://github.com/phoible/dev",
    "languages": [
        {"name": "Korean", "glottocode": "kore1280", "iso": "kor"},
        {"name": "KOREAN", "glottocode": "kore1280", "iso": "kor"},
        {"name": "Japanese", "glottocode": "nucl1643", "iso": "jpn"},
    ],
    "inventories": [
        {
            "id": "1",
            "language_name": "Korean",
            "glottocode": "kore1280",
            "iso": "kor",
            "dialect": None,
            "source": "spa",
            "source_short": "SPA",
            "source_description": "Stanford Phonology Archive",
            "segment_count": 2,
        },
        {
            "id": "2",
            "language_name": "Korean",
            "glottocode": "kore1280",
            "iso": "kor",
            "dialect": "Seoul Korean",
            "source": "ph",
            "source_short": "PHOIBLE",
            "source_description": "Curated PHOIBLE inventory",
            "segment_count": 2,
        },
        {
            "id": "9",
            "language_name": "KOREAN",
            "glottocode": "kore1280",
            "iso": "kor",
            "dialect": None,
            "source": "ea",
            "source_short": "Eurasian Phonologies",
            "source_description": "",
            "segment_count": 2,
        },
        {
            "id": "3",
            "language_name": "Japanese",
            "glottocode": "nucl1643",
            "iso": "jpn",
            "dialect": None,
            "source": "upsid",
            "source_short": "UPSID",
            "source_description": (
                "UCLA Phonological Segment Inventory Database"
            ),
            "segment_count": 1,
        },
    ],
}

_STUB_DATA: dict[str, object] = {
    "version": "PHOIBLE 2.0",
    "feature_names": ["Syllabic", "Consonantal"],
    "inventories": {
        "1": {"p": "-+", "i": "+-"},
        "2": {"k": "-+", "u": "+-"},
        "9": {"b": "-+", "a": "+-"},
        "3": {"t": "-+"},
    },
}


def test_provider_satisfies_protocol() -> None:
    """``PhoibleProvider`` must duck-type as
    :py:class:`InventoryProvider`; the runtime_checkable Protocol
    makes this assertable without an inheritance declaration.

    Stronger than a literal-name smoke test: also confirms the
    provider ACTUALLY consumes the stub data by reading the
    search-languages output back. A provider that ignored
    ``index_table`` would pass the isinstance/name checks while
    silently returning empty searches."""
    provider = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    assert isinstance(provider, InventoryProvider)
    assert provider.name == "PHOIBLE"
    assert provider.version == "PHOIBLE 2.0"
    # The stub index ships a "Korean" language; if the provider had
    # ignored the index_table, search would return [].
    assert "Korean" in provider.search_languages("Korean")


def test_search_languages_substring_matches() -> None:
    """Case-insensitive substring match against language names."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    assert "Korean" in p.search_languages("kor")
    assert "Japanese" in p.search_languages("jap")
    assert "Japanese" in p.search_languages("JAP")
    assert p.search_languages("klingon") == []


def test_search_languages_dedups_case_variants() -> None:
    """PHOIBLE ships both ``"Korean"`` and ``"KOREAN"``; the
    autocomplete should surface only the mixed-case form so users
    aren't shown two entries for the same language. Regression
    against the original implementation that overwrote with
    whichever case came last in the index iteration."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    results = p.search_languages("kor", limit=20)
    # Exactly one Korean entry, and it's the mixed-case form.
    korean_hits = [r for r in results if r.casefold() == "korean"]
    assert korean_hits == ["Korean"]


def test_search_languages_empty_query_returns_empty() -> None:
    """Picker should never auto-populate on an empty query;
    returning [] keeps the dropdown closed until the user types."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    assert p.search_languages("") == []


def test_search_languages_respects_limit() -> None:
    """``limit`` is a hard cap so the picker never balloons."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    assert len(p.search_languages("a", limit=2)) <= 2


def test_list_inventories_merges_case_variants() -> None:
    """Different sources record the language name with different
    case (``"Korean"`` vs ``"KOREAN"``); ``list_inventories`` must
    surface BOTH groups' inventories under the canonical name so
    the user sees every available source in one click. The
    casefold-keyed dispatch in ``_by_language`` is what makes this
    work."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inventories = p.list_inventories("Korean")
    ids = {inv.id for inv in inventories}
    assert ids == {"1", "2", "9"}
    # Same dispatch on uppercase input — the picker's autocomplete
    # may surface either form depending on user input.
    assert {inv.id for inv in p.list_inventories("KOREAN")} == ids


def test_list_inventories_sorted_by_source_short() -> None:
    """Stable ordering across calls so the radio-button list does
    not jitter between user opens. Sort key is ``source_short``
    because that is the heading the picker shows first; alpha
    tiebreak by inventory id keeps two same-source entries
    deterministic."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inventories = p.list_inventories("Korean")
    shorts = [inv.source_short for inv in inventories]
    assert shorts == sorted(shorts)


def test_list_inventories_unknown_language_returns_empty() -> None:
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    assert p.list_inventories("Klingon") == []


def test_generate_returns_bundles_for_known_inventory() -> None:
    """The encoded bundle decodes via positional zip against
    ``feature_names``; the GeneratedInventory matches the shape
    other providers (PanPhon, Lookup) return so the dialog code
    is agnostic to which provider the user picked."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    result = p.generate("1")
    assert set(result.segments) == {"p", "i"}
    assert dict(result.segments["p"]) == {
        "Syllabic": "-",
        "Consonantal": "+",
    }
    assert dict(result.segments["i"]) == {
        "Syllabic": "+",
        "Consonantal": "-",
    }


def test_generate_prunes_unused_features() -> None:
    """Features where no segment carries ``+``/``-`` are dropped,
    same as PanPhon. Inventory 3 only has ``"t"`` (Consonantal+,
    Syllabic-); both features carry at least one ``+``/``-`` so
    both stay. Tested with a synthetic all-zero bundle below."""
    table = {
        **_STUB_DATA,
        "inventories": {
            "1": {"p": "00", "i": "00"},  # all zero → both pruned
        },
    }
    index = {
        **_STUB_INDEX,
        "inventories": [
            inv for inv in _STUB_INDEX["inventories"] if inv["id"] == "1"
        ],
    }
    p = PhoibleProvider(index_table=index, data_table=table)
    result = p.generate("1")
    assert result.features == ()
    assert dict(result.segments["p"]) == {}


def test_generate_unknown_inventory_id_raises_keyerror() -> None:
    """Unknown id → KeyError; the bridge layer translates that to
    a ValidationError the dialog shows to the user."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    with pytest.raises(KeyError, match="42"):
        p.generate("42")


def test_descriptor_lookup_by_id() -> None:
    """Used by the dialog for the preview before generate."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    descriptor = p.descriptor("2")
    assert descriptor is not None
    assert descriptor.language_name == "Korean"
    assert descriptor.dialect == "Seoul Korean"
    assert p.descriptor("999") is None


def test_descriptor_uses_strict_inventory_descriptor_type() -> None:
    """The Protocol pins ``InventoryDescriptor`` as the result
    type; tests against the dataclass shape so a future field
    rename trips here instead of at the picker."""
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inventories = p.list_inventories("Korean")
    assert all(isinstance(inv, InventoryDescriptor) for inv in inventories)


def test_load_data_payload_late_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web bridge boots with index only; data arrives later via
    ``load_data_payload``. Index-only mode supports search and
    list, but ``generate`` must raise until data lands.

    Mocks the on-disk fallback to ``None`` so the test pins the
    web cold-boot behaviour even when a developer has the bake
    artifact sitting in ``shared/.../editor/`` from a prior run.
    """
    monkeypatch.setattr(
        "phonology_shared.editor.phoible_provider._try_load_data_bytes",
        lambda: None,
    )
    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=None)
    assert not p.has_data
    # search and list still work
    assert "Korean" in p.search_languages("kor")
    assert len(p.list_inventories("Korean")) == 3
    # generate raises until payload arrives
    with pytest.raises(PhoibleSnapshotNotAvailable):
        p.generate("1")
    p.load_data_payload(json.dumps(_STUB_DATA))
    assert p.has_data
    assert "p" in p.generate("1").segments


def test_from_path_round_trip(tmp_path: Path) -> None:
    """Convenience constructor for tests that ship their own
    snapshot files; pin that it reads the schema produced by the
    bake script."""
    index_path = tmp_path / "index.json"
    data_path = tmp_path / "data.json"
    index_path.write_text(json.dumps(_STUB_INDEX), encoding="utf-8")
    data_path.write_text(json.dumps(_STUB_DATA), encoding="utf-8")
    p = PhoibleProvider.from_path(index_path, data_path)
    assert len(p.list_inventories("Korean")) == 3
    assert "p" in p.generate("1").segments


def test_constructor_rejects_non_mapping_index() -> None:
    """Schema enforcement at construction so a corrupt snapshot
    surfaces as a typed error the registry can catch and exclude
    the provider, not a stray crash mid-dialog."""
    with pytest.raises(TypeError, match="mapping"):
        PhoibleProvider(index_table=[1, 2, 3])  # type: ignore[arg-type]


def test_constructor_rejects_missing_inventories_list() -> None:
    with pytest.raises(ValueError, match="inventories"):
        PhoibleProvider(
            index_table={"version": "X", "languages": []},
        )


def test_phoible_snapshot_not_available_is_runtime_error() -> None:
    """The typed exception the registry catches must be a
    RuntimeError subclass so a generic exception-suppress also
    handles it gracefully."""
    assert issubclass(PhoibleSnapshotNotAvailable, RuntimeError)


# materialize_phoible_inventory: shared composition contract
#
# This is the single source of truth both the web bridge
# (load_phoible_inventory) and the desktop dialog
# (PhoibleDialog._on_load_clicked) consume; the tests pin the
# name template + metadata stamp so future bake schema changes
# either keep the contract or break here loudly.


def test_materialize_phoible_inventory_composes_name_with_source_short() -> (
    None
):
    """The inventory name follows ``"<language> [<source>]"`` so
    the toolbar reflects what the user loaded. Dialect-less inputs
    skip the parenthetical."""
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inv = materialize_phoible_inventory(p, "1")  # Korean SPA
    assert inv.name == "Korean [SPA]"


def test_materialize_phoible_inventory_includes_dialect_when_present() -> None:
    """When the descriptor records a dialect, the name gets a
    parenthetical so two inventories of the same language with
    different dialects do not collide in the toolbar dropdown."""
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inv = materialize_phoible_inventory(
        p, "2"
    )  # Korean PHOIBLE w/ Seoul dialect
    assert inv.name == "Korean (Seoul Korean) [PHOIBLE]"


def test_materialize_phoible_inventory_stamps_feature_source_metadata() -> (
    None
):
    """Provenance metadata is informational, not authoritative; the
    user can edit the field after load. Pinning the template here
    prevents silent drift between the web's saved-file format and
    the desktop's saved-file format."""
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    inv = materialize_phoible_inventory(p, "1")
    assert inv.metadata["feature_source"] == "PHOIBLE 2.0 / Korean / SPA"


def test_materialize_phoible_inventory_raises_keyerror_on_unknown_id() -> None:
    """The shared materializer surfaces unknown-id as ``KeyError``;
    each caller translates to its platform's error surface
    (``ValidationError`` on web, status-bar message on desktop)."""
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    p = PhoibleProvider(index_table=_STUB_INDEX, data_table=_STUB_DATA)
    with pytest.raises(KeyError, match="unknown PHOIBLE inventory id"):
        materialize_phoible_inventory(p, "does-not-exist")


def test_materialize_normalises_vowel_secondary_keys_to_engine_form() -> None:
    """The vowel_secondary metadata keys must use the SAME canonical
    form (NFC + IPA folding) the engine applies to inventory
    segments via ``Inventory.parse``. Without this, PHOIBLE's NFD-
    encoded nasal diphthongs (e.g. ``a + U+0303 + i``) silently
    miss the engine lookup in ``compute_placements`` (engine has
    ``U+00E3 + i``) and render as monophthongs.

    The stub mirrors the real-data shape: snapshot keys arrive as
    NFD; materialize must NFC-normalise them so every key in
    ``metadata['vowel_secondary']`` matches a key in
    ``inventory.segments``.
    """
    from phonology_shared.editor.phoible_provider import (
        materialize_phoible_inventory,
    )

    # Inventory id "v1": a tiny vowel system whose two diphthongs
    # arrive in NFD form (a + combining tilde, then a base char).
    nfd_index: dict[str, object] = {
        "version": "PHOIBLE 2.0",
        "languages": [{"name": "TestLang", "iso": "tst"}],
        "inventories": [
            {
                "id": "v1",
                "language_name": "TestLang",
                "iso": "tst",
                "source": "ph",
                "source_short": "PHOIBLE",
                "source_description": "",
                "segment_count": 3,
            }
        ],
    }
    nfd_data: dict[str, object] = {
        "version": "PHOIBLE 2.0",
        "feature_names": ["Syllabic", "Consonantal"],
        "inventories": {
            # NFD: 'a' + U+0303 = nasal a; 'i' is plain.
            "v1": {
                "a": "+-",
                "i": "+-",
                "ãi": "+-",  # /ãi/ in NFD
            },
        },
        "vowel_secondary": {
            "v1": {
                # Final state of the diphthong: nasal monophthong
                # values would arrive here in NFD too.
                "ãi": "+-",
            },
        },
    }
    p = PhoibleProvider(index_table=nfd_index, data_table=nfd_data)
    inv = materialize_phoible_inventory(p, "v1")
    vs = inv.metadata.get("vowel_secondary") or {}
    engine_segs = set(inv.segments)
    assert vs, "fixture invariant: stub injects one diphthong"
    assert set(vs).issubset(engine_segs), (
        f"vowel_secondary keys must be a subset of engine segments; "
        f"missing={set(vs) - engine_segs}"
    )
    # And explicitly: NFD input lands as NFC in both maps.
    assert "ãi" in inv.segments
    assert "ãi" in vs
