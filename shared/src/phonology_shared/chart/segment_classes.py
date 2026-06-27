"""Segment-class counting and per-class cap policy.

This is application POLICY, not grouping: it counts how many vowels,
consonants, and tone letters an inventory has and checks those
counts against the hard caps in
:py:mod:`phonology_shared.data.limits`. It lives apart from
:py:mod:`phonology_shared.chart.consonants` (which owns the
grouping algorithm) so that module stays purely about WHERE each
segment is displayed, while "how many of each class is allowed"
lives here.

It sits ABOVE grouping (it calls
:py:func:`~phonology_shared.chart.consonants.group_segments`) and
ABOVE the data layer (it reads the caps), which is also why it
cannot live in the data layer: ``data`` must not import ``chart``.

NATURAL CONSTRAINT: the three classes are DISJOINT. A vowel is
exactly what ``group_segments`` puts in the ``Vowels`` group; a
tone letter is exactly the ``Tones`` group; a consonant is
everything else. Tone letters count toward the total but never
toward the consonant cap, so the three figures need not sum to a
caller's expectation built on vowels + consonants alone.
"""

from __future__ import annotations

from collections.abc import Mapping

from phonology_shared.chart.consonants import (
    TONES_GROUP_NAME,
    VOWEL_GROUP_NAME,
    group_segments,
)
from phonology_shared.data.limits import MAX_CONSONANTS, MAX_VOWELS


def count_segment_classes(
    inventory: Mapping[str, Mapping[str, str]],
    *,
    normalized: Mapping[str, dict[str, str]] | None = None,
) -> tuple[int, int, int]:
    """Return ``(n_vowels, n_consonants, n_total)`` for ``inventory``.

    The single source of the class counts both the hard-cap
    validator and the live builder counter consume, so the two can
    never disagree about which side a segment falls on. Counting
    goes through :py:func:`group_segments` so each class means
    exactly what the charts render.

    ``n_consonants`` is every segment that is neither a vowel NOR a
    suprasegmental tone letter: the ``Tones`` group (Chao tone
    letters, e.g. PHOIBLE !Xoo) is a disjoint THIRD class, not a
    consonant, so folding it into the consonant count would inflate
    it against :py:data:`~phonology_shared.data.limits.MAX_CONSONANTS`.
    ``n_total`` counts every segment, tones included, since they
    occupy the inventory and the chart's tone tier and so count
    toward :py:data:`~phonology_shared.data.limits.MAX_SEGMENTS`.

    ``normalized`` optionally carries pre-normalized bundles, same
    contract as :py:func:`group_segments`.
    """
    groups = group_segments(inventory, normalized=normalized)
    n_total = sum(len(segs) for segs in groups.values())
    n_vowels = len(groups.get(VOWEL_GROUP_NAME, []))
    n_tones = len(groups.get(TONES_GROUP_NAME, []))
    n_consonants = n_total - n_vowels - n_tones
    return n_vowels, n_consonants, n_total


def validate_class_caps(
    inventory: Mapping[str, Mapping[str, str]],
    *,
    normalized: Mapping[str, dict[str, str]] | None = None,
) -> list[str]:
    """Check the per-class hard caps (``MAX_VOWELS`` /
    ``MAX_CONSONANTS`` from :py:mod:`phonology_shared.data.limits`).

    Returns user-facing messages, one per violated cap; empty means
    the inventory is within bounds. Class counts come from
    :py:func:`count_segment_classes` (vowels and consonants per the
    chart's own grouping, tone letters excluded from both), so the
    save-time gate and the live counter share one definition. A
    simpler ``syllabic == '+'`` predicate would drift from the
    grouping the charts actually render.

    Callers raise
    :py:class:`phonology_shared.data.inventory.ValidationError` with
    the returned messages wherever a grid becomes an
    :py:class:`~phonology_shared.data.inventory.Inventory` (builder
    save, new-inventory create, PHOIBLE materialization) and after
    every JSON load. The caps are sized so all PHOIBLE inventories
    pass (So has exactly ``MAX_VOWELS`` vowels; !Xoo has 130
    consonants, under the 135 cap, plus 3 tone letters); the display
    surfaces are stress-verified at these counts.

    ``normalized`` optionally carries pre-normalized bundles, same
    contract as :py:func:`group_segments`.
    """
    n_vowels, n_consonants, _ = count_segment_classes(
        inventory, normalized=normalized
    )
    messages: list[str] = []
    if n_vowels > MAX_VOWELS:
        messages.append(
            f"inventory has {n_vowels} vowels; " f"hard cap is {MAX_VOWELS}"
        )
    if n_consonants > MAX_CONSONANTS:
        messages.append(
            f"inventory has {n_consonants} consonants; "
            f"hard cap is {MAX_CONSONANTS}"
        )
    return messages
