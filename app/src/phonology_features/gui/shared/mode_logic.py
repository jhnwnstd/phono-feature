"""Qt-free mode-transition helpers shared by desktop and web.

This module owns the data rules of the top-level seg/feat mode switch:

* how the outgoing mode projects into the incoming mode
* which exact selection/query state is preserved
* which helper text belongs to each mode

The desktop still owns widget repaint and Qt-property updates. The web
still owns DOM mutation. Both frontends should route the transition's
state math through this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phonology_engine.feature_engine import FeatureEngine


class Mode(StrEnum):
    """Top-level UI mode. StrEnum so values round-trip as plain strings."""

    SEG_TO_FEAT = "seg_to_feat"
    FEAT_TO_SEG = "feat_to_seg"


@dataclass(frozen=True)
class ModeTransition:
    """Projection result for one mode switch.

    ``feature_query_origin`` carries provenance for the resulting FEAT
    query:

    * ``"projected"``: the query was auto-derived from the outgoing
      seg selection (a SEG→FEAT transition with a non-empty
      selection). The user hasn't touched the query yet, so a return
      to SEG mode should restore the ORIGINAL seg selection (from
      ``saved_seg_state``) rather than re-query
      ``find_segments(spec)``, which on non-natural-class selections
      silently expands. The FEAT-mode display itself ALWAYS shows
      ``find_segments(spec)`` so the user-visible invariant -- the
      highlighted segments form a natural class characterised by
      the active query -- always holds.
    * ``"typed"``: the query reflects user input in FEAT mode (or
      an empty starting state). Matches use the strict
      ``find_segments`` default; the seg selection on return is
      whatever the query strictly matches.

    The caller flips origin to ``"typed"`` the first time the user
    toggles a feature in FEAT mode after a projected transition.
    """

    saved_seg_state: list[str]
    saved_feat_state: dict[str, str]
    selected_segments: list[str]
    selected_features: dict[str, str]
    feature_query_origin: str = "typed"


def project_mode_transition(
    current_mode: Mode | str,
    target_mode: Mode | str,
    *,
    selected_segments: list[str],
    selected_features: Mapping[str, str],
    engine: FeatureEngine | None,
    feature_query_origin: str = "typed",
    prior_saved_seg_state: list[str] | None = None,
) -> ModeTransition:
    """Project the outgoing mode into the incoming one.

    ``saved_*`` means "state remembered from the mode we just left".
    ``selected_*`` means "state that should be active immediately
    after the switch in the target mode".

    Origin tracking:

    * SEG→FEAT with a non-empty seg selection sets
      ``feature_query_origin="projected"``. The FEAT-mode display
      shows ``find_segments(saved_feat_state)`` (which may differ
      from the prior seg selection -- the FEAT-mode invariant that
      highlighted segments form a natural class is preserved by
      always using ``find_segments``). The original seg list
      survives as ``saved_seg_state`` for the return trip.
    * FEAT→SEG with the incoming ``feature_query_origin == "projected"``
      AND ``prior_saved_seg_state`` supplied (meaning the user never
      touched the query after it was auto-projected): restores
      that saved seg state directly instead of recomputing from
      ``find_segments``. This is what gives the
      ``SEG → FEAT → SEG`` round-trip its exact preservation.
    * Any other transition is ``"typed"`` and seg state is
      recomputed from the query (or empty if no query).

    Callers without origin / prior-state tracking can omit the
    new parameters; the defaults reproduce the historical
    recompute behaviour.
    """
    current = Mode(current_mode)
    target = Mode(target_mode)
    next_feature_query_origin = "typed"

    if current == Mode.SEG_TO_FEAT:
        saved_seg_state = list(selected_segments)
        if selected_segments and engine is not None:
            saved_feat_state = dict(
                engine.project_segments_to_features(selected_segments)
            )
            if target == Mode.FEAT_TO_SEG and saved_feat_state:
                next_feature_query_origin = "projected"
        else:
            saved_feat_state = {}
    else:
        saved_feat_state = dict(selected_features)
        # If the user never edited the projected query, the original
        # seg selection (carried in ``prior_saved_seg_state``)
        # survives across the FEAT visit unchanged. Otherwise (typed
        # query, no projection memory, or caller didn't supply a
        # prior state), seg state is whatever the query strictly
        # matches.
        if (
            feature_query_origin == "projected"
            and prior_saved_seg_state is not None
            and selected_features
        ):
            saved_seg_state = list(prior_saved_seg_state)
        elif selected_features and engine is not None:
            saved_seg_state = list(
                engine.find_segments(dict(selected_features))
            )
        else:
            saved_seg_state = []

    if target == Mode.SEG_TO_FEAT:
        next_selected_segments = list(saved_seg_state)
        next_selected_features: dict[str, str] = {}
    else:
        next_selected_segments = []
        next_selected_features = dict(saved_feat_state)

    return ModeTransition(
        saved_seg_state=saved_seg_state,
        saved_feat_state=saved_feat_state,
        selected_segments=next_selected_segments,
        selected_features=next_selected_features,
        feature_query_origin=next_feature_query_origin,
    )


def mode_status_text(mode: Mode | str, *, has_engine: bool) -> str:
    """Status-bar helper text for the active mode."""
    if not has_engine:
        return "Select an inventory from the dropdown to begin."
    if Mode(mode) == Mode.SEG_TO_FEAT:
        return "Click a segment to inspect its features."
    return "Toggle feature values (+/−) to find matching segments."
