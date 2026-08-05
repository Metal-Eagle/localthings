# AC filter-time counter reset: not solved

`registry/capabilities/airconditioner.py`'s `filter_time` sensor
(`FilterTime_<N>` option token, tenths of an hour) has no reset entity. This
is where the failed attempts to find one are kept, so the next attempt starts
from the evidence instead of from scratch. Not finding a mechanism is not the
same as it not existing.

## What the reset actually is

Samsung models it as a **command**, not a value write: capability
`custom.dustFilter`, command `resetDustFilter`, no arguments (implemented in
several SmartThings HA forks; not in the core integration). That reframes
every attempt below — nothing changes the counter by writing to it, because
the board zeroes it itself on receiving a command.

## Tried, all against a live unit, all failed

- `FilterTime_0` via the single-token options merge that works for every
  other setting on this href — accepted with no error, then discarded. Tried
  on two units in opposite power states to rule out the obvious confound:
  5595 → back to 5595 after 69s (powered off, alarm active), 1925 → back to
  1925 after 65s (actively cooling).
- A full `options[]` read-modify-write with `FilterTime_0` substituted,
  instead of the single-token merge — zero fields changed anywhere.
- A write to `/consumable/vs/0`, the board's own filter resource
  (`items[{name: FilterProgress, state: N}]`) — discarded. `/oic/res`
  declares that resource `oic.if.s` (read-only), which fits.
- `/actions/vs/0` (`x.com.samsung.da.actions`, `oic.if.a`) is the obvious
  local command channel but publishes no schema: GET returns `{}` on
  baseline and on `oic.if.a`, and five POSTs probing the shape (empty map,
  empty string, empty array, invalid value, items shape) all returned 4.00
  with an empty body — no echo of accepted field names, unlike the laundry
  firmware's `"Control fail, <...>"`. Guessed action names were deliberately
  not enumerated against a live appliance: an unknown vocabulary on a
  channel called "actions" can hold a factory reset next to the one we want.
- `/hass/state/vs/0` and `/hass/command/vs/0` (advertised in `/oic/res`, and
  `/opt/data/hass.db` exists in `/file/list`) → 4.04 on every interface, so
  unimplemented scaffolding on this firmware.
- `/file/transfer/vs/0` serves only `/mnt/usage.db`; selecting another path
  returns 4.05/4.00, so the firmware can't be pulled that way to read the
  action vocabulary out of it.
- `/rm/micomdata/vs/0` (channel toward the MICOM board the physical panel
  talks to) stays empty even after successfully enabling remote management.

## What the failures are not

Not a transport, permission, or cert problem: a control write of `rmState`
on `/rm/state/vs/0` was accepted (2.04 Changed, value held, restored
afterwards), and `FilterAlarmTime_` is written through the very same options
merge and kept. Writes work; this one value just isn't driven that way.

## Where to look next

- The `/actions/vs/0` action vocabulary from an independent source (a
  firmware image, or a capture of what the cloud sends the device).
- The IR path — the physical remote has a filter reset (Options → Filter
  Reset → SET), and IRremoteESP8266 decodes this AC family, though issue
  #1277's dump doesn't include that button.

## Evidence for the counter's direction and scale

Confirmed counting *up* (running time since last reset, not remaining time):
token 1710 matched the Samsung app's "171 hours 0 minutes" for the same
filter (pins the tenths-of-an-hour scale); seen rising while the unit ran
(171.0 → 171.5); and across two units on one site the `/alarms/vs/0` filter
alarm tracks the counter in the right direction — live (`FilterAlarm`,
`Created`) at `FilterTime_5595`, still the `FilterAlarm_OFF`/`Deleted`
placeholder at `FilterTime_1915`, matching the app's own 500-hour threshold
behavior. `FilterAlarmTime_` in the same options blob is that threshold (500
on every unit on record).

The entity key stays `filter_time` rather than `filter_time_elapsed`:
renaming it would change every existing unit's `entity_id`/`unique_id` for a
wording improvement only.
