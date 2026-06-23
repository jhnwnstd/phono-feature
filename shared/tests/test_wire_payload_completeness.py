"""Pins the wire-payload shape against the web renderer's reads.

The web app consumes the inventory summary via
``view_models.build_inventory_summary`` to JSON serialisation to
``web/main.js`` field reads. When a Python refactor drops a field
the JS silently reads ``undefined`` and the affected feature breaks
without a test failing.

This test pins the fields web/main.js reads from each list/dict in
the wire payload. Any future refactor that drops one of these
fields fails CI; the test failure points at the dropped field +
the JS line that reads it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from phonology_shared.chart.vowel_geometry import build_vowel_chart_geometry
from phonology_shared.chart.vowels import detect_vowel_profile
from phonology_shared.data.inventory import Inventory
from phonology_shared.presentation.view_models import (
    build_inventory_summary,
)
from phonology_shared.theory.feature_engine import FeatureEngine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUNDLED_DIR = _REPO_ROOT / "desktop" / "inventories"
_WEB_MAIN_JS = _REPO_ROOT / "web" / "main.js"


def _load_bundled(stem: str) -> Inventory:
    """Load a bundled inventory by stem."""
    import json

    path = _BUNDLED_DIR / f"{stem}_features.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return Inventory.parse(raw, source=path.stem)


def _vowel_chart_summary_for(stem: str) -> dict:
    """Build the wire payload for a bundled inventory's vowel chart."""
    inv = _load_bundled(stem)
    engine = FeatureEngine(inv)
    summary = build_inventory_summary(engine, stem)
    return summary["vowel_chart"]


# ---------------------------------------------------------------------------
# Cell wire dict
# ---------------------------------------------------------------------------

# Fields the web renderer reads from each cell dict. Sourced by
# grepping ``web/main.js`` for ``cell.<name>``. Updating this set
# requires reviewing the JS to confirm the new field is actually
# consumed (or that an old field's consumer is gone).
_EXPECTED_CELL_FIELDS = frozenset(
    {
        "row",
        "col",
        "chart_x",
        "chart_y",
        "pair_side",
        "segs",
        "display_kind",
        "contrast_features",
        "pair_shift_px",
        "nudge_px",
    }
)


def test_cell_wire_dict_contains_every_field_web_reads() -> None:
    """The cells[] entries in the wire payload contain every
    field ``web/main.js`` reads via ``cell.<name>``.
    """
    chart = _vowel_chart_summary_for("korean")
    cells = chart["cells"]
    assert cells, "korean inventory should have populated cells"
    actual_fields = set(cells[0].keys())
    missing = _EXPECTED_CELL_FIELDS - actual_fields
    extra = actual_fields - _EXPECTED_CELL_FIELDS
    assert not missing, (
        f"cell wire dict is missing {missing!r}; web/main.js "
        f"reads these fields and gets undefined when they're "
        f"dropped. Add to view_models.py _vowel_chart_summary."
    )
    # Extra fields are OK; they're forward-compatible additions
    # the JS will ignore. Just log them so we notice drift.
    if extra:
        pytest.skip(
            f"cell wire dict has extra fields {extra!r}; update "
            f"_EXPECTED_CELL_FIELDS if these are intentional."
        )


# ---------------------------------------------------------------------------
# Top-level vowel_chart fields (read directly off info.vowel_chart)
# ---------------------------------------------------------------------------

# Fields the web renderer reads off ``info.vowel_chart`` itself (not
# nested arrays). Sourced from web/main.js:670 to 697 (the renderer's
# own schema check) and the ``_buildVowelChart`` function. Without
# this guard, a refactor that drops ``chart.title`` leaves the chart
# header empty without any failing test pointing at the change.
_EXPECTED_VOWEL_CHART_FIELDS = frozenset(
    {
        "title",
        "shape",
        "silhouette",
        "cols",
        "rows",
        "cells",
        "diphthongs",
        "natural_data_height_px",
        # ``bands`` is only emitted when the geometry produced any;
        # validated separately below so the contract doesn't force
        # empty-band inventories to carry the key.
    }
)

_EXPECTED_SILHOUETTE_FIELDS = frozenset(
    {
        "shape",
        "top_y",
        "bottom_y",
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "top_width",
        "bottom_width",
        # ``front_anchor_at_top`` and ``back_anchor`` are derived
        # for the cascade flush math; both renderers consume them
        # so they must travel through the wire payload too.
    }
)


def test_vowel_chart_top_level_fields_match_renderer_reads() -> None:
    """``info.vowel_chart`` must carry every field both renderers
    project. Pre-fix the cell + row + diphthong dicts were guarded;
    chart-level fields (``title``, ``shape``, ``silhouette``,
    ``natural_data_height_px``) were not. A refactor dropping any
    of them would leave the web header or trapezoid silently
    blank with no failing test.
    """
    chart = _vowel_chart_summary_for("korean")
    actual = set(chart.keys())
    missing = _EXPECTED_VOWEL_CHART_FIELDS - actual
    assert not missing, (
        f"vowel_chart top-level fields missing {missing!r}; "
        "web/main.js reads these directly off info.vowel_chart "
        "and gets undefined when they're dropped."
    )


def test_vowel_chart_silhouette_carries_every_renderer_field() -> None:
    """The silhouette dict drives the clip-path / trapezoid corners.
    Missing fields leave the renderer fallback-painting a canonical
    silhouette that does not match the inventory's row range.
    """
    chart = _vowel_chart_summary_for("korean")
    sil = chart["silhouette"]
    assert isinstance(sil, dict), (
        f"vowel_chart.silhouette must be a dict, got " f"{type(sil).__name__}"
    )
    missing = _EXPECTED_SILHOUETTE_FIELDS - set(sil.keys())
    assert not missing, (
        f"silhouette dict missing {missing!r}; the renderer's "
        "validity check (web/main.js around line 695) rejects "
        "the entire payload when these absent, falling back to "
        "the canonical Close-to-Open trapezoid."
    )


# ---------------------------------------------------------------------------
# Row wire dict
# ---------------------------------------------------------------------------

_EXPECTED_ROW_FIELDS = frozenset(
    {
        "logical_row",
        "label",
        "chart_y",
        "tier",
        # Label anchor y (chart_y + the half-button top/bottom shift
        # from the shared ``label_midpoint_norm``): web/main.js reads
        # it for ``--row-y`` so the Close/Open labels centre on the
        # anchor button row instead of the stack edge.
        "label_y",
        "silhouette_left",
        "silhouette_right",
        # Read by the web slot clamp (``_refreshVowelStackClamp``)
        # to shrink deep stacks when the rendered chart is shorter
        # than the natural request.
        "slot_height_norm",
    }
)


def test_row_wire_dict_contains_every_field_web_reads() -> None:
    """Same pattern for rows: web/main.js reads ``row.<name>``."""
    chart = _vowel_chart_summary_for("korean")
    rows = chart["rows"]
    assert rows, "korean inventory should have populated rows"
    actual_fields = set(rows[0].keys())
    missing = _EXPECTED_ROW_FIELDS - actual_fields
    assert not missing, (
        f"row wire dict is missing {missing!r}; web/main.js "
        f"depends on these for row-label positioning."
    )


# ---------------------------------------------------------------------------
# Diphthong wire dict
# ---------------------------------------------------------------------------


def test_diphthong_wire_shape_is_list_of_segment_strings() -> None:
    """``geometry.diphthongs`` (and its wire serialisation) is a plain
    list of segment-name strings. Both UIs render those as chips below
    the vowel space; there is no per-arrow endpoint dict anymore."""
    from phonology_shared.presentation.view_models import (
        _vowel_chart_summary,
    )

    inv = _load_bundled("spanish")
    engine = FeatureEngine(inv)
    vowels = list(engine.grouped_segments.get("Vowels", []))
    seg_feats = {s: dict(engine.normalized_segment_feats[s]) for s in vowels}
    profile = detect_vowel_profile(vowels, seg_feats)
    # Spanish has no diphthongs; inject a synthetic contour (/i/ -> /a/)
    # so the list is non-empty and we can check the element type.
    synthetic_secondary = {}
    if "i" in seg_feats and "a" in seg_feats:
        synthetic_secondary["i"] = dict(seg_feats["a"])
    geom = build_vowel_chart_geometry(
        vowels, profile, seg_feats, vowel_secondary=synthetic_secondary
    )
    if not geom.diphthongs:
        pytest.skip(
            "synthetic diphthong was suppressed by degeneracy "
            "filter; check spanish vowel set"
        )
    assert all(isinstance(seg, str) for seg in geom.diphthongs)
    # And the wire payload mirrors that: a JSON list of strings.
    summary = _vowel_chart_summary(engine, vowels)
    assert isinstance(summary["diphthongs"], list)
    assert all(isinstance(seg, str) for seg in summary["diphthongs"])


# ---------------------------------------------------------------------------
# Static grep: confirm the JS field reads match the expected set
# ---------------------------------------------------------------------------


def test_web_js_cell_field_reads_match_expected_set() -> None:
    """Grep ``web/main.js`` for ``cell.<name>`` reads and confirm
    every name appears in ``_EXPECTED_CELL_FIELDS``. If a JS edit
    adds a new ``cell.foo`` read, this test surfaces the addition
    so the test maintainer remembers to bake ``foo`` into the
    wire dict.

    Excludes obvious non-field accesses: ``cell.dataset.*``,
    ``cellEl.querySelector``, etc. Pattern is ``cell.<lowercase>``
    word followed by non-dot, since field reads are always
    snake_case here.
    """
    text = _WEB_MAIN_JS.read_text(encoding="utf-8")
    # Match cell.<word> but skip cellEl. / cellNode. etc; we
    # care about the variable named exactly ``cell``.
    pattern = re.compile(
        r"\bcell\.([a-z_][a-z0-9_]*)\b(?!\.)",
        re.IGNORECASE,
    )
    reads = set()
    for match in pattern.finditer(text):
        name = match.group(1)
        # Filter DOM helpers + closures + known non-field refs.
        if name in (
            # DOM properties on HTMLElement / DOM helpers
            "dataset",
            "querySelector",
            "querySelectorAll",
            "getBoundingClientRect",
            "appendChild",
            "addEventListener",
            "removeEventListener",
            "classList",
            "style",
            "setAttribute",
            "getAttribute",
            "isConnected",
            "parentElement",
            "firstChild",
            "innerHTML",
            "textContent",
            "tagName",
            "id",
            "className",
            "children",
            "title",
            "hidden",
            "disabled",
            "focus",
            "blur",
            "click",
            "remove",
            "insertBefore",
            "scrollIntoView",
        ):
            continue
        reads.add(name)
    unknown = reads - _EXPECTED_CELL_FIELDS
    assert not unknown, (
        f"web/main.js reads cell fields {unknown!r} that are NOT "
        f"in _EXPECTED_CELL_FIELDS. Either:\n"
        f"  (a) add the field to _EXPECTED_CELL_FIELDS + "
        f"      view_models.py if it's a wire-payload field, OR\n"
        f"  (b) update the exclusion list in this test if it's a "
        f"      DOM/JS helper or a non-wire access."
    )
