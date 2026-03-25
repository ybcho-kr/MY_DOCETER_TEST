"""경보 관리자 — AI-EMS v5.1 Phase 1.

AlarmDetector + AlarmSuppressor를 결합하여 계통 전체 경보를 통합 관리한다.
"""
from __future__ import annotations

import pandapower as pp

from src.layer1.alarm_model.detector import AlarmDetector
from src.layer1.alarm_model.suppression import AlarmSuppressor
from src.shared.schemas.alarm import Alarm, AlarmSeverity, AlarmSummary, AlarmType


class AlarmManager:
    """경보 통합 관리자.

    탐지 → 억제 → 에스컬레이션 → 활성 경보 목록 유지 파이프라인.
    """

    def __init__(self) -> None:
        """경보 관리자 초기화."""
        self.detector = AlarmDetector()
        self.suppressor = AlarmSuppressor()
        self._active_alarms: list[Alarm] = []

    # ------------------------------------------------------------------
    # 계통 처리
    # ------------------------------------------------------------------

    def process_network(self, net: pp.pandapowerNet) -> AlarmSummary:
        """계통 경보 전체 처리 파이프라인.

        1. detector.scan_network() 로 위반 탐지
        2. 각 경보에 억제 / 에스컬레이션 적용
        3. 활성 경보 목록 갱신
        4. AlarmSummary 반환

        Args:
            net: pandapower 계통 모델 (조류계산 완료 상태).

        Returns:
            AlarmSummary 스키마 인스턴스.
        """
        raw_alarms = self.detector.scan_network(net)

        processed: list[Alarm] = []
        for alarm in raw_alarms:
            # 억제 판정
            if self.suppressor.should_suppress(alarm):
                continue
            # 에스컬레이션 판정
            alarm = self.suppressor.check_escalation(alarm)
            processed.append(alarm)

        self._active_alarms = processed
        return self._build_summary(processed)

    # ------------------------------------------------------------------
    # 활성 경보 조회
    # ------------------------------------------------------------------

    def get_active_alarms(self) -> list[Alarm]:
        """현재 활성 경보 목록 반환.

        Returns:
            활성 Alarm 목록. process_network() 호출 전에는 빈 리스트.
        """
        return list(self._active_alarms)

    # ------------------------------------------------------------------
    # 경보 확인 처리
    # ------------------------------------------------------------------

    def acknowledge_alarm(self, alarm_id: str) -> bool:
        """경보 확인(ACK) 처리.

        Args:
            alarm_id: 확인 처리할 경보 ID.

        Returns:
            True: 경보 찾아서 ACK 처리 완료. False: 해당 ID 없음.
        """
        for i, alarm in enumerate(self._active_alarms):
            if alarm.alarm_id == alarm_id:
                # Pydantic v2 불변 모델 → model_copy로 갱신
                self._active_alarms[i] = alarm.model_copy(update={"acknowledged": True})
                return True
        return False

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(alarms: list[Alarm]) -> AlarmSummary:
        """경보 목록으로 AlarmSummary 생성.

        Args:
            alarms: 처리된 Alarm 목록.

        Returns:
            AlarmSummary 스키마 인스턴스.
        """
        by_type: dict[AlarmType, int] = {t: 0 for t in AlarmType}
        by_severity: dict[AlarmSeverity, int] = {s: 0 for s in AlarmSeverity}
        unacked = 0

        for alarm in alarms:
            by_type[alarm.alarm_type] += 1
            by_severity[alarm.severity] += 1
            if not alarm.acknowledged:
                unacked += 1

        return AlarmSummary(
            total=len(alarms),
            by_type=by_type,
            by_severity=by_severity,
            unacknowledged=unacked,
        )
