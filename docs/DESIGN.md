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
  name, the recipients of its prompt and its options (ask on last departure,
  reset on return, the two timings, the expiry notice). Any number of trackers.
  The options are set through entities of the tracker, not through the form.
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
5. **Events** with a fixed contract, one `event` entity per tracker — settled
   in "Event & service contract" above (M2a).
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
8. **The person of a new tracker** (M2g, done): the form of a *new* tracker
   offers to create the `person` the tracker needs, ticked by default, which
   takes the one manual step out of the setup that nothing else can do for the
   user. Only for new trackers, only once, never a duplicate of a person that
   is already there, and never removed again when the tracker is deleted -
   a person is the user's data. `tracker_not_assigned` stays as the fallback
   for everybody who unticks the box or whose person could not be created.

## Event & service contract (M2a, frozen; grown in M2b, M2d and M2f)

Everything in this section is a **public API**. Automations, scripts and
blueprints are written against it, and changing a name or a key breaks them
silently, so it only ever grows - names and keys are never renamed or removed.

### Per-tracker options (subentry data)

| Key | Type | Range | Default of a missing key | Label |
|---|---|---|---|---|
| `reset_on_return` | bool | - | `True` | Reset when someone comes home |
| `ask_on_departure` | bool | - | `False` | Ask when the house empties |
| `answer_timeout` | int, minutes | 1-120 | `10` | Time to answer |
| `prompt_delay` | int, seconds | 0-600 | `0` | Delay before asking |
| `notify_persons` (M2b) | list of `person` entity IDs | the entry's real persons | `[]` | Who is asked? |
| `notify_on_expiry` (M2b) | bool | - | `False` | Tell me when nobody answers |

The **keys are unchanged since M2b**; what changed with M2f is who writes them.
The first five have an entity each (below) and are written from the tracker's
device page **without reloading the config entry**; `notify_persons` stays in
the form, because it is a list of persons rather than a value.

A subentry may additionally carry `create_person: True` (M2g) for the short
while between the form and the start. That key is a **marker, not an option**
and deliberately no part of this contract: it is written by the form of a new
tracker, acted on once, and taken off again (see the technical notes).

A subentry from before M2a or M2b simply has none of the keys and uses the
defaults, so there is no migration - and a missing `ask_on_departure` still
means "does not ask", which is what every tracker from before the prompt relies
on. A tracker **added from M2f on** is written with all five keys spelled out
and with **`ask_on_departure: True`**: a new tracker asks, an old one does not
start to.

The tracker form holds nothing but name and `notify_persons` (M2f).
`notify_persons` is an `EntitySelector` (domain `person`, `multiple`) whose
`include_entities` are the entry's configured real persons plus whatever the
tracker already has stored - a recipient that lost its real-person status can
therefore still be submitted and is rejected with the error `person_not_real`
instead of a voluptuous failure. The flow checks the same rule server-side. For
a **new** tracker every real person of the entry is pre-selected; the
**reconfigure** step merges (`{**subentry.data, notify_persons: ...}`), so the
five settings pass through the form untouched.

### Option entities (M2f, one set per tracker)

On the tracker's device `(DOMAIN, subentry_id)`, `has_entity_name`, with the
option key as the translation key and as the suffix of the unique ID.

| Entity | Platform | Key | Unique ID | Category |
|---|---|---|---|---|
| Ask when the house empties | `switch` | `ask_on_departure` | `<subentry_id>_ask_on_departure` | `CONFIG` |
| Reset when someone comes home | `switch` | `reset_on_return` | `<subentry_id>_reset_on_return` | `CONFIG` |
| Tell me when nobody answers | `switch` | `notify_on_expiry` | `<subentry_id>_notify_on_expiry` | `CONFIG` |
| Time to answer | `number` | `answer_timeout` | `<subentry_id>_answer_timeout` | `CONFIG` |
| Delay before asking | `number` | `prompt_delay` | `<subentry_id>_prompt_delay` | `CONFIG` |

**All** of them are configuration entities (the ask switch became one after
M2f, on dabo53ck's call): they are settings of the tracker and belong together
under "Configuration" on its device page, away from the everyday control, which
is the tracker's own switch. The category is a matter of where the frontend
puts an entity and of what a voice assistant is offered by default; writing one
is unaffected, so an automation or a script still flips the ask switch like any
other switch. The numbers are `NumberMode.BOX`, step 1,
`NumberDeviceClass.DURATION` with
`UnitOfTime.MINUTES` / `UnitOfTime.SECONDS` (both are in the unit set the
device class allows), and the ranges of the constants they have always had.

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

### Services

Both are **entity services** on the integration's `switch` entities (target the
switch or its device).

`virtual_presence_tracker.answer_prompt`:

| Field | Required | Value |
|---|---|---|
| `answer` | yes | `yes` or `no` |
| `answered_by` | no | a `person` entity ID, passed on to the event |

Targeting a tracker without an open prompt raises a `ServiceValidationError`
with the translation key `no_open_prompt`.

`virtual_presence_tracker.open_prompt` (M2d), **no fields**: opens the prompt of
the tracker right now, with the tracker's configured answer timeout - so the
prompt can be tried out or triggered by an automation without a real departure.
Everything after the opening is the usual prompt: the `prompt_started` event,
the switch attributes, the built-in delivery, the answers, the expiry, the
expiry notice and the cancellations (`switched_on` when the tracker is switched
on, `person_home` when a real person arrives while none was home).

It deliberately ignores whether real persons are home, the tracker's
`ask_on_departure` option - that option governs the *automatic* opening only -
and `prompt_delay`: "now" means now. A prompt that is still waiting for its
delay is taken over instead of duplicated: it opens at once with the **same
`prompt_id`**, and its timer is dropped, so the event stream stays one chain.

Two conditions are left, both checked before anything changes, so a refusal
leaves no trace: a tracker that is already on raises `tracker_already_home`, a
tracker that already has an open prompt raises `prompt_already_open` (both
`ServiceValidationError`).

### Built-in delivery through the Companion App (M2b)

Active for a tracker whenever a prompt of it opens and `notify_persons` is not
empty - for the automatic opening that means `ask_on_departure` has to be on,
for `open_prompt` (M2d) the option does not matter, because the prompt is open
either way. An empty selection means no built-in push at all: the integration
then behaves exactly as in M2a, so an automation of the user's own stays the
only delivery. Recipients are looked up at send time and never cached.

**Person -> phones**: the `user_id` state attribute of the `person` entity is
matched against the `user_id` of the `mobile_app` config entries; every
matching entry's `device_name` gives the classic service
`notify.<slugify("mobile_app_" + device_name)>`, and only services that exist
are used. A person can have several phones; all of them are asked.

**Payload** (classic `notify.mobile_app_*` service, because only it carries
`data.actions`):

| Key | Value |
|---|---|
| `title` | localized prompt title |
| `message` | localized prompt message |
| `data.tag` | `vpt_<prompt_id>` |
| `data.actions` | `[{action: VPT_YES_<prompt_id>, title: <Yes>}, {action: VPT_NO_<prompt_id>, title: <No>}]` |
| `data.ttl`, `data.priority` | `0` / `high` - Android: deliver now, even on an idle phone |
| `data.timeout` | the answer timeout in seconds - Android: drop the message when it is over |
| `data.push` | `{"interruption-level": "time-sensitive"}` - iOS |
| `data.icon_url` (M2c, M2e) | `/api/brands/integration/virtual_presence_tracker/icon@2x.png` - the integration's own icon *beside* the message, in place of the Companion App's own: on iOS the message becomes a communication notification whose sender avatar it is (and whose sender name is the title), on Android it is the large icon. No `data.image` is sent: an attachment would show the same picture a second time. |

The action IDs and the tag are internal, but they have to stay stable: the
answer of a phone that was offline for a while still names the prompt it
belongs to, and the tag is what clears a message written by a previous Home
Assistant run.

**Clearing**: `message: clear_notification` with `data.tag` of the prompt, sent
to every recipient phone on *every* ending of the prompt (`answered_yes`,
`answered_no`, `expired`, `cancelled`).

**Expiry notice**: only on `expired` and only with `notify_on_expiry`, after
the clearing, with the tag `vpt_info_<prompt_id>` and the same `data.icon_url`.
The clearing carries neither: it is not a message, it takes one away.

**Answers** arrive as the bus event `mobile_app_notification_action`. Only
`data.action` is trusted: `VPT_YES_<prompt_id>` / `VPT_NO_<prompt_id>` for a
prompt that is open right now answers it through the manager - the same code
path the `answer_prompt` action uses, so first answer wins and the other phones
are cleared. Everything else is ignored with a debug log. `answered_by` is
derived from `context.user_id` of the event (see technical notes), or `null`.

**Texts**: English and German, chosen by `hass.config.language`, English
otherwise (`messages.py`).

| Text | English | German |
|---|---|---|
| title | Is {tracker} home alone? | Ist {tracker} alleine zu Hause? |
| message | Nobody else is home. Answer within {minutes} minutes. | Es ist niemand sonst zu Hause. Antworte innerhalb von {minutes} Minuten. |
| yes | Yes, home alone | Ja, alleine zu Hause |
| no | No | Nein |
| expiry | No answer: {tracker} counts as not at home. | Keine Antwort: {tracker} gilt als nicht zu Hause. |

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
- **Opened by hand** (M2d, `open_prompt`): the same open state, reached without
  any of those conditions - only "the tracker is off" and "no prompt is open"
  still hold. Such a prompt is marked `manual` in the store and therefore
  survives the catch-up cancellations of a restart (see below); while it is
  open it ends exactly like any other prompt. The mark is internal: no event
  carries it, and nothing but the resume looks at it.
- **`answer_prompt` yes** sets the tracker home and emits `answered_yes`,
  **no** emits `answered_no` and changes nothing, the **timeout** emits
  `expired` and changes nothing. In all three cases the house counts as empty
  unless the answer was yes.
- **Cancelled**: a real person comes home while a prompt is open
  (`person_home`, regardless of the tracker's reset option); the tracker is
  switched on by hand or by an automation while a prompt is scheduled or open
  (`switched_on`); the ask option is switched off while a prompt is scheduled
  or open (`option_disabled`). Answering yes ends the prompt *before* it sets
  the tracker home, so it never also emits `cancelled`. The prompt of a removed
  tracker is dropped silently.
- **Switching the ask option off** (M2f) now happens *live*, through the
  switch, instead of through a form that reloaded the entry - so the
  cancellation is immediate and not a catch-up: the manager keeps the last
  value it saw per tracker and takes the question back the moment the value
  goes from on to off. A prompt that was **opened by hand** is left alone, for
  the same reason the resume leaves it alone: it was never opened because the
  option was on. `async_resume_prompts()` keeps its own checks unchanged, for
  the case where the option changed while Home Assistant was down.

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
  | the five option entities (M2f) | `<subentry_id>_<option key>` | the tracker's device |

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
- **Icons**: the switch, the sensor and the five option entities have
  `translation_key`s and entries in `icons.json`. The tracker deliberately has neither, so it falls back to the
  `device_tracker` component icons (`mdi:account` / `mdi:account-arrow-right`),
  which are exactly right for a person.
- **Platform order**: platforms are forwarded after `async_load()` /
  `async_start()` and unloaded before `async_stop()`, so entities never read an
  unloaded manager and the store is flushed last. **Resuming the prompts is a
  third step, after the platforms** (M2a): the catch-up can emit `expired` or
  `cancelled`, and an event entity that does not exist yet would swallow it.
  That the entities *do* exist by then is guaranteed by `EntityPlatform.
  _async_setup_platform()`, which blocks on the add-entity tasks ("Block till
  all entities are done") before `async_forward_entry_setups()` returns. Hence
  the split between `async_load()` (read the store) and
  `async_resume_prompts()` (act on it).
- **Prompt timers** are `async_call_later()` handles, one per open prompt
  (expiry) and one per delayed prompt. `async_stop()` cancels all of them, so a
  reload never leaves a timer of the old manager behind; the tests would fail
  on it, as pytest-homeassistant-custom-component reports lingering timers.
- **The prompt ID is drawn when the state machine leaves idle**, not when the
  prompt opens, so that a prompt cancelled during its delay can still be named
  in the `cancelled` event. The delay phase itself is *not* persisted (see the
  contract): it was never announced. Consequently a person coming home during
  the delay drops it silently, while an open prompt is cancelled out loud - and
  the re-check at the end of the delay is what catches the silent case.
- **Store version stays 1** although the payload grew a `prompts` key: an older
  store simply does not have it, which reads as "no prompt was open" - exactly
  what a fresh install looks like. There is nothing to convert, so
  `async_migrate_func` would have nothing to do. The `manual` flag of a prompt
  (M2d) is optional for the same reason: a prompt written without it reads as
  "nobody opened this by hand", which is what every prompt before M2d was.
- **Resuming a manual prompt** (M2d): `async_resume_prompts()` skips *both* of
  its cancellations for a prompt that was opened by hand. Neither reason
  applies to it - it was never opened because the option was on, and never
  because the house was empty - so taking it back at the next reload would
  silently undo what the user or an automation just asked for. The deadline is
  the one rule that still holds, expired-while-down included. A real person who
  comes home *while* the manual prompt is open still cancels it: that is the
  question being answered by events, not a catch-up.
- **The answer is an entity service on the `switch`** (`platform.async_register_
  entity_service()` from `switch.py`, as core does in `pi_hole`), not a domain
  service taking a tracker name: the switch is the entity the prompt is about,
  so targeting it targets the tracker, areas and devices work for free, and
  there is no second way to name a tracker. Registering is idempotent
  (`async_register_entity_service` returns early when the service exists), so a
  reload does not have to care. An answer without an open prompt is a
  `ServiceValidationError` with a translation key, not a silent no-op: an
  answer that arrives too late must not switch anything on.
- **`event` entity, not bus events**: an event entity shows up in the
  automation editor as a trigger, carries its data as state attributes and
  restores its last event over a restart. `_trigger_event()` only records the
  event - `async_write_ha_state()` right after it is what publishes it.
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
- **Notify service naming** (checked against the HA 2026.9.3 sources, M2b):
  `mobile_app` loads the legacy notify platform with
  `discovery.async_load_platform(hass, Platform.NOTIFY, DOMAIN, {}, config)`
  and no `name` in the discovery info, so `notify/legacy.py` uses the
  integration name as the prefix and registers one service per target as
  `slugify(f"{prefix}_{name}")` - with `MobileAppNotificationService.targets`
  returning `{device_name: webhook_id}` for every push-capable registration.
  The service of a phone is therefore `notify.<slugify("mobile_app_" +
  device_name)>`; "dabo53ck's Phone" becomes `notify.mobile_app_dabo53ck_s_phone`.
  Registrations without push support have no service at all, which is why
  `hass.services.has_service()` decides and not the entry alone.
- **Person -> phone**: `mobile_app` stores `user_id` in its config entry data
  (`const.CONF_USER_ID`), and the `person` entity exposes the same value as the
  state attribute `user_id` - only when the person has a user, which is exactly
  the condition for having a Companion App. Both are read at send time; caching
  would survive a re-registration of the app with a new `device_name`.
- **Who answered**: the Companion App fires `mobile_app_notification_action`
  through the `fire_event` webhook, and `webhook.py` gives that event the
  context of the registration (`helpers.registration_context()` =
  `Context(user_id=registration[CONF_USER_ID])`). `context.user_id` is
  therefore set by Home Assistant, not by the app, and the person with that
  user is `answered_by`. The event *data* is app-provided and carries the
  `action`, `reply_text`, iOS `action_data` and, on Android, the data of the
  notification (documented in `companion.home-assistant`,
  `docs/notifications/actionable.md`); nothing but `action` is trusted.
- **Delivery hints**: `ttl: 0` and `priority: high` are what the companion docs
  prescribe to reach an idle Android phone (`docs/notifications/critical.md`),
  `timeout` drops the message when the answer time is over
  (`docs/notifications/basic.md`), and `push.interruption-level:
  time-sensitive` is the iOS counterpart. The payload carries all of them at
  once: each platform ignores the keys of the other, and the integration would
  otherwise have to guess the platform from the registration.
- **The icon in the message** (M2c, re-checked against the app sources
  2026-09-20 for M2e): the icon is the brand icon Home Assistant already serves,
  `/api/brands/integration/virtual_presence_tracker/icon@2x.png`. That endpoint
  wants an authenticated request (`brands/__init__.py`,
  `_BrandsBaseView._authenticate`: `request[KEY_AUTHENTICATED]` or a rotating
  `?token=`), and **both Companion Apps authenticate a notification icon whose
  URL starts with a slash**, so no route of our own is needed - nothing of the
  `brand` folder is exposed beyond what Home Assistant exposes anyway. Evidence:
  iOS copies `data.icon_url` into the APNs payload and sets `mutable-content`
  (`Sources/SharedPush/Sources/NotificationParserLegacy.swift`,
  `NotificationPayloadKey.iconURL` in `notificationDecorationKeys`),
  `NotificationSenderParser` turns it into a sender with
  `needsAuth = urlString.hasPrefix("/")` (`Sources/Shared/Notifications/
  NotificationSender/NotificationSenderParser.swift`) and
  `NotificationCommunicationDecorator` downloads it through the session that
  carries the token. Android resolves the URL against the server
  (`UrlUtil.handle`) and calls `getImageBitmap(serverId, url,
  requiresAuth = !UrlUtil.isAbsoluteUrl(dataIcon))`, which adds
  `Authorization: Bearer ...`, in `handleLargeIcon`
  (`app/src/main/kotlin/io/homeassistant/companion/
  android/notifications/MessagingManager.kt`). The endpoint is unchanged between
  our floor (2026.6.0) and 2026.9.3, serves a custom integration's `brand`
  folder when `Integration.has_branding` is true (the folder is there) and only
  under the eight names of `ALLOWED_IMAGES`; `brands` is in
  `bootstrap.DEFAULT_INTEGRATIONS`, so it is always set up. An icon that cannot
  be loaded is the phone's business: nothing in the delivery depends on it and
  the message arrives either way.
- **Why `icon_url` and not `image`** (M2e): `data.image` is an *attachment* -
  iOS shows it as a thumbnail on the right of the message and as the picture of
  the expanded notification, which is not what "whose question is this" needs.
  `data.icon_url` reaches the spot the app's own icon sits in: on iOS the
  message becomes a *communication notification* (rounded avatar on the left,
  the title as the sender's name - `INSendMessageIntent`, the image downsampled
  to 256 px and capped at 5 MB), on Android it is `setLargeIcon`. The key works
  on both platforms and is documented for both
  (`docs/notifications/basic.md`, "Notification Icon" / "Notification icon and
  color"). Sending `image` as well would show the same picture twice (and on
  Android the `image` would hide the icon again - the docs say so explicitly),
  so the prompt and the expiry notice carry `icon_url` only. The iOS side is
  young: PR #4672 (merged 2026-07-17) added it, PR #5188 (2026-07-20) made it
  work without a title, and the first release that contains either is **iOS
  Companion 2026.8.0** (`release/2026.7.3` does not have it yet). Our messages
  always have a title, so the avatar is named after the prompt title. An older
  app simply ignores the key.
- **No `mobile_app` dependency in the manifest**: nothing of it is imported -
  the domain, the entry keys and the event name are spelled out, as the
  `person` domain already was - and the integration is fully usable without a
  Companion App. A `dependencies` entry would force `mobile_app` to be set up,
  an `after_dependencies` entry would only affect the *load order*, which the
  repair issue solves better: it is evaluated after the start and re-evaluated
  whenever a `notify` service appears or disappears (`EVENT_SERVICE_REGISTERED`
  / `EVENT_SERVICE_REMOVED`), so a phone that registers later clears it.
- **Sending happens in background tasks of the config entry**
  (`entry.async_create_background_task()`): a notify service can block for
  seconds, and the prompt state machine is a chain of `@callback`s that must
  not wait for a phone. The tasks are cancelled and awaited when the entry
  unloads; tests wait for them with
  `async_block_till_done(wait_background_tasks=True)`. Every call is wrapped in
  its own `try`, so one unreachable phone neither stops the other recipients
  nor touches the prompt.
- **Reload on change**: Home Assistant notifies update listeners when the entry
  data or a subentry changes, but it never reloads the entry by itself — and
  adding or removing a subentry has no flow result that could reload it. The
  entry therefore registers an update listener that reloads. As a consequence
  both reconfigure flows must finish with `async_update_and_abort()`:
  `ConfigSubentryFlow.async_update_reload_and_abort()` raises while an update
  listener exists, and the `ConfigFlow` variant reports a deprecation that
  breaks in HA 2026.12.
- **The reload fingerprint** (M2f): the update listener above reloaded on
  *every* change, which stopped being acceptable when the five options became
  entities. A reload unloads the platforms, and an entity that is removed and
  added again goes through `unavailable`: `device_tracker.kid` flickers,
  `person.kid` follows it, and an automation that waits for somebody to come
  home cannot tell that apart from an arrival. Flipping a switch must not do
  that. `async_setup_entry` therefore stores a fingerprint in the runtime data
  — the entry title, `entry.data`, and per subentry its title and all of its
  data **except** `LIVE_OPTION_KEYS` — and the listener compares it: equal means
  nothing but those options changed, so the manager is told
  (`async_options_changed()`), the repair issues are re-checked and the entry
  stays loaded; anything else reloads as before. The stored fingerprint never
  has to be refreshed on the live path: it ignores exactly the keys that may
  change without a reload, and a reload builds it again anyway.
- **Writing an option** (M2f): `hass.config_entries.async_update_subentry(entry,
  subentry, data={**subentry.data, key: value})`. It replaces the data
  wholesale, hence the copy; it returns `False` and notifies nobody when the
  value is the one that was there. The subentry data is updated *synchronously*,
  but the update listeners are started as tasks (`_async_save_and_notify()`), so
  `HouseholdManager.async_set_option()` calls `async_options_changed()` itself
  right after the write: the entity that was just used shows the new value
  before the service call returns, instead of after the next tick. The listener
  path then runs the same method a second time and finds everything done —
  which is what makes a change that arrives any other way work as well.
- **Creating the person of a new tracker** (M2g, `persons.py`, checked against
  the `person` sources at **both** `2026.6.0` — our floor — and `2026.9.3`,
  2026-09-21). The two helpers are byte-identical at the two tags:
  `async_create_person(hass, name, *, user_id=None, device_trackers=None)`
  (line 93 at 2026.6.0, line 96 at 2026.9.3) and the `@callback`
  `persons_with_entity(hass, entity_id)` (line 133 / 136), which returns the
  `person` entity IDs whose `device_trackers` contain the entity and returns
  `[]` when `person` is not set up. `async_create_person` is not private in
  practice: core calls it from `onboarding/views.py` (line 199 / 219), and
  there too only after the component is up (`async_wait_component`). It writes
  through `hass.data[person.DOMAIN][1]`, the `PersonStorageCollection`, which
  is only put there at the very end of `person.async_setup()` (line 382 /
  392) — hence the same timing as the repair issues (`async_at_started`) plus
  a check of `hass.config.components`, and hence a marker in the subentry data
  instead of a person created by the flow: at form time neither the collection
  nor the tracker's own entity is guaranteed to exist.
  Three findings shape the rules around the call. **Duplicates are not
  prevented by core**: `PersonStorageCollection._get_suggested_id()` returns
  the plain *name* and `IDManager.generate_id()` slugifies it and appends
  `_2`, `_3`… (`helpers/collection.py`, line 96), so a second "Kid" is created
  silently. The integration therefore checks the person *states* itself, case
  insensitively (`State.name`, which covers YAML and storage persons alike),
  and creates nothing when the name is taken — taking somebody else's person
  over is not ours to decide, and `tracker_not_assigned` already names the two
  clicks. **`device_trackers` is only validated for domain and format**
  (`CREATE_FIELDS` uses `cv.entities_domain(device_tracker)`), not for
  existence, so the entity ID is looked up in the entity registry
  (`async_tracker_entities()`, the same helper the issues use) rather than
  guessed from the name. And **the person entity exists when the call
  returns**: `async_create_item()` awaits `notify_changes()`, which awaits
  `_CollectionLifeCycle._collection_changed()` and
  `EntityComponent.async_add_entities()`. That is what makes re-checking the
  repair issues right afterwards deterministic, and it is why
  `tracker_not_assigned` is merely *held back* while a marker is pending
  instead of being ordered against the person: the issues run first (they are
  started first, and their callback is a plain `@callback` while this one is a
  coroutine task), see the marker and skip that tracker; the person work then
  clears the marker and asks for a re-check.
- **No `person` dependency in the manifest** (M2g), for the same reasons as
  `mobile_app` above. hassfest does check the imports of a custom integration
  (`script/hassfest/dependencies.py`: `_validate_dependency_imports()` runs
  outside the `if not config.specific_integrations` branch), but `person` is
  part of `ALLOWED_USED_COMPONENTS` there, so importing it needs no
  declaration. `dependencies` would force `person` to be set up, and
  `after_dependencies` would only move the load order, which is irrelevant for
  work that happens after the start; both would be accepted by hassfest
  (`after_dependencies` is in `INTEGRATION_MANIFEST_SCHEMA`, which the custom
  schema extends) and buy nothing.
- **No option is cached**: the manager reads every one of them where it uses it
  (`_ask_on_departure()`, `_answer_timeout()`, `_prompt_delay()`, the reset in
  `_async_reset_trackers()`), and `delivery.py` reads `answer_timeout` and
  `notify_on_expiry` out of the subentry at send time. The single exception is
  deliberate: the manager remembers the *previous* ask value per tracker, in
  order to notice the transition to off. An open prompt keeps the deadline it
  was opened with when the timeout changes; the new value applies to the next
  prompt.

## Milestones

| Stage | Content |
|---|---|
| **M1** | Scaffolding, config flow + subentry (name, options), `switch` + `device_tracker` + `binary_sensor`, reset on real-person return, restore-state test, tests + CI. Live-testable: switch on → `zone.home` counts up. |
| **M1f** (done) | Onboarding (requested after the first live test, 2026-09-20): after the entry is created the config flow chains straight into the "add virtual tracker" subentry flow (`async_on_create_entry` + `FlowType.CONFIG_SUBENTRIES_FLOW`, which the frontend supports); a repair issue while no tracker exists. |
| **M1g** (done) | The household sensor loses its device (2026-09-20), so the entry row no longer shows "Devices that do not belong to a sub-entry"; one-off clean-up of the device of older installs. |
| **M2a** (done) | Prompt state machine per tracker (idle → pending → answered / expired / cancelled, persisted across restarts), a per-tracker `event` entity, an `answer_prompt` service and the per-tracker options (ask on departure, answer timeout, delay). **No push yet** — testable with services and events; the contract is frozen above. |
| **M2b** (done) | Built-in delivery: actionable `mobile_app` notification to the real persons chosen per tracker, person → phone mapping derived from the `mobile_app` entries at send time, answers from the notification buttons, clearing on every ending, optional expiry notice, `recipient_without_phone` repair issue. Live-tested on 2026-09-20 (HA 2026.9.3, iPhone): the prompt opens at once, the push arrives, a tapped button answers it, `answered_by` is the person behind the phone's user, "No" changes nothing. |
| **M2c** (done) | The message carries the integration's own icon (the brand icon served under `/api/brands`), on the prompt and on the expiry notice. First built as the picture of the message (`data.image`); the live test on 2026-09-20 showed it, but on the wrong side - see M2e. |
| **M2d** (done) | The entity service `open_prompt` on the switches: opens the prompt of a tracker at once, ignoring the real persons, the `ask_on_departure` option and the delay, so the whole chain can be tried out from Developer Tools without leaving the house. A prompt still waiting for its delay is taken over with its ID; a prompt opened by hand is marked `manual` and survives a restart that would withdraw an automatic one. Live-tested on 2026-09-20 (HA 2026.9.3, iPhone and Android tablet): the action opens the prompt, yes, cancelling by switching the tracker on and the expiry with its notice all behave as designed. |
| **M2e** (done) | The icon moves from the picture of the message to the icon beside it: `data.icon_url` instead of `data.image` (the live test of M2c showed the attachment as a thumbnail on the right, where the app's own icon on the left was meant). On iOS that makes the prompt a communication notification with the icon as its avatar, on Android it is the large icon; no `image` is sent any more. Needs iOS Companion 2026.8.0 or newer for the avatar. Live-tested on 2026-09-20 (HA 2026.9.3): the icon replaces the app icon on the iPhone, and the prompt works on an Android tablet. |
| **M2f** (done, not live-tested yet) | The settings of a tracker become entities on its device page (decided after a usability review, 2026-09-21): three switches and two numbers for `ask_on_departure`, `reset_on_return`, `notify_on_expiry`, `answer_timeout` and `prompt_delay`, so the form is down to name and recipients. The values stay in the subentry data, and writing one does **not** reload the entry any more — the update listener compares a fingerprint that leaves those five keys out, because a reload would take the trackers and their persons to `unavailable` for a moment. Switching the ask option off takes a scheduled or open automatic prompt back at once (`option_disabled`); a prompt opened by hand survives it. A new tracker is written with all five keys and asks by default, and its recipients come up with every real person ticked. |
| **M2g** (done, not live-tested yet) | The `person` of a new virtual tracker is created by the integration (decided after the same usability review, 2026-09-21): the form of a new tracker has a "Create a person for this tracker" box, ticked by default, and leaves a `create_person` marker in the subentry data; once Home Assistant has started, `person.async_create_person()` creates a person without a login named after the tracker with the tracker assigned. Nothing is created when a person already follows the tracker or already goes by that name, and the marker is taken off in every case — without reloading the entry, so the work happens exactly once and a person the user deletes later never comes back. `tracker_not_assigned` is held back while a marker is pending and stays the fallback for a tracker whose box was unticked. Removing a tracker still leaves its person alone. |
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
  - **Timeout semantics (confirmed 2026-09-20)**: an unanswered prompt never
    picks a default. At the timeout the tracker stays as it was (off), the house
    counts as empty and the event is `expired`; the built-in message is cleared
    from the phones. Switching the tracker on by hand before leaving means no
    prompt is opened at all.
  - **Optional expiry notice (M2b, per tracker, default off)**: option
    `notify_on_expiry`. When on and built-in delivery is active (recipients
    chosen), the recipients get a short "no answer, <name> counts as not at
    home" message when the prompt expires — never on an answer or a
    cancellation.

- **M2f decisions (dabo53ck, 2026-09-21, after a usability review)**: the
  per-tracker settings become **entities on the tracker's device page**, which
  leaves the form with name and recipients only - friendlier for people who do
  not think in config flows. All five are configuration entities - the ask
  switch was a normal control at first and joined the others on dabo53ck's call
  (2026-09-21), because it is a setting like the rest and reads better under
  "Configuration" than next to the tracker's own switch; it stays writable from
  an automation either way. **A change must not reload the entry** (the
  flicker of the trackers and their persons is the reason, and it is why the
  fingerprint exists). **A new tracker asks by default**, while a tracker
  without the key keeps meaning "does not ask", and the recipients of a new
  tracker come up with every real person ticked.

- **M2g decision (dabo53ck, 2026-09-21)**: the integration **creates the person**
  of a new virtual tracker, because having to create one by hand and assign the
  tracker to it is the biggest hurdle a new user faces - and the one step that
  nothing about the integration shows. Ticked by default, offered for **new
  trackers only**, and never a second person of a name that is already there.
  The person is **not** removed with its tracker: a person is the user's own
  data, may carry other trackers and may be named in automations. A tracker
  whose box is unticked keeps the old path, and the repair issue keeps naming
  it.

- **Branding (2026-09-20)**: the mark is a house in Home Assistant blue with a
  person drawn in dots ("somebody is home, but there is no tracker for them").
  Assets live in `custom_components/virtual_presence_tracker/brand/` — SVG
  sources plus PNGs (`icon`, `logo`, `dark_*`, `@2x`) rendered with resvg; Home
  Assistant 2026.3+ loads them straight from that folder, so no
  `home-assistant/brands` PR is needed for our floor (2026.6). The logo's
  subtitle is fitted to exactly the width of the title; regeneration steps are in
  `brand/README.md`.

Live instance facts: persons `person.dabo53ck`, `person.king53ck` (both currently home).

- **Prompt delivery = hybrid ("variant C")**: the integration owns the state
  machine (prompt pending, timeout, reset), fires events (prompt started /
  expired) and offers services (`confirm` / `deny`). On top it offers an
  *optional* built-in `mobile_app` actionable notification as a convenience.
  Other channels (Telegram, TTS, …) listen to the events and call the services;
  a companion blueprint can be a thin layer on that later. Pending state and
  timers must survive an HA restart. Event names and payload keys are fixed as
  of M2a — see "Event & service contract" (public contract, see CLAUDE.md).

- **M2b live test passed (2026-09-20, HA 2026.9.3, iPhone)**: the prompt opens
  the moment the house is empty, the push arrives, a tapped button answers the
  prompt, `answered_by` is derived from the user of the phone, and "No" changes
  nothing. The recipient was dabo53ck only; king53ck stayed a real person without being
  asked.

- **M2c live test (2026-09-20, HA 2026.9.3, iPhone)**: the icon is really
  fetched and shown, so the authenticated `/api/brands` URL works - but as a
  picture it sits as a thumbnail on the *right* of the message, while the spot
  that was meant is the app icon on the left. Hence M2e.

**Live test of M2d and M2e (2026-09-20, HA 2026.9.3, iPhone and Android
tablet)**: `open_prompt` on the tracker's switch from Developer Tools opens the
prompt without anybody having to leave the house; on the iPhone it shows as a
communication notification with our icon as its avatar on the left, and the
whole chain (yes, cancelling, expiry with its notice) works on both phones.
Nothing is open; nothing blocks M3.
