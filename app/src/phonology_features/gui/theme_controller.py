"""Theme toggle and chrome restyle for :class:`MainWindow`.

Owns every code path that runs when the active palette changes.

The controller does not own widgets; it only owns the *policy* of how
to repaint them when the theme changes. Widgets remain MainWindow
state. The controller reaches through ``self._main`` for both the
widget tree and the small handful of static style helpers
(``_apply_title_palette``) that still live on MainWindow.

Split rationale: theme handling crossed nine inline methods on
MainWindow and a hundred and fifty lines of code. Centralizing them
makes the cross-widget polish order explicit (palette before
property-selector polish, scrollbars before panel chrome) and lets
:py:meth:`apply` read as a single sequence rather than a chain of
private helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QLabel, QPushButton, QToolTip

from phonology_features._logging import get_logger
from phonology_features.gui.constants import scrollbar_style
from phonology_features.gui.mode_controller import _ModeController
from phonology_features.gui.palette import (
    C,
    get_theme_name,
    set_theme,
)
from phonology_features.gui.style_utils import (
    apply_app_palette,
    apply_tooltip_palette,
    set_css,
)
from phonology_features.gui.themed_widgets import _clear_btn_style

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QFrame

    from phonology_features.gui.main_window import MainWindow

_log = get_logger(__name__)


class _ThemeController:
    """Theme toggle and palette-driven chrome restyle for MainWindow.

    Construct after ``_build_ui`` has finished so the controller can
    reach the populated widget references through its back pointer.
    """

    def __init__(self, main: MainWindow) -> None:
        self._main = main

    @staticmethod
    def nav_btn_style() -> str:
        """Toolbar nav-button stylesheet evaluated against the active
        palette. Shared between construction and theme re-styling.
        """
        return f"""
            QPushButton {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                background: {C["accent_light"]};
                border: 1.5px solid {C["accent"]};
                color: {C["accent"]};
            }}
        """

    @staticmethod
    def combo_style() -> str:
        """Inventory-dropdown QSS.

        Styles the box to look button-like (so it visibly invites a
        click) and themes the popup list. The Fusion native arrow is
        suppressed by any QComboBox rule without a paired down-arrow
        image asset; that trade-off is intentional because the
        box-as-button styling reads as a dropdown affordance on its
        own.
        """
        return f"""
            QComboBox {{
                background: {C["bg"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 10px;
            }}
            QComboBox:hover {{
                border: 1.5px solid {C["accent"]};
            }}
            QComboBox QAbstractItemView {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                selection-background-color: {C["accent_light"]};
                selection-color: {C["accent"]};
                outline: none;
            }}
        """

    def toggle(self) -> None:
        """Switch between light and dark in place.

        Geometry, splitter sizes, selections, and the widget tree are
        preserved; only stylesheet strings change.
        """
        new_theme = "dark" if get_theme_name() == "light" else "light"
        _log.info("theme toggle: %s", new_theme)
        set_theme(new_theme)
        self._main._settings.setValue("theme", new_theme)
        self.apply()

    def apply(self) -> None:
        """Re-style every palette-dependent widget in place.

        Drops the cached :class:`InventoryBuilder` first (it caches
        palette-dependent button stylesheets at construction and
        never re-styles); modality prevents the builder from being
        open at this point, so this never destroys an in-use window.
        Then re-styles segment buttons, feature rows, and the
        chrome chain.
        """
        m = self._main
        QToolTip.hideText()
        if m._builder is not None:
            m._builder.deleteLater()
            m._builder = None
        with m._batched_updates():
            # Skip pool entries detached from the layout (orphans from
            # prior inventories). ``_get_or_create_seg_button`` calls
            # ``apply_theme`` on re-attachment so a stale orphan picks
            # up the new palette before it becomes visible.
            for btn in m._seg_button_pool.values():
                if btn.parent() is None:
                    continue
                btn.apply_theme()
            # Iterate every FeatureRow we own, not just the pool. The
            # "Other" card in inventories with non-FEATURE_ORDER
            # features (for example general_features.json) creates
            # rows that live in ``_feat_rows`` but NOT in
            # ``_feat_row_pool``. Missing them leaves their name and
            # +/- buttons styled with the old palette; in dark mode
            # after starting from light, the name label's text color
            # stays light against the dark bg, making the name appear
            # "unpopulated".
            for row in m._feat_row_pool.values():
                row.apply_theme()
            for feat, row in m._feat_rows.items():
                if feat not in m._feat_row_pool:
                    row.apply_theme()
            self._restyle_chrome()
            # Refresh panel-chrome QSS rules then re-polish so the
            # active-mode border picks up the new accent color.
            for panel in (m.seg_panel, m.feat_panel):
                set_css(
                    panel,
                    _ModeController.panel_chrome_qss(panel.objectName()),
                )
                panel.setProperty("active", None)
            m._mode_ctrl.apply_panel_chrome()
            m._mode_ctrl.refresh_analysis()

    def _restyle_chrome(self) -> None:
        """Re-apply every chrome stylesheet that depends on the palette.

        Each helper touches one logical group of widgets in place.
        """
        # Tooltip colors refresh via the shared QToolTip palette,
        # NOT via ``app.setStyleSheet``. The latter would re-polish
        # every widget in the tree and turn theme toggle into a
        # hundred-millisecond stall on populated inventories. The
        # shape rules (border, radius, padding) were applied once at
        # startup in :py:func:`app_qss` and do not change with theme.
        apply_tooltip_palette()
        # QApplication palette governs widgets that do not go through
        # our :py:func:`set_css` discipline: QDialog/QFileDialog/
        # QMessageBox/QInputDialog, default QPushButton chrome,
        # QLineEdit text colors, and so on. Without this refresh, dark
        # mode would leave file-dialog text black on a dark background.
        apply_app_palette()
        m = self._main
        set_css(m, f"background-color: {C['bg']};")
        self._restyle_toolbar()
        self._repaint_splitter_handles()
        self._restyle_panel_chrome_widgets()
        self._restyle_feature_cards()
        m.seg_grid_widget.apply_theme()
        m.vowel_chart_widget.apply_theme()
        m.analysis.apply_theme()
        m.status.apply_theme()

    def _restyle_toolbar(self) -> None:
        m = self._main
        set_css(
            m._toolbar,
            f"""
            QToolBar {{
                background: {C["panel"]};
                border-bottom: 1px solid {C["border"]};
                padding: 4px 8px;
                spacing: 6px;
            }}
        """,
        )
        set_css(
            m.inventory_combo,
            f"""
            QComboBox {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
                padding: 0 10px;
            }}
            QComboBox:hover {{
                border: 1.5px solid {C["accent"]};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                selection-background-color: {C["accent_light"]};
                selection-color: {C["accent"]};
                outline: none;
            }}
        """,
        )
        nav_style = self.nav_btn_style()
        for btn in m._nav_buttons:
            set_css(btn, nav_style)
        self.apply_theme_btn()

    def apply_theme_btn(self) -> None:
        """Set the theme-button text, tooltip, and styling.

        The symbol shows the OPPOSITE of the active theme: clicking
        switches to that.
        """
        is_dark = get_theme_name() == "dark"
        btn: QPushButton = self._main._theme_btn
        btn.setText("☼" if is_dark else "☾")
        btn.setToolTip(
            "Switch to light mode" if is_dark else "Switch to dark mode"
        )
        set_css(
            btn,
            f"""
            QPushButton {{
                background: transparent;
                color: {C["text_dim"]};
                border: 1.5px solid {C["border"]};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                color: {C["accent"]};
                border: 1.5px solid {C["accent"]};
            }}
        """,
        )

    def _repaint_splitter_handles(self) -> None:
        """Force splitter handles to repaint with the live palette.

        :py:meth:`_ThemedHandle.paintEvent` reads ``C`` on each paint,
        but the handles do not automatically know the palette changed.
        One ``update()`` per handle is essentially free (no polish
        cascade, just queues a single paint).
        """
        m = self._main
        for splitter in (m._hsplit, m._vsplit):
            for i in range(splitter.count()):
                handle = splitter.handle(i)
                if handle is not None:
                    handle.update()

    def _restyle_panel_chrome_widgets(self) -> None:
        """Re-style panel-child widgets with palette-dependent styles.

        Clear buttons, scroll bars, the seg hint. Scrollbar styles go
        directly on each :class:`QScrollBar` widget (not the scroll
        area) so the cascade does not invalidate every panel
        descendant. Panel container backgrounds and borders are
        handled separately via property-selector polish in
        :py:meth:`apply`.
        """
        m = self._main
        set_css(m.clear_seg_btn, _clear_btn_style())
        set_css(m.clear_feat_btn, _clear_btn_style())
        sb_qss = scrollbar_style()
        for scroll in (m._seg_scroll, m._feat_scroll):
            for bar in (
                scroll.verticalScrollBar(),
                scroll.horizontalScrollBar(),
            ):
                if bar is not None:
                    set_css(bar, sb_qss)
        set_css(m.seg_hint, f"color: {C['text_dim']};")

    def _restyle_feature_cards(self) -> None:
        """Refresh each feature-group card and its title.

        Cards are :class:`_ThemedCard` instances that paint themselves
        from the live palette. One ``update()`` per card queues a
        single repaint with no polish cascade. Title color lives in
        QPalette so re-applying it is cheap and does not cascade
        either.
        """
        m = self._main
        cards: list[QFrame] = [card for card, _ in m._feat_cards]
        if m._other_card is not None:
            cards.append(m._other_card)
        for card in cards:
            card.update()
            title = card.findChild(QLabel)
            if title is not None:
                m._apply_title_palette(title)
