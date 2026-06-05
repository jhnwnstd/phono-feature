"""Pin :py:meth:`MainWindow._open_builder` for the open-close-reopen
lifecycle.

Before the lifecycle fix landed, ``_open_builder`` overwrote
``self._builder`` when the existing builder was not currently
visible (e.g. user closed it but Qt had not yet GC'd it). The new
construction would land, but the field would point to a fresh
instance while the prior builder still lingered on the heap with
its ``_save_finished`` connection. The fix in
:py:meth:`MainWindow._open_builder` explicitly drops the stale
reference via ``deleteLater()`` and ``self._builder = None`` BEFORE
constructing the new one, and wires ``destroyed`` to a slot that
resets the field on eventual C++ teardown. This test pins the
"reopen replaces the reference" half of the contract.
"""

from __future__ import annotations


def test_open_close_reopen_replaces_builder_reference(window, qapp) -> None:
    """Open the builder, close it, reopen it. The reference must
    point at the freshly-constructed builder, not the prior one
    that the user closed."""
    window._open_builder()
    first = window._builder
    assert first is not None and first.isVisible()

    # Close the builder. Qt hides it; ``WA_DeleteOnClose`` is not
    # set on InventoryBuilder so the C++ object lives on until
    # MainWindow's stale-ref cleanup in ``_open_builder`` runs
    # ``deleteLater()`` on the next open call.
    first._dirty = False  # silence the unsaved-changes modal
    first._save_in_flight = False
    first.close()
    qapp.processEvents()
    # After close, the field still points at the closed (but not
    # yet destroyed) instance. The cleanup runs at the next open.
    assert window._builder is first

    window._open_builder()
    second = window._builder
    assert second is not None
    assert second is not first, (
        "reopen must construct a new builder, not reuse the closed "
        "predecessor; field must hold the live builder"
    )
    # Pump events so the prior builder's deferred deletion runs;
    # nothing must crash even though ``_on_builder_destroyed``
    # would fire on a field that has already moved on to the new
    # builder (the slot guards by always resetting to None).
    qapp.processEvents()

    second._dirty = False
    second._save_in_flight = False
    second.close()
    qapp.processEvents()


def test_open_visible_builder_raises_existing(window, qapp) -> None:
    """When the builder is already visible, ``_open_builder`` must
    raise / focus it rather than constructing a new instance.
    Pins the early-return at the top of the lifecycle path.
    """
    window._open_builder()
    first = window._builder
    assert first is not None and first.isVisible()

    window._open_builder()
    second = window._builder
    assert second is first, (
        "a still-visible builder must be re-raised in place; "
        "constructing a second instance would orphan the first"
    )

    first._dirty = False
    first._save_in_flight = False
    first.close()
    qapp.processEvents()
