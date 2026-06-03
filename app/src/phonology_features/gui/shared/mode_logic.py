"""Qt-free mode-transition helpers shared by desktop and web.

This module owns the data rules of mode toggles and pane clears.
The desktop still owns Qt widget repaint; the web still owns DOM
mutation. Every cross-mode state DECISION is made here so the two
frontends cannot disagree on the answer.

Contracts owned here (in dependency order):

* :py:class:`Mode` -- the two top-level modes.
* :py:class:`ModeTransition` + :py:func:`project_mode_transition` --
  the projection rule that decides which selection/query survives
  a mode toggle. The natural-class carry-over from FEAT to SEG is
  pinned by ``test_mode_logic.test_feat_to_seg_carries_natural_class_over``.
* :py:func:`mode_status_text` -- the status-bar message for each
  mode + the "no engine" fallback.
* :py:class:`AnalysisTabId` +
  :py:func:`preserved_analysis_tab` -- the rule "if the user's
  active tab is still valid, keep it; otherwise fall back to
  Class." Consumed by desktop ``AnalysisPanel.set_sections`` and
  web ``setAnalysisTabs``; the desktop's prior unconditional
  ``analysis.clear()`` in ``ModeController.apply_phases`` was the
  cause of the "Class snap on every toggle" bug, fixed by this
  contract.
* :py:class:`ClearScope` + :py:class:`ClearSemantics` +
  :py:func:`clear_semantics_for` -- per-scope effect record for
  the "wipe both panes" code path. Consumed by desktop
  ``_reset_both_sides`` and web ``clearAll``;
  ``test_mode_logic.test_clear_semantics_web_mirror_matches_python``
  pins the hand-mirrored JS constant against the Python factory.

Module-import discipline: no Qt, no DOM, no inventory state. Pure
functions over plain types. Anything that wants to grow a side
effect should add a return value the caller applies, not a hidden
mutation.
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

    Symmetric, stateless rule:

    * **SEG → FEAT.** The seg selection projects to a
      common-features query (``project_segments_to_features``).
      The FEAT-mode display shows ``find_segments(query)`` --
      the strict matches of that query, by construction a
      natural class characterised by the query itself.
    * **FEAT → SEG.** The natural class highlighted in FEAT
      (``find_segments(query)``) becomes the new SEG selection.
      The user sees in SEG the same segments they were just
      inspecting in FEAT.

    No origin tracking, no provenance, no round-trip preservation:
    switching modes always recomputes the target mode's state
    from the outgoing mode's analytical content (selection /
    query), never from cached pre-mode-switch state. This keeps
    the per-pane invariants aligned -- FEAT-mode highlights are a
    natural class, and the SEG selection after a FEAT→SEG switch
    is the same natural class.
    """

    saved_seg_state: list[str]
    saved_feat_state: dict[str, str]
    selected_segments: list[str]
    selected_features: dict[str, str]


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
    ``selected_*`` means "state that should be active immediately
    after the switch in the target mode".

    See :py:class:`ModeTransition` for the cross-mode contract.
    """
    current = Mode(current_mode)
    target = Mode(target_mode)

    if current == Mode.SEG_TO_FEAT:
        saved_seg_state = list(selected_segments)
        if selected_segments and engine is not None:
            saved_feat_state = dict(
                engine.project_segments_to_features(selected_segments)
            )
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
    )


def mode_status_text(mode: Mode | str, *, has_engine: bool) -> str:
    """Status-bar helper text for the active mode."""
    if not has_engine:
        return "Select an inventory from the dropdown to begin."
    if Mode(mode) == Mode.SEG_TO_FEAT:
        return "Click a segment to inspect its features."
    return "Toggle feature values (+/−) to find matching segments."


# ---------------------------------------------------------------------------
# ANALYSIS-PANE PRESERVATION CONTRACT
#
# When new analysis content arrives (a SEG/FEAT mode toggle, a fresh
# selection, an inventory swap), the analysis pane has three tabs --
# Class, Features, Contrasts. The user owns which tab is currently
# active. The system owns whether the Contrasts tab is enabled
# (Contrasts only makes sense for multi-segment SEG selections).
#
# The rule both UIs must follow: KEEP the user's active tab unless
# the new state makes it INVALID. Today the only way a tab becomes
# invalid is the Contrasts tab being disabled while Contrasts is
# active; everything else (Class, Features) is always valid.
#
# Prior to this contract, the desktop's ``ModeController.apply_phases``
# called ``analysis.clear()`` on every mode toggle, which always
# snapped the active tab back to Class -- visible to the user as
# "I clicked Features, toggled to FEAT mode, and lost my place".
# The web never had that bug because ``setAnalysisTabs`` only snaps
# when Contrasts becomes disabled. That web rule is the correct
# contract; it now lives here.
# ---------------------------------------------------------------------------


class AnalysisTabId(StrEnum):
    """Stable identifier for an analysis-pane tab.

    ``StrEnum`` so values round-trip as plain strings across the
    bridge (``"class"`` / ``"features"`` / ``"contrasts"`` are the
    same identifiers the web's ``activateAnalysisTab`` consumes).
    Indices into the Qt ``QTabWidget`` live in the widget itself
    (:py:attr:`AnalysisPanel._TAB_CLASS_IDX` and siblings); the
    widget maps both directions.
    """

    CLASS = "class"
    FEATURES = "features"
    CONTRASTS = "contrasts"


# ---------------------------------------------------------------------------
# CLEAR SEMANTICS
#
# Two contexts call "clear both sides" on the desktop today:
#
#   1. The user pressed the Clear button. Everything the user could
#      see or scroll back to gets wiped: selected segments, selected
#      features, saved cross-mode state, analysis pane content,
#      expand state.
#
#   2. The inventory just changed (load / swap / build). The new
#      inventory has different segments / features, so the OLD
#      saved cross-mode state would be wrong. But the user did NOT
#      ask for a reset; they asked for a fresh inventory. We clear
#      the visible selection but skip touching anything the user
#      themselves controls (notably, no analysis.clear() that would
#      force the Class tab back -- the next refresh will do it).
#
# Pre-Stage-2, those two contexts were spelled as ``silent=False``
# and ``silent=True``. That name encoded the engineering effect, not
# the user-facing reason, and the web had no analogue at all. The
# ``ClearSemantics`` record below names the reason; both UIs read it.
# ---------------------------------------------------------------------------


class ClearScope(StrEnum):
    """Why the clear was called.

    Used by :py:func:`clear_semantics_for` to pick which side
    effects fire. ``StrEnum`` so values round-trip the bridge.
    """

    #: A user pressed Clear or any other explicit reset surface.
    USER_INITIATED = "user_initiated"
    #: An inventory swap is wiping selections that are about to
    #: become meaningless. The user did NOT ask for a reset.
    SILENT_LOAD = "silent_load"


@dataclass(frozen=True)
class ClearSemantics:
    """What "clear both sides" means in a given context.

    Field-level rather than scope-level so a single behavior
    change (e.g. "user-initiated clear should NOT collapse the
    expanded analysis pane any more") is one field flip rather
    than a fork in every call site.
    """

    #: Wipe ``selected_segments`` / ``selected_features`` and
    #: reset every segment-button + feature-row to default.
    reset_active_selection: bool
    #: Wipe ``saved_seg_state`` / ``saved_feat_state`` (the
    #: mode-switch carry-over). False for inventory loads, which
    #: are not "clears" from the user's perspective.
    reset_saved_state: bool
    #: Call the analysis pane's full-reset sink. True only for
    #: user-initiated clears; the refresh path that follows a
    #: load handles its own analysis state.
    reset_analysis_pane: bool
    #: Collapse any active expand on the analysis pane.
    collapse_expanded_analysis: bool


def clear_semantics_for(scope: ClearScope | str) -> ClearSemantics:
    """Map a :py:class:`ClearScope` to its concrete effects.

    The map is exhaustive: every defined scope returns a non-None
    record. A future ClearScope value MUST grow a branch here
    (asserted by ``test_clear_semantics_factory_is_exhaustive``)
    so it can't ship with silent default behavior.
    """
    s = ClearScope(scope)
    if s is ClearScope.USER_INITIATED:
        return ClearSemantics(
            reset_active_selection=True,
            reset_saved_state=True,
            reset_analysis_pane=True,
            collapse_expanded_analysis=True,
        )
    if s is ClearScope.SILENT_LOAD:
        return ClearSemantics(
            reset_active_selection=True,
            reset_saved_state=False,
            reset_analysis_pane=False,
            collapse_expanded_analysis=False,
        )
    # Unreachable: ClearScope is a StrEnum and the call above
    # raises on an unknown value. The explicit raise here makes
    # the exhaustive-match intent visible to readers and is what
    # ``test_clear_semantics_factory_is_exhaustive`` pins.
    raise ValueError(f"clear_semantics_for: unknown scope {s!r}")


def preserved_analysis_tab(
    current: AnalysisTabId | str,
    *,
    contrasts_enabled: bool,
) -> AnalysisTabId:
    """Decide which tab should be active after fresh analysis lands.

    Rule:
      * If the current tab is still valid for the new state, keep it.
      * Otherwise return ``CLASS`` (the always-valid fallback).

    The only way the current tab becomes invalid is for ``CONTRASTS``
    to be active while ``contrasts_enabled=False``. ``CLASS`` and
    ``FEATURES`` are always valid.

    Both desktop ``AnalysisPanel.set_sections`` and web
    ``setAnalysisTabs`` consume this so a mode toggle, a selection
    change, or any other event that lands fresh content does NOT
    surprise the user by snapping the active tab back to Class.

    The full-reset paths (desktop ``AnalysisPanel.clear``, web
    ``clearAnalysisTabs``) deliberately bypass this rule and force
    ``CLASS`` -- they are the documented "user pressed Clear" sink,
    not the steady-state refresh path.
    """
    tab = AnalysisTabId(current)
    if tab is AnalysisTabId.CONTRASTS and not contrasts_enabled:
        return AnalysisTabId.CLASS
    return tab
