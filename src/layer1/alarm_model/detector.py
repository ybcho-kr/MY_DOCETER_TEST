"""경보 탐지 엔진 — AI-EMS v5.1 Phase 1.

pandapower 계통 상태에서 전압·부하율·주파수 한계치 위반을 탐지하여
Alarm 스키마를 반환한다. 모든 수치는 pandapower 솔버값만 사용.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pandapower as pp
import structlog

from src.shared.domain import get_frequency_limits, get_voltage_limits
from src.shared.schemas.alarm import Alarm, AlarmSeverity, AlarmType

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class AlarmDetector:
    """계통 경보 탐지기.

    전압, 부하율, 주파수를 검사하여 한계치 위반 경보를 생성한다.
    Dead-band를 적용하여 미세 진동(chattering)을 방지한다.

    Dead-band 기준값은 하드코딩 금지 — 도메인 JSON에서 로드:
      - voltage_limits.json의 alarm_thresholds.voltage.*.deadband_pu (전압)
      - voltage_limits.json의 alarm_thresholds.line_loading.deadband_pct (부하율)
      - frequency_limits.json의 alarm_thresholds.deadband_hz (주파수)
    """

    def __init__(
        self,
        voltage_limits: dict[str, Any] | None = None,
        frequency_limits: dict[str, Any] | None = None,
    ) -> None:
        """경보 탐지기 초기화.

        Args:
            voltage_limits: 전압 한계치 딕셔너리. None이면 domain 데이터에서 로드.
            frequency_limits: 주파수 한계치 딕셔너리. None이면 domain 데이터에서 로드.
        """
        self._vlim: dict[str, Any] = voltage_limits or get_voltage_limits()
        self._flim: dict[str, Any] = frequency_limits or get_frequency_limits()

        # Dead-band 및 임계값을 도메인 JSON에서 로드 (하드코딩 금지 원칙 준수)
        _valarm = self._vlim.get("alarm_thresholds", {})
        _falarm = self._flim.get("alarm_thresholds", {})

        #: 전압 dead-band (pu) — voltage_limits.json alarm_thresholds.voltage.345kV.deadband_pu
        self.VOLTAGE_DEADBAND_PU: float = (
            _valarm.get("voltage", {}).get("345kV", {}).get("deadband_pu", 0.005)
        )
        #: 선로 부하율 dead-band (%) — voltage_limits.json alarm_thresholds.line_loading.deadband_pct
        self.LOADING_DEADBAND_PCT: float = (
            _valarm.get("line_loading", {}).get("deadband_pct", 2.0)
        )
        #: 선로 부하율 WARNING 임계값 (%) — voltage_limits.json alarm_thresholds.line_loading.warning_pct
        self.LOADING_WARNING_PCT: float = (
            _valarm.get("line_loading", {}).get("warning_pct", 80.0)
        )
        #: 선로 부하율 CRITICAL 임계값 (%) — voltage_limits.json alarm_thresholds.line_loading.critical_pct
        self.LOADING_CRITICAL_PCT: float = (
            _valarm.get("line_loading", {}).get("critical_pct", 100.0)
        )
        #: 주파수 dead-band (Hz) — frequency_limits.json alarm_thresholds.deadband_hz
        self.FREQUENCY_DEADBAND_HZ: float = (
            _falarm.get("deadband_hz", 0.01)
        )
        #: 주파수 WARNING 편차 (Hz) — frequency_limits.json alarm_thresholds.warning_deviation_hz
        self.FREQUENCY_WARNING_DEV_HZ: float = (
            _falarm.get("warning_deviation_hz", 0.2)
        )
        #: 주파수 CRITICAL 편차 (Hz) — frequency_limits.json alarm_thresholds.critical_deviation_hz
        self.FREQUENCY_CRITICAL_DEV_HZ: float = (
            _falarm.get("critical_deviation_hz", 0.5)
        )

    # ------------------------------------------------------------------
    # 전압 검사
    # ------------------------------------------------------------------

    def check_voltage(
        self, bus_id: int, voltage_pu: float, nominal_kv: float
    ) -> Alarm | None:
        """모선 전압 한계치 위반 검사.

        한국 계통 전압 조정목표(고시 제3조) 기준:
          345kV: 0.95~1.05 pu (target), 0.90~1.10 pu (operating)
          154kV: 0.95~1.05 pu (target), 0.90~1.10 pu (operating)
          66kV:  0.97~1.03 pu (target), 0.90~1.10 pu (operating)
          22.9kV:0.99~1.01 pu (target), 0.94~1.06 pu (operating)

        Dead-band: 실제 초과량이 deadband(0.005 pu)를 넘어야 경보 생성.

        Args:
            bus_id: pandapower 모선 인덱스.
            voltage_pu: pandapower 솔버 반환 전압 (pu).
            nominal_kv: 공칭 전압 (kV).

        Returns:
            Alarm 또는 None (한계치 이내).
        """
        limits = self._get_voltage_limits_for_kv(nominal_kv)
        if limits is None:
            return None

        target_min: float = limits["target_min_pu"]
        target_max: float = limits["target_max_pu"]
        op_min: float = limits["operating_min_pu"]
        op_max: float = limits["operating_max_pu"]
        db = self.VOLTAGE_DEADBAND_PU

        # dead-band 적용: 초과량이 deadband를 넘어야 경보 발생
        if voltage_pu < op_min - db:
            severity = AlarmSeverity.CRITICAL
            threshold = op_min
            direction = "하한"
        elif voltage_pu > op_max + db:
            severity = AlarmSeverity.CRITICAL
            threshold = op_max
            direction = "상한"
        elif voltage_pu < target_min - db:
            severity = AlarmSeverity.WARNING
            threshold = target_min
            direction = "조정목표 하한"
        elif voltage_pu > target_max + db:
            severity = AlarmSeverity.WARNING
            threshold = target_max
            direction = "조정목표 상한"
        else:
            return None

        return Alarm(
            alarm_id=_new_id(),
            alarm_type=AlarmType.LIMIT,
            severity=severity,
            element_type="bus",
            element_id=bus_id,
            message=(
                f"모선 {bus_id} ({nominal_kv}kV) 전압 {voltage_pu:.4f}pu "
                f"{direction} {threshold:.3f}pu 위반"
            ),
            value=voltage_pu,
            threshold=threshold,
            acknowledged=False,
            timestamp=_utcnow(),
        )

    # ------------------------------------------------------------------
    # 선로 부하율 검사
    # ------------------------------------------------------------------

    def check_loading(self, line_id: int, loading_pct: float) -> Alarm | None:
        """선로 부하율 한계치 위반 검사.

        기준:
          80% 이상: WARNING
          100% 이상: CRITICAL (N-1 기준 위반)

        Dead-band: 실제 초과량이 deadband(2%)를 넘어야 경보 생성.

        Args:
            line_id: pandapower 선로 인덱스.
            loading_pct: pandapower 솔버 반환 부하율 (%).

        Returns:
            Alarm 또는 None (한계치 이내).
        """
        db = self.LOADING_DEADBAND_PCT
        warning_threshold = self.LOADING_WARNING_PCT
        critical_threshold = self.LOADING_CRITICAL_PCT

        if loading_pct >= critical_threshold + db:
            severity = AlarmSeverity.CRITICAL
            threshold = critical_threshold
            label = "과부하(과전류)"
        elif loading_pct >= warning_threshold + db:
            severity = AlarmSeverity.WARNING
            threshold = warning_threshold
            label = "부하율 경고"
        else:
            return None

        return Alarm(
            alarm_id=_new_id(),
            alarm_type=AlarmType.LIMIT,
            severity=severity,
            element_type="line",
            element_id=line_id,
            message=(
                f"선로 {line_id} 부하율 {loading_pct:.1f}% {label} — "
                f"임계값 {threshold:.0f}% 초과"
            ),
            value=loading_pct,
            threshold=threshold,
            acknowledged=False,
            timestamp=_utcnow(),
        )

    # ------------------------------------------------------------------
    # 주파수 검사
    # ------------------------------------------------------------------

    def check_frequency(self, freq_hz: float) -> Alarm | None:
        """계통 주파수 한계치 위반 검사.

        기준 (고시 제4조):
          정상: 59.8~60.2 Hz
          경고: 정상 범위 경계 접근 (dead-band 이내 진입)
          CRITICAL: 단일고장 최소 허용 59.7Hz 미만 또는 60.3Hz 초과

        Dead-band: 0.01 Hz.

        Args:
            freq_hz: 현재 계통 주파수 (Hz).

        Returns:
            Alarm 또는 None (정상 범위 이내).
        """
        normal_lower: float = self._flim["normal_band"]["lower_hz"]  # 59.8
        normal_upper: float = self._flim["normal_band"]["upper_hz"]  # 60.2
        single_fault_min: float = self._flim["fault_limits"]["single_fault_min_hz"]  # 59.7
        nominal_hz: float = self._flim.get("nominal_hz", 60.0)
        db = self.FREQUENCY_DEADBAND_HZ

        # CRITICAL 상한 임계값: 공칭주파수 + critical_deviation_hz (기본 0.5 → 60.5Hz)
        # 단, 실제 운용에서는 60.3Hz(고시 제4조 운용범위 ±0.3) 기준이 적용됨
        # frequency_limits.json alarm_thresholds.critical_deviation_hz에서 로드
        critical_upper: float = nominal_hz + self.FREQUENCY_CRITICAL_DEV_HZ

        if freq_hz < single_fault_min - db:
            severity = AlarmSeverity.CRITICAL
            threshold = single_fault_min
            direction = "하한 임계"
        elif freq_hz > critical_upper + db:
            # nominal(60.0) + critical_deviation_hz(0.5) = 60.5 Hz 초과 시 CRITICAL
            severity = AlarmSeverity.CRITICAL
            threshold = critical_upper
            direction = "상한 임계"
        elif freq_hz < normal_lower - db:
            severity = AlarmSeverity.WARNING
            threshold = normal_lower
            direction = "정상 하한"
        elif freq_hz > normal_upper + db:
            severity = AlarmSeverity.WARNING
            threshold = normal_upper
            direction = "정상 상한"
        else:
            return None

        return Alarm(
            alarm_id=_new_id(),
            alarm_type=AlarmType.LIMIT,
            severity=severity,
            element_type="system",
            element_id=0,
            message=(
                f"계통 주파수 {freq_hz:.3f}Hz — {direction} {threshold:.2f}Hz 위반"
            ),
            value=freq_hz,
            threshold=threshold,
            acknowledged=False,
            timestamp=_utcnow(),
        )

    # ------------------------------------------------------------------
    # 전체 계통 스캔
    # ------------------------------------------------------------------

    def scan_network(self, net: pp.pandapowerNet) -> list[Alarm]:
        """계통 전체 전압·부하율 위반 탐지.

        모든 모선 전압과 선로 부하율을 검사하여 경보 목록을 반환한다.

        Args:
            net: pandapower 계통 모델 (조류계산 완료 상태).

        Returns:
            탐지된 Alarm 목록. 위반 없으면 빈 리스트.
        """
        alarms: list[Alarm] = []

        # 모선 전압 검사
        if not net.res_bus.empty:
            for idx, row in net.res_bus.iterrows():
                voltage_pu: float = float(row["vm_pu"])
                # net.bus에서 공칭 전압 취득
                nominal_kv: float = float(net.bus.at[idx, "vn_kv"])
                alarm = self.check_voltage(
                    bus_id=int(idx),
                    voltage_pu=voltage_pu,
                    nominal_kv=nominal_kv,
                )
                if alarm is not None:
                    alarms.append(alarm)

        # 선로 부하율 검사
        if not net.res_line.empty:
            for idx, row in net.res_line.iterrows():
                loading_pct: float = float(row["loading_percent"])
                alarm = self.check_loading(
                    line_id=int(idx),
                    loading_pct=loading_pct,
                )
                if alarm is not None:
                    alarms.append(alarm)

        logger.info(
            "alarm_scan_complete",
            total_alarms=len(alarms),
            bus_count=len(net.res_bus) if not net.res_bus.empty else 0,
            line_count=len(net.res_line) if not net.res_line.empty else 0,
        )
        return alarms

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _get_voltage_limits_for_kv(self, nominal_kv: float) -> dict[str, Any] | None:
        """공칭 전압에 해당하는 전압 한계치 딕셔너리 반환.

        Args:
            nominal_kv: 공칭 전압 (kV).

        Returns:
            voltage_standards.levels 딕셔너리 항목 또는 None.
        """
        levels: dict[str, Any] = self._vlim.get("voltage_standards", {}).get("levels", {})
        # 공칭 전압 kV → 딕셔너리 키 매핑
        kv_map: dict[float, str] = {
            765.0: "765kV",
            345.0: "345kV",
            154.0: "154kV",
            66.0: "66kV",
            22.9: "22.9kV",
        }
        # 근사값 매칭 (부동소수점 비교)
        for kv_val, key in kv_map.items():
            if abs(nominal_kv - kv_val) < 0.5 and key in levels:
                return levels[key]
        # 키가 없으면 가장 가까운 등급으로 fallback
        return None
