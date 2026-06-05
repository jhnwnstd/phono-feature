"""Pin the no-engine ``project_mode_transition`` contract.

The web's pre-bridge ``fallbackModeSwitch()`` in ``web/main.js``
returns the same four-field shape that
:py:func:`phonology_shared.presentation.mode_logic.project_mode_transition`
emits when called with ``engine=None``. Without an engine the
projection cannot derive features-from-segments or
segments-from-features, so both helpers fall back to "save the
outgoing state, clear the incoming state". This test pins that the
Python side keeps emitting the four-field shape the JS expects, so
a future field addition to :py:class:`ModeTransition` either
prompts a JS-side update or fails this test loudly first.
"""

from __future__ import annotations

import pytest

from phonology_shared.presentation.mode_logic import (
    Mode,
    ModeTransition,
    project_mode_transition,
)

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "saved_seg_state",
        "saved_feat_state",
        "selected_segments",
        "selected_features",
    }
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Mode.SEG_TO_FEAT, Mode.FEAT_TO_SEG),
        (Mode.FEAT_TO_SEG, Mode.SEG_TO_FEAT),
    ],
    ids=["seg_to_feat_outgoing", "feat_to_seg_outgoing"],
)
def test_no_engine_returns_four_field_shape(
    current: Mode, target: Mode
) -> None:
    """A no-engine transition must populate exactly the four fields
    the JS pre-bridge fallback reads. Any extra field added to
    :py:class:`ModeTransition` lights this up so the JS fallback
    can be updated in lockstep."""
    result = project_mode_transition(
        current,
        target,
        selected_segments=["p", "t", "k"],
        selected_features={"voice": "+"},
        engine=None,
    )
    assert isinstance(result, ModeTransition)
    field_names = {f for f in result.__dataclass_fields__}
    assert field_names == REQUIRED_FIELDS, (
        "ModeTransition fields drifted from the JS fallback's "
        "expected shape; update web/main.js:fallbackModeSwitch to "
        "match before adding a new field here."
    )


def test_no_engine_seg_to_feat_drops_unprojected_features() -> None:
    """When the engine is absent the SEG_TO_FEAT outgoing branch
    can't compute features-from-segments, so the saved feature
    state must be empty (not the input dict). The JS fallback
    does the same; this pins both ends in lockstep."""
    result = project_mode_transition(
        Mode.SEG_TO_FEAT,
        Mode.FEAT_TO_SEG,
        selected_segments=["p", "t"],
        selected_features={},
        engine=None,
    )
    assert result.saved_seg_state == ["p", "t"]
    assert result.saved_feat_state == {}
    assert result.selected_segments == []
    assert result.selected_features == {}


def test_no_engine_feat_to_seg_drops_unprojected_segments() -> None:
    """Symmetric: the FEAT_TO_SEG outgoing branch can't compute
    segments-from-features without an engine, so the saved seg
    state must be empty even when a query was active."""
    result = project_mode_transition(
        Mode.FEAT_TO_SEG,
        Mode.SEG_TO_FEAT,
        selected_segments=[],
        selected_features={"voice": "+"},
        engine=None,
    )
    assert result.saved_feat_state == {"voice": "+"}
    assert result.saved_seg_state == []
    assert result.selected_segments == []
    assert result.selected_features == {}
