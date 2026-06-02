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
      seg selection (a SEG→FEAT transition with a non-empty selection).
      The FEAT-mode analysis should display the **original seg set**
      as the matches, not a strict re-query of the projected spec.
      Otherwise the round-trip silently drops segments whose values
      became ``'0'`` on the projected features.
    * ``"typed"``: the query reflects user input in FEAT mode (or an
      empty starting state). Matches use the strict ``find_segments``
      default, which is what the user expects when typing.

    The caller is responsible for flipping origin to ``"typed"`` the
    first time the user toggles a feature in FEAT mode after a
    projected transition.
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
) -> ModeTransition:
    """Project the outgoing mode into the incoming one.

    ``saved_*`` means "state remembered from the mode we just left".
    ``selected_*`` means "state that should be active immediately after
    the switch in the target mode".

    Origin tracking: a SEG→FEAT switch with a non-empty seg selection
    yields ``feature_query_origin="projected"`` and the saved seg
    state survives the transition so the FEAT-mode analysis can show
    those exact segments as the matches. All other transitions are
    ``"typed"``.
    """
    current = Mode(current_mode)
    target = Mode(target_mode)
    feature_query_origin = "typed"

    if current == Mode.SEG_TO_FEAT:
        saved_seg_state = list(selected_segments)
        if selected_segments and engine is not None:
            saved_feat_state = dict(
                engine.project_segments_to_features(selected_segments)
            )
            # Mark the resulting FEAT query as projected so the
            # analysis displays the original seg set; the round-trip
            # invariant ``SEG /b i j/ → FEAT → SEG → /b i j/`` depends
            # on this flag flowing through to ``summarize_feature_query``.
            if target == Mode.FEAT_TO_SEG and saved_feat_state:
                feature_query_origin = "projected"
        else:
            saved_feat_state = {}
    else:
        saved_feat_state = dict(selected_features)
        if selected_features and engine is not None:
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
        feature_query_origin=feature_query_origin,
    )


def mode_status_text(mode: Mode | str, *, has_engine: bool) -> str:
    """Status-bar helper text for the active mode."""
    if not has_engine:
        return "Select an inventory from the dropdown to begin."
    if Mode(mode) == Mode.SEG_TO_FEAT:
        return "Click a segment to inspect its features."
    return "Toggle feature values (+/−) to find matching segments."
