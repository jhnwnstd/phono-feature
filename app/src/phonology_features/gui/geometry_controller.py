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

from phonology_features._settings import safe_read_setting

if TYPE_CHECKING:
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QSplitter

    from phonology_features.gui.main_window import MainWindow


class _GeometryController:
    """Window shell sizing and splitter ratio policy."""

    # Floor for WM decoration when the WM reports zero (Wayland CSD,
    # some X11 themes). Keeps the window frame inside the screen on
    # inventory swaps even when Qt thinks frame == widget.
    MIN_DECO_W: ClassVar[int] = 8
    MIN_DECO_H: ClassVar[int] = 32
    MIN_ANALYSIS_H: ClassVar[int] = 220

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
        # Set True while we're mid-programmatic resize so the
        # paired moveEvent doesn't treat the compositor's response
        # as a user drag.
        self._programmatic_geom: bool = False

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
        if not self._programmatic_geom:
            self.anchor_pos = pos

    def mark_splitter_owned(self, *_args) -> None:
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
        seg_content_w = (
            seg_content.sizeHint().width() if seg_content else 400
        )
        seg_chrome = 28 + 6  # panel margins (14 * 2) + scrollbar
        seg_need_w = seg_content_w + seg_chrome
        feat_content = self._w._feat_scroll.widget()
        feat_content_w = (
            feat_content.sizeHint().width() if feat_content else 380
        )
        feat_chrome = 28 + 6
        feat_padding = 40
        feat_need_w = feat_content_w + feat_chrome + feat_padding
        feat_content_h = (
            feat_content.sizeHint().height() if feat_content else 400
        )
        feat_v_padding = 20
        top_need_h = feat_content_h + 80 + feat_v_padding
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
            if not self.has_saved_size:
                self.fit_window_to_size(
                    screen, seg_need_w + feat_need_w + 1, total_need_h
                )
            # Same rule for the panel boundary: once the user has
            # a restored or manually-dragged splitter ratio, leave
            # it alone on inventory swap. Only the first launch
            # (no saved state) gets a content-derived ratio.
            if not self.has_saved_splitter:
                self.apply_splitter_sizes(
                    seg_need_w, feat_need_w, top_need_h
                )

    def fit_window_to_size(
        self, screen, need_w: int, need_h: int
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
        self._programmatic_geom = True
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
            self._programmatic_geom = False

    def decoration_padding(
        self, old_pos
    ) -> tuple[int, int, int, int]:
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
            "hsplit_state",
            None,
            expected_type=QByteArray,
        )
        v_state = safe_read_setting(
            self._settings,
            "vsplit_state",
            None,
            expected_type=QByteArray,
        )
        restored = False
        if h_state is not None and self._hsplit.restoreState(h_state):
            restored = True
        if v_state is not None and self._vsplit.restoreState(v_state):
            restored = True
        return restored

    def apply_splitter_sizes(
        self, seg_need_w: int, feat_need_w: int, top_need_h: int
    ) -> None:
        """Size the seg pane to its content; let the feature pane
        absorb the rest. Rebalances the vertical splitter so the
        analysis pane keeps its minimum height.

        Called from ``fit_to_content`` which may run BEFORE the
        window is laid out (sync path when an inventory is auto
        loaded from settings during ``__init__``). In that case
        ``vsplit.height()`` is 0 and we can't compute a sensible
        top height; the horizontal axis still applies, but
        ``mark_splitter_owned`` flips ``has_saved_splitter`` and
        blocks any future re-attempt. Schedule a one-shot retry
        for after the post-show layout pass so the vertical
        splitter still gets sized once before the user sees the
        analysis pane at the constructor default.
        """
        available = self._hsplit.width() or (seg_need_w + feat_need_w)
        feat_w = max(feat_need_w, available - seg_need_w)
        self._hsplit.setSizes([seg_need_w, feat_w])
        total = self._vsplit.height()
        if total > 0:
            top_h = min(top_need_h, total - self.min_analysis_h)
            top_h = max(top_h, 200)
            self._vsplit.setSizes([top_h, total - top_h])
            return
        QTimer.singleShot(
            0, lambda: self.fit_vsplit_after_layout(top_need_h)
        )

    def fit_vsplit_after_layout(self, top_need_h: int) -> None:
        """Vertical-only fallback for the case in
        ``apply_splitter_sizes`` where the window hadn't been laid
        out yet. Runs after one event-loop tick (post-show); if
        height is still 0 we accept the constructor default rather
        than recurse."""
        total = self._vsplit.height()
        if total <= 0:
            return
        top_h = min(top_need_h, total - self.min_analysis_h)
        top_h = max(top_h, 200)
        self._vsplit.setSizes([top_h, total - top_h])
