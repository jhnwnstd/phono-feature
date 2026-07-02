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

from phonology_shared.chart.segment_classes import count_segment_classes
from phonology_shared.data.limits import (
    MAX_CONSONANTS,
    MAX_SEGMENTS,
    MAX_VOWELS,
)

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import FeatureEngine, MatchMode


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
      The FEAT-mode display shows ``find_segments(query)``:
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
    the per-pane invariants aligned: FEAT-mode highlights are a
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
    match_mode: MatchMode | None = None,
) -> ModeTransition:
    """Project the outgoing mode into the incoming one.

    ``saved_*`` means "state remembered from the mode we just left".
    ``selected_*`` means "state that should be active immediately
    after the switch in the target mode".

    ``match_mode`` is the active strict/wildcard toggle. The FEAT
    pane's highlight is mode-aware (``summarize_feature_query``
    threads it), so the FEAT to SEG projection must run the same
    semantics: with wildcard active, a strict projection here would
    silently drop every segment that matched only through an
    unspecified value, breaking the contract that the post-switch
    SEG selection equals the set the user was just inspecting.
    ``None`` falls back to the engine's strict default.

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
            if match_mode is None:
                saved_seg_state = list(
                    engine.find_segments(dict(selected_features))
                )
            else:
                saved_seg_state = list(
                    engine.find_segments(
                        dict(selected_features), mode=match_mode
                    )
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
    # FEAT mode: the analysis pane's empty state already says how to
    # query ("Toggle feature values to query the inventory."), so the
    # status bar stays quiet rather than repeating it.
    return ""


#: Template for the clipboard-copy status; substituted in Python
#: and in main.js so both UIs read the same wording.
CLIPBOARD_COPY_MESSAGE_TEMPLATE: str = "Copied /{seg}/ to clipboard"


def clipboard_copy_message(seg: str) -> str:
    return CLIPBOARD_COPY_MESSAGE_TEMPLATE.format(seg=seg)


#: Template for the load-success status message. Relayed through
#: ``STATUS_TEXT`` so the web can substitute locally and stay
#: byte-identical to the desktop's rendering of the same load.
INVENTORY_LOADED_TEMPLATE: str = (
    "{name}: {n_segments} segments × {n_features} features"
)


def inventory_loaded_message(
    *, name: str, n_segments: int, n_features: int
) -> str:
    """Status-bar text after a successful inventory load. Both UIs
    render identical wording from
    :py:data:`INVENTORY_LOADED_TEMPLATE`.
    """
    return INVENTORY_LOADED_TEMPLATE.format(
        name=name, n_segments=n_segments, n_features=n_features
    )


#: Template for the load-failure status message. ``{fname}`` and
#: ``{issue}`` are substituted by each UI in its own runtime; the
#: web build relays this template through ``STATUS_TEXT`` so JS
#: can do the substitution without round-tripping the bridge.
LOAD_FAILED_TEMPLATE: str = "Cannot load {fname}: {issue}"


def inventory_load_failure_message(*, fname: str, issue: str) -> str:
    """Status-bar text after a failed inventory load. The filename
    is load-bearing: background paths (filesystem watcher auto-reload,
    startup auto-restore) can fail without a user-initiated pick, so
    dropping it would leave failures unanchored.
    """
    return LOAD_FAILED_TEMPLATE.format(fname=fname, issue=issue)


#: Heading above the validation-issue list shown in the analysis
#: pane (desktop) and the Class tab (web) after a failed load.
#: Names the engine's actual exception category so the user can
#: tell schema failure from I/O failure.
VALIDATION_REPORT_HEADING: str = "Validation errors:"


def theme_toggle_tooltip(*, is_dark: bool) -> str:
    """Tooltip / aria-label on the theme button. Names the
    destination of clicking (the opposite of the active theme).
    """
    return "Switch to light mode" if is_dark else "Switch to dark mode"


def theme_toggle_glyph(*, is_dark: bool) -> str:
    """Glyph shown on the theme button. Mirrors the tooltip: when
    dark is active the button shows the sun (clicking switches to
    light); when light is active it shows the moon. U+2600 BLACK
    SUN renders cleanly in both Qt's default font and the browser
    font stack; the moon U+263E was already shared.
    """
    return "☀" if is_dark else "☾"


#: Status-bar message when the user hits undo with no history.
UNDO_NOTHING_MESSAGE: str = "Nothing to undo."

#: Status-bar message when the user hits redo with no future history.
REDO_NOTHING_MESSAGE: str = "Nothing to redo."

#: ``{n}`` and ``{plural}`` substituted per UI.
UNDID_TEMPLATE: str = "Undid {n} cell change{plural}."

#: ``{n}`` and ``{plural}`` substituted per UI.
REDID_TEMPLATE: str = "Redid {n} cell change{plural}."

#: ``{seg}`` substituted per UI. Editor add/remove status messages.
ADDED_SEGMENT_TEMPLATE: str = "Added segment '{seg}'."
REMOVED_SEGMENT_TEMPLATE: str = "Removed segment '{seg}'."

#: ``{feat}`` substituted per UI. Editor add/remove status messages.
ADDED_FEATURE_TEMPLATE: str = "Added feature '{feat}'."
REMOVED_FEATURE_TEMPLATE: str = "Removed feature '{feat}'."


def plural_s(n: int) -> str:
    """English plural-suffix helper. Single rule shared by both UIs
    so ``"1 cell change"`` vs ``"2 cell changes"`` stays consistent.
    """
    return "" if n == 1 else "s"


def undid_message(n: int) -> str:
    """Editor status after undo. ``{plural}`` resolves via
    :py:func:`plural_s`.
    """
    return UNDID_TEMPLATE.format(n=n, plural=plural_s(n))


def redid_message(n: int) -> str:
    return REDID_TEMPLATE.format(n=n, plural=plural_s(n))


def added_segment_message(seg: str) -> str:
    return ADDED_SEGMENT_TEMPLATE.format(seg=seg)


def removed_segment_message(seg: str) -> str:
    return REMOVED_SEGMENT_TEMPLATE.format(seg=seg)


def added_feature_message(feat: str) -> str:
    return ADDED_FEATURE_TEMPLATE.format(feat=feat)


def removed_feature_message(feat: str) -> str:
    return REMOVED_FEATURE_TEMPLATE.format(feat=feat)


#: Fraction of a cap at which the live editor counter turns from
#: neutral to warning, so the user sees the ceiling approaching
#: before an add is refused. Below it the counter reads "ok".
_CAP_WARN_FRACTION: float = 0.9


@dataclass(frozen=True)
class InventoryCapStatus:
    """Live vowel / consonant / total counts for the editor counter,
    classified against the hard caps.

    ``severity`` is ``"error"`` only when a count is strictly OVER its
    cap -- an INVALID inventory the save gate refuses (reachable by
    editing a cell so a segment reclassifies past its class cap, not
    just by adding). At exactly the cap the inventory is still valid but
    FULL (the next add is refused), so it reads ``"warn"`` alongside the
    approaching-cap case (>= :py:data:`_CAP_WARN_FRACTION` of a cap), not
    red error. ``"ok"`` otherwise. This keeps the counter's colour in
    step with the ``count > cap`` enforcement gate, so a valid at-cap
    inventory (e.g. exactly 50 vowels) no longer flashes error-red.
    ``text`` is the ready-to-render one-line summary both UIs display;
    the counts are exposed too so a frontend can style the individual
    figures if it wants."""

    n_vowels: int
    n_consonants: int
    n_total: int
    severity: str
    text: str


def inventory_cap_status(
    segments: Mapping[str, Mapping[str, str]],
    *,
    normalized: Mapping[str, dict[str, str]] | None = None,
) -> InventoryCapStatus:
    """Build the live cap-counter view model for an editor grid.

    Class counts come from
    :py:func:`phonology_shared.chart.segment_classes.count_segment_classes`
    (the single source the save-time
    :py:func:`~phonology_shared.chart.segment_classes.validate_class_caps`
    gate also uses), so the counter and the enforcement can never
    disagree about which side a segment falls on, tone letters
    included (counted toward the total, never toward the consonant
    cap). Cheap to recompute on each grid mutation at the capped
    inventory sizes (<=180 segments). ``normalized`` forwards
    pre-normalized bundles when the caller already holds them.
    """
    n_vowels, n_consonants, n_total = count_segment_classes(
        segments, normalized=normalized
    )
    pairs = (
        (n_vowels, MAX_VOWELS),
        (n_consonants, MAX_CONSONANTS),
        (n_total, MAX_SEGMENTS),
    )
    if any(count > cap for count, cap in pairs):
        # Strictly over a cap == invalid (the save gate refuses it).
        severity = "error"
    elif any(count >= _CAP_WARN_FRACTION * cap for count, cap in pairs):
        # At the cap (valid but full) or approaching it: amber, not red.
        severity = "warn"
    else:
        severity = "ok"
    text = (
        f"Vowels {n_vowels}/{MAX_VOWELS} · "
        f"Consonants {n_consonants}/{MAX_CONSONANTS} · "
        f"Total {n_total}/{MAX_SEGMENTS}"
    )
    return InventoryCapStatus(
        n_vowels=n_vowels,
        n_consonants=n_consonants,
        n_total=n_total,
        severity=severity,
        text=text,
    )


def palette_toggle_tooltip(*, is_colorblind: bool) -> str:
    """Tooltip / aria-label on the colorblind-palette button.
    Names the destination palette. ``-friendly`` is retained:
    it disambiguates intent (palette FOR colorblind users, not
    AS colorblind) and the no-dashes house rule targets sentence
    punctuation only, not compound modifiers.
    """
    if is_colorblind:
        return "Switch to standard palette"
    return "Switch to colorblind-friendly palette"
