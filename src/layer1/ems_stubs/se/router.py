"""SE(상태 추정) FastAPI 라우터.

엔드포인트:
  GET /se/run          — 상태추정 실행
  GET /se/latest       — 최신 결과 조회
  GET /se/observability — 관측성 분석
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.shared.schemas.se import SEResult

router = APIRouter(prefix="/se", tags=["State Estimation"])

# 의존성 주입을 위한 전역 추정기 (app.py에서 설정)
_estimator = None


def get_estimator():
    """SE 추정기 의존성."""
    if _estimator is None:
        raise RuntimeError("StateEstimator가 초기화되지 않았습니다.")
    return _estimator


def set_estimator(estimator) -> None:
    """SE 추정기 설정 (앱 시작 시 호출)."""
    global _estimator
    _estimator = estimator


@router.get("/run", response_model=SEResult)
def run_estimation(est=Depends(get_estimator)) -> SEResult:
    """상태 추정 실행 및 결과 반환."""
    return est.run_estimation()


@router.get("/latest", response_model=SEResult | None)
def get_latest(est=Depends(get_estimator)) -> SEResult | None:
    """최신 상태 추정 결과 조회. 미실행 시 null."""
    return est.get_latest()


@router.get("/observability")
def get_observability(est=Depends(get_estimator)) -> dict:
    """관측성 분석 결과 조회."""
    return est.check_observability()
