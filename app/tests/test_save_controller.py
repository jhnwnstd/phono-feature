"""Regression test for :py:mod:`phonology_features.gui.builder.save_controller`.

Pins the invariant that ``save_finished`` fires no matter what the
worker raises — including ``BaseException`` subclasses. Without that
invariant the daemon thread dies silently, ``save_in_flight`` stays
True forever, and the user is locked out of further saves until
the app restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PyQt6.QtWidgets import QStatusBar, QWidget

from phonology_engine.feature_engine import FeatureEngine
from phonology_engine.inventory import Inventory
from phonology_features.gui.builder import save_controller as save_controller_module
from phonology_features.gui.builder.save_controller import _SaveController

INVENTORIES_DIR = Path(__file__).resolve().parents[1] / "inventories"


class _CustomBaseError(BaseException):
    """BaseException subclass that the inner ``except Exception``
    deliberately does not catch — exactly the case the finally block
    is there to handle.
    """


def _load_inventory() -> Inventory:
    raw = json.loads(
        (INVENTORIES_DIR / "hayes_features.json").read_text("utf-8-sig")
    )
    return Inventory.parse(raw, source="test")


def _make_controller(
    qapp: Any,
    write_atomic_raises: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_SaveController, QWidget]:
    """Build a controller whose worker will raise ``write_atomic_raises``.

    Returns the controller and the QWidget parent so the test can keep
    the parent alive for the duration of the save.
    """
    monkeypatch.setattr(
        save_controller_module, "show_warning", lambda *a, **kw: None
    )
    inventory = _load_inventory()
    # Make sure the engine can load the inventory we're handing the
    # controller; a snapshot returning an unbuildable Inventory would
    # fail at validation rather than reaching the worker.
    FeatureEngine(inventory)

    class _ExplodingInventory:
        segments = inventory.segments
        features = inventory.features

        def write_atomic(self, _path: str) -> None:
            raise write_atomic_raises

    parent = QWidget()
    status = QStatusBar()
    controller = _SaveController(
        parent, status, snapshot=lambda: _ExplodingInventory()  # type: ignore[arg-type, return-value]
    )
    return controller, parent


def test_worker_emits_completion_on_ordinary_exception(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, parent = _make_controller(
        qapp, OSError("disk full"), monkeypatch
    )
    try:
        controller.request_save(str(tmp_path / "out.json"))
        assert controller.wait_for_save(timeout_ms=3000)
        assert controller.save_in_flight is False
        # Failure path re-dirties so the close guard reflects the
        # unsaved state — locks in the contract at the error branch.
        assert controller.dirty is True
    finally:
        parent.deleteLater()


def test_worker_emits_completion_on_base_exception(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The critical invariant: a BaseException subclass propagating out
    of ``write_atomic`` must NOT leave ``save_in_flight`` stuck on True.
    The worker's ``finally`` clause is what guarantees this; if someone
    later refactors the worker to drop the ``finally``, this test
    catches the regression.
    """
    controller, parent = _make_controller(
        qapp, _CustomBaseError("interrupted"), monkeypatch
    )
    try:
        controller.request_save(str(tmp_path / "out.json"))
        assert controller.wait_for_save(timeout_ms=3000), (
            "save_finished never fired — daemon thread died silently and "
            "save_in_flight is stuck on True"
        )
        assert controller.save_in_flight is False
        assert controller.dirty is True
    finally:
        parent.deleteLater()
