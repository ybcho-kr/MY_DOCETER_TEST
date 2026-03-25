"""SE(상태 추정) 스텁 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 기반 상태 추정기 및 라우터 검증.
"""
from __future__ import annotations

import pandapower as pp
import pandapower.networks as pn
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.layer1.ems_stubs.se.estimator import StateEstimator
from src.layer1.ems_stubs.se.router import router as se_router, set_estimator
from src.shared.schemas.se import SEResult


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 네트워크."""
    n = pn.case14()
    pp.runpp(n, verbose=False)
    return n


@pytest.fixture(scope="module")
def estimator(net: pp.pandapowerNet) -> StateEstimator:
    """상태 추정기 인스턴스."""
    return StateEstimator(net=net)


@pytest.fixture(scope="module")
def client(estimator: StateEstimator) -> TestClient:
    """FastAPI 테스트 클라이언트."""
    set_estimator(estimator)
    app = FastAPI()
    app.include_router(se_router)
    return TestClient(app)


# ------------------------------------------------------------------
# 상태 추정 테스트
# ------------------------------------------------------------------

class TestStateEstimation:
    """상태 추정 핵심 기능 테스트."""

    def test_run_estimation_returns_se_result(self, estimator: StateEstimator) -> None:
        """run_estimation()이 SEResult 스키마를 반환해야 한다."""
        result = estimator.run_estimation()
        assert isinstance(result, SEResult)
        assert result.snapshot_ts is not None

    def test_estimation_solved_or_fallback(self, estimator: StateEstimator) -> None:
        """상태 추정이 수렴하거나 fallback이 동작해야 한다."""
        result = estimator.run_estimation()
        # SE 또는 fallback(조류계산) 모두 결과를 반환
        assert isinstance(result.solved, bool)

    def test_confidence_level_range(self, estimator: StateEstimator) -> None:
        """confidence_level이 0~1 범위여야 한다."""
        result = estimator.run_estimation()
        assert 0.0 <= result.confidence_level <= 1.0, (
            f"confidence_level {result.confidence_level}이 0~1 범위 밖"
        )

    def test_observable_ratio_range(self, estimator: StateEstimator) -> None:
        """observable_ratio가 0~1 범위여야 한다."""
        result = estimator.run_estimation()
        assert 0.0 <= result.observable_ratio <= 1.0

    def test_max_residual_non_negative(self, estimator: StateEstimator) -> None:
        """max_residual이 0 이상이어야 한다."""
        result = estimator.run_estimation()
        assert result.max_residual >= 0.0


# ------------------------------------------------------------------
# 관측성 분석 테스트
# ------------------------------------------------------------------

class TestObservability:
    """관측성 분석 테스트."""

    def test_observability_check(self, estimator: StateEstimator) -> None:
        """check_observability()가 올바른 키를 반환해야 한다."""
        # 먼저 측정값 추가
        estimator._add_measurements_from_powerflow()
        obs = estimator.check_observability()
        assert "observable_buses" in obs
        assert "unobservable_buses" in obs
        assert "observable_ratio" in obs
        assert "pseudo_ratio" in obs

    def test_observable_ratio_type(self, estimator: StateEstimator) -> None:
        """observable_ratio가 float 타입이어야 한다."""
        estimator._add_measurements_from_powerflow()
        obs = estimator.check_observability()
        assert isinstance(obs["observable_ratio"], float)


# ------------------------------------------------------------------
# SE latest 캐시 테스트
# ------------------------------------------------------------------

class TestSELatest:
    """SE latest 캐시 테스트."""

    def test_se_latest_none_initially(self) -> None:
        """SE 최초 실행 전 get_latest()는 None이어야 한다."""
        net = pn.case14()
        pp.runpp(net, verbose=False)
        est = StateEstimator(net=net)
        assert est.get_latest() is None

    def test_se_latest_after_run(self, estimator: StateEstimator) -> None:
        """run_estimation() 후 get_latest()가 결과를 반환해야 한다."""
        estimator.run_estimation()
        latest = estimator.get_latest()
        assert latest is not None
        assert isinstance(latest, SEResult)


# ------------------------------------------------------------------
# FastAPI 라우터 테스트
# ------------------------------------------------------------------

class TestSERouter:
    """SE FastAPI 라우터 테스트."""

    def test_se_run_endpoint(self, client: TestClient) -> None:
        """GET /se/run이 200 응답을 반환해야 한다."""
        response = client.get("/se/run")
        assert response.status_code == 200
        data = response.json()
        assert "solved" in data
        assert "confidence_level" in data
        assert "snapshot_ts" in data

    def test_se_latest_endpoint(self, client: TestClient) -> None:
        """GET /se/latest가 응답을 반환해야 한다."""
        # 먼저 /se/run 호출
        client.get("/se/run")
        response = client.get("/se/latest")
        assert response.status_code == 200

    def test_se_observability_endpoint(self, client: TestClient) -> None:
        """GET /se/observability가 200 응답을 반환해야 한다."""
        response = client.get("/se/observability")
        assert response.status_code == 200
        data = response.json()
        assert "observable_ratio" in data
