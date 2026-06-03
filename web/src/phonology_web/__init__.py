"""Pyodide-side Python bridge used by the web app.

Only one importable module today: ``api``. JS calls it through
``pyodide.pyimport("api")`` at runtime; the build pipeline copies
``api.py`` to the bundle root so the runtime arcname stays ``api``.
Source path lives here so the bridge is a normal workspace package
for lint, mypy, and pytest.
"""
