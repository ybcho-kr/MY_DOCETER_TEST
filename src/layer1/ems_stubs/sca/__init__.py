"""SCA(단락전류 분석) 스텁 패키지 — AI-EMS v5.1 Phase 1.

pandapower calc_sc() 기반 단락전류 계산.
IEC 60909 표준 준거. 모든 수치는 솔버 반환값만 사용.

하위 모듈:
  calculator: ShortCircuitCalculator 클래스 (핵심 계산 로직)
  router:     FastAPI 라우터 (READ-ONLY 엔드포인트)
"""
from __future__ import annotations

from src.layer1.ems_stubs.sca.calculator import ShortCircuitCalculator
from src.layer1.ems_stubs.sca.router import router, set_calculator

__all__ = [
    "ShortCircuitCalculator",
    "router",
    "set_calculator",
]
