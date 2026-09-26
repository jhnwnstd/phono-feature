"""Laryngeal segments display in their manner homes.

The "Laryngeals" convenience row (h / ɦ / ʔ peeled out of their manner
classes when population guards allowed) is RETIRED: it was a
population cover that moved segments off their reached-class subtree,
so the same glottal displayed under different labels in different
inventories, and it even swallowed breathy-release plosives and
affricates (PHOIBLE ``pɦ`` / ``kǀh`` displayed under Laryngeals
instead of their reached Affricates). Display membership now never
leaves the reached-class subtree: h / ɦ sit among the fricatives, ʔ
among the plosives, exactly the standard manner-by-place chart layout
the old rescue's own guards fell back to.
"""

from __future__ import annotations

from phonology_shared.chart.consonants import group_segments


def _fric(**kw: str) -> dict[str, str]:
    base = {"consonantal": "+", "continuant": "+", "sonorant": "-"}
    base.update(kw)
    return base


def _stop(**kw: str) -> dict[str, str]:
    base = {
        "consonantal": "+",
        "continuant": "-",
        "sonorant": "-",
        "nasal": "-",
        "delrel": "-",
    }
    base.update(kw)
    return base


def _h() -> dict[str, str]:
    return _fric(spreadgl="+")  # voiceless glottal fricative


def _hh() -> dict[str, str]:
    return _fric(spreadgl="+", voice="+")  # breathy glottal fricative


def _glottal_stop() -> dict[str, str]:
    return _stop(constrgl="+")


def test_glottal_fricatives_stay_with_the_fricatives() -> None:
    groups = group_segments(
        {
            "h": _h(),
            "ɦ": _hh(),
            "f": _fric(labial="+"),
            "s": _fric(coronal="+"),
        }
    )
    assert "Laryngeals" not in groups
    fricatives = groups.get("Fricatives", [])
    assert "h" in fricatives and "ɦ" in fricatives


def test_glottal_stop_stays_with_the_plosives() -> None:
    groups = group_segments(
        {
            "ʔ": _glottal_stop(),
            "p": _stop(labial="+"),
            "t": _stop(coronal="+"),
        }
    )
    assert "Laryngeals" not in groups
    assert "ʔ" in groups.get("Plosives", [])


def test_no_population_ever_forms_a_laryngeals_row() -> None:
    """Even the population shape that used to fire the rescue (several
    glottals across two manner homes, no stranding) keeps every
    segment in its reach class."""
    groups = group_segments(
        {
            "h": _h(),
            "ɦ": _hh(),
            "ʔ": _glottal_stop(),
            "f": _fric(labial="+"),
            "s": _fric(coronal="+"),
            "p": _stop(labial="+"),
            "t": _stop(coronal="+"),
        }
    )
    assert "Laryngeals" not in groups
    assert "h" in groups.get("Fricatives", [])
    assert "ɦ" in groups.get("Fricatives", [])
    assert "ʔ" in groups.get("Plosives", [])


# --------------------------------------------------------------------
# The laryngeal breakout reads phases EXISTENTIALLY, not a collapsed
# single value. PHOIBLE states ejection on the RELEASE of an affricate:
# the real /tɬʼ/ row carries ``constrictedGlottis "-,+"`` and
# ``raisedLarynxEjective "-,+"`` alongside ``continuant "-,+"``. A read
# that keeps one value decides the sub-class by whichever phase the
# collapse happened to keep.
# --------------------------------------------------------------------


def _release_ejective_affricate() -> dict[str, str]:
    """Primary bundle of a /tɬʼ/-shaped segment: the onset anchor, so
    the ejective evidence is absent from it and present only in the
    sequences below. That asymmetry is the whole point."""
    return {
        "consonantal": "+",
        "sonorant": "-",
        "continuant": "-",
        "nasal": "-",
        "delrel": "-",
        "coronal": "+",
        "voice": "-",
        "constrgl": "-",
        "raisedlarynxejective": "-",
    }


def _release_ejective_sequences() -> dict[str, tuple[str, ...]]:
    return {
        "continuant": ("-", "+"),
        "delrel": ("-", "+"),
        "constrgl": ("-", "+"),
        "raisedlarynxejective": ("-", "+"),
    }


def _ejective_affricate_inventory() -> (
    tuple[dict[str, dict[str, str]], dict[str, dict[str, tuple[str, ...]]]]
):
    """Three release-ejective affricates, a PLAIN affricate so the
    Affricates parent is not homogeneous (``_apply_breakout`` keeps the
    general label when every member matches), and plain plosives so the
    breakout's population guard can fire."""
    inv: dict[str, dict[str, str]] = {
        sym: _stop() for sym in ("p", "t", "k", "q")
    }
    seqs: dict[str, dict[str, tuple[str, ...]]] = {}
    for sym in ("tsʼ", "tɬʼ", "tθʼ"):
        inv[sym] = _release_ejective_affricate()
        seqs[sym] = _release_ejective_sequences()
    inv["ts"] = _release_ejective_affricate()
    seqs["ts"] = {"continuant": ("-", "+"), "delrel": ("-", "+")}
    return inv, seqs


def test_ejective_stated_on_the_release_still_peels_out() -> None:
    """The existential read finds the ejective phase and the Ejective
    Affricates row forms. A collapsed onset read sees ``-`` on every
    consulted feature and silently drops the whole row."""
    inv, seqs = _ejective_affricate_inventory()
    groups = group_segments(inv, sequences=seqs)
    assert sorted(groups.get("Ejective Affricates", [])) == [
        "tsʼ",
        "tɬʼ",
        "tθʼ",
    ], groups


def test_a_segment_no_phase_of_which_is_ejective_is_not_swept_in() -> None:
    """The guard's other side. Same shape, but nothing ever reaches
    ``+raisedlarynxejective``, so no phase derives EJECTIVE."""
    inv, seqs = _ejective_affricate_inventory()
    inv["tsʰ"] = _release_ejective_affricate()
    seqs["tsʰ"] = {
        "continuant": ("-", "+"),
        "delrel": ("-", "+"),
    }
    groups = group_segments(inv, sequences=seqs)
    assert "tsʰ" not in groups.get("Ejective Affricates", []), groups
