"""HTML rendering for the AnalysisPanel. Returns HTML strings and
holds no GUI state. Every interpolation of inventory-provided text in
this module goes through ``html.escape``, so segment symbols and
feature names are escaped at each interpolation site here.
"""

from __future__ import annotations

import functools
import html
from collections import Counter
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
from phonology_shared.presentation.feature_metadata import feature_sort_key
from phonology_shared.presentation.layout import ANALYSIS_MIN_VISIBLE_ROWS
from phonology_shared.presentation.mode_logic import VALIDATION_REPORT_HEADING
from phonology_shared.presentation.palette import C

if TYPE_CHECKING:
    from phonology_shared.theory.feature_engine import (
        FeatureEngine,
        MatchMode,
        NaturalClassCompletion,
    )

# Imported eagerly (not under TYPE_CHECKING) because the renderer
# branches on it at runtime to pick wildcard vs. strict labels.
from phonology_shared.theory.feature_engine import (  # noqa: E402
    MatchMode as _MatchMode,
)

# --- chip + paragraph primitives ---------------------------------


@functools.lru_cache(maxsize=2048)
def _tag_cached(text: str, colour: TagColor, _version: int) -> str:
    """Memoised inner body of :py:func:`_tag`. The ``_version`` arg
    is the palette ``theme_version``, threaded through so a theme
    toggle invalidates the cache. Working set is bounded (about 300
    entries per inventory, segments times two colours plus features
    times two signs), so maxsize=2048 covers the worst PHOIBLE
    inventory plus headroom."""
    return f"{tag_prefix(colour)}{html.escape(text)}</span>"


def _tag(text: str, colour: TagColor) -> str:
    """Render a coloured inline chip. ``text`` is escaped here.

    ``white-space: nowrap`` keeps the chip atomic, since browsers
    treat ``/`` as a soft break point (the same heuristic that lets
    long URLs wrap), so without nowrap a chip like ``/ɪ/`` can end up
    split across lines with ``/`` on one line and ``ɪ/`` on the next.
    """
    return _tag_cached(text, colour, _palette.theme_version)


def _segment_chip(seg: str, colour: TagColor = TagColor.SEGMENT) -> str:
    """Render a segment symbol as a chip wrapped in slashes."""
    return _tag(f"/{seg}/", colour)


def _segment_chip_strip(
    segs: Sequence[str], colour: TagColor = TagColor.SEGMENT
) -> str:
    """Render ``segs`` as a single space-joined chip strip. Passing a
    list rather than a generator to ``str.join`` lets it pre-size the
    result buffer and avoids generator overhead.
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


def _signed_feature_chip_strip(spec: Mapping[str, str]) -> str:
    """Render ``spec`` as one space-joined strip of signed feature
    chips, ordered by :py:func:`sort_spec`. The feature-side twin of
    :py:func:`_segment_chip_strip`. The minimal-spec editor uses a
    pre-filtered dict in its own order, so it does NOT route here.
    """
    return " ".join(
        _signed_feature_chip(value, feature)
        for feature, value in sort_spec(spec).items()
    )


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


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    """English pluralisation. ``_plural(1, "segment")`` returns
    "segment" and ``_plural(2, "segment")`` returns "segments"."""
    if n == 1:
        return singular
    return plural if plural is not None else singular + "s"


# --- spec-list rendering -----------------------------------------


_STRICT_SPEC_LABEL_SINGULAR = "Minimal specification"
_STRICT_SPEC_LABEL_PLURAL = "Minimal specifications"
# Wildcard bundles are minimal COMPATIBILITY specifications, not
# minimal strict specs, since they characterise the selection under
# wildcard matching (a plus f constraint excludes only explicit
# minus f). The distinct label keeps users from reading them as strict
# bundles that would round-trip in the feat pane's default mode.
_WILDCARD_SPEC_LABEL_SINGULAR = "Minimal compatible specification"
_WILDCARD_SPEC_LABEL_PLURAL = "Minimal compatible specifications"


def _spec_labels(mode: "MatchMode") -> tuple[str, str]:
    """Return ``(singular, plural)`` heading labels for a spec
    list rendered under ``mode``."""
    if mode is _MatchMode.WILDCARD:
        return _WILDCARD_SPEC_LABEL_SINGULAR, _WILDCARD_SPEC_LABEL_PLURAL
    return _STRICT_SPEC_LABEL_SINGULAR, _STRICT_SPEC_LABEL_PLURAL


# Spec-grid cell style. ``vertical-align:top`` plus a right-hand gap
# gives the columns air. ``white-space:nowrap`` keeps each minimal spec
# on one line so the column-major rows stay a uniform height (a wrapping
# spec would desync the grid and its row count). Mirrors the Contrasts
# table's cell conventions so both tables read the same in the Qt
# rich-text pane.
_SPEC_CELL_STYLE: str = (
    "vertical-align:top; padding-right:18px; white-space:nowrap;"
)

# Shared open tag for both analysis tables (spec grid + contrast grid)
# so the border geometry lives in one place and the two cannot drift.
_ANALYSIS_TABLE_OPEN: str = (
    "<table cellpadding='3' cellspacing='0'"
    " style='border-collapse:separate; border-spacing:0 2px;'>"
)


def _render_spec_table(
    chip_rows: Sequence[str], rows_per_column: int | None
) -> str:
    """Arrange numbered ``chip_rows`` into a column-major HTML table.

    Each ``<td>`` is one column holding up to ``rows_per_column`` specs
    stacked top to bottom, and the columns sit side by side. Entries
    fill down the first column before the next column starts, so
    ``1, 2, 3`` read top to bottom then left to right. Laying each
    column out as one multi-line cell rather than a grid of one-spec
    cells keeps the numbering intact on copy, since a table serializes
    cell by cell and yields the specs in column order.

    Rendered as a ``<table>`` rather than CSS multi-column so it lays
    out identically in the web ``<div>`` and the desktop Qt rich-text
    pane, which supports tables but not CSS ``columns``. When the
    columns are wider than the pane each surface scrolls horizontally
    on its own.
    """
    n = len(chip_rows)
    rows = (
        rows_per_column
        if rows_per_column and rows_per_column > 0
        else ANALYSIS_MIN_VISIBLE_ROWS
    )
    columns: list[str] = []
    for start in range(0, n, rows):
        items = [
            f"<span style='color:{C['text_dim']}'>{i + 1}.</span> "
            f"{chip_rows[i]}"
            for i in range(start, min(start + rows, n))
        ]
        columns.append(
            f"<td style='{_SPEC_CELL_STYLE}'>" + "<br>".join(items) + "</td>"
        )
    return _ANALYSIS_TABLE_OPEN + "<tr>" + "".join(columns) + "</tr></table>"


def _order_specs_for_scan(
    specs: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Order the features within each spec, and the specs themselves, so
    a MULTI-spec list scans easily top-to-bottom.

    A single spec keeps canonical feature order (there is nothing to
    align it against). With several specs, the values shared by the most
    specs lead each line, so the common core forms a stable left-aligned
    prefix and the distinguishing features trail on the right; the specs
    then sort by that shared-first sequence, so rows that share a long
    prefix sit next to each other. Ties fall back to canonical feature
    order (then value) for a deterministic result.

    Runs on the handful of already-computed spec dicts, so it adds no
    measurable cost and leaves the engine's bundle search untouched.
    """
    if len(specs) == 1:
        return [dict(sort_spec(specs[0]))]
    freq = Counter(item for spec in specs for item in spec.items())

    def chip_key(item: tuple[str, str]) -> tuple[int, int, str]:
        feature, value = item
        return (-freq[item], feature_sort_key(feature), value)

    ordered = [dict(sorted(spec.items(), key=chip_key)) for spec in specs]
    ordered.sort(key=lambda spec: [chip_key(item) for item in spec.items()])
    return ordered


def _render_spec_list(
    specs: Sequence[Mapping[str, str]],
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> str:
    """Render minimal feature specifications, numbered.

    Drops ``0`` values (under-specification is implicit), collapses
    rows that become identical after the drop, and omits the
    ``1.`` numbering when only one row remains. Returns ``""`` if
    nothing's left to show.

    A single surviving spec renders as one line in canonical feature
    order. Multiple specs are reordered by
    :py:func:`_order_specs_for_scan` (shared features lead each line,
    similar rows adjacent) and fill a COLUMN-MAJOR table (see
    :py:func:`_render_spec_table`) so the fixed-height pane uses its
    horizontal space before scrolling. ``rows_per_column`` is how many
    specs fit vertically before a column wraps. It defaults to
    :py:data:`ANALYSIS_MIN_VISIBLE_ROWS` (the pane's guaranteed-visible
    count) and each frontend passes the row count its own live pane fits.

    ``mode`` selects the heading label. Strict bundles read
    "Minimal specification" while wildcard bundles read "Minimal
    compatible specification" so the two flavours are visually distinct.
    """
    singular, plural = _spec_labels(mode)
    seen: set[tuple[tuple[str, str], ...]] = set()
    filtered_specs: list[dict[str, str]] = []
    for spec in specs:
        filtered = {
            feature: value for feature, value in spec.items() if value != "0"
        }
        if not filtered:
            continue
        key = tuple(sorted(filtered.items()))
        if key in seen:
            continue
        seen.add(key)
        filtered_specs.append(filtered)
    if not filtered_specs:
        return ""
    chip_rows = [
        " ".join(
            _signed_feature_chip(value, feature)
            for feature, value in spec.items()
        )
        for spec in _order_specs_for_scan(filtered_specs)
    ]
    if len(chip_rows) == 1:
        return f"<p><b>{singular}:</b></p>" f"<p>{chip_rows[0]}</p>"
    return f"<p><b>{plural} ({len(chip_rows)}):</b></p>" + _render_spec_table(
        chip_rows, rows_per_column
    )


# --- engine-side query helper ------------------------------------


def _render_completion_specs(
    bundles: Sequence[Mapping[str, str]],
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> str:
    """Render the minimal specs of a completion under ``mode``.

    Renders the universal-class line when the bundle is the empty
    bundle (the completed class is the entire inventory), otherwise
    dispatches to :py:func:`_render_spec_list` (which handles the
    mode-specific headings and the column-major layout).
    """
    singular, _ = _spec_labels(mode)
    if bundles and not bundles[0]:
        return (
            f"<p><b>{singular}:</b>"
            f" {_tag('∅ (universal)', TagColor.NEUTRAL)}</p>"
        )
    return _render_spec_list(
        bundles, mode=mode, rows_per_column=rows_per_column
    )


def _render_matching_segments(
    matching: Sequence[str],
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
) -> str:
    """HTML for the matching-segments answer of a feature query.

    Under strict matching the heading counts the matches. Underspecified
    matching adds a qualifier so the relaxed result reads as visually
    distinct from a strict match.
    """
    if not matching:
        return f"<p><b>Matching segments:</b> {_muted_italic_span('none')}</p>"
    n = len(matching)
    chips = _segment_chip_strip(matching)
    qualifier = (
        " (underspecified matching)" if mode is _MatchMode.WILDCARD else ""
    )
    return (
        f"<p><b>Matching {_plural(n, 'segment')} ({n}){qualifier}:</b></p>"
        f"<p>{chips}</p>"
    )


def render_validation_report(issues: Sequence[str]) -> str:
    """HTML for the validation-error banner shown on a failed
    inventory load. Single source of truth so the Class tab on
    web and the analysis pane on desktop produce identical markup
    (red heading plus one paragraph per issue). Every issue is
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
    the segments by membership in the engine's existential value sets,
    so a segment lists under '+' when some phase reaches ``[+feat]`` (a
    contour segment can list under BOTH polarities).

    Returns ``{feat: {'+': [...], '-': [...], '0': [...]}}``. The '0'
    bucket appears only when some segments are underspecified. Bucket
    order follows the caller's ``segs`` list so rendered chips align
    with selection order.

    Iterates ``engine.active_features`` (uniformly-zero features
    cannot be contrastive) and walks ``segs`` once per feature via
    direct lookup into the engine's per-feature segment sets, instead
    of the prior three comprehensions over ``segs`` per feature.
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


def _render_completion_body(
    completion: NaturalClassCompletion,
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> str:
    """Class-pane content for a single selection's completion under
    ``mode``.

    It handles two cases.

    * ``already_natural_class`` renders ``selected_minimal_bundles``,
      the minimal strict or compatible bundles per ``mode``.
    * ``one_minimal_completion`` / ``multiple_minimal_completions``
      render the "N segments needed for ..." line, explicitly naming
      underspecified matching when ``mode`` is wildcard.
    """
    if completion.status == "already_natural_class":
        return _render_completion_specs(
            completion.selected_minimal_bundles,
            mode=mode,
            rows_per_column=rows_per_column,
        )
    additions = completion.additions[0]
    n = len(additions)
    chips = _segment_chip_strip(additions, TagColor.NEUTRAL)
    if mode is _MatchMode.WILDCARD:
        return (
            f"<p><b>{n} {_plural(n, 'segment')} needed for a natural "
            f"class under underspecified matching:</b></p>"
            f"<p>{chips}</p>"
        )
    return (
        f"<p><b>{n} {_plural(n, 'segment')} needed for natural "
        f"class:</b></p>"
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
    chips = _signed_feature_chip_strip(common)
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
            + _ANALYSIS_TABLE_OPEN
            + body
            + "</table>"
        )

    # No contrastive features. Distinguish "actually identical" from
    # "only differ in unspecified features", since the latter is a
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


def _sign_glyph(value: str) -> str:
    """Coloured ``+`` or ``−`` marker glyph for a contrast cell. One
    home for the plus/minus colour decision shared by both cells."""
    if value == "+":
        return f"<span style='color:{C['plus']};font-weight:bold'>+</span>"
    return (
        f"<span style='color:{C['minus']};font-weight:bold'>"
        f"{MINUS_SIGN}</span>"
    )


def _render_contrast_row(feat: str, groups: dict[str, list[str]]) -> str:
    """One ``<tr>`` for the contrastive-features table.

    The columns are feature, plus segments, minus segments, and
    optionally zero segments when the row has underspecified data.
    Omitting the empty third column prevents a selectable empty cell
    from showing up as a phantom highlight.

    A non-breaking space sits between each +/-/0 glyph and its first
    chip so the marker cannot end up orphaned on its own line, while
    chip-to-chip gaps stay breakable.
    """
    name_html = f"<b>{html.escape(feat)}</b>"
    plus_chips = _segment_chip_strip(groups["+"])
    minus_chips = _segment_chip_strip(groups["-"])
    plus_glyph = _sign_glyph("+")
    minus_glyph = _sign_glyph("-")
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
# Per-tab renderers. One HTML string per analysis tab in the UI.
#
# The desktop's tabbed analysis panel and the web's tabbed layout
# consume these per-tab variants so each tab gets exactly its
# section. Both clients read the same Python output via
# ``view_models``, so the rendering stays in lockstep without a
# parallel JS implementation.
# ---------------------------------------------------------------------------


#: Maximum chip count rendered inline in the persistent selection
#: header. Past this, the header truncates and appends a muted
#: "+N more" indicator; the full selection stays available in the
#: per-tab content below. Keeps the header from bloating the analysis
#: pane on selections like General-IPA's "all 97 consonants", which
#: would otherwise wrap to many rows and push the tabs down.
SELECTION_HEADER_MAX_CHIPS: int = 24


def render_selection_summary_seg(segs: list[str]) -> str:
    """Persistent header content for SEG-mode selections.

    Returns ``"Selected (N): chip chip"``-style HTML that sits above
    the tabs and doesn't move when the user switches tabs. Empty
    selection returns the empty string, and the surrounding chrome
    then hides the strip entirely (desktop ``setVisible(False)`` /
    web ``hidden`` attribute) so it doesn't repeat the status bar.

    Beyond :py:data:`SELECTION_HEADER_MAX_CHIPS`, only the first N
    chips render inline with a muted ``"+M more"`` standing in for the
    rest. The full count stays in the header label so the user always
    sees how many segments are in play, and truncation governs only the
    chip rendering.
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


def _wildcard_badge() -> str:
    """Small inline badge prepended to wildcard Class-tab output so
    users see at a glance that the verdict applies under
    underspecified matching, not strict. Rendered as a coloured tag so
    it lines up with the other inline chips in the tab body."""
    return f"<p>{_tag('underspecified matching', TagColor.NEUTRAL)}</p>"


def _with_mode_badge(body: str, mode: "MatchMode") -> str:
    """Prefix ``body`` with the wildcard badge under wildcard mode, and
    return ``body`` unchanged under strict. One home for the badge rule
    shared by the SEG and FEAT Class tabs."""
    if mode is _MatchMode.WILDCARD:
        return _wildcard_badge() + body
    return body


def render_class_tab_seg(
    segs: list[str],
    completion: NaturalClassCompletion,
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
    rows_per_column: int | None = None,
) -> str:
    """Class tab content for SEG mode under ``mode``.

    Wildcard verdicts open with an ``underspecified matching`` badge
    so they are visually distinct from strict verdicts (which would
    otherwise render identical chip strips with subtly different
    semantics).

    ``rows_per_column`` is forwarded to the minimal-spec renderer so a
    long list of minimal specs fills the pane's height then wraps into
    columns, and each frontend passes the count its live pane fits.
    """
    if not segs:
        return _muted_italic_p("Click a segment to inspect it.")
    body = _render_completion_body(
        completion, mode=mode, rows_per_column=rows_per_column
    )
    return _with_mode_badge(body, mode)


def render_class_tab_feat(
    feature_dict: dict[str, str],
    matching: list[str],
    *,
    mode: "MatchMode" = _MatchMode.STRICT,
) -> str:
    """Class tab content for FEAT mode under ``mode``. It lists the
    matching segments (the result of the query) and their count.

    Wildcard FEAT-mode queries get the ``underspecified matching``
    badge for the same reason SEG-mode wildcard verdicts do, since the
    matching set differs in meaning even when it happens to coincide
    with the strict result.
    """
    if not feature_dict:
        return _muted_italic_p(
            "Set + or − on a feature to find matching segments."
        )
    body = _render_matching_segments(matching, mode=mode)
    return _with_mode_badge(body, mode)


def render_features_tab_seg(
    engine: FeatureEngine,
    segs: list[str],
    common: dict[str, str],
) -> str:
    """Features tab content for SEG mode. It shows the full feature
    bundle for a single segment, or the shared features (intersection)
    for a multi-segment selection.
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
    """Features tab content for FEAT mode. It shows the active query as
    chips plus the count. Lighter than the desktop's feature pane,
    which has the interactive +/− buttons, so this tab supports
    at-a-glance review of the current query.
    """
    if not feature_dict:
        return _muted_italic_p("No features set yet.")
    chips = _signed_feature_chip_strip(feature_dict)
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
    """Contrasts tab content for SEG mode. It gives a feature by
    feature breakdown of how the selection splits. It is only
    meaningful for multi-segment selections, and the under-two-segments
    case shows a short hint pointing the user at the next step.
    """
    if not segs:
        return _muted_italic_p("Select two or more segments to compare.")
    if len(segs) < 2:
        return _muted_italic_p("Select another segment to compare.")
    return _render_contrast_section(engine, segs, contrastive)


def render_contrasts_tab_feat() -> str:
    """Contrasts tab in FEAT mode is not meaningful, since the user is
    asking which segments match a feature spec, not how segments
    differ. Stable placeholder so the tab still exists and the user is
    not left wondering whether they broke something.
    """
    return _muted_italic_p("Switch to segment mode to compare segments.")
