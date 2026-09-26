"""Hypothesis properties for the segment grouper.

Split out of :py:mod:`test_grouping_robustness` so a stripped venv
without ``hypothesis`` skips ONLY these properties. The module-scope
``importorskip`` below drops this whole file, which is the point: when
it lived at the bottom of the robustness module it dropped that
module's seven hand-built affricate and degradation tests too, and a
skip never fails a run, so the loss was silent.

The properties fuzz over REAL feature names (see
:py:data:`_CANONICAL_FEATURES`) so the grouper's actual manner and
place specs engage. A purely random alphabet would only ever exercise
the Contoid / Vocoid catch-all path and prove nothing about the specs.
"""

from __future__ import annotations

import pytest
from _grouping_asserts import MANNER_GROUPS, assert_covers

from phonology_shared.data.inventory import normalize_feature_bundle

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

#: A pool of real feature names so generated inventories actually reach
#: the manner/place specs (a purely random alphabet would only ever
#: exercise the catch-all path).
_CANONICAL_FEATURES = [
    "Consonantal",
    "Sonorant",
    "Syllabic",
    "Continuant",
    "DelRel",
    "Nasal",
    "Lateral",
    "Trill",
    "Tap",
    "Approximant",
    "Strident",
    "Coronal",
    "Voice",
    "Click",
    "Tone",
]
_VALUES = st.sampled_from(["+", "-", "0"])


@st.composite
def _random_inventory(draw: st.DrawFn) -> dict[str, dict[str, str]]:
    feats = draw(
        st.lists(
            st.sampled_from(_CANONICAL_FEATURES),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    count = draw(st.integers(min_value=1, max_value=10))
    return {f"s{i}": {f: draw(_VALUES) for f in feats} for i in range(count)}


@given(_random_inventory())
@settings(max_examples=200, deadline=None)
def test_grouping_always_partitions(inv: dict[str, dict[str, str]]) -> None:
    """No generated inventory makes a segment vanish, duplicate, or
    raise: the grouper always returns a clean partition."""
    assert_covers(inv)


@given(_random_inventory())
@settings(max_examples=200, deadline=None)
def test_vowel_phonemes_never_in_a_consonant_class(
    inv: dict[str, dict[str, str]],
) -> None:
    """A vowel-phoneme (``Syllabic=+``, not ``Consonantal=+``, not a
    click) is barred from every consonant manner class; it lands in
    Vowels or the Vocoid catch-all."""
    place = assert_covers(inv)
    for seg, bundle in inv.items():
        nb = normalize_feature_bundle(bundle)
        is_vowel_phoneme = (
            nb.get("syllabic") == "+"
            and nb.get("consonantal") != "+"
            and nb.get("click") != "+"
        )
        if is_vowel_phoneme:
            assert place[seg].isdisjoint(MANNER_GROUPS), (seg, place[seg])
