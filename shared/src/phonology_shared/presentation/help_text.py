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
    "<p>Every grouping and position here is decided only by a segment's"
    " <b>encoded features</b>. The symbol and its diacritics are never"
    " read: if a distinction is not in the features, the display cannot"
    " show it.</p>"
    "<p><b>Consonants</b> are grouped by manner of articulation and,"
    " within each group, ordered by place from front to back. The"
    " groupings aim for reasonably canonical inventory groups while"
    " keeping the layout balanced, so no single group grows too visually"
    " dominant. A class with enough members for the inventory is shown on"
    " its own (sibilants split from fricatives, ejectives and implosives"
    " from plosives); a class too small to stand alone is folded into a"
    " broader cover label (Vibrants, Rhotics, Liquids). The same class can"
    " therefore stand alone in one inventory and merge in another."
    " Anything the features cannot place stays visible in a catch-all:"
    " Contoids below the consonants, Vocoids below the vowel chart.</p>"
    "<p>Because the chart aims to cover most cases rather than every"
    " possible analysis, treat the groupings as a representational"
    " convenience, not a theoretical claim. They may not be your preferred"
    " groupings for a given inventory, but they should be adequate for"
    " general use.</p>"
    "<p><b>Vowels</b> follow the same principle. Mapping discrete features"
    " onto a static, continuous vowel space necessarily takes"
    " representational shortcuts, so a vowel's position is a guide and a"
    " soft validation check, not the definitive phonetic vowel space for a"
    " language's speakers. Click the <b>Vowels</b> label above the chart"
    " for the specific placement rules.</p>"
)

#: Title of the ``Vowels`` help window.
VOWELS_HELP_TITLE: str = "How vowels are placed"

#: Body of the ``Vowels`` help window: the specific feature-to-space
#: rules, led by the low-vowel Near-open split, then the other bespoke
#: display decisions a user might notice and question.
VOWELS_HELP_HTML: str = (
    "<p>A vowel's row and column come only from its features. When"
    " features are missing or contradictory, it is drawn at a"
    " low-confidence anchor, a stable place to show it, not a claim about"
    " its phonetics.</p>"
    "<p><b>Height (rows).</b> [+high] is Close, [+low] is Open, and"
    " [-high, -low] is the mid region. Where an inventory uses a tense or"
    " ATR distinction it refines the tier: [-tense] high becomes"
    " Near-close, and the mid region splits into Close-mid [+tense] versus"
    " Open-mid [-tense]. A plain [-high, -low] vowel with no tense or ATR"
    " value sits on the middle Mid row.</p>"
    "<p><b>Low vowels and /a/.</b> A low vowel ([-high, +low], including"
    " the central [-front, -back] /a/) normally sits on the bottom Open"
    " row. If it also carries [-tense] (or [-ATR]; [+RTR] counts as"
    " [-ATR]) and the inventory uses a tense or ATR distinction, it moves"
    " up one row to Near-open. A [+tense] low vowel, or one with no tense"
    " or ATR value, stays on Open. This low-vowel split is theory"
    " sensitive (some analyses, following Hayes, leave all low vowels on"
    " Open); it is on by default here.</p>"
    "<p><b>Backness (columns).</b> [+front] is Front, [+back] is Back, and"
    " [-front, -back] is Central. [-back] on its own is not treated as"
    " front. Where rounding is used, an unrounded and rounded vowel form a"
    " side-by-side pair (unrounded on the left); a vowel with no rounding"
    " value sits centred on its backness anchor, the schwa pattern.</p>"
    "<p><b>Relative features</b> nudge a base placement: [+raised] or"
    " [+lowered] by one row, [+advanced] or [+retracted] by one column,"
    " [+centralized] toward Central. A feature and its opposite cancel.</p>"
    "<p><b>Things you may notice.</b></p>"
    "<ul>"
    "<li>Length is not a position. Vowels differing only in [long] share a"
    " cell and show the contrast as one connected capsule.</li>"
    "<li>Two vowels differing on exactly one of length, nasality,"
    " rhoticity, phonation, tone, or pharyngealization render as one"
    " segmented capsule (the marked member on the right); two such"
    " contrasts make a small 2x2 capsule. Otherwise co-located vowels"
    " stack.</li>"
    "<li>Diphthongs are never placed inside the trapezoid. They appear as"
    " labelled chips below it, with an arrow between their endpoints.</li>"
    "<li>A lone low vowel with no front vowels present is drawn in the"
    " bottom-left corner instead of floating at the middle of the narrow"
    " bottom edge.</li>"
    "<li>The trapezoid narrows toward the bottom because open vowels carry"
    " less front/back contrast. The shape is a convention, not a"
    " measurement.</li>"
    "</ul>"
)
