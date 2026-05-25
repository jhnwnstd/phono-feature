# Security policy

## Report a vulnerability

Report security issues through GitHub private vulnerability reporting:

<https://github.com/jhnwnstd/features/security/advisories/new>

Do not open a public issue for problems that affect user data, the build pipeline, or the deployed web app.

Include:

- The commit or release tested.
- Steps to reproduce.
- A minimal inventory JSON if relevant.
- The affected target: desktop app, browser app, or both.
- The expected and actual behavior.

## Scope

Inventory files are untrusted input. The parser validates them before the engine uses them.

The browser app runs client side through Pyodide. It has no server component. Uploaded JSON stays in the browser.

The desktop launchers create a local virtual environment and install Python packages with `pip`.

## Current safeguards

- Inventory parsing uses size limits and structural validation.
- Browser rendering escapes user controlled strings.
- The browser app uses a Content Security Policy.
- Pyodide loads from a pinned URL with Subresource Integrity.
- JavaScript bridge calls clean up Pyodide proxy objects after use.
- The web deploy runs a browser smoke test before publishing.
- Desktop inventory saves use atomic file replacement.

## Limits

The Content Security Policy is delivered as a `<meta>` tag. Some directives, including `frame-ancestors`, require HTTP headers and cannot be enforced this way.

The launcher scripts are trust on first run. Review them before running if needed.

The inventory editor is a local editing tool. A user who can edit your inventory files can change their contents.