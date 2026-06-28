"""Per-class hard caps: the vowel / consonant counters, the
classifier-backed validator, the enforcement seam, and the live
editor counter helper.

Classification is feature-driven (``group_segments``), so a "vowel"
here means exactly what the chart renders as one; these tests pin
that the validator, the raising seam, and the counter all agree on
the count and on the cap boundaries.
"""

from __future__ import annotations

import pytest

from phonology_shared.chart.segment_classes import (
    count_segment_classes,
    validate_class_caps,
)
from phonology_shared.data.inventory import ValidationError
from phonology_shared.data.limits import MAX_CONSONANTS, MAX_VOWELS
from phonology_shared.editor.grid import enforce_class_caps
from phonology_shared.presentation.mode_logic import inventory_cap_status

_PLOSIVE = {
    "consonantal": "+",
    "continuant": "-",
    "sonorant": "-",
    "nasal": "-",
    "delrel": "-",
}


def _vowels(n: int) -> dict[str, dict[str, str]]:
    # Distinct strings; only ``syllabic: +`` matters for the Vowels
    # group membership the caps count against.
    return {f"v{i}": {"syllabic": "+"} for i in range(n)}


def _consonants(n: int) -> dict[str, dict[str, str]]:
    return {f"c{i}": dict(_PLOSIVE) for i in range(n)}


def _tones(n: int) -> dict[str, dict[str, str]]:
    # group_segments routes ``hightone: +`` segments to the disjoint
    # ``Tones`` class (Chao tone letters), neither vowel nor consonant.
    return {f"t{i}": {"hightone": "+"} for i in range(n)}


def test_validate_class_caps_passes_at_boundary():
    """Exactly at each cap is allowed; the validator uses a strict
    over-cap comparison so the densest real inventories (So at
    MAX_VOWELS, !Xóõ under MAX_CONSONANTS) load."""
    segments = {**_vowels(MAX_VOWELS), **_consonants(MAX_CONSONANTS)}
    assert validate_class_caps(segments) == []


def test_validate_class_caps_flags_too_many_vowels():
    messages = validate_class_caps(_vowels(MAX_VOWELS + 1))
    assert len(messages) == 1
    assert "vowels" in messages[0]
    assert str(MAX_VOWELS) in messages[0]


def test_validate_class_caps_flags_too_many_consonants():
    messages = validate_class_caps(_consonants(MAX_CONSONANTS + 1))
    assert len(messages) == 1
    assert "consonants" in messages[0]


def test_validate_class_caps_reports_both():
    segments = {
        **_vowels(MAX_VOWELS + 1),
        **_consonants(MAX_CONSONANTS + 1),
    }
    messages = validate_class_caps(segments)
    assert len(messages) == 2


def test_enforce_class_caps_raises_validation_error():
    with pytest.raises(ValidationError) as excinfo:
        enforce_class_caps(_vowels(MAX_VOWELS + 1))
    assert "vowels" in excinfo.value.issues[0]


def test_enforce_class_caps_silent_when_within_caps():
    # Should not raise.
    enforce_class_caps({**_vowels(3), **_consonants(5)})


def test_cap_status_text_and_counts():
    status = inventory_cap_status({**_vowels(2), **_consonants(3)})
    assert status.n_vowels == 2
    assert status.n_consonants == 3
    assert status.n_total == 5
    assert status.severity == "ok"
    assert f"/{MAX_VOWELS}" in status.text
    assert f"/{MAX_CONSONANTS}" in status.text


def test_cap_status_warns_near_cap():
    """At 90% of a cap the counter escalates to warn before any add
    is refused."""
    near = int(MAX_VOWELS * 0.9) + 1
    status = inventory_cap_status(_vowels(near))
    assert status.severity == "warn"


def test_cap_status_errors_at_cap():
    status = inventory_cap_status(_vowels(MAX_VOWELS))
    assert status.severity == "error"


def test_cap_status_consonant_count_excludes_vowels_and_tones():
    """Consonants are every segment that is neither a vowel nor a
    tone letter. Tones count toward the total but not the consonant
    cap, so the three figures need not sum."""
    status = inventory_cap_status(
        {**_vowels(4), **_consonants(7), **_tones(3)}
    )
    assert status.n_vowels == 4
    assert status.n_consonants == 7
    assert status.n_total == 14


def test_tone_letters_are_not_counted_as_consonants():
    """Regression: tone letters must NOT inflate the consonant count.
    group_segments puts them in a disjoint ``Tones`` class; folding
    them into ``n_total - n_vowels`` (the pre-fix formula) counted
    them as consonants and could falsely reject an inventory whose
    real consonant count is under the cap."""
    nv, nc, nt = count_segment_classes({**_consonants(130), **_tones(8)})
    assert nv == 0
    assert nc == 130  # NOT 138
    assert nt == 138  # tones still count toward the total


def test_class_caps_admit_max_consonants_plus_tones():
    """130 real consonants + a rich tone tier stays admissible: the
    pre-fix formula reported 138 consonants and falsely tripped
    MAX_CONSONANTS=135. With tones excluded it passes."""
    segments = {**_consonants(MAX_CONSONANTS - 5), **_tones(8)}
    assert validate_class_caps(segments) == []


def test_counter_and_validator_share_one_count():
    """The live counter and the save-time validator must agree on
    the class split for the same inventory (both route through
    count_segment_classes)."""
    segments = {**_vowels(12), **_consonants(40), **_tones(2)}
    nv, nc, nt = count_segment_classes(segments)
    status = inventory_cap_status(segments)
    assert (status.n_vowels, status.n_consonants, status.n_total) == (
        nv,
        nc,
        nt,
    )
