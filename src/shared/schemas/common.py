"""
공통 스키마 모듈 — AI-EMS v5.1 Phase 1
모든 API 응답의 기반이 되는 공유 스키마.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """UTC 현재 시각 반환."""
    return datetime.now(timezone.utc)


class Timestamp(BaseModel):
    """분석 기준 시각 및 데이터 출처 메타데이터.

    모든 응답에 snapshot_ts 필드를 포함하여 분석 기준 시각을 명시한다 (설계 원칙 5).
    """

    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="분석 기준 시각 (UTC). 모든 응답에 필수 포함.",
    )
    source: str = Field(
        description="데이터 출처 식별자 (예: 'pandapower', 'redis:ops:state', 'scada_sim').",
    )


class ErrorResponse(BaseModel):
    """API 오류 응답 스키마.

    모든 오류 응답에 사용되며 snapshot_ts 를 포함하여 시각을 추적한다.
    """

    code: int = Field(
        description="HTTP 상태 코드 또는 애플리케이션 오류 코드.",
    )
    message: str = Field(
        description="오류 요약 메시지.",
    )
    detail: Optional[str] = Field(
        default=None,
        description="상세 오류 설명 (선택). 디버그 정보 포함 가능.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="오류 발생 기준 시각 (UTC).",
    )
