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
   ``QByteArray`` with bytes, etc. Calling ``size.width()`` on a str
   crashes startup uncaught. If ``expected_type`` is provided and the
   stored value isn't an instance, fall back to ``default`` (do NOT
   remove -- the user may have set it deliberately and we just don't
   know how to use it yet).

Returning the default rather than raising is the right shape for
startup-path code: a user with a stale or corrupt settings file
should still be able to launch the app.
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


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
    return value
