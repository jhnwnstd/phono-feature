"""Bridge-payload JSON parity test.

Pins the contract documented at the top of ``web/api.py``: every
bridge function returns a value that round-trips cleanly through
``json.dumps`` / ``json.loads``. If a future refactor returns a
dataclass, an enum, a set, or a Python object that Pyodide would
proxy across to JS as a ``PyProxy``, this test catches it on the
CPython side before the regression reaches the browser.

Why this matters: Pyodide converts return values from Python to JS
heuristically. Plain ``str`` / ``int`` / ``float`` / ``bool`` /
``None`` / ``list`` / ``dict`` round-trip cleanly. Anything else
becomes a ``PyProxy`` that the JS side has to ``.destroy()``
manually; missed destroys leak memory. Returning a JSON-clean
payload makes the bridge robust to the future worker migration
(``postMessage`` boundary serialises via the structured-clone
algorithm, which has the same restriction).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from phonology_shared.data import Inventory
from phonology_shared.theory import FeatureEngine
from phonology_web import api as bridge

REPO_ROOT = Path(__file__).resolve().parents[2]
HAYES = str(REPO_ROOT / "desktop" / "inventories" / "hayes_features.json")


@pytest.fixture(autouse=True)
def _loaded_engine() -> None:
    inv = Inventory.load(HAYES)
    bridge._engine = FeatureEngine(inv)
    bridge._inventory_name = inv.name or "hayes"
    yield
    bridge._engine = None
    bridge._inventory_name = ""


def _assert_json_clean(name: str, value: Any) -> None:
    """Assert ``value`` survives a JSON round-trip. The assertion
    error names the bridge method so a regression is immediately
    traceable.
    """
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        pytest.fail(
            f"bridge.{name} returned non-JSON-serialisable value: "
            f"{type(value).__name__}: {exc}"
        )
    decoded = json.loads(encoded)
    assert (
        decoded == value or json.dumps(decoded) == encoded
    ), f"bridge.{name} round-trip drift; encoded={encoded[:200]!r}"


# ----- Sync bridge methods (no arguments or with trivial args) -----


def test_get_cycle_ladder_json_round_trips() -> None:
    _assert_json_clean("get_cycle_ladder", bridge.get_cycle_ladder())


def test_get_max_undo_depth_json_round_trips() -> None:
    _assert_json_clean("get_max_undo_depth", bridge.get_max_undo_depth())


def test_get_mode_status_text_json_round_trips() -> None:
    for mode in ("seg_to_feat", "feat_to_seg"):
        _assert_json_clean(
            f"get_mode_status_text({mode!r})",
            bridge.get_mode_status_text(mode),
        )


def test_get_move_keys_json_round_trips() -> None:
    _assert_json_clean("get_move_keys", bridge.get_move_keys())


def test_get_value_keys_json_round_trips() -> None:
    _assert_json_clean("get_value_keys", bridge.get_value_keys())


def test_get_setup_defaults_json_round_trips() -> None:
    _assert_json_clean("get_setup_defaults", bridge.get_setup_defaults())


def test_get_grid_state_json_round_trips() -> None:
    _assert_json_clean("get_grid_state", bridge.get_grid_state())


def test_get_download_filename_json_round_trips() -> None:
    _assert_json_clean(
        "get_download_filename",
        bridge.get_download_filename(),
    )


def test_serialize_current_inventory_json_round_trips() -> None:
    _assert_json_clean(
        "serialize_current_inventory",
        bridge.serialize_current_inventory(),
    )


# ----- Analysis bridge methods (per-selection workhorses) ----------


def test_analyze_segments_json_round_trips() -> None:
    payload = bridge.analyze_segments(["p"])
    _assert_json_clean("analyze_segments(['p'])", payload)


def test_analyze_segments_multi_json_round_trips() -> None:
    payload = bridge.analyze_segments(["p", "b", "t"])
    _assert_json_clean(
        "analyze_segments(['p','b','t'])",
        payload,
    )


def test_analyze_features_json_round_trips() -> None:
    payload = bridge.analyze_features({"Voice": "+"})
    _assert_json_clean(
        "analyze_features({'Voice': '+'})",
        payload,
    )


def test_validation_report_html_json_round_trips() -> None:
    payload = bridge.validation_report_html(
        ["bad inventory: missing 'features'"]
    )
    _assert_json_clean(
        "validation_report_html",
        payload,
    )


# ----- PHOIBLE picker methods --------------------------------------


def test_phoible_is_available_json_round_trips() -> None:
    _assert_json_clean(
        "phoible_is_available",
        bridge.phoible_is_available(),
    )


def test_phoible_is_ready_json_round_trips() -> None:
    _assert_json_clean(
        "phoible_is_ready",
        bridge.phoible_is_ready(),
    )


# ----- Layout helpers (delegated to shared) ------------------------


def test_best_segment_n_cols_for_groups_json_round_trips() -> None:
    # Argument is a list of button counts (one per group), matching
    # the JS call site at ``main.js:_relayoutSegments`` which passes
    # ``sizes = rows.map(r => r.querySelectorAll('.seg-btn').length)``.
    payload = bridge.best_segment_n_cols_for_groups([3, 4, 2], 400)
    _assert_json_clean(
        "best_segment_n_cols_for_groups",
        payload,
    )


def test_partition_segment_spillover_json_round_trips() -> None:
    # Argument is a list of group heights in pixels, matching the
    # JS call site at ``main.js:_applySegmentSpillover``.
    payload = bridge.partition_segment_spillover([60, 80, 40], 400)
    _assert_json_clean(
        "partition_segment_spillover",
        payload,
    )
