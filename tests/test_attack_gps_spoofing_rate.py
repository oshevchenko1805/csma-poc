"""B1 item 5: optional spoof rate (SIM_GPS_OFF_R) for gps_spoofing.
H3_PREREGISTRATION.md "Attack": OFF_R written before OFF_N, both read
back, restored to OFF_N = 0 and OFF_R = 0.02. Default None = v1."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attacks.base import AttackContext
from attacks.gps_spoofing import GpsSpoofingInjector

N, R = "SIM_GPS_OFF_N", "SIM_GPS_OFF_R"
V1_KEYS = {"param", "fired", "spoofed_value", "original_value",
           "readback_end_of_window", "readback_after_restore",
           "readback_error", "injection_confirmed"}
# H3 levels: v0 = r * f * A, f = 30 Hz, A = 50 m
LEVELS = {"L30": 0.02, "L10": 0.006667, "L3": 0.002, "L1": 0.0006667}


class Writer:
    def __init__(self, params=None, fail_get=(), fail_set=()):
        self.params = dict(params or {N: 0.0, R: 0.02})
        self.fail_get, self.fail_set = set(fail_get), set(fail_set)
        self.log: list[tuple] = []

    async def get_param_float(self, name):
        self.log.append(("get", name))
        if name in self.fail_get:
            raise RuntimeError("get failed")
        return self.params.get(name, 0.0)

    async def set_param_float(self, name, value):
        self.log.append(("set", name, value))
        if name in self.fail_set:
            raise RuntimeError("set failed")
        self.params[name] = value


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def armed(inj, w):
    run(inj.arm(AttackContext(target_uav="uav_0", target_sysid=1,
                              log_dir=Path("/tmp"), param_writer=w)))
    return inj


def sets(w):
    return [(e[1], e[2]) for e in w.log if e[0] == "set"]


class TestDefaultIsV1:
    def test_no_rate_param_touched(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(), w)
        run(inj.fire())
        run(inj.cleanup())
        assert all(e[1] == N for e in w.log)
        assert inj.spoof_rate is None

    def test_evidence_keys_unchanged(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(), w)
        run(inj.fire())
        run(inj.cleanup())
        assert set(inj.injection_evidence()["gps_spoofing"]) == V1_KEYS


class TestValidation:
    @pytest.mark.parametrize("bad", [True, "0.02"])
    def test_type(self, bad):
        with pytest.raises(TypeError):
            GpsSpoofingInjector(spoof_rate=bad)

    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
    def test_range(self, bad):
        with pytest.raises(ValueError):
            GpsSpoofingInjector(spoof_rate=bad)

    def test_empty_rate_param(self):
        with pytest.raises(ValueError):
            GpsSpoofingInjector(spoof_rate=0.002, rate_param_name="")

    @pytest.mark.parametrize("level", sorted(LEVELS))
    def test_preregistered_levels_accepted(self, level):
        r = LEVELS[level]
        assert GpsSpoofingInjector(spoof_rate=r).spoof_rate == r
        v0 = r * 30 * 50
        assert v0 == pytest.approx(float(level[1:]), rel=1e-3)


class TestFireAndCleanup:
    def test_rate_written_before_target(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(spoof_rate=0.0006667), w)
        run(inj.fire())
        assert sets(w) == [(R, 0.0006667), (N, 50.0)]
        ev = inj.injection_evidence()["gps_spoofing"]
        assert ev["rate_original"] == 0.02
        assert ev["t_rate_set"] is not None and ev["t_target_set"] is not None
        assert ev["t_rate_set"] <= ev["t_target_set"]

    def test_cleanup_restores_target_then_rate_and_reads_back(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        run(inj.fire())
        w.log.clear()
        run(inj.cleanup())
        assert w.log == [("get", N), ("set", N, 0.0), ("get", N),
                         ("get", R), ("set", R, 0.02), ("get", R)]
        assert w.params == {N: 0.0, R: 0.02}
        ev = inj.injection_evidence()["gps_spoofing"]
        assert ev["injection_confirmed"] is True
        assert ev["rate_confirmed"] is True
        assert ev["rate_readback_end_of_window"] == 0.002
        assert ev["rate_readback_after_restore"] == 0.02
        assert ev["rate_restore_value"] == 0.02
        assert set(ev) >= V1_KEYS

    def test_rate_restored_even_if_target_write_fails(self):
        w = Writer(fail_set={N})
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        with pytest.raises(RuntimeError):
            run(inj.fire())
        run(inj.cleanup())
        assert w.params[R] == 0.02
        ev = inj.injection_evidence()["gps_spoofing"]
        assert ev["fired"] is False and ev["injection_confirmed"] is False
        assert ev["t_target_set"] is None

    def test_rate_write_failure_leaves_nothing_to_restore(self):
        w = Writer(fail_set={R})
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        with pytest.raises(RuntimeError):
            run(inj.fire())
        w.log.clear()
        run(inj.cleanup())
        assert w.log == []
        assert inj.injection_evidence()["gps_spoofing"]["rate_confirmed"] is False

    def test_rate_read_failure_is_recorded_not_fatal(self):
        w = Writer(fail_get={R})
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        run(inj.fire())
        run(inj.cleanup())
        ev = inj.injection_evidence()["gps_spoofing"]
        assert ev["rate_original"] is None
        assert ev["rate_confirmed"] is None
        assert "rate end" in ev["readback_error"]
        assert w.params[R] == 0.02   # restore still attempted

    def test_rate_restore_failure_swallowed(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        run(inj.fire())
        w.fail_set = {R}
        run(inj.cleanup())      # does not raise
        assert w.params[N] == 0.0

    def test_cleanup_without_fire_is_noop(self):
        w = Writer()
        inj = armed(GpsSpoofingInjector(spoof_rate=0.002), w)
        run(inj.cleanup())
        assert w.log == []
