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
6. **Repairs / validation** (M1e, done): three repair issues. `tracker_not_
   assigned` — a tracker that no `person` follows, the most common pitfall of
   the approach. `real_person_has_virtual_tracker` — the **self-reset hazard**:
   a person that has one of *our* virtual trackers attached must not be a
   *real* person, because switching that tracker on would look like a real
   arrival and reset every tracker at once. `real_person_missing` — a
   configured real `person` whose entity is gone. The config flow (user +
   reconfigure) rejects a person that carries one of our trackers
   (`person_has_virtual_tracker`); the issue covers the case where the
   assignment happens afterwards. `no_tracker` (M1f) joins them: an entry
   without a single tracker does nothing at all, and that is exactly what a
   user who closed the chained setup form is left with.
7. **Onboarding** (M1f, done): creating the entry chains straight into the
   "add virtual tracker" form, so the first tracker is one dialog away instead
   of a button on a page the user never opened. Closing that form is allowed
   and leaves a valid entry; the `no_tracker` issue then names the path to the
   button.

## Event & service contract (M2a, frozen)

Everything in this section is a **public API**. Automations, scripts and
blueprints are written against it, and changing a name or a key breaks them
silently, so it only ever grows - names and keys are never renamed or removed.

### Per-tracker options (subentry data)

| Key | Type | Range | Default | Label |
|---|---|---|---|---|
| `ask_on_departure` | bool | - | `False` | Ask when the house becomes empty |
| `answer_timeout` | int, minutes | 1-120 | `10` | Time to answer |
| `prompt_delay` | int, seconds | 0-600 | `0` | Delay before asking |

A subentry from before M2a simply has none of the keys and uses the defaults,
so there is no migration. `NumberSelector` returns floats; the flow stores
`int`.

### Event entity (one per tracker)

`unique_id` = `<subentry_id>_prompt`, on the tracker's device
`(DOMAIN, subentry_id)`, `has_entity_name`, `translation_key` `prompt`.

`event_types`: `prompt_started`, `answered_yes`, `answered_no`, `expired`,
`cancelled`.

Event data, all values strings (times ISO-8601 in UTC) or `null`:

| Key | On | Value |
|---|---|---|
| `prompt_id` | every event | random ID, new for every prompt |
| `tracker` | every event | the tracker's name (the subentry title) |
| `expires_at` | `prompt_started` | when an unanswered prompt gives up |
| `answered_by` | `answered_yes`, `answered_no` | `person` entity ID or `null` |
| `reason` | `cancelled` | `person_home`, `switched_on`, `option_disabled` |

### Service

`virtual_presence_tracker.answer_prompt`, an **entity service** on the
integration's `switch` entities (target the switch or its device).

| Field | Required | Value |
|---|---|---|
| `answer` | yes | `yes` or `no` |
| `answered_by` | no | a `person` entity ID, passed on to the event |

Targeting a tracker without an open prompt raises a `ServiceValidationError`
with the translation key `no_open_prompt`.

### Switch state attributes

`since` (unchanged), plus `prompt_open` (bool) and `prompt_expires_at` (ISO
string or `null`).

### State machine

idle -> *scheduled* (only while `prompt_delay` > 0) -> **open** ->
answered_yes / answered_no / expired / cancelled -> idle.

- **Opens** when the number of real persons *known* to be home goes from >= 1
  to 0 because a known person left, the tracker is off, `ask_on_departure` is
  on and no prompt is open yet. Never at HA start, never out of
  `unknown`/`unavailable`, never while `real_home` is `None`. With
  `prompt_delay` > 0 the opening is delayed and **all** conditions are checked
  again when the delay is over; with delay `0` the prompt opens straight away,
  inside the state change that caused it.
- **`answer_prompt` yes** sets the tracker home and emits `answered_yes`,
  **no** emits `answered_no` and changes nothing, the **timeout** emits
  `expired` and changes nothing. In all three cases the house counts as empty
  unless the answer was yes.
- **Cancelled**: a real person comes home while a prompt is open
  (`person_home`, regardless of the tracker's reset option); the tracker is
  switched on by hand or by an automation while a prompt is scheduled or open
  (`switched_on`); the option is switched off while a prompt is open
  (`option_disabled`). Answering yes ends the prompt *before* it sets the
  tracker home, so it never also emits `cancelled`. The prompt of a removed
  tracker is dropped silently.

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
- **Devices**: **every device belongs to a tracker subentry; an entity of the
  config entry itself has no device** (M1g). The frontend shows a "Devices that
  do not belong to a sub-entry" heading on the entry row as soon as an entry
  with subentries owns a device outside of them (`ha-config-entry-row.ts`,
  `ownDevices`), and the household device — one device for a single sensor —
  was not worth that. Within a tracker, the device tracker still gets no device
  (`_attr_device_info: None`); the switch carries it.
  `BaseTrackerEntity` defaults to `EntityCategory.DIAGNOSTIC`
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
  | `binary_sensor.only_virtual_trackers_home` | `<entry_id>_only_virtual_home` | none |

  The tracker sets `_attr_name` and leaves `has_entity_name` off: it has no
  device, so its own name is the full name and the entity ID follows the title
  (`device_tracker.kid`). The switch and the sensor use `has_entity_name` with
  a `translation_key`. For the switch that means the device name plus the
  translated entity name ("Kid At home"); the sensor has no device, so the
  translated entity name is the whole name and the whole entity ID ("Only
  virtual trackers home", `binary_sensor.only_virtual_trackers_home` — checked
  against `_async_get_full_entity_name()`, which simply leaves the device part
  out). Renaming a tracker renames the entities and the device but never the
  entity IDs — Home Assistant only regenerates an entity ID when the user asks
  it to.
- **Legacy household device** (`migration.py`, M1g): an install from before
  M1g has the sensor attached to a household device, and its entity ID carries
  the device name as a prefix. `async_setup_entry` therefore removes that
  device once, before the platforms are forwarded — so that the sensor is added
  to a registry entry that is already device-less. The order inside the helper
  is the point: removing a device removes every entity of it that belongs to
  the same config entry and subentry (`EntityRegistry.async_device_modified()`
  reacts to the `remove` action), which would destroy the entity ID, the
  history and every automation naming it. The entities are therefore detached
  (`async_update_entity(device_id=None)`) first; entity ID, unique ID and
  options survive that untouched. The helper only ever looks at the device with
  the identifiers `{(DOMAIN, entry_id)}` *of this entry*, and it does nothing
  when the device is gone or carries a foreign entity, so it is a no-op on
  every later setup. It can be deleted once no pre-M1g install is left. Note
  that the platform alone would already detach the entity — `entity_platform`
  passes `device_id=None` into `async_get_or_create()` when an entity provides
  no `device_info` — but it would leave the empty device behind.
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
- **`integration_type` is `service`, not `helper`** (corrected after the first
  live test, 2026-09-20). A helper is listed on the *Helpers* page, which has no
  way to add a config subentry, so the user could set the integration up but
  never add a virtual tracker. The Integrations page is where the "Add virtual
  tracker" button (`config_subentries.tracker.initiate_flow.user`) lives, and it
  lists `device` / `hub` / `service`. Core integrations with subentries
  (ollama, anthropic, openai_conversation, telegram_bot) are all `service`.
  Guarded by `tests/test_manifest.py`.
- **Subentries**: entities are added per subentry with `config_subentry_id`, so
  removing a subentry removes its entities; entity unique IDs are built from
  `subentry_id` (stable across renames), never from the name.
- **Repair issues** (`issues.py`, M1e): the checks run from
  `async_at_started()`. At startup the `person` states do not exist yet, so
  checking any earlier would report every tracker as unassigned and every real
  person as gone. Afterwards a domain-filtered listener
  (`async_track_state_change_filtered` on `person`) re-checks whenever a person
  appears, disappears or changes its `device_trackers`; a person that only
  comes or goes is ignored, and persons change state a lot. Issue IDs are
  `<entry_id>_<translation_key>[_<subentry_id|person|tracker>]`, so all issues
  of an entry can be found by prefix: the check deletes every issue of the
  entry it did not just raise, which covers a fixed cause, a removed tracker
  subentry (the entry reloads) and the unload. All issues are non-fixable
  warnings with `is_persistent=False`, so there is no `repairs.py` — a fix flow
  could only repeat what the description already says. Our own trackers are
  recognised through the entity registry (platform `DOMAIN`, domain
  `device_tracker`, entities of this entry), which is also what the config flow
  checks a selected person against.
- **Chained subentry flow** (M1f): `ConfigFlow.async_on_create_entry()` exists
  for "creating next flow entries to the result which needs a config entry
  created before it can start" — it runs after the entry was added *and* set
  up, so `result["result"].entry_id` is usable. The flow is started with
  `config_entries.subentries.async_init((entry_id, SUBENTRY_TYPE_TRACKER),
  context=SubentryFlowContext(source=SOURCE_USER))` and handed on as
  `result["next_flow"] = (FlowType.CONFIG_SUBENTRIES_FLOW, flow_id)`.
  `async_create_entry(next_flow=…)` cannot do it: `_async_set_next_flow_if_
  valid()` accepts only `FlowType.CONFIG_FLOW` and points at this hook. The
  frontend handles `config_subentries_flow` in `dialog-data-entry-flow.ts`
  (it skips the device-rename dialog and opens the subentry dialog). Core does
  the same in `ntfy`, `scrape` and `bayesian`. A form the user closes just
  drops the flow; nothing is left behind, and the entry stays loaded and valid.
- **Issue severity**: `IssueSeverity` has `CRITICAL`, `ERROR` and `WARNING` and
  no informational level, so even a pure hint like `no_tracker` is a
  `WARNING` — the alternative would be no repair issue at all.
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
| **M1f** (done) | Onboarding (requested after the first live test, 2026-09-20): after the entry is created the config flow chains straight into the "add virtual tracker" subentry flow (`async_on_create_entry` + `FlowType.CONFIG_SUBENTRIES_FLOW`, which the frontend supports); a repair issue while no tracker exists. |
| **M1g** (done) | The household sensor loses its device (2026-09-20), so the entry row no longer shows "Devices that do not belong to a sub-entry"; one-off clean-up of the device of older installs. |
| **M2a** | Prompt state machine per tracker (idle → pending → answered / expired / cancelled, persisted across restarts), a per-tracker `event` entity, an `answer_prompt` service and the per-tracker options (ask on departure, answer timeout, delay). **No push yet** — testable with services and events. |
| **M2b** | Built-in delivery: actionable `mobile_app` notification, per-tracker choice of *which real persons are asked*, person → phone mapping (derived from `mobile_app` entries, overridable), options flow. |
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

- **First live test passed (2026-09-20, HA 2026.9.3)**: tracker `not_home` →
  switch on → tracker `home` (`in_zones` = home zone + its enclosing zone),
  `person` `home` with the tracker as source, `zone.home` 2 → 3 with the virtual
  person listed, sensor stays `off` while real persons are home and lists the
  tracker in `virtual_trackers_home`, no repair issues, no log errors. Found
  and fixed: `integration_type` `helper` → `service` (see Technical notes).
  Not yet verified live: persistence across an HA restart (switch was left on
  for it), the reset on a real arrival, the repair issues.
- **M1f requested**: chain into the subentry flow right after setup, plus a
  hint while no tracker exists.

- **M2 decisions (dabo53ck, 2026-09-20, "grundsätzlich ok")**:
  - The prompt is an **option per tracker**, **off by default** — a tracker
    without it behaves exactly as before.
  - **Recipients are chosen per tracker among the real persons**
    (`notify_persons`), person-based with an automatic person → phone mapping
    (`mobile_app` config entries carry the `user_id` of the person's user;
    overridable). A recipient is not the same as a *real person*: king53ck keeps
    counting for "the house is empty" even when she is not asked. For the tests
    only dabo53ck is asked.
  - **First answer wins** when several persons are asked; the others' messages
    are replaced/cleared.
  - Events are exposed as **one `event` entity per tracker** (shows up as a
    trigger in the automation editor) instead of bus events.
  - Defaults: answer timeout **10 min**, prompt delay **0 s**; no answer, "no"
    or a returning person changes nothing (the house counts as empty).
  - Known consequence: an "everyone away" automation with a short `for:` (his
    "Präsenz zu Hause" waits 1 min) can fire before the answer arrives.
  - Caveat: buttons in a notification only work through the classic
    `notify.mobile_app_*` services (the notify *entities* of the companion app
    carry only title and message); HA may retire the classic services one day.

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
