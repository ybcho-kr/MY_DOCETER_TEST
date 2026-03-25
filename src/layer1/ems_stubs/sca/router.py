"""SCA(단락전류 분석) FastAPI 라우터 — AI-EMS v5.1 Phase 1.

READ-ONLY 엔드포인트만 제공. 계산 요청(POST)도 데이터 변경 없이
pandapower 솔버를 실행하여 결과를 반환하는 것에 한정.

엔드포인트:
  POST /sca/run        — 단일 모선 단락전류 계산 (계산 요청용)
  GET  /sca/bus/{id}   — 특정 모선 단락전류 조회
  POST /sca/all        — 전체 모선 단락전류 일괄 계산
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.layer1.ems_stubs.sca.calculator import ShortCircuitCalculator
from src.shared.schemas.study import ShortCircuitResult

router = APIRouter(prefix="/sca", tags=["SCA (단락전류 분석)"])

# 의존성 주입용 전역 계산기 (app.py에서 설정)
_calculator: ShortCircuitCalculator | None = None


def get_calculator() -> ShortCircuitCalculator:
    """SCA 계산기 의존성.

    Raises:
        RuntimeError: 계산기가 초기화되지 않은 경우.
    """
    if _calculator is None:
        raise RuntimeError(
            "ShortCircuitCalculator가 초기화되지 않았습니다. "
            "app.py의 lifespan에서 set_calculator()를 호출하세요."
        )
    return _calculator


def set_calculator(calculator: ShortCircuitCalculator) -> None:
    """SCA 계산기 설정 (앱 시작 시 호출).

    Args:
        calculator: 초기화된 ShortCircuitCalculator 인스턴스.
    """
    global _calculator
    _calculator = calculator


# ──────────────────────────────────────────────
# 요청 스키마
# ──────────────────────────────────────────────

class ShortCircuitRequest(BaseModel):
    """단락전류 계산 요청 스키마."""

    bus_id: int = Field(
        ge=0,
        description="단락 고장 발생 모선 ID (pandapower bus index).",
    )
    fault_type: Literal["3ph", "slg", "llg", "ll"] = Field(
        default="3ph",
        description=(
            "고장 유형. "
            "3ph: 3상 단락(가장 심각), slg: 1선 지락(가장 빈번), "
            "llg: 2선 지락, ll: 2선 단락."
        ),
    )


class AllBusesSCRequest(BaseModel):
    """전체 모선 단락전류 일괄 계산 요청 스키마."""

    fault_type: Literal["3ph", "slg", "llg", "ll"] = Field(
        default="3ph",
        description="고장 유형. 기본값: 3ph (3상 단락).",
    )


# ──────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────

@router.post(
    "/run",
    response_model=ShortCircuitResult,
    summary="단일 모선 단락전류 계산",
    description=(
        "지정된 모선에서 단락 고장 발생 시 초기 대칭 단락전류(Ikss)를 계산한다. "
        "pandapower calc_sc() + IEC 60909 표준. "
        "LLM 수치 생성 절대 금지 — 솔버 반환값만 반환. "
        "계산 요청 전용 POST — ops: 네임스페이스 데이터 변경 없음."
    ),
)
def run_shortcircuit(
    req: ShortCircuitRequest,
    calc: ShortCircuitCalculator = Depends(get_calculator),
) -> ShortCircuitResult:
    """단일 모선 단락전류 계산 실행.

    Args:
        req: 단락전류 계산 요청 (bus_id, fault_type).
        calc: ShortCircuitCalculator 의존성.

    Returns:
        ShortCircuitResult: IEC 60909 기반 단락전류 계산 결과.

    Raises:
        422: bus_id가 유효하지 않은 경우.
        503: pandapower 계산 실패 시.
    """
    try:
        return calc.calculate(bus_id=req.bus_id, fault_type=req.fault_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"단락전류 계산 실패: {exc}",
        ) from exc


@router.get(
    "/bus/{bus_id}",
    response_model=ShortCircuitResult,
    summary="특정 모선 단락전류 조회 (3상 단락)",
    description=(
        "지정된 모선의 3상 단락전류를 계산하여 반환한다. "
        "단순 조회용 GET 엔드포인트. "
        "다른 고장 유형은 POST /sca/run 사용."
    ),
)
def get_bus_shortcircuit(
    bus_id: int,
    calc: ShortCircuitCalculator = Depends(get_calculator),
) -> ShortCircuitResult:
    """특정 모선 3상 단락전류 조회.

    Args:
        bus_id: pandapower 모선 인덱스.
        calc: ShortCircuitCalculator 의존성.

    Returns:
        ShortCircuitResult: 3상 단락전류 계산 결과.
    """
    try:
        return calc.calculate(bus_id=bus_id, fault_type="3ph")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"단락전류 계산 실패: {exc}",
        ) from exc


@router.post(
    "/all",
    response_model=list[ShortCircuitResult],
    summary="전체 모선 단락전류 일괄 계산",
    description=(
        "계통 내 모든 유효 모선에 대해 단락전류를 일괄 계산한다. "
        "pandapower calc_sc()는 전체 모선 결과를 한 번에 반환하므로 효율적. "
        "계산 시간이 길 수 있으므로 Phase 1에서는 소규모 계통에만 권장."
    ),
)
def run_all_buses_shortcircuit(
    req: AllBusesSCRequest | None = None,
    calc: ShortCircuitCalculator = Depends(get_calculator),
) -> list[ShortCircuitResult]:
    """전체 모선 단락전류 일괄 계산.

    Args:
        req: 요청 파라미터. None이면 기본값(3ph) 사용.
        calc: ShortCircuitCalculator 의존성.

    Returns:
        list[ShortCircuitResult]: 모든 유효 모선의 단락전류 결과 목록.
    """
    fault_type: Literal["3ph", "slg", "llg", "ll"] = (
        req.fault_type if req is not None else "3ph"
    )
    try:
        return calc.calculate_all_buses(fault_type=fault_type)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"전체 모선 단락전류 계산 실패: {exc}",
        ) from exc
