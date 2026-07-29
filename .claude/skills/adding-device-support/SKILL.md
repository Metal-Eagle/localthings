---
name: adding-device-support
description: >-
  Add or extend support for a Samsung OCF appliance in localthings from a
  /device/0 diagnostics dump. Use when a device-support issue lands, a device
  raises the "incomplete capability coverage" repair, a diagnostics JSON needs
  triaging, or you're mapping OCF resources to HA entities. Covers reading dumps,
  routing an unrecognized board family to a registry (oneUiVersion, modelNum
  board tokens, resource signatures),
  OCF-standard vs vendor hrefs, the diagnostic/config/normal entity taxonomy,
  preferring dynamic (device-reported) select options over hardcoded lists,
  ensuring every href is bound or ignored, and locking it in with a fixture +
  golden + test.
---

# Adding device support

localthings maps a Samsung appliance's OCF resources (`/device/0` dump) to Home
Assistant entities. Each resource `href` is handled by a `Capability` that
declares the entities it produces. This skill is the workflow for turning a new
dump into coverage.

## 1. Get the dump and see the gaps

A user's diagnostics download (`config_entry-localthings-*.json`) has, under
`data`:
- `resources`: `{href: rep}` — the parsed `/device/0` snapshot. **This is the
  source of truth**, not code comments.
- `unbound_hrefs`: resources that bound to no capability. The
  "incomplete capability coverage" repair fires whenever this is **non-empty or
  the device type is unrecognized** (`coordinator._update_coverage_gap_issue`).

Goal: make `unbound_hrefs` empty by **binding** the useful resources and
**ignoring** the noise — and surface every genuinely useful sensor/select/switch
along the way.

## 2. Compute coverage without Home Assistant

The `registry/` package is HA-free, so you can drive discovery directly (HA
isn't importable standalone because `localthings/__init__.py` pulls it in — stub
the package to skip that):

```python
import sys, types, json, importlib
cc = types.ModuleType('custom_components'); cc.__path__=['custom_components']; sys.modules['custom_components']=cc
lt = types.ModuleType('custom_components.localthings'); lt.__path__=['custom_components/localthings']; sys.modules['custom_components.localthings']=lt
by_type   = importlib.import_module('custom_components.localthings.registry.by_type')
discovery = importlib.import_module('custom_components.localthings.registry.discovery')
adapter   = importlib.import_module('custom_components.localthings.registry.adapter')

resources = json.load(open('dump.json'))['data']['resources']
info = resources.get('/information/vs/0', {})
one_ui = resources.get('/otninformation/vs/0', {}).get('swVersionInfo', {}).get('oneUiVersion', '')
# Same three-stage order the coordinator uses -- see §3.
reg = (
    (by_type.for_device(one_ui) if one_ui else None)
    or by_type.for_device_by_model(info.get('x.com.samsung.da.modelNum', ''),
                                   info.get('x.com.samsung.da.description', ''))
    or by_type.for_device_by_resources(resources)
)
unbound = []
bound = discovery.discover(resources, reg.capabilities, reg.pattern_capabilities, log=unbound.append)
state = adapter.flatten(bound, resources)   # {entity_key: value}
print('registry:', reg.name, 'unbound:', sorted(unbound))
print('state_keys:', sorted(state))
```

`discover()` binds caps (applies `rt_filter`/`match_fn`); `flatten()` applies
`exists_fn` and produces the final entity values. Use the same routine to
regenerate a golden.

## 3. Route the device to a registry — add a row, never a branch

If `for_device*` returns `None`, the device falls back to common capabilities
and loses roughly **half** its entities (measured across the fixture corpus:
843 of 1510 bound entities survive). So routing is the first thing to fix, and
`registry/by_type/__init__.py` is deliberately kept boring:

1. **`for_device(one_ui_version)`** — `/otninformation/vs/0`'s
   `swVersionInfo.oneUiVersion`, e.g. `'7.0 Dishwasher'`. The device naming
   its own type, so it's tried first — but only a minority of hardware
   reports it, so never assume it exists.
2. **`for_device_by_model(model_num, description)`** — the workhorse. Both
   fields come from `/information/vs/0`. Board-family tokens are matched
   against `modelNum` first, then `description`, then the fuzzy two-letter
   consumer-model prefix.
3. **`for_device_by_resources(resources)`** — last resort for boards that
   report no `/information/vs/0` at all. Needs a *distinctive* signature.

### Adding a board family

Almost always a one-line addition to `_BOARD_TOKEN_TO_KEY`:

```python
'VSKR': 'vacuum_station',   # issue #131 -- stick-vacuum clean station
```

Matching is on **whole tokens** of the model string, split on any run of
non-alphanumerics and upper-cased. That is what keeps this a table, and it
carries rules:

- **Never add a delimiter spelling.** `'_RAC_'` and `'-RAC-'` are the same
  entry, `RAC`. If you find yourself adding a second row for punctuation, the
  tokenizer already handled it.
- **Name the specific type, never the board family.** `DA-AC-` prefixes
  RAC/WAC/DHM/AIR alike — a bare `'AC'` row would swallow the dehumidifier
  and the air purifier. Same for `DA`, `KS`, `WM`, `TP1X`, `ARTIK051`.
  `TestBoardTokenTable` asserts these stay out.
- **Never add a token that can co-occur with another.** `_board_family_key`
  returns the first hit, which is only safe while no real model string
  contains two tokens naming different types.
  `TestBoardTokenAmbiguity` checks that invariant against every fixture, so a
  new dump exercises it automatically — if it fails, the answer is a narrower
  token, not a reordering.
- **Two-letter tokens are a last resort.** `'CT'` (legacy gas cooktop) is the
  only one, and it is loose enough to collide by accident.

Reach past the table only when the evidence isn't a board token:

- **Consumer-model prefix** (`_CONSUMER_PREFIX_TO_KEY`) — for washers, dryers
  and dishwashers, whose `modelNum` is the shared `DA_WM_` laundry board and
  whose real type is only in `description`'s trailing model code
  (`..._WA8000T`). Deliberately split on `_` only: widening it to `-` would
  read the dishwasher's `ADW-WW-RTL-24-AILITE` board segment as a `WW`
  washer. Consulted last because a two-letter prefix is the weakest evidence
  here — `WAC` (window AC) starts with `WA` (top-load washer).
- **Resource signature** (`for_device_by_resources`) — only when
  `/information/vs/0` is absent entirely. Require **two** independent shapes
  (e.g. `/oven/vs/0` present *and* a `MicroWave*` entry in `supportedModes`),
  never one, or an unrelated family's `/mode/vs/0` will match.

### If the model string identifies nothing

Check the diagnostics `identity` block before inventing a rule: it carries
`/oic/p` and `/oic/d`, which sit outside the `/device/0` dump.
`identity.device_types` is `/oic/d`'s `rt` — OCF's own device-type
declaration (`oic.d.airconditioner`). Nothing routes on it yet because no
captured dump has ever included it; if real hardware turns out to populate it,
it beats parsing board part numbers and this whole section shrinks. Note in
the issue when a dump has it.

### Sharing a registry vs adding one

Route a new family to an **existing** registry when its resource surface
matches (most AC board families do — verify by checking the dump binds with
zero unbound hrefs). Add a **new** registry only when the resources genuinely
differ: `vacuum_station` earned one because it shares no hrefs with anything
modelled; `microwave` split from `oven` over a distinct mode vocabulary,
setpoint bounds, and a `powerLevel` field.

## 4. OCF-standard vs vendor hrefs (`/x/0` vs `/x/vs/0`)

Samsung appliances run RT-OCF and often expose the **same state twice**:
- `/x/vs/0` — **vendor** resource, `x.com.samsung.da.*` fields.
- `/x/0` — **standard OCF** resource type (`oic.r.*`) with OCF's fixed field
  names. Confirmable against the OCF spec: `/power/0` `{value: bool}` is
  `oic.r.switch.binary`; `/operational/state/0` is `oic.r.operational.state`.

Newer firmware advertises both as Samsung migrates onto the OCF standard. **There
is no single "always prefer vs / always prefer non-vs" rule** — decide per
resource from the populated dump:
- **Both populated, same state** (power, kids-lock, remote): prefer the
  OCF-standard `/x/0`; fall back to `/x/vs/0` when `/x/0` is absent. Encode with
  a `match_fn` presence check — see `common.POWER_GENERIC` / `POWER_VS_FALLBACK`.
- **Only vendor populated** (`/energy/consumption/0` is often empty `{}`): use
  `/x/vs/0`.
- **Vendor is a superset** (`/operational/state/vs/0` adds fields the OCF one
  lacks): build on the vendor resource, ignore the OCF subset.

Course/cycle is **not** an OCF question — there's no standard course resource, so
`/course/vs/0` (and the `/st/*course/vs/0` re-encoding) are both vendor.

## 5. Entity taxonomy — the judgement call

For each field worth exposing, decide the entity kind and category
(`entity_category` on the descriptor):
- **Normal / primary** (no `entity_category`): the things a user acts on or
  watches — power switch, machine state, the cycle select, energy sensors.
- **`config`**: user-tunable settings — sound mode, door LED, wash temperature,
  buzzer. Shown under the device's Configuration section.
- **`diagnostic`**: read-only status/troubleshooting — alarms, diagnosis, job
  beginning status, last-operation source.

Also set `poll_tier` (`hot`/`warm`/`cold`) on the capability for how often it's
sub-polled between summary polls. Pick descriptor types from `entities.py`
(`SensorDesc`, `SelectDesc`, `SwitchDesc`, `NumberDesc`, `BinarySensorDesc`,
`TimeDesc`, `ButtonDesc`) — the class selects the HA platform.

**Don't guess.** If a field's meaning or write contract is unclear from the dump
(opaque encoded blobs, no supported-values list), leave it unbound so it surfaces
as a gap for a human, or ignore it with a documented reason — never invent an
entity on a hunch (`ignored.py`'s rule).

## 6. Select options: read them from the device, don't hardcode

A `SelectDesc`'s `options` should come from the device's own advertised list
whenever the resource carries one, not from a Python tuple typed in from a
single dump. Two dynamic forms already exist in the repo and should be
reached for first:
- `options_field='x.com.samsung.da.supportedModes'` (or whatever the
  resource's own supported-values field is called) — reads the live rep on
  the capability's own href. See `laundry.py`'s `buzzer_sound`/
  `finish_sound` (`options_field='supportedBuzzerSound'`/
  `'supportedFinishSound'`).
- `options=<callable>` — for option lists that live on a **different**
  resource than the select's own href (e.g. a course table keyed off a
  sibling href). See `laundry.cycle_select`'s `options=cycle_options`.

A static `options=(...)` tuple is a coverage gap waiting to happen: the next
dump from a different board generation will report modes/values the tuple
doesn't have, and both the HA options list *and* `write_fn`'s validation (if
it checks the same tuple) will silently reject values the device itself
advertises as supported. That's exactly what happened with `oven._OVEN_MODES`
in issue #138 — a hardcoded list rejected `AirFryer`/`Dehydrate`/
`SelfClean`/etc. even though the device's own `supportedModes` field listed
them. Reach for a static tuple only when the dump genuinely has no
supported-values field to read (e.g. the NV7000BS-class oven dump
`_OVEN_MODES` was inferred before any live oven dump existed — see that
module's docstring), and treat it as an interim best-guess rather than a
permanent design choice: migrate it to `options_field`/a callable the moment
a dump with a real supported-values list surfaces, instead of just adding
the new values to the static tuple.

## 7. Names and enum labels live in translations, never in Python

Descriptors have **no `name` field**. Every entity is named from the shipped
catalog, keyed by `translation_key` — which defaults to the descriptor's own
`key`. So adding `SensorDesc(key='filter_status', ...)` obliges you to add:

```json
"entity": { "sensor": { "filter_status": { "name": "Filter status" } } }
```

to `translations/en.json`. Skip it and the entity ships nameless;
`tests/test_translations.py` fails the build instead.

- **Sentence case** ("Filter status", not "Filter Status"), per HA's style
  guide — capitalize only proper nouns and Samsung feature names ("AI Energy
  Mode", "Storm Wash+").
- Set `translation_key` explicitly only to **share** one catalog entry across
  descriptors, or to point at a differently-named one. Two descriptors on the
  same platform with the same `key` already share an entry — intended for
  `common.py`'s OCF/vendor fallback pairs, a silent mislabel otherwise.
- Prefer HA's own vocabulary where it fits: a `device_class` gives you
  translated states for free (`binary_sensor` door/running, `sensor`
  timestamp/enum), so don't restate them.

Selects whose options are raw device codes (course/cycle, code-valued
settings) additionally need those codes labelled:
- `options`/`options_field` supply the **raw** codes; the catalog maps them.
- Add labels under `entity.select.<translation_key>.state.<code>`, code
  **lowercased** (e.g. `"16": "Cotton"`). `select.py` derives which values it
  normalizes from the catalog itself, so there is no Python list to keep in
  sync — a code with no entry simply renders as the raw code, which is the cue
  to identify and name it.

`translations/en.json` is the only place any of this lives: there is no
`strings.json` (Home Assistant doesn't read one from a custom integration) and
no `[%key:...%]` resolution (that's Core build tooling). Every other language
must mirror `en.json` key for key — also enforced by
`tests/test_translations.py`.

## 8. Coverage discipline: bound or ignored

Every href in the dump must resolve, or the repair fires. If a resource isn't
worth an entity, add it to `capabilities/ignored.py` (a no-entity `Capability`)
with a one-line reason. Add there only when it's **irrelevant plumbing**
(network/OTA/account housekeeping) or a **duplicate of state exposed via a
friendlier href**.

- **Global vs per-registry ignore:** `ignored.IGNORED` is folded into every
  registry. A global ignore **collides** (via `_build`) with any real capability
  that binds the same href in some family — e.g. `/course/vs/0` can't be globally
  ignored because washers bind it. When only one family should ignore an href
  that another binds, scope the ignore to that family's registry.

## 9. Reuse before writing new code

Check `common.py` (generic OCF: power, energy, alarms, water) and `laundry.py`
(shared washer/dryer/dishwasher: buzzer, job status, `cycle_select` + course
machinery) before adding a capability. Cross-family reuse is normal — the dryer
registry uses `fridge.FIRMWARE_UPDATE`; all three laundry families share
`laundry.cycle_select`. If two families hand-roll the same helper, hoist it to a
shared module rather than copying.

## 10. Lock it in

1. Add a **scrubbed** fixture `tests/fixtures/<type>_device.json`
   (`{"device0": [ {devcol rep}, {href, rep}, ... ]}`) — replace serials, MACs,
   and other PII with placeholders.
2. Generate `tests/fixtures/golden/<type>.json` (`{"state_keys": [...]}`) with
   the harness in §2.
3. Add the type to `test_golden_regression.py` and write a
   `test_<type>_capabilities.py` asserting **zero unbound hrefs** and that the
   expected entities exist (and any misleading ones are gated).
4. Run `pytest tests/ -q` — and re-run the golden tests for **other** device
   types after any change to `common.py`/`laundry.py`, since they share those.

The new fixture is picked up automatically by the corpus-wide checks (the
`all_device_fixtures` conftest fixture), including
`TestBoardTokenAmbiguity` — so a model string that collides with an existing
board token fails the build rather than silently mistyping someone's
appliance.

## Key files
- `registry/discovery.py` — `discover()`, unbound reporting, pattern caps.
- `registry/capability.py`, `registry/entities.py` — the `Capability` and
  descriptor shapes (`rt_filter`, `match_fn`, `exists_fn`, `rep_fn`, `write_fn`).
- `registry/capabilities/{common,laundry,fridge,...}.py` — capability defs.
- `registry/capabilities/ignored.py` — the ignore list + its philosophy.
- `registry/by_type/*.py` — per-device-type registries (what to include).
- `registry/registry.py` — the global unknown-device fallback + collision check.
- `tests/test_golden_regression.py`, `tests/fixtures/` — regression harness.
