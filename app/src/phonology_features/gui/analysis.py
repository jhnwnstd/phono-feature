"""Build the HTML shown in the AnalysisPanel.

All functions return HTML strings and hold no GUI state. Every
interpolation of inventory-provided text (segment symbols, feature
names) goes through ``html.escape`` -- nothing else in the project
sanitizes them, so a feature named ``"<b>oops</b>"`` would otherwise
break the rendered layout.

Design choices that match the rest of the codebase:

  - **Typed chip colours.** ``_tag`` takes a :class:`TagColor` enum,
    not a magic string. Renaming or removing a palette colour shows
    up as a type error; ``_tag(text, "bleu")`` no longer silently
    falls back to gray.

  - **Single chip style.** Border radius, padding, margin, font size
    live in ``constants.py``. Every chip is identical by construction;
    no f-string ever hardcodes a chip dimension.

  - **Compose, don't concatenate.** Repeated HTML shapes (segment
    chips, signed-feature chips, muted-italic paragraphs, count
    paragraphs) live in tiny helpers so the renderer functions read
    as a sequence of intent rather than a wall of f-strings.
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
    from phonology_features.engine.feature_engine import FeatureEngine


# ---------------------------------------------------------------------------
# Chip + paragraph primitives. Every renderer below composes from these.
# ---------------------------------------------------------------------------
def _tag(text: str, colour: TagColor) -> str:
    """Render a coloured inline chip. ``text`` is escaped here so
    every caller can pass raw inventory strings without thinking
    about it. Chip geometry is shared via ``constants.CHIP_*``."""
    palette = tag_palettes()
    bg, fg = palette.get(colour, palette[TagColor.NEUTRAL])
    return (
        f"<span style='"
        f"background:{bg}; color:{fg};"
        f" border-radius:{CHIP_BORDER_RADIUS_PX}px;"
        f" padding:{CHIP_PADDING_CSS};"
        f" margin:{CHIP_MARGIN_PX}px;"
        f" font-family:{MONO_FAMILY_CSS};"
        f" font-size:{CHIP_FONT_SIZE_PT}pt;'>"
        f"{html.escape(text)}</span>"
    )


def _segment_chip(seg: str, colour: TagColor = TagColor.SEGMENT) -> str:
    """Render a segment symbol as a chip with surrounding slashes."""
    return _tag(f"/{seg}/", colour)


def _signed_feature_chip(value: str, feature: str) -> str:
    """Render a feature with its sign as a chip. ``value`` is ``+``
    or ``-`` (ASCII); the rendered prefix is the matching glyph and
    the chip colour follows the sign."""
    if value == "+":
        return _tag(f"+{feature}", TagColor.PLUS)
    # Any non-``+`` value renders as a minus chip. Callers only ever
    # pass ``+`` or ``-`` -- ``0`` is filtered upstream by the spec
    # display logic.
    return _tag(f"{MINUS_SIGN}{feature}", TagColor.MINUS)


def _muted_italic_span(text: str) -> str:
    """Inline ``<i>`` styled with the palette's muted-text colour.
    Used for "none" / "not present" placeholders that sit inside a
    larger paragraph."""
    return f"<i style='color:{C['text_dim']}'>{text}</i>"


def _muted_italic_p(text: str) -> str:
    """Standalone ``<p>`` wrapping ``_muted_italic_span`` for cases
    where the placeholder is its own paragraph block."""
    return f"<p>{_muted_italic_span(text)}</p>"


def _yes_no(yes: bool) -> str:
    """Render a Yes/No verdict in the palette's positive / negative
    colour."""
    colour = C["plus"] if yes else C["minus"]
    label = "Yes" if yes else "No"
    return f"<span style='color:{colour}'>{label}</span>"


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    """English pluralisation. ``_plural(1, "segment")`` -> "segment";
    ``_plural(2, "segment")`` -> "segments"."""
    if n == 1:
        return singular
    return plural if plural is not None else singular + "s"


# ---------------------------------------------------------------------------
# Spec-list rendering
# ---------------------------------------------------------------------------
def _render_spec_list(specs: Sequence[Mapping[str, str]]) -> str:
    """Render minimal feature specifications as numbered HTML rows.

    Drops ``0`` values (under-specification is implicit), collapses
    rows that become identical after the drop, and special-cases the
    single-row case to omit the ``1.`` numbering prefix. Returns ``""``
    if there's nothing left to show.
    """
    seen: set[tuple[tuple[str, str], ...]] = set()
    chip_rows: list[str] = []  # each row is just the chips, no prefix
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
        return f"<p><b>Minimal specification:</b><br>{chip_rows[0]}</p>"
    numbered = "<br>".join(
        f"<span style='color:{C['text_dim']}'>{i + 1}.</span> {row}"
        for i, row in enumerate(chip_rows)
    )
    return (
        f"<p><b>Minimal specifications ({len(chip_rows)}):</b>"
        f"<br>{numbered}</p>"
    )


# ---------------------------------------------------------------------------
# Engine-side query: bucket segments by their value of each contrastive feature
# ---------------------------------------------------------------------------
def compute_contrastive(
    engine: FeatureEngine, segs: list[str]
) -> dict[str, dict[str, list[str]]]:
    """For each feature with both '+' and '-' among ``segs``, bucket the segments.

    Returns ``{feat: {'+': [...], '-': [...], '0': [...]}}``. The '0'
    bucket is only present when some segments are underspecified.
    Bucket order follows the caller's ``segs`` list so rendered chips
    align with selection order.
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


# ---------------------------------------------------------------------------
# Top-level renderers (each returns one HTML fragment for the analysis pane)
# ---------------------------------------------------------------------------
def render_single_segment(
    engine: FeatureEngine, seg: str, feats: dict[str, str]
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

    Two columns from the very top, no full-width header row. The
    selection / natural-class side sits on the left, the analysis
    side (shared and contrasting features) on the right, so
    ``Selected:`` shares its visual row with ``Shared features:``.

        left  (50%): Selected segments, Natural class verdict,
                     minimal specification (or suggested
                     completions when the verdict is "No")
        right (50%): Shared features, Contrasting features

    Falls back to a single full-width column for the universal
    class (whole inventory selected): the left side reduces to a
    one-line "Natural class: Yes" plus an "∅ universal" badge and
    would leave the right side towering over an almost-empty left.
    """
    seg_tags = " ".join(_segment_chip(seg) for seg in segs)
    is_nc, specs = engine.is_natural_class(segs)
    is_universal = is_nc and (not specs or not specs[0])
    nc_html, spec_html = _render_natural_class_verdict(engine, segs, suggested)
    common_html = _render_shared_features(common)
    contrast_html = _render_contrast_section(engine, segs, contrastive)
    selected_html = f"<p><b>Selected:</b> {seg_tags}</p>"
    if is_universal:
        return f"{selected_html}{nc_html}{spec_html}{common_html}{contrast_html}"
    return (
        "<table width='100%' cellpadding='0' cellspacing='0'>"
        "<tr>"
        "<td width='50%' style='vertical-align:top; padding-right:18px;'>"
        f"{selected_html}{nc_html}{spec_html}"
        "</td>"
        "<td width='50%' style='vertical-align:top;'>"
        f"{common_html}{contrast_html}"
        "</td>"
        "</tr></table>"
    )


def render_feat_to_seg(
    engine: FeatureEngine,
    feature_dict: dict[str, str],
    matching: list[str],
) -> str:
    """Build HTML for a feature-to-segment query result. ``engine`` is
    kept in the signature even though this renderer doesn't query it
    directly; future extensions (e.g. showing the spec's effect on
    contrast) would need it and rewiring callers later is more work
    than carrying a known-good handle now."""
    del engine  # currently unused; see docstring
    feat_tags = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(feature_dict).items()
    )
    if matching:
        seg_tags = " ".join(_segment_chip(seg) for seg in matching)
        n = len(matching)
        segs_html = (
            f"<p><b>Matching {_plural(n, 'segment')} ({n}):</b>"
            f"<br>{seg_tags}</p>"
        )
    else:
        segs_html = (
            f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
        )
    return f"<p><b>Query:</b> {feat_tags}</p>{segs_html}"


# ---------------------------------------------------------------------------
# Helpers for render_multi_segment (kept here so the top-level renderer
# reads as a sequence of intent rather than four screens of f-strings).
# ---------------------------------------------------------------------------
def _render_shared_features(common: dict[str, str]) -> str:
    if not common:
        return f"<p><b>Shared features:</b> {_muted_italic_span('none')}</p>"
    chips = " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(common).items()
    )
    return f"<p><b>Shared features:</b><br>{chips}</p>"


def _render_contrast_section(
    engine: FeatureEngine,
    segs: list[str],
    contrastive: dict[str, dict[str, list[str]]],
) -> str:
    if contrastive:
        # Rendered as an HTML table so feature names left-align in a
        # fixed column and the ``+`` / ``−`` / ``0`` buckets line up
        # vertically across every row. The previous inline-flow shape
        # put feature names of different lengths on the same baseline
        # as the bucket glyphs, so the eye had to re-scan from the
        # left edge for each feature -- the user's "hard to parse"
        # complaint. Table columns make vertical scanning trivial.
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
    # No contrastive features. Distinguish "actually identical" from
    # "only differ in unspecified features"; the latter is a common
    # source of confusion ("why do these look the same?").
    has_underspec_diff = any(
        len({engine.segments[seg].get(feat, "0") for seg in segs}) > 1
        and "0" in {engine.segments[seg].get(feat, "0") for seg in segs}
        for feat in engine.features
    )
    reason = (
        "none (only unspecified features differ)"
        if has_underspec_diff
        else "none (featurally identical)"
    )
    return f"<p><b>Contrasting features:</b> {_muted_italic_span(reason)}</p>"


# ---------------------------------------------------------------------------
# Cell-style constants for the contrastive-features table.
# Pre-built so the per-row helper isn't reconstructing identical CSS
# strings for every feature; also keeps geometry editable in one place.
# ---------------------------------------------------------------------------
_CONTRAST_CELL_BASE: str = "vertical-align:top; padding-right:14px;"
_CONTRAST_NAME_CELL: str = _CONTRAST_CELL_BASE + " white-space:nowrap;"


def _render_contrast_row(feat: str, groups: dict[str, list[str]]) -> str:
    """One ``<tr>`` for the contrastive-features table. Columns:

        | feature | + segments | − segments | (0 segments, only when present) |

    The ``0`` cell is omitted entirely when the row has no
    underspecified segments. An empty ``<td>`` would still occupy a
    selectable area on screen (and contribute a stray tab on copy),
    which surfaced as "selection highlights an empty third column".
    Omitting the cell removes both the phantom highlight and the
    extra tab; rows that DO have ``0`` data simply extend one column
    further to the right.
    """
    # Plain bold for the feature name. The chip background was
    # redundant once the table column provided visual separation, and
    # the pale gray on near-white panel had almost no contrast in
    # light mode -- the name was effectively unstyled either way.
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
        f"<td style='{_CONTRAST_CELL_BASE}'>{plus_glyph} {plus_chips}</td>",
        f"<td style='{_CONTRAST_CELL_BASE}'>{minus_glyph} {minus_chips}</td>",
    ]
    if "0" in groups:
        zero_chips = " ".join(
            _segment_chip(seg, TagColor.NEUTRAL) for seg in groups["0"]
        )
        zero_glyph = f"<span style='color:{C['text_dim']}'>0</span>"
        cells.append(
            f"<td style='{_CONTRAST_CELL_BASE}'>"
            f"{zero_glyph} {zero_chips}</td>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


def _render_natural_class_verdict(
    engine: FeatureEngine, segs: list[str], suggested: list[str]
) -> tuple[str, str]:
    """Returns ``(verdict_html, spec_html)``. ``spec_html`` is empty
    when the answer is "No" since there's no minimal bundle to show."""
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
            f" add {n} {_plural(n, 'segment')} to complete:"
            f"<br>{suggested_tags}</p>"
        )
    else:
        verdict = f"<p><b>Natural class:</b> {_yes_no(False)}</p>"
    return verdict, ""
