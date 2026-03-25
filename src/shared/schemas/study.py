"""
해석(Study) 스키마 모듈 — AI-EMS v5.1 Phase 1
AI 해석 스터디 결과 및 단락 고장 해석 스키마.

중요: AI는 study: 네임스페이스에만 write 가능. ops: 네임스페이스 write 절대 금지.
(설계 원칙 2: ops/study 네임스페이스 격리)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudyResult(BaseModel):
    """AI 해석 스터디 결과 스키마.

    namespace는 반드시 'study' — AI는 ops: 네임스페이스에 write 불가.
    study_type에 따라 상세 결과는 별도 스키마(PowerFlowResult, ContingencyResult 등) 참조.
    """

    study_id: str = Field(
        description="스터디 고유 식별자 (UUID 기반).",
    )
    study_type: Literal["powerflow", "contingency", "vsa", "shortcircuit"] = Field(
        description=(
            "스터디 유형. "
            "powerflow: 조류 계산, contingency: N-1/N-2 예비, "
            "vsa: 전압 안정도, shortcircuit: 단락 고장."
        ),
    )
    namespace: Literal["study"] = Field(
        default="study",
        description=(
            "네임스페이스. 반드시 'study' 고정. "
            "AI는 ops: 네임스페이스에 절대 write 불가 (설계 원칙 2)."
        ),
    )
    completed: bool = Field(
        description="스터디 완료 여부. False: 진행 중 또는 오류.",
    )
    result_summary: str = Field(
        description="스터디 결과 요약 문자열 (운영자 가독성 중심).",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="스터디 중 발생한 경고 메시지 목록.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="스터디 기준 시각 (UTC).",
    )


class ShortCircuitResult(BaseModel):
    """단락 고장 해석 결과 스키마.

    ikss_ka: 초기 대칭 단락 전류 (kA). IEC 60909 표준.
    skss_mva: 초기 대칭 단락 용량 (MVA).
    fault_type:
      3ph: 3상 단락 (가장 심각), slg: 1선 지락 (가장 빈번),
      llg: 2선 지락, ll: 2선 단락.
    """

    bus_id: int = Field(
        ge=1,
        description="단락 고장 발생 모선 ID.",
    )
    fault_type: Literal["3ph", "slg", "llg", "ll"] = Field(
        description=(
            "고장 유형. "
            "3ph: 3상 단락, slg: 1선 지락, llg: 2선 지락, ll: 2선 단락."
        ),
    )
    ikss_ka: float = Field(
        ge=0,
        description="초기 대칭 단락 전류 (kA). IEC 60909 기준. LLM 수치 생성 절대 금지.",
    )
    skss_mva: float = Field(
        ge=0,
        description="초기 대칭 단락 용량 (MVA). ikss_ka × √3 × nominal_kv.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="단락 고장 해석 기준 시각 (UTC).",
    )
