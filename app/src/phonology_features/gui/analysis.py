"""HTML rendering for the AnalysisPanel.

All public functions return HTML strings and hold no GUI state.
Every interpolation of inventory-provided text (segment symbols,
feature names) goes through ``html.escape``; nothing else in the
project sanitizes them.

Conventions:

* Chip colours are typed (:class:`TagColor`), not magic strings.
* Chip geometry (border-radius, padding, margin, font size) lives
  in ``constants.py`` so every chip is identical by construction.
* Repeated HTML shapes are factored into helpers so the top-level
  renderers read as a sequence of intent.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from phonology_features.gui.constants import (
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
from phonology_features.gui.palette import C

if TYPE_CHECKING:
    from phonology_engine.feature_engine import FeatureEngine


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
    """Inline ``<i>`` styled with the palette's muted-text colour."""
    return f"<i style='color:{C['text_dim']}'>{text}</i>"


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
    engine: FeatureEngine,
    seg: str,
    feats: dict[str, str],
) -> str:
    """Build HTML for a single selected segment."""
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
    is_nc, specs = engine.is_natural_class([seg])
    if not is_nc:
        non_zero = {
            feature: value for feature, value in feats.items() if value != "0"
        }
        equiv = engine.find_segments(non_zero, underspec_compatible=True)
        if len(equiv) > 1:
            is_nc, specs = engine.is_natural_class(equiv)
    if is_nc and specs:
        out += _render_spec_list(specs)
    else:
        out += _muted_italic_p("Not uniquely characterizable.")
    return out


def render_multi_segment(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
    contrastive: dict[str, dict[str, list[str]]],
    suggested: list[str],
) -> str:
    """Build HTML for multiple selected segments.

    Two-column layout: selection / natural-class verdict on the
    left, shared / contrasting features on the right. Falls back to
    a single full-width column for the universal class (whole
    inventory selected), where the left side reduces to one line.
    """
    seg_tags = " ".join(_segment_chip(seg) for seg in segs)
    is_nc, specs = engine.is_natural_class(segs)
    is_universal = is_nc and (not specs or not specs[0])
    nc_html, spec_html = _render_natural_class_verdict(engine, segs, suggested)
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
    if matching:
        seg_tags = " ".join(_segment_chip(seg) for seg in matching)
        n = len(matching)
        segs_html = (
            f"<p><b>Matching {_plural(n, 'segment')} ({n}):</b></p>"
            f"<p>{seg_tags}</p>"
        )
    else:
        segs_html = (
            f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
        )
    return f"<p><b>Query:</b> {feat_tags}</p>{segs_html}"


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
    engine: FeatureEngine,
    segs: list[str],
    suggested: list[str],
) -> tuple[str, str]:
    """Return ``(verdict_html, spec_html)``. ``spec_html`` is empty
    for a No verdict (no minimal bundle to show)."""
    is_nc, specs = engine.is_natural_class(segs)
    if is_nc:
        verdict = f"<p><b>Natural class:</b> {_yes_no(True)}</p>"
        is_universal = not specs or not specs[0]
        if is_universal:
            spec_html = (
                f"<p><b>Minimal specification:</b>"
                f" {_tag('∅ (universal)', TagColor.NEUTRAL)}</p>"
            )
        else:
            spec_html = _render_spec_list(specs)
        return verdict, spec_html
    if suggested:
        suggested_tags = " ".join(
            _segment_chip(seg, TagColor.NEUTRAL) for seg in suggested
        )
        n = len(suggested)
        verdict = (
            f"<p><b>Natural class:</b> {_yes_no(False)},"
            f" add {n} {_plural(n, 'segment')} to complete:</p>"
            f"<p>{suggested_tags}</p>"
        )
    else:
        verdict = f"<p><b>Natural class:</b> {_yes_no(False)}</p>"
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


def render_selection_summary_seg(segs: list[str]) -> str:
    """Persistent header content for SEG-mode selections.

    Returns ``"Selected: chip chip"``-style HTML that sits above the
    tabs and doesn't move when the user switches tabs. Empty
    selection returns the empty string. The surrounding chrome
    hides the strip entirely (desktop ``setVisible(False)`` / web
    ``hidden`` attribute), so we don't repeat what the status bar
    already says.
    """
    if not segs:
        return ""
    chips = " ".join(_segment_chip(seg) for seg in segs)
    return f"<p><b>Selected ({len(segs)}):</b> {chips}</p>"


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
    engine: FeatureEngine,
    segs: list[str],
    suggested: list[str],
) -> str:
    """Class tab content for SEG mode.

    The "is this a natural class?" verdict is no longer shown as
    Yes/No text. The surrounding tab colour conveys that (driven
    by ``analysis_tabs.class_state``). The body now carries only
    the substantive answer:

    * Natural class: the minimal feature specifications.
    * Not a natural class but completable: "N segments needed
      for natural class:" followed by the chips that would
      complete it.
    * Not a natural class and not completable from the current
      inventory: a muted italic note.
    """
    if not segs:
        # Empty body. The status bar already tells the user what to
        # do ("Click a segment to inspect its features."), so the tab
        # stays quiet instead of echoing that prompt.
        return ""
    if len(segs) == 1:
        seg = segs[0]
        feats = engine.get_segment_features(seg)
        is_nc, specs = engine.is_natural_class([seg])
        if not is_nc:
            non_zero = {feat: val for feat, val in feats.items() if val != "0"}
            equiv = engine.find_segments(non_zero, underspec_compatible=True)
            if len(equiv) > 1:
                is_nc, specs = engine.is_natural_class(equiv)
        if is_nc and specs:
            return _render_spec_list(specs)
        return _muted_italic_p("Not uniquely characterizable.")
    is_nc, specs = engine.is_natural_class(segs)
    if is_nc:
        if not specs or not specs[0]:
            return (
                f"<p><b>Minimal specification:</b>"
                f" {_tag('∅ (universal)', TagColor.NEUTRAL)}</p>"
            )
        return _render_spec_list(specs)
    if suggested:
        chips = " ".join(
            _segment_chip(seg, TagColor.NEUTRAL) for seg in suggested
        )
        n = len(suggested)
        return (
            f"<p><b>{n} {_plural(n, 'segment')} needed for natural"
            f" class:</b></p>"
            f"<p>{chips}</p>"
        )
    return _muted_italic_p("No natural-class completion from this inventory.")


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
            "Set + or − on features in the feature pane "
            "to see matching segments."
        )
    if not matching:
        return f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
    n = len(matching)
    chips = " ".join(_segment_chip(seg) for seg in matching)
    return (
        f"<p><b>Matching {_plural(n, 'segment')} ({n}):</b></p>"
        f"<p>{chips}</p>"
    )


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
        # Empty body, same reasoning as the Class tab: the status
        # bar carries the "click a segment" prompt, so this tab
        # doesn't repeat it.
        return ""
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
        return _muted_italic_p("No features in the current query.")
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
    multi-segment selections; the under-two-segments case returns
    an empty body so the tab stays quiet rather than echoing the
    status-bar prompt.
    """
    if len(segs) < 2:
        return ""
    return _render_contrast_section(engine, segs, contrastive)


def render_contrasts_tab_feat() -> str:
    """Contrasts tab in FEAT mode is not meaningful: the user is
    asking which segments match a feature spec, not how segments
    differ. Renders a stable placeholder so the tab still exists
    and the user isn't left wondering whether they broke something.
    """
    return _muted_italic_p(
        "Switch to segment-mode and select two or more segments "
        "to compare features across them."
    )
