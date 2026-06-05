"""Bottom-pane analysis tabs + the clipboard-safe text-edit subclass
that backs them. ``_class_state_stylesheet`` lives here too because
it's specific to the analysis pane's QTabBar.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGridLayout,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from phonology_features.gui.style_utils import (
    _LAST_HTML_ATTR,
    set_css,
    set_html,
)
from phonology_shared.presentation.constants import (
    MONO_FAMILIES,
    scrollbar_style,
)
from phonology_shared.presentation.layout import REGION_CONSTRAINTS
from phonology_shared.presentation.palette import (
    C,
    ClassState,
    class_state_palette_keys,
)


def _class_state_stylesheet(class_state: str | ClassState) -> str:
    """Compose the analysis pane's QTabBar stylesheet with an
    optional ``QTabBar::tab:first`` override that paints the Class
    tab green / red per the natural-class verdict. Shared by
    :py:class:`AnalysisPanel` and :py:class:`AnalysisPeekPopup` so
    both surfaces show the cue identically; previously they each
    had their own private copy and drifted on theme swaps.
    """
    base = f"""
        QTabWidget::pane {{
            border: 1px solid {C["border"]};
            border-radius: 6px;
        }}
        QTabBar::tab {{
            background: {C["bg"]};
            color: {C["text_dim"]};
            border: 1px solid {C["border"]};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 4px 14px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {C["panel"]};
            color: {C["text"]};
            font-weight: bold;
        }}
        QTabBar::tab:hover:!selected {{
            color: {C["text"]};
        }}
        QTabBar::tab:disabled {{
            color: {C["border"]};
        }}
    """
    keys = class_state_palette_keys(class_state)
    if keys is None:
        return base
    fg_key, bg_key = keys
    fg = C[fg_key]
    bg = C[bg_key]
    return base + f"""
        QTabBar::tab:first {{
            background: {bg};
            color: {fg};
        }}
        QTabBar::tab:first:selected {{
            background: {bg};
            color: {fg};
            font-weight: bold;
        }}
    """


class _CopyableTextEdit(QTextEdit):
    """``QTextEdit`` that normalises display-only characters back to
    their interchange forms at the clipboard boundary.

    The analysis pane renders feature minus values as U+2212 (`−`,
    MATHEMATICAL MINUS SIGN) for typographic symmetry with `+`. The
    rest of the ecosystem (JSON files, code, regex, most terminals)
    expects ASCII U+002D (`-`, HYPHEN-MINUS). Pasting `−Voice` into
    a JSON value silently does NOT match `"-"`.

    Translating at the copy boundary lets the display layer keep the
    nice typographic glyph and gives every paste target the byte
    they expect. Both the plain-text and HTML mime payloads get
    translated so rich-text targets (a doc editor) agree with
    plain-text targets (a code editor).
    """

    # ``str.maketrans`` precomputes the translation table at class
    # load. The dict literal is intentionally minimal: if we ever
    # add another display-only glyph (for example ``∅`` for
    # "universal"), add it here, not as scattered ``replace`` calls.
    _COPY_TRANSLATIONS = str.maketrans(
        {
            "−": "-",  # U+2212 MINUS SIGN -> ASCII hyphen-minus
        }
    )

    def createMimeDataFromSelection(self) -> QMimeData | None:
        original = super().createMimeDataFromSelection()
        if original is None:
            return original
        text = original.text()
        translated = text.translate(self._COPY_TRANSLATIONS)
        # Fast path: no display-only chars in the selection.
        if text == translated and not original.hasHtml():
            return original
        out = QMimeData()
        out.setText(translated)
        if original.hasHtml():
            # Apply the same translation to the HTML payload so a
            # rich-text paste target sees the ASCII form too. Without
            # this, copying to e.g. a docx editor would still produce
            # U+2212 because Qt prefers the HTML payload for those.
            out.setHtml(original.html().translate(self._COPY_TRANSLATIONS))
        return out


class AnalysisPanel(QWidget):
    """Analysis output pane. The tab labels (Class / Features /
    Contrasts) carry their own naming, so there's no top heading.

    Layout (single ``QGridLayout``):

    - Row 0 hosts the persistent selection label. A reserved row
      minimum height keeps the selection strip's vertical footprint
      stable when the label is hidden (FEAT mode), so the tab bar's
      ``y`` does not shift between modes.
    - Row 1 hosts the tab widget; it absorbs all vertical stretch.

    The pane is non-resizable: ``REGION_CONSTRAINTS['analysis_panel']``
    pins its floor at the comfortable four-row minimum, and each tab's
    ``_CopyableTextEdit`` (a ``QTextEdit`` subclass) provides built-in
    scrollbars when the content overflows.
    """

    # Index in ``self.tabs`` for the Contrasts tab, kept as a class
    # constant so ``set_sections`` can enable/disable it cleanly. Order
    # also matches the user's chosen reading order: Class first (the
    # analytical conclusion), then Features (raw spec), then Contrasts
    # (only meaningful for multi-segment SEG mode).
    _TAB_CLASS_IDX = 0
    _TAB_FEATURES_IDX = 1
    _TAB_CONTRASTS_IDX = 2

    # Reserved minimum height for row 0 (the selection-label strip).
    # 26 px keeps the strip's vertical footprint stable when the
    # selection label hides in FEAT mode so the tab bar below does
    # not jump between modes.
    _SELECTION_ROW_MIN_H = 26

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Pane absorbs leftover vertical space inside the vsplit and
        # stretches with the window horizontally. ``minimumSizeHint``
        # below pins the floor; ``REGION_CONSTRAINTS['analysis_panel']``
        # is the single source for both ends.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        # Persistent header content: "Selected: /a/ /b/" or
        # "Query: +Voice −Nasal". Stays visible regardless of which
        # tab is active so the user always sees what they selected.
        self.selection_label = _CopyableTextEdit(self)
        self.selection_label.setReadOnly(True)
        self.selection_label.setFixedHeight(38)
        mono_font = QFont()
        mono_font.setFamilies(MONO_FAMILIES)
        mono_font.setPointSize(10)
        self.selection_label.setFont(mono_font)
        # The three analysis tabs. Each contains its own
        # ``_CopyableTextEdit`` so tab swaps are cheap (no re-render)
        # and the cached-HTML short-circuit in ``set_html`` still
        # applies per tab. The Contrasts tab gets disabled (greyed
        # out, not removed) when the current selection has nothing
        # to compare.
        self.tabs = QTabWidget(self)
        self._tab_class = _CopyableTextEdit(self.tabs)
        self._tab_features = _CopyableTextEdit(self.tabs)
        self._tab_contrasts = _CopyableTextEdit(self.tabs)
        for tab_widget in (
            self._tab_class,
            self._tab_features,
            self._tab_contrasts,
        ):
            tab_widget.setReadOnly(True)
            tab_widget.setFont(mono_font)
        self.tabs.addTab(self._tab_class, "Class")
        self.tabs.addTab(self._tab_features, "Features")
        self.tabs.addTab(self._tab_contrasts, "Contrasts")
        # Back-compat alias so the existing ``self.analysis.content``
        # references in tests + other code keep working; the Class
        # tab carries the most prominent analytical output so
        # ``.content`` lands there.
        self.content = self._tab_class
        self.content.setMinimumHeight(60)
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 2, 16, 8)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(2)
        # Row 0: selection label. The reserved minimum height keeps
        # the strip's footprint stable when the label hides in FEAT
        # mode so the tab bar's y does not shift.
        layout.setRowMinimumHeight(0, self._SELECTION_ROW_MIN_H)
        layout.addWidget(self.selection_label, 0, 0)
        layout.addWidget(self.tabs, 1, 0)
        layout.setRowStretch(1, 1)
        # Selection label starts hidden. Empty selection / FEAT
        # mode shouldn't render chips. ``set_sections`` toggles
        # visibility based on whether the html payload actually
        # carries chips.
        self.selection_label.setVisible(False)
        # Class-tab background-colour state (natural / not_natural /
        # neutral). ``apply_theme`` reads this when composing the
        # stylesheet so a theme swap mid-session keeps the cue.
        self._class_state: ClassState = ClassState.NEUTRAL
        self.apply_theme()

    def minimumSizeHint(self) -> QSize:
        """Sourced from ``REGION_CONSTRAINTS['analysis_panel']``. The
        Qt splitter and the vsplit fitting code consult this when
        deciding how much room the analysis pane can yield under
        resize pressure; the entry pins the bottom edge so future
        ``setMinimumHeight(0)`` paths can't silently collapse it."""
        constraint = REGION_CONSTRAINTS["analysis_panel"]
        return QSize(constraint.min_w, constraint.min_h)

    def apply_theme(self) -> None:
        """Re-apply palette-dependent styles. Called on theme toggle."""
        set_css(
            self,
            f"background: {C['analysis_bg']};"
            f" border-top: 1px solid {C['border']};",
        )
        text_edit_css = f"""
            QTextEdit {{
                background: {C["panel"]};
                color: {C["text"]};
                border: 1px solid {C["border"]};
                border-radius: 6px;
                padding: 8px;
            }}
            """ + scrollbar_style()
        for tab in (self._tab_class, self._tab_features, self._tab_contrasts):
            set_css(tab, text_edit_css)
        # Persistent selection header: same colour palette as the
        # tab bodies but no border (it sits flush above the tabs).
        set_css(
            self.selection_label,
            f"""
            QTextEdit {{
                background: transparent;
                color: {C["text"]};
                border: none;
                padding: 0 2px;
            }}
            """,
        )
        set_css(self.tabs, _class_state_stylesheet(self._class_state))

    def set_html(self, html: str) -> None:
        """Legacy single-blob entry point. Routes the whole HTML to
        the Class tab so anything still calling this from outside the
        view-model layer keeps working. New call sites should use
        :py:meth:`set_sections` so the three tabs each carry their
        own content."""
        set_html(self._tab_class, html)
        self.selection_label.setHtml("")
        set_html(self._tab_features, "")
        set_html(self._tab_contrasts, "")

    def set_sections(
        self,
        selection_html: str,
        class_html: str,
        features_html: str,
        contrasts_html: str,
        *,
        contrasts_enabled: bool = True,
        class_state: str | ClassState = ClassState.NEUTRAL,
    ) -> None:
        """Push the four analysis sections produced by the shared
        view-model into the persistent selection header + three tabs.

        ``contrasts_enabled=False`` greys out the Contrasts tab and
        prevents activation. Used for single-segment SEG selections
        and for FEAT mode, where contrasts aren't meaningful. If the
        currently-active tab is the disabled one, focus jumps back
        to the Class tab so the user lands on real content instead
        of a placeholder explaining why the tab is empty.

        ``class_state`` colours the Class tab text: ``"natural"``
        maps to palette ``plus`` (green), ``"not_natural"`` maps to
        palette ``minus`` (red), anything else uses the default text
        colour. The coloured tab replaces the previous "Natural
        class: Yes/No" text in the tab body.

        Empty ``selection_html`` hides the persistent selection
        label entirely (no reserved strip of space). Used in FEAT
        mode where the query is already explicit in the Features
        tab.
        """
        if selection_html:
            self.selection_label.setHtml(selection_html)
            self.selection_label.setVisible(True)
        else:
            self.selection_label.clear()
            self.selection_label.setVisible(False)
        set_html(self._tab_class, class_html)
        set_html(self._tab_features, features_html)
        set_html(self._tab_contrasts, contrasts_html)
        self.tabs.setTabEnabled(self._TAB_CONTRASTS_IDX, contrasts_enabled)
        if (
            not contrasts_enabled
            and self.tabs.currentIndex() == self._TAB_CONTRASTS_IDX
        ):
            self.tabs.setCurrentIndex(self._TAB_CLASS_IDX)
        self._apply_class_state(class_state)

    def _apply_class_state(self, state: str | ClassState) -> None:
        """Colour the first tab (Class) per the natural-class verdict.

        Re-applies the full tab-bar stylesheet with a state-specific
        ``QTabBar::tab:first`` rule appended. Background colour is
        the cue (palette ``plus_bg`` for natural, ``minus_bg`` for
        not-natural, default for neutral); using background instead
        of text colour stays readable for users with reduced colour
        vision and is consistent with the web's ``data-class-state``
        styling.
        """
        coerced = ClassState(state)
        if coerced is self._class_state:
            return
        self._class_state = coerced
        set_css(self.tabs, _class_state_stylesheet(coerced))

    def clear(self) -> None:
        """Reset the analysis pane to its post-construction state.

        Canonical full-reset sink. After this returns, every observable
        visual cue (tab bodies, tab colour, tab enable, active tab,
        chips strip) is back to its empty baseline. Any new display
        cue added later must reset here too, so a future regression
        breaks ``test_analysis_panel_clear`` instead of the UI.
        """
        self.selection_label.clear()
        self.selection_label.setVisible(False)
        for tab in (self._tab_class, self._tab_features, self._tab_contrasts):
            tab.clear()
            # set_html caches the last HTML string on the widget and
            # short-circuits duplicate calls. clear() resets the widget
            # but not the cache, so a later set_html(X) where X matches
            # the pre-clear value would no-op and leave the pane blank.
            if hasattr(tab, _LAST_HTML_ATTR):
                delattr(tab, _LAST_HTML_ATTR)
        if hasattr(self.selection_label, _LAST_HTML_ATTR):
            delattr(self.selection_label, _LAST_HTML_ATTR)
        self._apply_class_state(ClassState.NEUTRAL)
        self.tabs.setTabEnabled(self._TAB_CONTRASTS_IDX, True)
        self.tabs.setCurrentIndex(self._TAB_CLASS_IDX)
