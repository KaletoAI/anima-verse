# Contributing

By submitting contributions to this project, you agree to license your work under the **[MIT
Non-Commercial License](LICENSE)**.

- You retain copyright to your contributions.
- Your contributions must also be non-commercial.
- Commercial use requires separate permission from the copyright holder.

The rest of this file is the practical part: how to run the thing, how to verify a change, and the
house rules a patch is reviewed against. [`CLAUDE.md`](CLAUDE.md) holds the same rules in the
longer form an AI coding agent gets; the [README](README.md) covers installation and the feature
catalog.

---

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
./fetch_models.sh            # u2net + the built-in embedding model

./start.sh --world demo      # backend on :8000, logs in logs/main.log
./start.sh --with-3d         # plus the 3D client on :5183
./start.sh --stop | --restart | --status
```

The first start of a world without users logs a random bootstrap admin password **once**:
`grep "BOOTSTRAP ADMIN" logs/main.log`.

Frontend work needs one `npm install` at the repository root (it is an npm workspace root covering
`frontend`, `client3d` and `packages/*`):

```bash
npm run dev:admin            # Vite on :5173
npm run build:admin          # → static/game_admin/ (the built assets are committed)
npm run dev:client3d         # 3D client on :5183
npm run lint -w frontend     # the only lint script; covers frontend/ and packages/*/src
```

The built bundle under `static/game_admin/` is checked in, so a frontend change is only finished
once it has been rebuilt and the rebuilt assets are part of the commit.

---

## Verifying a change

There is **no pytest suite and no `tests/` directory**. Checks are standalone scripts under
`scripts/`, and a change that touches behaviour is expected to come with one.

```bash
./.venv/bin/python scripts/smoke_scene_recipe.py    # run a check
ls scripts/smoke_*.py                               # the existing ones (200+)
```

Conventions for a new check:

- Name it `scripts/smoke_<topic>.py` (or `scripts/test_<topic>.py` for the older LLM-facing ones).
  `scripts/` is tracked despite the global `test_*.py` ignore; only `scripts/legacy/` stays out.
- Start with a module docstring that contains a `Usage:` line and — this is the point — **derives
  the expected numbers by hand from the specification**. `scripts/smoke_scene_recipe.py` is the
  model: its docstring does the geometry from `docs/schnittstellen-3d.md` § B5a and the script
  compares against that. A check that merely records what the code currently prints proves nothing.
- It must run **without the server**, without a world DB where possible, and must never open
  `worlds/*/world.db` or `task_queue.db` while a server is running (SQLite locks).
- Exit non-zero on failure and print one `PASS`/`FAIL` line per assertion.
- Anything that needs the animation clips must set `ANIMATION_CLIPS_DIR` (and `ANIMATION_RIG_FILE`)
  so it never touches the real library.
- An ad-hoc script that loads a world must call `paths.init(<absolute path>)` — without an argument
  every script writes into `worlds/demo`.
- 3D findings are argued **numerically**, never from a screenshot.

Documentation claims can be guarded the same way: `scripts/smoke_docs_readme.py`,
`smoke_docs_config_defaults.py`, `smoke_docs_llm_templates.py` and `smoke_docs_client3d_readme.py`
check that the docs still describe the code.

---

## House rules

**No `.env`, no environment configuration.** Configuration lives per world in
`worlds/<world>/config.json` (+ the gitignored `secrets.json`) and is edited through
`/admin/settings`, backed by the schema in `app/core/config_schema.py`. Do not introduce an `.env`
reader or a `getenv` switch for a product setting. The legacy exceptions are `queue_cli.py`
(`TASK_QUEUE_DB`) and the `docker/` setup; the two test-only variables are `ANIMATION_CLIPS_DIR`
and `ANIMATION_RIG_FILE`.

**A feature is backend + UI.** Never ship a capability whose only interface is a database edit. If
a setting exists, it has a field in the schema or an editor in the React app.

**World data is DB-only.** `world.db` is the single source of truth — no JSON mirrors, no backup
copies written alongside it.

**This repository stays SFW.** The demo world, templates, prompts, comments, examples and commit
messages are safe for work. Adult content is a user's own configuration and lives in separate
packages installed through the marketplace; none of it belongs here. Never use a real person's or a
private world's names in code, docstrings, CLI help or examples — `demo` is the only sample name.

**UI strings are English — and only some of them are translatable.** New or changed strings are
written in English at the source. Two surfaces have a translation layer and only those may add keys
to `shared/languages/<lang>.json`: React, via `t()` from `useI18n()` (`frontend/src/i18n/`), and
server strings put through `t(en, lang)` (`app/core/i18n.py`) — including the English strings a
route hands to the React clients for them to translate. The **Python-rendered admin pages**
(`/admin/settings`, `/admin/users`, `/admin/llm-stats`, `/admin/models`, `/admin/agent-loop`,
`/admin/templates`, `/logs/*`, `/dashboard`) and the **config schema**
(`app/core/config_schema.py`, rendered raw by `static/admin/settings.js`) are **English-only by
decision**: they have no `t()` layer, none is planned, and a translation key for one of their
strings is dead weight. `scripts/smoke_i18n_orphans.py` guards that — it fails on any key in
`de.json` without a live source. Localised *data* fields follow the `<field>_<lang>` convention
resolved by `localized(obj, field, lang)`. When you work on an admin page, translate the German
strings you find there along the way — there is no project-wide sweep.

**Code comments and docstrings are English.** Translate the German ones in a file you touch.

**Two clocks, two types.** `utc_now()` / `parse_iso()` give SYSTEM time as a `datetime` and are for
technical stamps only (persistence, ordering, cooldowns, the queue, logs). Everything the game world
sees runs on `game_time()`, which returns a `GameTime` on the world calendar. A naive
`datetime.now()`, `time.time()` or `fromisoformat()` in game logic is a bug —
`scripts/smoke_game_time_lint.py` enforces it.

**No backward-compat shims on a rename or refactor** — no fallback readers, no alias fields — unless
it was agreed first.

**No hardcoded character stats.** Stamina, stress and friends are data; keep the handling generic.

**Skills are packages.** A skill lives under `plugins/<name>/` with its `plugin.yaml`, code,
templates, config schema and template fragments. The core never names a skill: capabilities are
wired through hooks, intents, tool flags and `requires`/`conflicts`. The definition of done is the
deletion test — remove the folder, the feature is gone and nothing else breaks. See
[`docs/plugins.md`](docs/plugins.md) and [`docs/skill-core-api.md`](docs/skill-core-api.md).

**Prompts are templates.** All LLM prompts live under `shared/templates/llm/` and are rendered with
`StrictUndefined`. The chat prompt's split into a stable system part and a per-turn moment part is a
cache contract — see [`CHAT_PROMPTS.md`](CHAT_PROMPTS.md).

---

## Commits and pull requests

Commit subjects follow Conventional Commits with an optional scope, and the description says what
**changed in behaviour**, not which files moved:

```
feat(llm): cache lanes — LLM concurrency moves from the provider to the model
fix(security): default-deny authentication, scoped CORS
perf(ui): tiles load thumbnails instead of full-size renders
chore(frontend): remove dead UI code and orphaned i18n keys
docs: the chat prompt's two parts, and who may move how
feat!: remove the Telegram channel
```

Common types: `feat`, `fix`, `perf`, `refactor`, `chore`, `build`, `docs`; `!` marks a breaking
change. Scopes in use include `llm`, `chat`, `world`, `character`, `imagegen`, `queue`, `sim`,
`admin`, `ui`, `frontend`, `client3d`, `3d`, `data`, `security`.

Before opening a pull request:

1. Run the checks that cover the area you touched, and add one for the behaviour you changed.
2. Rebuild the frontend if you edited `frontend/` or `packages/`, and commit the bundle.
3. Run `npm run lint -w frontend` for TypeScript changes.
4. Update the documentation that describes what you changed — `docs/` for the technical reference,
   the README for anything a newcomer or operator sees.
5. Describe the user-visible effect in the PR body, and say how you verified it.

Design and plan documents live in `development_instructions/` (gitignored, so they are not part of a
patch); the technical reference in `docs/` is tracked and is the right place for anything a
contributor needs.
