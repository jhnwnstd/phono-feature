"""Regression tests for header styling consistency on inventory reload.

Previously, ``set_headers_active`` cached its last-applied state to skip
redundant restyling. But ``set_groups`` (segment grid) and ``set_vowels``
(vowel chart) recreate the underlying header QLabel widgets on every
inventory load, initialised with their muted (``text_dim``) color. If
the cached active-state matched the requested active-state across that
reload, the dedup early-returned and the fresh labels stayed muted ;
visible to the user as a panel that "stayed in muted form until clicked."

These tests load an inventory in seg-mode (where seg-grid headers should
be bright), reload it, and assert the headers are still bright.
"""

from __future__ import annotations

from phonology_features.gui.shared.palette import C


def _is_bright_color(stylesheet: str) -> bool:
    """Heuristic: the header is bright if its color matches C['text']
    (the active color) and not C['text_dim'] (the muted color)."""
    if C["text_dim"].lower() in stylesheet.lower():
        return False
    return C["text"].lower() in stylesheet.lower()


def test_seg_grid_headers_bright_after_inventory_reload(window):
    """Loading an inventory in seg-mode and then reloading the same one
    must leave the seg-grid headers bright. The fixture loads Hayes in
    seg mode; we then reload to trigger the bug path."""
    window._load_path("inventories/hayes_features.json")
    headers = window.seg_grid_widget._headers
    assert headers, "expected seg-grid headers to be present after load"
    for hdr in headers:
        assert _is_bright_color(hdr.styleSheet()), (
            f"seg-grid header '{hdr.text()}' is muted after reload "
            f"in seg mode (stylesheet: {hdr.styleSheet()!r})"
        )


def test_seg_grid_headers_bright_after_inventory_switch(window):
    """Switching between two different inventories while in seg-mode
    must keep the seg-grid headers bright."""
    window._load_path("inventories/blevins_features.json")
    headers = window.seg_grid_widget._headers
    assert headers
    for hdr in headers:
        assert _is_bright_color(hdr.styleSheet()), (
            f"seg-grid header '{hdr.text()}' muted after switch to Blevins:"
            f" {hdr.styleSheet()!r}"
        )


def test_vowel_chart_headers_bright_after_reload(window):
    """Same regression for the vowel-chart row+column headers."""
    window._load_path("inventories/hayes_features.json")
    labels = window.vowel_chart_widget._header_labels
    assert labels, "expected vowel-chart headers"
    for lbl, _is_row in labels:
        assert _is_bright_color(lbl.styleSheet()), (
            f"vowel-chart header '{lbl.text()}' muted after reload:"
            f" {lbl.styleSheet()!r}"
        )


def test_seg_grid_headers_dim_when_in_feat_mode(window):
    """Sanity: in feat mode the seg-grid headers should be muted."""
    from phonology_features.gui.main_window import Mode

    window._set_mode(Mode.FEAT_TO_SEG)
    headers = window.seg_grid_widget._headers
    for hdr in headers:
        assert not _is_bright_color(hdr.styleSheet()), (
            f"seg-grid header '{hdr.text()}' should be muted in feat mode:"
            f" {hdr.styleSheet()!r}"
        )
