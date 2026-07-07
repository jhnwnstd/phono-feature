"""Anchor -> data-x projection under a converged-bottom slant (layer 4c).

Maps abstract backness anchors into the silhouette at a given display
y. Under the classic trapezoid the back edge is vertical (back is the
fixed point), so back vowels sit flush against a straight right edge
and everything to their left migrates toward it as the row narrows.
Under a converged bottom (a lone-low-vowel inventory triggered
``open_apex_backness``), the pivot slants from ``back_anchor`` at
``top_y`` to ``back_anchor_at_bottom`` at ``bottom_y`` so both edges
slant inward and cells at the bottom converge on the sole low vowel's
column.

Cell-blind: consumes only the silhouette + an abstract anchor + y;
the slot assigner has already picked each cell's canonical anchor by
this point. Cell-cell distances at any row are pivot-invariant, so
the shrink solver's per-row width demands keep the same meaning under
either regime.
"""

from __future__ import annotations

from phonology_shared.chart.vowel_geometry.model import VowelChartSilhouette


def width_at_y(silhouette: VowelChartSilhouette, y: float) -> float:
    """Linear interp between the silhouette's top and bottom widths
    at display y. The single projection-width definition the cell
    projection and the column headers share, so everything lies on
    the silhouette slant by construction.
    """
    if silhouette.bottom_y == silhouette.top_y:
        return silhouette.top_width
    t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
    return silhouette.top_width * (1.0 - t) + silhouette.bottom_width * t


def project_anchor_x(
    silhouette: VowelChartSilhouette, anchor_x: float, y: float
) -> float:
    """Projection of an abstract backness anchor into the silhouette
    at display y.

    Default (trapezoid): the back anchor is the fixed point at every
    y, so the silhouette's right edge stays a vertical line that back
    vowels sit flush against; everything to its left migrates toward
    it as the row narrows: ``back + width * (anchor - back)``.

    Converged bottom: when the silhouette carries a
    ``back_anchor_at_bottom`` distinct from ``back_anchor`` (set when
    the Open row has only one populated backness column), the pivot
    interpolates linearly from ``back_anchor`` at ``top_y`` to
    ``back_anchor_at_bottom`` at ``bottom_y``. Both edges slant
    inward, and cells at the bottom converge toward the apex the
    sole low vowel sits on. Cell-cell distances at any row are
    pivot-invariant, so the shrink solver's per-row width demands
    keep the same meaning under either regime.
    """
    top_pivot = silhouette.back_anchor
    bot_pivot = silhouette.back_anchor_at_bottom
    if bot_pivot is None or bot_pivot == top_pivot:
        pivot = top_pivot
    elif silhouette.bottom_y == silhouette.top_y:
        pivot = top_pivot
    else:
        t = (y - silhouette.top_y) / (silhouette.bottom_y - silhouette.top_y)
        pivot = top_pivot * (1.0 - t) + bot_pivot * t
    return pivot + width_at_y(silhouette, y) * (anchor_x - pivot)
