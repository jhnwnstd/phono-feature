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

from collections.abc import Callable

import pytest

from phonology_shared.chart import vowels as vowels_mod
from phonology_shared.chart import vowels_layout as vowels_layout_mod
from phonology_shared.chart.vowels import (
    _compute_shrunken_widths,
    _stage1_uniform_shrink,
    _stage2_slant_tweak,
    build_vowel_chart_geometry,
    detect_vowel_profile,
)
from phonology_shared.theory.feature_engine import FeatureEngine

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


# ---------------------------------------------------------------------------
# Stage 2 -- slant tweak with hard cap
# ---------------------------------------------------------------------------


def test_stage2_disabled_by_default_for_silhouette_consistency() -> None:
    """Regression guard: ``_VOWEL_SLANT_CHANGE_CAP_FRAC`` MUST
    stay at ``0.0`` in production. Stage 2 (asymmetric slant
    tweak) was disabled after user feedback that the silhouette
    "felt different for every inventory" -- the cause was Stage
    2's per-inventory asymmetric reshaping of the canonical
    trapezoid. With the cap at 0, every inventory's silhouette
    is either the canonical Close-to-Open trapezoid (sparse) or
    a UNIFORMLY scaled copy of it (dense), preserving the IPA
    visual identity across the chart set.

    If Stage 2 is ever re-enabled, do it deliberately: bump this
    constant in chart_style/vowels_layout, update this test to
    document the new value + rationale, and visual-verify that
    the per-inventory slant variation is desired.
    """
    assert vowels_layout_mod._VOWEL_SLANT_CHANGE_CAP_FRAC == 0.0, (
        "Stage 2 slant tweak re-enabled! "
        "_VOWEL_SLANT_CHANGE_CAP_FRAC must stay 0.0 to keep the "
        "silhouette consistent across inventories. See the "
        "test docstring for the rationale."
    )


def test_stage2_disabled_returns_stage1() -> None:
    """Setting the cap fraction to 0 turns Stage 2 off; the function
    returns Stage 1's widths verbatim.
    """
    saved = vowels_layout_mod._VOWEL_SLANT_CHANGE_CAP_FRAC
    vowels_layout_mod._VOWEL_SLANT_CHANGE_CAP_FRAC = 0.0
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
        vowels_layout_mod._VOWEL_SLANT_CHANGE_CAP_FRAC = saved


# ---------------------------------------------------------------------------
# Composition -- _compute_shrunken_widths runs both stages
# ---------------------------------------------------------------------------


def test_compose_returns_canonical_when_factor_zero() -> None:
    """``_VOWEL_SHRINK_FACTOR = 0`` disables both stages at once."""
    saved = vowels_layout_mod._VOWEL_SHRINK_FACTOR
    vowels_layout_mod._VOWEL_SHRINK_FACTOR = 0.0
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
        vowels_layout_mod._VOWEL_SHRINK_FACTOR = saved


# ---------------------------------------------------------------------------
# End-to-end: real inventory through build_vowel_chart_geometry
# ---------------------------------------------------------------------------


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


def test_hayes_silhouette_within_slant_cap(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """The Hayes inventory's rendered silhouette must respect the
    Stage 2 cap on slant change relative to the canonical
    silhouette's own slant (computed via ``vowel_silhouette()`` so
    the test reflects the actual baseline, not a derived formula).
    With Stage 2 disabled (``_VOWEL_SLANT_CHANGE_CAP_FRAC = 0.0``)
    the cap is 0, so the test asserts the slant is EXACTLY
    canonical (within float epsilon). Stage 1's uniform shrink
    preserves the slant by construction.
    """
    engine = bundled_engine("hayes")
    vowels = _vowel_segs(engine)
    if not vowels:
        pytest.skip("no vowels in inventory")
    seg_feats = {s: dict(engine.segments[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)
    sil = geometry.silhouette
    rendered_slant = sil.top_width - sil.bottom_width
    canonical_sil = vowels_mod.vowel_silhouette(
        vowels_mod.VowelChartShape.TRAPEZOID
    )
    canonical_slant = canonical_sil.top_width - canonical_sil.bottom_width
    max_allowed_delta = (
        vowels_layout_mod._VOWEL_SLANT_CHANGE_CAP_FRAC * canonical_slant
    )
    assert abs(rendered_slant - canonical_slant) <= max_allowed_delta + 1e-9, (
        f"Hayes silhouette slant {rendered_slant:.4f} differs from "
        f"canonical {canonical_slant:.4f} by more than the cap "
        f"{max_allowed_delta:.4f}"
    )


def test_silhouette_slant_canonical_across_bundled_inventories(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """SILHOUETTE CONSISTENCY INVARIANT: with Stage 2 disabled
    (``_VOWEL_SLANT_CHANGE_CAP_FRAC = 0.0``) every bundled
    inventory's silhouette must preserve the canonical slant
    exactly. Stage 1's uniform shrink narrows both top and
    bottom edges by the SAME amount, so the slant
    ``(top_width - bottom_width)`` is invariant.

    This is what gives the IPA vowel chart a stable visual
    identity across inventories: a 5-vowel Spanish chart and a
    33-vowel Maximalist chart share the same trapezoid
    proportions, with the dense one just slightly narrower
    overall. Pre-fix the per-inventory Stage 2 tweak made each
    chart's proportions drift, breaking that visual identity.

    If this test fails, either Stage 2 was re-enabled or
    Stage 1's math was changed -- both warrant a visual review
    before landing.
    """
    canonical_sil = vowels_mod.vowel_silhouette(
        vowels_mod.VowelChartShape.TRAPEZOID
    )
    canonical_slant = canonical_sil.top_width - canonical_sil.bottom_width
    sample_inventories = (
        "spanish",
        "korean",
        "english",
        "hayes",
        "maximalist_vowels",
        "general",
        "modern_standard_arabic",
    )
    drifts: list[tuple[str, float]] = []
    for name in sample_inventories:
        try:
            engine = bundled_engine(name)
        except (FileNotFoundError, KeyError, pytest.skip.Exception):
            # bundled_engine raises pytest.skip when an
            # inventory file isn't checked in (gitignored in
            # CI). Skip just that inventory; keep scanning the
            # rest so the invariant is still exercised.
            continue
        vowels = _vowel_segs(engine)
        if not vowels:
            continue
        seg_feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)
        sil = geometry.silhouette
        rendered_slant = sil.top_width - sil.bottom_width
        drifts.append((name, rendered_slant - canonical_slant))
    assert drifts, "no bundled inventories loaded -- fixture broken"
    for name, drift in drifts:
        assert abs(drift) < 1e-9, (
            f"{name}: slant drifted from canonical "
            f"by {drift:.6f} -- Stage 2 re-enabled or Stage 1 "
            f"broke its uniform-shrink invariant"
        )
