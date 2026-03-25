"""TP(조류계산) FastAPI 라우터.

엔드포인트:
  POST /tp/powerflow    — 조류계산 실행
  POST /tp/contingency  — N-1 상정고장 분석
  POST /tp/vsa          — 전압 안정도 분석
  GET  /tp/violations   — 현재 위반사항 조회
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.shared.schemas.tp import (
    ContingencyCase,
    ContingencyResult,
    PowerFlowResult,
    VSAResult,
)

router = APIRouter(prefix="/tp", tags=["Topology Processing / Powerflow"])

# 의존성 주입용 전역 (app.py에서 설정)
_pf_engine = None
_ca_analyzer = None
_vsa_analyzer = None


def get_pf_engine():
    if _pf_engine is None:
        raise RuntimeError("PowerFlowEngine이 초기화되지 않았습니다.")
    return _pf_engine


def get_ca_analyzer():
    if _ca_analyzer is None:
        raise RuntimeError("ContingencyAnalyzer가 초기화되지 않았습니다.")
    return _ca_analyzer


def get_vsa_analyzer():
    if _vsa_analyzer is None:
        raise RuntimeError("VoltageStabilityAnalyzer가 초기화되지 않았습니다.")
    return _vsa_analyzer


def set_engines(pf_engine, ca_analyzer, vsa_analyzer) -> None:
    """TP 엔진 설정 (앱 시작 시 호출)."""
    global _pf_engine, _ca_analyzer, _vsa_analyzer
    _pf_engine = pf_engine
    _ca_analyzer = ca_analyzer
    _vsa_analyzer = vsa_analyzer


class ContingencyRequest(BaseModel):
    """N-1 분석 요청."""
    cases: list[ContingencyCase] | None = Field(
        default=None,
        description="분석할 케이스. None이면 자동 생성.",
    )
    use_tier: bool = Field(default=True, description="2-Tier 방식 사용 여부.")
    top_n: int = Field(default=20, ge=1, description="Tier-1 선별 건수.")


@router.post("/powerflow", response_model=PowerFlowResult)
def run_powerflow(engine=Depends(get_pf_engine)) -> PowerFlowResult:
    """조류계산 실행."""
    return engine.run()


@router.post("/contingency", response_model=ContingencyResult)
def run_contingency(
    req: ContingencyRequest | None = None,
    analyzer=Depends(get_ca_analyzer),
) -> ContingencyResult:
    """N-1 상정고장 분석."""
    if req is None:
        return analyzer.run_n1()
    return analyzer.run_n1(
        cases=req.cases,
        use_tier=req.use_tier,
        top_n=req.top_n,
    )


@router.post("/vsa", response_model=VSAResult)
def run_vsa(analyzer=Depends(get_vsa_analyzer)) -> VSAResult:
    """전압 안정도 분석."""
    return analyzer.run()


@router.get("/violations")
def get_violations(engine=Depends(get_pf_engine)) -> list[dict[str, Any]]:
    """현재 전압/열용량 위반사항 조회."""
    return engine.get_violations()
