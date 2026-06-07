"""HTML rendering for the AnalysisPanel. Returns HTML strings;
holds no GUI state. Every interpolation of inventory-provided text
goes through ``html.escape``; nothing else in the project
sanitizes segment symbols or feature names.
"""

from __future__ import annotations

import functools
import html
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from phonology_shared.presentation import palette as _palette
from phonology_shared.presentation.constants import (
    MINUS_SIGN,
    TagColor,
    sort_features,
    sort_spec,
    tag_prefix,
)
from phonology_shared.presentation.mode_logic import VALIDATION_REPORT_HEADING
from phonology_shared.presentation.palette import C

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import (
        FeatureEngine,
        NaturalClassCompletion,
    )


# --- chip + paragraph primitives ---------------------------------


@functools.lru_cache(maxsize=2048)
def _tag_cached(text: str, colour: TagColor, _version: int) -> str:
    """Memoised inner body of :py:func:`_tag`. The ``_version`` arg
    is the palette ``theme_version``, threaded through so a theme
    toggle invalidates the cache. Working set is bounded (~300
    entries per inventory: segments x 2 colours + features x 2
    signs); maxsize=2048 covers the worst PHOIBLE inventory plus
    headroom."""
    return f"{tag_prefix(colour)}{html.escape(text)}</span>"


def _tag(text: str, colour: TagColor) -> str:
    """Render a coloured inline chip. ``text`` is escaped here.

    ``white-space: nowrap`` keeps the chip atomic: browsers treat
    ``/`` as a soft break point (same heuristic that lets long URLs
    wrap), so without nowrap a chip like ``/ɪ/`` can end up split
    across lines with ``/`` on one line and ``ɪ/`` on the next.
    """
    return _tag_cached(text, colour, _palette.theme_version)


def _tag_raw(escaped_text: str, colour: TagColor) -> str:
    """Fast-path :py:func:`_tag` for callers that hold a
    pre-escaped string (e.g. the engine's
    ``escaped_segments`` / ``escaped_features`` maps). Skips
    ``html.escape`` and goes directly to the prefix cache.
    """
    return f"{tag_prefix(colour)}{escaped_text}</span>"


def _segment_chip(seg: str, colour: TagColor = TagColor.SEGMENT) -> str:
    """Render a segment symbol as a chip wrapped in slashes."""
    return _tag(f"/{seg}/", colour)


def _segment_chip_strip(
    segs: Sequence[str], colour: TagColor = TagColor.SEGMENT
) -> str:
    """Render ``segs`` as a single space-joined chip strip. Replaces
    the inlined ``' '.join(_segment_chip(seg) for seg in ...)`` idiom
    that appeared at 7 sites and benefits from passing a list to
    ``str.join`` instead of a generator (avoids generator overhead;
    ``str.join`` can pre-size the result buffer).
    """
    return " ".join([_segment_chip(seg, colour) for seg in segs])


def _signed_feature_chip(value: str, feature: str) -> str:
    """Render a signed feature chip (e.g. +Voice).

    ``value`` is ``+`` or ``-`` (ASCII); ``0`` is filtered upstream
    by the spec-display logic so any non-``+`` falls through to a
    minus chip.
    """
    if value == "+":
        return _tag(f"+{feature}", TagColor.PLUS)
    return _tag(f"{MINUS_SIGN}{feature}", TagColor.MINUS)


def _muted_italic_span(text: str) -> str:
    """Inline ``<i>`` styled with the palette's muted-text colour.

    ``text`` is HTML-escaped. Every call site currently passes a
    literal string, but escaping unconditionally keeps the rule
    simple ("text helpers escape, HTML helpers don't") and removes
    the footgun if a future caller passes inventory-derived text.
    """
    return f"<i style='color:{C['text_dim']}'>{html.escape(text)}</i>"


def _muted_italic_p(text: str) -> str:
    """Standalone ``<p>`` wrapping ``_muted_italic_span``."""
    return f"<p>{_muted_italic_span(text)}</p>"


def _yes_no(yes: bool) -> str:
    """Yes/No verdict in the palette's positive / negative colour."""
    colour = C["plus"] if yes else C["minus"]
    label = "Yes" if yes else "No"
    return f"<span style='color:{colour}'>{label}</span>"


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    """English pluralisation: ``_plural(1, "segment")`` -> "segment",
    ``_plural(2, "segment")`` -> "segments"."""
    if n == 1:
        return singular
    return plural if plural is not None else singular + "s"


# --- spec-list rendering -----------------------------------------


def _render_spec_list(specs: Sequence[Mapping[str, str]]) -> str:
    """Render minimal feature specifications as numbered HTML rows.

    Drops ``0`` values (under-specification is implicit), collapses
    rows that become identical after the drop, and omits the
    ``1.`` numbering when only one row remains. Returns ``""`` if
    nothing's left to show.
    """
    seen: set[tuple[tuple[str, str], ...]] = set()
    chip_rows: list[str] = []
    for spec in specs:
        filtered = {
            feature: value
            for feature, value in sort_spec(spec).items()
            if value != "0"
        }
        if not filtered:
            continue
        key = tuple(sorted(filtered.items()))
        if key in seen:
            continue
        seen.add(key)
        chip_rows.append(
            " ".join(
                _signed_feature_chip(value, feature)
                for feature, value in filtered.items()
            )
        )
    if not chip_rows:
        return ""
    if len(chip_rows) == 1:
        return f"<p><b>Minimal specification:</b></p>" f"<p>{chip_rows[0]}</p>"
    numbered = "<br>".join(
        f"<span style='color:{C['text_dim']}'>{i + 1}.</span> {row}"
        for i, row in enumerate(chip_rows)
    )
    return (
        f"<p><b>Minimal specifications ({len(chip_rows)}):</b></p>"
        f"<p>{numbered}</p>"
    )


# --- engine-side query helper ------------------------------------


def _render_completion_specs(
    bundles: Sequence[Mapping[str, str]],
) -> str:
    """Render the minimal specs of a completion.

    Renders the universal-class line when the bundle is the empty
    bundle (the completed class is the entire inventory), otherwise
    dispatches to :py:func:`_render_spec_list` (which handles the
    singular vs "Minimal specifications (N)" headings).
    """
    if bundles and not bundles[0]:
        return (
            f"<p><b>Minimal specification:</b>"
            f" {_tag('∅ (universal)', TagColor.NEUTRAL)}</p>"
        )
    return _render_spec_list(bundles)


def _render_matching_segments(matching: Sequence[str]) -> str:
    """HTML for the matching-segments answer of a feature query.

    ``"none"`` when empty; otherwise ``"Matching N segment(s):"``
    followed by the chips. Used by ``render_features_tab_feat`` so
    the answer line shares one source of truth.
    """
    if not matching:
        return f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
    n = len(matching)
    chips = _segment_chip_strip(matching)
    return (
        f"<p><b>Matching {_plural(n, 'segment')} ({n}):</b></p>"
        f"<p>{chips}</p>"
    )


def render_validation_report(issues: Sequence[str]) -> str:
    """HTML for the validation-error banner shown on a failed
    inventory load. Single source of truth so the Class tab on
    web and the analysis pane on desktop produce identical markup
    (red heading + one paragraph per issue). Every issue is
    HTML-escaped because inventory data is user-supplied.
    """
    parts = [
        f"<p><b style='color:{C['minus']}'>"
        f"{html.escape(VALIDATION_REPORT_HEADING)}</b></p>"
    ]
    parts.extend(f"<p>{html.escape(issue)}</p>" for issue in issues)
    return "".join(parts)


def compute_contrastive(
    engine: FeatureEngine,
    segs: list[str],
) -> dict[str, dict[str, list[str]]]:
    """For each feature with both '+' and '-' among ``segs``, bucket
    the segments by their value.

    Returns ``{feat: {'+': [...], '-': [...], '0': [...]}}``. The
    '0' bucket is included only when some segments are
    underspecified. Bucket order follows the caller's ``segs`` list
    so rendered chips align with selection order.

    Iterates ``engine.active_features`` (uniformly-zero features
    cannot be contrastive) and walks ``segs`` once per feature,
    bucketing by direct lookup into the engine's per-feature segment
    sets. Replaces the prior triple-scan that did three list
    comprehensions over ``segs`` per feature.
    """
    result: dict[str, dict[str, list[str]]] = {}
    seg_set = set(segs)
    n_segs = len(seg_set)
    plus_segs = engine.plus_segs
    minus_segs = engine.minus_segs
    spec_segs = engine.spec_segs
    for feat in engine.active_features:
        feat_plus = plus_segs[feat]
        feat_minus = minus_segs[feat]
        if not (feat_plus & seg_set) or not (feat_minus & seg_set):
            continue
        feat_spec = spec_segs[feat]
        plus_bucket: list[str] = []
        minus_bucket: list[str] = []
        zero_bucket: list[str] = []
        for s in segs:
            if s in feat_plus:
                plus_bucket.append(s)
            elif s in feat_minus:
                minus_bucket.append(s)
            elif s not in feat_spec:
                zero_bucket.append(s)
        entry: dict[str, list[str]] = {
            "+": plus_bucket,
            "-": minus_bucket,
        }
        if len(feat_spec & seg_set) < n_segs:
            entry["0"] = zero_bucket
        result[feat] = entry
    return result


def _render_completion_body(completion: NaturalClassCompletion) -> str:
    """Class-pane content for a single selection's completion.

    Hard concept boundary:

    * ``already_natural_class``: render
      ``selected_minimal_bundles``, the minimal feature spec(s)
      of the SELECTED set (Concept A).
    * ``one_minimal_completion`` / ``multiple_minimal_completions``:
      render the "N segments needed for natural class" chip strip
      alone (Concept B). The completed class's minimal specs (if
      anyone wanted them) would be Concept A applied to
      ``S ∪ additions`` and are NOT carried on the completion
      result. The not-a-natural-class UI does not display them, so
      the engine does not pay the hitting-set search cost.
    """
    if completion.status == "already_natural_class":
        return _render_completion_specs(completion.selected_minimal_bundles)
    # Engine contract (NaturalClassCompletion docstring): additions
    # is non-empty whenever status isn't "already_natural_class".
    # additions is tuple-of-tuples; current solver produces a single
    # completion, pick the first.
    additions = completion.additions[0]
    n = len(additions)
    chips = _segment_chip_strip(additions, TagColor.NEUTRAL)
    return (
        f"<p><b>{n} {_plural(n, 'segment')} needed for natural class:</b></p>"
        f"<p>{chips}</p>"
    )


def _render_shared_features(common: dict[str, str]) -> str:
    if not common:
        from phonology_shared.presentation.constants import (
            EMPTY_SHARED_FEATURES_HINT,
        )

        return (
            f"<p><b>Shared features:</b></p>"
            f"<p>{_muted_italic_span(EMPTY_SHARED_FEATURES_HINT)}</p>"
        )
    chips = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(common).items()
    )
    return f"<p><b>Shared features:</b></p><p>{chips}</p>"


def _render_contrast_section(
    engine: FeatureEngine,
    segs: list[str],
    contrastive: dict[str, dict[str, list[str]]],
) -> str:
    """Contrastive-features table, or a one-line "none" reason.

    Rendered as a table so feature names left-align in a fixed
    column and the +/-/0 buckets stack vertically across rows.
    """
    if contrastive:
        body = "".join(
            _render_contrast_row(feat, contrastive[feat])
            for feat in sort_features(contrastive)
        )
        return (
            "<p><b>Contrasting features:</b></p>"
            "<table cellpadding='3' cellspacing='0'"
            " style='border-collapse:separate; border-spacing:0 2px;'>"
            f"{body}"
            "</table>"
        )

    # No contrastive features. Distinguish "actually identical"
    # from "only differ in unspecified features": the latter is a
    # common source of "why do these look the same?" confusion.
    def _has_mixed_underspec(feat: str) -> bool:
        vals = {engine.segments[seg].get(feat, "0") for seg in segs}
        return len(vals) > 1 and "0" in vals

    has_underspec_diff = any(_has_mixed_underspec(f) for f in engine.features)
    reason = (
        "none (only unspecified features differ)"
        if has_underspec_diff
        else "none (featurally identical)"
    )
    return f"<p><b>Contrasting features:</b> {_muted_italic_span(reason)}</p>"


# Pre-built cell styles to avoid reconstructing identical CSS in
# the per-row helper and to keep geometry tweaks in one place.
_CONTRAST_CELL_BASE: str = "vertical-align:top; padding-right:14px;"
_CONTRAST_NAME_CELL: str = _CONTRAST_CELL_BASE + " white-space:nowrap;"


def _render_contrast_row(feat: str, groups: dict[str, list[str]]) -> str:
    """One ``<tr>`` for the contrastive-features table.

    Columns: feature | + segments | − segments | (0 segments,
    only when the row has underspecified data). Omitting the empty
    third column prevents a selectable empty cell from showing
    up as a phantom highlight.

    A non-breaking space sits between each +/-/0 glyph and its
    first chip so the marker can't end up orphaned on its own
    line; chip-to-chip gaps stay breakable.
    """
    name_html = f"<b>{html.escape(feat)}</b>"
    plus_chips = _segment_chip_strip(groups["+"])
    minus_chips = _segment_chip_strip(groups["-"])
    plus_glyph = f"<span style='color:{C['plus']};font-weight:bold'>+</span>"
    minus_glyph = (
        f"<span style='color:{C['minus']};font-weight:bold'>"
        f"{MINUS_SIGN}</span>"
    )
    cells = [
        f"<td style='{_CONTRAST_NAME_CELL}'>{name_html}</td>",
        f"<td style='{_CONTRAST_CELL_BASE}'>{plus_glyph}&nbsp;{plus_chips}</td>",
        f"<td style='{_CONTRAST_CELL_BASE}'>{minus_glyph}&nbsp;{minus_chips}</td>",
    ]
    if "0" in groups:
        zero_chips = _segment_chip_strip(groups["0"], TagColor.NEUTRAL)
        zero_glyph = f"<span style='color:{C['text_dim']}'>0</span>"
        cells.append(
            f"<td style='{_CONTRAST_CELL_BASE}'>"
            f"{zero_glyph}&nbsp;{zero_chips}</td>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


# ---------------------------------------------------------------------------
# Per-tab renderers: one HTML string per analysis tab in the UI.
#
# The desktop's tabbed analysis panel and the web's tabbed layout
# consume these per-tab variants so each tab gets exactly its
# section. Both clients read the same Python output via
# ``view_models``, so the rendering stays in lockstep without a
# parallel JS implementation.
# ---------------------------------------------------------------------------


#: Maximum chip count rendered inline in the persistent selection
#: header. Past this, the header truncates and appends a "+N more"
#: muted indicator. The full selection is still available via the
#: per-tab content below; this just keeps the persistent header
#: from bloating the analysis pane on selections like General-IPA's
#: "all 97 consonants", which would otherwise wrap to many rows
#: and push the tabs / content down.
SELECTION_HEADER_MAX_CHIPS: int = 24


def render_selection_summary_seg(segs: list[str]) -> str:
    """Persistent header content for SEG-mode selections.

    Returns ``"Selected (N): chip chip"``-style HTML that sits
    above the tabs and doesn't move when the user switches tabs.
    Empty selection returns the empty string. The surrounding
    chrome hides the strip entirely (desktop ``setVisible(False)``
    / web ``hidden`` attribute), so we don't repeat what the
    status bar already says.

    When the selection exceeds :py:data:`SELECTION_HEADER_MAX_CHIPS`,
    only the first N chips render inline and a muted ``"+M more"``
    indicator stands in for the rest. The full count stays in the
    header label so the user can always see how many segments are
    in play; the truncation only governs the chip rendering.
    """
    if not segs:
        return ""
    count = len(segs)
    if count <= SELECTION_HEADER_MAX_CHIPS:
        chips = _segment_chip_strip(segs)
    else:
        head = _segment_chip_strip(segs[:SELECTION_HEADER_MAX_CHIPS])
        more = count - SELECTION_HEADER_MAX_CHIPS
        chips = f"{head} {_muted_italic_span(f'+{more} more')}"
    return f"<p><b>Selected ({count}):</b> {chips}</p>"


def render_selection_summary_feat(feature_dict: dict[str, str]) -> str:
    """Persistent header content for FEAT-mode queries."""
    if not feature_dict:
        return _muted_italic_p("Toggle feature values to query the inventory.")
    chips = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(feature_dict).items()
    )
    return f"<p><b>Query:</b> {chips}</p>"


def render_class_tab_seg(
    segs: list[str],
    completion: NaturalClassCompletion,
) -> str:
    """Class tab content for SEG mode.

    The Yes/No verdict is no longer shown as text; the surrounding
    tab colour conveys that (driven by ``analysis_tabs.class_state``).
    The body carries the substantive answer:

    * ``already_natural_class``: the minimal feature spec(s) of the
      selection.
    * ``one_minimal_completion`` / ``multiple_minimal_completions``:
      "N segments needed for natural class:" + chips + the minimal
      spec(s) of the completed class.

    The universal class (whole inventory containment) is always a
    valid completion, so there is no "no completion possible"
    fall-through.
    """
    if not segs:
        return _muted_italic_p("Click a segment to inspect it.")
    return _render_completion_body(completion)


def render_class_tab_feat(
    feature_dict: dict[str, str],
    matching: list[str],
) -> str:
    """Class tab content for FEAT mode: list of matching segments
    (the result of the query) + count. The query itself is in the
    persistent header above the tabs, so this tab is purely the
    answer.
    """
    if not feature_dict:
        return _muted_italic_p(
            "Set + or − on a feature to find matching segments."
        )
    return _render_matching_segments(matching)


def render_features_tab_seg(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
) -> str:
    """Features tab content for SEG mode: full feature bundle for a
    single segment, or the shared features (intersection) for a
    multi-segment selection.
    """
    if not segs:
        return _muted_italic_p("Click a segment to view its features.")
    if len(segs) == 1:
        seg = segs[0]
        feats = engine.get_segment_features(seg)
        plus_feats = sort_features(
            [feature for feature, value in feats.items() if value == "+"]
        )
        minus_feats = sort_features(
            [feature for feature, value in feats.items() if value == "-"]
        )
        plus_tags = " ".join(
            _signed_feature_chip("+", feature) for feature in plus_feats
        )
        minus_tags = " ".join(
            _signed_feature_chip("-", feature) for feature in minus_feats
        )
        return (
            f"<p><b>Feature bundle for /{html.escape(seg)}/:</b></p>"
            f"<p>{plus_tags}</p>"
            f"<p>{minus_tags}</p>"
        )
    return _render_shared_features(common)


def render_features_tab_feat(feature_dict: dict[str, str]) -> str:
    """Features tab content for FEAT mode: the active query
    visualised as chips, plus the count. Lighter than the desktop's
    feature pane (which has the interactive +/- buttons); this tab
    is for at-a-glance "what am I querying?" review.
    """
    if not feature_dict:
        return _muted_italic_p("No features set yet.")
    chips = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(feature_dict).items()
    )
    n = len(feature_dict)
    return (
        f"<p><b>Active query ({n} {_plural(n, 'feature')}):</b></p>"
        f"<p>{chips}</p>"
    )


def render_contrasts_tab_seg(
    engine: FeatureEngine,
    segs: list[str],
    contrastive: dict[str, dict[str, list[str]]],
) -> str:
    """Contrasts tab content for SEG mode: feature-by-feature
    breakdown of how the selection splits. Only meaningful for
    multi-segment selections; the under-two-segments case shows a
    short hint pointing the user at the next step.
    """
    if not segs:
        return _muted_italic_p("Select two or more segments to compare.")
    if len(segs) < 2:
        return _muted_italic_p("Select another segment to compare.")
    return _render_contrast_section(engine, segs, contrastive)


def render_contrasts_tab_feat() -> str:
    """Contrasts tab in FEAT mode is not meaningful: the user is
    asking which segments match a feature spec, not how segments
    differ. Stable placeholder so the tab still exists and the user
    isn't left wondering whether they broke something.
    """
    return _muted_italic_p("Switch to segment mode to compare segments.")
