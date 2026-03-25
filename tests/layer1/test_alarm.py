"""경보 모델 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 계통을 기반으로 AlarmDetector, AlarmSuppressor,
AlarmManager를 검증한다.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandapower as pp
import pandapower.networks as pn
import pytest

from src.layer1.alarm_model.detector import AlarmDetector
from src.layer1.alarm_model.manager import AlarmManager
from src.layer1.alarm_model.suppression import AlarmSuppressor
from src.shared.schemas.alarm import (
    Alarm,
    AlarmSeverity,
    AlarmSummary,
    AlarmType,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_alarm(
    element_type: str = "bus",
    element_id: int = 1,
    alarm_type: AlarmType = AlarmType.LIMIT,
    severity: AlarmSeverity = AlarmSeverity.WARNING,
) -> Alarm:
    """테스트용 Alarm 팩토리."""
    return Alarm(
        alarm_id="test-alarm-001",
        alarm_type=alarm_type,
        severity=severity,
        element_type=element_type,
        element_id=element_id,
        message="테스트 경보",
        value=1.1,
        threshold=1.05,
        acknowledged=False,
        timestamp=_utcnow(),
    )


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 계통 (조류계산 완료)."""
    n = pn.case14()
    pp.runpp(n, verbose=False)
    return n


@pytest.fixture
def detector() -> AlarmDetector:
    """AlarmDetector 인스턴스 (도메인 데이터 로드)."""
    return AlarmDetector()


@pytest.fixture
def suppressor() -> AlarmSuppressor:
    """AlarmSuppressor 인스턴스."""
    return AlarmSuppressor()


@pytest.fixture
def manager() -> AlarmManager:
    """AlarmManager 인스턴스."""
    return AlarmManager()


# ------------------------------------------------------------------
# AlarmType 열거형 테스트
# ------------------------------------------------------------------

class TestAlarmEnums:
    """경보 열거형 값 검증."""

    def test_alarm_types_enum(self) -> None:
        """AlarmType 4종 값이 모두 정의되어야 한다."""
        assert AlarmType.LIMIT == "LIMIT"
        assert AlarmType.STATE == "STATE"
        assert AlarmType.COMM == "COMM"
        assert AlarmType.QUALITY == "QUALITY"

    def test_alarm_severity_enum(self) -> None:
        """AlarmSeverity 4종 값이 모두 정의되어야 한다."""
        assert AlarmSeverity.INFO == "INFO"
        assert AlarmSeverity.WARNING == "WARNING"
        assert AlarmSeverity.CRITICAL == "CRITICAL"
        assert AlarmSeverity.EMERGENCY == "EMERGENCY"


# ------------------------------------------------------------------
# 전압 경보 탐지 테스트
# ------------------------------------------------------------------

class TestVoltageAlarm:
    """전압 경보 탐지 테스트."""

    def test_voltage_alarm_detection(self, detector: AlarmDetector) -> None:
        """범위 이탈 전압이 경보를 생성해야 한다 (345kV 상한 1.05 pu 초과)."""
        # 345kV target_max_pu = 1.05, deadband = 0.005
        # 1.06 pu > 1.05 + 0.005 = 1.055 → WARNING 발생
        alarm = detector.check_voltage(bus_id=1, voltage_pu=1.06, nominal_kv=345.0)
        assert alarm is not None, "범위 이탈 전압에서 경보가 생성되어야 한다"
        assert alarm.alarm_type == AlarmType.LIMIT
        assert alarm.severity in (AlarmSeverity.WARNING, AlarmSeverity.CRITICAL)
        assert alarm.element_type == "bus"
        assert alarm.element_id == 1
        assert alarm.value == pytest.approx(1.06)

    def test_voltage_alarm_lower_limit(self, detector: AlarmDetector) -> None:
        """하한 이탈 전압이 경보를 생성해야 한다 (345kV 0.94 pu)."""
        # 0.94 < 0.95 - 0.005 = 0.945 → WARNING 발생
        alarm = detector.check_voltage(bus_id=2, voltage_pu=0.94, nominal_kv=345.0)
        assert alarm is not None
        assert alarm.severity in (AlarmSeverity.WARNING, AlarmSeverity.CRITICAL)

    def test_voltage_within_deadband(self, detector: AlarmDetector) -> None:
        """Dead-band 이내 전압은 경보를 생성하면 안 된다 (345kV)."""
        # 345kV target_max_pu = 1.05, deadband = 0.005
        # 1.053 < 1.05 + 0.005 = 1.055 → 경보 없음
        alarm = detector.check_voltage(bus_id=3, voltage_pu=1.053, nominal_kv=345.0)
        assert alarm is None, (
            f"Dead-band 이내 전압(1.053 pu)은 경보 생성 불가, 실제: {alarm}"
        )

    def test_voltage_normal_range_no_alarm(self, detector: AlarmDetector) -> None:
        """정상 전압은 경보를 생성하면 안 된다."""
        alarm = detector.check_voltage(bus_id=4, voltage_pu=1.0, nominal_kv=345.0)
        assert alarm is None

    def test_voltage_critical_below_operating_min(self, detector: AlarmDetector) -> None:
        """운용 하한(0.90 pu) 이탈 시 CRITICAL 경보가 생성되어야 한다."""
        # 0.89 < 0.90 - 0.005 = 0.895 → CRITICAL
        alarm = detector.check_voltage(bus_id=5, voltage_pu=0.89, nominal_kv=345.0)
        assert alarm is not None
        assert alarm.severity == AlarmSeverity.CRITICAL


# ------------------------------------------------------------------
# 선로 부하율 경보 테스트
# ------------------------------------------------------------------

class TestLoadingAlarm:
    """선로 부하율 경보 탐지 테스트."""

    def test_loading_alarm_warning(self, detector: AlarmDetector) -> None:
        """80~100% 부하율 → WARNING 경보가 생성되어야 한다."""
        # 83% > 80 + 2 = 82 → WARNING
        alarm = detector.check_loading(line_id=1, loading_pct=83.0)
        assert alarm is not None, "83% 부하율에서 WARNING 경보가 생성되어야 한다"
        assert alarm.severity == AlarmSeverity.WARNING
        assert alarm.element_type == "line"
        assert alarm.element_id == 1

    def test_loading_alarm_critical(self, detector: AlarmDetector) -> None:
        """100% 초과 부하율 → CRITICAL 경보가 생성되어야 한다."""
        # 103% > 100 + 2 = 102 → CRITICAL
        alarm = detector.check_loading(line_id=2, loading_pct=103.0)
        assert alarm is not None, "103% 부하율에서 CRITICAL 경보가 생성되어야 한다"
        assert alarm.severity == AlarmSeverity.CRITICAL
        assert alarm.threshold == pytest.approx(100.0)

    def test_loading_within_deadband_no_alarm(self, detector: AlarmDetector) -> None:
        """Dead-band 이내 부하율은 경보를 생성하면 안 된다."""
        # 81% < 80 + 2 = 82 → 경보 없음
        alarm = detector.check_loading(line_id=3, loading_pct=81.0)
        assert alarm is None, f"Dead-band 이내 81%는 경보 생성 불가, 실제: {alarm}"

    def test_loading_normal_no_alarm(self, detector: AlarmDetector) -> None:
        """정상 부하율은 경보를 생성하면 안 된다."""
        alarm = detector.check_loading(line_id=4, loading_pct=50.0)
        assert alarm is None


# ------------------------------------------------------------------
# 주파수 경보 테스트
# ------------------------------------------------------------------

class TestFrequencyAlarm:
    """주파수 경보 탐지 테스트."""

    def test_frequency_alarm_below_normal(self, detector: AlarmDetector) -> None:
        """정상 하한(59.8 Hz) 미만 → WARNING 경보가 생성되어야 한다."""
        # 59.78 < 59.8 - 0.01 = 59.79 → WARNING
        alarm = detector.check_frequency(freq_hz=59.78)
        assert alarm is not None, "59.78 Hz에서 WARNING 경보가 생성되어야 한다"
        assert alarm.alarm_type == AlarmType.LIMIT
        assert alarm.severity == AlarmSeverity.WARNING

    def test_frequency_alarm_critical_below_single_fault(
        self, detector: AlarmDetector
    ) -> None:
        """단일고장 최소 허용(59.7 Hz) 미만 → CRITICAL 경보가 생성되어야 한다."""
        # 59.68 < 59.7 - 0.01 = 59.69 → CRITICAL
        alarm = detector.check_frequency(freq_hz=59.68)
        assert alarm is not None
        assert alarm.severity == AlarmSeverity.CRITICAL

    def test_frequency_alarm_above_normal(self, detector: AlarmDetector) -> None:
        """정상 상한(60.2 Hz) 초과 → WARNING 경보가 생성되어야 한다."""
        # 60.22 > 60.2 + 0.01 = 60.21 → WARNING
        alarm = detector.check_frequency(freq_hz=60.22)
        assert alarm is not None
        assert alarm.severity == AlarmSeverity.WARNING

    def test_frequency_within_deadband_no_alarm(self, detector: AlarmDetector) -> None:
        """Dead-band 이내 주파수는 경보를 생성하면 안 된다."""
        # 59.795 > 59.8 - 0.01 = 59.79 → dead-band 이내, 경보 없음
        alarm = detector.check_frequency(freq_hz=59.795)
        assert alarm is None, f"Dead-band 이내 59.795 Hz는 경보 생성 불가, 실제: {alarm}"

    def test_frequency_normal_no_alarm(self, detector: AlarmDetector) -> None:
        """정상 주파수(60.0 Hz)는 경보를 생성하면 안 된다."""
        alarm = detector.check_frequency(freq_hz=60.0)
        assert alarm is None


# ------------------------------------------------------------------
# 경보 억제 테스트
# ------------------------------------------------------------------

class TestAlarmSuppression:
    """AlarmSuppressor 억제 규칙 테스트."""

    def test_suppression_maintenance(self, suppressor: AlarmSuppressor) -> None:
        """유지보수 중인 설비의 경보는 억제되어야 한다."""
        alarm = _make_alarm(element_type="line", element_id=5)
        suppressor.add_maintenance("line", 5)
        assert suppressor.should_suppress(alarm) is True, (
            "유지보수 중인 line:5 경보가 억제되어야 한다"
        )
        suppressor.remove_maintenance("line", 5)
        assert suppressor.should_suppress(alarm) is False, (
            "유지보수 해제 후 경보가 통과되어야 한다"
        )

    def test_suppression_after_operation(self, suppressor: AlarmSuppressor) -> None:
        """스위칭 조작 후 30초 이내 경보는 억제되어야 한다."""
        alarm = _make_alarm(element_type="bus", element_id=10)
        suppressor.record_operation("bus", 10)
        assert suppressor.should_suppress(alarm) is True, (
            "조작 직후 bus:10 경보가 억제되어야 한다"
        )

    def test_suppression_not_suppressed_without_rule(
        self, suppressor: AlarmSuppressor
    ) -> None:
        """억제 조건이 없으면 경보가 통과되어야 한다."""
        alarm = _make_alarm(element_type="gen", element_id=99)
        assert suppressor.should_suppress(alarm) is False

    def test_maintenance_remove_clears_suppression(
        self, suppressor: AlarmSuppressor
    ) -> None:
        """유지보수 해제 후에는 억제가 적용되지 않아야 한다."""
        suppressor.add_maintenance("trafo", 7)
        suppressor.remove_maintenance("trafo", 7)
        alarm = _make_alarm(element_type="trafo", element_id=7)
        assert suppressor.should_suppress(alarm) is False


# ------------------------------------------------------------------
# 에스컬레이션 테스트
# ------------------------------------------------------------------

class TestAlarmEscalation:
    """경보 에스컬레이션 테스트."""

    def test_escalation_3_times(self, suppressor: AlarmSuppressor) -> None:
        """동일 경보가 10분 내 3회 이상 발생하면 심각도가 상향되어야 한다.

        WARNING → CRITICAL 에스컬레이션.
        """
        alarm = _make_alarm(
            element_type="bus",
            element_id=42,
            alarm_type=AlarmType.LIMIT,
            severity=AlarmSeverity.WARNING,
        )
        # 1, 2회 호출 — 아직 에스컬레이션 미발생
        result1 = suppressor.check_escalation(alarm)
        assert result1.severity == AlarmSeverity.WARNING

        result2 = suppressor.check_escalation(alarm)
        assert result2.severity == AlarmSeverity.WARNING

        # 3회: 에스컬레이션 발생
        result3 = suppressor.check_escalation(alarm)
        assert result3.severity == AlarmSeverity.CRITICAL, (
            f"3회째 동일 경보는 CRITICAL이어야 한다, 실제: {result3.severity}"
        )

    def test_escalation_info_to_warning(self, suppressor: AlarmSuppressor) -> None:
        """INFO 경보 3회 → WARNING으로 에스컬레이션."""
        alarm = _make_alarm(
            element_type="gen",
            element_id=55,
            alarm_type=AlarmType.STATE,
            severity=AlarmSeverity.INFO,
        )
        suppressor.check_escalation(alarm)
        suppressor.check_escalation(alarm)
        result = suppressor.check_escalation(alarm)
        assert result.severity == AlarmSeverity.WARNING

    def test_escalation_critical_stays_critical(
        self, suppressor: AlarmSuppressor
    ) -> None:
        """CRITICAL 경보는 더 이상 에스컬레이션되지 않아야 한다."""
        alarm = _make_alarm(
            element_type="line",
            element_id=66,
            alarm_type=AlarmType.LIMIT,
            severity=AlarmSeverity.CRITICAL,
        )
        for _ in range(5):
            result = suppressor.check_escalation(alarm)
        assert result.severity == AlarmSeverity.CRITICAL


# ------------------------------------------------------------------
# 계통 스캔 테스트
# ------------------------------------------------------------------

class TestNetworkScan:
    """AlarmDetector.scan_network() 테스트."""

    def test_scan_network(self, detector: AlarmDetector, net: pp.pandapowerNet) -> None:
        """계통 전체 스캔이 Alarm 목록을 반환해야 한다."""
        alarms = detector.scan_network(net)
        assert isinstance(alarms, list), "scan_network()는 list를 반환해야 한다"
        # 모든 항목이 Alarm 타입인지 검증
        for alarm in alarms:
            assert isinstance(alarm, Alarm), f"항목이 Alarm 타입이 아님: {type(alarm)}"

    def test_scan_network_alarm_fields(
        self, detector: AlarmDetector, net: pp.pandapowerNet
    ) -> None:
        """탐지된 경보가 필수 필드를 가져야 한다."""
        alarms = detector.scan_network(net)
        for alarm in alarms:
            assert alarm.alarm_id, "alarm_id가 비어있음"
            assert alarm.element_type in ("bus", "line", "gen", "trafo", "system")
            assert alarm.timestamp is not None


# ------------------------------------------------------------------
# AlarmManager 종단간 테스트
# ------------------------------------------------------------------

class TestAlarmManager:
    """AlarmManager 통합 테스트."""

    def test_alarm_manager_process(
        self, manager: AlarmManager, net: pp.pandapowerNet
    ) -> None:
        """process_network()가 AlarmSummary를 반환해야 한다."""
        summary = manager.process_network(net)
        assert isinstance(summary, AlarmSummary), (
            f"process_network()는 AlarmSummary를 반환해야 한다, 실제: {type(summary)}"
        )
        assert summary.total >= 0
        assert summary.unacknowledged >= 0
        assert summary.snapshot_ts is not None

    def test_alarm_manager_summary_fields(
        self, manager: AlarmManager, net: pp.pandapowerNet
    ) -> None:
        """AlarmSummary에 by_type, by_severity 필드가 있어야 한다."""
        summary = manager.process_network(net)
        # AlarmType 4종이 모두 key로 존재해야 함
        for alarm_type in AlarmType:
            assert alarm_type in summary.by_type, (
                f"by_type에 {alarm_type} 누락"
            )
        # AlarmSeverity 4종이 모두 key로 존재해야 함
        for severity in AlarmSeverity:
            assert severity in summary.by_severity, (
                f"by_severity에 {severity} 누락"
            )

    def test_alarm_manager_get_active_alarms(
        self, manager: AlarmManager, net: pp.pandapowerNet
    ) -> None:
        """get_active_alarms()가 처리된 경보 목록을 반환해야 한다."""
        manager.process_network(net)
        active = manager.get_active_alarms()
        assert isinstance(active, list)

    def test_alarm_manager_acknowledge(
        self, manager: AlarmManager, net: pp.pandapowerNet
    ) -> None:
        """acknowledge_alarm()이 올바르게 동작해야 한다."""
        manager.process_network(net)
        active = manager.get_active_alarms()

        if active:
            alarm_id = active[0].alarm_id
            result = manager.acknowledge_alarm(alarm_id)
            assert result is True, "유효한 alarm_id 확인 처리가 True를 반환해야 한다"
            # 확인 후 acknowledged=True 검증
            updated = [a for a in manager.get_active_alarms() if a.alarm_id == alarm_id]
            assert updated[0].acknowledged is True
        else:
            # 경보가 없는 경우: 잘못된 ID는 False 반환
            result = manager.acknowledge_alarm("nonexistent-id")
            assert result is False

    def test_alarm_manager_acknowledge_invalid_id(
        self, manager: AlarmManager
    ) -> None:
        """존재하지 않는 alarm_id 확인은 False를 반환해야 한다."""
        result = manager.acknowledge_alarm("invalid-alarm-id-xyz")
        assert result is False

    def test_alarm_manager_suppressed_alarms_excluded(
        self, net: pp.pandapowerNet
    ) -> None:
        """유지보수 억제가 적용된 경보는 활성 목록에서 제외되어야 한다."""
        manager = AlarmManager()
        # 모든 버스를 유지보수로 표시
        for bus_id in net.bus.index:
            manager.suppressor.add_maintenance("bus", int(bus_id))

        summary_before = manager.process_network(net)
        bus_alarms_after = [
            a for a in manager.get_active_alarms() if a.element_type == "bus"
        ]
        assert len(bus_alarms_after) == 0, (
            "유지보수 중인 모든 버스의 경보는 억제되어야 한다"
        )
