"""Shared grouping-contract assertions for the grouper test modules.

Lives in its own importable module (not conftest.py) for the same
reason as :py:mod:`_inventory_names`: pytest's conftest.py is not a
regular Python module, so importing helpers from it across files
fails. Promoting them here lets both
:py:mod:`test_grouping_robustness` (hand-built fixtures) and
:py:mod:`test_grouping_properties` (Hypothesis-generated ones) assert
the SAME cover contract, so the two cannot drift on what "the grouper
placed every segment" means.
"""

from __future__ import annotations

from phonology_shared.chart.consonants import (
    CONTOID_GROUP_NAME,
    DISPLAY_ORDER,
    TONES_GROUP_NAME,
    VOCOID_GROUP_NAME,
    VOWEL_GROUP_NAME,
    group_segments,
)

#: The catch-alls plus the non-consonant homes. Everything else in
#: ``DISPLAY_ORDER`` is a consonant manner class, derived here so the
#: set stays in sync if the display order gains a class.
NON_MANNER = frozenset(
    {
        VOWEL_GROUP_NAME,
        TONES_GROUP_NAME,
        CONTOID_GROUP_NAME,
        VOCOID_GROUP_NAME,
    }
)
MANNER_GROUPS = frozenset(g for g in DISPLAY_ORDER if g not in NON_MANNER)

AFFRICATE_LABELS = frozenset(
    {
        "Affricates",
        "Sibilant Affricates",
        "Lateral Affricates",
        "Ejective Affricates",
    }
)


def flat(groups: dict[str, list[str]]) -> list[str]:
    return [seg for segs in groups.values() for seg in segs]


def membership(groups: dict[str, list[str]]) -> dict[str, set[str]]:
    """Each segment -> the SET of groups it renders in. group_segments is
    a MULTISET: a segment reaching several manner classes appears in each,
    so membership is a set, not a single label."""
    out: dict[str, set[str]] = {}
    for name, segs in groups.items():
        for seg in segs:
            out.setdefault(seg, set()).add(name)
    return out


def assert_covers(inv: dict[str, dict[str, str]]) -> dict[str, set[str]]:
    """Grouping must COVER every segment (place each in >= 1 group, none
    invented, none listed twice in one group) and may place a
    multi-membership segment in several groups. Returns the seg -> set of
    groups membership for further per-segment assertions."""
    groups = group_segments(inv)
    flattened = flat(groups)
    assert set(flattened) == set(inv), "grouping dropped or invented a segment"
    for name, segs in groups.items():
        assert len(segs) == len(set(segs)), f"{name} lists a segment twice"
    return membership(groups)
