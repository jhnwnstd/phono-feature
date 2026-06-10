"""Top-level UI mode state machine for :class:`MainWindow`. Owns
the ``mode`` enum, the cross-mode ``saved_seg_state`` /
``saved_feat_state`` projections, and every method that runs as
part of a mode transition.

Ordering: ``save_outgoing_state`` runs BEFORE ``mode`` is updated
(it captures the leaving-mode state, projected into the opposite
mode's saved slot). Every other phase runs after ``mode`` is set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer

from phonology_features.gui.widgets import SegmentState
from phonology_shared.presentation.mode_logic import (
    Mode,
    mode_status_text,
    project_mode_transition,
)
from phonology_shared.presentation.palette import C

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget

    from phonology_features.gui.main_window import MainWindow


class ModeController:
    """Mode-toggle state machine + cross-mode state projection."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window
        self.mode: Mode = Mode.SEG_TO_FEAT
        # State of each mode at the moment we leave it, projected into
        # the other mode as a pre-fill on switch.
        self.saved_seg_state: list[str] = []
        self.saved_feat_state: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Transition entry point
    # ------------------------------------------------------------------
    def set_mode(self, mode: Mode | str) -> None:
        """Switch top-level UI mode. Accepts bare strings (from QSettings
        and tests) and coerces. Bails when the requested mode equals the
        current one; callers that need to re-apply chrome unconditionally
        call ``apply_phases`` directly.
        """
        mode = Mode(mode)
        if mode == self.mode:
            return
        self.save_outgoing_state(mode)
        self.mode = mode
        self.apply_phases()

    def apply_phases(self) -> None:
        """Run every mode-aware UI update against the current mode.

        Split into two stages so the mode-toggle click feels snappy:

        * **Visible stage**: panel chrome, row interactivity,
          segment-button states, feature-row states, status text.
          Everything that paints the new mode's framing. Held inside
          a single ``setUpdatesEnabled(False/True)`` so the user sees
          one clean swap, not a flicker as each piece changes.
        * **Deferred stage**: ``refresh_analysis``, which re-renders
          the analysis pane (heavy ``setHtml`` work, ~30 ms on the
          slower direction). Posted to the next event-loop tick via
          ``QTimer.singleShot(0, ...)``. The user sees the mode swap
          repaint first; the analysis content fills in one frame
          later, so the perceived transition is two short steps
          instead of one long blocking one.

        No ``analysis.clear()`` call here. The deferred refresh ends
        in :py:meth:`AnalysisPanel.set_sections`, which overwrites the
        tab bodies and only snaps the active tab when Contrasts
        becomes disabled while active. Calling ``clear()`` here would
        force the Class tab on every toggle (the user-visible
        regression this branch fixed).
        """
        with self._w._batched_updates():
            self.apply_panel_chrome()
            self.apply_row_interactivity()
            self.restore_segment_selection()
            self.restore_feature_selection()
            self.update_status_message()
        QTimer.singleShot(0, self._deferred_refresh_analysis)

    def _deferred_refresh_analysis(self) -> None:
        """Re-run the active mode's analysis after the visible mode-
        switch frame has already painted. See :py:meth:`apply_phases`
        for the staging rationale. The mode may have flipped again
        between scheduling and firing (rapid toggles); the
        ``refresh_analysis`` body already reads the live mode and
        selections so this is safe to call unconditionally.
        """
        self.refresh_analysis()

    def save_outgoing_state(self, target_mode: Mode | str) -> None:
        """Snapshot the current mode's exact state and project it into
        the opposite mode's saved state. Called only when the mode is
        actually changing.
        """
        transition = project_mode_transition(
            self.mode,
            target_mode,
            selected_segments=list(self._w._selected_segments),
            selected_features=dict(self._w._selected_features),
            engine=self._w.engine,
        )
        self.saved_seg_state = transition.saved_seg_state
        self.saved_feat_state = transition.saved_feat_state

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------
    @staticmethod
    def panel_chrome_qss(object_name: str) -> str:
        """Stylesheet baked once at panel creation with both active and
        inactive rules. ``apply_panel_chrome`` toggles the ``active``
        property instead of replacing the sheet; Qt then only re-polishes
        the panel widget, not every descendant.
        """
        return (
            f"QFrame#{object_name} {{ background: {C['bg']}; border: none; }}"
            f'QFrame#{object_name}[active="true"] {{'
            f" background: {C['panel']};"
            f" border: 1.5px solid {C['accent']};"
            f" }}"
        )

    def apply_panel_chrome(self) -> None:
        """Reflect the active mode on the chrome. Panel highlight uses
        a Qt property + ``style().polish()`` so the active border swap
        re-styles the panel only, not its 140+ descendants. Title
        labels are tiny so a direct setStyleSheet on them is fine.
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        self._polish_active(self._w.seg_panel, is_s2f)
        self._polish_active(self._w.feat_panel, not is_s2f)
        self._w._seg_title.setStyleSheet(
            f"color: {C['text'] if is_s2f else C['text_dim']};"
            " letter-spacing: 1.5px;"
        )
        self._w._feat_title.setStyleSheet(
            f"color: {C['text'] if not is_s2f else C['text_dim']};"
            " letter-spacing: 1.5px;"
        )
        self._w.seg_grid_widget.set_headers_active(is_s2f)
        self._w.vowel_chart_widget.set_headers_active(is_s2f)

    @staticmethod
    def _polish_active(widget: QWidget, active: bool) -> None:
        """Flip the ``active`` Qt property and re-polish so the
        property-selector rule takes effect. Cheaper than setStyleSheet
        because polish doesn't cascade.
        """
        if widget.property("active") == active:
            return
        widget.setProperty("active", active)
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def apply_row_interactivity(self) -> None:
        """Set each FeatureRow's interactivity to match the active mode."""
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        for row in self._w._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)

    def restore_segment_selection(self) -> None:
        """Set each segment button to its final state for the new mode.

        Two short-circuits keep the per-button cost minimal during a
        mode switch; this is the dominant flash budget in the visible
        stage:

        1. **Skip the no-op case.** When transitioning into FEAT
           mode AND the projected query is non-empty, the deferred
           ``refresh_analysis`` will momentarily re-style every
           button as MATCHED / UNMATCHED. The intermediate trip
           through DEFAULT for previously-SELECTED buttons is wasted
           ``setStyleSheet`` work; skip it. Only the data-state
           reset (``setChecked``, ``_selected_segments.clear()``)
           runs here so the button's checked semantics stay correct.
        2. **Don't re-set identical visual states.** ``set_state``
           already short-circuits on no-change, but doing the
           comparison here saves the Python call overhead too.
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        restore_segs = set(self.saved_seg_state) if is_s2f else set()
        self._w._selected_segments.clear()
        if not is_s2f and self.saved_feat_state:
            # FEAT mode with a non-empty query: defer all visual
            # restyle to the upcoming ``_update_feat_to_seg`` pass.
            # We still need to drop the checked state on previously-
            # selected buttons so the underlying QPushButton model
            # is consistent.
            for btn in self._w._seg_buttons.values():
                if btn.isChecked():
                    btn.setChecked(False)
            return
        for seg, btn in self._w._seg_buttons.items():
            if seg in restore_segs:
                self._w._selected_segments.append(seg)
                if btn._state != SegmentState.SELECTED:
                    btn.set_state(SegmentState.SELECTED)
                    btn.setChecked(True)
            elif btn._state != SegmentState.DEFAULT:
                btn.set_state(SegmentState.DEFAULT)
                btn.setChecked(False)

    def restore_feature_selection(self) -> None:
        """Set each feature row to its final state for the new mode.
        Sole authority on per-row visual state during a mode switch;
        rows in ``saved_feat_state`` get ``restore_value``, the rest
        get ``reset``.
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        restore_feats = self.saved_feat_state if not is_s2f else {}
        self._w._selected_features.clear()
        for feat, row in self._w._feat_rows.items():
            if feat in restore_feats:
                self._w._selected_features[feat] = restore_feats[feat]
                row.restore_value(restore_feats[feat])
            else:
                row.reset()

    def refresh_analysis(self) -> None:
        """Apply the active mode's summary to the panels. The shared
        view-model returns a total payload for any input (including
        empty selection), so this is a straight dispatch; no
        special empty-state branch. The user-pressed-Clear path
        still goes through :py:meth:`AnalysisPanel.clear` (the
        documented full-reset sink that forces the Class tab); the
        steady-state refresh here preserves the user's active tab.
        """
        if self.mode == Mode.SEG_TO_FEAT:
            self._w._update_seg_to_feat()
        else:
            self._w._update_feat_to_seg()

    def apply_to_new_widgets(self) -> None:
        """Set interactivity on freshly-populated rows + headers for the
        current mode, then clear both sides. Called after inventory load.
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        self._w.seg_grid_widget.set_headers_active(is_s2f)
        self._w.vowel_chart_widget.set_headers_active(is_s2f)
        for row in self._w._feat_rows.values():
            row.set_panel_active(not is_s2f)
            row.set_interactive(not is_s2f)
        self._w._clear_segments(silent=True)
        self._w._clear_features(silent=True)

    def update_status_message(self) -> None:
        """Show the per-mode helper text in the status bar."""
        self._w.status.showMessage(
            mode_status_text(self.mode, has_engine=self._w.engine is not None)
        )
