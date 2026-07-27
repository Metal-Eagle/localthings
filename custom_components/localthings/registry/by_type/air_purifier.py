"""Air-purifier device registry.

Spans two board generations sharing this one registry (see
capabilities/air_purifier.py's module docstring for the per-href
match_fn discriminators that keep them from colliding):

- ARTIK051_TVTL-class (issue #56). Reports no oneUiVersion; resolved via
  for_device_by_model's '_TVTL_' modelNum token (see registry.py).
- TP1X_DA-AC-AIR-class (issue #130). Self-reports oneUiVersion "7.0 Air
  purifier", resolved via for_device(). Adds real fan-mode control plus
  display/HEPA-filter/pet-filter/sound resources the older family never
  reported; reuses airconditioner.DISPLAY_LIGHT and airconditioner.MUTE_ONCE
  for /light/vs/0 and /option/muteonce/vs/0, which are identical shapes on
  the shared DA-AC- board family.

Reuses dishwasher.DIAGNOSIS for /diagnosis/vs/0 (identical field/write
contract).
"""
from ..capabilities import air_purifier, airconditioner, common, dishwasher, ignored
from ._base import DeviceRegistry, _build

REGISTRY = DeviceRegistry(
    name='air_purifier',
    capabilities=_build([
        *ignored.IGNORED,
        *common.UNIVERSAL,
        *common.POWER,
        dishwasher.DIAGNOSIS,
        air_purifier.AIR_QUALITY,
        air_purifier.FILTER,
        air_purifier.DEVICE_ACTIVE,
        air_purifier.AIRFLOW_GENERIC,
        air_purifier.AIRFLOW_VS_FALLBACK,
        air_purifier.MODE,
        air_purifier.FAN,
        air_purifier.DISPLAY,
        air_purifier.HEPA_FILTER,
        air_purifier.PANEL_STATUS,
        air_purifier.PET_FILTER_ACTIVATION,
        air_purifier.SOUND_MODE,
        air_purifier.SOUND_OUTPUT,
        air_purifier.SOUND_VOLUME,
        airconditioner.DISPLAY_LIGHT,
        airconditioner.MUTE_ONCE,
        *air_purifier.COVERAGE,
    ]),
)
