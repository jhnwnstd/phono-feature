"""
gui/analysis.py

Analysis HTML rendering. Builds the HTML shown in the AnalysisPanel.

All functions return HTML strings. They are pure of GUI state. They take
engine data, segments, features, and specs, then produce markup.
"""

from gui.constants import TAG_PALETTES, sort_features, sort_spec
from gui.palette import C


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

    Underspecified features with value "0" are hidden from display.
    Specs that become identical after filtering are collapsed.
    """
    seen: set = set()
    rows: list = []

    for spec in specs:
        sorted_spec = sort_spec(spec)

        filtered = {
            feature: value
            for feature, value in sorted_spec.items()
            if value != "0"
        }

        if not filtered:
            continue

        key = tuple(sorted(filtered.items()))

        if key in seen:
            continue

        seen.add(key)

        row_tags = " ".join(
            tag(f"{value}{feature}", "green" if value == "+" else "red")
            for feature, value in filtered.items()
        )

        row_number = len(rows) + 1
        rows.append(
            f"<span style='color:{C['text_dim']}'>{row_number}.</span> {row_tags}"
        )

    if not rows:
        return ""

    if len(rows) == 1:
        _, content = rows[0].split("</span> ", 1)
        return f"<p><b>Minimal specification:</b><br>{content}</p>"

    return (
        f"<p><b>Minimal specifications ({len(rows)}):</b><br>"
        + "<br>".join(rows)
        + "</p>"
    )


def compute_contrastive(engine, segs: list) -> dict:
    """
    Return {feature: {'+': [segs...], '-': [segs...], '0': [segs...]}}
    for every feature where at least one segment is '+' and at least one
    segment is '-'.

    Segments with '0' are tracked separately so the display can account for
    all selected segments.
    """
    result = {}

    for feat in engine.features:
        plus_segs = [
            seg for seg in segs if engine.segments[seg].get(feat, "0") == "+"
        ]

        minus_segs = [
            seg for seg in segs if engine.segments[seg].get(feat, "0") == "-"
        ]

        feature_is_contrastive = plus_segs and minus_segs

        if not feature_is_contrastive:
            continue

        zero_segs = [
            seg for seg in segs if engine.segments[seg].get(feat, "0") == "0"
        ]

        entry: dict = {
            "+": plus_segs,
            "-": minus_segs,
        }

        if zero_segs:
            entry["0"] = zero_segs

        result[feat] = entry

    return result


def render_single_segment(engine, seg: str, feats: dict) -> str:
    """Build HTML for a single selected segment."""
    plus_feats = [feature for feature, value in feats.items() if value == "+"]

    minus_feats = [feature for feature, value in feats.items() if value == "-"]

    plus_feats = sort_features(plus_feats)
    minus_feats = sort_features(minus_feats)

    plus_tags = " ".join(tag(f"+{feature}", "green") for feature in plus_feats)

    minus_tags = " ".join(
        tag(f"\u2212{feature}", "red") for feature in minus_feats
    )

    html = (
        f"<p><b style='color:{C['text']}'>/{seg}/</b>"
        " feature bundle:</p>"
        f"<p>{plus_tags}</p>"
        f"<p>{minus_tags}</p>"
    )

    is_nc, specs = engine.is_natural_class([seg])

    if not is_nc:
        non_zero = {
            feature: value for feature, value in feats.items() if value != "0"
        }

        equiv = engine.find_segments(
            non_zero,
            underspec_compatible=True,
        )

        if len(equiv) > 1:
            is_nc, specs = engine.is_natural_class(equiv)

    if is_nc and specs:
        html += render_spec_list(specs)
    else:
        html += (
            f"<p style='color:{C['text_dim']}'><i>"
            "Not uniquely characterizable."
            "</i></p>"
        )

    return html


def render_multi_segment(
    engine,
    segs: list,
    common: dict,
    contrastive: dict,
    suggested: list,
) -> str:
    """Build HTML for multiple selected segments."""
    seg_tags = " ".join(tag(f"/{seg}/", "blue") for seg in segs)

    if common:
        sorted_common = sort_spec(common)

        common_tags = " ".join(
            tag(f"{value}{feature}", "green" if value == "+" else "red")
            for feature, value in sorted_common.items()
        )

        common_html = f"<p><b>Shared features:</b><br>{common_tags}</p>"
    else:
        common_html = f"<p><b>Shared features:</b> <i style='color:{C['text_dim']}'>none</i></p>"

    if contrastive:
        rows = []

        for feat in sort_features(list(contrastive)):
            groups = contrastive[feat]

            plus_segs = " ".join(
                tag(f"/{seg}/", "blue") for seg in groups["+"]
            )

            minus_segs = " ".join(
                tag(f"/{seg}/", "blue") for seg in groups["-"]
            )

            minus_sign = chr(8722)
            clr_plus = C["plus"]
            clr_minus = C["minus"]

            row_html = (
                f"{tag(feat, 'gray')}"
                f" <span style='color:{clr_plus};font-weight:bold'>+</span>"
                f" {plus_segs}"
                f" &nbsp;"
                f" <span style='color:{clr_minus};font-weight:bold'>"
                f"{minus_sign}</span>"
                f" {minus_segs}"
            )

            if "0" in groups:
                zero_segs = " ".join(
                    tag(f"/{seg}/", "gray") for seg in groups["0"]
                )

                row_html += f" &nbsp; <span style='color:{C['text_dim']}'>0</span> {zero_segs}"

            rows.append(row_html)

        contrast_html = (
            "<p><b>Contrasting features:</b><br>" + "<br>".join(rows) + "</p>"
        )

    else:
        has_underspec_diff = False

        for feat in engine.features:
            values = {engine.segments[seg].get(feat, "0") for seg in segs}

            values_are_mixed = len(values) > 1
            includes_underspec = "0" in values

            if values_are_mixed and includes_underspec:
                has_underspec_diff = True
                break

        if has_underspec_diff:
            contrast_html = (
                f"<p><b>Contrasting features:</b>"
                f" <i style='color:{C['text_dim']}'>none"
                " (only unspecified features differ)</i></p>"
            )
        else:
            contrast_html = (
                f"<p><b>Contrasting features:</b>"
                f" <i style='color:{C['text_dim']}'>none"
                " (featurally identical)</i></p>"
            )

    is_nc, specs = engine.is_natural_class(segs)
    spec_html = ""

    if is_nc:
        nc_html = f"<p><b>Natural class:</b> <span style='color:{C['plus']}'>Yes</span></p>"

        is_universal_class = not specs or not specs[0]

        if is_universal_class:
            universal_label = "\u2205 (universal)"
            spec_html = f"<p><b>Minimal specification:</b> {tag(universal_label, 'gray')}</p>"
        else:
            spec_html = render_spec_list(specs)

    else:
        if suggested:
            suggested_tags = " ".join(
                tag(f"/{seg}/", "gray") for seg in suggested
            )

            plural_suffix = "s" if len(suggested) != 1 else ""

            nc_html = (
                "<p><b>Natural class:</b>"
                f" <span style='color:{C['minus']}'>No</span>"
                f", add {len(suggested)} segment{plural_suffix} to complete:"
                f"<br>{suggested_tags}</p>"
            )
        else:
            # No suggestion available — match the terse "Yes" branch
            # rather than restating what "not a natural class" means.
            nc_html = (
                "<p><b>Natural class:</b>"
                f" <span style='color:{C['minus']}'>No</span>"
                "</p>"
            )

    return (
        f"<p><b>Selected:</b> {seg_tags}</p>"
        f"{nc_html}{common_html}{spec_html}{contrast_html}"
    )


def render_feat_to_seg(engine, feature_dict: dict, matching: list) -> str:
    """Build HTML for a feature-to-segment query result."""
    sorted_features = sort_spec(feature_dict)

    feat_tags = " ".join(
        tag(f"{value}{feature}", "green" if value == "+" else "red")
        for feature, value in sorted_features.items()
    )

    if matching:
        seg_tags = " ".join(tag(f"/{seg}/", "blue") for seg in matching)

        segs_html = (
            f"<p><b>Matching segments ({len(matching)}):</b><br>{seg_tags}</p>"
        )
    else:
        segs_html = (
            "<p><b>Matching segments:</b>"
            f" <i style='color:{C['text_dim']}'>none</i></p>"
        )

    return f"<p><b>Query:</b> {feat_tags}</p>{segs_html}"
