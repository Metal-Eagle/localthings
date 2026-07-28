"""Capabilities specific to the AirDresser family (Samsung DA_DF_A51-class,
issue #162).

This board reports no oneUiVersion and no /information/vs/0 token any
existing family routes on, so it gets its own device type -- but most of
the resources it exposes are already handled by the shared laundry
machinery:

  /washer/vs/0    -> AIR_DRESSER_SETTINGS (wrinkle_prevent only -- a
                      dedicated capability rather than reusing
                      dryer.DRYER_SETTINGS wholesale: this board's dump
                      never populates dryLevel/dryTime/dryerType at all,
                      and those are permanently-empty-not-just-absent
                      dryer-only fields on an AirDresser, not merely unset
                      ones, so binding them here would ship three sensors
                      that can never read anything on this device type)
  /course/vs/0    -> AIR_DRESSER_COURSE (cycle select). This board has no
                      /wm/editcourse/vs/0 at all, so cycle_options() falls
                      through entirely to its supportedOptions fallback --
                      confirmed against the issue #162 dump: header nibble
                      '0' + 10 self-indexed one-byte records
                      (01/02/04/03/05/1A/1B/1C/07/08), all distinct, current
                      selection 'Course_01' among them. Course names aren't
                      identified yet (no code->name mapping was reported),
                      so they render as their raw codes until named in
                      translations, same as dryer.py's unidentified codes.
  /diagnosis/vs/0 -> reuses dishwasher.DIAGNOSIS
"""
from ..capability import Capability
from ..entities import SwitchDesc
from .laundry import cycle_select


def _wrinkle_write(p, rep, href=None):
    if p not in ('On', 'Off'):
        return None
    return ['washer', 'vs', '0'], {'x.com.samsung.da.wrinklePrevent': p}


AIR_DRESSER_SETTINGS = Capability(
    href='/washer/vs/0',
    poll_tier='warm',
    entities=(
        SwitchDesc(key='wrinkle_prevent', field='x.com.samsung.da.wrinklePrevent',
                   icon='mdi:iron',
                   value_fn=lambda v: v == 'On',
                   write_fn=_wrinkle_write),
    ),
)

AIR_DRESSER_COURSE = Capability(
    href='/course/vs/0',
    entities=(
        cycle_select(translation_key='air_dresser_cycle', icon='mdi:tshirt-crew'),
    ),
)
