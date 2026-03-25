"""
위상 처리(Topology Processing) 및 조류 계산 스키마 모듈 — AI-EMS v5.1 Phase 1
조류 계산 결과, N-1 예비 분석, 전압 안정도 분석 스키마.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PowerFlowResult(BaseModel):
    """조류 계산(Power Flow) 결과 스키마.

    pandapower runpp() 결과를 매핑. LLM 수치 생성 절대 금지.
    converged=False 이면 하위 필드는 참고값이므로 주의.
    """

    converged: bool = Field(
        description="조류 계산 수렴 여부. False 이면 결과값 신뢰 불가.",
    )
    iterations: int = Field(
        ge=0,
        description="Newton-Raphson 반복 횟수.",
    )
    max_vm_pu: float = Field(
        description="계통 전체 최대 모선 전압 (pu). 운용 상한 초과 시 과전압 경보.",
    )
    min_vm_pu: float = Field(
        description="계통 전체 최소 모선 전압 (pu). 운용 하한 미달 시 저전압 경보.",
    )
    max_loading_pct: float = Field(
        ge=0,
        description="계통 전체 최대 선로 부하율 (%). 100% 이상 과부하, 80% 이상 경고.",
    )
    total_p_gen_mw: float = Field(
        description="전체 발전 유효전력 합계 (MW).",
    )
    total_p_load_mw: float = Field(
        description="전체 부하 유효전력 합계 (MW).",
    )
    total_loss_mw: float = Field(
        ge=0,
        description="계통 전체 유효전력 손실 (MW). total_p_gen_mw - total_p_load_mw.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="조류 계산 기준 시각 (UTC).",
    )


class ContingencyCase(BaseModel):
    """단일 예비 케이스(N-1 또는 N-2) 정의 스키마.

    산업통상자원부고시 제2023-65호 제15조: 단일 설비 탈락 시 나머지 위반 없어야 함.
    """

    case_id: str = Field(
        description="예비 케이스 고유 식별자 (예: 'N1_LINE_001', 'N1_GEN_045').",
    )
    element_type: Literal["line", "trafo", "gen"] = Field(
        description="탈락 설비 유형. line: 선로, trafo: 변압기, gen: 발전기.",
    )
    element_id: int = Field(
        ge=0,
        description="탈락 설비 pandapower index (0 이상).",
    )
    description: str = Field(
        description="예비 케이스 설명 (예: '신서울-서울 154kV 1L 탈락').",
    )


class ContingencyResult(BaseModel):
    """N-1/N-2 예비 분석 결과 스키마.

    tier=1: N-1 (단일 고장), tier=2: N-2 (연쇄 고장).
    위반 항목은 violations 리스트에 element_type, element_id, violation_type, value 포함.
    """

    tier: Literal[1, 2] = Field(
        description="예비 분석 등급. 1: N-1, 2: N-2.",
    )
    contingencies: List[ContingencyCase] = Field(
        description="분석한 예비 케이스 목록.",
    )
    violations: List[Dict[str, Any]] = Field(
        description=(
            "위반 항목 목록. 각 항목: element_type, element_id, violation_type "
            "(voltage/loading/frequency), value, limit."
        ),
    )
    converged_count: int = Field(
        ge=0,
        description="수렴 성공 케이스 수.",
    )
    diverged_count: int = Field(
        ge=0,
        description="수렴 실패 케이스 수. 0 이상이면 계통 불안정 가능성.",
    )
    worst_voltage_pu: Optional[float] = Field(
        default=None,
        description="전체 예비 케이스 중 최악 모선 전압 (pu). 위반 없으면 None.",
    )
    worst_loading_pct: Optional[float] = Field(
        default=None,
        description="전체 예비 케이스 중 최악 선로 부하율 (%). 위반 없으면 None.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="예비 분석 기준 시각 (UTC).",
    )


class VSAResult(BaseModel):
    """전압 안정도 분석(Voltage Stability Analysis) 결과 스키마.

    P-V 곡선(nose curve) 기반 전압 안정도 여유도 계산.
    p_margin_mw: 현재 운전점에서 코 끝(nose point)까지의 유효전력 여유.
    """

    critical_bus_id: int = Field(
        ge=1,
        description="전압 안정도 한계 모선 ID (가장 취약한 모선).",
    )
    p_margin_mw: float = Field(
        description="유효전력 안정도 여유 (MW). 양수: 안정, 음수: 불안정.",
    )
    q_margin_mvar: float = Field(
        description="무효전력 안정도 여유 (Mvar). 양수: 안정, 음수: 불안정.",
    )
    nose_point_mw: float = Field(
        ge=0,
        description="P-V 곡선 코 끝 유효전력 (MW). 전압 붕괴 한계점.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="전압 안정도 분석 기준 시각 (UTC).",
    )
