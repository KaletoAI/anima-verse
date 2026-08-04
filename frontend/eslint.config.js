import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

// The `lint` script runs this config from the REPO ROOT (`cd .. && eslint
// --config frontend/eslint.config.js frontend packages/player-ui/src
// packages/scene-render/src`), because ESLint's base path is the config file's
// directory (or the cwd when --config is passed) and files outside it are
// silently ignored — a `files` glob cannot contain `..`. Running from the root
// is what makes the shared packages reachable: the player panels in
// packages/player-ui/src used to live under frontend/src and were linted, and
// the hook rules below are the reason that must stay true; scene-render is the
// shared geometry code both renderers depend on and belongs under the same
// rules. Therefore all globs here are root-relative.
export default tseslint.config(
  { ignores: ['**/dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      // The two classic hook rules, named explicitly. Since
      // eslint-plugin-react-hooks 7 its `recommended` also turns on the
      // fourteen React-Compiler rules (purity, immutability, set-state-in-
      // effect, …) — 207 further errors in this codebase at a stroke. Those
      // are worth adopting, but as their OWN piece of work, not as a side
      // effect of a security bump. Adding them here is one line each.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  },
)
