"""Pure-Python layout helpers shared by the desktop GUI and the
web app.

Nothing in this module imports Qt or anything browser-specific. The
desktop reads it directly; the web app picks it up via the build
script's renderer relay (web/scripts/build.py copies this file into
the Pyodide bundle, where api.py exposes it through the JS bridge).

That way: one definition of which group goes in which column. Edits
to the pin constants or the LPT algorithm propagate to both UIs on
next launch / next web build.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# Pins are conventional in IPA chart layouts: place-of-articulation
# features (Major Class, Place) sit on the left, manner-of-
# articulation (Manner) on the right. Everything else goes wherever
# the LPT step puts it.
LEFT_PINS: tuple[str, ...] = ("Major Class", "Place")
RIGHT_PINS: tuple[str, ...] = ("Manner",)

# Per-card overhead (header + padding) expressed in row-equivalents.
# Added to each card's row count when balancing column heights so
# many-small-cards columns aren't under-counted vs few-big-cards.
CARD_OVERHEAD: int = 1


def distribute_feature_groups(
    group_sizes: Mapping[str, int],
    *,
    group_order: Sequence[str] | None = None,
    left_pins: Sequence[str] = LEFT_PINS,
    right_pins: Sequence[str] = RIGHT_PINS,
    card_overhead: int = CARD_OVERHEAD,
) -> tuple[list[str], list[str]]:
    """Assign feature-group names to two columns.

    ``group_sizes`` maps each group name to its row count (i.e. the
    number of active features in the group). Groups with size 0 are
    dropped from the output -- empty cards shouldn't render.

    Returns ``(left_names, right_names)``: each is a list of group
    names in the order they should be stacked vertically in that
    column.

    Algorithm:
      1. Pin LEFT_PINS / RIGHT_PINS to their columns first.
      2. Sort the remaining groups by cost descending.
      3. LPT-greedy: add each remaining group to whichever column is
         currently shorter.

    ``group_order`` only matters for tie-breaking among unpinned
    groups of equal cost; pass the canonical FEATURE_GROUPS order
    when you care about determinism. Defaults to the iteration order
    of ``group_sizes`` (insertion order in modern Python dicts).
    """

    def cost(name: str) -> int:
        n = group_sizes.get(name, 0)
        return n + card_overhead if n > 0 else 0

    left: list[str] = []
    right: list[str] = []
    left_height = 0
    right_height = 0

    pinned: set[str] = set(left_pins) | set(right_pins)

    for name in left_pins:
        c = cost(name)
        if c > 0:
            left.append(name)
            left_height += c
    for name in right_pins:
        c = cost(name)
        if c > 0:
            right.append(name)
            right_height += c

    iteration_order = list(group_order) if group_order else list(group_sizes)
    unpinned_with_cost: list[tuple[str, int]] = []
    for name in iteration_order:
        if name in pinned:
            continue
        c = cost(name)
        if c > 0:
            unpinned_with_cost.append((name, c))
    # Sort by cost descending; ties broken by iteration order, which
    # is what ``key`` on a stable sort preserves implicitly.
    unpinned_with_cost.sort(key=lambda pair: -pair[1])

    for name, c in unpinned_with_cost:
        if left_height <= right_height:
            left.append(name)
            left_height += c
        else:
            right.append(name)
            right_height += c
    return left, right
