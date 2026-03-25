"""AGC FastAPI 라우터 — AI-EMS v5.1 Phase 1.

READ-ONLY 스텁. GET 엔드포인트만 제공.
POST/PUT/PATCH/DELETE 절대 금지 (설계 원칙 2: ops 네임스페이스 write 불가).
"""
from __future__ import annotations

from typing import Any

import pandapower.networks as pn
from fastapi import APIRouter, HTTPException, status

from src.layer1.ems_stubs.agc.controller import AGCController
from src.shared.schemas.agc import AGCStatus

router = APIRouter(prefix="/agc", tags=["AGC"])

# Phase 1 MDP: IEEE 14-bus를 기본 테스트 계통으로 사용
# 실제 운영 환경에서는 DI(Dependency Injection)로 net 주입
_default_net = pn.case14()
_controller = AGCController(net=_default_net, nominal_freq=60.0)


@router.get(
    "/status",
    response_model=AGCStatus,
    summary="AGC 상태 조회",
    description=(
        "현재 AGC(자동 발전 제어) 상태를 반환한다. "
        "주파수, ACE, 조정용량, 참여 발전기 수를 포함한다. "
        "읽기 전용 엔드포인트 — pandapower 솔버값만 반환."
    ),
)
def get_agc_status(freq_hz: float | None = None) -> AGCStatus:
    """AGC 현재 상태 조회.

    Args:
        freq_hz: 선택. 계통 주파수 직접 지정 (Hz). 미입력 시 pandapower net에서 추산.

    Returns:
        AGCStatus 스키마 인스턴스.
    """
    try:
        import pandapower as pp

        pp.runpp(_default_net, verbose=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"pandapower 조류계산 실패: {exc}",
        ) from exc

    return _controller.get_status(freq_hz=freq_hz)


@router.get(
    "/reserves",
    response_model=dict[str, Any],
    summary="예비력 현황 조회",
    description=(
        "예비력 5종 현황을 반환한다 (고시 제6조). "
        "주파수제어(5분), 초속응(1초), 1차(10초), 2차(10분), 3차(30분). "
        "읽기 전용 엔드포인트 — pandapower 솔버값만 반환."
    ),
)
def get_agc_reserves() -> dict[str, Any]:
    """예비력 5종 현황 조회.

    Returns:
        예비력 유형별 MW 현황 딕셔너리.
    """
    try:
        import pandapower as pp

        pp.runpp(_default_net, verbose=False)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"pandapower 조류계산 실패: {exc}",
        ) from exc

    return _controller.get_reserves()
