"""Tests for the New-inventory setup dialog's PanPhon integration.

Pins the dialog-side half of the bootstrap contract:

* The PanPhon entry appears in the preset combo when ``panphon`` is
  installed and sits at the TOP as the auto-fill recommended
  default, with the static presets (Hayes, PHOIBLE, Custom)
  beneath it.
* Selecting the PanPhon entry exposes a :py:class:`FeatureProvider`
  via :py:meth:`InputDialog.get_chosen_provider`, and pre-fills the
  features textarea with the provider's canonical names.
* Switching back to a static preset clears the chosen provider so
  the next Create-Grid press falls back to the user-typed feature
  list.

Skipped when ``panphon`` is absent. The non-PanPhon dialog path is
covered indirectly by every other editor test that exercises the
Hayes / PHOIBLE / Custom static presets.
"""

from __future__ import annotations

import pytest

pytest.importorskip("panphon")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from phonology_features.gui.editor.dialogs import InputDialog  # noqa: E402
from phonology_features.providers.panphon_provider import (  # noqa: E402
    PanPhonFeatureProvider,
)

PANPHON_LABEL = "PanPhon (auto-fill)"


def test_preset_combo_lists_panphon_first_then_static_presets(
    qapp: QApplication,
) -> None:
    """PanPhon is the recommended auto-fill option and sits at the
    top of the combo; the static presets (Hayes, PHOIBLE, Custom)
    follow underneath in their FEATURE_PRESETS insertion order."""
    dlg = InputDialog()
    labels = [
        dlg.preset_combo.itemText(i) for i in range(dlg.preset_combo.count())
    ]
    assert labels[0] == PANPHON_LABEL
    assert labels[1:] == ["Hayes", "PHOIBLE", "Custom"]
    dlg.deleteLater()


def test_accept_blocks_when_panphon_chosen_with_empty_segments(
    qapp: QApplication, mocker
) -> None:
    """Robustness pin: picking PanPhon with the segments box empty
    must not accept the dialog. Otherwise the editor would run
    ``provider.generate([])`` and present the user with a
    0-segment grid that fails save-time validation downstream.
    The dialog instead surfaces a provider-specific warning, names
    the provider in the message, and leaves itself open."""
    from PyQt6.QtWidgets import QDialog, QMessageBox

    warn = mocker.patch.object(QMessageBox, "warning")
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    assert dlg.get_chosen_provider() is not None
    dlg.seg_edit.clear()
    dlg.accept()
    warn.assert_called_once()
    title, body = warn.call_args.args[1], warn.call_args.args[2]
    assert title == "No segments found"
    assert "PanPhon" in body
    assert dlg.result() != QDialog.DialogCode.Accepted
    dlg.deleteLater()


def test_accept_passes_when_panphon_chosen_with_segments(
    qapp: QApplication, mocker
) -> None:
    """Sanity opposite: with PanPhon selected and at least one
    segment, accept must dismiss the dialog. Pins that the
    provider-specific empty-segments check does NOT introduce a
    regression that blocks the happy path."""
    from PyQt6.QtWidgets import QDialog, QMessageBox

    warn = mocker.patch.object(QMessageBox, "warning")
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    dlg.name_edit.setText("Round Trip")
    dlg.seg_edit.setPlainText("p b i")
    dlg.accept()
    warn.assert_not_called()
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.deleteLater()


def test_accept_passes_when_panphon_features_box_cleared(
    qapp: QApplication, mocker
) -> None:
    """When PanPhon is the chosen preset the features textarea is
    auto-filled; if the user wipes it, validation must still pass
    because the editor will use the provider's canonical feature
    names regardless. Otherwise the user sees a misleading "No
    features found" error for a path where features are
    provider-supplied."""
    from PyQt6.QtWidgets import QDialog, QMessageBox

    warn = mocker.patch.object(QMessageBox, "warning")
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    dlg.name_edit.setText("Features Cleared")
    dlg.seg_edit.setPlainText("p b")
    dlg.feat_edit.clear()
    dlg.accept()
    warn.assert_not_called()
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.deleteLater()


def test_choosing_panphon_exposes_provider_and_fills_features(
    qapp: QApplication,
) -> None:
    """Switching to the PanPhon entry must (a) make
    ``get_chosen_provider`` return a provider with ``name == "PanPhon"``
    and (b) fill the features textarea with the same names the
    provider promises in ``feature_names()``. This is the round-trip
    the editor relies on when it calls ``provider.generate`` after
    the dialog accepts."""
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)

    provider = dlg.get_chosen_provider()
    assert provider is not None
    assert provider.name == "PanPhon"

    typed_features = dlg.get_features()
    expected = list(PanPhonFeatureProvider().feature_names())
    assert typed_features == expected
    dlg.deleteLater()


def test_features_textarea_trims_to_used_features_when_segments_typed(
    qapp: QApplication,
) -> None:
    """The features preview must reflect the same pruning the grid
    will get. Typing a single vowel must not advertise all 24
    PanPhon features, because the resulting grid will only contain
    the features that vowel actually uses. Pins the dialog/grid
    parity the user asked for: what you see in the setup textarea
    matches what you get in the editor."""
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    provider = dlg.get_chosen_provider()
    assert provider is not None
    full = set(provider.feature_names())

    # No segments yet: full set is shown so the user has a preview.
    preview_empty = set(dlg.get_features())
    assert preview_empty == full

    # Typing a single vowel triggers the debounce timer; bypass it
    # by invoking the refresh directly (the timer fires the same
    # callback after 250 ms in interactive use).
    dlg.seg_edit.setPlainText("i")
    dlg._refresh_provider_features()

    trimmed = set(dlg.get_features())
    assert trimmed.issubset(full)
    assert trimmed != full, (
        "single-vowel input must drop the features /i/ does not "
        "specify; otherwise dialog and grid disagree on what the "
        "saved inventory will contain"
    )
    # Major-class features that any segment carries: must survive.
    assert {"Syllabic", "Consonantal"}.issubset(trimmed)

    # Erasing the segments must expand the preview back to the full
    # canonical set so the user sees the whole catalogue again.
    dlg.seg_edit.clear()
    dlg._refresh_provider_features()
    assert set(dlg.get_features()) == full
    dlg.deleteLater()


def test_switching_to_static_preset_cancels_pending_provider_refresh(
    qapp: QApplication,
) -> None:
    """If the user picks PanPhon, types segments (arming the debounce
    timer), then switches to ``Hayes``, the pending provider
    refresh must not fire over the static preset's features. Without
    the explicit ``stop()`` the static preset would briefly flicker
    to a trimmed PanPhon set when the timer eventually fired."""
    from phonology_shared.editor.setup import FEATURE_PRESETS

    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    dlg.seg_edit.setPlainText("i")
    assert dlg._provider_refresh_timer.isActive()

    dlg.preset_combo.setCurrentText("Hayes")
    assert not dlg._provider_refresh_timer.isActive()
    # Static preset must own the features list.
    assert dlg.get_features() == list(FEATURE_PRESETS["Hayes"])
    dlg.deleteLater()


def test_switching_back_to_static_preset_clears_chosen_provider(
    qapp: QApplication,
) -> None:
    """Selecting PanPhon then switching back to ``Hayes``
    must clear ``get_chosen_provider``. Otherwise the editor would
    call ``provider.generate`` on a path where the user explicitly
    asked for a static features-only preset."""
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    assert dlg.get_chosen_provider() is not None
    dlg.preset_combo.setCurrentText("Hayes")
    assert dlg.get_chosen_provider() is None
    dlg.preset_combo.setCurrentText("Custom")
    assert dlg.get_chosen_provider() is None
    dlg.deleteLater()
