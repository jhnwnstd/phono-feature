# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Required Notice: Copyright 2026 John Winstead,
# https://github.com/jhnwnstd/phono-feature
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
    tab green or red per the natural-class verdict. Shared by
    :py:class:`AnalysisPanel` and :py:class:`AnalysisPeekPopup` so
    both surfaces show the cue identically; each previously had its
    own copy and they drifted on theme swaps.
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
            font-weight: bold;
        }}
        QTabBar::tab:selected {{
            background: {C["panel"]};
            color: {C["text"]};
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
    typographic glyph and gives every paste target the byte it
    expects. Both the plain-text and HTML mime payloads are
    translated so rich-text targets (a doc editor) agree with
    plain-text targets (a code editor).
    """

    # Add any new display-only glyph here (for example ``∅`` for
    # "universal"), not as scattered ``replace`` calls.
    _COPY_TRANSLATIONS = str.maketrans(
        {
            "−": "-",  # U+2212 MINUS SIGN to ASCII hyphen-minus
        }
    )

    def createMimeDataFromSelection(self) -> QMimeData | None:
        original = super().createMimeDataFromSelection()
        if original is None:
            return original
        text = original.text()
        translated = text.translate(self._COPY_TRANSLATIONS)
        # Fast path when the selection has no display-only chars.
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
    """Analysis output pane: three tabs (Class, Features, Contrasts).
    The selection chip strip (formerly a persistent header row above
    the tabs) now lives inside the Class tab body, so tab position is
    stable across mode swaps and no vertical space is reserved for the
    strip when a query has no chips.
    """

    _TAB_CLASS_IDX = 0
    _TAB_FEATURES_IDX = 1
    _TAB_CONTRASTS_IDX = 2

    # Floor for the active tab's content so a single-line output still
    # presents as a real pane, not a thin strip.
    _CONTENT_TAB_MIN_H = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        mono_font = QFont()
        mono_font.setFamilies(MONO_FAMILIES)
        mono_font.setPointSize(10)
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
        # Back-compat alias for ``self.analysis.content`` in older
        # tests + call sites; the Class tab is the primary output.
        self.content = self._tab_class
        self.content.setMinimumHeight(self._CONTENT_TAB_MIN_H)
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 2, 16, 8)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(2)
        layout.addWidget(self.tabs, 0, 0)
        layout.setRowStretch(0, 1)
        self._class_state: ClassState = ClassState.NEUTRAL
        self.apply_theme()

    def minimumSizeHint(self) -> QSize:
        """Sourced from ``REGION_CONSTRAINTS['analysis_panel']``. The
        Qt splitter and the vsplit fitting code consult this when
        deciding how much room the analysis pane can yield under
        resize pressure. The entry pins the bottom edge so a future
        ``setMinimumHeight(0)`` path can't silently collapse it."""
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
        set_css(self.tabs, _class_state_stylesheet(self._class_state))

    def set_html(self, html: str) -> None:
        """Single-blob entry point (validation-error path). Routes the
        whole HTML to the Class tab and clears the other tabs.
        """
        set_html(self._tab_class, html)
        set_html(self._tab_features, "")
        set_html(self._tab_contrasts, "")
        self._apply_class_state(ClassState.NEUTRAL)

    def set_sections(
        self,
        class_html: str,
        features_html: str,
        contrasts_html: str,
        *,
        contrasts_enabled: bool = True,
        class_state: str | ClassState = ClassState.NEUTRAL,
    ) -> None:
        """Push the three tab-body strings from the shared view-model.
        ``contrasts_enabled=False`` greys the Contrasts tab (single-
        segment SEG or any FEAT). If Contrasts was the active tab,
        focus jumps back to Class. ``class_state`` tints the Class
        tab: natural/not_natural/neutral.
        """
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
        ``QTabBar::tab:first`` rule appended. Background colour is the
        cue (palette ``plus_bg`` for natural, ``minus_bg`` for
        not-natural, default for neutral). Background rather than text
        colour stays readable for users with reduced colour vision and
        matches the web's ``data-class-state`` styling.
        """
        coerced = ClassState(state)
        if coerced is self._class_state:
            return
        self._class_state = coerced
        set_css(self.tabs, _class_state_stylesheet(coerced))

    def clear(self) -> None:
        """Canonical full-reset sink. Any new display cue added later
        must reset here too so a regression breaks the test, not the UI.
        """
        for tab in (self._tab_class, self._tab_features, self._tab_contrasts):
            tab.clear()
            # set_html caches HTML on the widget; drop the cache so a
            # later set_html(same-as-pre-clear) actually re-renders.
            if hasattr(tab, _LAST_HTML_ATTR):
                delattr(tab, _LAST_HTML_ATTR)
        self._apply_class_state(ClassState.NEUTRAL)
        self.tabs.setTabEnabled(self._TAB_CONTRASTS_IDX, True)
        self.tabs.setCurrentIndex(self._TAB_CLASS_IDX)
