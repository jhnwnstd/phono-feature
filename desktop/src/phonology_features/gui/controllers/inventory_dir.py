"""Inventory-directory ownership for :class:`MainWindow`:
filesystem watcher with a 600 ms debounce, MRU list for the
delete-fallback path, and dropdown population (with a stale-
tmp-file sweep). The boundary between "files changed on disk"
and "load this path". The actual load stays on MainWindow
because it touches engine state, the status bar, and the
analysis pane.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QFileSystemWatcher, QTimer
from PyQt6.QtGui import QStandardItemModel

from phonology_features._logging import get_logger
from phonology_features._settings import SettingsKey, write_setting
from phonology_shared.editor.setup import inventory_display_label
from phonology_shared.presentation.constants import inventory_sort_key

if TYPE_CHECKING:
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QComboBox

    from phonology_features.gui.main_window import MainWindow
    from phonology_shared.data.inventory import Inventory

#: Prefix marking a dropdown entry as a session PHOIBLE inventory.
#: The combo's userData is otherwise an absolute file path, so this
#: string namespace cannot collide. It MUST be a string, not a tuple:
#: ``QComboBox.findData`` cannot match tuple userData against the
#: dropdown's ``QStandardItemModel`` (it silently returns -1), which
#: broke selecting a just-loaded PHOIBLE inventory.
_PHOIBLE_KEY_PREFIX = "phoible::"


def phoible_entry_key(name: str) -> str:
    """Combo userData for a session PHOIBLE entry named ``name``."""
    return f"{_PHOIBLE_KEY_PREFIX}{name}"


def phoible_entry_name(data: object) -> str | None:
    """The PHOIBLE inventory name in a combo userData value, or
    ``None`` when the value is a file path (bundled / saved entry)."""
    if isinstance(data, str) and data.startswith(_PHOIBLE_KEY_PREFIX):
        return data[len(_PHOIBLE_KEY_PREFIX) :]
    return None


_log = get_logger(__name__)

# Cap on MRU history. ~10 covers any realistic switching pattern;
# beyond that the oldest entries are stale enough that the user
# probably doesn't want to fall back to them anyway.
_MRU_CAP: int = 10

# Watcher debounce: many editors delete-then-write rather than
# truncate-and-overwrite, which fires the watcher twice in quick
# succession. The timer coalesces those into one reload.
_RELOAD_DEBOUNCE_MS: int = 600

# Delay before re-adding a path to the watcher after a fileChanged
# fires. Vim and a few other editors implement save as ``unlink +
# rename``; the original inode is gone for the duration of the swap,
# so an immediate ``addPath`` finds nothing and the watcher silently
# drops. 200 ms is long enough for the rename to land in every
# editor we've tested but short enough that the user doesn't
# perceive lag on the next save.
_WATCHER_REARM_DELAY_MS: int = 200

# Stale tmp-file age threshold. Atomic writes complete in
# milliseconds; anything older than an hour is from a crashed save.
_TMP_FILE_STALE_SECONDS: int = 3600


def _read_metadata_name(path: str) -> str | None:
    """Best-effort read of an inventory's ``metadata.name`` (or
    top-level ``name``) so the dropdown label matches what the web
    build precomputes. Any parse / IO failure returns ``None`` and
    the shared helper falls back to a filename-derived label.
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    meta = raw.get("metadata") or {}
    candidate = meta.get("name") if isinstance(meta, dict) else None
    if candidate is None:
        candidate = raw.get("name")
    return candidate if isinstance(candidate, str) else None


def _is_visible_inventory_file(fname: str) -> bool:
    """True for files that should appear in the dropdown.

    Skips dotfiles (.tmp_inv_*.json side-files from atomic writes,
    editor swap files), non-JSON, and underscore-prefixed siblings
    used for schema or other metadata that lives alongside the
    inventories but isn't itself an inventory.
    """
    if fname.startswith(".") or fname.startswith("_"):
        return False
    return fname.endswith(".json")


class InventoryDirController:
    """Owns the inventory-directory watcher, dropdown, and MRU
    fallback. MainWindow forwards inventory load/register calls
    through this controller."""

    def __init__(
        self,
        window: MainWindow,
        settings: QSettings,
        inventory_combo: QComboBox,
    ) -> None:
        self._w = window
        self._settings = settings
        self._combo = inventory_combo
        # Path of the currently-loaded on-disk inventory, owned here:
        # ``register_loaded_path`` is the sole setter, the watcher logic
        # reads/clears it internally, and MainWindow reads it through
        # ``current_path``. ``None`` when nothing on-disk is loaded
        # (startup, or after a PHOIBLE-only swap).
        self._path: str | None = None
        # Public: tests read this directly. MRU of paths the user
        # has loaded, deduplicated, capped. Not persisted across
        # sessions (starts empty each launch).
        self.recent_paths: list[str] = []
        # Session cache of PHOIBLE-loaded inventories, keyed by
        # display name. Rendered as a "PHOIBLE" group at the END of
        # the dropdown so a once-searched inventory can be reloaded
        # without reopening the picker, while staying visually apart
        # from the on-disk entries (it becomes a regular entry once
        # the user saves it locally). Insertion-ordered; not
        # persisted across sessions.
        self.phoible_inventories: dict[str, Inventory] = {}
        # Parent set to the window so the watcher / timer get torn
        # down when MainWindow closes.
        self._watcher = QFileSystemWatcher(window)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._reload_timer = QTimer(window)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(_RELOAD_DEBOUNCE_MS)
        self._reload_timer.timeout.connect(self._do_auto_reload)
        # Start watching the bundled inventories directory so saves
        # from the Editor (or external edits) appear in the
        # dropdown live.
        inventories_dir = self.get_inventories_dir()
        if (
            os.path.isdir(inventories_dir)
            and inventories_dir not in self._watcher.directories()
        ):
            self._watcher.addPath(inventories_dir)
        # Fill the combo on construction so MainWindow's toolbar
        # build sequence doesn't need a separate populate call.
        self.populate_dropdown()

    # ------------------------------------------------------------------
    # Paths / sweep
    # ------------------------------------------------------------------
    @staticmethod
    def get_inventories_dir() -> str:
        """Absolute path to the bundled ``inventories/`` directory.
        Resolves four levels up from this file
        (``desktop/src/phonology_features/gui/controllers/``) to ``desktop/``.
        """
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "..",
                "inventories",
            )
        )

    @staticmethod
    def sweep_stale_tmp_files(directory: str) -> None:
        """Remove ``.tmp_inv_*.json`` files older than 1 hour from
        ``directory``. These are atomic-write side files that were
        orphaned because a previous save was killed between
        ``mkstemp`` and ``os.replace``. They're hidden from the
        dropdown by the filter below, but without sweeping they
        accumulate forever across crashes. The 1-hour age threshold
        is well past any legitimate in-flight save (atomic writes
        complete in milliseconds), so the sweep never touches an
        active operation.

        Failures are swallowed silently: the dropdown population
        must succeed even when the inventories directory is
        read-only or partially permissioned.
        """
        cutoff = time.time() - _TMP_FILE_STALE_SECONDS
        try:
            entries = os.listdir(directory)
        except OSError:
            return
        for fname in entries:
            if not (fname.startswith(".tmp_inv_") and fname.endswith(".json")):
                continue
            path = os.path.join(directory, fname)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                # Race with another save, permission denied, file
                # vanished. All benign for an opportunistic sweep.
                continue

    # ------------------------------------------------------------------
    # Dropdown
    # ------------------------------------------------------------------
    def populate_dropdown(self) -> None:
        """Scan ``inventories/`` and fill the dropdown. Preserves the
        current selection if the previously-loaded path still exists
        after the rescan (matters when the Editor saves a new file
        and the directory watcher triggers a refresh).
        """
        previous_path = self._combo.currentData()
        self._combo.blockSignals(True)
        try:
            self._combo.clear()
            self._combo.addItem("Select inventory…", userData=None)
            # Disable the placeholder row so it can't be picked.
            model = self._combo.model()
            placeholder = (
                model.item(0)
                if isinstance(model, QStandardItemModel)
                else None
            )
            if placeholder is not None:
                placeholder.setEnabled(False)
            inventories_dir = self.get_inventories_dir()
            if os.path.isdir(inventories_dir):
                self.sweep_stale_tmp_files(inventories_dir)
                entries: list[tuple[str, str, str]] = []
                for fname in os.listdir(inventories_dir):
                    # Skip dotfiles (.tmp_inv_*.json side files from
                    # atomic writes are visible to the watcher for
                    # ~ms between mkstemp and os.replace; editor swap
                    # files); skip underscore-prefixed siblings like
                    # ``_schema.json`` that live alongside inventories
                    # but aren't loadable themselves.
                    if not _is_visible_inventory_file(fname):
                        continue
                    path = os.path.join(inventories_dir, fname)
                    label = inventory_display_label(
                        fname=fname,
                        metadata_name=_read_metadata_name(path),
                    )
                    entries.append((fname, path, label))
                # Hayes default first, then any other Hayes, then
                # alphabetical: shared with the web manifest build via
                # inventory_sort_key so both dropdowns match.
                entries.sort(key=lambda e: inventory_sort_key(e[0], e[2]))
                for _fname, path, label in entries:
                    self._combo.addItem(label, userData=path)
            self._append_phoible_section()
            idx = self._combo.findData(previous_path) if previous_path else 0
            self._combo.setCurrentIndex(max(idx, 0))
        finally:
            self._combo.blockSignals(False)

    def _append_phoible_section(self) -> None:
        """Append the session's PHOIBLE entries under a disabled
        "PHOIBLE" heading at the end of the dropdown. No-op when
        nothing has been loaded from the picker yet."""
        if not self.phoible_inventories:
            return
        self._combo.insertSeparator(self._combo.count())
        self._combo.addItem("PHOIBLE", userData=None)
        model = self._combo.model()
        if isinstance(model, QStandardItemModel):
            header = model.item(self._combo.count() - 1)
            if header is not None:
                header.setEnabled(False)
        for name in self.phoible_inventories:
            self._combo.addItem(name, userData=phoible_entry_key(name))

    def add_phoible_entry(self, inventory: Inventory) -> None:
        """Cache a picker-loaded PHOIBLE inventory and select its
        dropdown entry. Re-loading the same inventory just refreshes
        the cached object."""
        self.phoible_inventories[inventory.name] = inventory
        self.populate_dropdown()
        idx = self._combo.findData(phoible_entry_key(inventory.name))
        if idx >= 0:
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(idx)
            self._combo.blockSignals(False)

    def get_phoible_entry(self, name: str) -> Inventory | None:
        """Cached PHOIBLE inventory for a dropdown entry, if any."""
        return self.phoible_inventories.get(name)

    # ------------------------------------------------------------------
    # Load registration / MRU
    # ------------------------------------------------------------------
    @property
    def current_path(self) -> str | None:
        """Path of the currently-loaded on-disk inventory (read-only;
        :py:meth:`register_loaded_path` is the canonical setter)."""
        return self._path

    def clear_current_path(self) -> None:
        """Forget the on-disk path, e.g. after a PHOIBLE swap that has
        no backing file."""
        self._path = None

    def register_loaded_path(self, path: str) -> None:
        """Wire watcher, dropdown, and settings for a newly-loaded
        path. Called by MainWindow._load_path after a successful
        inventory load."""
        if self._path and self._path != path:
            self._watcher.removePath(self._path)
            old_dir = os.path.dirname(os.path.abspath(self._path))
            new_dir = os.path.dirname(os.path.abspath(path))
            # The bundled inventories dir is a permanent watch target
            # (added once in __init__) so Editor saves into it always
            # refresh the dropdown. Never drop it when navigating to an
            # out-of-tree file, or the dropdown stops live-updating for
            # bundled inventories until the next in-tree load.
            bundled_dir = os.path.normpath(
                os.path.abspath(self.get_inventories_dir())
            )
            if old_dir != new_dir and old_dir != bundled_dir:
                self._watcher.removePath(old_dir)
        self._path = path
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        parent_dir = os.path.dirname(os.path.abspath(path))
        if parent_dir not in self._watcher.directories():
            self._watcher.addPath(parent_dir)
        idx = self._combo.findData(path)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        write_setting(self._settings, SettingsKey.LAST_INVENTORY, path)
        # Push to MRU front for delete-fallback. Dedup so a repeated
        # load doesn't push the same path twice. Cap so the list
        # doesn't grow unbounded over a long session.
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self.recent_paths.insert(0, path)
        del self.recent_paths[_MRU_CAP:]

    def pick_fallback_after_delete(self, deleted_path: str) -> str | None:
        """Choose what to load when ``deleted_path`` has been removed
        from disk while it was the current inventory. Priority:

        1. Most recent previously-opened inventory that still exists
           (skipping the deleted one itself).
        2. First file in the bundled inventories directory (sorted).
        3. None if nothing's available. Caller falls back to the
           "no inventory loaded" placeholder.
        """
        for path in self.recent_paths:
            if path == deleted_path:
                continue
            if os.path.isfile(path):
                return path
        inv_dir = self.get_inventories_dir()
        if os.path.isdir(inv_dir):
            for fname in sorted(os.listdir(inv_dir)):
                if not _is_visible_inventory_file(fname):
                    continue
                return os.path.join(inv_dir, fname)
        return None

    # ------------------------------------------------------------------
    # Watcher signal handlers
    # ------------------------------------------------------------------
    def _on_file_changed(self, path: str) -> None:
        """Called by QFileSystemWatcher when the watched file
        changes."""
        # Some editors remove and recreate the file; re-add if
        # needed (see _WATCHER_REARM_DELAY_MS).
        QTimer.singleShot(
            _WATCHER_REARM_DELAY_MS,
            lambda: (
                self._watcher.addPath(path)
                if path not in self._watcher.files()
                else None
            ),
        )
        self._reload_timer.start()

    def _on_directory_changed(self, directory: str) -> None:
        """Watched directory changed (file created / renamed /
        deleted). Refresh the dropdown if the inventories dir
        changed; re-arm the file watcher if the current file
        reappeared after a delete-then-write editor cycle. If the
        currently-loaded file was deleted, fall back to the
        most-recent previously-opened inventory (or the first one
        in the directory) so the viewer doesn't sit on a dangling
        reference.
        """
        # Cancel any pending file-watcher debounce: if we're about
        # to load synchronously (fallback after delete) or re-arm
        # the watcher ourselves below, letting an earlier 600 ms
        # timer also fire would reload the file twice. The two
        # paths that need it (re-arm at the bottom, fallback load)
        # re-start it explicitly when appropriate.
        self._reload_timer.stop()
        if os.path.normpath(directory) == self.get_inventories_dir():
            self.populate_dropdown()
        if not self._path:
            return
        if not os.path.isfile(self._path):
            # Current inventory was deleted under us (most often
            # via Editor Delete). Pick a fallback so the viewer
            # doesn't continue showing stale data with a
            # missing-file path. pick_fallback_after_delete prefers
            # an MRU neighbour; if none survives, it picks the
            # first file in the inventories dir; if none of those
            # either, returns None and we clear current_path.
            deleted = self._path
            fname = os.path.basename(deleted)
            _log.info("current inventory deleted on disk: %s", fname)
            fallback = self.pick_fallback_after_delete(deleted)
            self._path = None
            self._settings.remove(str(SettingsKey.LAST_INVENTORY))
            if fallback is not None:
                _log.info("falling back to: %s", os.path.basename(fallback))
                self._w._load_path(fallback)
            else:
                # Nothing to fall back to. Reset the dropdown to
                # the placeholder.
                self._combo.setCurrentIndex(0)
                self._w.status.showMessage(
                    f"Deleted “{fname}”; no other " f"inventories available."
                )
            return
        if self._path not in self._watcher.files():
            self._watcher.addPath(self._path)
            self._reload_timer.start()

    def _do_auto_reload(self) -> None:
        """Reload the current inventory after the watcher debounce
        fires."""
        path = self._path
        if path and os.path.isfile(path):
            fname = os.path.basename(path)
            _log.info("auto-reload (watcher fired): %s", fname)
            self._w._load_path(path)
            self._w.status.showMessage(f"Auto-reloaded “{fname}”")
