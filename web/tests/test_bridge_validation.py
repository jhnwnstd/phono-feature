"""Bridge-boundary input validation tests.

``web/api.py`` is the only place untrusted JS-supplied data enters
Python. Before this pass the bridge passed inputs straight through
to the engine, which raised bare ``KeyError`` / ``ValueError`` /
``TypeError``; those exceptions propagated through ``callBridge``
into JS as unhandled runtime errors with no statusbar feedback.

These tests pin the new contract: every public bridge function
either accepts a valid input (no change) or raises
:py:class:`ValidationError` with a message naming the offending
value. The ``@_translate_engine_errors`` decorator is the safety
net for any path the per-function validators miss.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from phonology_shared.data import (
    Inventory,
    ValidationError,
)
from phonology_shared.theory import FeatureEngine
from phonology_web import api as bridge

REPO_ROOT = Path(__file__).resolve().parents[2]
HAYES = str(REPO_ROOT / "desktop" / "inventories" / "hayes_features.json")


@pytest.fixture(autouse=True)
def _loaded_engine() -> None:
    """Every test runs with the Hayes inventory loaded into the
    bridge's module-level engine. The fixture restores the prior
    state on teardown so tests don't leak the engine reference.
    """
    inv = Inventory.load(HAYES)
    bridge._engine = FeatureEngine(inv)
    bridge._inventory_name = inv.name or "hayes"
    yield
    bridge._engine = None
    bridge._inventory_name = ""


# ----- F1: per-function validators --------------------------------


def test_analyze_segments_rejects_unknown_segment() -> None:
    """A segment label not in the active inventory must come back
    as ``ValidationError`` (not raw ``KeyError`` from the engine).
    Reproduces the stale-selection-after-inventory-swap scenario:
    the JS still holds a reference to a segment that no longer
    exists; without this guard the bridge crashes.
    """
    with pytest.raises(ValidationError) as ex:
        bridge.analyze_segments(["nosuch_segment_xyz"])
    assert "nosuch_segment_xyz" in " ".join(ex.value.issues)


def test_analyze_segments_rejects_non_string_input() -> None:
    """Non-string element (None, int, dict) must be rejected; the
    engine's segment dict is keyed on str and would otherwise raise
    a less helpful ``TypeError`` from the lookup.
    """
    with pytest.raises(ValidationError):
        bridge.analyze_segments([None])  # type: ignore[list-item]


def test_analyze_segments_accepts_known_segments() -> None:
    """Sanity: real segments still produce a valid analysis payload."""
    result = bridge.analyze_segments(["p"])
    assert "analysis_tabs" in result
    assert "segment_states" in result


def test_analyze_features_rejects_unknown_feature() -> None:
    with pytest.raises(ValidationError) as ex:
        bridge.analyze_features({"NotAFeature": "+"})
    assert "NotAFeature" in " ".join(ex.value.issues)


def test_analyze_features_rejects_invalid_value() -> None:
    """Feature values are tri-valued: ``"+"`` / ``"-"`` / ``"0"``.
    Anything else (a typo, a ``True``, a Unicode quote) must come
    back as ``ValidationError`` before reaching the engine.
    """
    inv = Inventory.load(HAYES)
    feat = next(iter(inv.features))
    with pytest.raises(ValidationError) as ex:
        bridge.analyze_features({feat: "yes"})
    issues = " ".join(ex.value.issues)
    assert "yes" in issues


def test_analyze_features_accepts_valid_spec() -> None:
    inv = Inventory.load(HAYES)
    feat = next(iter(inv.features))
    result = bridge.analyze_features({feat: "+"})
    assert "analysis_tabs" in result


def test_project_mode_switch_rejects_typo_mode_string() -> None:
    """``Mode(...)`` raises ``ValueError`` on a typo (``"seg-to-feat"``
    with hyphens, wrong case, etc.); the decorator translates that
    to ``ValidationError``.
    """
    with pytest.raises(ValidationError):
        bridge.project_mode_switch("seg_to_feat", "seg-to-feat", [], {})


def test_set_active_theme_rejects_unknown() -> None:
    with pytest.raises(ValidationError) as ex:
        bridge.set_active_theme("blue")
    assert "blue" in " ".join(ex.value.issues)


def test_set_active_theme_accepts_light_and_dark() -> None:
    bridge.set_active_theme("light")
    bridge.set_active_theme("dark")
    # No exception; reset for any downstream test.
    bridge.set_active_theme("light")


def test_set_active_palette_mode_rejects_unknown() -> None:
    with pytest.raises(ValidationError) as ex:
        bridge.set_active_palette_mode("rainbow")
    assert "rainbow" in " ".join(ex.value.issues)


def test_set_active_palette_mode_accepts_standard_and_colorblind() -> None:
    bridge.set_active_palette_mode("standard")
    bridge.set_active_palette_mode("colorblind")
    bridge.set_active_palette_mode("standard")


# ----- F5: decorator catches engine errors as a safety net -------


def test_translate_engine_errors_converts_keyerror() -> None:
    """A bridge function that hits a ``KeyError`` from the engine
    layer (without an explicit per-function validator catching it
    first) still surfaces as ``ValidationError`` thanks to the
    decorator. Uses a small inline function to exercise the
    decorator directly without depending on a specific bridge call's
    internals.
    """

    @bridge._translate_engine_errors
    def raises_keyerror() -> None:
        raise KeyError("X")

    with pytest.raises(ValidationError) as ex:
        raises_keyerror()
    assert "X" in " ".join(ex.value.issues)


def test_translate_engine_errors_passes_validation_error_through() -> None:
    """``ValidationError`` raised inside a wrapped function must
    pass through unchanged (not get re-wrapped). The decorator's
    ``except ValidationError: raise`` short-circuit is what makes
    the explicit per-function validators' messages reach the JS
    caller as written.
    """

    @bridge._translate_engine_errors
    def raises_validation() -> None:
        raise ValidationError(("very specific message",))

    with pytest.raises(ValidationError) as ex:
        raises_validation()
    assert ex.value.issues == ("very specific message",)


# ----- engine-not-loaded path ------------------------------------


def test_require_engine_raises_validation_error_when_unloaded() -> None:
    """``_require_engine()`` previously raised ``RuntimeError`` which
    JS would surface as an opaque error. Now it raises
    ``ValidationError`` so the JS catch path treats it like any
    other bad input.
    """
    bridge._engine = None
    with pytest.raises(ValidationError) as ex:
        bridge._require_engine()
    assert "load" in " ".join(ex.value.issues).lower()
