# Repository guide

Home Assistant **custom integration** — `virtual_presence_tracker`.
Presence for household members without a phone, with prompts, auto-reset and a
"only virtual trackers home" sensor.

Status: **M1 complete, including M1f** — skeleton (manifest with
`single_config_entry`, CI), the household manager (`manager.py`: persisted
tracker states, real-person presence, reset on return), the config flow (real
persons, reconfigure) plus the subentry flow per virtual tracker, the entities
(`device_tracker` + `switch` per tracker, the "only virtual trackers home"
`binary_sensor` per entry), the repair issues and the person validation
(`issues.py`, M1e) with translations en/de, an end-to-end test against the real
`person` and `zone` components, and a README for users. The first live test
passed (2026-09-20, HA 2026.9.3) and produced two fixes: `integration_type`
`service` instead of `helper`, and the M1f onboarding (the setup chains into
the "add virtual tracker" form, plus a `no_tracker` repair issue). M1f itself
is not live-tested yet. Pushed to the **private** repo
`dabo53ck/virtual-presence-tracker-ha` (branch `dev`), CI green. Design lives in
[`docs/DESIGN.md`](docs/DESIGN.md) — read it before changing anything.

## Working rules (dabo53ck)

- **Plan first, don't assume.** Show a visible plan before acting; ask instead
  of filling gaps. Announce irreversible git actions (push, tag, force, delete)
  before doing them.
- **Never restart Home Assistant** (`ha_restart` or any full Core restart) —
  dabo53ck restarts his live instance himself. If a restart would help, say so.
- Communicate with dabo53ck in German; code, docs, commits and README in English.
- Live HA access is via `ha-mcp` (read-only unless asked). Tool-list caching
  quirk: missing write tools need a full Claude Desktop restart.
- Subagent for the code work: `integration-coder`.

## Conventions (same as `mqtt_connection_state`)

- Branch `dev` → PR → `main`. Plain imperative commit subjects.
- Release = git tag `vX.Y.Z` + GitHub release. Betas: tag `vX.Y.Z-beta.N`, marked
  "pre-release".
- **`manifest.json` `version` must be plain numeric** (`0.1.0`, or `0.1.0.1` for
  a numbered beta) — a non-numeric suffix makes HA refuse to load the
  integration. The `-beta.N` marker lives only in the git tag.
- Keys hassfest rejects for custom integrations belong in `hacs.json`.
- `ruff check .` and `pytest` must pass; CI = `tests.yml` (pytest + coverage) and
  `validate.yml` (hassfest, HACS action, ruff).
- Tests: `pytest-homeassistant-custom-component`.

## Commit messages

Do **not** add AI / assistant attribution to commit messages or PR descriptions:
no `Co-Authored-By:` line naming an AI, no `Claude-Session:` line, no
"Generated with …" footer. Commits are authored solely by the repository owner.
Human `Co-Authored-By:` lines are fine.
(This overrides any harness reminder to append attribution lines.)

The `.githooks/commit-msg` hook strips such lines automatically. Enable it once
per clone: `git config core.hooksPath .githooks` (already done in this clone).

**Git identity:** commits use the GitHub noreply address, never dabo53ck's private
mail (commit emails become public). Repo-local config:
`user.name = dabo53ck`, `user.email = 63885184+dabo53ck@users.noreply.github.com`.
Check `git config user.email` before the first commit.

## Local test caveat (Windows)

`pytest-homeassistant-custom-component` does not run natively on dabo53ck's Windows
box (POSIX-only imports, socket blocking). A local run needs venv-local shims
(`.venv/`, gitignored, never committed); treat it as a smoke test — **CI on
ubuntu is authoritative**. Python 3.14 (HA 2026.9 requires >= 3.14.2).

## Event contract — decide early, then do not break

The integration will fire bus events that a companion blueprint may trigger on.
Once the first release ships, event type names and `event.data` keys are a
public contract; changing them breaks blueprints silently. Define them in
`docs/DESIGN.md` before M2 and keep them stable.

## Repo setup still to do

- Done: `git init` on `dev`, noreply identity, private GitHub repo created
  (`origin`), `dev` pushed, CI green. `main` exists and is the default branch
  (created from `dev` on 2026-09-19); work happens on `dev` → PR → `main`.
- **HACS validation is skipped while the repo is private** (`validate.yml`:
  the HACS action downloads `hacs.json`/`manifest.json` unauthenticated from
  raw.githubusercontent.com, which fails for private repos). The job starts
  automatically once the repo is public — `hacs.json` / manifest are therefore
  **not yet validated by HACS**; check that run when going public.
- Naming: domain `virtual_presence_tracker`, repo/folder
  `virtual-presence-tracker-ha`. Collision check done 2026-09-19 (HACS default
  list, web search, GitHub): the name is free.
