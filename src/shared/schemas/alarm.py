"""
경보(Alarm) 스키마 모듈 — AI-EMS v5.1 Phase 1
계통 운영 경보 유형, 심각도, 경보 개별/요약 스키마.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlarmType(str, Enum):
    """경보 유형 열거형.

    - LIMIT: 한계치 초과 경보 (전압, 부하율, 주파수 등)
    - STATE: 상태 변화 경보 (차단기 트립, 선로 탈락 등)
    - COMM: 통신 이상 경보 (SCADA 데이터 수신 불가 등)
    - QUALITY: 데이터 품질 경보 (나쁜 데이터, 스테일 데이터 등)
    """

    LIMIT = "LIMIT"
    STATE = "STATE"
    COMM = "COMM"
    QUALITY = "QUALITY"


class AlarmSeverity(str, Enum):
    """경보 심각도 열거형.

    - INFO: 정보성 이벤트 (상태 변화 기록)
    - WARNING: 주의 (한계치 80% 접근 등)
    - CRITICAL: 위험 (한계치 초과, N-1 위반 등)
    - EMERGENCY: 긴급 (주파수 이탈, 연쇄 고장 등)
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class Alarm(BaseModel):
    """개별 경보 스키마.

    경보 발생 시 alarm_id로 추적하며, HITL 대상 경보는 운영자 승인 필수.
    acknowledged=False 경보는 운영자 확인 대기 상태.
    """

    alarm_id: str = Field(
        description="경보 고유 식별자 (UUID 또는 타임스탬프 기반 ID).",
    )
    alarm_type: AlarmType = Field(
        description="경보 유형. LIMIT/STATE/COMM/QUALITY 중 하나.",
    )
    severity: AlarmSeverity = Field(
        description="경보 심각도. INFO/WARNING/CRITICAL/EMERGENCY 중 하나.",
    )
    element_type: str = Field(
        description="경보 대상 설비 유형 (예: 'bus', 'line', 'gen', 'trafo').",
    )
    element_id: int = Field(
        description="경보 대상 설비 pandapower index.",
    )
    message: str = Field(
        description="경보 메시지 (예: '신서울345 모선 전압 1.06pu 상한 초과').",
    )
    value: Optional[float] = Field(
        default=None,
        description="경보 트리거 측정값 (해당하는 경우). 예: 전압(pu), 부하율(%), 주파수(Hz).",
    )
    threshold: Optional[float] = Field(
        default=None,
        description="경보 한계치 (해당하는 경우). value와 동일 단위.",
    )
    acknowledged: bool = Field(
        default=False,
        description="운영자 확인 여부. False: 미확인(대기), True: 확인 완료.",
    )
    timestamp: datetime = Field(
        description="경보 발생 시각 (UTC).",
    )


class AlarmSummary(BaseModel):
    """경보 요약 스키마.

    현재 활성 경보의 유형별 및 심각도별 집계.
    운영자 대시보드 상단 경보 현황 패널에 사용.
    """

    total: int = Field(
        ge=0,
        description="전체 활성 경보 수.",
    )
    by_type: Dict[AlarmType, int] = Field(
        description="유형별 경보 수 (AlarmType → 건수).",
    )
    by_severity: Dict[AlarmSeverity, int] = Field(
        description="심각도별 경보 수 (AlarmSeverity → 건수).",
    )
    unacknowledged: int = Field(
        ge=0,
        description="미확인 경보 수. 0이면 모든 경보 확인 완료.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="경보 요약 기준 시각 (UTC).",
    )
