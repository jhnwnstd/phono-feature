"""Pin :py:meth:`MainWindow._open_editor` for the open-close-reopen
lifecycle.

Before the lifecycle fix landed, ``_open_editor`` overwrote
``self._editor`` when the existing editor was not currently
visible (e.g. user closed it but Qt had not yet GC'd it). The new
construction would land, but the field would point to a fresh
instance while the prior editor still lingered on the heap with
its ``_save_finished`` connection. The fix in
:py:meth:`MainWindow._open_editor` explicitly drops the stale
reference via ``deleteLater()`` and ``self._editor = None`` BEFORE
constructing the new one, and wires ``destroyed`` to a slot that
resets the field on eventual C++ teardown. This test pins the
"reopen replaces the reference" half of the contract.
"""

from __future__ import annotations


def test_open_close_reopen_replaces_editor_reference(window, qapp) -> None:
    """Open the editor, close it, reopen it. The reference must
    point at the freshly-constructed editor, not the prior one
    that the user closed."""
    window._open_editor()
    first = window._editor
    assert first is not None and first.isVisible()

    # Close the editor. Qt hides it; ``WA_DeleteOnClose`` is not
    # set on InventoryEditor so the C++ object lives on until
    # MainWindow's stale-ref cleanup in ``_open_editor`` runs
    # ``deleteLater()`` on the next open call.
    first._dirty = False  # silence the unsaved-changes modal
    first._save_in_flight = False
    first.close()
    qapp.processEvents()
    # After close, the field still points at the closed (but not
    # yet destroyed) instance. The cleanup runs at the next open.
    assert window._editor is first

    window._open_editor()
    second = window._editor
    assert second is not None
    assert second is not first, (
        "reopen must construct a new editor, not reuse the closed "
        "predecessor; field must hold the live editor"
    )
    # Pump events so the prior editor's deferred deletion runs;
    # nothing must crash even though ``_on_editor_destroyed``
    # would fire on a field that has already moved on to the new
    # editor (the slot guards by always resetting to None).
    qapp.processEvents()

    second._dirty = False
    second._save_in_flight = False
    second.close()
    qapp.processEvents()


def test_open_visible_editor_raises_existing(window, qapp) -> None:
    """When the editor is already visible, ``_open_editor`` must
    raise / focus it rather than constructing a new instance.
    Pins the early-return at the top of the lifecycle path.
    """
    window._open_editor()
    first = window._editor
    assert first is not None and first.isVisible()

    window._open_editor()
    second = window._editor
    assert second is first, (
        "a still-visible editor must be re-raised in place; "
        "constructing a second instance would orphan the first"
    )

    first._dirty = False
    first._save_in_flight = False
    first.close()
    qapp.processEvents()
