"""Tests for :py:mod:`phonology_shared.render.view_models`.

The module is pure-Python and is relayed into the web bundle, so
these tests lock in the shared payload shapes without needing Qt or
Pyodide.
"""

from __future__ import annotations

import json
from pathlib import Path

from phonology_shared.engine.feature_engine import FeatureEngine
from phonology_shared.engine.inventory import Inventory
from phonology_shared.render.view_models import (
    build_inventory_summary,
    summarize_feature_query,
    summarize_segment_selection,
)

INVENTORIES_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)


def _engine(name: str) -> FeatureEngine:
    import pytest

    path = INVENTORIES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present (gitignored in CI)")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def test_build_inventory_summary_groups_colliding_vowels() -> None:
    engine = _engine("general_features.json")
    summary = build_inventory_summary(engine, "General")
    target = next(
        cell
        for cell in summary["vowel_chart"]["cells"]
        if cell["row"] == 3 and cell["col"] == 2
    )
    assert set(target["segs"]) == {"ə", "ɜ"}


def test_summarize_segment_selection_single_maps_zero_to_empty() -> None:
    engine = _engine("hayes_features.json")
    summary = summarize_segment_selection(engine, ["b"])
    assert summary["selected"] == ["b"]
    assert summary["suggested"] == []
    assert summary["contrastive"] == []
    assert summary["common"]["Voice"] == "+"
    assert summary["common"]["Back"] == ""
    assert "/b/" in summary["analysis_html"]
    assert summary["segment_states"]["b"] == "selected"
    assert summary["segment_states"]["d"] == "default"
    assert summary["feature_rows"]["Voice"]["value"] == "+"
    assert summary["feature_rows"]["Voice"]["shared"] is True
    assert summary["feature_rows"]["Back"]["value"] == ""
    assert summary["feature_rows"]["Back"]["shared"] is False


def test_summarize_segment_selection_multi_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    summary = summarize_segment_selection(engine, segs)
    assert summary["selected"] == segs
    assert summary["common"]["Voice"] == "+"
    assert "LABIAL" in summary["contrastive"]
    # Under strict natural-class semantics, ``suggested`` is the
    # smallest set of segments whose addition makes the union a
    # strict natural class -- i.e. a class for which some feature
    # bundle round-trips exactly via ``find_segments``. For
    # /b/ /d/ /ɡ/ in Hayes the union with the suggestion must be
    # a strict natural class. Pin the size > 0 condition and the
    # round-trip invariant rather than the specific completion,
    # since multiple equivalent completions may exist.
    suggested = summary["suggested"]
    assert isinstance(suggested, list)
    assert suggested, (
        f"/b d ɡ/ is not a strict natural class on its own; a"
        f" non-empty completion should be suggested, got {suggested!r}"
    )
    # Closure: adding the suggestion to the selection must produce
    # a strict natural class. This is the round-trip invariant the
    # whole engine semantics rests on.
    is_nc, bundles = engine.is_natural_class(segs + suggested)
    assert is_nc, (
        f"engine.suggest_natural_class_extension({segs}) returned "
        f"{suggested}, but {segs + suggested} is not a natural class"
    )
    # Strict round-trip: every returned bundle returns exactly the
    # union of selection + suggestion under default-strict
    # ``find_segments``.
    for b in bundles:
        recovered = engine.find_segments(dict(b))
        assert sorted(recovered) == sorted(segs + suggested), (
            f"bundle {dict(b)} does not strictly round-trip: "
            f"got {recovered}, expected {sorted(segs + suggested)}"
        )
    # Selection itself is never in the suggested list.
    assert not set(segs) & set(suggested)
    assert summary["segment_states"]["b"] == "selected"
    assert summary["feature_rows"]["Voice"]["value"] == "+"
    assert summary["feature_rows"]["Voice"]["shared"] is True
    assert summary["feature_rows"]["LABIAL"]["contrastive"] is True
    assert summary["feature_rows"]["LABIAL"]["badge"] == "±"


def test_feature_categories_for_english_j_i_capital_ɪ() -> None:
    """User-reported scenario, pinned: selecting /j/ /i/ /ɪ/ in
    English. Tense's values across the selection are ``+`` (/i/),
    ``-`` (/ɪ/), and ``'0'`` (/j/) -- the canonical
    ``UNDERSPEC_CONFLICT`` case. Front and High are both ``+`` on
    all three -- ``ALL_PLUS``. The feature-row state surfaces the
    category so renderers can show
    underspec-conflict distinctly from explicit-conflict.
    """
    engine = _engine("english_features.json")
    summary = summarize_segment_selection(engine, ["j", "i", "ɪ"])
    # Tense: +, -, 0 across the three -> UNDERSPEC_CONFLICT
    tense = summary["feature_rows"]["Tense"]
    assert tense["category"] == "underspec_conflict"
    assert tense["contrastive"] is True
    assert tense["shared"] is False
    # Front: all three are + -> ALL_PLUS
    front = summary["feature_rows"]["Front"]
    assert front["category"] == "all_plus"
    assert front["shared"] is True
    # High: all three are + -> ALL_PLUS
    assert summary["feature_rows"]["High"]["category"] == "all_plus"
    # /j i ɪ/ is a STRICT natural class via the {Front:+, High:+}
    # bundle (the only features categorically ALL_PLUS that are
    # also discriminating). Round-trip via strict find_segments.
    is_nc, bundles = engine.is_natural_class(["j", "i", "ɪ"])
    assert is_nc
    assert bundles
    for b in bundles:
        assert sorted(engine.find_segments(dict(b))) == sorted(["j", "i", "ɪ"])


def test_feature_row_badge_uses_unicode_minus_for_shared_negative() -> None:
    """A feature shared as ``-`` across the selection must surface in
    the row's ``badge`` as U+2212 (MINUS SIGN), not ASCII U+002D
    (HYPHEN-MINUS). The web frontend renders the badge text via
    canvas rasterisation; the visible mate of the ``-`` polarity
    button (also U+2212) must use the same glyph so the two read as
    the same symbol. Desktop already does this translation inside
    ``FeatureRow.set_display``; the shared layer is the single
    source of truth so both UIs inherit it.
    """
    engine = _engine("hayes_features.json")
    # Pick a selection where some feature is shared-negative. /m/
    # /n/ are both [-Continuant], among many shared values.
    summary = summarize_segment_selection(engine, ["m", "n"])
    cont = summary["feature_rows"].get("Continuant")
    assert cont is not None, "Hayes inventory exposes a 'Continuant' feature"
    assert cont["value"] == "-"
    assert cont["shared"] is True
    assert cont["badge"] == "−"
    # Positive badges stay ASCII ``+`` (no display-only character).
    voice = summary["feature_rows"]["Voice"]
    assert voice["value"] == "+"
    assert voice["badge"] == "+"


def test_suggest_natural_class_blevins_affricate_strict_closure() -> None:
    """Pinning: under strict natural-class semantics,
    ``suggest_natural_class_extension([b͡v, d͡z, t͡s])`` returns
    a completion that, when added, makes the union a STRICT
    natural class -- i.e. some feature bundle strictly round-trips
    to it via the default ``find_segments``.

    Historical note: a previous version of the engine used
    wildcard (underspec-compatible) matching for both the natural-
    class verdict and the suggestion algorithm. Under that scheme
    /b͡v d͡z t͡s/ + /p͡f/ formed a wildcard natural class, so the
    suggestion was a single segment. Strict semantics requires
    every member of the union to have an explicit value on every
    bundle feature, so the completion includes more segments
    (typically the full strict-common matchers minus the
    selection). The trade is the round-trip invariant: the bundle
    the engine reports for the completed set, when typed into
    feat→seg, returns exactly that set.

    Skipped in CI when ``blevins_features.json`` is gitignored.
    """
    import pytest

    blevins_path = INVENTORIES_DIR / "blevins_features.json"
    if not blevins_path.exists():
        pytest.skip("blevins_features.json not present (gitignored in CI)")
    engine = _engine("blevins_features.json")
    selected = ["b͡v", "d͡z", "t͡s"]
    assert all(s in engine.segments for s in selected)
    # /b͡v d͡z t͡s/ is not a STRICT natural class on its own (some
    # member has '0' on a discriminating feature).
    assert not engine.is_natural_class(selected)[0]
    suggested = engine.suggest_natural_class_extension(selected)
    assert suggested, "expected a non-empty completion"
    # Closure: the union forms a STRICT natural class and every
    # returned bundle round-trips exactly via find_segments.
    is_nc, bundles = engine.is_natural_class(selected + suggested)
    assert is_nc
    assert bundles
    for b in bundles:
        recovered = engine.find_segments(dict(b))
        assert sorted(recovered) == sorted(selected + suggested), (
            f"bundle {dict(b)} does not strictly round-trip: "
            f"got {recovered}"
        )
    # Selection itself is never in the suggestion.
    assert not set(selected) & set(suggested)


def test_summarize_feature_query_always_returns_find_segments() -> None:
    """**FEAT-mode display invariant**: the matches returned by
    ``summarize_feature_query`` are always exactly
    ``engine.find_segments(spec)`` -- the strict matches of the
    active query. The set returned therefore always forms a
    strict natural class characterised by the query itself.

    The SEG→FEAT seg-selection round-trip is preserved by
    ``mode_logic.project_mode_transition`` (origin flag +
    saved-seg-state restore on FEAT→SEG return), NOT by altering
    the FEAT-mode matches. An earlier "projected_segments"
    override violated this invariant on non-natural-class seg
    selections (e.g. SEG /j i/ → FEAT showed /j i/ highlighted
    even though /j i/ are not a natural class) and is no longer
    permitted.
    """
    engine = _engine("english_features.json")
    # Projection from a non-natural-class seg selection: the
    # FEAT query strictly matches a superset, and the highlighted
    # segments in FEAT mode must reflect that superset, not the
    # original seg selection.
    spec = engine.project_segments_to_features(["j", "i"])
    strict_match = engine.find_segments(spec)
    assert "ɪ" in strict_match
    summary = summarize_feature_query(engine, spec)
    assert summary["matching"] == strict_match
    assert summary["segment_states"]["j"] == "matched"
    assert summary["segment_states"]["i"] == "matched"
    assert summary["segment_states"]["ɪ"] == "matched"


def test_summarize_feature_query_matches_engine() -> None:
    engine = _engine("hayes_features.json")
    spec = {"Voice": "+"}
    summary = summarize_feature_query(engine, spec)
    # ``matching`` should contain canonical voiced segments and
    # exclude canonical voiceless ones. Membership-style assertions
    # so the test fails if the engine's filter inverts, rather than
    # silently matching whatever ``find_segments`` returns now.
    matching = summary["matching"]
    assert isinstance(matching, list)
    for seg in ("b", "d", "ɡ", "v", "z"):
        assert seg in matching, f"voiced /{seg}/ should match +Voice"
    for seg in ("p", "t", "k", "f", "s"):
        assert seg not in matching, f"voiceless /{seg}/ should not match"
    assert "+Voice" in summary["analysis_html"]
    assert summary["segment_states"]["b"] == "matched"
    assert summary["segment_states"]["p"] == "unmatched"


# ---------------------------------------------------------------------------
# analysis_tabs payload: shared contract between the desktop's
# ``AnalysisPanel.set_sections`` and the web's ``setAnalysisTabs``.
# Both consume the same keys; these tests pin the keys + invariants
# so a rename / drop on either side breaks the build here, not later
# at runtime in one UI but not the other.
# ---------------------------------------------------------------------------


def _assert_tabs_shape(tabs: dict[str, object]) -> None:
    for key in ("selection", "class", "features", "contrasts"):
        assert key in tabs, f"missing tab key: {key}"
        assert isinstance(tabs[key], str)
    assert "contrasts_enabled" in tabs
    assert isinstance(tabs["contrasts_enabled"], bool)


def test_analysis_tabs_seg_single_keeps_contrasts_enabled() -> None:
    """Tab enable/disable is MODE-driven, not selection-driven. SEG
    mode keeps Contrasts clickable regardless of selection count;
    the tab body carries a 'select two or more segments' hint when
    the user lands there with fewer than two segments. The Class
    tab stays NEUTRAL (white) since a single segment is trivially
    a natural class of itself."""
    engine = _engine("hayes_features.json")
    tabs = summarize_segment_selection(engine, ["b"])["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is True
    assert tabs["class_state"] == "neutral"
    # Class tab carries the natural-class verdict / specs.
    assert "+Voice" in tabs["features"]
    # Selection header has the chip for /b/.
    assert "/b/" in tabs["selection"]


def test_analysis_tabs_seg_multi_natural_class() -> None:
    """Multi-segment SEG selection that IS a natural class: tab
    state goes ``"natural"`` so the UI paints the Class tab green.
    Picking every voiced obstruent in Hayes — voiced stops + voiced
    fricatives — yields a real natural class definable by the
    feature ``+Voice``."""
    engine = _engine("hayes_features.json")
    voiced = engine.find_segments({"Voice": "+"})
    tabs = summarize_segment_selection(engine, voiced)["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["class_state"] == "natural"


def test_analysis_tabs_seg_multi_enables_contrasts() -> None:
    """Multi-segment SEG: contrasting features go in the Contrasts
    tab; the flag is on. /b/ /d/ /ɡ/ aren't a natural class on
    their own in Hayes (the other voiced stops would need to be in
    the selection too), so ``class_state == "not_natural"``."""
    engine = _engine("hayes_features.json")
    segs = ["b", "d", "ɡ"]
    tabs = summarize_segment_selection(engine, segs)["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is True
    assert tabs["class_state"] == "not_natural"
    assert "Contrasting features" in tabs["contrasts"]


def test_analysis_tabs_feat_disables_contrasts() -> None:
    """FEAT mode: contrasts aren't meaningful for a feature query,
    so the flag stays off regardless of how many matches there are.
    """
    engine = _engine("hayes_features.json")
    tabs = summarize_feature_query(engine, {"Voice": "+"})["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is False
    assert tabs["class_state"] == "neutral"
    # The Class tab is where matching segments land in FEAT mode.
    assert "Matching" in tabs["class"]


def test_analysis_tabs_empty_selection_safe_shape() -> None:
    """Empty SEG selection still produces a well-formed payload, so
    the UI can call setSections without checking for nulls. The
    selection-strip stays hidden (empty ``selection``) and the Class
    cue is neutral; the tab bodies now carry short next-step hints
    instead of empty strings so the user isn't staring at blank
    tabs wondering whether the app is alive."""
    engine = _engine("hayes_features.json")
    tabs = summarize_segment_selection(engine, [])["analysis_tabs"]
    _assert_tabs_shape(tabs)
    assert tabs["contrasts_enabled"] is True
    assert tabs["class_state"] == "neutral"
    assert tabs["selection"] == ""
    assert "Click a segment" in tabs["class"]
    assert "Click a segment" in tabs["features"]
    assert "Select" in tabs["contrasts"]


def test_segment_state_payload_strings_match_enum() -> None:
    """The desktop coerces ``segment_states`` strings into the
    ``SegmentState`` StrEnum via ``SegmentState(state)``. If the enum
    drifts from the strings produced here, the desktop silently raises
    ``ValueError`` on every paint. Pin every payload string at the
    enum so a rename surfaces here, not in the UI.
    """
    from phonology_features.gui.widgets import SegmentState

    enum_values = {member.value for member in SegmentState}
    assert {"default", "selected", "suggested", "matched", "unmatched"} <= (
        enum_values
    )

    engine = _engine("hayes_features.json")
    seg_list = list(engine.segments)
    seen: set[str] = set()
    seen.update(
        summarize_segment_selection(engine, [])["segment_states"].values()
    )
    seen.update(
        summarize_segment_selection(engine, seg_list[:1])[
            "segment_states"
        ].values()
    )
    seen.update(
        summarize_segment_selection(engine, seg_list[:3])[
            "segment_states"
        ].values()
    )
    seen.update(summarize_feature_query(engine, {})["segment_states"].values())
    seen.update(
        summarize_feature_query(engine, {"Voice": "+"})[
            "segment_states"
        ].values()
    )
    assert seen <= enum_values, f"Unknown segment states: {seen - enum_values}"
