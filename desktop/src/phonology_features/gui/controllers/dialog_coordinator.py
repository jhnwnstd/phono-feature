"""Modal-dialog and Editor coordination for :class:`MainWindow`.

Owns the Browse and PHOIBLE-picker launchers and the embedded Editor's
open / raise / close / save lifecycle, keeping that Qt plumbing out of
MainWindow. The inventory load + engine swap stay on MainWindow (engine
+ session state live there); this only launches the dialogs and routes
their results back through ``_load_path`` / ``_adopt_phoible_inventory``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog

from phonology_features._logging import get_logger
from phonology_features.gui.editor.dialogs import center_on_parent

if TYPE_CHECKING:
    from phonology_features.gui.editor import InventoryEditor
    from phonology_features.gui.main_window import MainWindow

_log = get_logger(__name__)


class DialogCoordinator:
    """Launch the Browse / PHOIBLE dialogs and own the Editor window
    lifecycle for one MainWindow."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window
        self._editor: InventoryEditor | None = None

    @property
    def editor(self) -> InventoryEditor | None:
        """The live Editor window, or ``None`` when none is open."""
        return self._editor

    def browse_inventory(self) -> None:
        """Open a file dialog and load the chosen JSON."""
        dlg = QFileDialog(
            self._w, "Open Phonological Inventory", "", "JSON Files (*.json)"
        )
        dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        center_on_parent(dlg, self._w)
        if not dlg.exec():
            return
        path = dlg.selectedFiles()[0] if dlg.selectedFiles() else ""
        if not path:
            return
        combo = self._w.inventory_combo
        idx = combo.findData(path)
        if idx < 0:
            pretty = os.path.splitext(os.path.basename(path))[0]
            pretty = pretty.replace("_", " ").title()
            combo.addItem(pretty, userData=path)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        self._w._load_path(path)

    def open_phoible_picker(self) -> None:
        """Open the PHOIBLE inventory picker and adopt the chosen
        language inventory into the active engine.

        Mirrors the web's toolbar PHOIBLE button. All non-Qt composition
        (search, list, generate, name + metadata stamp,
        ``Inventory.from_grid``) lives in shared so the two UIs produce
        the same ``Inventory`` from the same picker selection. Falls back
        to a status-bar message when the PHOIBLE snapshot is absent on
        this checkout; the dialog is never shown in that case.
        """
        from phonology_features.gui.phoible_dialog import (
            create_phoible_dialog,
        )

        dialog = create_phoible_dialog(self._w)
        if dialog is None:
            self._w.status.showMessage(
                "PHOIBLE data not available; run "
                "``python web/scripts/bake_phoible.py`` to enable."
            )
            return
        if not dialog.exec():
            return
        inventory = dialog.chosen_inventory
        if inventory is None:
            return
        self._w._adopt_phoible_inventory(inventory)

    def open_editor(self) -> None:
        """Open (or raise) the Editor window. Edits the current inventory
        in place if one is loaded; otherwise shows the new-inventory
        setup dialog.

        The Editor is window-modal against MainWindow. While it is open
        the user can't toggle the theme (the Editor's palette-dependent
        chrome isn't rebuilt on theme changes), which avoids a
        half-restyled state.
        """
        if self._editor is not None and self._editor.isVisible():
            self._editor.raise_()
            self._editor.activateWindow()
            return
        # Drop any stale (closed-but-not-yet-deleted) editor and
        # disconnect its signals first, otherwise a still-running save
        # could fire _on_editor_save_finished after the new editor is
        # wired to the same slot, and the old editor's eventual
        # ``destroyed`` would null out the reference to the new one.
        if self._editor is not None:
            for signal, slot in (
                (self._editor._save_finished, self._on_editor_save_finished),
                (self._editor.destroyed, self._on_editor_destroyed),
            ):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            self._editor.deleteLater()
            self._editor = None

        from phonology_features.gui.editor import InventoryEditor

        current_path = self._w._inv_dir.current_path
        if current_path:
            editor = InventoryEditor(parent=self._w, load_path=current_path)
        elif self._w.engine is not None:
            # In-memory inventory with no backing file (PHOIBLE load).
            # Seed the editor from the live engine; Save routes through
            # Save As since there is no path to overwrite.
            editor = InventoryEditor(parent=self._w)
            editor.load_inventory(self._w.engine.inventory)
        else:
            editor = InventoryEditor(parent=self._w)
            if not editor.show_setup_dialog():
                editor.deleteLater()
                return

        editor.setWindowFlag(Qt.WindowType.Window)
        editor.setWindowModality(Qt.WindowModality.WindowModal)
        editor._save_finished.connect(self._on_editor_save_finished)
        editor.destroyed.connect(self._on_editor_destroyed)
        self._editor = editor
        self._editor.show()

    def _on_editor_destroyed(self, _obj: object) -> None:
        """Reset the cached editor reference once Qt finishes destroying
        it, so the next open builds a fresh instance."""
        self._editor = None

    def _on_editor_save_finished(self, path: str, err: str) -> None:
        """Switch the main viewer to a freshly-saved editor file when it
        differs from the current one (new author, or Save As). A
        same-path save is left to the directory watcher's auto-reload so
        the user's analysis state isn't cleared twice.
        """
        if err:
            return  # editor already showed its own error dialog
        if path == self._w._inv_dir.current_path:
            return  # same-path save, watcher will refresh
        if os.path.isfile(path):
            _log.info(
                "switching to inventory saved from editor: %s",
                os.path.basename(path),
            )
            self._w._load_path(path)

    def drop_editor(self) -> None:
        """Destroy and forget the Editor window. Called on a theme
        toggle, whose palette-dependent chrome the Editor does not
        rebuild; modality means it is never open at that point, so this
        never destroys an in-use window."""
        if self._editor is not None:
            self._editor.deleteLater()
            self._editor = None

    def try_close_editor(self) -> bool:
        """Let a visible Editor prompt for unsaved changes on app close.

        Returns ``False`` if the editor refused to close (the user
        cancelled), so the caller can abort the window close; ``True``
        when there is nothing to close or it closed cleanly.
        """
        if self._editor is not None and self._editor.isVisible():
            return self._editor.close()
        return True
