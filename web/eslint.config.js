// ESLint flat config for the web frontend.
//
// Scope: only the hand-authored sources at the repo root of web/
// (``main.js`` + ``sw.js``). The build output (``dist/``) and any
// vendored or generated artifacts are ignored.
//
// Rule set is ``eslint:recommended`` plus a small project-tuned
// adjustment for unused function arguments: the codebase uses
// ``_``-prefixed names for intentionally-unused parameters
// (callback signatures, header-only Qt-bridge stubs) so the rule
// allows that pattern instead of forcing an underscore-everywhere
// rename.

import js from "@eslint/js"
import globals from "globals"

export default [
  {
    ignores: ["dist/**", "node_modules/**", "scripts/**", "src/**"],
  },
  {
    files: ["main.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        ...globals.browser,
        // Injected by the Pyodide CDN script tag in index.html; the
        // global is the entry point for the WASM-backed Python
        // runtime the bridge mounts at boot.
        loadPyodide: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      "no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    files: ["sw.js"],
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "script",
      globals: {
        ...globals.serviceworker,
        // Stamped in by web/scripts/build.py at bundle-build time
        // (the source carries the literal token; the dist copy has
        // the real precache list).
        __PRECACHE_LIST__: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      "no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
]
