"""
계통 설비 스키마 모듈 — AI-EMS v5.1 Phase 1
모선 전압, 선로 조류, 발전기 출력, 토폴로지 버전 스키마.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# 한국 계통 공칭 전압 등급 (kV)
_VALID_NOMINAL_KV: tuple[float, ...] = (765.0, 345.0, 154.0, 66.0, 22.9)


class BusVoltage(BaseModel):
    """모선 전압 스키마.

    전압 단위는 per unit (pu). 공칭 전압은 한국 계통 표준 등급만 허용.
    산업통상자원부고시 제2023-65호 기준: 345kV ±5%, 154kV 95~105%, 66kV 97~103%, 22.9kV 99~101%.
    """

    bus_id: int = Field(
        ge=1,
        description="모선 고유 식별자 (pandapower bus index, 1 이상).",
    )
    name: str = Field(
        description="모선 명칭 (예: '신서울345', 'SEOUL_345').",
    )
    voltage_pu: float = Field(
        gt=0,
        le=2.0,
        description="모선 전압 (per unit). pandapower 솔버 반환값만 사용. LLM 수치 생성 절대 금지.",
    )
    voltage_kv: float = Field(
        gt=0,
        description="모선 전압 (kV). voltage_pu × nominal_kv 로 계산.",
    )
    nominal_kv: float = Field(
        description="공칭 전압 (kV). 한국 계통 표준: 765, 345, 154, 66, 22.9 중 하나.",
    )
    zone: Optional[int] = Field(
        default=None,
        description="계통 구역 번호 (선택). PSS/E .raw 파일의 zone 필드.",
    )
    in_service: bool = Field(
        default=True,
        description="모선 서비스 여부. False 이면 정전 또는 유지보수 상태.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="분석 기준 시각 (UTC). 상태 추정 또는 조류 계산 기준 시각.",
    )

    @field_validator("nominal_kv")
    @classmethod
    def validate_nominal_kv(cls, v: float) -> float:
        if v not in _VALID_NOMINAL_KV:
            raise ValueError(
                f"nominal_kv must be one of {_VALID_NOMINAL_KV}, got {v}. "
                "한국 계통 표준 공칭 전압 등급만 허용."
            )
        return v


class LineLoading(BaseModel):
    """선로 조류 및 부하율 스키마.

    조류 단위: MW (유효전력), Mvar (무효전력).
    부하율: loading_pct (100% 이상 = 과부하, 경고 기준 80%).
    """

    line_id: int = Field(
        ge=0,
        description="선로 고유 식별자 (pandapower line index, 0 이상).",
    )
    from_bus: int = Field(
        ge=1,
        description="송전단 모선 ID.",
    )
    to_bus: int = Field(
        ge=1,
        description="수전단 모선 ID.",
    )
    loading_pct: float = Field(
        ge=0,
        description="선로 부하율 (%). 80% 경고, 100% 이상 과부하 (N-1 기준 위반).",
    )
    p_from_mw: float = Field(
        description="송전단 유효전력 조류 (MW). 양수: 송전 방향.",
    )
    q_from_mvar: float = Field(
        description="송전단 무효전력 조류 (Mvar). 양수: 송전 방향.",
    )
    rating_mva: float = Field(
        gt=0,
        description="선로 정격 용량 (MVA).",
    )
    in_service: bool = Field(
        default=True,
        description="선로 서비스 여부. False 이면 개방 또는 유지보수 상태.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="분석 기준 시각 (UTC). 조류 계산 기준 시각.",
    )


class GenDispatch(BaseModel):
    """발전기 급전 스키마.

    출력 단위: MW (유효전력), Mvar (무효전력).
    vm_pu: 발전기 단자 전압 지령 (pu).
    """

    gen_id: int = Field(
        ge=0,
        description="발전기 고유 식별자 (pandapower gen index, 0 이상).",
    )
    bus_id: int = Field(
        ge=1,
        description="발전기 연결 모선 ID.",
    )
    name: str = Field(
        description="발전기 명칭 (예: '신서울#1', 'SEOUL_G1').",
    )
    p_mw: float = Field(
        description="유효전력 출력 (MW). pandapower 솔버 반환값.",
    )
    q_mvar: float = Field(
        description="무효전력 출력 (Mvar). pandapower 솔버 반환값.",
    )
    p_max_mw: float = Field(
        gt=0,
        description="최대 유효전력 출력 한계 (MW).",
    )
    p_min_mw: float = Field(
        ge=0,
        description="최소 유효전력 출력 한계 (MW). 기저부하 또는 열병합 최소출력.",
    )
    vm_pu: float = Field(
        gt=0,
        le=1.5,
        description="발전기 단자 전압 지령 (pu). AVR 설정값.",
    )
    gen_type: str = Field(
        description="발전기 유형 (예: 'hydro', 'gas', 'steam', 'nuclear', 'solar', 'wind', 'ESS').",
    )
    in_service: bool = Field(
        default=True,
        description="발전기 서비스 여부. False 이면 정지 또는 유지보수 상태.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="분석 기준 시각 (UTC). 발전기 출력 기준 시각.",
    )


class TopologyVersion(BaseModel):
    """계통 토폴로지 버전 스키마.

    PSS/E .raw 파일 파싱 또는 토폴로지 프로세서 갱신 시 버전 업데이트.
    islands: 계통 분리 섬 수 (정상 = 1, 1 초과 = 분리 발생).
    """

    version: int = Field(
        ge=0,
        description="토폴로지 버전 번호 (0 이상, 단조증가).",
    )
    timestamp: datetime = Field(
        description="토폴로지 갱신 시각 (UTC). .raw 파일 로드 또는 스위칭 조작 시각.",
    )
    total_buses: int = Field(
        ge=0,
        description="전체 모선 수.",
    )
    total_lines: int = Field(
        ge=0,
        description="전체 선로 수 (변압기 포함 가능).",
    )
    total_gens: int = Field(
        ge=0,
        description="전체 발전기 수.",
    )
    islands: int = Field(
        default=1,
        ge=1,
        description="계통 분리 섬 수. 정상: 1. 1 초과 시 계통 분리 경보 발령.",
    )

    # Literal type alias to suppress mypy complaints about int Literal
    # islands is validated via ge=1 Field constraint
