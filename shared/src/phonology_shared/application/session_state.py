# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
"""The session state both frontends share.

:class:`SessionState` owns the active inventory and engine, the analysis
mode and match mode, the current selection (segments + feature query),
the hidden segment classes, and the classified source link. The desktop
and web clients render this state and call its transition methods rather
than each tracking the same fields on a MainWindow / module globals.

Deliberately pure: it imports only shared domain types (no Qt, no DOM),
so the transitions are unit-testable and the two clients cannot drift on
what a load, a selection toggle, or a clear means. Rendering and
serialisation stay in the frontends; this layer never touches a widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.mode_logic import Mode
from phonology_shared.presentation.source_link import (
    NONE_SOURCE,
    SourceLink,
    classify_source,
)
from phonology_shared.theory.feature_engine import FeatureEngine, MatchMode

# Cleared-cell sentinels for a feature query. ``"0"`` is the unspecified
# value the grid/query uses; an empty string is the deselected button.
_CLEARED_FEATURE_VALUES = ("", "0")


@dataclass
class SessionState:
    """Orchestration state for one analysis session.

    Starts empty (no inventory loaded). Frontends construct one of these
    per window/tab and drive it through the methods below.
    """

    inventory: Inventory | None = None
    engine: FeatureEngine | None = None
    mode: Mode = Mode.SEG_TO_FEAT
    match_mode: MatchMode = MatchMode.STRICT
    selected_segments: list[str] = field(default_factory=list)
    selected_features: dict[str, str] = field(default_factory=dict)
    hidden_segment_classes: set[str] = field(default_factory=set)
    source: SourceLink = NONE_SOURCE

    def load_inventory(self, inventory: Inventory) -> None:
        """Adopt a freshly loaded or swapped inventory.

        Rebuilds the engine (its grouping/normalisation caches are
        per-engine, so a new engine starts fresh), reclassifies the
        source from ``metadata.source``, and resets the per-inventory
        display state: a prior inventory's selection and hidden classes
        never carry across a swap.
        """
        self.inventory = inventory
        self.engine = FeatureEngine(inventory)
        self.source = classify_source(inventory.metadata.get("source"))
        self.reset_selection()
        self.hidden_segment_classes.clear()

    def set_mode(self, mode: Mode) -> bool:
        """Switch the analysis mode. Returns whether it changed, so a
        caller can skip a no-op re-render."""
        if mode == self.mode:
            return False
        self.mode = mode
        return True

    def set_match_mode(self, match_mode: MatchMode) -> bool:
        """Switch strict vs wildcard matching. Returns whether it
        changed."""
        if match_mode == self.match_mode:
            return False
        self.match_mode = match_mode
        return True

    def toggle_segment(self, segment: str, selected: bool) -> bool:
        """Add or remove ``segment`` from the ordered selection.

        Idempotent per target state: selecting an already-selected
        segment (or deselecting an absent one) is a no-op, and selection
        order is preserved for downstream display. Returns whether the
        selection changed so a caller can skip a no-op re-render.
        """
        if selected:
            if segment in self.selected_segments:
                return False
            self.selected_segments.append(segment)
            return True
        if segment not in self.selected_segments:
            return False
        self.selected_segments.remove(segment)
        return True

    def set_feature(self, feature: str, value: str) -> bool:
        """Set one feature in the query, or clear it when ``value`` is a
        cleared-cell sentinel (``""`` / ``"0"``).

        Clearing on ``"0"`` matches the strict query rule where an
        unspecified cell carries no constraint, so the query holds only
        explicit plus and minus values. Returns whether the query
        changed so a caller can skip a no-op re-render.
        """
        if value in _CLEARED_FEATURE_VALUES:
            return self.selected_features.pop(feature, None) is not None
        if self.selected_features.get(feature) == value:
            return False
        self.selected_features[feature] = value
        return True

    def set_class_hidden(self, label: str, hidden: bool) -> bool:
        """Hide or reveal a display class.

        The hidden set is advisory and may hold a label the current
        grouping does not emit, since ``visible_groups`` filters by
        membership and an absent label removes nothing. Returns whether
        the hidden set changed so a caller can skip a no-op re-render.
        """
        if hidden:
            if label in self.hidden_segment_classes:
                return False
            self.hidden_segment_classes.add(label)
            return True
        if label not in self.hidden_segment_classes:
            return False
        self.hidden_segment_classes.discard(label)
        return True

    def reset_selection(self) -> None:
        """Clear both the segment selection and the feature query.

        Leaves the inventory, engine, mode, match mode, and hidden
        classes untouched (the user-pressed Clear semantics).
        """
        self.selected_segments.clear()
        self.selected_features.clear()
