"""Process-wide logging configuration.

Logging is opt-in: callers (the ``__main__`` entry point, tests that
want diagnostics) call :func:`configure` once at startup. Library
modules use ``logging.getLogger(__name__)`` and emit at the
appropriate level; they never touch the root configuration. This
matches the Python stdlib convention: libraries provide loggers,
applications configure handlers.

Why structured logging matters here:

  - **User bug reports are unreproducible.** Without a log we have
    only "it crashed" or "save didn't work", with no timing, no
    error cause, no inventory size. A log line per observable
    boundary (load, save start, save finish, validation failure,
    theme toggle, engine swap) turns a blind incident into a
    traceable one.

  - **Background work is invisible.** The save worker runs on a
    daemon thread and reports completion via a signal. If it dies
    silently (we used to have an OSError-only catch, which produced
    the permanent-lockout bug) the user sees nothing. A log
    statement on every worker entry and exit makes that class of
    bug obvious on its first occurrence.

  - **Performance regressions are silent.** ``cProfile`` finds them
    when we go looking; a debug-level "inventory load took N ms"
    line makes them findable in field logs without re-running the
    profiler against a user's data.

What we deliberately do NOT log:

  - Inventory contents (segment names, feature values). Cardinality
    is fine (counts, feature names that triggered validation
    errors), but the full segment table is not interesting in logs
    and bloats them.

  - User-typed metadata names beyond what's already in error
    messages. The inventory name is acceptable; the entire metadata
    blob is not.

  - Raw file paths verbatim. We log ``basename(path)`` to keep logs
    portable across users' filesystems and avoid leaking sensitive
    directory structure when a log is shared in a bug report.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_CONFIGURED = False


def configure(
    *,
    console_level: int = logging.INFO,
    file_path: Path | None = None,
    file_level: int = logging.DEBUG,
) -> None:
    """Install a single console handler on the root logger, and
    optionally a file handler. Idempotent: repeated calls re-apply
    levels but do not stack handlers.

    The console handler writes to stderr so logs don't interfere
    with anything the GUI prints to stdout (currently nothing, but
    keeping the convention costs nothing).

    Environment overrides for diagnostics-without-rebuild:
      - ``PHONOLOGY_LOG_LEVEL`` (DEBUG / INFO / WARNING / ERROR):
        overrides ``console_level``.
      - ``PHONOLOGY_LOG_FILE``: path to a log file; debug-level.
        Overrides ``file_path``.
    """
    global _CONFIGURED
    env_level = os.environ.get("PHONOLOGY_LOG_LEVEL")
    if env_level:
        console_level = getattr(logging, env_level.upper(), console_level)
    env_file = os.environ.get("PHONOLOGY_LOG_FILE")
    if env_file:
        file_path = Path(env_file)

    root = logging.getLogger("phonology_features")
    root.setLevel(
        min(console_level, file_level if file_path else console_level)
    )

    # Wipe existing handlers so a repeat ``configure`` does not pile
    # up duplicates (for example test setup re-calling configure).
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(console)

    if file_path is not None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(
            logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        root.addHandler(file_handler)

    # Do not propagate to Python root. Our handlers are the only
    # consumers of the ``phonology_features.*`` namespace.
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """``logging.getLogger`` namespaced under ``phonology_features``.

    Use module's ``__name__`` for ``name`` so the log line says where
    each message came from (``phonology_shared.engine.inventory``
    etc.). The handler is shared across all modules via the root
    namespace logger.
    """
    if not name.startswith("phonology_features"):
        name = f"phonology_features.{name}"
    return logging.getLogger(name)
