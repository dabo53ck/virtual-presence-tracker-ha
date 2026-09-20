# Repository guide

Home Assistant **custom integration** — `virtual_presence_tracker`.
Presence for household members without a phone, with prompts, auto-reset and a
"only virtual trackers home" sensor.

Status: **M1 complete (incl. M1f and M1g), M2a, M2b, M2c and M2d complete** — skeleton
(manifest with `single_config_entry`, CI), the household manager (`manager.py`:
persisted tracker states, real-person presence, reset on return, prompt state
machine), the config flow (real persons, reconfigure) plus the subentry flow
per virtual tracker (name, reset, prompt options, recipients), the entities
(`device_tracker` + `switch` + prompt `event` per tracker, the "only virtual
trackers home" `binary_sensor` per entry), the `answer_prompt` entity service
on the switches, the built-in delivery of the prompt to the Companion App
(`delivery.py` + `messages.py`, M2b: actionable notification per recipient,
answers from the buttons, clearing on every ending, optional expiry notice;
M2c: the integration's brand icon as the picture of the message;
M2d: the `open_prompt` entity service, which opens a prompt on demand —
ignoring the real persons, the `ask_on_departure` option and the delay — so the
chain can be tried out without leaving the house, with the `manual` flag that
keeps such a prompt alive across a restart),
the repair issues and the person validation (`issues.py`, M1e) with
translations en/de, an end-to-end test against the real `person` and `zone`
components, and a README for users. The first live test passed (2026-09-20, HA
2026.9.3) and produced two fixes: `integration_type` `service` instead of
`helper`, and the M1f onboarding (the setup chains into the "add virtual
tracker" form, plus a `no_tracker` repair issue). M1g followed: the household
sensor has no device any more (rule: every device belongs to a subentry,
entry-level entities are device-less), with a one-off clean-up of the device of
older installs in `migration.py`. M2b was live-tested on 2026-09-20 (HA
2026.9.3, iPhone): the push arrives, its buttons answer the prompt and
`answered_by` follows the phone's user. M1f, M1g, M2c and M2d are not
live-tested yet. Pushed to the **private** repo
`dabo53ck/virtual-presence-tracker-ha` (branch `dev`), CI green. Design lives in
[`docs/DESIGN.md`](docs/DESIGN.md) — read it before changing anything; its
"Event & service contract" section is frozen public API.

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

The integration publishes prompt events through one `event` entity per tracker,
which a companion blueprint may trigger on. Event type names and event data
keys are a public contract; changing them breaks blueprints silently. They are
written down in `docs/DESIGN.md` → "Event & service contract" (frozen with
M2a), together with the `answer_prompt` action and the switch attributes. The
contract may grow; nothing in it is ever renamed or removed.

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
