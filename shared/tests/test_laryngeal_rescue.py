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
