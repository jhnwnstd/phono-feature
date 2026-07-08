"""Uniform-shrink silhouette-width solver tests.

Stage 1 shrinks ``top_width`` and ``bottom_width`` by the same
amount, preserving the canonical slant. (An earlier Stage 2 slant
tweak has been retired -- it tilted the trapezoid per-inventory,
defeating the chart's at-a-glance familiarity.)

These tests exercise the helpers directly (so a regression in the
solver's math fails here rather than in the rendered chart) plus an
end-to-end check against the real Hayes inventory through
:py:func:`build_vowel_chart_geometry`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from phonology_shared.chart import vowels as vowels_mod

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowel_geometry import shrink as shrink_mod
from phonology_shared.chart.vowel_geometry import silhouette as silhouette_mod
from phonology_shared.chart.vowel_geometry.shrink import (
    _compute_shrunken_widths,
    _shrink_uniform,
)
from phonology_shared.chart.vowels import detect_vowel_profile
from phonology_shared.theory.feature_engine import FeatureEngine


@contextmanager
def patched_module_attr(module: Any, name: str, value: Any) -> Iterator[None]:
    """Restore ``module.name`` to its prior value when the block
    exits, even on test failure or KeyboardInterrupt."""
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, saved)


# Uniform shrink preserves the canonical slant


def test_uniform_shrink_preserves_slant() -> None:
    """Both edges drop by the SAME amount, so ``top_w - bot_w`` is
    invariant. This is what gives every inventory's silhouette a
    stable visual identity: sparse and dense inventories share the
    canonical trapezoid proportions, only the overall scale differs.
    """
    canonical_top = 1.0
    canonical_bot = 0.7
    row_data = [(0.5, 0.7)]
    top, bot = _shrink_uniform(row_data, canonical_top, canonical_bot)
    assert top < canonical_top
    assert bot < canonical_bot
    assert top - bot == pytest.approx(canonical_top - canonical_bot)


def test_compose_returns_canonical_when_factor_zero() -> None:
    """``_VOWEL_SHRINK_FACTOR = 0`` short-circuits the solver: no
    shrinking happens, canonical widths flow through unchanged."""
    with patched_module_attr(shrink_mod, "_VOWEL_SHRINK_FACTOR", 0.0):
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


# End-to-end: real inventory through build_vowel_chart_geometry


def _vowel_segs(engine: FeatureEngine) -> list[str]:
    return [
        s for s in engine.segments if engine.segments[s].get("Syllabic") == "+"
    ]


def test_hayes_silhouette_preserves_canonical_slant(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """The Hayes inventory's rendered silhouette must preserve the
    canonical slant exactly. Uniform shrink narrows both edges by
    the SAME amount, so the slant is invariant.
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
    canonical_sil = silhouette_mod.vowel_silhouette(
        vowels_mod.VowelChartShape.TRAPEZOID
    )
    canonical_slant = canonical_sil.top_width - canonical_sil.bottom_width
    assert abs(rendered_slant - canonical_slant) < 1e-9, (
        f"Hayes silhouette slant {rendered_slant:.4f} != canonical "
        f"{canonical_slant:.4f}; uniform-shrink invariant broke."
    )


def test_silhouette_slant_canonical_across_bundled_inventories(
    bundled_engine: Callable[[str], FeatureEngine],
) -> None:
    """SILHOUETTE CONSISTENCY INVARIANT: every trapezoid-shaped
    bundled inventory's silhouette must preserve the canonical slant
    exactly. Uniform shrink narrows both top and bottom edges by the
    SAME amount, so ``(top_width - bottom_width)`` is invariant.

    This is what gives the IPA vowel chart a stable visual identity
    across inventories: a 5-vowel Spanish chart and a 33-vowel
    Maximalist chart share the same trapezoid proportions, with the
    dense one just slightly narrower overall.
    """
    canonical_sil = silhouette_mod.vowel_silhouette(
        vowels_mod.VowelChartShape.TRAPEZOID
    )
    canonical_slant = canonical_sil.top_width - canonical_sil.bottom_width
    sample_inventories = (
        "spanish",
        "korean",
        "english",
        "hayes",
        "maximalist_vowels",
        "modern_standard_arabic",
    )
    drifts: list[tuple[str, float]] = []
    for name in sample_inventories:
        try:
            engine = bundled_engine(name)
        except (FileNotFoundError, KeyError, pytest.skip.Exception):
            continue
        vowels = _vowel_segs(engine)
        if not vowels:
            continue
        seg_feats = {s: dict(engine.segments[s]) for s in vowels}
        profile = detect_vowel_profile(vowels, seg_feats)
        geometry = build_vowel_chart_geometry(vowels, profile, seg_feats)
        sil = geometry.silhouette
        # Converged-bottom inventories deliberately raise the top
        # width floor above what uniform shrink would compute so
        # the front slant reads visibly on a sparse chart; they
        # change the slant BY DESIGN. Only pin the canonical-slant
        # invariant on trapezoid-shaped inventories.
        if sil.back_anchor_at_bottom is not None:
            continue
        rendered_slant = sil.top_width - sil.bottom_width
        drifts.append((name, rendered_slant - canonical_slant))
    assert drifts, (
        "no trapezoid-shaped bundled inventories loaded; the invariant "
        "would trivially hold. Fixture broken?"
    )
    for name, drift in drifts:
        assert abs(drift) < 1e-9, (
            f"{name}: slant drifted from canonical by {drift:.6f}; "
            f"uniform-shrink invariant broke."
        )
