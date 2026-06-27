"""Theme + colorblind-palette toggle for :class:`MainWindow`.

Owns the policy of how to repaint widgets when the active palette
changes (widgets themselves stay on MainWindow). Reaches through
``self._main`` for the widget tree and the few static style
helpers still living on MainWindow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolTip

from phonology_features._logging import get_logger
from phonology_features._settings import SettingsKey, write_setting
from phonology_features.gui.controllers.mode import ModeController
from phonology_features.gui.style_utils import (
    apply_app_palette,
    apply_tooltip_palette,
    set_css,
)
from phonology_features.gui.themed_widgets import (
    _clear_btn_style,
    _match_mode_btn_style,
)
from phonology_shared.presentation.constants import scrollbar_style
from phonology_shared.presentation.mode_logic import (
    palette_toggle_tooltip,
    theme_toggle_glyph,
    theme_toggle_tooltip,
)
from phonology_shared.presentation.palette import (
    C,
    PaletteMode,
    Theme,
    get_palette_mode,
    get_theme_name,
    set_palette_mode,
    set_theme,
)

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QFrame

    from phonology_features.gui.main_window import MainWindow

_log = get_logger(__name__)


def detect_system_theme(default: str = "light") -> str:
    """Return "dark" if the OS reports dark mode, else "light".

    Uses Qt's ``styleHints().colorScheme()`` (Qt 6.5+); falls back
    to ``default`` when no QApplication exists or Qt reports
    Unknown. Lives here (desktop-only) rather than in
    :py:mod:`phonology_shared.presentation.palette` so the shared
    package stays Qt-free; the web build never needs it.
    """
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return default
    hints = app.styleHints()
    if hints is None or not hasattr(hints, "colorScheme"):
        return default
    scheme = hints.colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    return default


class ThemeController:
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
    def filled_btn_style(family: str, padding: str) -> str:
        """Solid-fill action-button QSS (Save / Delete / Create Grid).

        ``family`` selects the palette colour group (``btn_primary``
        or ``btn_danger``); ``padding`` sets the box padding (the
        height-pinned toolbar buttons use ``0 16px``, dialog buttons
        pad vertically with ``6px 20px``).
        """
        return f"""
            QPushButton {{
                background: {C[family]};
                color: {C[f"{family}_text"]};
                border: none;
                border-radius: 6px;
                padding: {padding};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C[f"{family}_hover"]};
                color: {C[f"{family}_hover_text"]};
            }}
        """

    @staticmethod
    def combo_style() -> str:
        """Inventory-dropdown QSS: THE single home for this widget.

        Styles the box to look button-like (so it visibly invites a
        click) and themes the popup list. The Fusion native arrow is
        suppressed by any QComboBox rule without a paired down-arrow
        image asset; that trade-off is intentional because the
        box-as-button styling reads as a dropdown affordance on its
        own. The ``::drop-down`` rule removes the subcontrol border
        and pads the (assetless) arrow zone.

        Both the construction styling and the theme/palette restyle
        (``_restyle_toolbar``) call this, so the dropdown cannot shift
        its background or gain/lose the drop-down rule on the first
        toggle.
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
        """

    def toggle(self) -> None:
        """Switch between light and dark in place.

        Geometry, splitter sizes, selections, and the widget tree are
        preserved; only stylesheet strings change.
        """
        new_theme = (
            Theme.DARK
            if Theme(get_theme_name()) is Theme.LIGHT
            else Theme.LIGHT
        )
        _log.info("theme toggle: %s", new_theme.value)
        set_theme(new_theme)
        write_setting(self._main._settings, SettingsKey.THEME, new_theme.value)
        self.apply()

    def toggle_palette_mode(self) -> None:
        """Flip between standard and colorblind palettes in place.

        The light/dark axis is preserved; only the hue family changes.
        Same in-place re-style path as :py:meth:`toggle`.
        """
        new_mode = (
            PaletteMode.COLORBLIND
            if PaletteMode(get_palette_mode()) is PaletteMode.STANDARD
            else PaletteMode.STANDARD
        )
        _log.info("palette mode toggle: %s", new_mode.value)
        set_palette_mode(new_mode)
        write_setting(
            self._main._settings, SettingsKey.PALETTE_MODE, new_mode.value
        )
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
                    ModeController.panel_chrome_qss(panel.objectName()),
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
        # One home for the dropdown QSS: the same string construction
        # uses, so the box does not jump background or gain the
        # drop-down rule on the first toggle.
        set_css(m.inventory_combo, self.combo_style())
        nav_style = self.nav_btn_style()
        for btn in m._nav_buttons:
            set_css(btn, nav_style)
        self.apply_theme_btn()
        self.apply_cb_btn()

    def apply_theme_btn(self) -> None:
        """Set the theme-button text, tooltip, and styling.

        The symbol shows the OPPOSITE of the active theme: clicking
        switches to that.
        """
        is_dark = Theme(get_theme_name()) is Theme.DARK
        btn: QPushButton = self._main._theme_btn
        btn.setText(theme_toggle_glyph(is_dark=is_dark))
        btn.setToolTip(theme_toggle_tooltip(is_dark=is_dark))
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

    def apply_cb_btn(self) -> None:
        """Set the colorblind-toggle text, tooltip, and styling.

        Uses the eye-glyph (U+1F441) so the icon reads as "vision
        mode" rather than "theme". The button fill switches to the
        accent when colorblind mode is on so the active state is
        visible at a glance, matching the toolbar nav buttons'
        hover affordance.
        """
        is_cb = PaletteMode(get_palette_mode()) is PaletteMode.COLORBLIND
        btn: QPushButton = self._main._cb_btn
        btn.setText("\U0001f441")
        btn.setToolTip(palette_toggle_tooltip(is_colorblind=is_cb))
        if is_cb:
            qss = f"""
                QPushButton {{
                    background: {C["accent_light"]};
                    color: {C["accent"]};
                    border: 1.5px solid {C["accent"]};
                    border-radius: 6px;
                }}
                QPushButton:hover {{
                    background: {C["accent"]};
                    color: {C["btn_primary_text"]};
                    border: 1.5px solid {C["accent"]};
                }}
            """
        else:
            qss = f"""
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
            """
        set_css(btn, qss)

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
        # Re-apply the wildcard toggle's QSS so the ``:checked``
        # accent fill switches to the new palette's accent
        # (standard ⇄ colorblind, light ⇄ dark all share this hook).
        set_css(m._match_mode_btn, _match_mode_btn_style())
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
