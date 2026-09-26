# Automations and actions

Full reference for the event entity and the actions of Virtual Presence Tracker.
Read this if you want to deliver the prompt or the reminder somewhere other than
a phone — a speaker, Telegram, a dashboard button — or react to them in your own
automations. For the everyday behavior, see the [README](../README.md).

The examples use a tracker named *Kid* on an English instance, so its switch is
`switch.kid_at_home` and its event entity `event.kid_questions`. Entity IDs
follow the language of your Home Assistant; look yours up under **Settings →
Devices & services → Entities** (see
[Add a virtual tracker](../README.md#2-add-a-virtual-tracker)).

Leave **Who is asked?** empty on a tracker and the integration sends nothing to
any phone. The prompt and the reminder still open, the event entity still
announces them and the actions still answer them, so your own automation is in
charge. Both ways combine: the event entity fires whether or not the built-in
notification goes out, so an extra announcement on a speaker is just another
automation.

## The event entity

`event.kid_questions` publishes everything that happens to the prompt and to the
reminder of that tracker. Its `event_type` is one of:

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

## The answer action

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

## The open action

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

## The reminder actions

The reminder has the same pair of actions:

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

Target the tracker's **At home** switch (or its device), as with the prompt;
the settings switches are not valid targets and say so.

**Open reminder** asks right now, without waiting for **Remind after** to
pass — it even works for a tracker whose interval is 0. It refuses, without
changing anything, if the tracker is **switched off** (there is nobody to
remind you about) or if a reminder for it is **already open**. **Answer
reminder** fails with "there is no open reminder" if nothing is waiting, so a
late answer cannot switch anything off by accident.

## Example: ask somewhere else

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

The same pattern works for the reminder: trigger on `reminder_started` and answer
with `answer_reminder`.

## How the timing works

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

## When the reminder comes

The counting starts when the tracker is switched on, and it starts again every
time somebody answers "still home" or lets a reminder run out. Switching the
tracker off ends it; switching it on starts it over. If you raise **Remind
after** the next reminder moves further away, and if you lower it below the time
the tracker has already been on, you are asked straight away — which is the
point of a safety net.

## After a restart

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

A reminder survives a restart too: it keeps the time it has left, or reports
`reminder_expired` if its time ran out while Home Assistant was off, or is
withdrawn (`reminder_cancelled`, reason `switched_off`) if the tracker was
switched off meanwhile. A tracker whose interval passed while Home Assistant was
down is asked about shortly after the start.
