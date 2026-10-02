<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/virtual_presence_tracker/brand/dark_logo@2x.png">
  <img src="custom_components/virtual_presence_tracker/brand/logo@2x.png" alt="Virtual Presence Tracker" width="640">
</picture>

**Somebody is at home but Home Assistant thinks the house is empty? Tell it. For a
child without a phone, grandparents, a babysitter, or any guest.**

[![Release][release-badge]][release-url] &nbsp; [![HACS][hacs-badge]][hacs-url] &nbsp; [![Validate][validate-badge]][validate-url] &nbsp; [![Tests][tests-badge]][tests-url]

</div>

A Home Assistant custom integration for people who are at home without a
tracked phone. For each of them you create a **virtual tracker**, and you set
it yourself: by hand, from an automation, or by answering a question on your
phone. It has no detection of its own; if you want, a tracker can also follow a
button or a presence source you already have in Home Assistant.

It does not simulate presence in an empty house; it is for people who really
are at home.

## How it works

Home Assistant decides who is at home from your **real persons**: the people it
already locates with a device tracker of their own, usually a phone. When the
last of them leaves, the house counts as empty.

A virtual tracker is a switch: on means "Kid is at home". While it is on, it
behaves like a device tracker: `person.kid` is `home`, `zone.home` counts them,
and your "nobody home" routines stay quiet. It can be switched in several ways,
and they can be combined:

- **By hand or by an automation**: from a dashboard, an NFC tag or a wall
  switch. See [Use the switch](#5-use-the-switch).
- **By answering your phone**: when the last real person leaves, your phone
  asks "Is Kid home alone?", and **Yes** switches the tracker on. See
  [The prompt](#the-prompt).
- **By a button** you already have in Home Assistant, for example a Shelly BLU
  button: one press for home, a long press for away. See [Buttons](#buttons).
- **By a presence source** you already have in Home Assistant (optional):
  - a **Wi-Fi device**, such as the child's tablet, through the device tracker
    of your router's integration;
  - a **Bluetooth tag**, such as a key finder in the school bag, picked
    directly from the Bluetooth devices Home Assistant receives;
  - any other device tracker or binary sensor.

  The tracker goes on when a source is present and off once all of them have
  been away for a while. A source only tells what it sees (a tablet in the
  Wi-Fi, a tag in radio range), not who is holding it. See
  [Presence sources](#presence-sources).

Two things look after a tracker that is on:

- When the first real person comes back to the empty house, it switches itself
  off. See [Rules at a glance](#rules-at-a-glance).
- If it stays on for a long time (24 hours by default), you get a reminder
  asking whether Kid is still home. See [The reminder](#the-reminder).

## Who it is for

A tracker has a free-form name and no built-in role. Create one per person, or
one shared tracker for a group ("Guests").

| Somebody who… | A setup that fits |
|---|---|
| **A child** with no phone, home alone after school | The defaults. Your phone asks when the last of you leaves; the tracker switches off when the first of you is back. A switch on an NFC tag by the door works too. |
| **A babysitter** for an evening | Switch the tracker on before you go, or answer **Yes** when your phone asks. It switches off when you are back; if the sitter leaves earlier, switch it off yourself. |
| **Grandparents** or **guests** for several days | Turn **Reset on return** off, so the tracker does not switch off the first time you come home during the visit. Set **Remind after** to about the length of the stay (48 hours, say), so you are asked instead of finding out a week later. |
| **A carer, a cleaner, a house sitter** | Keep **Ask when empty** on: whenever the last of you leaves, you are asked whether they are still in the house. |

Nothing has to be installed on the other person's side.

## What it does not do

- It delivers the questions only to the Home Assistant Companion App. Any other
  channel is an automation of your own; see
  [docs/AUTOMATIONS.md](docs/AUTOMATIONS.md).
- It never switches a tracker off because nobody answered. It reminds you;
  switching off stays your decision.
- It detects nothing by itself. A tracker only knows what you, an automation or
  a source you linked to it tells it.

## Requirements

- Home Assistant **2026.6.0** or newer (the trackers are built on
  `BaseScannerEntity`, which first shipped with that release).
- At least one real person with a device tracker of their own.
- For the question on the phone: the Home Assistant Companion App on the phones
  of the people who are asked, signed in with **that person's own user
  account**. Any app version delivers the question; showing the integration's
  icon in place of the app icon needs the **iOS Companion App 2026.8.0** or
  newer.
- Only for Bluetooth devices as a presence source: Home Assistant's Bluetooth
  integration, with a local adapter or a Bluetooth proxy.

**Tested with** the iOS Companion App on an iPhone and the Android Companion App
on a tablet.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dabo53ck&repository=virtual-presence-tracker-ha&category=integration)

1. Click the button above (or open HACS → **⋮** menu, top right → **Custom
   repositories**, and add
   `https://github.com/dabo53ck/virtual-presence-tracker-ha` with the type
   **Integration**).
2. Install **Virtual Presence Tracker** and restart Home Assistant.

### Manual

1. Copy the folder `custom_components/virtual_presence_tracker` into the
   `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

## Setup

### 1. Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=virtual_presence_tracker)

If the button doesn't work: **Settings → Devices & services → Add integration
→ Virtual Presence Tracker.**

You are asked for your **real persons**. They decide when the house is empty,
so each of them needs a device tracker of their own; the persons that currently
have one are suggested. At least one person is required.

You can change them later with **Reconfigure** on the integration's page.

Do **not** pick the person a virtual tracker belongs to: switching that tracker
on would look like a real arrival and switch every tracker off. **Reconfigure**
refuses such a person, and a repair issue reports it if it happens otherwise.

### 2. Add a virtual tracker

The form for your first tracker opens by itself. It asks for three things:

- **Name**: the child, grandparent or guest the tracker stands for.
- **Who is asked?**: the real persons whose phones get the questions about this
  tracker. For a new tracker all of them are ticked. Leave it empty to send
  nothing and handle the questions with an automation of your own.
- **Create a person for this tracker** (ticked): creates a person without a
  login, named like the tracker, and assigns the tracker's device tracker to
  it. That person is what counts as being at home. The integration never
  changes a person you already have, never creates a second person of the same
  name, and never deletes one, not even together with its tracker.

If you unticked the box because you already have a person for this tracker:
open it under **Settings → People** (or add one, no login needed), pick
`device_tracker.kid` in its list of device trackers, and save. Until then a
repair issue reminds you.

Three more fields, **Buttons**, **Presence sources** and **Bluetooth devices**,
are optional; leave them empty for a tracker you switch yourself (see
[Optional: buttons and presence sources](#optional-buttons-and-presence-sources)).

If you close the form without adding a tracker, a repair issue reminds you. You
add the first and every further tracker under **Settings → Devices & services →
Integrations → Virtual Presence Tracker → Add virtual tracker**. **Edit virtual
tracker** on the same page changes the name, **Who is asked?**, the buttons and
the presence sources later.

### 3. The entities you get

For a tracker named *Kid*:

| Entity | What it is for |
|---|---|
| `switch.kid_at_home` | The control. On means "Kid is at home". |
| `device_tracker.kid` | Follows the switch (`home` / `not_home`). Assigned to Kid's person. |
| `event.kid_questions` | Announces the prompt and the reminder (see below). |

Next to them sit nine settings entities; see [Settings](#settings).

Entity IDs are built from the tracker's name and the entity names in the
**language of your Home Assistant**. This README uses English; on a German
instance the same entities are `switch.kid_zuhause` and `event.kid_fragen`.
Look yours up under **Settings → Devices & services → Entities**.

### 4. Try it right away

You do not have to leave the house to see the question on your phone:

1. **Developer tools → Actions**.
2. Pick **Virtual Presence Tracker: Open prompt** (the tracker has to be off)
   or **Virtual Presence Tracker: Open reminder** (the tracker has to be on).
3. Choose the tracker's switch (`switch.kid_at_home`) as the target and press
   **Perform action**.

The question goes to everybody under **Who is asked?** and then behaves as
after a real departure: answer it on the phone, switch the tracker yourself, or
let the time run out. Set **Prompt answer time** or **Reminder answer time** to
one minute while you are testing.

### 5. Use the switch

Put the switch on a dashboard (see [Everyday use](#everyday-use)), on an NFC
tag at the front door or on a wall button, or let an automation flip it.

## Everyday use

![An entities card "At home" with a tracker's switch, its device tracker and the "Only virtual trackers home" sensor, and below it the same switch as a tile card](images/dashboard.png)

```yaml
type: entities
title: At home
entities:
  - entity: switch.kid_at_home
    name: Kid
  - entity: device_tracker.kid
  - entity: binary_sensor.only_virtual_trackers_home
```

### The "Only virtual trackers home" sensor

One binary sensor for the household, `binary_sensor.only_virtual_trackers_home`
on an English instance: on when at least one virtual tracker is at home and
none of your real persons is. Use it to make a routine behave differently when
the only people at home are ones without a tracked phone. It has no device;
find it under **Settings → Devices & services → Entities**.

Its attributes are `real_persons_home` (how many real persons are at home) and
`virtual_trackers_home` (the names of the trackers that are on). Right after a
restart it is `unknown` until the state of a real person is known; treat
`unknown` as "do nothing".

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.only_virtual_trackers_home
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_<your_phone>
    data:
      message: Only virtual trackers are at home now.
```

## The phone question and the reminder

### The prompt

When the last real person leaves and a tracker is off, the people under **Who is
asked?** get a question on their phones:

![A prompt on an iPhone lock screen: "Is Noah home alone? Nobody else is home. Answer within 10 minutes.", with the integration's icon and the buttons "Yes, home alone" and "No"](images/notification.png)

**Yes** switches the tracker on. **No** or no answer changes nothing: the house
keeps counting as empty. There is never a default answer. The first answer
counts, and the message disappears from every phone that was asked; it also
disappears when somebody comes home, when the tracker is switched on and when
the time runs out.

A tracker that is already on does not ask, so you can also switch it on before
you leave.

### The reminder

A tracker that somebody forgets to switch off keeps the house counting as
occupied: the alarm does not arm, the vacuum does not run. Once a tracker has
been on for **Remind after** hours, the same people are asked "Is Kid still
home?":

- **Yes, still home** changes nothing and starts the waiting time again.
- **No, switch off** switches the tracker off.
- **No answer** changes nothing either: the tracker stays on, and you are asked
  again after another interval. Nothing is switched off by itself.

**0 means never**; a new tracker starts at 24 hours. The reminder has its own
**Reminder answer time** (60 minutes by default, against the prompt's 10),
because a reminder is often answered much later than a prompt.

### About the messages

- **Notice if unanswered** sends a short note when a question expires: "No
  answer: Kid counts as not at home." for the prompt, "No answer: Kid stays
  marked as home." for the reminder. Off by default, and only sent on an
  expiry.
- All messages about one tracker are stacked in a group of their own on the
  phone; Android labels it "Virtual presence: Kid".
- The messages show the integration's icon in place of the Home Assistant app
  icon (on iOS this needs the Companion App 2026.8.0 or newer).
- They are in English, German, French or Spanish, following the language of
  your Home Assistant instance; any other language gets English.
- A person with two phones is asked on both. If Home Assistant has no phone for
  somebody under **Who is asked?**, a repair issue says so.

### When the phone is on silent

A phone on silent or on Do Not Disturb shows the prompt without a sound, and an
unnoticed prompt leaves the house counting as empty. With **Override Do Not
Disturb for the prompt** on, the prompt is sent:

- on **iOS** as a *critical alert*, which ignores the mute switch and Do Not
  Disturb. This also needs the **Critical Alerts** switch in the notification
  settings of the Home Assistant app; without it the prompt arrives as a normal
  notification.
- on **Android** on the `alarm_stream` channel, the exception Do Not Disturb
  keeps for alarms.

It is loud, at night and in meetings too, so it is **off by default**. It
applies to the prompt only; the reminder and the notes about unanswered
questions stay quiet.

### Other channels

Every prompt and reminder is announced by the tracker's event entity and can be
answered with an action, so a speaker, Telegram or a dashboard button can carry
the question instead of the phone, or alongside it. See
[docs/AUTOMATIONS.md](docs/AUTOMATIONS.md).

## Settings

Everything a tracker can be set to is an entity on its device page, **Settings →
Devices & services → Virtual Presence Tracker → Kid**, under **Configuration**,
out of the way of everyday use. They can be used in automations like any other
switch or number, and a change takes effect without a reload.

![The Configuration section of a tracker's device page with the settings entities of a tracker](images/settings.png)

| Entity | What it does | Default |
|---|---|---|
| **Ask when empty** (switch) | Whether the tracker asks at all when the last real person leaves. | on |
| **Reset on return** (switch) | Switches the tracker off when the first real person comes back to the empty house. | on |
| **Prompt answer time** (number) | How long a prompt stays open, 1 to 120 minutes. | 10 |
| **Prompt delay** (number) | How long to wait after the last departure before asking, 0 to 600 seconds. | 0 |
| **Notice if unanswered** (switch) | Sends a short note when a prompt or a reminder expires. | off |
| **Remind after** (number) | After how many hours on the tracker asks whether the person is still there, 0 to 168 hours. 0 means never. | 24 |
| **Reminder answer time** (number) | How long a reminder stays open, 1 to 360 minutes. | 60 |
| **Override Do Not Disturb for the prompt** (switch) | Lets the prompt through a silenced phone; see [When the phone is on silent](#when-the-phone-is-on-silent). | off |
| **Away after** (number) | Only for a tracker with presence sources: how long all of them have to report "away" before it switches off, 1 to 120 minutes. | 10 |

### Rules at a glance

- **Reset on return** acts when the number of real persons at home goes from
  **0 to 1**. Nothing happens when a second person arrives, when people leave,
  or right after a restart (a person whose state was not known before does not
  count as arriving).
- It is set per tracker. Turn it off for guests who stay several days.
- A tracker with **presence sources** is never reset this way; its sources
  decide when it goes off. A tracker with buttons only resets as usual.
- A tracker asks only when the last real person leaves and it is off. Switching
  **Ask when empty** off withdraws a waiting or open prompt, from the phones as
  well (not one you opened with **Open prompt**).
- The prompt does not hold back your own "nobody home" automations:
  `zone.home` is already empty when the last real person leaves. See
  [How the timing works](docs/AUTOMATIONS.md#how-the-timing-works).

## Optional: buttons and presence sources

A tracker needs none of this and works as described above without it. Buttons
and presence sources only add more ways to switch it; the switch, your
automations and the questions keep working. Both are picked in the tracker's
form (**Add virtual tracker** or **Edit virtual tracker**).

![The optional fields of a tracker's form: a Shelly BLU button under Buttons, a tablet's device tracker under Presence sources, and the same Shelly picked under Bluetooth devices](images/sources.png)

Three examples:

- **A Shelly BLU button by the door** as a button: `press` means home (switch
  on), `long_press` means away (switch off). Every other event type of the
  button is ignored and stays free for your own automations.
- **A Bluetooth tag in the school bag** as a Bluetooth device, with **Away
  after** at 10 minutes: the tracker switches on when the tag is heard and off
  once it has not been heard for 10 minutes.
- **The child's tablet in your Wi-Fi** as a device tracker of your router's
  integration: the tracker switches on when the tablet connects and off once it
  has been away for **Away after**.

### Buttons

A button can be any `event` entity, from any integration. After you pick one,
the step **Button events** asks which of its event types mean home and which
mean away; for a button that offers `press` it suggests `press` and
`long_press`.

![The Button events step: press ticked under "Means home (switch on)", long_press ticked under "Means away (switch off)", every other event type unticked](images/button-events.png)

### Presence sources

The tracker counts as present while any of its sources is:

- a **device tracker** while it is `home`, for example a tablet or a games
  console in your Wi-Fi through your router's integration, or a Bluetooth tag
  through an integration such as iBeacon Tracker, Private BLE Device or
  Bermuda;
- a **binary sensor** while it is `on`;
- a **Bluetooth device**, picked by its fixed address from the devices Home
  Assistant receives, while it has been heard within **Away after**. Phones and
  other devices that keep changing their address cannot be followed this way;
  use the device tracker of their own integration instead.

The tracker switches on when its sources become present and off once all of
them have been away for **Away after**. A change by hand in between stays until
the next such change, and `unknown` or `unavailable` never counts as away.

A source only says what it says: a tablet in the Wi-Fi may be lying on the
sofa while its owner is out, and a Bluetooth tag in range means it is near one
of Home Assistant's Bluetooth adapters or proxies, which may include the garden
or the flat next door.

If a source is present when the last real person leaves, the tracker switches
on instead of asking, also with **Ask when empty** off.

Timing, polling and what a restart does are in
[docs/AUTOMATIONS.md](docs/AUTOMATIONS.md#buttons-and-presence-sources).

## Troubleshooting

The integration reports what it cannot fix by itself under **Settings → Devices
& services → Repairs**. Every issue disappears on its own once its cause is
gone.

| Repair issue | Cause | Fix |
|---|---|---|
| **No virtual tracker has been added yet** | The integration is set up without a tracker, so nothing happens. | Add one: **Virtual Presence Tracker → Add virtual tracker**. |
| **The virtual tracker … is not assigned to a person** | The tracker's device tracker is not part of any person, so switching it on makes nobody count as being at home. | In **Settings → People**, open the person (or add one, no login needed) and pick `device_tracker.<name>`. Or delete the tracker. |
| **The real person … has a virtual tracker attached** | A real person carries a virtual tracker, so switching it on looks like a real arrival and resets every tracker. | Remove the tracker from that person in **Settings → People**, or take the person out of the real persons with **Reconfigure**. |
| **… has no phone to be asked on** | Somebody under **Who is asked?** has no Companion App registered for their user account. | Install the Companion App and sign in with their own user account, or take them out of **Who is asked?**. |
| **The real person … no longer exists** | A real person was deleted or renamed, so their presence is no longer taken into account. | Select your real persons again with **Reconfigure**. |

## FAQ

**Does the other person have to install anything?**
No. Nothing runs on their side. The integration stores, per tracker, whether it
is on and since when, plus an open question if there is one.

**Can a person have both a virtual tracker and a real one?**
Yes. The virtual tracker reports as a `router`-type tracker (home or away, no
coordinates), and Home Assistant prefers such a tracker that is `home` over GPS:
while the virtual tracker is on it wins, while it is off the other tracker
decides.

**Can I have more than one household?**
No. There is one configuration per Home Assistant instance, with any number of
trackers in it.

**Does renaming a tracker break my automations?**
No. Entity IDs and unique IDs do not change when you rename a tracker; only the
displayed name does.

## Help, translations and license

Questions and bug reports:
[GitHub issues](https://github.com/dabo53ck/virtual-presence-tracker-ha/issues).
To add a language, see [CONTRIBUTING.md](CONTRIBUTING.md).

License: [MIT](LICENSE)

[release-badge]: https://img.shields.io/github/v/release/dabo53ck/virtual-presence-tracker-ha?include_prereleases&label=release
[release-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/releases
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[validate-badge]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/validate.yml
[tests-badge]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/tests.yml/badge.svg
[tests-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/tests.yml
