"""Regression tests for desktop stability fixes.

Each test pins a fix for a concrete stability defect found in a
stability audit:

* The segment-button pool must stay bounded across inventory loads.
  It previously only ever grew: inactive buttons were detached but
  kept in ``_seg_button_pool`` forever, so every unique segment ever
  loaded leaked as a hidden orphaned widget (a memory leak over a
  PHOIBLE-browsing session).
* ``_SaveController.wait_for_save`` must release the in-flight guard
  when the drain times out. A stuck save previously left
  ``save_in_flight`` True forever, silently rejecting every later
  save for the rest of the session.
* Reopening the builder must not let the OLD instance's ``destroyed``
  signal null the reference to the freshly-opened builder.
"""

from __future__ import annotations

from pathlib import Path

_INV_DIR = Path(__file__).resolve().parent.parent / "inventories"


def _bundled(name: str) -> str:
    return str(_INV_DIR / f"{name}_features.json")


def test_segment_button_pool_stays_bounded(window, qapp) -> None:
    """After every inventory load the pool must hold EXACTLY the
    current inventory's segments, with nothing retained from prior
    inventories. Repeated and revisited inventories exercise both the
    reuse-of-shared-buttons and the evict-the-leftovers paths."""
    # Distinct bundled inventories, with repeats so a revisit cannot
    # silently double the pool.
    names = [
        "hayes",
        "english",
        "german",
        "blevins",
        "japanese",
        "hindi",
        "english",
        "hayes",
    ]
    for name in names:
        window._load_path(_bundled(name))
        qapp.processEvents()
        pool = set(window._seg_button_pool)
        active = set(window._seg_buttons)
        leaked = pool - active
        assert not leaked, (
            f"after loading {name!r} the pool retained {len(leaked)} "
            f"button(s) not in the current inventory ({sorted(leaked)[:8]}"
            "...): orphan accumulation reintroduces the memory leak"
        )
        # Every active button is pooled (the pool is the creation cache).
        assert active <= pool


def test_save_guard_released_on_drain_timeout(qapp) -> None:
    """A drain that times out (worker stuck or never emits) must
    release ``save_in_flight`` so saving is not locked out for the
    session, while still reporting the save as not completed."""
    from PyQt6.QtWidgets import QStatusBar, QWidget

    from phonology_features.gui.builder.save_controller import (
        _SaveController,
    )

    host = QWidget()
    ctrl = _SaveController(host, QStatusBar(), lambda: None)
    # Simulate an in-flight save whose worker never emits save_finished.
    ctrl.save_in_flight = True
    completed = ctrl.wait_for_save(timeout_ms=50)
    assert completed is False, "a timed-out drain must report not completed"
    assert ctrl.save_in_flight is False, (
        "the in-flight guard must be released on timeout; otherwise every "
        "subsequent save is silently rejected for the rest of the session"
    )


def test_reopen_keeps_new_builder_reference_when_old_destroyed(
    window, qapp
) -> None:
    """The old builder's ``destroyed`` signal (fired when its deferred
    deletion runs) must not null the reference to the freshly-opened
    builder. The fix disconnects the outgoing builder's signals before
    scheduling its deletion."""
    window._open_builder()
    first = window._builder
    assert first is not None
    first._dirty = False
    first._save_in_flight = False
    first.close()
    qapp.processEvents()

    window._open_builder()
    second = window._builder
    assert second is not None and second is not first

    # Force the OLD builder's deferred deletion so its ``destroyed``
    # signal actually fires. Plain ``processEvents`` excludes
    # ``DeferredDelete`` events, so deleteLater'd objects would linger
    # and the test would pass trivially without exercising the bug.
    from PyQt6 import sip
    from PyQt6.QtCore import QEvent

    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    # Precondition: the old builder really was destroyed (its
    # ``destroyed`` signal fired during the dispatch above).
    assert sip.isdeleted(first), (
        "old builder was not destroyed; test would not exercise the "
        "destroyed-signal path"
    )
    assert window._builder is second, (
        "the old builder's destroyed signal nulled the new builder "
        "reference; outgoing-builder signals must be disconnected before "
        "deleteLater"
    )

    second._dirty = False
    second._save_in_flight = False
    second.close()
    qapp.processEvents()
