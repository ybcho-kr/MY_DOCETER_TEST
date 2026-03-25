"""
상태 추정(State Estimation) 스키마 모듈 — AI-EMS v5.1 Phase 1
상태 추정 결과 스키마. pandapower 솔버 반환값 기반.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SEResult(BaseModel):
    """상태 추정(State Estimation) 결과 스키마.

    관측성 분석 및 잔차 검증 결과를 포함한다.
    LLM 수치 생성 절대 금지 — 모든 수치는 pandapower 솔버 반환값만 사용.
    """

    solved: bool = Field(
        description="상태 추정 수렴 여부. True: 수렴 성공, False: 발산 또는 관측성 부족.",
    )
    confidence_level: float = Field(
        ge=0,
        le=1.0,
        description="상태 추정 신뢰도 (0.0~1.0). 잔차 기반 계산.",
    )
    observable_ratio: float = Field(
        ge=0,
        le=1.0,
        description="관측 가능 모선 비율 (0.0~1.0). 1.0: 완전 관측성.",
    )
    unobservable_buses: List[int] = Field(
        description="관측 불가 모선 ID 목록. 완전 관측성 시 빈 리스트.",
    )
    iterations: int = Field(
        ge=0,
        description="상태 추정 반복 횟수.",
    )
    max_residual: float = Field(
        ge=0,
        description="최대 측정 잔차 (normalized). 3σ 초과 시 나쁜 데이터(bad data) 의심.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="상태 추정 기준 시각 (UTC).",
    )
