"""Microwave device registry (combi and plain microwaves, issues #66/#121).

Shares the oven board family's cavity/cook-cycle resource shape, so the
operational-state, door, cloud-connected, and quick-recipe-display
Capability objects are reused directly from oven.py rather than duplicated.
Cooking mode, setpoint, cavity power level, and lamp are genuinely
different for this family (different mode vocabulary, different setpoint
bounds, an extra powerLevel field, a differently-named lamp option) and are
defined fresh in capabilities/microwave.py -- see that module's docstring.
"""
from ..capabilities import common, ignored, microwave, oven
from ._base import DeviceRegistry, _build

REGISTRY = DeviceRegistry(
    name='microwave',
    capabilities=_build([
        *ignored.IGNORED,
        *common.UNIVERSAL,
        *common.POWER,
        microwave.MICROWAVE_CAVITY,
        microwave.MICROWAVE_SETPOINT,
        microwave.MICROWAVE_MODE,
        oven.OVEN_OPERATIONAL_STATE,
        oven.OVEN_DOOR,
        oven.OVEN_CONNECTED,
        oven.OVEN_RECIPE_COOK,
    ]),
)
