"""Window geometry and splitter sizing for MainWindow.

Owns the policy state that decides whether a load can change the
window shell, the splitter ratio, or the panel boundary. MainWindow
constructs one instance, forwards its Qt event overrides
(``showEvent``, ``moveEvent``) and signal connections
(``splitterMoved``) into it, and routes all sizing calls through it
instead of inline methods.

The split is by responsibility, not by line count: every method
here decides "how big and where" and reads / writes the
ownership flags (``has_saved_size``, ``has_saved_splitter``,
``anchor_pos``) that other MainWindow methods previously had to
reason about inline.

Holds a back reference to the MainWindow because the sizing logic
needs frequent access to ``self.resize`` / ``self.move`` /
``self.frameGeometry`` and to the seg / feat scroll widgets
populated during ``_build_central``. The controller is conceptually
part of MainWindow, not an independent component, so the back
reference is honest rather than a coupling smell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import QByteArray, QPoint, QTimer
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication

from phonology_features._settings import SettingsKey, safe_read_setting
from phonology_features.gui.shared import layout

if TYPE_CHECKING:
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QSplitter

    from phonology_features.gui.main_window import MainWindow


class GeometryController:
    """Window shell sizing and splitter ratio policy."""

    # Floor for WM decoration when the WM reports zero (Wayland CSD,
    # some X11 themes). Keeps the window frame inside the screen on
    # inventory swaps even when Qt thinks frame == widget.
    MIN_DECO_W: ClassVar[int] = 8
    MIN_DECO_H: ClassVar[int] = 32
    # Preferred analysis-pane height when the feature pane already
    # fits its content. On short windows where the features need more
    # height than they'd get with this floor, ``apply_splitter_sizes``
    # gives priority to fitting the feature pane and lets the analysis
    # pane shrink past this (down to ``HARD_MIN_ANALYSIS_H``). The
    # rationale: features are primary inspection surface, analysis
    # text reflows comfortably to whatever room is left.
    MIN_ANALYSIS_H: ClassVar[int] = layout.MIN_ANALYSIS_H
    # Absolute floor so analysis is at least its title bar + a line
    # of text on the worst-case window size.
    HARD_MIN_ANALYSIS_H: ClassVar[int] = layout.HARD_MIN_ANALYSIS_H
    # First-launch floor: the content-derived width can come out
    # around 900-1100 px depending on the inventory, which leaves the
    # analysis pane visibly cramped on a fresh install. The floor
    # lives in ``phonology_features.gui.shared.layout`` so the web bundle
    # picks up the same value via ``generate_layout_css``.
    MIN_FIRST_LAUNCH_W: ClassVar[int] = layout.MIN_FIRST_LAUNCH_W
    MIN_FIRST_LAUNCH_H: ClassVar[int] = layout.MIN_FIRST_LAUNCH_H

    def __init__(
        self,
        window: MainWindow,
        hsplit: QSplitter,
        vsplit: QSplitter,
        settings: QSettings,
    ) -> None:
        self._w = window
        self._hsplit = hsplit
        self._vsplit = vsplit
        self._settings = settings
        # Public state: tests and other MainWindow methods read /
        # write these directly. Promoted from private to public on
        # the controller because they are the controller's contract.
        self.has_saved_size: bool = False
        self.has_saved_splitter: bool = False
        self.min_analysis_h: int = self.MIN_ANALYSIS_H
        # Anchor for programmatic resizes; updated only by user
        # moves (mouse drag). Reading live self.pos() each resize
        # caused leftward drift on Wayland compositors that nudge
        # the reported position by 1-2 px in response to geometry
        # requests.
        self.anchor_pos: QPoint | None = None
        # Nonzero while we're mid-programmatic resize so the paired
        # moveEvent doesn't treat the compositor's response as a
        # user drag. A counter (not a bool) so a nested call from
        # within a programmatic resize, e.g. an inventory load that
        # triggers fit_window_to_size while another is still in its
        # finally, doesn't drop the outer guard when the inner call
        # exits.
        self._programmatic_geom_depth: int = 0

    # ------------------------------------------------------------------
    # Screen / clamping
    # ------------------------------------------------------------------
    def target_screen(self) -> QScreen | None:
        """Primary screen for initial placement. The user can drag the
        window anywhere afterwards; that position is what's persisted.
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        return app.primaryScreen()

    def clamp_size_to_screen(
        self, w: int, h: int, deco_w: int = 40, deco_h: int = 40
    ) -> tuple[int, int]:
        """Clamp ``(w, h)`` so widget + decoration fits in
        ``availableGeometry``. Defaults to 40 px decoration, the
        heuristic used pre-show when real decoration isn't known.
        """
        screen = self.target_screen()
        if screen is None:
            return w, h
        avail = screen.availableGeometry()
        return (
            min(w, max(640, avail.width() - deco_w)),
            min(h, max(480, avail.height() - deco_h)),
        )

    def default_window_size(self) -> tuple[int, int]:
        """Fresh-install window size. Delegates the policy to the
        Qt-free :py:func:`layout.recommended_initial_window_size` so
        the same fraction-of-screen rule applies on both desktop and
        web. The result is then clamped to the actual screen so the
        resize never overshoots.
        """
        screen = self.target_screen()
        if screen is None:
            return self.MIN_FIRST_LAUNCH_W, self.MIN_FIRST_LAUNCH_H
        avail = screen.availableGeometry()
        w, h = layout.recommended_initial_window_size(
            avail.width(), avail.height()
        )
        return self.clamp_size_to_screen(w, h)

    def ensure_visible_on_screen(self) -> None:
        """Run after first show. Leaves the window alone when it's a
        reasonable size and intersects any screen; only recenters when
        truly off-screen. ``raise_`` / ``activateWindow`` fire only on
        the recovery path (on the happy path they cause a visible
        focus blink on some Linux WMs).
        """
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        screen = self.target_screen()
        if screen is None:
            return
        frame = self._w.frameGeometry()
        sane_size = frame.width() >= 300 and frame.height() >= 200
        if sane_size and any(
            s.geometry().intersects(frame) for s in app.screens()
        ):
            return
        avail = screen.availableGeometry()
        frame.moveCenter(avail.center())
        self._w.move(frame.topLeft())
        self._w.raise_()
        self._w.activateWindow()

    # ------------------------------------------------------------------
    # Event hooks (MainWindow forwards Qt overrides into these)
    # ------------------------------------------------------------------
    def on_user_move(self, pos: QPoint) -> None:
        """Called from ``MainWindow.moveEvent``. Updates the resize
        anchor only when the move was user-initiated (not when we
        triggered it ourselves via the programmatic_geom guard).
        """
        if self._programmatic_geom_depth == 0:
            self.anchor_pos = pos

    def mark_splitter_owned(self, *_args: object) -> None:
        """Promoted to user-owned the first time a splitter handle
        moves under user input. Subsequent inventory loads then
        leave both splitters alone. Wired to splitterMoved by
        MainWindow."""
        self.has_saved_splitter = True

    # ------------------------------------------------------------------
    # Fit / restore
    # ------------------------------------------------------------------
    def fit_to_content(self) -> None:
        """Measure content and size the splitters; on first launch
        only, also size the top-level window.

        Window-geometry policy: once ``has_saved_size`` is True (either
        because settings had a saved size at startup, or because the
        first-launch auto-fit ran and claimed one), inventory changes
        MUST NOT resize or move the window. The user (or their last
        session's saved state) owns the shell; inventory swaps only
        repaint the scrollable interior. The previous behaviour was
        to chase every inventory's content ``sizeHint`` with
        ``self.resize()``, which produced visible layout shift on
        every load and clobbered the user's manual window sizing.
        """
        QApplication.processEvents()
        # Seg panel sticks to its natural content width; extra
        # horizontal room belongs to the feature pane (stretch=1 on
        # the splitter), not to dead space after the vowels.
        seg_content = self._w._seg_scroll.widget()
        seg_content_w = seg_content.sizeHint().width() if seg_content else 400
        seg_chrome = 28 + 6  # panel margins (14 * 2) + scrollbar
        seg_need_w = seg_content_w + seg_chrome
        feat_content = self._w._feat_scroll.widget()
        feat_content_w = (
            feat_content.sizeHint().width() if feat_content else 380
        )
        feat_chrome = 28 + 6
        feat_padding = 40
        feat_need_w = feat_content_w + feat_chrome + feat_padding
        # Heights come from the shared layout helpers, not Qt's
        # ``sizeHint`` — the helpers compute from inventory data
        # directly so we don't have to wait for Qt's reflow, and so
        # the same numbers appear on the web bundle via the CSS-
        # variable relay. Falls back to ``sizeHint`` if the engine
        # isn't ready yet (e.g. early startup before _populate runs).
        engine = self._w.engine
        if engine is not None:
            cons_groups = [
                len(segs)
                for manner, segs in engine.grouped_segments.items()
                if manner.lower() != "vowels"
            ]
            # Predict the EVENTUAL seg pane width (post-splitter) so
            # ``seg_pane_n_cols`` picks the column count the grid
            # will actually paint at. Neither ``seg_panel.width()``
            # nor ``hsplit.width()`` is reliable here — on the
            # first-launch synchronous path they're constructor
            # defaults (480 and 100 px respectively). The WINDOW
            # width is reliable because the caller resizes the
            # window before showing it. Derive the hsplit-available
            # width from window.width(); ``distribute_pane_widths``
            # is then a pure function that yields the eventual seg
            # pane width.
            available_w = max(
                self._w.width(),
                seg_need_w + feat_need_w + 1,
                self.MIN_FIRST_LAUNCH_W,
            )
            seg_pane_w, _ = layout.distribute_pane_widths(
                available_w,
                seg_content_w=seg_need_w,
                feat_content_w=feat_need_w,
            )
            n_cols = layout.seg_pane_n_cols(seg_pane_w)
            seg_content_h = layout.seg_grid_natural_height(cons_groups, n_cols)
            from phonology_features.gui.shared.constants import FEATURE_GROUPS

            present = set(engine.features)
            placed: set[str] = set()
            card_names: list[str] = []
            card_counts: list[int] = []
            for group_name, group_feats in FEATURE_GROUPS:
                in_inv = [f for f in group_feats if f in present]
                if in_inv:
                    card_names.append(group_name)
                    card_counts.append(len(in_inv))
                    placed.update(in_inv)
            leftovers = [f for f in engine.features if f not in placed]
            if leftovers:
                card_names.append("Other")
                card_counts.append(len(leftovers))
            feat_content_h = layout.feature_panel_natural_height(
                card_counts, group_names=card_names
            )
        else:
            seg_content_h = (
                seg_content.sizeHint().height() if seg_content else 400
            )
            feat_content_h = (
                feat_content.sizeHint().height() if feat_content else 400
            )
        feat_v_padding = 20
        top_need_h = feat_content_h + 80 + feat_v_padding
        # Lock each panel's vertical minimum to its actual content
        # height. Without this, the vsplit's stretch policy (top=0,
        # analysis=1) lets the top section shrink when the window
        # shrinks past the analysis floor, but never restores it
        # when the window grows back — Qt's stretch factor only
        # distributes EXTRA space, so anything the top "gave up"
        # stays lost. Setting a content-driven minimum on each panel
        # turns those givebacks into reversible operations: when the
        # window grows again, Qt honors the minimum and analysis
        # absorbs only what's beyond it.
        #
        # The chrome constant lives in ``layout`` so both UIs apply
        # the same overhead: panel outer padding + header strip
        # (clear button row) = ``PANEL_CHROME_V``. Was previously
        # the duplicated literal ``24 + 30`` here.
        self._w.seg_panel.setMinimumHeight(
            seg_content_h + layout.PANEL_CHROME_V
        )
        self._w.feat_panel.setMinimumHeight(
            feat_content_h + layout.PANEL_CHROME_V
        )
        analysis_h = self.min_analysis_h
        toolbar_h = 50
        total_need_h = top_need_h + analysis_h + toolbar_h + 30
        # Paint suspended so the window doesn't flash through
        # "new size + old splitter ratio" before setSizes lands.
        screen = self.target_screen()
        with self._w._batched_updates():
            # First-launch only: claim a sensible window size from
            # the first inventory's content. Subsequent loads skip
            # this and rely on the splitter to absorb width changes.
            # Width policy is content-driven with TWO floors:
            #   * absolute floor (``MIN_FIRST_LAUNCH_W`` = 1120):
            #     keeps the layout safe before any inventory loads.
            #   * vowel-safe floor: per-inventory, ensures the seg
            #     pane gets ``>= VOWEL_STACK_W`` so the vowel chart
            #     stays beside the consonants. The user's stated
            #     "default startup width should be the minimum
            #     needed so vowels don't display under the consonant
            #     segments" preference.
            if not self.has_saved_size:
                vowel_safe_w = layout.min_vowel_safe_window_w(feat_content_w)
                target_w = max(
                    seg_need_w + feat_need_w + 1,
                    vowel_safe_w,
                    self.MIN_FIRST_LAUNCH_W,
                )
                self.fit_window_to_size(
                    screen,
                    target_w,
                    max(total_need_h, self.MIN_FIRST_LAUNCH_H),
                )
            # The hsplit ratio (left/right between seg and feat) is
            # user-draggable, so once they've established a width
            # preference we leave it alone on inventory swap. Only
            # the first launch gets a content-derived hsplit ratio.
            # The vsplit (top vs analysis) is NOT user-draggable —
            # the handle is disabled — so we always re-fit it to the
            # new content. Otherwise loading a smaller inventory
            # would leave the analysis pane at its old size instead
            # of growing to absorb the freed space (the user's
            # "analysis as tall as it can be" preference).
            if not self.has_saved_splitter:
                self.apply_splitter_sizes(seg_need_w, feat_need_w, top_need_h)
            else:
                self.apply_vsplit_to_content(top_need_h)

    def fit_window_to_size(
        self, screen: QScreen | None, need_w: int, need_h: int
    ) -> None:
        """Resize the window to ``(need_w, need_h)`` and anchor it
        in place.

        Anchors to the user's last position; only shifts when the
        title bar would otherwise be off-screen. First load centers
        instead.
        """
        if screen is None:
            return
        avail = screen.availableGeometry()
        cur_w = self._w.width()
        cur_h = self._w.height()
        if self.anchor_pos is None:
            self.anchor_pos = self._w.pos()
        anchor = self.anchor_pos
        deco_w, deco_h, left_pad, top_pad = self.decoration_padding(anchor)
        new_w, new_h = self.clamp_size_to_screen(
            need_w, need_h, deco_w, deco_h
        )
        self._programmatic_geom_depth += 1
        try:
            if not self.has_saved_size:
                self._w.resize(new_w, new_h)
                frame = self._w.frameGeometry()
                frame.moveCenter(avail.center())
                self._w.move(frame.topLeft())
                self.anchor_pos = self._w.pos()
                self.has_saved_size = True
                return
            if new_w == cur_w and new_h == cur_h:
                return
            target_x = anchor.x()
            target_y = anchor.y()
            if target_x - left_pad < avail.x():
                target_x = avail.x() + left_pad
            if target_y - top_pad < avail.y():
                target_y = avail.y() + top_pad
            # Atomic setGeometry: one xdg_toplevel configure carries
            # both size and position so the compositor places once,
            # not twice (resize then move-back drifted on Wayland).
            self._w.setGeometry(target_x, target_y, new_w, new_h)
            if target_x != anchor.x() or target_y != anchor.y():
                # Off-screen recovery promoted to the new anchor.
                self.anchor_pos = QPoint(target_x, target_y)
        finally:
            self._programmatic_geom_depth -= 1

    def decoration_padding(self, old_pos: QPoint) -> tuple[int, int, int, int]:
        """Return ``(deco_w, deco_h, left_pad, top_pad)`` for the
        current frame.

        Trusts the WM-reported decoration when nonzero; falls back
        to ``MIN_DECO_*`` only when the WM reports zero (Wayland
        CSD, pre-show callers). Inflating real values past their
        true size used to shift the anchor a few pixels per resize.
        """
        if not self._w.isVisible():
            return self.MIN_DECO_W, self.MIN_DECO_H, 0, 0
        old_frame = self._w.frameGeometry()
        deco_w_reported = max(0, old_frame.width() - self._w.width())
        deco_h_reported = max(0, old_frame.height() - self._w.height())
        deco_w = deco_w_reported if deco_w_reported else self.MIN_DECO_W
        deco_h = deco_h_reported if deco_h_reported else self.MIN_DECO_H
        left_pad = max(0, old_pos.x() - old_frame.x())
        top_pad = max(0, old_pos.y() - old_frame.y())
        return deco_w, deco_h, left_pad, top_pad

    # ------------------------------------------------------------------
    # Splitter sizing
    # ------------------------------------------------------------------
    def restore_splitter_state(self) -> bool:
        """Apply saved horizontal+vertical splitter state. Returns
        True if at least one splitter was successfully restored, so
        the caller can suppress content-based sizing.
        """
        # QByteArray is what ``saveState`` produces. A non-QByteArray
        # value (hand-edited INI, previous schema) reaching
        # ``restoreState`` can crash or silently fail; the type
        # guard falls back cleanly to the unrestored case.
        h_state = safe_read_setting(
            self._settings,
            SettingsKey.HSPLIT_STATE,
            None,
            expected_type=QByteArray,
        )
        v_state = safe_read_setting(
            self._settings,
            SettingsKey.VSPLIT_STATE,
            None,
            expected_type=QByteArray,
        )
        restored = False
        if h_state is not None:
            if self._hsplit.restoreState(h_state):
                restored = True
        if v_state is not None:
            if self._vsplit.restoreState(v_state):
                restored = True
        return restored

    def apply_splitter_sizes(
        self, seg_need_w: int, feat_need_w: int, top_need_h: int
    ) -> None:
        """Distribute splitter sizes via the shared
        :py:func:`layout.distribute_pane_widths` policy. The feat
        pane lands at ``feat_need_w + cushion`` (content-driven, kept
        relatively consistent); the seg pane absorbs the rest so it
        fans out on wide screens. Vertical splitter then leaves the
        analysis pane its ``min_analysis_h`` floor.

        Called from ``fit_to_content``, which may run BEFORE the
        window is laid out (sync path when an inventory is auto-
        loaded from settings during ``__init__``). In that case
        ``vsplit.height()`` is 0 and we can't compute a sensible top
        height; the horizontal axis still applies, but
        ``mark_splitter_owned`` flips ``has_saved_splitter`` and
        blocks any future re-attempt. Schedule a one-shot retry for
        after the post-show layout pass so the vertical splitter
        still gets sized once before the user sees the analysis
        pane at the constructor default.
        """
        available = self._hsplit.width() or (seg_need_w + feat_need_w)
        seg_w, feat_w = layout.distribute_pane_widths(
            available,
            seg_content_w=seg_need_w,
            feat_content_w=feat_need_w,
        )
        self._hsplit.setSizes([seg_w, feat_w])
        # Notify the seg-pane internals (vowel chart sizing /
        # stack-vs-side-by-side) that the seg width changed. The
        # callback is a no-op pre-build_central; we guard for that.
        notify = getattr(self._w, "_on_seg_pane_width_changed", None)
        if callable(notify):
            notify(seg_w)
        total = self._vsplit.height()
        if total > 0:
            top_h = layout.top_pane_height(top_need_h, total)
            self._vsplit.setSizes([top_h, total - top_h])
            return
        QTimer.singleShot(0, lambda: self.fit_vsplit_after_layout(top_need_h))

    def apply_vsplit_to_content(self, top_need_h: int) -> None:
        """Re-fit JUST the vsplit (top vs analysis) to the current
        inventory's content height. Called on every inventory swap
        AFTER the first launch (when ``has_saved_splitter`` is True
        and we keep the user's hsplit drag preference). The vsplit
        is not user-draggable, so re-fitting here is safe — and
        necessary, because the user's "analysis as tall as it can
        be" preference requires the top pane to shrink when a smaller
        inventory loads, freeing vertical room for analysis.
        """
        total = self._vsplit.height()
        if total <= 0:
            QTimer.singleShot(
                0, lambda: self.fit_vsplit_after_layout(top_need_h)
            )
            return
        top_h = layout.top_pane_height(top_need_h, total)
        self._vsplit.setSizes([top_h, total - top_h])

    def fit_vsplit_after_layout(self, top_need_h: int) -> None:
        """Vertical-only fallback for the case in
        ``apply_splitter_sizes`` where the window hadn't been laid
        out yet. Runs after one event-loop tick (post-show); if
        height is still 0 we accept the constructor default rather
        than recurse."""
        total = self._vsplit.height()
        if total <= 0:
            return
        top_h = layout.top_pane_height(top_need_h, total)
        self._vsplit.setSizes([top_h, total - top_h])
