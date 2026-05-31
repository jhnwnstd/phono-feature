"""Background save coordinator for the inventory builder.

Owns the save state machine: ``save_in_flight``, ``dirty``,
``draining_save`` flags, plus the QObject signals (``save_finished``,
``save_drained``) that carry the save worker's completion back to
the main thread.

A QObject subclass because pyqtSignal must be a class attribute on
a QObject. Holds a back reference to the InventoryBuilder so it can
call back into the grid serialization (``_to_inventory``) and the
existing modal helpers (``show_warning``, ``ask_question``). The
builder still owns the table widget, the undo stack, and the
inventory name; this controller owns only the save lifecycle.

Snapshot semantics: at the moment ``request_save`` runs,
``_to_inventory`` is captured synchronously (validation runs on the
main thread). The disk write happens on a worker thread. ``dirty``
is cleared at snapshot time. Any cell edit between snapshot and
worker completion re-dirties the grid via the normal edit chokepoint
(``_commit_edit``), so the post-completion handler does NOT touch
``dirty`` on the success path.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from phonology_engine.inventory import (
    Inventory,
    ValidationError,
)
from phonology_features._logging import get_logger
from phonology_features.gui.builder.dialogs import ask_question, show_warning

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QStatusBar

    from phonology_features.gui.builder.window import InventoryBuilder

_log = get_logger(__name__)


class _SaveController(QObject):
    """Save state machine + background worker coordinator.

    Public state (tests and the builder read/write these directly):
        save_in_flight: True between save start and worker completion.
        dirty: True when the in-memory grid has unsaved edits.
        draining_save: True while wait_for_save is running a nested
            QEventLoop (used to gate user-triggered file actions so
            they don't re-enter mid-drain).

    Public signals:
        save_finished(path, error): emitted from the save worker
            thread; Qt picks QueuedConnection automatically for
            cross-thread emit, so the slot runs on the main thread.
        save_drained(): emitted from _on_save_finished AFTER the
            state flags have settled, on the main thread.
            wait_for_save connects loop.quit to this so a worker
            that fired BEFORE the wait was set up still triggers the
            quit. The queued save_finished call dispatches inside
            the nested loop, runs _on_save_finished, and that emits
            save_drained direct-connect into the freshly-connected
            loop.quit slot. Connecting loop.quit to save_finished
            itself would miss this case because queued signals
            capture the slot list at emit time, so a slot connected
            after the emit never runs.
    """

    save_finished = pyqtSignal(str, str)
    save_drained = pyqtSignal()

    def __init__(
        self,
        builder: InventoryBuilder,
        status_bar: QStatusBar,
        snapshot: Callable[[], Inventory],
    ) -> None:
        super().__init__(builder)
        self._b = builder
        self._status = status_bar
        # Callback into the builder's grid serializer. Held as a
        # callable rather than a hard reference to a builder method
        # so the controller never has to know about the grid
        # internals.
        self._snapshot = snapshot
        self.save_in_flight: bool = False
        self.dirty: bool = False
        self.draining_save: bool = False
        self.save_finished.connect(self._on_save_finished)

    # ------------------------------------------------------------------
    # Save entry / completion
    # ------------------------------------------------------------------
    def request_save(self, path: str) -> None:
        """Save the grid via the shared Inventory contract.

        Validation + Inventory construction run on the main thread
        (they touch grid widgets); the actual disk write runs on a
        worker thread. Atomic write means an external reader sees
        either the old file or the new file, never a half-written
        one, regardless of how long the background write takes.

        On a slow / network disk this keeps the UI responsive: a
        ``json.dump`` + ``fsync`` on a remote share can freeze the
        window for hundreds of milliseconds. Re-entrancy guard
        (``save_in_flight``) drops a second click rather than
        racing two writers on the same path.

        Completion hops back to the main thread via the
        ``save_finished`` signal (QueuedConnection by default for
        cross-thread emit), so the worker never touches GUI state
        directly and the dirty flag / status text mutate only on
        the main thread.
        """
        basename = os.path.basename(path)
        if self.save_in_flight:
            _log.info("save rejected (already in flight): %s", basename)
            self._status.showMessage("Save already in progress; ignored.")
            return
        try:
            inventory = self._snapshot()
        except ValidationError as e:
            _log.warning(
                "save aborted: grid failed validation (%d issue%s)",
                len(e.issues),
                "" if len(e.issues) == 1 else "s",
            )
            show_warning(
                self._b,
                "Cannot save inventory",
                "The grid does not satisfy the inventory contract:\n\n"
                + "\n".join(f"• {issue}" for issue in e.issues),
            )
            return

        self.save_in_flight = True
        # Commit the snapshot to "being written" RIGHT HERE. Any edit
        # made between this point and worker completion goes through
        # _commit_edit, which re-sets dirty=True. Without this clear,
        # _on_save_finished unconditionally cleared dirty, silently
        # marking post-snapshot edits as saved and losing them on
        # close-without-save.
        self.dirty = False
        _log.info(
            "save start: %s (%d segments, %d features)",
            basename,
            len(inventory.segments),
            len(inventory.features),
        )
        self._status.showMessage(f"Saving {basename}...")

        def worker() -> None:
            # ``err`` defaults to a non-empty failure string so that if
            # a BaseException subclass propagates past the inner
            # ``except Exception`` (KeyboardInterrupt, SystemExit, or
            # any future BaseException-derived class), the ``finally``
            # below still emits a *failure* completion — the main
            # thread clears ``save_in_flight`` and the user is not
            # told "saved" when the file was not written. The string
            # is cleared to "" only on the success path inside try.
            err: str = "save interrupted unexpectedly"
            try:
                inventory.write_atomic(path)
                err = ""
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                _log.exception("save worker failed: %s", basename)
            finally:
                try:
                    self.save_finished.emit(path, err)
                except RuntimeError:
                    # The window was destroyed while we were still
                    # running (close drain timed out, Qt deleted the
                    # C++ widget). PyQt raises "wrapped C/C++ object
                    # has been deleted" on the daemon thread.
                    # Functionally fine (the app is already shutting
                    # down) but logging it avoids the silent thread
                    # death the finally block was added to prevent.
                    _log.debug(
                        "save worker: receiver destroyed before "
                        "completion emit: %s",
                        basename,
                    )

        threading.Thread(target=worker, daemon=True).start()

    def _on_save_finished(self, path: str, error: str) -> None:
        """Main-thread completion handler for the background save.
        ``error`` is empty on success, the ``str(OSError)`` otherwise.

        Branches structured as if/else (not early-return) so the
        ``save_drained.emit()`` at the end runs on BOTH paths.
        wait_for_save quits the nested loop only when this fires.
        """
        self.save_in_flight = False
        basename = os.path.basename(path)
        if error:
            # Snapshot didn't reach disk; in-memory state diverges
            # from the file. Re-dirty so the close guard and title
            # bar correctly reflect the unsaved state.
            self.dirty = True
            _log.warning("save failed: %s: %s", basename, error)
            show_warning(
                self._b,
                "Save failed",
                f"Could not write '{path}':\n{error}",
            )
        else:
            # Success: do NOT touch dirty. It was cleared at save
            # start; any edit made during the worker re-dirtied it
            # via _commit_edit (the single chokepoint every edit
            # path goes through), which is the authoritative source
            # of truth here.
            _log.info("save complete: %s", basename)
            self._status.showMessage(f"Saved to {basename}")
        self.save_drained.emit()

    # ------------------------------------------------------------------
    # Drain helpers (Save+Close, Save-As, post-close)
    # ------------------------------------------------------------------
    def wait_for_save(self, timeout_ms: int = 5000) -> bool:
        """Block on a nested QEventLoop until the background save
        completes or ``timeout_ms`` elapses. Returns True if the
        save finished, False on timeout.

        Used by check_unsaved (Save+Close flow), the Save-As path
        (drain before second write), and the builder's closeEvent
        (post-close cleanup). Without this, a window close while
        the save thread is still running would let the worker emit
        save_finished on a QObject that's being destroyed by Qt.
        """
        if not self.save_in_flight:
            return True
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        self.save_drained.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        self.draining_save = True
        try:
            loop.exec()
        finally:
            self.draining_save = False
            timer.stop()
            try:
                self.save_drained.disconnect(loop.quit)
            except TypeError:
                # Disconnect raises TypeError if the signal-slot pair
                # is no longer connected. Benign: nothing to clean up.
                pass
        return not self.save_in_flight

    def check_unsaved(self) -> bool:
        """Return True if it's OK to discard changes (or there are
        none). Used by the builder's closeEvent and the Open File
        flow."""
        if not self.dirty:
            return True
        reply = ask_question(
            self._b,
            "Unsaved changes",
            "You have unsaved changes. Discard them?",
            buttons=(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
            default=QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            # The builder's _save() handles "no current path -> Save
            # As" routing; route back through it rather than
            # duplicating the dialog logic here.
            self._b._save()
            # _save is async (background thread + signal). Block
            # until the worker finishes so ``not dirty`` reflects
            # the ACTUAL outcome. Without the wait, dirty is still
            # True at this point and Close would get refused even
            # though the user asked for Save+Close.
            self.wait_for_save()
            return bool(not self.dirty)
        return bool(reply == QMessageBox.StandardButton.Discard)
