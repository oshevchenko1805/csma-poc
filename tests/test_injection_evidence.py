"""Injection evidence for the stage-3 inclusion rule (review stage 3a-4)."""

from __future__ import annotations

import asyncio

from attacks.base import NullAttackInjector
from attacks.composite import SequentialAttackInjector
from attacks.gps_spoofing import GpsSpoofingInjector
from runners.experiment import RunResult
from tests.test_attack_gps_spoofing import FakeParamWriter, _ctx


def _flown(writer, **kw):
    inj = GpsSpoofingInjector(spoofed_value=50.0, **kw)
    asyncio.run(inj.arm(_ctx(writer=writer)))
    asyncio.run(inj.fire())
    asyncio.run(inj.cleanup())
    return inj


def _ev(inj):
    return inj.injection_evidence()["gps_spoofing"]


def test_confirmed_when_offset_held_to_window_end():
    w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
    ev = _ev(_flown(w))
    assert ev["injection_confirmed"] is True
    assert ev["readback_end_of_window"] == 50.0
    assert ev["readback_after_restore"] == 0.0
    assert ev["readback_error"] is None


def test_read_happens_before_restore_and_after_it():
    w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
    _flown(w)
    # fire: 1 get (baseline); cleanup: get, set(restore), get
    assert w.gets == ["SIM_GPS_OFF_N"] * 3
    assert w.sets == [("SIM_GPS_OFF_N", 50.0), ("SIM_GPS_OFF_N", 0.0)]


def test_fire_does_not_read_back():
    # Timing guard: fire() must stay one get + one set, as in v1.
    w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
    inj = GpsSpoofingInjector(spoofed_value=50.0)
    asyncio.run(inj.arm(_ctx(writer=w)))
    asyncio.run(inj.fire())
    assert len(w.gets) == 1 and len(w.sets) == 1


def test_not_confirmed_when_param_did_not_stick():
    class Ignoring(FakeParamWriter):
        async def set_param_float(self, name, value):
            self.sets.append((name, value))  # PX4 silently ignored it
    ev = _ev(_flown(Ignoring(params={"SIM_GPS_OFF_N": 0.0})))
    assert ev["injection_confirmed"] is False


def test_unknown_not_false_when_readback_fails():
    class NoReadInCleanup(FakeParamWriter):
        async def get_param_float(self, name):
            if self.sets:  # after the spoof was set
                raise RuntimeError("timeout")
            return await super().get_param_float(name)
    ev = _ev(_flown(NoReadInCleanup(params={"SIM_GPS_OFF_N": 0.0})))
    assert ev["injection_confirmed"] is None
    assert "end: timeout" in ev["readback_error"]


def test_never_fired_is_not_confirmed():
    inj = GpsSpoofingInjector()
    asyncio.run(inj.arm(_ctx(writer=FakeParamWriter())))
    assert _ev(inj)["injection_confirmed"] is False


def test_composite_merges_children():
    w = FakeParamWriter(params={"SIM_GPS_OFF_N": 0.0})
    comp = SequentialAttackInjector([NullAttackInjector(), GpsSpoofingInjector()])
    asyncio.run(comp.arm(_ctx(writer=w)))
    asyncio.run(comp.fire())
    asyncio.run(comp.cleanup())
    assert comp.injection_evidence()["gps_spoofing"]["injection_confirmed"] is True


def test_default_is_empty_and_summary_field_exists():
    assert NullAttackInjector().injection_evidence() == {}
    assert "attack_evidence" in RunResult.__dataclass_fields__
