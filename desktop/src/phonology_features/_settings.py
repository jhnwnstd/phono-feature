"""Defensive QSettings reads.

Centralizes the two failure classes that can occur reading a stored
QSettings value at startup, both of which would otherwise crash the
app before the GUI is on screen.

1. **Unmarshallable values.** Older builds wrote pickled enum members
   under the old package name. After a rename, ``QSettings.value``
   raises ``SystemError`` / ``ModuleNotFoundError`` trying to load the
   stale class. The bad blob is removed so the next ``setValue``
   replaces it with a fresh, schema-correct value.

2. **Wrong-type values.** A hand-edited INI file (or a previous
   schema) may have replaced a ``QSize`` with a string, a
   ``QByteArray`` with bytes, and so on. Calling ``size.width()`` on
   a ``str`` crashes startup uncaught. If ``expected_type`` is
   provided and the stored value is not an instance, fall back to
   ``default``. Do not remove the value: the user may have set it
   deliberately and we just do not know how to use it yet.

Returning the default rather than raising is the right shape for
startup-path code: a user with a stale or corrupt settings file
should still be able to launch the app.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar, cast, overload

T = TypeVar("T")
U = TypeVar("U")


class SettingsKey(StrEnum):
    """Canonical registry of every QSettings key the app reads or
    writes.

    Defining each key once eliminates the typo class of bug where a
    write to ``"pallete_mode"`` (typo) silently creates an orphan
    key that no read path ever matches. The values are the existing
    literal strings, so an upgrade is a non-event for existing user
    settings files: the round-trip is byte-identical.

    Use with :py:func:`safe_read_setting` and :py:func:`write_setting`
    so every QSettings access goes through one of the two typed
    wrappers. Keep the enum and the helpers in this module so
    ``from phonology_features._settings import SettingsKey,
    write_setting, safe_read_setting`` is the single import every
    caller needs.
    """

    WINDOW_POS = "window_pos"
    WINDOW_SIZE = "window_size"
    HSPLIT_STATE = "hsplit_state"
    VSPLIT_STATE = "vsplit_state"
    THEME = "theme"
    PALETTE_MODE = "palette_mode"
    MODE = "mode"
    LAST_INVENTORY = "last_inventory"
    # MatchMode (strict / wildcard) for natural-class queries.
    # Persists the user's "Allow underspecified" toolbar toggle so
    # the choice survives a relaunch.
    MATCH_MODE = "match_mode"
    # VowelChartMode (monophthong / diphthong) -- which class of
    # vowel segments the chart's silhouette area renders. The
    # diphthong chip strip below the silhouette always renders the
    # inventory's diphthongs regardless of this setting; the value
    # only decides what fills the trapezoid.
    VOWEL_CHART_MODE = "vowel_chart_mode"


def write_setting(settings: Any, key: SettingsKey, value: Any) -> None:
    """Typed wrapper around ``QSettings.setValue`` that enforces a
    :py:class:`SettingsKey` member as the key.

    Catches the "stringly-typed key" class of bug at mypy time: a
    raw string literal that isn't a ``SettingsKey`` member fails
    type-checking. The value type is intentionally ``Any`` because
    QSettings stores arbitrary serialisable objects (``QSize``,
    ``QPoint``, ``QByteArray``, ``str``, ``int``, ...).
    """
    settings.setValue(str(key), value)


@overload
def safe_read_setting(
    settings: Any,
    key: str,
    default: T,
    expected_type: None = None,
) -> T: ...


@overload
def safe_read_setting(
    settings: Any,
    key: str,
    default: None,
    expected_type: type[U] | tuple[type[U], ...],
) -> U | None: ...


@overload
def safe_read_setting(
    settings: Any,
    key: str,
    default: T,
    expected_type: type[Any] | tuple[type[Any], ...],
) -> T: ...


def safe_read_setting(
    settings: Any,
    key: str,
    default: T,
    expected_type: type | tuple[type, ...] | None = None,
) -> T:
    """Read ``key`` from ``settings``, returning ``default`` if the
    stored value can't be deserialized or doesn't match
    ``expected_type``. See module docstring for the failure modes.
    """
    try:
        value = settings.value(key, default)
    except (SystemError, ModuleNotFoundError, TypeError):
        settings.remove(key)
        return default
    if expected_type is not None and not isinstance(value, expected_type):
        return default
    return cast(T, value)
