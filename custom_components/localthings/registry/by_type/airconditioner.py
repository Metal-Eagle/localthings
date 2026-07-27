"""Air-conditioner device registry (Samsung ARTIK051_PRAC-class, issue #17).

The first device whose core controls surface as a single composite HA `climate`
entity (see capabilities/airconditioner.py and climate.py). Power/mode/temp/wind
are consumed by that entity rather than exposed as separate switches/selects, so
this registry includes *common.UNIVERSAL but deliberately NOT common.POWER --
on/off is the climate entity's HVACMode.OFF / TURN_ON/OFF. See common.POWER's
own comment in capabilities/common.py for why it's excluded.

Reuses dishwasher.DIAGNOSIS for /diagnosis/vs/0.
"""
from ..capabilities import airconditioner, common, dishwasher, ignored
from ._base import DeviceRegistry, _build

# /information/vs/0 is globally ignored (serial/model identity plumbing), but
# the AC exposes Software/Firmware version in its items[] -- model those here
# and drop the no-entity coverage entry so INFO is the sole cap on the href.
_AC_IGNORED = [c for c in ignored.IGNORED if c.href != '/information/vs/0']

REGISTRY = DeviceRegistry(
    name='airconditioner',
    capabilities=_build([
        *_AC_IGNORED,
        *common.UNIVERSAL,
        dishwasher.DIAGNOSIS,
        airconditioner.CLIMATE,
        airconditioner.AIR_PURIFY,
        airconditioner.AUTO_CLEAN,
        airconditioner.AIR_FILTER,
        airconditioner.AIR_QUALITY,
        airconditioner.INFO,
        airconditioner.DISPLAY_LIGHT,
        airconditioner.MUTE_ONCE,
        airconditioner.CURRENT_LIMIT,
        airconditioner.CURRENT_TEMPERATURE,
        airconditioner.CURRENT_TEMPERATURE_VS,
        airconditioner.HUMIDITY,
        *airconditioner.COVERAGE,
    ]),
)
