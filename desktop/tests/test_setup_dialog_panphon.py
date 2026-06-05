"""Tests for the New-inventory setup dialog's PanPhon integration.

Pins the dialog-side half of the bootstrap contract:

* The PanPhon entry appears in the preset combo when ``panphon`` is
  installed; the static presets ("Default (33)" and "Custom") still
  sit alongside it so the existing flows are not displaced.
* Selecting the PanPhon entry exposes a :py:class:`FeatureProvider`
  via :py:meth:`InputDialog.get_chosen_provider`, and pre-fills the
  features textarea with the provider's canonical names.
* Switching back to a static preset clears the chosen provider so
  the next Create-Grid press falls back to the user-typed feature
  list.

Skipped when ``panphon`` is absent. The non-PanPhon dialog path is
covered indirectly by every other builder test that exercises the
existing "Default (33)" preset.
"""

from __future__ import annotations

import pytest

pytest.importorskip("panphon")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from phonology_features.gui.builder.dialogs import InputDialog  # noqa: E402
from phonology_features.providers.panphon_provider import (  # noqa: E402
    PanPhonFeatureProvider,
)

PANPHON_LABEL = "PanPhon (auto-generate)"


def test_preset_combo_lists_panphon_after_static_presets(
    qapp: QApplication,
) -> None:
    """The combo must keep the static presets at the top and append
    the PanPhon entry. Pins the relative ordering so the user's
    muscle memory for picking ``Default (33)`` is not disrupted by
    the provider extension."""
    dlg = InputDialog()
    labels = [
        dlg.preset_combo.itemText(i) for i in range(dlg.preset_combo.count())
    ]
    assert labels[0] == "Default (33)"
    assert labels[1] == "Custom"
    assert PANPHON_LABEL in labels
    assert labels.index(PANPHON_LABEL) > labels.index("Custom")
    dlg.deleteLater()


def test_choosing_panphon_exposes_provider_and_fills_features(
    qapp: QApplication,
) -> None:
    """Switching to the PanPhon entry must (a) make
    ``get_chosen_provider`` return a provider with ``name == "PanPhon"``
    and (b) fill the features textarea with the same names the
    provider promises in ``feature_names()``. This is the round-trip
    the builder relies on when it calls ``provider.generate`` after
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


def test_switching_back_to_static_preset_clears_chosen_provider(
    qapp: QApplication,
) -> None:
    """Selecting PanPhon then switching back to ``Default (33)``
    must clear ``get_chosen_provider``. Otherwise the builder would
    call ``provider.generate`` on a path where the user explicitly
    asked for a static features-only preset."""
    dlg = InputDialog()
    dlg.preset_combo.setCurrentText(PANPHON_LABEL)
    assert dlg.get_chosen_provider() is not None
    dlg.preset_combo.setCurrentText("Default (33)")
    assert dlg.get_chosen_provider() is None
    dlg.preset_combo.setCurrentText("Custom")
    assert dlg.get_chosen_provider() is None
    dlg.deleteLater()
