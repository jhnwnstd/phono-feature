"""Property-based contract for :py:class:`Inventory`.

Three invariants drive every test in this file:

  1. **Round-trip stability.** ``parse(to_json_dict(inv))`` produces
     an inventory equivalent to ``inv`` (same features, same
     segments, same per-feature values).
  2. **Closed feature set.** Every key in every validated bundle is a
     declared feature; every declared feature appears in the
     ``feature_index``.
  3. **Acceptance is symmetric with rejection.** A malformed input
     (e.g. an undeclared feature inside a bundle) raises
     :py:class:`ValidationError` and the error carries at least one
     :py:class:`ValidationIssue`.

Hypothesis is a dev dependency; ``pytest.importorskip`` keeps the
file safely skipped if a stripped venv lacks it.
"""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from phonology_shared.data.inventory import (  # noqa: E402
    Inventory,
    ValidationError,
)

#: Feature names are short, ascii, no whitespace, no delimiters.
#: This keeps the strategy inside the parser's accept range
#: without exercising every Unicode edge case (those have
#: dedicated example-based tests).
_FEATURE_NAMES = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll"), min_codepoint=ord("A")
    ),
    min_size=1,
    max_size=12,
)

#: Segment labels: short ASCII letters + a few IPA-safe Latin
#: extensions. Avoiding the IPA-confusable folding set keeps the
#: canonicalisation pass identity.
_SEG_LABELS = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll"),
        whitelist_characters="ɑəɔɛ",
        max_codepoint=0x02B0,
    ),
    min_size=1,
    max_size=4,
)

_FEATURE_VALUES = st.sampled_from(["+", "-", "0"])


@st.composite
def _well_formed_inventory(draw: st.DrawFn) -> dict[str, object]:
    """Build a JSON-shaped inventory dict that
    :py:meth:`Inventory.parse` should accept."""
    features = draw(
        st.lists(_FEATURE_NAMES, min_size=1, max_size=6, unique=True)
    )
    seg_labels = draw(
        st.lists(_SEG_LABELS, min_size=1, max_size=6, unique=True)
    )
    segments: dict[str, dict[str, str]] = {}
    for seg in seg_labels:
        # Each segment may omit some features; readers treat
        # omitted features as "0".
        per_seg_features = draw(
            st.lists(
                st.sampled_from(features),
                unique=True,
                max_size=len(features),
            )
        )
        segments[seg] = {f: draw(_FEATURE_VALUES) for f in per_seg_features}
    return {"features": features, "segments": segments}


@given(_well_formed_inventory())
@settings(max_examples=50, deadline=None)
def test_round_trip_through_to_json_dict(raw: dict[str, object]) -> None:
    """``parse -> to_json_dict -> parse`` is idempotent: the second
    parse produces the same feature tuple, same segment set, and
    the same per-feature value lookup as the first.
    """
    inv = Inventory.parse(raw)
    redo = Inventory.parse(inv.to_json_dict())
    assert redo.features == inv.features
    assert set(redo.segments) == set(inv.segments)
    for seg in inv.segments:
        for feat in inv.features:
            assert redo.feature_value(seg, feat) == inv.feature_value(
                seg, feat
            ), f"value drift at ({seg!r}, {feat!r})"


@given(_well_formed_inventory())
@settings(max_examples=50, deadline=None)
def test_bundle_keys_are_declared_features(
    raw: dict[str, object],
) -> None:
    """Every key in every validated bundle is a declared feature.
    This is the parse-don't-validate contract: downstream code can
    trust the bundle keys without re-checking."""
    inv = Inventory.parse(raw)
    declared = set(inv.features)
    for seg, bundle in inv.segments.items():
        for feat in bundle:
            assert (
                feat in declared
            ), f"undeclared feature {feat!r} survived in {seg!r}"


@given(_well_formed_inventory())
@settings(max_examples=50, deadline=None)
def test_feature_index_covers_features(
    raw: dict[str, object],
) -> None:
    inv = Inventory.parse(raw)
    assert set(inv.feature_index) == set(inv.features)
    for i, name in enumerate(inv.features):
        assert inv.feature_index[name] == i


@given(_well_formed_inventory())
@settings(max_examples=30, deadline=None)
def test_undeclared_bundle_feature_raises(
    raw: dict[str, object],
) -> None:
    """Injecting a bundle key that is NOT a declared feature (and
    NOT an alias of one) makes the parser reject with at least one
    :py:class:`ValidationIssue`.
    """
    features = list(raw["features"])  # type: ignore[arg-type]
    segments = dict(raw["segments"])  # type: ignore[arg-type]
    if not segments:
        return  # nothing to perturb
    # Pick the first segment, give it a feature that cannot
    # canonical-fold or alias-fold to any declared name.
    first_seg = next(iter(segments))
    intruder = "ZZZ_unlikely_to_exist_" + "x" * 4
    while intruder in features:
        intruder += "y"
    perturbed_bundle = dict(segments[first_seg])  # type: ignore[index]
    perturbed_bundle[intruder] = "+"
    perturbed_segments = dict(segments)
    perturbed_segments[first_seg] = perturbed_bundle
    raw_bad = {"features": features, "segments": perturbed_segments}
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(raw_bad)
    assert len(ex.value.validation_issues) >= 1
