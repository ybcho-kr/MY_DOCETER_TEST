"""경보 억제 및 에스컬레이션 규칙 — AI-EMS v5.1 Phase 1.

유지보수 중 설비, 스위칭 직후, 반복 경보에 대한 억제/에스컬레이션 처리.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import DefaultDict

from src.shared.schemas.alarm import Alarm, AlarmSeverity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlarmSuppressor:
    """경보 억제기.

    두 가지 억제 규칙과 에스컬레이션 규칙을 적용한다:
      - Rule 1: 유지보수 중 설비 경보 억제
      - Rule 2: 스위칭 조작 후 30초 이내 경보 억제
      - Escalation: 동일 경보 10분 내 3회 이상 → 심각도 상향
    """

    #: 스위칭 조작 후 억제 시간 (초)
    OPERATION_SUPPRESS_SEC: int = 30
    #: 에스컬레이션 판정 시간 창 (분)
    ESCALATION_WINDOW_MIN: int = 10
    #: 에스컬레이션 발생 반복 횟수
    ESCALATION_COUNT: int = 3

    def __init__(self) -> None:
        """억제기 초기화."""
        # 유지보수 중인 설비 집합: {(element_type, element_id), ...}
        self._maintenance_elements: set[tuple[str, int]] = set()
        # 최근 스위칭 조작 시각: {(element_type, element_id): datetime}
        self._operation_timestamps: dict[tuple[str, int], datetime] = {}
        # 경보 발생 이력: {alarm_key: [datetime, ...]}
        # alarm_key = "{element_type}:{element_id}:{alarm_type}"
        self._alarm_history: DefaultDict[str, list[datetime]] = defaultdict(list)

    # ------------------------------------------------------------------
    # 유지보수 관리
    # ------------------------------------------------------------------

    def add_maintenance(self, element_type: str, element_id: int) -> None:
        """설비를 유지보수 상태로 표시.

        Args:
            element_type: 설비 유형 (예: 'bus', 'line', 'gen').
            element_id: pandapower 설비 인덱스.
        """
        self._maintenance_elements.add((element_type, element_id))

    def remove_maintenance(self, element_type: str, element_id: int) -> None:
        """설비의 유지보수 상태 해제.

        Args:
            element_type: 설비 유형.
            element_id: pandapower 설비 인덱스.
        """
        self._maintenance_elements.discard((element_type, element_id))

    # ------------------------------------------------------------------
    # 스위칭 조작 기록
    # ------------------------------------------------------------------

    def record_operation(self, element_type: str, element_id: int) -> None:
        """스위칭 조작 시각을 기록한다.

        조작 후 OPERATION_SUPPRESS_SEC(30초) 동안 해당 설비 경보가 억제된다.

        Args:
            element_type: 설비 유형.
            element_id: pandapower 설비 인덱스.
        """
        self._operation_timestamps[(element_type, element_id)] = _utcnow()

    # ------------------------------------------------------------------
    # 억제 판정
    # ------------------------------------------------------------------

    def should_suppress(self, alarm: Alarm) -> bool:
        """경보 억제 여부 판정.

        Rule 1: 설비가 유지보수 상태이면 억제.
        Rule 2: 조작 후 30초 이내이면 억제.

        Args:
            alarm: 판정 대상 Alarm.

        Returns:
            True이면 경보 억제, False이면 정상 처리.
        """
        key = (alarm.element_type, alarm.element_id)

        # Rule 1: 유지보수 억제
        if key in self._maintenance_elements:
            return True

        # Rule 2: 스위칭 조작 후 억제
        op_ts = self._operation_timestamps.get(key)
        if op_ts is not None:
            elapsed = (_utcnow() - op_ts).total_seconds()
            if elapsed <= self.OPERATION_SUPPRESS_SEC:
                return True

        return False

    # ------------------------------------------------------------------
    # 에스컬레이션
    # ------------------------------------------------------------------

    def check_escalation(self, alarm: Alarm) -> Alarm:
        """반복 경보 에스컬레이션 판정.

        동일 (element_type, element_id, alarm_type) 조합이
        ESCALATION_WINDOW_MIN(10분) 내 ESCALATION_COUNT(3회) 이상 발생하면
        심각도를 한 단계 상향한다.
          INFO → WARNING → CRITICAL (CRITICAL은 더 이상 상향 없음)

        경보 발생 이력은 이 메서드 호출 시 자동으로 기록된다.

        Args:
            alarm: 판정 대상 Alarm.

        Returns:
            에스컬레이션 적용(또는 미적용) 후 Alarm 인스턴스.
        """
        alarm_key = f"{alarm.element_type}:{alarm.element_id}:{alarm.alarm_type}"
        now = _utcnow()
        window = timedelta(minutes=self.ESCALATION_WINDOW_MIN)

        # 이력 갱신: 오래된 항목 제거 후 현재 시각 추가
        history = self._alarm_history[alarm_key]
        cutoff = now - window
        history[:] = [ts for ts in history if ts >= cutoff]
        history.append(now)

        # 에스컬레이션 기준 충족 여부 판정
        if len(history) >= self.ESCALATION_COUNT:
            new_severity = self._escalate_severity(alarm.severity)
            if new_severity != alarm.severity:
                # Pydantic v2: model_copy로 불변 객체 복사본 생성
                alarm = alarm.model_copy(update={"severity": new_severity})

        return alarm

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _escalate_severity(current: AlarmSeverity) -> AlarmSeverity:
        """심각도 한 단계 상향.

        Args:
            current: 현재 AlarmSeverity.

        Returns:
            상향된 AlarmSeverity. CRITICAL 이상은 그대로 반환.
        """
        escalation_map: dict[AlarmSeverity, AlarmSeverity] = {
            AlarmSeverity.INFO: AlarmSeverity.WARNING,
            AlarmSeverity.WARNING: AlarmSeverity.CRITICAL,
            AlarmSeverity.CRITICAL: AlarmSeverity.CRITICAL,
            AlarmSeverity.EMERGENCY: AlarmSeverity.EMERGENCY,
        }
        return escalation_map[current]
