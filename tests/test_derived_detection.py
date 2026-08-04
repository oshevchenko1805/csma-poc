"""
Що саме рахується виявленням атаки.

Регресія на дефект, знайдений 4 серпня. `metrics/derived.py` рахував
`detected` як «існує будь-яка security-подія в прогоні»:

    detected = _first_ts(events, "security") is not None

Ні часового гейта, ні перевірки цілі. Через це передатакове хибне
спрацювання зараховувалось як виявлення атаки. У кампанії це дало вісім
хибних виявлень: A і B під detector_takeout+GPS показували 2/28 і 3/30,
хоча правильна відповідь — 0/28 і 0/30. Впізнати їх можна було по
порожньому MTTD: MTTD гейт мав, `detected` — ні.

Те саме правило вже було реалізоване двічі й правильно —
`metrics/analyzer.py` (target + час) і `campaign_report.mttd` (час), —
причому в останній стоїть коментар, який описує рівно цей дефект. Тобто
проблема була не в незнанні, а в тому, що визначення жило в трьох місцях
і розʼїхалось.

Ці тести фіксують поведінку, щоб воно не розʼїхалось знову.
"""

from __future__ import annotations

import pytest

from metrics.derived import attributable_ts, first_attack_detection_ts

T_ATTACK = 1000.0
TARGET = "uav_0"


def security(ts: float, target: str = TARGET, detector: str = "gps") -> dict:
    return {
        "source": "monitor_%s" % target,
        "event_type": "security",
        "timestamp": ts,
        "detector": detector,
        "target_uav": target,
        "severity": "high",
    }


def attack(ts: float = T_ATTACK, phase: str = "inject_start") -> dict:
    return {
        "source": "experiment_runner",
        "event_type": "attack",
        "timestamp": ts,
        "attack_type": "gps_spoofing",
        "target_uav": TARGET,
        "phase": phase,
    }


class TestPostAttackGate:
    """Подія до інʼєкції не є виявленням цієї інʼєкції."""

    def test_detection_after_attack_counts(self):
        events = [attack(), security(T_ATTACK + 2.72)]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) == \
            pytest.approx(T_ATTACK + 2.72)

    def test_detection_exactly_at_injection_counts(self):
        # Межа включна: command injection виявляється за 0.01 с, і
        # округлення не повинно викидати такий прогін.
        events = [attack(), security(T_ATTACK)]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) == \
            pytest.approx(T_ATTACK)

    def test_pre_attack_false_positive_is_not_detection(self):
        """Саме той випадок, що дав A 2/28 і B 3/30."""
        events = [security(T_ATTACK - 31.5, detector="heartbeat"), attack()]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) is None

    def test_pre_attack_fp_does_not_mask_a_later_real_detection(self):
        """Хибне спрацювання до атаки не має ні зараховуватись само, ні
        забирати на себе момент справжнього виявлення."""
        events = [
            security(T_ATTACK - 20.0, detector="heartbeat"),
            attack(),
            security(T_ATTACK + 3.3),
        ]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) == \
            pytest.approx(T_ATTACK + 3.3)

    def test_no_attack_timestamp_means_no_detection(self):
        events = [security(T_ATTACK + 1.0)]
        assert first_attack_detection_ts(events, None, TARGET) is None


class TestTargetGate:
    """Подія про інший борт не є виявленням атаки на цей борт."""

    def test_event_about_another_uav_is_ignored(self):
        events = [attack(), security(T_ATTACK + 1.0, target="uav_2")]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) is None

    def test_correct_target_found_past_a_wrong_one(self):
        events = [
            attack(),
            security(T_ATTACK + 1.0, target="uav_2"),
            security(T_ATTACK + 4.0, target=TARGET),
        ]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) == \
            pytest.approx(T_ATTACK + 4.0)

    def test_target_none_accepts_any_target(self):
        # Прогони, де ціль не записана, не мають мовчки ставати
        # «не виявлено»: гейт лишається часовим.
        events = [attack(), security(T_ATTACK + 1.0, target="uav_2")]
        assert first_attack_detection_ts(events, T_ATTACK, None) == \
            pytest.approx(T_ATTACK + 1.0)


class TestOnlyEarliestQualifying:
    def test_returns_first_qualifying_not_first_overall(self):
        events = [
            security(T_ATTACK - 5.0),
            attack(),
            security(T_ATTACK + 2.0),
            security(T_ATTACK + 9.0, detector="cross_check"),
        ]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) == \
            pytest.approx(T_ATTACK + 2.0)

    def test_non_security_events_never_qualify(self):
        events = [
            attack(),
            {"event_type": "isolation_announce", "timestamp": T_ATTACK + 1.0,
             "target_uav": TARGET},
            {"event_type": "recovery_ack", "timestamp": T_ATTACK + 1.1,
             "target_uav": TARGET},
        ]
        assert first_attack_detection_ts(events, T_ATTACK, TARGET) is None


def event(kind: str, ts: float, target: str = TARGET, **kw) -> dict:
    d = {"event_type": kind, "timestamp": ts, "target_uav": target}
    d.update(kw)
    return d


class TestAttributionGateOnAllEventTimes:
    """Той самий гейт для ізоляції та відновлення, не тільки для детекції.

    Регресія на другу половину дефекту. `detected` виправили 4 серпня,
    але `t_detect`, `t_isolate` і `t_last_rec` ще бралися по всьому
    прогону. Наслідки на корпусі: `time_to_isolation_s` мав викид
    59 119 мкс серед типових 52 мкс (звідси хибне «40-59 мкс» у тексті),
    а якір MTTR міг стояти ДО атаки і давав 70-127 с проти медіан
    51-54 с у десяти прогонах.
    """

    def test_pre_attack_isolation_is_not_the_anchor(self):
        """Головний випадок: хибна тривога до атаки оголосила ізоляцію."""
        events = [
            event("security", T_ATTACK - 30.0, detector="heartbeat"),
            event("isolation_announce", T_ATTACK - 30.0),
            attack(),
            event("security", T_ATTACK + 2.5),
            event("isolation_announce", T_ATTACK + 2.5),
        ]
        ts = attributable_ts(events, T_ATTACK, TARGET,
                             ("isolation_announce",))
        assert ts == pytest.approx(T_ATTACK + 2.5)
        # без гейта якір поїхав би на 30 с у минуле
        assert ts - T_ATTACK >= 0.0

    def test_time_to_isolation_stays_microseconds(self):
        """Ізоляція — внутрішньопроцесна операція; різниця між виявленням
        і оголошенням має лишатись мікросекундною, а не набирати
        десятки мілісекунд за рахунок передатакової події."""
        events = [
            event("isolation_announce", T_ATTACK - 59.0),
            attack(),
            event("security", T_ATTACK + 1.0),
            event("isolation_announce", T_ATTACK + 1.000052),
        ]
        t_det = attributable_ts(events, T_ATTACK, TARGET, ("security",))
        t_iso = attributable_ts(events, T_ATTACK, TARGET,
                                ("isolation_announce",))
        assert (t_iso - t_det) == pytest.approx(52e-6, abs=1e-9)

    def test_last_recovery_is_the_last_attributable_one(self):
        events = [
            event("recovery_ack", T_ATTACK - 10.0, action="mode_loiter"),
            attack(),
            event("recovery_request", T_ATTACK + 2.0, action="mode_loiter"),
            event("recovery_ack", T_ATTACK + 7.4, action="mode_loiter"),
        ]
        ts = attributable_ts(events, T_ATTACK, TARGET,
                             ("recovery_ack", "recovery_request"), last=True)
        assert ts == pytest.approx(T_ATTACK + 7.4)

    def test_total_response_time_cannot_go_negative(self):
        """Два відʼємні `total_response_time_s` у корпусі виникли саме
        так: відновлення після передатакової хибної тривоги, а відлік від
        інʼєкції."""
        events = [
            event("recovery_ack", T_ATTACK - 31.5, action="mode_loiter"),
            attack(),
        ]
        ts = attributable_ts(events, T_ATTACK, TARGET,
                             ("recovery_ack", "recovery_request"), last=True)
        assert ts is None

    def test_events_about_another_uav_are_excluded(self):
        events = [attack(), event("isolation_announce", T_ATTACK + 1.0,
                                  target="uav_2")]
        assert attributable_ts(events, T_ATTACK, TARGET,
                               ("isolation_announce",)) is None

    def test_detection_helper_delegates_to_the_same_gate(self):
        events = [event("security", T_ATTACK - 5.0), attack(),
                  event("security", T_ATTACK + 2.72)]
        assert (first_attack_detection_ts(events, T_ATTACK, TARGET)
                == attributable_ts(events, T_ATTACK, TARGET, ("security",)))


class TestAgreesWithMttd:
    """`detected` і MTTD мають узгоджуватись за побудовою.

    Розбіжність між ними і була підписом дефекту: у восьми прогонах
    `detected == True` при порожньому MTTD. Обидва тепер походять з
    одного правила, тому «виявлено, але MTTD немає» стало неможливим.
    """

    @pytest.mark.parametrize("events", [
        [attack(), security(T_ATTACK + 2.72)],
        [security(T_ATTACK - 10.0), attack()],
        [attack(), security(T_ATTACK + 1.0, target="uav_2")],
        [attack()],
    ])
    def test_detected_implies_a_finite_mttd(self, events):
        ts = first_attack_detection_ts(events, T_ATTACK, TARGET)
        if ts is None:
            return
        mttd = ts - T_ATTACK
        assert mttd >= 0.0
