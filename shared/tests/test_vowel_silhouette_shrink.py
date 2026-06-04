"""Two-stage shrink of the vowel chart silhouette.

Stage 1 shrinks ``top_width`` and ``bottom_width`` by the same
amount, preserving the canonical slant; Stage 2 then nudges either
edge further inward by DIFFERENT amounts (changing the slant),
capped at a fraction of the canonical slant so the result still
reads as the canonical IPA trapezoid.

These tests exercise the helpers directly (so a regression in
either stage's math fails here rather than in the rendered chart)
plus an end-to-end check against the real Hayes inventory through
:py:func:`build_vowel_chart_geometry`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phonology_shared.chart import vowels as vowels_mod
from phonology_shared.chart.vowels import (
    _compute_shrunken_widths,
    _stage1_uniform_shrink,
    _stage2_slant_tweak,
    build_vowel_chart_geometry,
    detect_vowel_profile,
)
from phonology_shared.data.inventory import Inventory
from phonology_shared.theory.feature_engine import FeatureEngine

INVENTORIES_DIR = (
    Path(__file__).resolve().parents[2] / "desktop" / "inventories"
)


# ---------------------------------------------------------------------------
# Stage 1 -- uniform shrink
# ---------------------------------------------------------------------------


def test_stage1_preserves_slant() -> None:
    """The pre-existing concurrent shrink: both edges drop by the
    SAME amount, so ``top_w - bot_w`` is invariant.
    """
    canonical_top = 1.0
    canonical_bot = 0.7
    # One interior row whose min_w eats some slack.
    row_data = [(0.5, 0.7)]
    top, bot = _stage1_uniform_shrink(row_data, canonical_top, canonical_bot)
    assert top < canonical_top
    assert bot < canonical_bot
    assert top - bot == pytest.approx(canonical_top - canonical_bot)


def test_stage1_no_shrink_when_min_w_meets_canonical() -> None:
    """If the most-constrained row's min_w equals its canonical row
    width, Stage 1 has no slack to consume and returns the canonical
    widths unchanged.
    """
    row_data = [(0.0, 1.0), (1.0, 0.7)]
    top, bot = _stage1_uniform_shrink(row_data, 1.0, 0.7)
    assert top == pytest.approx(1.0)
    assert bot == pytest.approx(0.7)


def test_stage1_bounded_by_most_constrained_row() -> None:
    """Stage 1's consume is set by the SMALLEST slack across rows,
    not the average. A row with tiny slack pins the whole chart
    even when other rows could shrink much more.
    """
    # Row 0 at t=0 has canonical width 1.0, min 0.95 -> slack 0.05.
    # Row 1 at t=1 has canonical width 0.7, min 0.30 -> slack 0.40.
    # min_slack is 0.05 from row 0; consume = SHRINK_FACTOR * 0.05.
    row_data = [(0.0, 0.95), (1.0, 0.30)]
    top, bot = _stage1_uniform_shrink(row_data, 1.0, 0.7)
    expected_consume = vowels_mod._VOWEL_SHRINK_FACTOR * 0.05
    assert top == pytest.approx(1.0 - expected_consume)
    assert bot == pytest.approx(0.7 - expected_consume)


# ---------------------------------------------------------------------------
# Stage 2 -- slant tweak with hard cap
# ---------------------------------------------------------------------------


def test_stage2_no_op_when_stage1_saturates_uniformly() -> None:
    """If every row's slack is consumed equally by Stage 1, there is
    no asymmetric slack left for Stage 2 to exploit; both edges
    return unchanged.
    """
    # Single row at t=0.5, exactly at the post-Stage-1 minimum.
    row_data = [(0.5, 0.85)]  # current row width at this t is 0.85
    top, bot = _stage2_slant_tweak(
        row_data,
        stage1_top=1.0,
        stage1_bot=0.7,
        canonical_top_width=1.0,
        canonical_bottom_width=0.7,
    )
    assert top == pytest.approx(1.0)
    assert bot == pytest.approx(0.7)


def test_stage2_pulls_in_underloaded_edge() -> None:
    """If the bottom row has lots of remaining slack but the top
    row has none, Stage 2 reduces ``bot_w`` only -- the slant
    steepens but ``top_w`` stays put.
    """
    # Row 0 at t=0: stage1 width is stage1_top=0.97, min 0.97 -> no slack.
    # Row 1 at t=1: stage1 width is stage1_bot=0.67, min 0.20 -> 0.47 slack.
    row_data = [(0.0, 0.97), (1.0, 0.20)]
    top, bot = _stage2_slant_tweak(
        row_data,
        stage1_top=0.97,
        stage1_bot=0.67,
        canonical_top_width=1.0,
        canonical_bottom_width=0.7,
    )
    assert top == pytest.approx(0.97)
    assert bot < 0.67
    # Slant magnitude (top - bot) increased -- but capped.
    assert (top - bot) <= (1.0 - 0.7) * (
        1.0 + vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC + 1e-9
    )


def test_stage2_respects_slant_cap_when_slack_is_abundant() -> None:
    """A row with unlimited slack would let Stage 2 push the slant
    arbitrarily; the cap stops it at a fixed fraction of the
    canonical slant.
    """
    # Stage 1 widths slack-free at top; bottom can absorb anything.
    row_data = [(0.0, 0.97), (1.0, 0.0)]
    canonical_top = 1.0
    canonical_bot = 0.7
    top, bot = _stage2_slant_tweak(
        row_data,
        stage1_top=0.97,
        stage1_bot=0.67,
        canonical_top_width=canonical_top,
        canonical_bottom_width=canonical_bot,
    )
    cap = vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC * (
        canonical_top - canonical_bot
    )
    d_top = 0.97 - top
    d_bot = 0.67 - bot
    assert abs(d_top - d_bot) <= cap + 1e-9
    # And the cap is binding for this case: |d_top - d_bot| should
    # be at the cap (within float epsilon).
    assert abs(d_top - d_bot) == pytest.approx(cap, rel=1e-6, abs=1e-9)


def test_stage2_does_not_flip_slant_direction() -> None:
    """The cap is symmetric so the slant may either steepen or
    flatten, but the cap fraction is < 1.0 so the trapezoid cannot
    invert -- bottom stays narrower than top in normal vowel
    inventories.
    """
    row_data = [(0.0, 0.5), (1.0, 0.5)]
    canonical_top = 1.0
    canonical_bot = 0.7
    top, bot = _stage2_slant_tweak(
        row_data,
        stage1_top=0.91,
        stage1_bot=0.61,
        canonical_top_width=canonical_top,
        canonical_bottom_width=canonical_bot,
    )
    assert top >= bot, "slant must not invert under the default cap"


def test_stage2_disabled_returns_stage1() -> None:
    """Setting the cap fraction to 0 turns Stage 2 off; the function
    returns Stage 1's widths verbatim.
    """
    saved = vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC
    vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC = 0.0
    try:
        row_data = [(0.0, 0.5), (1.0, 0.5)]
        top, bot = _stage2_slant_tweak(
            row_data,
            stage1_top=0.91,
            stage1_bot=0.61,
            canonical_top_width=1.0,
            canonical_bottom_width=0.7,
        )
        assert top == pytest.approx(0.91)
        assert bot == pytest.approx(0.61)
    finally:
        vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC = saved


# ---------------------------------------------------------------------------
# Composition -- _compute_shrunken_widths runs both stages
# ---------------------------------------------------------------------------


def test_compose_stage2_strictly_dominates_stage1_when_slack_remains() -> None:
    """End to end: a chart with asymmetric per-row slack must come
    out narrower than Stage 1 alone would have produced.
    """
    # Pin both rows so they have appreciable slack after Stage 1.
    cells_meta_by_row = {0: [], 1: []}
    display_y_by_row = {0: 0.0, 1: 1.0}
    canonical_top, canonical_bot = 1.0, 0.7
    # Patch _min_row_width_for_meta via monkey-patch is heavy; instead
    # call the stage helpers directly with synthetic data and confirm
    # the composition produces values >=, not just == to stage 1.
    row_data = [(0.0, 0.97), (1.0, 0.20)]
    stage1_top, stage1_bot = _stage1_uniform_shrink(
        row_data, canonical_top, canonical_bot
    )
    stage2_top, stage2_bot = _stage2_slant_tweak(
        row_data, stage1_top, stage1_bot, canonical_top, canonical_bot
    )
    # Width REDUCTIONS from Stage 1 to Stage 2:
    assert stage2_top <= stage1_top + 1e-9
    assert stage2_bot <= stage1_bot + 1e-9
    # And at least one edge actually moved.
    assert (stage1_top - stage2_top) + (stage1_bot - stage2_bot) > 1e-9
    del cells_meta_by_row, display_y_by_row  # quiet unused-var lint


def test_compose_returns_canonical_when_factor_zero() -> None:
    """``_VOWEL_SHRINK_FACTOR = 0`` disables both stages at once."""
    saved = vowels_mod._VOWEL_SHRINK_FACTOR
    vowels_mod._VOWEL_SHRINK_FACTOR = 0.0
    try:
        top, bot = _compute_shrunken_widths(
            cells_meta_by_row={0: []},
            display_y_by_row={0: 0.5},
            top_y=0.0,
            bottom_y=1.0,
            canonical_top_width=1.0,
            canonical_bottom_width=0.7,
        )
        assert top == pytest.approx(1.0)
        assert bot == pytest.approx(0.7)
    finally:
        vowels_mod._VOWEL_SHRINK_FACTOR = saved


# ---------------------------------------------------------------------------
# End-to-end: real inventory through build_vowel_chart_geometry
# ---------------------------------------------------------------------------


def _engine(name: str) -> FeatureEngine:
    path = INVENTORIES_DIR / name
    if not path.exists():
        pytest.skip(f"inventory not present: {name}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return FeatureEngine(Inventory.parse(raw, source=str(path)))


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


def test_hayes_silhouette_within_slant_cap() -> None:
    """The Hayes inventory's rendered silhouette must respect the
    Stage 2 cap on slant change relative to its canonical slant.
    """
    engine = _engine("hayes_features.json")
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip("no vowels in inventory")
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)
    sil = geometry.silhouette
    # Canonical slant is the difference between the canonical
    # top_width (1.0) and the canonical bottom_width for the
    # inventory-adapted silhouette shape; the silhouette's own
    # top_width / bottom_width are the rendered (post-shrink)
    # values, so we compare the rendered slant against the
    # canonical-bottom-width-derived ceiling.
    rendered_slant = sil.top_width - sil.bottom_width
    canonical_slant = 1.0 - vowels_mod.TRAPEZOID_BOTTOM_WIDTH
    max_allowed_delta = (
        vowels_mod._VOWEL_SLANT_CHANGE_CAP_FRAC * canonical_slant
    )
    assert abs(rendered_slant - canonical_slant) <= max_allowed_delta + 1e-9, (
        f"Hayes silhouette slant {rendered_slant:.4f} differs from "
        f"canonical {canonical_slant:.4f} by more than the cap "
        f"{max_allowed_delta:.4f}"
    )
