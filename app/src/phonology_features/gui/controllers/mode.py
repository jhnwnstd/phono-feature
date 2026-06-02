"""Top-level UI mode state machine for MainWindow.

Owns the ``mode`` enum value, the cross-mode ``saved_seg_state`` /
``saved_feat_state`` projections, and every method that runs as part
of a mode transition. MainWindow constructs one instance and either
forwards or replaces its previous inline methods with delegations.

The split is by responsibility: every method here either reads or
writes one of the controller's three state attributes, or applies
mode-dependent chrome to widgets MainWindow owns. Methods that
mutate non-mode state (``_on_segment_clicked``, ``_update_seg_to_feat``,
debounce dispatch) stay on MainWindow.

Back-reference to MainWindow is honest, not a coupling smell: the
controller IS conceptually part of MainWindow and frequently needs
``self._w.engine``, ``self._w._feat_rows``, ``self._w.analysis``,
etc. Same pattern as ``GeometryController`` and ``_SaveController``.

Save/restore semantics: ``save_outgoing_state`` runs BEFORE ``mode``
is updated (it captures the state of the mode being LEFT, projected
into the opposite mode's saved slot). Every other phase runs after
``mode`` has been set. Tests assert on this ordering by checking
that the saved state matches the pre-transition selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phonology_features.gui.shared.mode_logic import (
    Mode,
    mode_status_text,
    project_mode_transition,
)
from phonology_features.gui.shared.palette import C
from phonology_features.gui.widgets import SegmentState

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
        # Provenance for the active FEAT query: ``"projected"`` when
        # the query was auto-derived from a prior seg selection (so
        # the FEAT-mode analysis renders the original seg set as the
        # matches), ``"typed"`` once the user toggles any feature in
        # FEAT mode. MainWindow flips this via
        # ``mark_feature_query_typed`` from ``_on_feature_changed``.
        self.feature_query_origin: str = "typed"

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
        """Run every mode-aware UI update against the current mode."""
        with self._w._batched_updates():
            self.apply_panel_chrome()
            self.apply_row_interactivity()
            self.restore_segment_selection()
            self.restore_feature_selection()
            self.refresh_analysis()
            self.update_status_message()

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
            feature_query_origin=self.feature_query_origin,
            prior_saved_seg_state=list(self.saved_seg_state),
        )
        self.saved_seg_state = transition.saved_seg_state
        self.saved_feat_state = transition.saved_feat_state
        self.feature_query_origin = transition.feature_query_origin

    def mark_feature_query_typed(self) -> None:
        """Called by MainWindow when the user toggles any feature in
        FEAT mode. Drops the ``"projected"`` provenance so the next
        FEAT→SEG transition recomputes the seg state from
        ``find_segments(query)`` instead of restoring the original
        seg selection. (The FEAT-mode highlighted segments always
        come from ``find_segments(query)`` -- this flag only
        affects what the seg state becomes on mode-switch return.)
        """
        self.feature_query_origin = "typed"

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
        Seg mode restores from ``saved_seg_state``; feat mode clears
        the visual selection (matched/unmatched styling is applied
        later by ``refresh_analysis``).
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        restore_segs = set(self.saved_seg_state) if is_s2f else set()
        self._w._selected_segments.clear()
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
        """Clear the analysis panel and re-run the active mode's
        analysis if there's something to analyze.
        """
        is_s2f = self.mode == Mode.SEG_TO_FEAT
        self._w.analysis.clear()
        if is_s2f and self._w._selected_segments:
            self._w._update_seg_to_feat()
        elif not is_s2f and self._w._selected_features:
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
