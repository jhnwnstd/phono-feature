"""Pin :py:meth:`MainWindow.closeEvent` against a pending debounce.

The ``_debounce`` ``QTimer`` carries selection-change updates with
a 150 ms delay. If the user clicks a segment and then closes the
window within that window, the timer fires its slot
(:py:meth:`MainWindow._run_pending_update`) on a half-destroyed
instance and raises into the Qt event loop. The fix is a single
``self._debounce.stop()`` at the top of ``closeEvent``; this test
pins that fix so the close path can never regress to "armed timer
+ closing window".
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication


def test_close_stops_pending_debounce(window, qapp: QApplication) -> None:
    """Arm the debounce, close the window, drain events: the timer
    must be inactive and no exception must surface."""
    window._debounce.start()
    assert (
        window._debounce.isActive()
    ), "fixture invalid: debounce timer must be active before close"

    # ``close()`` invokes ``closeEvent`` synchronously, then schedules
    # destruction. The stop() at the top of closeEvent makes
    # ``isActive()`` return False immediately, before the destruction
    # pump runs.
    window.close()
    assert not window._debounce.isActive(), (
        "closeEvent must stop the debounce timer so its slot can't "
        "fire on a half-destroyed window"
    )

    # Pump the queue. If the prior contract regressed (timer still
    # armed) the queued slot would fire and Qt would either raise
    # or surface a RuntimeError; both fail this test cleanly.
    qapp.processEvents()
    qapp.processEvents()
