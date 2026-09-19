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

## Status

**Pre-release / in development.** Not usable yet — no entities are created at
this point. See [`docs/DESIGN.md`](docs/DESIGN.md) for the design and the
milestone plan.

## Requirements

Home Assistant 2025.3 or newer (the floor is re-checked before the first
release).

## License

[MIT](LICENSE)
