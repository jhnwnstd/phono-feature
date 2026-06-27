"""Regression tests for the transactional / state-surface loopholes
closed in the inventory + analysis flows.

These pin behaviours the audit found broken: a surface (the FEAT query,
the inventory dropdown, the Class-tab tint) that fell out of sync with
the active inventory / engine after a mode toggle or a failed load.
"""

from __future__ import annotations

from phonology_features.gui.controllers.theme import ThemeController
from phonology_shared.presentation.palette import ClassState


def test_match_mode_toggle_preserves_feat_query(window) -> None:
    """H2: flipping strict<->wildcard must keep the active FEAT query,
    re-applying it onto the rebuilt rows (the rebuild used to wipe it)."""
    window._set_mode("feat_to_seg")
    for feat in list(window._feat_rows):
        window._selected_features[feat] = "+"
    queried = set(window._selected_features)
    assert queried, "fixture should surface some feature rows"

    window._toggle_match_mode()

    # Features the new mode still surfaces keep their query value; the
    # whole query is no longer emptied by the feature-pane rebuild.
    survivors = queried & set(window._feat_rows)
    assert survivors, "expected features to survive the mode toggle"
    for feat in survivors:
        assert window._selected_features.get(feat) == "+"
    assert window._selected_features, "query must not be wiped on toggle"


def test_failed_load_reverts_inventory_combo(window) -> None:
    """M1: a load that fails validation must leave the dropdown naming
    the inventory that is actually loaded, not the failed one."""
    loaded_path = window._current_path
    loaded_idx = window.inventory_combo.currentIndex()
    assert loaded_idx >= 0

    # The dropdown / Browse move the combo BEFORE the load; emulate that,
    # then load a path that fails (Inventory.load wraps OSError as a
    # ValidationError).
    window.inventory_combo.setCurrentIndex(0)
    window._load_path("/no/such/inventory_file_does_not_exist.json")

    assert window._current_path == loaded_path
    assert window.inventory_combo.currentIndex() == loaded_idx


def test_set_html_resets_class_tab_tint(window) -> None:
    """L4: the single-blob report sink (validation errors) carries no
    natural-class verdict, so it must clear a prior green/red Class-tab
    tint rather than leave it implying a verdict."""
    panel = window.analysis
    panel._apply_class_state(ClassState.NATURAL)
    assert panel._class_state == ClassState.NATURAL

    panel.set_html("<p>The grid does not satisfy the contract.</p>")

    assert panel._class_state == ClassState.NEUTRAL


def test_inventory_combo_restyle_matches_construction(window) -> None:
    """H6: the inventory dropdown must carry the same QSS after a theme
    restyle as it does at construction. Both paths route through
    ThemeController.combo_style(), so the box cannot jump its
    background or gain the drop-down subcontrol rule on the first
    theme / palette toggle (the restyle used to inline a divergent
    copy: panel bg + an extra drop-down rule)."""
    built = window.inventory_combo.styleSheet()
    assert built == ThemeController.combo_style()

    # A restyle at the SAME palette must reproduce the construction QSS
    # byte for byte; set_css then no-ops on the identical string.
    window._theme._restyle_toolbar()
    assert window.inventory_combo.styleSheet() == built
