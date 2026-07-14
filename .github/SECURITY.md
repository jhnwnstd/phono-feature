# Security policy

## Report a vulnerability

Report security issues through GitHub private vulnerability reporting:

<https://github.com/jhnwnstd/phono-feature/security/advisories/new>

Do not open a public issue for problems that affect user data, the build pipeline, or the deployed web app.

Include the commit tested, steps to reproduce, the affected target (desktop app, browser app, or both), and a minimal inventory JSON if one is needed to reproduce.

## Scope

Inventory files are untrusted input. The parser enforces size limits and structural validation before the engine reads them.

The browser app runs entirely client side through Pyodide. It has no server component; loaded JSON stays in the browser.

The launcher scripts (`RUN-Linux.sh`, `RUN-Mac.command`, `RUN-Windows.bat`) create a local virtual environment and install Python packages with `pip`. They are trust on first run; review them before running if needed.

## Safeguards

- Rendering escapes user controlled strings.
- Pyodide loads from a version pinned URL, with Subresource Integrity on the entry script.

The CSP is delivered as a `<meta>` tag because GitHub Pages cannot set HTTP headers. Directives that require headers, such as `frame-ancestors`, are not enforced.
