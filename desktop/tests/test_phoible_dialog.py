"""Smoke tests for the desktop PHOIBLE picker dialog.

Pins the wiring contract between the dialog and the shared
:py:func:`materialize_phoible_inventory`:

* Dialog construction succeeds when the bundled snapshot is
  available; ``create_phoible_dialog`` returns ``None`` otherwise.
* Selecting a language populates the source list; selecting a
  source enables Load and previews segment counts.
* Clicking Load (or calling the click handler) populates
  :py:attr:`PhoibleDialog.chosen_inventory` with an
  :py:class:`~phonology_shared.data.inventory.Inventory` whose
  name and metadata match the shared materializer's contract.

Skipped when ``_phoible_data.generated.json`` is absent (developer
checkout that has never run ``web/scripts/bake_phoible.py``).
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from phonology_features.gui.phoible_dialog import (
    PhoibleDialog,
    create_phoible_dialog,
)


def _make_dialog(qapp: QApplication) -> PhoibleDialog:
    """Construct the dialog or skip if the PHOIBLE snapshot is
    absent. Centralised so each test gets the same skip semantics."""
    dialog = create_phoible_dialog()
    if dialog is None:
        pytest.skip(
            "PHOIBLE snapshot not baked; "
            "run `python web/scripts/bake_phoible.py` to enable."
        )
    return dialog


def test_create_returns_dialog_when_snapshot_available(
    qapp: QApplication,
) -> None:
    """The factory hands back a working dialog whenever the bundled
    snapshot files are present. The toolbar handler relies on the
    ``None`` return signalling absent data, so the test pins the
    happy path."""
    dialog = _make_dialog(qapp)
    assert isinstance(dialog, PhoibleDialog)
    assert dialog.chosen_inventory is None
    dialog.deleteLater()


def test_search_populates_results(qapp: QApplication) -> None:
    """Typing a language name lands matching results in the
    autocomplete list. Mirrors the web picker's debounced search;
    here we drive the debounce manually so the test does not depend
    on a QTimer wall-clock."""
    dialog = _make_dialog(qapp)
    try:
        dialog._search_edit.setText("Korean")
        dialog._run_search()
        assert dialog._results.count() > 0
        labels = [
            dialog._results.item(i).text()
            for i in range(dialog._results.count())
        ]
        assert any("Korean" in label for label in labels)
    finally:
        dialog.deleteLater()


def test_source_pick_enables_load_and_renders_preview(
    qapp: QApplication,
) -> None:
    """Selecting a language renders its source cards and the
    default source pick enables the Load button and writes a
    non-empty preview. Pins the dialog's reactive chain."""
    dialog = _make_dialog(qapp)
    try:
        dialog._search_edit.setText("Korean")
        dialog._run_search()
        # Activate the first matching language to drive the
        # source-list build.
        item = dialog._results.item(0)
        assert item is not None
        dialog._on_language_activated(item)
        assert dialog._sources.count() > 0
        # The widget pre-selects a default source on render, which
        # in turn fires currentItemChanged and enables Load.
        assert dialog._selected_inventory_id is not None
        assert dialog._load_btn.isEnabled()
        assert dialog._summary.text() != ""
        assert dialog._segments_label.text() != ""
    finally:
        dialog.deleteLater()


def test_load_click_materializes_inventory_via_shared_path(
    qapp: QApplication,
) -> None:
    """Clicking Load (driven via the slot here) routes through the
    shared :py:func:`materialize_phoible_inventory` and stamps the
    same name template + ``feature_source`` metadata the web side
    produces. This is the single-source-of-truth check."""
    dialog = _make_dialog(qapp)
    try:
        dialog._search_edit.setText("Korean")
        dialog._run_search()
        first = dialog._results.item(0)
        assert first is not None
        dialog._on_language_activated(first)
        inv_id = dialog._selected_inventory_id
        assert inv_id is not None
        dialog._on_load_clicked()
        inv = dialog.chosen_inventory
        assert inv is not None
        # Name follows ``<language> [(<dialect>)] [<source_short>]``;
        # we only check the bracketed source tag without pinning the
        # exact source default, which is data-driven (median
        # segment-count rule).
        assert inv.name.startswith("Korean")
        assert inv.name.endswith("]")
        # Provenance metadata is the contract the desktop and web
        # share; rendering the prefix verifies the materializer
        # composed it from this provider's version.
        assert inv.metadata["feature_source"].startswith(
            "PHOIBLE 2.0 / Korean"
        )
    finally:
        dialog.deleteLater()
