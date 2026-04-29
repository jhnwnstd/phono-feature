"""
gui/analysis.py
Analysis HTML rendering: builds the HTML shown in the AnalysisPanel.

All functions return HTML strings.  They are pure of GUI state — they take
engine data (segments, features, specs) and produce markup.
"""

from gui.constants import TAG_PALETTES, sort_features, sort_spec
from gui.palette import C

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def tag(text: str, colour: str) -> str:
    """Render a coloured inline chip."""
    bg, fg = TAG_PALETTES.get(colour, (C["tag_gray"], C["tag_gray_text"]))
    return (
        f"<span style='"
        f"background:{bg}; color:{fg}; border-radius:4px;"
        f" padding:2px 7px; margin:2px; font-family:monospace;"
        f" font-size:10pt;'>{text}</span>"
    )


def render_spec_list(specs: list) -> str:
    """Render a deduplicated list of minimal specifications as HTML.

    Underspecified features (value "0") are hidden from display;
    specs that become identical after filtering are collapsed.
    """
    seen: set = set()
    rows: list = []
    for spec in specs:
        filtered = {f: v for f, v in sort_spec(spec).items() if v != "0"}
        if not filtered:
            continue
        key = tuple(sorted(filtered.items()))
        if key in seen:
            continue
        seen.add(key)
        row_tags = " ".join(
            tag(f"{v}{f}", "green" if v == "+" else "red") for f, v in filtered.items()
        )
        rows.append(
            f"<span style='color:{C['text_dim']}'>{len(rows) + 1}.</span> {row_tags}"
        )
    if not rows:
        return ""
    if len(rows) == 1:
        content = rows[0].split("</span> ", 1)[1]
        return f"<p><b>Minimal specification:</b><br>{content}</p>"
    return (
        f"<p><b>Minimal specifications ({len(rows)}):</b><br>"
        + "<br>".join(rows)
        + "</p>"
    )


# ---------------------------------------------------------------------------
# Contrastive feature computation
# ---------------------------------------------------------------------------


def compute_contrastive(engine, segs: list) -> dict:
    """
    Return {feature: {'+': [segs...], '-': [segs...], '0': [segs...]}}
    for every feature where at least one segment is '+' and at least one
    is '-'.  Segments with '0' (inapplicable / unspecified) are tracked
    separately so the display can account for all selected segments.
    """
    result = {}
    for feat in engine.features:
        plus_segs = [s for s in segs if engine.segments[s].get(feat, "0") == "+"]
        minus_segs = [s for s in segs if engine.segments[s].get(feat, "0") == "-"]
        if plus_segs and minus_segs:
            zero_segs = [s for s in segs if engine.segments[s].get(feat, "0") == "0"]
            entry: dict = {"+": plus_segs, "-": minus_segs}
            if zero_segs:
                entry["0"] = zero_segs
            result[feat] = entry
    return result


# ---------------------------------------------------------------------------
# Single-segment analysis
# ---------------------------------------------------------------------------


def render_single_segment(engine, seg: str, feats: dict) -> str:
    """Build HTML for a single selected segment."""
    plus_feats = sort_features([f for f, v in feats.items() if v == "+"])
    minus_feats = sort_features([f for f, v in feats.items() if v == "-"])

    plus_tags = " ".join(tag(f"+{f}", "green") for f in plus_feats)
    minus_tags = " ".join(tag(f"\u2212{f}", "red") for f in minus_feats)

    html = (
        f"<p><b style='color:{C['text']}'>/{seg}/</b>"
        f" &nbsp;\u2014&nbsp; full feature bundle:</p>"
        f"<p>{plus_tags}</p>"
        f"<p>{minus_tags}</p>"
    )

    is_nc, specs = engine.is_natural_class([seg])
    if not is_nc:
        # Expand to equivalence class: all segments identical except
        # for underspecified features (e.g. ng -> {ng, ng+, ng-}).
        non_zero = {f: v for f, v in feats.items() if v != "0"}
        equiv = engine.find_segments(non_zero, underspec_compatible=True)
        if len(equiv) > 1:
            is_nc, specs = engine.is_natural_class(equiv)
    if is_nc and specs:
        html += render_spec_list(specs)
    else:
        html += (
            f"<p style='color:{C['text_dim']}'><i>"
            "Cannot be uniquely characterized in this inventory."
            "</i></p>"
        )

    return html


# ---------------------------------------------------------------------------
# Multi-segment analysis
# ---------------------------------------------------------------------------


def render_multi_segment(
    engine, segs: list, common: dict, contrastive: dict, suggested: list
) -> str:
    """Build HTML for multiple selected segments."""
    seg_tags = " ".join(tag(f"/{s}/", "blue") for s in segs)

    if common:
        c_tags = " ".join(
            tag(f"{v}{f}", "green" if v == "+" else "red")
            for f, v in sort_spec(common).items()
        )
        common_html = f"<p><b>Shared features:</b><br>{c_tags}</p>"
    else:
        common_html = (
            f"<p><b>Shared features:</b> <i style='color:{C['text_dim']}'>none</i></p>"
        )

    if contrastive:
        rows = []
        for feat in sort_features(list(contrastive)):
            groups = contrastive[feat]
            plus_segs = " ".join(tag(f"/{s}/", "blue") for s in groups["+"])
            minus_segs = " ".join(tag(f"/{s}/", "blue") for s in groups["-"])
            minus_sign = chr(8722)
            clr_plus = C["plus"]
            clr_minus = C["minus"]
            row_html = (
                f"{tag(feat, 'gray')}"
                f" <span style='color:{clr_plus};font-weight:bold'>+</span>"
                f" {plus_segs}"
                f" &nbsp;"
                f" <span style='color:{clr_minus};font-weight:bold'>{minus_sign}</span>"
                f" {minus_segs}"
            )
            if "0" in groups:
                zero_segs = " ".join(tag(f"/{s}/", "gray") for s in groups["0"])
                row_html += (
                    f" &nbsp; <span style='color:{C['text_dim']}'>0</span> {zero_segs}"
                )
            rows.append(row_html)
        contrast_html = (
            "<p><b>Contrasting features:</b><br>" + "<br>".join(rows) + "</p>"
        )
    else:
        # Check if segments differ only in underspecification (0 vs +/-)
        has_underspec_diff = False
        for feat in engine.features:
            vals = {engine.segments[s].get(feat, "0") for s in segs}
            if len(vals) > 1 and "0" in vals:
                has_underspec_diff = True
                break
        if has_underspec_diff:
            contrast_html = (
                f"<p><b>Contrasting features:</b>"
                f" <i style='color:{C['text_dim']}'>none \u2014 segments"
                " differ only in underspecification</i></p>"
            )
        else:
            contrast_html = (
                f"<p><b>Contrasting features:</b>"
                f" <i style='color:{C['text_dim']}'>none \u2014 segments"
                " are featurally identical</i></p>"
            )

    is_nc, specs = engine.is_natural_class(segs)
    spec_html = ""
    if is_nc:
        nc_html = (
            f"<p><b>Natural class:</b> <span style='color:{C['plus']}'>Yes</span></p>"
        )
        if not specs or not specs[0]:
            _univ = "\u2205 (universal \u2014 all segments)"
            spec_html = f"<p><b>Minimal specification:</b> {tag(_univ, 'gray')}</p>"
        else:
            spec_html = render_spec_list(specs)
    else:
        if suggested:
            sug_tags = " ".join(tag(f"/{s}/", "gray") for s in suggested)
            nc_html = (
                "<p><b>Natural class:</b>"
                f" <span style='color:{C['minus']}'>No</span>"
                f" \u2014 add {len(suggested)} segment"
                f"{'s' if len(suggested) != 1 else ''}"
                f" to complete the smallest shared-feature class:<br>{sug_tags}</p>"
            )
        else:
            nc_html = (
                "<p><b>Natural class:</b>"
                f" <span style='color:{C['minus']}'>No \u2014"
                " these segments cannot be uniquely picked out by any"
                " feature bundle in this inventory.</span></p>"
            )

    return (
        f"<p><b>Selected:</b> {seg_tags}</p>"
        f"{nc_html}{common_html}{spec_html}{contrast_html}"
    )


# ---------------------------------------------------------------------------
# Feature-to-segment query
# ---------------------------------------------------------------------------


def render_feat_to_seg(engine, feature_dict: dict, matching: list) -> str:
    """Build HTML for a feature-to-segment query result."""
    feat_tags = " ".join(
        tag(f"{v}{f}", "green" if v == "+" else "red")
        for f, v in sort_spec(feature_dict).items()
    )

    if matching:
        seg_tags = " ".join(tag(f"/{s}/", "blue") for s in matching)
        segs_html = f"<p><b>Matching segments ({len(matching)}):</b><br>{seg_tags}</p>"
    else:
        segs_html = (
            "<p><b>Matching segments:</b>"
            f" <i style='color:{C['text_dim']}'>none \u2014 no segment"
            " satisfies all selected features.</i></p>"
        )

    return f"<p><b>Query:</b> {feat_tags}</p>{segs_html}"
