"""Frontend-agnostic application layer.

Owns the orchestration state and use-case transitions both the desktop
and web frontends share, so each client renders one state machine
instead of re-implementing the load / select / mode bookkeeping. Pure
shared Python (no Qt, no DOM); the frontends adapt it to widgets or the
DOM and serialise it at the bridge boundary.
"""

from phonology_shared.application.session_state import SessionState

__all__ = ["SessionState"]
