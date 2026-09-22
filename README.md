<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/virtual_presence_tracker/brand/dark_logo@2x.png">
  <img src="custom_components/virtual_presence_tracker/brand/logo@2x.png" alt="Virtual Presence Tracker" width="640">
</picture>

**Somebody is at home but Home Assistant thinks the house is empty? Tell it. For a
child without a phone, grandparents, a babysitter, or any guest.**

[![Release][release-badge]][release-url] &nbsp; [![HACS][hacs-badge]][hacs-url] &nbsp; [![Validate][validate-badge]][validate-url] &nbsp; [![Tests][tests-badge]][tests-url]

</div>

A Home Assistant custom integration. For every person who cannot be tracked
automatically you create a **virtual tracker**. While it is switched on, that
person counts as being at home: `zone.home` counts them, and the "nobody home"
automations you already have stay quiet. It switches itself off when you come
back, and it can ask you on your phone whether somebody is home when the last of
you leaves.

**This is not a presence simulation.** Unlike "Home Alone"-style integrations that
fake activity while the house is empty, this one is about people who really are at
home but carry no tracked device.

## Quick start

1. **Install it.** Copy the folder `custom_components/virtual_presence_tracker`
   into your Home Assistant configuration and restart. The repository is still
   private, so HACS is not an option yet — see [Installation](#installation).
2. **Add the integration.** **Settings → Devices & services → Add integration →
   Virtual Presence Tracker**, or use this button:

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=virtual_presence_tracker)

3. **Answer the two forms** that follow — your real persons, then your first
   virtual tracker — and let the integration create the tracker's person for
   you. Step by step under [Setup](#setup).

Everything a tracker can be set to afterwards is an entity on the tracker's own
page; see [The tracker's settings](#the-trackers-settings).

## Who it is for

Home Assistant works out who is at home from trackers, usually phones. That
breaks down whenever somebody is in the house without one: you leave, the house
looks empty, and the routines for an empty house run — lights off, alarm armed,
heating turned down, the robot vacuum sent off — around the person who is still
there.

| Somebody who… | Without a virtual tracker | With one |
|---|---|---|
| **A child** with no phone, home alone after school | The house counts as empty as soon as the last of you has left. | Their tracker is on (or they are asked on your phone): the house does not count as empty. |
| **A babysitter** for an evening | The moment you go out, your "nobody home" routines run around the sitter. | The sitter's tracker is on while you are out, and it switches itself off when you are back. |
| **Grandparents** or **guests** who stay a few days | Every time the family goes out, the empty-house routines run — for the whole visit. | Their tracker is on for the stay and off when they leave. |
| **A carer, a cleaner, a house sitter** | The house looks empty while they work. | A tracker per person, or one shared tracker, switched on when they arrive. |

Nothing has to be installed on the other person's side, and nothing is tracked:
the integration only knows what you, an automation, or an answered prompt tell it.

## How it works

1. You create a virtual tracker, for example "Grandma", and assign its
   `device_tracker` to a `person` without a login.
2. You switch it on — from a dashboard, an NFC tag, a button, an automation, or
   by answering a prompt on your phone. `person.grandma` is now `home`.
3. `zone.home` counts them, so every automation and dashboard card that asks "is
   anybody home?" sees somebody at home. When you come back to the house, the
   tracker switches itself off again (you can turn that off per tracker).

## What it does

- A **switch** per virtual tracker: on means "this person is at home".
- A **device tracker** per virtual tracker that follows the switch (`home` /
  `not_home`). This is the entity a person needs to have.
- **The person for a new tracker, created for you**: a person without a login,
  named like the tracker and with the tracker already assigned — the step that
  used to be manual, and the one people forgot. Optional, and only ever for a
  tracker you are adding.
- A **binary sensor** "Only virtual trackers home" for the household: on when at
  least one virtual tracker is at home and none of your real persons is.
- **Automatic reset**: when the first real person comes back to an empty house,
  the trackers switch off again, so nobody stays "at home" for days by mistake.
- **Settings as entities**: whether a tracker asks, when it resets and the
  timings of its prompt are switches and numbers on the tracker's own page —
  changed with a tap, usable in automations, and without a reload.
- A **prompt** when the last real person leaves: "is Kid at home?",
  sent to the phones of the people you pick as a **notification with Yes and No
  buttons**. Every prompt is also announced by an **event entity** and can be
  answered with the action **Answer prompt**, so any other channel — a speaker,
  a dashboard, Telegram — can carry the question instead. The action **Open
  prompt** asks the question on demand, which is also how you try the whole
  chain out without leaving the house.
- A **reminder** for a tracker that has been on for too long: "is Kid still
  home?", after the number of hours you set. A forgotten switch is the one way
  this integration can make things worse than before — the house counts as
  occupied for days — and this is the safety net against it.

## What it does not do

- It does not detect anything by itself. A virtual tracker only knows what you,
  an automation or an answered prompt tell it.
- It does not deliver the prompt or the reminder anywhere except to the Home
  Assistant Companion App. Any other channel is an automation of your own on the
  event entity (there is a ready-made example below).
- It does not switch a tracker off by itself when nobody answers. It reminds
  you; switching off stays your decision.
- It does not change what your automations do — it only changes who counts as
  being at home.
- It does not manage your persons beyond the one step it offers: a **new**
  tracker can have its person created for you, once, when you add it. It never
  changes a person you already have, never creates a second person of the same
  name, and never deletes a person — not even when you delete its tracker.
  Untick the box in the form and the person stays yours to create (see below).

## Requirements

Home Assistant **2026.6.0** or newer. The virtual trackers are built on
`BaseScannerEntity`, which first shipped with that release. The phone prompt
additionally needs the Home Assistant Companion App on the phones you want to ask
— any version delivers the question; showing the integration's icon in place of
the app icon needs **2026.8.0 or newer on iOS**.

**Tested with:** the built-in notification has been tried with the **iOS**
Companion App on an iPhone and with the **Android** Companion App on a tablet:
the question arrives, its buttons answer it, and it disappears from the phone
when it ends.

## Status

**Pre-release / in development.** The trackers, switches, the household sensor,
the prompt on the last departure, the reminder for a tracker that has been on
for too long and the delivery of both to the Companion App work. What is not
built yet are the evidence sources (BLE tag, tablet Wi-Fi, door contact) that
could set a tracker home by themselves. See [`docs/DESIGN.md`](docs/DESIGN.md)
for the design and the milestone plan.

## Installation

The repository is still **private**, so it cannot be installed through HACS yet.
Until it is public, use the manual installation.

### HACS (once the repository is public)

<!-- TODO: add the HACS My-button once the repo is public -->

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/dabo53ck/virtual-presence-tracker-ha` with the
   category **Integration**.
3. Install **Virtual Presence Tracker** and restart Home Assistant.

### Manual

1. Copy the folder `custom_components/virtual_presence_tracker` into the
   `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

## Setup

### 1. Add the integration

**Settings → Devices & services → Add integration → Virtual Presence Tracker.**

You are asked for your **real persons**: the people whose presence decides
whether somebody is at home who is not a virtual tracker. Home Assistant has to
be able to locate them on its own, so each of them needs a device tracker of
their own (a phone, usually). The persons that currently have one are
suggested. At least one person is required.

Do **not** pick the person a virtual tracker belongs to. Switching that tracker
on would look like a real arrival and reset all your trackers.

### 2. Add a virtual tracker

The form for your first virtual tracker opens by itself once you have chosen the
real persons. It asks for three things: a name — the name of the child,
grandparent or guest it stands for — **who is asked** when the house empties,
which starts with everybody ticked, and whether to **create a person for this
tracker**, which is ticked as well. Everything else the tracker can be set to is
an entity of its own on the tracker's page (see "The tracker's settings"), so
there is nothing else to decide here.

**Create a person for this tracker** does the step that used to be yours: it
creates a person without a login, named like the tracker, and assigns the
tracker's device tracker to it — which is what makes anybody count as being at
home. Leave it ticked unless you already have a person for this tracker; then
untick it and assign the tracker yourself, as described in step 3.

If you close that form, the integration is set up but has nothing to do, and a
repair issue reminds you of it. You can add a tracker at any time under
**Settings → Devices & services → Integrations → Virtual Presence Tracker → Add
virtual tracker**, which is also where you add the second and every further
tracker. Renaming a tracker later does not change any entity IDs.

Each tracker gives you three entities to work with, for a tracker named *Kid*:

| Entity | What it is for |
|---|---|
| `switch.kid_at_home` | The control. Turn it on when the kid is at home. |
| `device_tracker.kid` | Follows the switch. Assign this one to a person. |
| `event.kid_questions` | Announces the prompt and the reminder (see below). Idle until one of them happens. |

Next to them sit the eight entities that hold the tracker's settings — see "The
tracker's settings".

The entity IDs are built from the tracker's name and the entity names in the
**language of your Home Assistant**. The examples in this README use English; on
a German instance the same entities are `switch.kid_zuhause` and
`event.kid_fragen`. Look yours up under **Settings → Devices & services →
Entities**.

### 3. The person behind the tracker

This is what makes everything else work: without a person, the tracker is just
an entity nobody looks at. If you left **Create a person for this tracker**
ticked, it is done already — `person.kid` exists and follows `device_tracker.kid`
— and you can skip straight to step 4.

Do it by hand if you unticked the box, if you already have a person for this
tracker, or if the person could not be created (a repair issue tells you so):

1. **Settings → People → Add person**, or open the person you already have.
2. Enter the name, and leave the login option off — the person does not need a
   user account.
3. In the list of device trackers at the bottom of the dialog, pick the virtual
   tracker's entity, `device_tracker.kid`.
4. Save.

From now on `person.kid` is `home` while the switch is on, `zone.home` counts the
person, and every automation and dashboard card that asks "is anybody home" sees
them.

Two things the integration deliberately leaves alone: a person that already
goes by the tracker's name is never touched or doubled (you get the repair issue
below instead, and two clicks fix it), and deleting a tracker never deletes its
person — it is yours, it may carry other trackers and it may be named in your
automations.

### 4. Use the switch

Put the switch on a dashboard, on an NFC tag at the front door, on a wall button,
or let an automation flip it. That is the whole daily routine.

## On your dashboard

A tracker needs no card of its own. The switch is the one thing you use every
day; the device tracker and the household sensor are worth having next to it
while you get used to the integration:

```yaml
type: entities
title: At home
entities:
  - entity: switch.kid_at_home
    name: Kid
  - entity: device_tracker.kid
  - entity: binary_sensor.only_virtual_trackers_home
```

The same switch as a tile card, which is what a wall tablet usually gets:

```yaml
type: tile
entity: switch.kid_at_home
name: Kid
```

Use your own entity IDs — they follow the language of your Home Assistant, as
described above.

## Typical setups

- **A child alone after school.** Keep **Reset on return** on and leave your own
  phone under **Who is asked?**: when the last of you leaves, your phone asks
  "Is Kid home alone?" and one tap answers it. Or put the switch on an NFC tag
  by the door.
- **A babysitter for an evening.** Create a tracker "Babysitter" (or reuse one
  called "Guest"). Before you go, switch it on — or answer **Yes** when your
  phone asks. When the first of you comes back, it switches itself off; if the
  sitter leaves earlier, switch it off yourself.
- **Grandparents or guests for several days.** Create a tracker for them and turn
  **Reset on return** **off** for it: otherwise the tracker would switch itself
  off the first time you come home, while the guests are still there. Switch it
  on when they arrive and off when they leave. A single tracker can stand for a
  whole group ("Guests"). Because nothing switches this one off for you, set
  **Remind after** to the length of a typical stay — 48 hours, say — so you are
  asked instead of finding out a week later.
- **Somebody who comes and goes, like a carer or a cleaner.** Leave **Ask when
  empty** on for their tracker and pick who is asked: whenever the last of you
  leaves, you are asked whether they are still in the house.

## The tracker's settings

Everything a tracker can be set to is an entity of that tracker, on its page
under **Settings → Devices & services → Virtual Presence Tracker → Kid**. Change
one and it takes effect immediately — nothing reloads, nothing goes
`unavailable`, and your automations do not notice.

| Entity | What it does | Default |
|---|---|---|
| **Ask when empty** (switch) | Whether this tracker asks at all when the last real person leaves. | on |
| **Reset on return** (switch) | Switches the tracker off again when the first real person enters the empty house. | on |
| **Prompt answer time** (number) | How long a prompt stays open, in minutes (1–120). | 10 |
| **Prompt delay** (number) | How long to wait after the last departure, in seconds (0–600). | 0 |
| **Notice if unanswered** (switch) | Sends a short note when a prompt or a reminder expires. | off |
| **Remind after** (number) | After how many hours at home the tracker asks whether the person is still there, in hours (0–168). **0 means never.** | 24 |
| **Reminder answer time** (number) | How long a reminder stays open, in minutes (1–360). Separate from **Prompt answer time**, because a reminder is often answered much later than a prompt. | 60 |
| **Override Do Not Disturb for the prompt** (switch) | Lets the prompt through a phone that is silenced. Loud — see below. | off |

All of them sit under **Configuration** on that page, out of the way of everyday
use — the only thing under **Controls** is the tracker's own switch. That is
about where they are shown, not about what they can do: they work in automations
and scripts like any other switch or number — switch **Ask when empty** off for
an evening with guests, for example, and on again the next morning.

The defaults above are what a tracker you add now starts with. A tracker created
before these entities existed keeps behaving exactly as it did: its **Ask when
empty** switch is off and its **Remind after** is 0 until you change them.

Only the name and **Who is asked?** are still in a form — **Edit virtual
tracker** on the integration's page — because they are not a value to flip.

## The "only virtual trackers home" sensor

The household sensor (`binary_sensor.only_virtual_trackers_home` on an English
instance) is on when at least one virtual tracker is at home while none of your
real persons is — the situation that used to break "nobody home" routines. Use it
to make a routine behave differently when the only people at home are ones who
cannot be tracked, for example to skip the alarm or to keep the heating on.

The sensor belongs to the household, not to one tracker, and it has no device of
its own. You find it under **Settings → Devices & services → Entities** or
through the **Entities** link on the integration's page — not on a device page.

It has two attributes: `real_persons_home` (how many of your real persons are at
home) and `virtual_trackers_home` (the names of the trackers that are on).

Right after a Home Assistant restart the sensor is `unknown` until the state of
at least one real person is known. It reports what it knows rather than
guessing; automations should treat `unknown` as "do nothing".

## Reset when somebody real comes home

A virtual tracker that stays on for days is worse than no tracker at all, so the
default is to switch it off again when the household stops being empty: the
moment the number of real persons at home goes from **0 to 1**, every tracker
whose **Reset on return** switch is on switches off.

- Nothing happens when a *second* person arrives: if you are at home and somebody
  else comes back, a tracker that is on stays on.
- Nothing happens when people leave.
- Nothing happens right after a restart: a person whose state was never known
  before cannot trigger a reset.
- The setting is per tracker. Turn it **off** for a tracker you always set by
  hand — above all one for guests who stay for several days, since the family
  will come home more than once during the visit.

## Asking when the house empties

The tracker can ask instead of waiting to be told: when the last of your real
persons leaves and the tracker is off, it opens a **prompt** — "is Kid at home?".
Answer **yes** and the tracker switches on. Answer **no**, answer nothing, or let
somebody come home in the meantime, and **nothing changes**: the house keeps
counting as empty. There is never a default answer.

A tracker you add asks by default. Its **Ask when empty** switch turns that off
and on again at any time — during the day, from an automation, or from a
dashboard — and switching it off while a question is already open takes that
question back, off your phones as well. **Prompt answer time** and **Prompt
delay** set the timing, and **Who is asked?** in the tracker's form decides
whose phones the question goes to (see "The tracker's settings").

You can also switch the tracker on by hand before you leave. A tracker that is
already on does not ask anything.

## Ask a phone: the built-in notification

Pick one or more of your **real persons** under **Who is asked?** and the
question is sent to their phones — no automation needed:

> **Is Kid home alone?**
> Nobody else is home. Answer within 10 minutes.
> \[ Yes, home alone ] \[ No ]

**Yes** switches the tracker on, **No** leaves everything as it is, and either way
the message disappears from *every* phone that was asked: the first answer
counts, the rest is ignored. The same happens when somebody comes home, when you
switch the tracker on yourself and when the time runs out — the question is never
left sitting on a phone.

The message wears the integration's own icon instead of the Home Assistant app
icon, so you can see at a glance whose question it is. On **iOS** it takes the
place the app icon sits in, on the left of the message: the notification is shown
in the rounded-avatar style of a messaging app, with the question's title as the
name. This needs the **iOS Companion App 2026.8.0 or newer**; an older app simply
shows its own icon, and everything else about the message is unchanged. On
**Android** the icon is the large icon of the notification.

What it needs:

- the **Home Assistant Companion App** on that person's phone, signed in with
  **that person's own user account** (Settings → People shows which user a person
  belongs to);
- nothing else. A person with two phones is asked on both.

If Home Assistant has no phone for somebody you picked, a repair issue says so
(see below) — the prompt itself still runs.

**Notice if unanswered** adds a short note when a question expires — "No answer:
Kid counts as not at home." for the prompt, "No answer: Kid stays marked as
home." for the reminder further down. One switch covers both. It is off by
default, and it is only ever sent on an expiry — never when somebody answers or
when the question is withdrawn.

### When the phone is on silent

A phone on Do Not Disturb, or simply on silent, shows the prompt without a
sound — and a prompt nobody notices is a prompt nobody answers, which leaves
the house counting as empty for the rest of the evening. **Override Do Not
Disturb for the prompt** is the switch for that case. With it on, the question
is sent in the way each phone reserves for things that must not be missed:

- on **iOS** as a *critical alert*, which ignores both the mute switch and Do
  Not Disturb;
- on **Android** on the *alarm* channel, which is the exception Do Not Disturb
  keeps for alarms.

**It is loud.** It will ring at night, in a meeting and in the cinema, and it
is the one thing in this integration that deliberately ignores a phone that was
put on silent. That is why it is **off by default** — switch it on only for a
tracker where being woken up is better than missing the question, and only for
people who agree to it.

Two more things to know:

- It applies to the **prompt only**. The reminder ("is Kid still home?") and
  the short notes about an unanswered question stay quiet, whatever this switch
  says — they are not questions with a deadline.
- On **iOS** critical alerts additionally need the **Critical Alerts** switch
  in the notification settings of the Home Assistant app. If that is off, the
  prompt simply arrives as a normal notification; nothing else changes.

**Leaving "Who is asked?" empty means the integration sends nothing at all.** The
prompt still opens, the event entity still announces it and the action still
answers it, so your own automation stays in charge. Both ways can be combined:
the event entity fires whether or not the built-in notification goes out, so an
extra announcement on a speaker is just another automation.

The message is in English or in German, depending on the language of your Home
Assistant instance.

### The event entity

`event.kid_questions` publishes everything that happens to the prompt — and to
the reminder — of that tracker. Its `event_type` is one of:

| `event_type` | Meaning |
|---|---|
| `prompt_started` | The prompt is open. `expires_at` says until when. |
| `answered_yes` | Somebody answered yes; the tracker is now on. |
| `answered_no` | Somebody answered no; nothing changed. |
| `expired` | Nobody answered in time; nothing changed. |
| `cancelled` | The prompt was taken back. `reason` says why: `person_home`, `switched_on` or `option_disabled`. |
| `reminder_started` | The reminder is open. `expires_at` says until when. |
| `reminder_answered_yes` | Somebody answered "still home"; nothing changed. |
| `reminder_answered_no` | Somebody answered "switch off"; the tracker is now off. |
| `reminder_expired` | Nobody answered in time; nothing changed. |
| `reminder_cancelled` | The reminder was taken back. `reason` says why: `switched_off` or `option_disabled`. |

Every prompt event also carries `prompt_id` (identifies this one prompt from
start to finish) and `tracker` (the tracker's name); every reminder event
carries `reminder_id` and `tracker`. The two IDs never mix: a reminder event
has no `prompt_id`, and a prompt event has no `reminder_id`. The four
`answered` events carry `answered_by` — the person who answered, or nothing if
the caller did not say.

The switch has four matching attributes, so a dashboard or a template can see
the same thing without listening for events: `prompt_open`,
`prompt_expires_at`, `reminder_open` and `reminder_expires_at`.

### The answer action

```yaml
action: virtual_presence_tracker.answer_prompt
target:
  entity_id: switch.kid_at_home
data:
  answer: "yes"          # or "no"
  answered_by: person.dabo53ck   # optional
```

Target the tracker's **At home** switch (or its device). The tracker's settings
switches are not valid targets: pick one by hand and the action tells you so
instead of doing anything. If that tracker has no open prompt, the action fails
with "there is no open prompt" — an answer that arrives too late does not
switch anything on by accident.

### The open action

```yaml
action: virtual_presence_tracker.open_prompt
target:
  entity_id: switch.kid_at_home
```

Opens the prompt of that tracker **right now**, without waiting for anybody to
leave. It has no options: the tracker's own **Prompt answer time** applies, the
question goes to the phones under **Who is asked?**, the event entity announces
it, and every way of ending it works as usual.

It ignores everything that decides whether to ask *by itself*: who is at home,
the **Ask when empty** switch — a tracker with that switch off can still be
asked about this way — and **Prompt delay**, because "now" means now. If a prompt
of that tracker was still waiting for its delay, it opens immediately instead,
as that same prompt.

Two cases it refuses, without changing anything: the tracker is **already
switched on** (there is nobody to ask about), or a prompt for it is **already
open**.

One thing to keep in mind when you call it from an automation: the message
always says *"Nobody else is home."* That is the sentence the prompt was written
for, and opening the prompt yourself does not check it. Make your automation's
own conditions the thing that makes it true.

### Try the prompt without leaving the house

Trying the prompt out used to mean actually walking out of the zone. It does
not any more:

1. **Developer tools → Actions**.
2. Pick **Virtual Presence Tracker: Open prompt**.
3. Choose the tracker's switch (`switch.kid_at_home`) as the target and press
   **Perform action**.

The question appears on the phones of everybody under **Who is asked?**,
`event.kid_questions` fires `prompt_started`, and the switch gets
`prompt_open: true`. Answer on the phone, answer with **Answer prompt**, switch
the tracker on or let the time run out — all of it behaves exactly as it does
after a real departure. Set **Prompt answer time** to a minute while you are
testing if you do not want to wait ten.

### Example: ask somewhere else

You do not need this to ask a phone — that is what **Who is asked?** does. It is
the pattern for every *other* channel, and it is what a Telegram message, a TTS
announcement or a dashboard button looks like. Two automations: one turns the
prompt into an actionable notification, the other turns the tapped button back
into an answer. Replace `notify.mobile_app_<your_phone>` with your own notify
action, and use a tag and action names of your own — the ones starting with
`VPT_` belong to the built-in delivery.

```yaml
automation:
  - alias: Ask whether Kid is at home
    triggers:
      - trigger: state
        entity_id: event.kid_questions
        not_from: ["unavailable", "unknown"]
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type == 'prompt_started' }}"
    actions:
      - action: notify.mobile_app_<your_phone>
        data:
          title: Nobody at home?
          message: Is Kid at home?
          data:
            tag: vpt_kid_prompt
            actions:
              - action: VPT_KID_YES
                title: "Yes"
              - action: VPT_KID_NO
                title: "No"

  - alias: Answer the Kid prompt
    triggers:
      - trigger: event
        event_type: mobile_app_notification_action
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.action in ['VPT_KID_YES', 'VPT_KID_NO'] }}"
    actions:
      - action: virtual_presence_tracker.answer_prompt
        target:
          entity_id: switch.kid_at_home
        data:
          answer: "{{ 'yes' if trigger.event.data.action == 'VPT_KID_YES' else 'no' }}"
          answered_by: person.dabo53ck
```

A plain state trigger on the event entity plus a condition on `event_type` works
on every supported Home Assistant version. Recent versions also offer a dedicated
**Event received** trigger for event entities in the automation editor, which does
the same thing in one step.

`not_from` is there because the event entity keeps its last event over a restart
of Home Assistant and a reload of the integration: it comes back from
`unavailable`, and with a prompt still open that looks exactly like a fresh
`prompt_started` to a plain state trigger, so you would be asked a second time.
The built-in notification is not affected — it follows the prompt itself, not the
state of the entity.

Buttons in a notification only work through the classic `notify.mobile_app_*`
actions; the notify *entities* of the companion app carry only a title and a
message. The built-in delivery uses the classic actions for the same reason.

### How the timing works

The prompt does not hold anything back. The moment the last real person leaves,
`zone.home` is empty and your own "nobody home" automations run — if one of them
has a short `for:` (a minute, say), it fires **before** the answer arrives.
Answering yes afterwards switches the tracker on and makes the person `home`
again, but whatever already happened has happened.

Two ways around it, and they combine: keep **Prompt delay** shorter than the
delay of your own automations, and make those automations check
`binary_sensor.only_virtual_trackers_home` or the `prompt_open` attribute of the
switch before they act. Or skip the waiting altogether and switch the tracker on
before you leave.

### After a restart

An open prompt survives a restart of Home Assistant and a reload of the
integration. When it comes back:

- if one of your real persons is at home by then, the prompt is withdrawn
  (`cancelled`, reason `person_home`);
- if its time ran out while Home Assistant was off, it reports `expired`;
- otherwise it simply continues with the time it has left and says nothing new.

A prompt you opened yourself with **Open prompt** is an exception to the first
case: it was never about an empty house, so neither a person being at home nor
the switch being off withdraws it after a restart. It still expires on time.

A prompt that was still waiting for its **Prompt delay** is forgotten instead:
it had not been announced yet, so there is nothing to take back. Switching **Ask
when empty** off withdraws an open or waiting prompt with the reason
`option_disabled` — at once, not at the next restart, and again with the
exception of a prompt you opened yourself. A message that is still on a phone is
taken off it in every one of these cases, including the ones that happen while
Home Assistant starts up again.

## Remind me when a tracker has been on for too long

A virtual tracker that somebody forgets to switch off is the one way this
integration can leave you worse off than before: the house counts as occupied
day after day, the vacuum never runs, the alarm never arms. **Remind after**
is the safety net. Set it to the number of hours after which you want to be
asked, and when a tracker has been on for that long your phone gets:

> **Is Kid still home?**
> Kid has been marked as home for 24 hours. Answer within 60 minutes.
> \[ Yes, still home ] \[ No, switch off ]

- **Yes, still home** changes nothing and starts the waiting time again, so the
  next reminder comes after another full interval.
- **No, switch off** switches the tracker off, exactly as if you had used the
  switch.
- **No answer** changes nothing either — the tracker stays on, and you are
  asked again after another interval. Nothing is ever switched off by itself.
  With **Notice if unanswered** on you get a short note about it ("No answer:
  Kid stays marked as home."), the same switch the prompt uses.

**0 means never**, and that is what every tracker created before this feature
keeps: it stays silent until you set a number. A tracker you add now starts at
**24 hours**.

The reminder goes to the same people as the prompt (**Who is asked?**), and
**Reminder answer time** decides how long it waits — an hour by default,
against the prompt's ten minutes. The two are separate on purpose: a prompt has
to be answered before your away routines run, while a reminder asks about a
whole day, and answering it an hour later is perfectly normal. Changing one of
them never changes the other.

The reminder is announced by the same event entity, `event.kid_questions`, with
its own event types, and the switch carries `reminder_open` and
`reminder_expires_at` while it is waiting.
Leave **Who is asked?** empty and nothing is sent at all — the events and the
actions still work, so your own automation can deliver it.

The counting starts when the tracker is switched on, and it starts again every
time somebody answers "still home" or lets a reminder run out. Switching the
tracker off ends it; switching it on starts it over. If you raise **Remind
after** the next reminder moves further away, and if you lower it below the time
the tracker has already been on, you are asked straight away — which is the
point of a safety net.

A reminder survives a restart of Home Assistant: it keeps the time it has left,
or reports `reminder_expired` if its time ran out while Home Assistant was off,
or is withdrawn (`reminder_cancelled`, reason `switched_off`) if the tracker
was switched off meanwhile. A tracker whose interval passed while Home
Assistant was down is asked about shortly after the start.

### The reminder actions

```yaml
action: virtual_presence_tracker.answer_reminder
target:
  entity_id: switch.kid_at_home
data:
  answer: "yes"          # or "no", which switches the tracker off
  answered_by: person.dabo53ck   # optional
```

```yaml
action: virtual_presence_tracker.open_reminder
target:
  entity_id: switch.kid_at_home
```

Target the tracker's **At home** switch (or its device) here too; the settings
switches are not valid targets and say so.

**Open reminder** asks right now, without waiting for **Remind after** to
pass — it even works for a tracker whose interval is 0. It refuses, without
changing anything, if the tracker is **switched off** (there is nobody to
remind you about) or if a reminder for it is **already open**. **Answer
reminder** fails with "there is no open reminder" if nothing is waiting, so a
late answer cannot switch anything off by accident.

### Try the reminder without waiting for hours

1. Switch the tracker on.
2. **Developer tools → Actions**, pick **Virtual Presence Tracker: Open
   reminder**.
3. Choose the tracker's switch (`switch.kid_at_home`) as the target and press
   **Perform action**.

The question appears on the phones of everybody under **Who is asked?**,
`event.kid_questions` fires `reminder_started`, and the switch gets
`reminder_open: true`. Answer on the phone, answer with **Answer reminder**,
switch the tracker off or let the time run out — all of it behaves exactly as
it does after a real interval. Set **Reminder answer time** to a minute while
you are testing.

## Troubleshooting: repair issues

The integration checks its own setup and reports what it cannot fix by itself
under **Settings → Devices & services → Repairs**. Every issue disappears on its
own as soon as its cause is gone; the checks run once Home Assistant has started
and again whenever a person or a notify action changes.

**"No virtual tracker has been added yet"**
The integration is set up but has no virtual tracker, so nothing happens. Add one
under **Settings → Devices & services → Integrations → Virtual Presence Tracker →
Add virtual tracker**; the hint disappears with the first tracker.

**"The virtual tracker … is not assigned to a person"**
The tracker's `device_tracker` is not part of any person, so switching it on makes
nobody count as being at home. You see this for a tracker you added without
letting the integration create its person, for one that already had a person of
that name, and for one whose person was deleted later. Go to **Settings →
People**, open the person the tracker stands for (or add one, no login needed)
and pick `device_tracker.<name>` in its list of device trackers. If you do not
need the tracker any more, delete it on the integration's page.

**"The real person … has a virtual tracker attached"**
A person you configured as a *real* person carries one of the virtual trackers.
Switching that tracker on then looks like a real person coming home and resets
every virtual tracker. Either remove the tracker from that person in **Settings →
People**, or take the person out of the real persons with **Reconfigure** on the
integration's page.

**"… has no phone to be asked on"**
Somebody you picked under **Who is asked?** has no Companion App registered for
their user account, so the question cannot reach them. Install the Home Assistant
Companion App on that person's phone and sign in with **their own** user account,
or take them out of **Who is asked?** on the tracker. It is reported for every
tracker that sends anything at all — one that asks when the house empties, one
that reminds, or both. The questions themselves keep working through the event
entity and the actions.

**"The real person … no longer exists"**
A person you configured as a real person was deleted or renamed, so their presence
is no longer taken into account and the automatic reset may not happen any more.
Use **Reconfigure** on the integration's page and select your real persons again.

## Limitations and FAQ

**Is it only for children?**
No. A virtual tracker has a free-form name and no built-in role: it works for
a child, a grandparent, a babysitter, a guest, a carer — anybody who is at home
without a tracked device. Create one tracker per person, or one shared tracker for
a group ("Guests").

**Does the other person have to install anything?**
No. Nothing runs on their side, and nothing about them is tracked. For each
tracker the integration only stores whether it is on and since when, plus an open
prompt if there is one.

**Does it ask me whether somebody is at home?**
Yes, unless you switch that off for the tracker — see "Ask when the house
empties". Pick who is asked and the question goes to their phone by itself;
leave that empty and an automation of yours delivers it, with the example above
as a starting point. It also asks again when a tracker has been on for a long
time — see "Remind me when a tracker has been on for too long".

**Does it switch a forgotten tracker off by itself?**
No. It reminds you and leaves the decision to you: "no, switch off" on the
notification does it, and so does the switch. Nothing in this integration ever
changes a tracker without somebody saying so.

**Why is the tracker's `source_type` "router"?**
Home Assistant's device trackers have to declare where their information comes
from, and the list has no entry for "a human told me". `router` is the closest
match — a connection that is either there or not, without coordinates — and it is
what makes the person follow the tracker reliably.

**Can a person have both a virtual tracker and a real one?**
Yes. While the virtual tracker is switched on it wins, because Home Assistant
gives a connected tracker that reports a zone precedence over GPS. While it is off
it stays out of the way and the other tracker decides.

**Can I have more than one household?**
No. There is one configuration per Home Assistant instance, with any number of
trackers in it.

**Does renaming a tracker break my automations?**
No. Entity IDs and unique IDs are derived from internal IDs, not from the name, so
renaming only changes what is displayed.

## License

[MIT](LICENSE)

[release-badge]: https://img.shields.io/github/v/release/dabo53ck/virtual-presence-tracker-ha?include_prereleases&label=release
[release-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/releases
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[validate-badge]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/validate.yml/badge.svg
[validate-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/validate.yml
[tests-badge]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/tests.yml/badge.svg
[tests-url]: https://github.com/dabo53ck/virtual-presence-tracker-ha/actions/workflows/tests.yml
