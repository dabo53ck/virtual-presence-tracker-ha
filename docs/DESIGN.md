# Design — virtual_presence_tracker

Tagline: *Presence for household members without a phone, with prompts,
auto-reset and a "only virtual trackers home" sensor.*

## Problem

A person without a phone (child, grandparent, carer, guest…) has no tracker.
When everyone with a tracker leaves the `home` zone, `zone.home` is 0 and every
"nobody home" routine fires (lights off, vacuum starts, heating setback…)
although someone is at home.

## Core idea

The user creates **any number of named virtual trackers**. Each one is a
**`device_tracker`** (`BaseScannerEntity`, connected → `home` / not_home) that the user attaches to
a `person` without an HA user. Then `zone.home` counts that person, and
**existing automations keep working unchanged**. Each tracker is driven by a
`switch` ("<name> is home") that can be toggled from a dashboard, NFC tag,
button or automation.

Not child-specific: the tracker has a free-form name and no built-in role.

Prior art: [`twrecked/hass-virtual`](https://github.com/twrecked/hass-virtual)
offers generic virtual trackers (no household logic). Our value is the logic
around it: prompt, auto-reset, the "only virtual trackers home" sensor.
Known pitfall from hass-virtual issue #82: a persistent tracker that restores
late makes the `person` briefly `unknown` after an HA restart → the tracker must
restore its last state immediately; cover with a test in M1.

## Structure

- **One config entry** (manifest `single_config_entry: true`): the *real*
  persons (`person` multi-select) whose presence decides "someone real is home",
  notification options, global defaults. Only one household per HA instance;
  relaxing this later is easy, tightening it would not be.
- **Config subentry per virtual tracker** (config subentries): free-form
  name, per-tracker options (ask on last departure, reset on return, max
  duration). Any number of trackers.
- Per tracker: `switch` + `device_tracker` (`BaseScannerEntity`, mirrors the
  switch). Both are thin views of a manager-owned state that is persisted in a
  `Store` and loaded *before* the platforms are set up (see technical notes).
- Per config entry: `binary_sensor` "Only virtual trackers home" = at least one
  virtual tracker home AND no real person home.
- Event-driven, no polling: a manager in `runtime_data` subscribes to person
  states, runs timers via `async_call_later`, handles notification actions
  (`mobile_app_notification_action`) if built-in notifications are chosen.

## Behaviour

1. **Prompt**: last real person leaves and a tracker's switch is off → after a
   configurable delay, prompt "Is <name> home?" [Yes] / [No]. Per-tracker
   opt-out (e.g. a guest tracker you set manually).
2. **Answer / no answer**: "Yes" → switch on. "No" or no answer within the
   timeout → **nothing changes** (house counts as empty). Consequence: the
   prompt delay must be shorter than the delays of the user's existing away
   routines, otherwise they fire before the answer arrives.
3. **Reset**: when the number of real persons at home goes from **0 to ≥ 1**
   → switch off (default on, per-tracker option), so the next departure asks
   again and nothing stays stuck for days. Not on every arrival: if dabo53ck is
   home and king53ck leaves and returns, a tracker that is on must stay on.
   `unknown` / `unavailable` / a missing entity mean "state not known": the last
   known value of that person is kept, and a person whose state was never known
   cannot trigger a reset (HA start).
4. **Safety net**: max duration → notify.
5. **Events** with a fixed contract (names TBD before M2), e.g. prompt sent,
   only-virtual-home.
6. **Repairs / validation** (M1e): issue if a tracker is not assigned to any
   `person` (the most common pitfall of the approach); issue if a configured
   real `person` is gone; **self-reset hazard**: a person that has one of *our*
   virtual trackers attached must not be a *real* person — switching the tracker
   on would look like a real arrival and reset every tracker at once. The config
   flow (user + reconfigure) rejects such persons, and a repair covers the case
   where the assignment happens afterwards.

## Technical notes (checked against HA 2026.9.3 sources, 2026-09-19)

- **Base class**: `ScannerEntity` is MAC-based (`unique_id` = MAC, `device_info`
  final `None`) and unsuitable. `BaseScannerEntity` "does not make assumptions
  about MAC addresses": only `is_connected` is required; `state` is `home` when
  connected (associated zone defaults to `zone.home`, user-configurable via
  entity options), `not_home` otherwise, `None` when `is_connected` is `None`.
  `source_type` must be set; `SourceType` has no "virtual" member
  (GPS / ROUTER / BLUETOOTH / BLUETOOTH_LE) → `ROUTER` is the closest.
  `state_attributes` is `@final` there: extra attributes of a tracker would
  have to go through `extra_state_attributes`.
- **Devices**: tracker entities never get a device (`_attr_device_info: None`);
  the switch may. `BaseTrackerEntity` defaults to `EntityCategory.DIAGNOSTIC`
  — **overridden to `None`** (M1c): the tracker is the entity the user assigns
  to a person, picks in the person dialog and puts on a dashboard, and it has
  no device to be a diagnostic part of. A category would only keep it out of
  default dashboards and of the default exposure to voice assistants
  (`_is_default_exposed` skips every entity with a category). Core's own
  trackers keep the diagnostic default, so this is a deliberate deviation.
- **Entities per config entry** (M1c). Names are only used for display, never
  for identity — unique IDs are built from the subentry or entry ID.
  | Entity | Unique ID | Device |
  |---|---|---|
  | `device_tracker.<title>` | `<subentry_id>_tracker` | none |
  | `switch.<title>_at_home` | `<subentry_id>_at_home` | one per tracker, `(DOMAIN, subentry_id)`, named after the tracker |
  | `binary_sensor.virtual_presence_tracker_only_virtual_trackers_home` | `<entry_id>_only_virtual_home` | household, `(DOMAIN, entry_id)` |

  The tracker sets `_attr_name` and leaves `has_entity_name` off: it has no
  device, so its own name is the full name and the entity ID follows the title
  (`device_tracker.kid`). The switch and the sensor use `has_entity_name` with
  a `translation_key`, so their name is the device name plus the translated
  entity name ("Kid At home"). Renaming a tracker renames the entities and the
  device but never the entity IDs — Home Assistant only regenerates an entity
  ID when the user asks it to.
- **No `via_device`** between the tracker devices and the household device:
  `DeviceInfo.via_device` is deprecated in 2026.9 (removed in 2027.8) in favour
  of `via_device_id`, which needs the target device to exist before the
  platforms are forwarded. Not worth the coupling for a cosmetic link.
- **Icons**: the switch and the sensor have `translation_key`s and entries in
  `icons.json`. The tracker deliberately has neither, so it falls back to the
  `device_tracker` component icons (`mdi:account` / `mdi:account-arrow-right`),
  which are exactly right for a person.
- **Platform order**: platforms are forwarded after `async_load()` /
  `async_start()` and unloaded before `async_stop()`, so entities never read an
  unloaded manager and the store is flushed last.
- **person**: connected scanner trackers with a non-empty `in_zones` attribute
  take precedence over every other tracker of that person, so a connected
  virtual tracker reliably makes the `person` `home`. Precisely: `person`
  prefers a tracker whose capability attribute `tracking_type` is `connection`
  *and* whose `in_zones` is non-empty, then a legacy `home`, then GPS, then the
  rest. `BaseScannerEntity` sets `tracking_type` to `connection` and reports
  `in_zones == ["zone.home"]` while connected and `[]` while not, so a switched
  on tracker wins and a switched off one does not veto a GPS tracker.
- **zone**: a zone counts a `person` when the person's own `in_zones` attribute
  contains the zone's entity ID (`zone.home` counts nothing else — no distance
  maths for persons). The person copies `in_zones` from the tracker it follows.
  Both behaviours are covered end to end against the real components in
  `tests/test_end_to_end.py` (M1d), including the reset chain.
- **Persistence**: manager-owned `Store` (key `virtual_presence_tracker.
  <entry_id>`, version 1), loaded before platform setup, so the first state
  written after a restart is already correct (avoids the `person` → `unknown`
  blip reported for hass-virtual, issue #82). States of subentries that no
  longer exist are pruned on load.
- **Subentries**: entities are added per subentry with `config_subentry_id`, so
  removing a subentry removes its entities; entity unique IDs are built from
  `subentry_id` (stable across renames), never from the name.
- **Reload on change**: Home Assistant notifies update listeners when the entry
  data or a subentry changes, but it never reloads the entry by itself — and
  adding or removing a subentry has no flow result that could reload it. The
  entry therefore registers an update listener that reloads. As a consequence
  both reconfigure flows must finish with `async_update_and_abort()`:
  `ConfigSubentryFlow.async_update_reload_and_abort()` raises while an update
  listener exists, and the `ConfigFlow` variant reports a deprecation that
  breaks in HA 2026.12.

## Milestones

| Stage | Content |
|---|---|
| **M1** | Scaffolding, config flow + subentry (name, options), `switch` + `device_tracker` + `binary_sensor`, reset on real-person return, restore-state test, tests + CI. Live-testable: switch on → `zone.home` counts up. |
| **M2** | Prompt with timeout, options flow (delivery per decision below). |
| **M3** | Evidence sources (BLE tag, tablet Wi-Fi, door contact) that auto-set "home"; max-duration alert, services, repairs, diagnostics, translations en/de. |
| **M4** | README, brand, beta releases via `dev`, HACS default submission. |

## Decisions

Confirmed by dabo53ck (2026-09-19):

- **No answer to the prompt → house counts as empty** (no state change).
- **Reset on real-person return: default on.**
- **Virtual tracker appears as a `person`** in dashboards; "person arrives home"
  automations also fire for it. Accepted.
- **Generic, not child-specific**: multiple trackers, each with its own name.
- **Single config entry** per HA instance; all trackers are subentries of it.
- **Repo tooling**: `commit-msg` hook (strips AI attribution) in `.githooks/`,
  `ruff format --check` in CI. Work starts with a **private** GitHub repo and a
  green CI before the real config flow / entities are built (local pytest is
  only a smoke test on Windows, hassfest/HACS only run in CI).
- **HA version**: live instance runs 2026.9.3. The design needs
  `BaseScannerEntity` (core PR #171063, commit `a9475683e`, 2026-05-20) and its
  `in_zones` attribute (PR #171832, commit `6de03f4ed`, 2026-05-25). Verified
  2026-09-19 against the core repository: `gh api
  repos/home-assistant/core/compare/<tag>...<sha>` reports both commits as
  contained in `2026.6.0b0` and `2026.6.0` (`status: behind`) and in no
  `2026.5.x` tag (`status: diverged`, checked against `2026.5.0` and the last
  patch `2026.5.4`); `BaseScannerEntity` is absent from the `device_tracker`
  sources at tag `2026.5.4` and present at `2026.6.0`. `hacs.json` floor is
  therefore **2026.6.0** (the skeleton's `2025.3.0` was a placeholder).

- **HA floor 2026.6.0 accepted** (needs `BaseScannerEntity`); older HA versions
  cannot install the integration.
- **`binary_sensor` "only virtual trackers home" reports `unknown` while
  `manager.real_home is None`** (no real-person state known yet, e.g. right
  after HA start). The config flow requires at least one real person, so an
  entry without persons cannot exist from M1b on.
- **Manager save delay 5 s** (flushed on unload/shutdown) is fine.
- Known gap (M3 repair): a configured real person whose entity is deleted keeps
  its last known value until the next restart.
- **Repair "tracker not assigned to any person" is part of M1** (step M1e, last),
  not M3: without the person assignment nothing visible happens in a live test.
- **Live-test path: SSH** — start the *Advanced SSH & Web Terminal* add-on
  (currently stopped, update available; starting it and the SSH credentials need
  dabo53ck's OK) and `scp` `custom_components/virtual_presence_tracker/` to
  `/config/custom_components/`. Every new code state needs an HA restart **by
  dabo53ck**, so live tests only at checkpoints (after M1c/M1d), not per stage.
  Installed add-ons: File editor, Advanced SSH (both stopped), no Samba/VS Code.

Live instance facts: persons `person.dabo53ck`, `person.king53ck` (both currently home).

- **Prompt delivery = hybrid ("variant C")**: the integration owns the state
  machine (prompt pending, timeout, reset), fires events (prompt started /
  expired) and offers services (`confirm` / `deny`). On top it offers an
  *optional* built-in `mobile_app` actionable notification as a convenience.
  Other channels (Telegram, TTS, …) listen to the events and call the services;
  a companion blueprint can be a thin layer on that later. Pending state and
  timers must survive an HA restart. Event names / payload keys are still to be
  fixed before M2 (public contract, see CLAUDE.md).

Still open: nothing blocking M1.
