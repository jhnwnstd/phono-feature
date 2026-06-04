"""HTML rendering for the AnalysisPanel. Returns HTML strings;
holds no GUI state. Every interpolation of inventory-provided text
goes through ``html.escape``; nothing else in the project
sanitizes segment symbols or feature names.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from phonology_shared.presentation.constants import (
    CHIP_BORDER_RADIUS_PX,
    CHIP_FONT_SIZE_PT,
    CHIP_MARGIN_PX,
    CHIP_PADDING_CSS,
    MINUS_SIGN,
    MONO_FAMILY_CSS,
    TagColor,
    sort_features,
    sort_spec,
    tag_palettes,
)
from phonology_shared.presentation.mode_logic import VALIDATION_REPORT_HEADING
from phonology_shared.presentation.palette import C

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import (
        FeatureEngine,
        NaturalClassCompletion,
    )


# --- chip + paragraph primitives ---------------------------------


def _tag(text: str, colour: TagColor) -> str:
    """Render a coloured inline chip. ``text`` is escaped here.

    ``white-space: nowrap`` keeps the chip atomic: browsers treat
    ``/`` as a soft break point (same heuristic that lets long URLs
    wrap), so without nowrap a chip like ``/ɪ/`` can end up split
    across lines with ``/`` on one line and ``ɪ/`` on the next.
    """
    palette = tag_palettes()
    bg, fg = palette.get(colour, palette[TagColor.NEUTRAL])
    return (
        f"<span style='"
        f"background:{bg}; color:{fg};"
        f" border-radius:{CHIP_BORDER_RADIUS_PX}px;"
        f" padding:{CHIP_PADDING_CSS};"
        f" margin:{CHIP_MARGIN_PX}px;"
        f" font-family:{MONO_FAMILY_CSS};"
        f" font-size:{CHIP_FONT_SIZE_PT}pt;"
        f" white-space:nowrap;'>"
        f"{html.escape(text)}</span>"
    )


def _segment_chip(seg: str, colour: TagColor = TagColor.SEGMENT) -> str:
    """Render a segment symbol as a chip wrapped in slashes."""
    return _tag(f"/{seg}/", colour)


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


def _render_universal_spec() -> str:
    """Markup for the universal-class spec line, shown when the
    completed class is the entire inventory and the minimal spec
    is the empty bundle.
    """
    return (
        f"<p><b>Minimal specification:</b>"
        f" {_tag('∅ (universal)', TagColor.NEUTRAL)}</p>"
    )


def _render_completion_specs(
    bundles: Sequence[Mapping[str, str]],
) -> str:
    """Render the minimal specs of a completion.

    Dispatches to :py:func:`_render_universal_spec` when the
    bundle is the universal-class empty bundle, otherwise to
    :py:func:`_render_spec_list` (which handles the singular vs
    "Minimal specifications (N)" headings and numbered rows).
    """
    if bundles and not bundles[0]:
        return _render_universal_spec()
    return _render_spec_list(bundles)


def _render_matching_segments(matching: Sequence[str]) -> str:
    """HTML for the matching-segments answer of a feature query.

    ``"none"`` when empty; otherwise ``"Matching N segment(s):"``
    followed by the chips. Shared between the legacy blob renderer
    and the per-tab variant so the two surfaces can't drift on the
    answer line.
    """
    if not matching:
        return f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
    n = len(matching)
    chips = " ".join(_segment_chip(seg) for seg in matching)
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
    """
    result: dict[str, dict[str, list[str]]] = {}
    seg_set = set(segs)
    for feat in engine.features:
        plus_in = engine.plus_segs[feat] & seg_set
        minus_in = engine.minus_segs[feat] & seg_set
        if not (plus_in and minus_in):
            continue
        spec_in = engine.spec_segs[feat] & seg_set
        entry: dict[str, list[str]] = {
            "+": [s for s in segs if s in plus_in],
            "-": [s for s in segs if s in minus_in],
        }
        if len(spec_in) < len(seg_set):
            entry["0"] = [s for s in segs if s not in spec_in]
        result[feat] = entry
    return result


# --- top-level renderers -----------------------------------------


def render_single_segment(
    seg: str,
    feats: dict[str, str],
    completion: NaturalClassCompletion,
) -> str:
    """Build HTML for a single selected segment.

    ``completion`` is the precomputed
    :py:class:`~phonology_shared.theory.feature_engine.NaturalClassCompletion`
    for ``[seg]``; the renderer dispatches on its status without
    re-asking the engine. The previous fallback that quietly looked
    for an underspec-compatible equivalence class is gone. When
    ``seg`` is not its own natural class the user now sees the
    smallest strict completion explicitly.
    """
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
    seg_safe = html.escape(seg)
    out = (
        f"<p><b style='color:{C['text']}'>/{seg_safe}/</b>"
        " feature bundle:</p>"
        f"<p>{plus_tags}</p>"
        f"<p>{minus_tags}</p>"
    )
    out += _render_completion_body(completion)
    return out


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
    # additions is tuple-of-tuples; current solver produces a single
    # completion, but pick the first defensively if the shape ever
    # widens.
    if not completion.additions:
        return ""
    additions = completion.additions[0]
    n = len(additions)
    chips = " ".join(_segment_chip(seg, TagColor.NEUTRAL) for seg in additions)
    return (
        f"<p><b>{n} {_plural(n, 'segment')} needed for natural class:</b></p>"
        f"<p>{chips}</p>"
    )


def render_multi_segment(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    completion: NaturalClassCompletion,
) -> str:
    """Build HTML for multiple selected segments.

    Two-column layout: selection / natural-class verdict on the
    left, shared / contrasting features on the right. Falls back to
    a single full-width column for the universal class (whole
    inventory selected), where the left side reduces to one line.
    """
    seg_tags = " ".join(_segment_chip(seg) for seg in segs)
    # Universal-class layout cue: the spec is the empty bundle. The
    # left column collapses to one line, so render full-width.
    is_universal = (
        completion.status == "already_natural_class"
        and completion.selected_minimal_bundles
        and not completion.selected_minimal_bundles[0]
    )
    nc_html, spec_html = _render_natural_class_verdict(completion)
    common_html = _render_shared_features(common)
    contrast_html = _render_contrast_section(engine, segs, contrastive)
    selected_html = f"<p><b>Selected:</b> {seg_tags}</p>"
    if is_universal:
        return (
            f"{selected_html}{nc_html}{spec_html}{common_html}{contrast_html}"
        )
    return (
        "<table width='100%' cellpadding='0' cellspacing='0'>"
        "<tr>"
        "<td width='50%' style='vertical-align:top; padding-right:18px;'>"
        f"{selected_html}{nc_html}{spec_html}{common_html}"
        "</td>"
        "<td width='50%' style='vertical-align:top;'>"
        f"{contrast_html}"
        "</td>"
        "</tr></table>"
    )


def render_feat_to_seg(
    feature_dict: dict[str, str],
    matching: list[str],
) -> str:
    """Build HTML for a feature-to-segment query result."""
    feat_tags = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(feature_dict).items()
    )
    return f"<p><b>Query:</b> {feat_tags}</p>{_render_matching_segments(matching)}"


# --- helpers for render_multi_segment ----------------------------


def _render_shared_features(common: dict[str, str]) -> str:
    if not common:
        return f"<p><b>Shared features:</b> {_muted_italic_span('none')}</p>"
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
            for feat in sort_features(list(contrastive))
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
    plus_chips = " ".join(_segment_chip(seg) for seg in groups["+"])
    minus_chips = " ".join(_segment_chip(seg) for seg in groups["-"])
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
        zero_chips = " ".join(
            _segment_chip(seg, TagColor.NEUTRAL) for seg in groups["0"]
        )
        zero_glyph = f"<span style='color:{C['text_dim']}'>0</span>"
        cells.append(
            f"<td style='{_CONTRAST_CELL_BASE}'>"
            f"{zero_glyph}&nbsp;{zero_chips}</td>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


def _render_natural_class_verdict(
    completion: NaturalClassCompletion,
) -> tuple[str, str]:
    """Return ``(verdict_html, spec_html)`` from the completion.

    For ``already_natural_class``, ``spec_html`` is the minimal
    feature spec(s) of the selection. For both completion statuses
    (``one_minimal_completion`` / ``multiple_minimal_completions``)
    ``spec_html`` is empty: the verdict line carries the chips and
    the completed-class spec is intentionally suppressed to keep
    the not-a-natural-class display focused on what to add.
    """
    if completion.status == "already_natural_class":
        verdict = f"<p><b>Natural class:</b> {_yes_no(True)}</p>"
        return verdict, _render_completion_specs(
            completion.selected_minimal_bundles
        )
    additions = completion.additions[0] if completion.additions else ()
    n = len(additions)
    chips = " ".join(_segment_chip(seg, TagColor.NEUTRAL) for seg in additions)
    verdict = (
        f"<p><b>Natural class:</b> {_yes_no(False)},"
        f" add {n} {_plural(n, 'segment')} to complete:</p>"
        f"<p>{chips}</p>"
    )
    return verdict, ""


# ---------------------------------------------------------------------------
# Per-tab renderers: one HTML string per analysis tab in the UI.
#
# The single-blob ``render_*`` functions above are still used (the web's
# legacy ``analysis_html`` payload reads them) but the desktop's tabbed
# analysis panel and the matching web layout consume these per-tab
# variants so each tab gets exactly its section. Splitting the
# rendering at this layer keeps the desktop and web in lockstep: both
# read the same Python output via ``view_models``.
# ---------------------------------------------------------------------------


#: Maximum chip count rendered inline in the persistent selection
#: header. Past this, the header truncates and appends a "+N more"
#: muted indicator. The full selection is still available via the
#: per-tab content below; this just keeps the persistent header
#: from bloating the analysis pane on selections like General-IPA's
#: "all 97 consonants", which would otherwise wrap to many rows,
#: push the tabs / content down, and collide with the expand
#: button at the top-right.
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
        chips = " ".join(_segment_chip(seg) for seg in segs)
    else:
        head = " ".join(
            _segment_chip(seg) for seg in segs[:SELECTION_HEADER_MAX_CHIPS]
        )
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
