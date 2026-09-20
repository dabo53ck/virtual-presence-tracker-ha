# Virtual Presence Tracker

**Presence for household members without a phone, with prompts, auto-reset and an
"only virtual trackers home" sensor.**

A Home Assistant custom integration. You create any number of named virtual
trackers — one per person who has no phone to track (a child, a grandparent, a
carer, a guest). Each tracker is a `device_tracker` you attach to a `person`, so
`zone.home` counts that person and your existing "nobody home" automations keep
working unchanged. A switch per tracker toggles them home or away from a
dashboard, an NFC tag, a button or an automation.

**This is not a presence simulation.** Unlike "Home Alone"-style integrations
that fake activity while the house is empty, this one tracks people who really
are at home but carry no tracked device.

## What it does

- A **switch** per virtual tracker: on means "this person is at home".
- A **device tracker** per virtual tracker that follows the switch (`home` /
  `not_home`). This is the entity you assign to a person.
- A **binary sensor** "Only virtual trackers home" for the household: on when
  at least one virtual tracker is at home and none of your real persons is.
- **Automatic reset**: when the first real person comes back to an empty house,
  the trackers switch off again, so nobody stays "at home" for days by mistake.

## What it does not do

- It does not detect anything by itself. A virtual tracker only knows what you,
  an automation or (later) an answered prompt tell it.
- It does not simulate presence, and it does not change what your automations
  do — it only changes who counts as being at home.
- It does not manage your persons. Creating the person and assigning the
  tracker to it is a manual step (see below), and it is the step people forget.

## Requirements

Home Assistant **2026.6.0** or newer. The virtual trackers are built on
`BaseScannerEntity`, which first shipped with that release.

## Status

**Pre-release / in development.** The trackers, switches and the household
sensor work; the prompt on the last departure and the safety-net notification
are not built yet. See [`docs/DESIGN.md`](docs/DESIGN.md) for the design and the
milestone plan.

## Installation

The repository is still **private**, so it cannot be installed through HACS yet.
Until it is public, use the manual installation.

### HACS (once the repository is public)

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

Do **not** pick the person a virtual tracker belongs to. Switching that
tracker on would look like a real arrival and reset all your trackers.

### 2. Add a virtual tracker

The form for your first virtual tracker opens by itself once you have chosen
the real persons. Give the tracker a name — the name of the child, grandparent
or guest it stands for — and decide whether it should reset when a real person
comes home (see below).

If you close that form, the integration is set up but has nothing to do, and a
repair issue reminds you of it. You can add a tracker at any time under
**Settings → Devices & services → Integrations → Virtual Presence Tracker →
Add virtual tracker**, which is also where you add the second and every further
tracker. Renaming a tracker later does not change any entity IDs.

Each tracker gives you two entities, for a tracker named *Kid*:

| Entity | What it is for |
|---|---|
| `switch.kid_at_home` | The control. Turn it on when the kid is at home. |
| `device_tracker.kid` | Follows the switch. Assign this one to a person. |

### 3. Create a person and assign the tracker — required

This step is what makes everything else work. Without it the tracker is just an
entity nobody looks at.

1. **Settings → People → Add person.**
2. Enter the name, and leave the login option off — the person does not need a
   user account.
3. In the list of device trackers at the bottom of the dialog, pick the virtual
   tracker's entity, `device_tracker.kid`.
4. Save.

From now on `person.kid` is `home` while the switch is on, `zone.home` counts
the person, and every automation and dashboard card that asks "is anybody home"
sees them.

### 4. Use the switch

Put the switch on a dashboard, on an NFC tag at the front door, on a wall
button, or let an automation flip it. That is the whole daily routine.

## The "only virtual trackers home" sensor

`binary_sensor.only_virtual_trackers_home` is on when at least one virtual
tracker is at home while none of your real persons is — the situation that used
to break "nobody home" routines. Use it to make a routine behave differently
when the only person at home is one who cannot be tracked, for example to skip
the alarm or to keep the heating on.

The sensor belongs to the household, not to one tracker, and it has no device
of its own. You find it under **Settings → Devices & services → Entities** or
through the **Entities** link on the integration's page — not on a device page.
(If you set the integration up before this change, the sensor keeps the entity
ID it already had; only its device disappears.)

It has two attributes: `real_persons_home` (how many of your real persons are
at home) and `virtual_trackers_home` (the names of the trackers that are on).

Right after a Home Assistant restart the sensor is `unknown` until the state of
at least one real person is known. It reports what it knows rather than
guessing; automations should treat `unknown` as "do nothing".

## Reset when somebody real comes home

A virtual tracker that stays on for days is worse than no tracker at all, so
the default is to switch it off again when the household stops being empty:
the moment the number of real persons at home goes from **0 to 1**, every
tracker with the option **Reset when a real person comes home** switches off.

- Nothing happens when a *second* person arrives: if you are at home and
  somebody else comes back, a tracker that is on stays on.
- Nothing happens when people leave.
- Nothing happens right after a restart: a person whose state was never known
  before cannot trigger a reset.
- The option is per tracker. Turn it off for a tracker you always set by hand,
  for example one for a guest who stays a week.

## Troubleshooting: repair issues

The integration checks its own setup and reports what it cannot fix by itself
under **Settings → Devices & services → Repairs**. Every issue disappears on its
own as soon as its cause is gone; the checks run once Home Assistant has
started and again whenever a person changes.

**"No virtual tracker has been added yet"**
The integration is set up but has no virtual tracker, so nothing happens. Add
one under **Settings → Devices & services → Integrations → Virtual Presence
Tracker → Add virtual tracker**; the hint disappears with the first tracker.

**"The virtual tracker … is not assigned to a person"**
The tracker's `device_tracker` is not part of any person, so switching it on
makes nobody count as being at home. This is the step that is easy to forget.
Go to **Settings → People**, open the person the tracker stands for (or add one,
no login needed) and pick `device_tracker.<name>` in its list of device
trackers. If you do not need the tracker any more, delete it on the
integration's page.

**"The real person … has a virtual tracker attached"**
A person you configured as a *real* person carries one of the virtual trackers.
Switching that tracker on then looks like a real person coming home and resets
every virtual tracker. Either remove the tracker from that person in
**Settings → People**, or take the person out of the real persons with
**Reconfigure** on the integration's page.

**"The real person … no longer exists"**
A person you configured as a real person was deleted or renamed, so their
presence is no longer taken into account and the automatic reset may not
happen any more. Use **Reconfigure** on the integration's page and select your
real persons again.

## Limitations and FAQ

**Does it ask me whether somebody is at home?**
Not yet. The prompt on the last departure ("Is Kid home?" with Yes / No) is the
next milestone, as is the safety-net notification for a tracker that has been
on for very long.

**Why is the tracker's `source_type` "router"?**
Home Assistant's device trackers have to declare where their information comes
from, and the list has no entry for "a human told me". `router` is the closest
match — a connection that is either there or not, without coordinates — and it
is what makes the person follow the tracker reliably.

**Can a person have both a virtual tracker and a real one?**
Yes. While the virtual tracker is switched on it wins, because Home Assistant
gives a connected tracker that reports a zone precedence over GPS. While it is
off it stays out of the way and the other tracker decides.

**Can I have more than one household?**
No. There is one configuration per Home Assistant instance, with any number of
trackers in it.

**Does renaming a tracker break my automations?**
No. Entity IDs and unique IDs are derived from internal IDs, not from the name,
so renaming only changes what is displayed.

## License

[MIT](LICENSE)
