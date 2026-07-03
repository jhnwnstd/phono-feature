"""User-facing help copy for the Segments pane, shared by both UIs.

The Segments pane exposes two click-to-open help windows: the pane's
``SEGMENTS`` title explains how to read the consonant AND vowel displays
at a philosophy level, and the ``Vowels`` chart title drills into the
specific feature-to-space placement rules. Keeping the copy here makes
it the single source of truth: the desktop imports these constants
directly, and ``web/scripts/build.py`` bakes them into an inline
``application/json`` block the web reads (mirroring the status-text
relay), so the two frontends can never show different wording.

The bodies are a conservative HTML subset (``<p>``, ``<b>``, ``<ul>``,
``<li>``) that renders identically in a Qt rich-text widget and in the
browser. Feature notation uses plain brackets (``[-tense]``) so it needs
no markup. The wording is grounded in the actual heuristics:

* consonants: manner grouping + place-ordering + size-driven
  breakout/merge, all from encoded features
  (:mod:`phonology_shared.chart.consonants`);
* vowels: the height/backness/rounding inference and the low-vowel
  Near-open split (:mod:`phonology_shared.chart.vowels`), the Open-row
  migration (:mod:`phonology_shared.chart.vowel_geometry.display_slots`).
"""

from __future__ import annotations

#: Title of the ``SEGMENTS`` help window.
SEGMENTS_HELP_TITLE: str = "How to read the segment displays"

#: Body of the ``SEGMENTS`` help window: the shared philosophy behind
#: both the consonant groups and the vowel chart. The substance-free
#: framing is stated ONCE here (it governs everything) so the Vowels
#: window need not repeat it.
SEGMENTS_HELP_HTML: str = (
    "<p><i>Copy any segment by right clicking the button.</i></p>"
    "<p>A segment's encoded features alone decide its grouping and"
    " position. The chart never infers features from the symbol or its"
    " diacritics. If the features do not encode a distinction, the display"
    " cannot show it.</p>"
    "<p>The display covers most use cases, not every possible analysis."
    " Treat its groupings and positions as representational conveniences,"
    " not as theoretical claims. Anything the features cannot place stays"
    " visible in a catch-all group: Contoids appear below the consonants,"
    " and Vocoids appear below the vowel chart.</p>"
    "<p><b>Consonants</b> are grouped by manner of articulation and,"
    " within each group, ordered by place from front to back. The groups"
    " aim to be reasonably canonical while keeping the layout balanced, so"
    " no single group becomes visually dominant. A class with enough"
    " members in the inventory forms its own group. For example, sibilants"
    " may split from fricatives, and ejectives or implosives may split"
    " from plosives. A class too small to stand alone folds into a broader"
    " cover label, such as Vibrants, Rhotics, or Liquids."
    " The same class can therefore stand alone in one inventory and merge"
    " into a broader group in another.</p>"
    "<p><b>Vowels</b> follow the same principle. Mapping discrete features"
    " onto a static, continuous vowel space requires representational"
    " shortcuts. A vowel's position is therefore a guide and a soft"
    " validation check, not the definitive phonetic vowel space for a"
    " language's speakers. Click the <b>Vowels</b> label above the chart"
    " for the specific placement rules.</p>"
)

#: Title of the ``Vowels`` help window.
VOWELS_HELP_TITLE: str = "How vowels are placed"

#: Body of the ``Vowels`` help window: the specific feature-to-space
#: placement rules (height, the low-vowel Near-open split, backness,
#: relative features, rounding, secondary-feature capsules, diphthongs,
#: and the lone-low-vowel corner).
VOWELS_HELP_HTML: str = (
    "<p>Chart placement does not imply a vowel's exact phonetic value. If a"
    " vowel has missing or contradictory features, the chart falls back to a"
    " fixed position so the vowel remains visible.</p>"
    "<p><b>Height (rows)</b><br>A vowel's height determines its row. [+high]"
    " maps to Close, [+low] maps to Open, and [-high, -low] maps to the mid"
    " regions. If the inventory uses tense or ATR contrasts, those features"
    " select a finer row. A [-tense] high vowel maps to Near-close. A"
    " [+tense] mid vowel maps to Close-mid, and a [-tense] mid vowel maps to"
    " Open-mid. A mid vowel with no tense or ATR value maps to the plain Mid"
    " row.</p>"
    "<p><b>Low vowels and /a/</b><br>Low vowels normally remain on the Open"
    " row. This includes central /a/, which carries the features [-front,"
    " -back]. If a low vowel is also [-tense], [-ATR], or [+RTR], and the"
    " inventory uses tense or ATR contrasts, the vowel moves up to the"
    " Near-open row. A [+tense] low vowel, or a low vowel with no tense or"
    " ATR value, remains Open. This rule is theory-sensitive. Some analyses"
    " keep all low vowels on Open; this chart splits by default.</p>"
    "<p>If the Open (bottom) row has no front vowel, a central vowel there,"
    " such as a lone /a/, sits in the bottom-left corner instead of the"
    " bottom-center edge.</p>"
    "<p><b>Backness (columns)</b><br>A vowel's backness determines its"
    " column. A [+front] vowel sits in the Front column. A [+back] vowel"
    " sits in the Back column. A [-front, -back] vowel sits in the Central"
    " column. The feature [-back] by itself does not imply [+front].</p>"
    "<p><b>Relative features</b> shift a vowel from its base position."
    " [+raised] moves a vowel up one row. [+lowered] moves it down one row."
    " [+advanced] moves it one column forward. [+retracted] moves it one"
    " column backward. [+centralized] moves it toward the Central column."
    " Opposing pairs cancel: a vowel marked both [+raised] and [+lowered],"
    " or both [+advanced] and [+retracted], stays put.</p>"
    "<p><b>Rounded</b> and <b>unrounded</b> vowels of the same height and"
    " backness sit side by side in their column, the unrounded vowel on the"
    " left and the rounded vowel on the right. Front, central, and back"
    " columns all work this way. A vowel with no rounding feature sits"
    " centered in its own column instead.</p>"
    "<p><b>Secondary features</b> like length, nasality, rhoticity,"
    " phonation, tone, and pharyngealization do not change a vowel's row or"
    " column. Two vowels that differ in exactly one of these features share"
    " one segmented capsule. If two such contrasts are present, the vowels"
    " form a small two-by-two capsule. Vowels that share a position but"
    " differ in more complex ways stack.</p>"
    "<p><b>Diphthongs</b> display in a list under the vowel chart.</p>"
)
