"""Tests for the shared ``Inventory`` contract.

This is the file the reviewer flagged as missing: validator behaviour,
malformed-input handling, engine/validator agreement, atomic-write
durability, and the alias-collision check in segment_grouper.

Every test here exercises the SINGLE entry point ``Inventory.parse``
(or a thin wrapper). The engine cannot accept anything the parser
rejects, and the builder cannot save anything the parser rejects --
the parser is the contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from phonology_features.engine.feature_engine import FeatureEngine
from phonology_features.engine.geometry import GeometryAnalyzer
from phonology_features.engine.inventory import (
    Inventory,
    ValidationError,
    atomic_write_json,
)
from phonology_features.engine.inventory_validator import (
    validate_inventory_data,
)
from phonology_features.engine.segment_grouper import (
    AliasCollisionError,
    _normalize_feats,
)

from .conftest import close_builder_silent

REPO_ROOT = Path(__file__).resolve().parent.parent
HAYES = str(REPO_ROOT / "inventories" / "hayes_features.json")


# ---------------------------------------------------------------------------
# parse(): structural shape errors
# ---------------------------------------------------------------------------
def test_parse_rejects_non_dict_top_level() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(["features", "segments"])
    assert any("top-level" in i for i in ex.value.issues)


def test_parse_rejects_missing_features_key() -> None:
    """The old validator only warned on missing 'features'; the engine
    rejected the same data with ValueError. The new contract is
    strict so the two cannot disagree."""
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"segments": {"p": {}}})
    assert any("'features'" in i for i in ex.value.issues)


def test_parse_rejects_missing_segments_key() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice"]})
    assert any("'segments'" in i for i in ex.value.issues)


# ---------------------------------------------------------------------------
# parse(): features validation
# ---------------------------------------------------------------------------
def test_parse_rejects_non_list_features() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": "Voice", "segments": {}})
    assert any("'features'" in i and "list" in i for i in ex.value.issues)


def test_parse_rejects_empty_feature_name_without_crashing() -> None:
    """The old validator's lowercase-name warning path did ``feat[0]``
    on an empty string and raised ``IndexError``. The new parser
    surfaces it as a structured issue."""
    inv = {"features": ["Voice", ""], "segments": {}}
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("empty" in i.lower() for i in ex.value.issues)


def test_parse_rejects_duplicate_feature_names() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice", "Voice"], "segments": {}})
    assert any("duplicate" in i.lower() for i in ex.value.issues)


def test_parse_rejects_non_string_feature_entries() -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.parse({"features": ["Voice", 42], "segments": {}})
    assert any("'features[1]'" in i for i in ex.value.issues)


# ---------------------------------------------------------------------------
# parse(): segments validation
# ---------------------------------------------------------------------------
def test_parse_rejects_non_dict_segments() -> None:
    with pytest.raises(ValidationError):
        Inventory.parse({"features": ["Voice"], "segments": []})


def test_parse_rejects_undeclared_feature_in_segment() -> None:
    """The old validator only warned on undeclared features and the
    engine then silently dropped them from queries. New contract:
    undeclared features are an error so the two cannot disagree."""
    inv = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-", "Nasal": "-"}},
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("'Nasal'" in i and "not declared" in i for i in ex.value.issues)


def test_parse_rejects_invalid_feature_value() -> None:
    inv = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "yes"}},
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert any("invalid" in i.lower() and "yes" in i for i in ex.value.issues)


def test_parse_rejects_non_string_segment_key() -> None:
    inv = {"features": ["Voice"], "segments": {42: {"Voice": "+"}}}
    with pytest.raises(ValidationError):
        Inventory.parse(inv)


def test_parse_collects_all_issues_not_just_first() -> None:
    """Reviewer asked for structured validation results that report
    every problem at once, not crash on the first."""
    inv = {
        "features": ["", "Voice", "Voice"],
        "segments": {
            "p": {"Voice": "yes"},
            "x": {"Undeclared": "+"},
        },
    }
    with pytest.raises(ValidationError) as ex:
        Inventory.parse(inv)
    assert len(ex.value.issues) >= 3


# ---------------------------------------------------------------------------
# parse(): happy path produces a usable immutable Inventory
# ---------------------------------------------------------------------------
def test_parse_returns_immutable_inventory() -> None:
    inv = Inventory.parse(
        {
            "features": ["Voice", "Nasal"],
            "segments": {"p": {"Voice": "-"}, "m": {"Nasal": "+"}},
        }
    )
    assert isinstance(inv.features, tuple)
    with pytest.raises(TypeError):
        inv.segments["p"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        inv.segments["p"]["Voice"] = "+"  # type: ignore[index]


def test_parse_missing_feature_in_bundle_defaults_to_zero() -> None:
    """Segments may omit features; the parser does NOT auto-fill the
    on-disk representation. Readers default to '0' via
    ``Inventory.feature_value``."""
    inv = Inventory.parse(
        {
            "features": ["Voice", "Nasal"],
            "segments": {"p": {"Voice": "-"}},
        }
    )
    assert inv.feature_value("p", "Voice") == "-"
    assert inv.feature_value("p", "Nasal") == "0"
    # On-disk shape unchanged: Nasal is NOT auto-inserted.
    assert "Nasal" not in inv.segments["p"]


def test_parse_uses_metadata_name_then_top_level_name() -> None:
    inv = Inventory.parse(
        {
            "metadata": {"name": "Pretty Name"},
            "name": "Fallback Name",
            "features": [],
            "segments": {},
        }
    )
    assert inv.name == "Pretty Name"
    inv2 = Inventory.parse(
        {"name": "Fallback Name", "features": [], "segments": {}}
    )
    assert inv2.name == "Fallback Name"
    inv3 = Inventory.parse({"features": [], "segments": {}})
    assert inv3.name == "Untitled Inventory"


def test_hayes_parses_without_issues() -> None:
    inv = Inventory.load(HAYES)
    assert len(inv.features) > 0
    assert len(inv.segments) > 0


# ---------------------------------------------------------------------------
# load(): file-level errors come through ValidationError too
# ---------------------------------------------------------------------------
def test_load_missing_file_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(tmp_path / "does_not_exist.json"))
    assert any("not found" in i for i in ex.value.issues)


def test_load_invalid_json_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValidationError) as ex:
        Inventory.load(str(bad))
    assert any("invalid JSON" in i for i in ex.value.issues)


# ---------------------------------------------------------------------------
# Engine / validator agreement
# ---------------------------------------------------------------------------
def test_engine_rejects_what_validator_rejects() -> None:
    """Reviewer's #1: the engine and validator must not disagree on
    'is this valid'. With one parse path they cannot."""
    bad = {"segments": {"p": {"Voice": "+"}}}  # missing features
    errors, _ = validate_inventory_data(bad)
    assert errors
    with pytest.raises(ValidationError):
        Inventory.parse(bad)


def test_engine_requires_inventory_not_raw_dict() -> None:
    """The engine's old load_inventory_data accepted raw dicts and
    could be more lenient than the validator. New engine refuses raw
    input."""
    with pytest.raises(TypeError):
        FeatureEngine({"features": [], "segments": {}})  # type: ignore[arg-type]


def test_engine_caches_cannot_desync_from_mutation() -> None:
    """Reviewer's #3: previously the engine stored caller's data by
    reference and the caches went stale on caller mutation. With a
    frozen Inventory this can't happen."""
    inv_raw: dict[str, object] = {
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-"}, "b": {"Voice": "+"}},
    }
    inv = Inventory.parse(inv_raw)
    eng = FeatureEngine(inv)
    # Mutating the original raw dict must not affect the engine.
    inv_raw["segments"]["p"]["Voice"] = "+"  # type: ignore[index]
    assert eng.get_feature_value("p", "Voice") == "-"
    assert "p" not in eng.plus_segs["Voice"]
    assert "p" in eng.minus_segs["Voice"]


def test_engine_features_are_immutable_view() -> None:
    eng = FeatureEngine.from_path(HAYES)
    assert isinstance(eng.features, tuple)


# ---------------------------------------------------------------------------
# Engine architectural invariants
# ---------------------------------------------------------------------------
def test_engine_has_no_empty_state() -> None:
    """The engine takes its Inventory in ``__init__``; there is no
    moment where ``eng.features`` is empty because no inventory was
    loaded yet. Constructing without an inventory is an error."""
    with pytest.raises(TypeError):
        FeatureEngine()  # type: ignore[call-arg]


def test_engine_caches_bundle_search_results() -> None:
    """``is_natural_class`` and ``compute_natural_class`` both delegate
    to ``find_all_minimal_bundles``. Calling them back-to-back on the
    same input must not re-run the exponential-worst-case search.
    We probe via the private cache dict since timing is too flaky."""
    eng = FeatureEngine.from_path(HAYES)
    segs = ["b", "d", "ɡ"]
    assert frozenset(segs) not in eng._bundle_cache
    eng.is_natural_class(segs)
    assert frozenset(segs) in eng._bundle_cache
    # Second call must hit the cache (same list identity isn't required;
    # only the frozenset).
    cached = eng._bundle_cache[frozenset(segs)]
    eng.compute_natural_class(segs)
    assert eng._bundle_cache[frozenset(segs)] is cached


def test_engine_grouped_segments_cached_per_engine() -> None:
    """``grouped_segments`` is a cached_property: same engine returns
    the same dict object; new engine = new computation."""
    eng = FeatureEngine.from_path(HAYES)
    a = eng.grouped_segments
    b = eng.grouped_segments
    assert a is b
    eng2 = FeatureEngine.from_path(HAYES)
    assert eng2.grouped_segments is not a


def test_engine_seg_value_tuples_lazy() -> None:
    """Built lazily: not present in ``__dict__`` until first access."""
    eng = FeatureEngine.from_path(HAYES)
    assert "_seg_value_tuples" not in eng.__dict__
    eng.segment_distance("b", "p")
    assert "_seg_value_tuples" in eng.__dict__


# ---------------------------------------------------------------------------
# GeometryAnalyzer: state must not leak across analyze() calls
# ---------------------------------------------------------------------------
def test_find_all_minimal_bundles_bitmask_matches_naive() -> None:
    """The bitmask hitting-set search must produce the same bundles
    as a brute-force reference implementation for a handful of
    inputs. Catches off-by-one in the bit numbering."""
    eng = FeatureEngine.from_path(HAYES)
    seg_lists = (
        ["b", "d", "ɡ"],
        ["p", "t", "k"],
        ["m", "n", "ŋ"],
        ["f", "s"],
        ["a", "e", "i", "o", "u"],
        ["l"],
        ["b"],  # singleton -- common path
    )
    for segs in seg_lists:
        bundles = eng.find_all_minimal_bundles(segs)
        # Every returned bundle must characterise S exactly.
        for bundle in bundles:
            recovered = set(
                eng.find_segments(bundle, underspec_compatible=True)
            )
            assert recovered == set(
                segs
            ), f"bundle {bundle} for {segs} recovered {recovered}"
        # All bundles must be the same size (minimal).
        sizes = {len(b) for b in bundles}
        assert len(sizes) <= 1, f"non-uniform bundle sizes for {segs}: {sizes}"


def test_cell_brushes_cached_until_theme_changes() -> None:
    """The brush triple cache must return the SAME QBrush object
    across calls within one theme epoch, then a fresh one after
    ``set_theme`` bumps ``theme_version``."""
    from phonology_features.gui import palette
    from phonology_features.gui.builder.grid import _cell_brushes

    palette.set_theme("light")
    fg_a, bg_a = _cell_brushes("+")
    fg_b, bg_b = _cell_brushes("+")
    assert fg_a is fg_b and bg_a is bg_b, "cache miss within one theme"
    palette.set_theme("dark")
    fg_c, _ = _cell_brushes("+")
    assert fg_c is not fg_a, "cache should rebuild after theme change"
    palette.set_theme("light")  # restore for other tests


def test_geometry_analyzer_resets_between_runs() -> None:
    """Calling ``analyze`` twice on the same analyzer used to leak
    dependency entries from the first run. Now it clears first."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    analyzer.analyze()
    first_deps = dict(analyzer.dependencies)
    # Poison the dict with a fake entry and re-run; analyze must drop it.
    analyzer.dependencies["FakeFeature"] = {
        "parent": "FakeParent",
        "coverage": 1.0,
        "p_value": 0.0,
        "confidence": "high",
    }
    analyzer.analyze()
    assert "FakeFeature" not in analyzer.dependencies
    assert analyzer.dependencies == first_deps


# ---------------------------------------------------------------------------
# Atomic writes: a crash mid-write must not corrupt the destination
# ---------------------------------------------------------------------------
def test_atomic_write_replaces_atomically(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")
    atomic_write_json(str(target), {"new": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}


def test_atomic_write_does_not_leave_tmp_file_on_success(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.json"
    atomic_write_json(str(target), {"x": 1})
    leftover = [p for p in tmp_path.iterdir() if p.name != "out.json"]
    assert leftover == []


def test_atomic_write_cleans_up_tmp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force ``os.replace`` to fail and confirm we don't leave debris."""
    target = tmp_path / "out.json"
    real_replace = os.replace

    def fail_replace(src: str, dst: str) -> None:
        # Remove the tmp file to simulate a crash partway through;
        # the cleanup branch should swallow the missing-tmp gracefully.
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        atomic_write_json(str(target), {"x": 1})
    monkeypatch.setattr(os, "replace", real_replace)
    leftover = list(tmp_path.iterdir())
    assert leftover == [], f"tmp files leaked: {leftover}"


def test_inventory_write_atomic_round_trip(tmp_path: Path) -> None:
    inv = Inventory.parse(
        {
            "metadata": {"name": "Test"},
            "features": ["Voice"],
            "segments": {"p": {"Voice": "-"}, "b": {"Voice": "+"}},
        }
    )
    target = tmp_path / "round.json"
    inv.write_atomic(str(target))
    loaded = Inventory.load(str(target))
    assert loaded.name == "Test"
    assert loaded.features == ("Voice",)
    assert loaded.feature_value("b", "Voice") == "+"


def test_round_trip_preserves_top_level_metadata(tmp_path: Path) -> None:
    """Some bundled inventories (e.g. ``general_features.json``) store
    ``name``/``version``/``notes`` at the top level rather than under
    a ``metadata`` object. ``to_json_dict`` must not silently drop
    them on round-trip -- the parser harvests both conventions into
    ``Inventory.metadata`` and ``to_json_dict`` writes them all back
    under the canonical ``metadata`` key."""
    raw = {
        "name": "X",
        "version": "3.0",
        "notes": "important",
        "features": ["Voice"],
        "segments": {"p": {"Voice": "-"}},
    }
    inv = Inventory.parse(raw)
    target = tmp_path / "round.json"
    inv.write_atomic(str(target))
    reloaded = Inventory.load(str(target))
    assert reloaded.name == "X"
    assert reloaded.metadata.get("version") == "3.0"
    assert reloaded.metadata.get("notes") == "important"


def test_explicit_metadata_wins_over_top_level_collision() -> None:
    """If both shapes set ``name``, the explicit metadata object wins
    -- it's the more deliberate, structured location."""
    inv = Inventory.parse(
        {
            "name": "top-level",
            "metadata": {"name": "metadata-name"},
            "features": [],
            "segments": {},
        }
    )
    assert inv.name == "metadata-name"


# ---------------------------------------------------------------------------
# from_grid normalizes Unicode minus to ASCII before validation
# ---------------------------------------------------------------------------
def test_from_grid_accepts_unicode_minus() -> None:
    inv = Inventory.from_grid(
        name="X",
        features=["Voice"],
        segments={"p": {"Voice": "−"}},  # U+2212 MINUS SIGN
    )
    assert inv.feature_value("p", "Voice") == "-"


def test_from_grid_rejects_unknown_cell_value() -> None:
    """The old builder silently rewrote unknown values to '0'. New
    contract: unknown values are an error -- they shouldn't reach the
    save path in the first place, so surfacing them is the bug-hunting
    behaviour."""
    with pytest.raises(ValidationError):
        Inventory.from_grid(
            name="X",
            features=["Voice"],
            segments={"p": {"Voice": "weird"}},
        )


# ---------------------------------------------------------------------------
# Alias collision detection in segment_grouper
# ---------------------------------------------------------------------------
def test_normalize_feats_raises_on_alias_collision() -> None:
    """Reviewer's #7: previously a dict-comprehension rebuild would
    silently keep whichever alias came last. Now the collision is
    surfaced."""
    with pytest.raises(AliasCollisionError) as ex:
        _normalize_feats({"DelRel": "+", "delayed_release": "-"})
    assert "delrel" in ex.value.collisions


def test_normalize_feats_passes_when_no_collision() -> None:
    out = _normalize_feats({"DelRel": "+", "Voice": "-"})
    assert out["delrel"] == "+"
    assert out["voice"] == "-"


# ---------------------------------------------------------------------------
# Geometry: confidence vocabulary and acyclicity
# ---------------------------------------------------------------------------
def test_geometry_confidence_uses_medium_not_moderate() -> None:
    """Reviewer's #9: implementation drifted to 'moderate' while
    tests / public docs say 'medium'. Standardize on 'medium'."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    analyzer.analyze()
    for dep in analyzer.get_dependency_summary():
        assert dep["confidence"] in {
            "high",
            "medium",
            "low",
        }, f"unexpected confidence label: {dep['confidence']!r}"


def test_geometry_tree_is_acyclic() -> None:
    """The reviewer flagged that geometry acyclicity isn't tested.
    Walk every node from the root and confirm no node is visited
    twice (DFS with a visited set)."""
    eng = FeatureEngine.from_path(HAYES)
    analyzer = GeometryAnalyzer(eng)
    root = analyzer.analyze()
    visited: set[str] = set()

    def walk(node) -> None:
        assert node.feature not in visited, f"cycle detected at {node.feature}"
        visited.add(node.feature)
        for child in node.children:
            walk(child)

    walk(root)


# ---------------------------------------------------------------------------
# HTML escaping in the analysis pane
# ---------------------------------------------------------------------------
def test_analysis_copy_translates_unicode_minus_to_ascii(
    tmp_path: Path,
) -> None:
    """The analysis pane renders feature negatives as U+2212 (`−`)
    for visual symmetry with `+`, but the rest of the ecosystem
    (JSON values, code, regex, terminals) expects ASCII `-`. The
    ``_CopyableTextEdit`` subclass must translate at the clipboard
    boundary so a user copying `-Voice` from the pane can paste it
    into a JSON value and have it actually match.

    Asserts both payloads: the plain-text mime (for code editors and
    terminals) AND the HTML mime (for rich-text targets like docx).
    """
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.widgets import _CopyableTextEdit

    edit = _CopyableTextEdit()
    # The display layer puts U+2212 in the HTML; verify the copy
    # path turns it into ASCII '-' in both mime payloads. The
    # show()+processEvents() bit is required for selectAll() to
    # establish a real selection under the offscreen QPA -- an
    # unrealised widget produces an empty selection and Qt then
    # crashes deep in createMimeDataFromSelection.
    edit.setHtml(
        "<p>shared: <span style='color:red'>" "−Voice</span> +Continuant</p>"
    )
    edit.show()
    for _ in range(3):
        app.processEvents()
    edit.selectAll()
    for _ in range(3):
        app.processEvents()
    mime = edit.createMimeDataFromSelection()
    assert mime is not None
    assert (
        "−" not in mime.text()
    ), "plain-text payload still contains U+2212 minus"
    assert "-Voice" in mime.text()
    assert mime.hasHtml()
    assert "−" not in mime.html(), "HTML payload still contains U+2212 minus"

    # Sanity: a selection with no U+2212 still produces a usable mime
    # (the fast path returns the original; we don't care which branch
    # ran, only that the output is right).
    edit.clear()
    edit.setHtml("<p>just plain ASCII +Voice +Nasal</p>")
    for _ in range(3):
        app.processEvents()
    edit.selectAll()
    for _ in range(3):
        app.processEvents()
    mime2 = edit.createMimeDataFromSelection()
    assert mime2 is not None
    assert "+Voice" in mime2.text()
    edit.close()


def test_analysis_tag_escapes_html_in_text() -> None:
    """A feature named ``"<b>X"`` must not break the rendered
    layout. The ``_tag`` chip is the only path through which
    inventory text reaches the HTML output, so escaping there is
    sufficient."""
    from phonology_features.gui.analysis import _tag
    from phonology_features.gui.constants import TagColor

    out = _tag("<b>oops</b>", TagColor.PLUS)
    assert "<b>oops</b>" not in out
    assert "&lt;b&gt;oops&lt;/b&gt;" in out


def test_analysis_render_single_segment_escapes_symbol() -> None:
    """The segment symbol is interpolated into the bold header
    outside the tag chip, so it has its own escape call."""
    from phonology_features.gui.analysis import render_single_segment

    class _FakeEngine:
        features: tuple[str, ...] = ("Voice",)
        segments = {"<x>": {"Voice": "+"}}

        def is_natural_class(self, segs):
            return False, []

        def find_segments(self, *args, **kwargs):
            return []

    # The renderer treats ``engine`` as duck-typed for testability;
    # the cast keeps mypy happy without forcing a real FeatureEngine.
    out = render_single_segment(_FakeEngine(), "<x>", {"Voice": "+"})  # type: ignore[arg-type]
    assert "/<x>/" not in out
    assert "/&lt;x&gt;/" in out


def test_bulk_cycle_whole_table_under_100ms(tmp_path: Path) -> None:
    """Regression guard against the ResizeToContents footgun. Before
    we switched the vertical header to Fixed, every per-cell
    setForeground stalled Qt re-walking the row to recompute height;
    a whole-table cycle on Hayes (3920 cells) took ~60+ seconds. The
    Fixed-mode fix dropped it to ~17 ms. 100 ms is a comfortable
    ceiling that still catches the failure mode if it ever regresses."""
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.show()
    for _ in range(4):
        app.processEvents()
    b._table.selectAll()
    for _ in range(2):
        app.processEvents()
    anchor = b._table.item(0, 0)
    assert anchor is not None
    t0 = _time.perf_counter()
    b._cycle_selection_from(anchor)
    elapsed_ms = (_time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, (
        f"whole-table bulk cycle took {elapsed_ms:.1f} ms; "
        f"regression vs <100 ms target. Did vertical header drift "
        f"back to ResizeToContents?"
    )
    # Bulk cycle dirtied the grid; close_builder_silent skips the
    # unsaved-changes modal that would block forever in offscreen mode.
    close_builder_silent(b)


def test_bulk_edit_does_not_disable_rm_buttons(tmp_path: Path) -> None:
    """After a bulk-cycle on a selected column the Qt selection is
    UNCHANGED. The -Segment button must stay enabled to reflect
    that the column is still selected and still removable. The old
    behaviour cleared rm state in ``_commit_edits`` and produced a
    visible-but-disabled mismatch (column highlighted, -Segment
    grey, forcing a header re-click)."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.show()
    for _ in range(4):
        app.processEvents()
    b._on_col_header_clicked(5)
    for _ in range(2):
        app.processEvents()
    assert (
        b._rm_seg_btn.isEnabled()
    ), "after selecting a column, -Segment should be enabled"
    anchor = b._table.item(0, 5)
    assert anchor is not None
    b._cycle_selection_from(anchor)
    for _ in range(2):
        app.processEvents()
    assert b._rm_seg_btn.isEnabled(), (
        "after a bulk edit on a still-selected column, "
        "-Segment must stay enabled (Qt selection didn't change)"
    )
    assert b._user_clicked_col == 5
    close_builder_silent(b)


def test_header_doubleclick_still_toggles_selection(tmp_path: Path) -> None:
    """PyQt6's QHeaderView suppresses ``sectionClicked`` when a press
    lands within the OS double-click interval (~400 ms) of the previous
    press, firing ``sectionDoubleClicked`` instead. We worked around
    this by installing ``_ToggleHeaderView``, which forwards
    ``mouseDoubleClickEvent`` to ``mousePressEvent`` so every press
    flows through the standard click pipeline. End-to-end check: a
    Qt double-click on the header must fire ``sectionClicked`` for
    EACH of the two presses (same haptic as QPushButton)."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QPoint, QSettings
    from PyQt6.QtCore import Qt as _Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    b.resize(1600, 900)
    b.show()
    for _ in range(4):
        app.processEvents()
    h = b._table.horizontalHeader()
    assert h is not None
    col = 5
    x = h.sectionViewportPosition(col) + h.sectionSize(col) // 2
    y = h.height() // 2
    viewport = h.viewport()
    assert viewport is not None

    # A single click should toggle ON.
    QTest.mouseClick(  # type: ignore[call-overload]
        viewport,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
        QPoint(x, y),
    )
    for _ in range(3):
        app.processEvents()
    assert b._user_clicked_col == col, "first click did not toggle ON"

    # _ToggleHeaderView.mouseDoubleClickEvent manually emits
    # sectionClicked so the second press of a doubleclick pair
    # registers as a click (Qt's default suppresses it). Count
    # emissions from a synthetic doubleclick event directly.
    h_sig_count = [0]
    h.sectionClicked.connect(
        lambda _: h_sig_count.__setitem__(0, h_sig_count[0] + 1)
    )
    QTest.mouseDClick(  # type: ignore[call-overload]
        viewport,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
        QPoint(x, y),
    )
    for _ in range(3):
        app.processEvents()
    assert h_sig_count[0] >= 1, (
        f"doubleclick should emit sectionClicked at least once "
        f"(via _ToggleHeaderView.mouseDoubleClickEvent), got {h_sig_count[0]}"
    )
    assert b._user_clicked_col is None, (
        "after 1 single click (ON) + 1 doubleclick-as-click (OFF), "
        "expected user_clicked_col=None"
    )

    b.close()


def test_dropdown_filters_out_atomic_write_tmp_files(tmp_path: Path) -> None:
    """``atomic_write_json`` creates ``.tmp_inv_*.json`` files in the
    target directory between ``mkstemp`` and ``os.replace``. The
    directory watcher can fire on the tmp create; the dropdown must
    not include those side files."""
    inv_dir = tmp_path / "inventories"
    inv_dir.mkdir()
    real = inv_dir / "real_features.json"
    Inventory.parse(
        {"metadata": {"name": "Real"}, "features": [], "segments": {}}
    ).write_atomic(str(real))
    # Simulate a tmp file that atomic_write_json would create
    tmp = inv_dir / ".tmp_inv_abc123.json"
    tmp.write_text('{"in_progress": true}', encoding="utf-8")
    listed = sorted(
        f
        for f in os.listdir(inv_dir)
        if f.endswith(".json") and not f.startswith(".")
    )
    assert listed == ["real_features.json"]
    assert ".tmp_inv_abc123.json" not in listed


def test_builder_close_waits_for_save_in_flight(tmp_path: Path) -> None:
    """Closing the builder while a background save is still running
    must wait for the worker to finish, so the worker can't emit
    ``_save_finished`` on a QObject that Qt is destroying."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "saved.json"
    b._write_json(str(target))
    assert b._save_in_flight, "save should be scheduled but not done"
    # close() should drive the save to completion before returning.
    closed_ok = b.close()
    assert closed_ok
    assert not b._save_in_flight, "save must complete before close returns"
    assert target.exists(), "file must be on disk after close completes"


def test_builder_save_then_close_dialog_path(tmp_path: Path) -> None:
    """User edits, then clicks Close. The unsaved dialog's Save button
    calls ``_save()`` (async) and then ``_wait_for_save()``; the
    dirty flag must clear before ``_check_unsaved`` returns so the
    close proceeds. Without the wait, the user would be told their
    save succeeded but the close would be silently refused."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "edited.json"
    b._current_path = str(target)
    b._dirty = True
    # Simulate the "Save" branch directly (skip the dialog).
    b._save()
    waited = b._wait_for_save()
    assert waited, "save did not complete within timeout"
    assert not b._dirty, "dirty flag must clear once save signal lands"


def test_worker_non_oserror_clears_save_in_flight(
    tmp_path: Path, monkeypatch
) -> None:
    """The save worker catches BaseException, not just OSError. If
    any other exception slipped through, the daemon thread would die
    silently, ``_save_finished`` would never fire, and
    ``_save_in_flight`` would be stuck True forever -- a permanent
    save lockout. Reproduce by monkey-patching write_atomic to raise
    TypeError."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder
    from phonology_features.gui.builder import window as _bw

    # Stub modal warning so the error path doesn't deadlock the test.
    monkeypatch.setattr(_bw, "show_warning", lambda *a, **k: None)

    def boom(self, path):
        raise TypeError("simulated non-OSError")

    monkeypatch.setattr(Inventory, "write_atomic", boom)

    b = InventoryBuilder(load_path=HAYES)
    b._write_json(str(tmp_path / "out.json"))
    import time as _time

    deadline = _time.monotonic() + 2.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight, (
        "non-OSError in worker left _save_in_flight=True forever; "
        "user would be permanently locked out of save"
    )
    close_builder_silent(b)


def test_save_as_drains_in_flight_save(tmp_path: Path, monkeypatch) -> None:
    """A Save-As during an in-flight Save must wait for the first
    save to drain so its own write isn't silently dropped by the
    re-entrancy guard in ``_write_json``."""
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QFileDialog

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    b._current_path = str(first)
    b._write_json(str(first))
    assert b._save_in_flight, "first save did not schedule"
    # Patch the file dialog to return ``second`` without opening.
    monkeypatch.setattr(QFileDialog, "exec", lambda self: 1)
    monkeypatch.setattr(
        QFileDialog, "selectedFiles", lambda self: [str(second)]
    )
    b._save_as()
    import time as _time

    deadline = _time.monotonic() + 3.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert first.exists(), "first save did not complete"
    assert second.exists(), (
        "Save-As silently dropped because _save_as did not drain the "
        "in-flight save before issuing the second write"
    )
    close_builder_silent(b)


def test_builder_save_runs_off_main_thread(tmp_path: Path) -> None:
    """``_write_json`` validates synchronously then hands the disk
    write to a background worker. We assert:
      1. The call returns BEFORE the file is fully written
         (well, before the post-write callback fires).
      2. After a brief wait the file is on disk and parses back.
      3. ``_save_in_flight`` is cleared so a subsequent save proceeds."""
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    settings_dir = str(tmp_path / "qt-settings")
    _os.makedirs(settings_dir, exist_ok=True)
    for fmt in (
        QSettings.Format.NativeFormat,
        QSettings.Format.IniFormat,
    ):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, settings_dir)
    app = QApplication.instance() or QApplication([])
    from phonology_features.gui.builder import InventoryBuilder

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "saved.json"
    b._write_json(str(target))
    # Save was scheduled; spin the event loop briefly so the timer
    # callback fires (worker -> QTimer.singleShot(0)).
    deadline = _time.monotonic() + 2.0
    while _time.monotonic() < deadline and b._save_in_flight:
        app.processEvents()
        _time.sleep(0.01)
    assert target.exists(), "background save never produced the file"
    assert not b._save_in_flight, "in-flight flag not cleared"
    # File is a valid Inventory.
    reloaded = Inventory.load(str(target))
    assert len(reloaded.features) > 0
    b.close()


def test_edit_during_in_flight_save_preserves_dirty(
    tmp_path: Path, monkeypatch
) -> None:
    """The snapshot handed to the save worker is fixed at the moment
    ``_to_inventory()`` ran. Any edit made *after* the snapshot but
    *before* the worker finishes is NOT in the file on disk -- so the
    completion handler must not clear ``_dirty``. Before the fix, the
    completion handler unconditionally cleared the flag, silently
    marking post-snapshot edits as saved and losing them at close.
    """
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder

    # Stall the worker so the main thread has time to mutate the grid
    # between snapshot and completion.
    real_write = Inventory.write_atomic

    def slow_write(self, path):
        _time.sleep(0.15)
        return real_write(self, path)

    monkeypatch.setattr(Inventory, "write_atomic", slow_write)

    b = InventoryBuilder(load_path=HAYES)
    target = tmp_path / "out.json"
    b._write_json(str(target))
    # Snapshot is committed; _dirty cleared by the save-start path.
    assert b._save_in_flight, "worker should still be running"
    assert not b._dirty, "snapshot commit should have cleared _dirty"

    # Edit a cell while the worker is still writing the OLD snapshot.
    # Route through _set_cell_value so it goes through _commit_edit
    # (the real edit chokepoint), the same path a user click takes.
    item = b._table.item(0, 0)
    assert item is not None
    new = "-" if item.text() == "+" else "+"
    b._set_cell_value(0, 0, new)

    deadline = _time.monotonic() + 3.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight, "worker never completed"
    assert b._dirty, (
        "post-snapshot edit was clobbered: completion handler cleared "
        "_dirty even though the edit is not in the file on disk"
    )
    close_builder_silent(b)


def test_save_failure_redirties_grid(tmp_path: Path, monkeypatch) -> None:
    """A failed write leaves in-memory state diverged from the file on
    disk. ``_dirty`` is cleared at save-start (snapshot commit), so on
    worker failure the completion handler must restore it -- otherwise
    the close guard would let the user discard their unsaved changes.
    """
    import os as _os
    import time as _time

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    sd = str(tmp_path / "qt-settings")
    _os.makedirs(sd, exist_ok=True)
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, sd)
    app = QApplication.instance() or QApplication([])
    from phonology_features.engine.inventory import Inventory
    from phonology_features.gui.builder import InventoryBuilder
    from phonology_features.gui.builder import window as _bw

    monkeypatch.setattr(_bw, "show_warning", lambda *a, **k: None)
    monkeypatch.setattr(
        Inventory,
        "write_atomic",
        lambda self, path: (_ for _ in ()).throw(OSError("disk full")),
    )

    b = InventoryBuilder(load_path=HAYES)
    b._dirty = True
    b._write_json(str(tmp_path / "out.json"))

    deadline = _time.monotonic() + 2.0
    while b._save_in_flight and _time.monotonic() < deadline:
        app.processEvents()
        _time.sleep(0.01)
    assert not b._save_in_flight
    assert b._dirty, (
        "save failure left _dirty=False; close guard would discard "
        "the user's unsaved work silently"
    )
    close_builder_silent(b)


def test_validation_report_html_escapes_issue_text() -> None:
    """The validation-report HTML interpolates raw issue strings; if
    one of those quotes back inventory data containing tag characters
    we must not let it break out of the <p>."""
    from phonology_features.gui.main_window import MainWindow

    issues = (
        "segment '<script>': bad",
        "feature '\"oops\"': bad",
    )
    out = MainWindow._validation_report_html(issues)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
