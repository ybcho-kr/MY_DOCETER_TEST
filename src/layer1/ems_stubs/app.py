"""AI-EMS Layer 1 — EMS 스텁 통합 FastAPI 앱.

TP, SE, AGC, SCA 라우터를 통합하여 단일 FastAPI 앱으로 제공.
pandapower 네트워크 및 Redis 의존성 주입.

v0.3.0 변경사항:
  - SCA(단락전류 분석) 라우터 추가 (IEC 60909 기반)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pandapower.networks as pn
from fastapi import FastAPI

from src.layer1.ems_stubs.se.estimator import StateEstimator
from src.layer1.ems_stubs.se.router import router as se_router, set_estimator
from src.layer1.ems_stubs.tp.powerflow import PowerFlowEngine
from src.layer1.ems_stubs.tp.contingency import ContingencyAnalyzer
from src.layer1.ems_stubs.tp.vsa import VoltageStabilityAnalyzer
from src.layer1.ems_stubs.tp.router import router as tp_router, set_engines
from src.layer1.ems_stubs.agc.controller import AGCController
from src.layer1.ems_stubs.agc.router import router as agc_router, set_controller
from src.layer1.ems_stubs.sca.calculator import ShortCircuitCalculator
from src.layer1.ems_stubs.sca.router import router as sca_router, set_calculator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """앱 생명주기 관리 — pandapower 네트워크 및 엔진 초기화."""
    # IEEE 14-bus 네트워크 (MDP 단계)
    net = pn.case14()

    # 엔진 초기화 및 의존성 설정
    set_estimator(StateEstimator(net))
    set_engines(
        pf_engine=PowerFlowEngine(net),
        ca_analyzer=ContingencyAnalyzer(net),
        vsa_analyzer=VoltageStabilityAnalyzer(net),
    )
    set_controller(AGCController(net))
    set_calculator(ShortCircuitCalculator(net))

    yield  # 앱 실행


def create_app() -> FastAPI:
    """FastAPI 앱 생성."""
    app = FastAPI(
        title="AI-EMS Layer 1 — EMS Stubs",
        description=(
            "pandapower 기반 EMS 스텁 (TP, SE, AGC, SCA). Phase 1 MDP. "
            "READ-ONLY 원칙: ops: 네임스페이스 AI write 절대 금지."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )

    app.include_router(se_router)
    app.include_router(tp_router)
    app.include_router(agc_router)
    app.include_router(sca_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": "0.3.0"}

    return app


# uvicorn src.layer1.ems_stubs.app:app --reload
app = create_app()
