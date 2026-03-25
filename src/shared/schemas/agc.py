"""
자동 발전 제어(AGC, Automatic Generation Control) 스키마 모듈 — AI-EMS v5.1 Phase 1
계통 주파수 및 지역 제어 오차(ACE) 스키마.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AGCStatus(BaseModel):
    """AGC(자동 발전 제어) 상태 스키마.

    한국 계통 주파수 기준 (산업통상자원부고시 제2023-65호 제4조):
      - 정상 운용: 60Hz ±0.2Hz (59.8~60.2Hz)
      - 단일 고장 최소 허용: 59.7Hz
      - 연쇄 고장 최소 허용: 59.5Hz

    ACE(Area Control Error): 실제 순 교환량과 계획 순 교환량의 차이 (MW).
    ACE = (실제 전력 교환) - (계획 전력 교환) + 10×B×(f_actual - f_scheduled)
    """

    frequency_hz: float = Field(
        ge=58.0,
        le=62.0,
        description=(
            "계통 현재 주파수 (Hz). 한국 기준 60Hz. "
            "정상: ±0.2Hz, 단일고장 최소: 59.7Hz, 연쇄고장 최소: 59.5Hz. "
            "범위: 58.0~62.0Hz."
        ),
    )
    ace_mw: float = Field(
        description=(
            "지역 제어 오차 ACE (MW). "
            "양수: 발전 과잉 (주파수 상승 경향), 음수: 발전 부족 (주파수 하강 경향)."
        ),
    )
    model_type: str = Field(
        description=(
            "AGC 제어 모델 유형. "
            "'tie-line bias': 연계선 바이어스 제어 (한국 표준), "
            "'flat_frequency': 정주파수 제어."
        ),
    )
    total_regulation_mw: float = Field(
        ge=0,
        description="AGC 참여 발전기 전체 조정 가능 용량 합계 (MW).",
    )
    participating_units: int = Field(
        ge=0,
        description="AGC 참여 발전기 대수.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="AGC 상태 기준 시각 (UTC).",
    )
