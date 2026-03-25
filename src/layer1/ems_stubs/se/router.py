"""SE(상태 추정) FastAPI 라우터.

엔드포인트:
  GET /se/run             — 상태추정 실행
  GET /se/latest          — 최신 결과 조회
  GET /se/observability   — 관측성 분석
  GET /se/bad_data        — LNR 기반 Bad Data Detection 결과
  POST /se/pseudo_meas    — Pseudo-measurement 자동 추가 (계산 요청용)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.layer1.ems_stubs.se.estimator import StateEstimator
from src.shared.schemas.se import SEResult

router = APIRouter(prefix="/se", tags=["State Estimation"])

# 의존성 주입을 위한 전역 추정기 (app.py에서 설정)
_estimator: StateEstimator | None = None


def get_estimator() -> StateEstimator:
    """SE 추정기 의존성.

    Raises:
        RuntimeError: 추정기가 초기화되지 않은 경우.
    """
    if _estimator is None:
        raise RuntimeError("StateEstimator가 초기화되지 않았습니다.")
    return _estimator


def set_estimator(estimator: StateEstimator) -> None:
    """SE 추정기 설정 (앱 시작 시 호출).

    Args:
        estimator: 초기화된 StateEstimator 인스턴스.
    """
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


@router.get(
    "/bad_data",
    response_model=list[dict[str, Any]],
    summary="LNR 기반 Bad Data Detection",
    description=(
        "LNR(Largest Normalized Residual) 임계값(3σ)을 초과하는 "
        "나쁜 측정 데이터를 탐지하여 목록으로 반환한다. "
        "SE 실행(/se/run) 후 호출해야 유효한 결과를 반환한다. "
        "읽기 전용 엔드포인트."
    ),
)
def get_bad_data(est=Depends(get_estimator)) -> list[dict[str, Any]]:
    """LNR 기반 나쁜 데이터 탐지 결과 조회.

    Returns:
        나쁜 데이터 목록. 비어 있으면 bad data 없음.
    """
    return est.detect_bad_data()


@router.post(
    "/pseudo_meas",
    response_model=dict[str, Any],
    summary="Pseudo-measurement 자동 추가",
    description=(
        "관측성이 부족한 모선에 조류계산 기반 pseudo-measurement를 자동 추가한다. "
        "추가 후 /se/run을 다시 호출하면 관측성이 개선된 SE 결과를 얻을 수 있다. "
        "계산 요청 전용 POST — ops: 네임스페이스 데이터 변경 없음."
    ),
)
def add_pseudo_measurements(est=Depends(get_estimator)) -> dict[str, Any]:
    """Pseudo-measurement 자동 추가.

    Returns:
        추가된 pseudo-measurement 수와 대상 모선 정보.
    """
    try:
        obs_before = est.check_observability()
        added = est.add_pseudo_measurements()
        obs_after = est.check_observability()
        return {
            "added_count": added,
            "observable_ratio_before": obs_before["observable_ratio"],
            "observable_ratio_after": obs_after["observable_ratio"],
            "unobservable_before": len(obs_before["unobservable_buses"]),
            "unobservable_after": len(obs_after["unobservable_buses"]),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Pseudo-measurement 추가 실패: {exc}",
        ) from exc
