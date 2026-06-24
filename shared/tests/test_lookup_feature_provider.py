"""Contract tests for :py:class:`LookupFeatureProvider`.

Uses a hand-built stub table so the tests do not depend on the
build-baked snapshot (which CI machines without panphon installed
would not be able to produce). The byte-identical-with-live parity
check against the real panphon table is done as a desktop sanity
check via :py:mod:`web.scripts.bake_panphon` output; this module
pins the runtime behaviour of the lookup logic itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.editor.lookup_provider import (
    LookupFeatureProvider,
    LookupTableNotAvailable,
)
from phonology_shared.editor.providers import FeatureProvider

# Minimal-but-realistic stub. Two features (so feature-pruning is
# observable), three segments where one is "all zero" (would be
# pruned if it were the only resolved segment).
_STUB_TABLE: dict[str, object] = {
    "provider_name": "PanPhon",
    "provider_version": "stub-1.0",
    "feature_names": ["Syllabic", "Consonantal"],
    "segments": {
        "p": "-+",
        "i": "+-",
        # ``0`` for both features; emulates a segment whose
        # PanPhon row is all-unspecified for the columns we keep.
        "?": "00",
    },
}


def test_provider_satisfies_protocol() -> None:
    """The lookup provider duck-types as a FeatureProvider; the
    Protocol's runtime_checkable wrapper makes this assertable
    without a class-level inheritance declaration."""
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    assert isinstance(provider, FeatureProvider)
    assert provider.name == "PanPhon"
    assert provider.version == "stub-1.0"
    assert provider.display_label() == "PanPhon"
    assert provider.feature_names() == ("Syllabic", "Consonantal")


def test_generate_returns_bundles_for_known_segments() -> None:
    """Every known segment lands in ``segments``; the bundle decodes
    via positional zip against ``feature_names``."""
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    result = provider.generate(["p", "i"])
    assert set(result.segments) == {"p", "i"}
    assert dict(result.segments["p"]) == {
        "Syllabic": "-",
        "Consonantal": "+",
    }
    assert dict(result.segments["i"]) == {
        "Syllabic": "+",
        "Consonantal": "-",
    }
    assert result.unresolved == ()
    assert result.warnings == ()


def test_generate_marks_unknown_segments_unresolved() -> None:
    """Symbols not in the table land in ``unresolved`` with a
    human-readable warning; nothing throws."""
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    result = provider.generate(["p", "🤷"])
    assert "p" in result.segments
    assert result.unresolved == ("🤷",)
    assert len(result.warnings) == 1
    assert "🤷" in result.warnings[0]
    assert "not in the PanPhon table" in result.warnings[0]


def test_generate_prunes_features_no_segment_specifies() -> None:
    """Features that no resolved segment carries ``+``/``-`` for
    are dropped from both ``features`` and every bundle. Mirrors
    the desktop provider's behaviour so a small selection does not
    pull in every column.

    The stub has two features and only one segment (``"p"``)
    resolved; ``"p"`` is ``"-+"`` so both features are kept. To
    exercise pruning, resolve only the all-zero ``"?"``: the
    feature set should collapse to nothing.
    """
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    result = provider.generate(["?"])
    # ``"?"`` resolves but is all-zero so both columns get pruned.
    assert result.features == ()
    assert dict(result.segments["?"]) == {}


def test_generate_keeps_full_feature_set_when_nothing_resolves() -> None:
    """When no segment resolves the feature-pruning branch does
    not run; the dialog needs columns to display so the user can
    edit values manually for the unresolved cases."""
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    result = provider.generate(["unknownX"])
    assert result.features == ("Syllabic", "Consonantal")
    assert result.unresolved == ("unknownX",)
    assert result.segments == {}


def test_generate_empty_input_returns_full_feature_set() -> None:
    """Empty input is a UI preview case: no segments to resolve so
    the provider returns its full feature set as a hint of what
    columns the user will get."""
    provider = LookupFeatureProvider(table=_STUB_TABLE)
    result = provider.generate([])
    assert result.features == ("Syllabic", "Consonantal")
    assert result.segments == {}
    assert result.unresolved == ()


def test_from_path_round_trip(tmp_path: Path) -> None:
    """``from_path`` is the convenience entry point tests use to
    load arbitrary table snapshots; pin that it reads the same
    schema the in-memory constructor accepts."""
    table_file = tmp_path / "stub.json"
    table_file.write_text(json.dumps(_STUB_TABLE), encoding="utf-8")
    provider = LookupFeatureProvider.from_path(table_file)
    assert provider.feature_names() == ("Syllabic", "Consonantal")
    result = provider.generate(["p"])
    assert dict(result.segments["p"]) == {
        "Syllabic": "-",
        "Consonantal": "+",
    }


def test_constructor_rejects_non_mapping() -> None:
    """A corrupt snapshot (list at top level, integer, etc.) gets a
    typed error at construction so the registry can route to a
    fallback instead of crashing the dialog at first preview."""
    with pytest.raises(TypeError, match="must be a mapping"):
        LookupFeatureProvider(table=[1, 2, 3])  # type: ignore[arg-type]


def test_constructor_rejects_missing_feature_names() -> None:
    """Schema enforcement: a snapshot without ``feature_names``
    raises a specific message pointing the developer at the bake
    script."""
    with pytest.raises(ValueError, match="feature_names"):
        LookupFeatureProvider(
            table={"provider_name": "X", "segments": {}},
        )


def test_constructor_rejects_missing_segments() -> None:
    """Same as above for the ``segments`` slot."""
    with pytest.raises(ValueError, match="segments"):
        LookupFeatureProvider(
            table={
                "provider_name": "X",
                "feature_names": ["A"],
            },
        )


def test_constructor_skips_segments_with_wrong_length() -> None:
    """A forward-compat snapshot with extra columns must not crash
    older runtimes: segments whose encoded length disagrees with
    ``feature_names`` are silently skipped and surface to the user
    via the unresolved counter on the next lookup."""
    table = {
        "provider_name": "PanPhon",
        "provider_version": "1.0",
        "feature_names": ["A", "B"],
        # IPA-valid keys: the lookup normalises input to PanPhon form
        # (to_panphon_form), so non-IPA placeholders like "good" would
        # fold (g -> ɡ) and miss. "p"/"t" map to themselves.
        "segments": {
            "p": "+-",
            # 3 chars vs 2 declared: skipped at __init__, becomes
            # unresolved at generate-time.
            "t": "+-?",
        },
    }
    provider = LookupFeatureProvider(table=table)
    result = provider.generate(["p", "t"])
    assert "p" in result.segments
    assert "t" in result.unresolved


def test_load_failure_path() -> None:
    """``LookupTableNotAvailable`` is the typed signal the registry
    catches when the snapshot is missing. Smoke-test that the
    exception class exists in the public surface and is a
    RuntimeError so generic catchers also see it."""
    assert issubclass(LookupTableNotAvailable, RuntimeError)
