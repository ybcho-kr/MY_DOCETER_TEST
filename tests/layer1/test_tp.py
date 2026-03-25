"""TP(조류계산) 스텁 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 기반 조류계산, N-1 분석, VSA 검증.
"""
from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.layer1.ems_stubs.tp.powerflow import PowerFlowEngine
from src.layer1.ems_stubs.tp.contingency import ContingencyAnalyzer
from src.layer1.ems_stubs.tp.vsa import VoltageStabilityAnalyzer
from src.layer1.ems_stubs.tp.router import router as tp_router, set_engines
from src.shared.schemas.tp import (
    ContingencyCase,
    ContingencyResult,
    PowerFlowResult,
    VSAResult,
)


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 네트워크."""
    return pn.case14()


@pytest.fixture(scope="module")
def pf_engine(net: pp.pandapowerNet) -> PowerFlowEngine:
    """조류계산 엔진."""
    return PowerFlowEngine(net=net)


@pytest.fixture(scope="module")
def ca_analyzer(net: pp.pandapowerNet) -> ContingencyAnalyzer:
    """N-1 분석기."""
    return ContingencyAnalyzer(net=net)


@pytest.fixture(scope="module")
def vsa_analyzer(net: pp.pandapowerNet) -> VoltageStabilityAnalyzer:
    """전압 안정도 분석기."""
    return VoltageStabilityAnalyzer(net=net)


@pytest.fixture(scope="module")
def client(
    pf_engine: PowerFlowEngine,
    ca_analyzer: ContingencyAnalyzer,
    vsa_analyzer: VoltageStabilityAnalyzer,
) -> TestClient:
    """FastAPI 테스트 클라이언트."""
    set_engines(pf_engine, ca_analyzer, vsa_analyzer)
    app = FastAPI()
    app.include_router(tp_router)
    return TestClient(app)


# ------------------------------------------------------------------
# 조류계산 테스트
# ------------------------------------------------------------------

class TestPowerFlowEngine:
    """조류계산 엔진 테스트."""

    def test_powerflow_returns_result(self, pf_engine: PowerFlowEngine) -> None:
        """run()이 PowerFlowResult를 반환해야 한다."""
        result = pf_engine.run()
        assert isinstance(result, PowerFlowResult)
        assert result.converged is True
        assert result.snapshot_ts is not None

    def test_powerflow_values_reasonable(self, pf_engine: PowerFlowEngine) -> None:
        """조류계산 결과가 합리적 범위여야 한다."""
        result = pf_engine.run()
        assert result.max_vm_pu > 0
        assert result.min_vm_pu > 0
        assert result.total_p_gen_mw > 0
        assert result.total_loss_mw >= 0

    def test_violations_detection(self, pf_engine: PowerFlowEngine) -> None:
        """위반사항 검출이 동작해야 한다."""
        pf_engine.run()
        violations = pf_engine.get_violations()
        assert isinstance(violations, list)
        # IEEE 14-bus는 정상 상태이므로 위반이 없거나 적어야 함
        for v in violations:
            assert "element_type" in v
            assert "violation_type" in v


# ------------------------------------------------------------------
# N-1 상정고장 분석 테스트
# ------------------------------------------------------------------

class TestContingencyAnalysis:
    """N-1 분석 테스트."""

    def test_contingency_cases_generation(self, ca_analyzer: ContingencyAnalyzer) -> None:
        """자동 케이스 생성이 모든 선로/변압기를 포함해야 한다."""
        cases = ca_analyzer.generate_cases()
        assert len(cases) > 0
        for case in cases:
            assert isinstance(case, ContingencyCase)
            assert case.element_type in ("line", "trafo", "gen")

    def test_contingency_case_count(self, ca_analyzer: ContingencyAnalyzer) -> None:
        """케이스 수가 선로+변압기 수와 일치해야 한다."""
        cases = ca_analyzer.generate_cases()
        net = ca_analyzer._net
        expected = len(net.line[net.line["in_service"]]) + len(net.trafo[net.trafo["in_service"]])
        assert len(cases) == expected

    def test_contingency_n1_runs(self, ca_analyzer: ContingencyAnalyzer) -> None:
        """N-1 분석이 ContingencyResult를 반환해야 한다."""
        result = ca_analyzer.run_n1(use_tier=False)
        assert isinstance(result, ContingencyResult)
        assert result.tier == 1
        assert result.converged_count + result.diverged_count > 0
        assert result.snapshot_ts is not None

    def test_ptdf_screening_reduces_cases(self, ca_analyzer: ContingencyAnalyzer) -> None:
        """PTDF screening이 케이스 수를 줄여야 한다."""
        all_cases = ca_analyzer.generate_cases()
        if len(all_cases) > 5:
            screened = ca_analyzer._ptdf_screening(all_cases, top_n=5)
            assert len(screened) <= 5, "Tier-1은 top_n 이하로 선별해야 한다"

    def test_contingency_result_violations(self, ca_analyzer: ContingencyAnalyzer) -> None:
        """ContingencyResult의 violations가 올바른 구조여야 한다."""
        result = ca_analyzer.run_n1()
        assert isinstance(result.violations, list)
        for v in result.violations:
            assert isinstance(v, dict)


# ------------------------------------------------------------------
# 전압 안정도 분석 테스트
# ------------------------------------------------------------------

class TestVSA:
    """전압 안정도 분석 테스트."""

    def test_vsa_returns_result(self, vsa_analyzer: VoltageStabilityAnalyzer) -> None:
        """run()이 VSAResult를 반환해야 한다."""
        result = vsa_analyzer.run(load_steps=5)
        assert isinstance(result, VSAResult)
        assert result.snapshot_ts is not None

    def test_vsa_positive_margin(self, vsa_analyzer: VoltageStabilityAnalyzer) -> None:
        """정상 상태에서 안정도 여유가 양수여야 한다."""
        result = vsa_analyzer.run(load_steps=5)
        assert result.p_margin_mw >= 0, f"안정도 여유 {result.p_margin_mw}MW가 음수"

    def test_vsa_critical_bus(self, vsa_analyzer: VoltageStabilityAnalyzer) -> None:
        """critical_bus_id가 1 이상이어야 한다 (스키마 제약)."""
        result = vsa_analyzer.run(load_steps=5)
        assert result.critical_bus_id >= 1


# ------------------------------------------------------------------
# FastAPI 라우터 테스트
# ------------------------------------------------------------------

class TestTPRouter:
    """TP FastAPI 라우터 테스트."""

    def test_tp_powerflow_endpoint(self, client: TestClient) -> None:
        """POST /tp/powerflow가 200 응답을 반환해야 한다."""
        response = client.post("/tp/powerflow")
        assert response.status_code == 200
        data = response.json()
        assert "converged" in data
        assert "snapshot_ts" in data

    def test_tp_contingency_endpoint(self, client: TestClient) -> None:
        """POST /tp/contingency가 200 응답을 반환해야 한다."""
        response = client.post("/tp/contingency")
        assert response.status_code == 200
        data = response.json()
        assert "tier" in data
        assert "violations" in data

    def test_tp_vsa_endpoint(self, client: TestClient) -> None:
        """POST /tp/vsa가 200 응답을 반환해야 한다."""
        response = client.post("/tp/vsa")
        assert response.status_code == 200
        data = response.json()
        assert "p_margin_mw" in data

    def test_tp_violations_endpoint(self, client: TestClient) -> None:
        """GET /tp/violations가 200 응답을 반환해야 한다."""
        response = client.get("/tp/violations")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
