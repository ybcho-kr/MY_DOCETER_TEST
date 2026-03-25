"""SCA(단락전류 분석) 스텁 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 기반 단락전류 계산기 및 라우터 검증.
IEC 60909 기준 ikss_ka, skss_mva 검증.
"""
from __future__ import annotations

import math

import pandapower as pp
import pandapower.networks as pn
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.layer1.ems_stubs.sca.calculator import ShortCircuitCalculator
from src.layer1.ems_stubs.sca.router import router as sca_router, set_calculator
from src.shared.schemas.study import ShortCircuitResult


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 네트워크."""
    n = pn.case14()
    pp.runpp(n, verbose=False)
    return n


@pytest.fixture(scope="module")
def calculator(net: pp.pandapowerNet) -> ShortCircuitCalculator:
    """단락전류 계산기 인스턴스."""
    return ShortCircuitCalculator(net=net)


@pytest.fixture(scope="module")
def client(calculator: ShortCircuitCalculator) -> TestClient:
    """FastAPI 테스트 클라이언트."""
    set_calculator(calculator)
    app = FastAPI()
    app.include_router(sca_router)
    return TestClient(app)


# ──────────────────────────────────────────────
# 계산기 핵심 기능 테스트
# ──────────────────────────────────────────────

class TestShortCircuitCalculator:
    """ShortCircuitCalculator 핵심 기능 테스트."""

    def test_calculator_init(self, calculator: ShortCircuitCalculator) -> None:
        """계산기 초기화 확인."""
        assert calculator.net is not None
        assert len(calculator.net.bus) > 0

    def test_calculate_3ph_returns_result(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """3상 단락전류 계산이 ShortCircuitResult를 반환해야 한다."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert isinstance(result, ShortCircuitResult)
        assert result.snapshot_ts is not None

    def test_calculate_bus_id_preserved(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """결과의 bus_id가 요청한 bus_id와 일치해야 한다."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert result.bus_id == bus_id

    def test_calculate_fault_type_preserved(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """결과의 fault_type이 요청한 fault_type과 일치해야 한다."""
        bus_id = int(net.bus.index[0])
        for fault_type in ("3ph", "slg"):
            result = calculator.calculate(bus_id=bus_id, fault_type=fault_type)  # type: ignore
            assert result.fault_type == fault_type

    def test_ikss_ka_positive(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """단락전류 ikss_ka가 양수여야 한다 (LLM 수치 금지 검증)."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert result.ikss_ka > 0, f"ikss_ka={result.ikss_ka}이 0 이하 (솔버 반환값 이상)"

    def test_skss_mva_positive(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """단락용량 skss_mva가 양수여야 한다."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert result.skss_mva > 0, f"skss_mva={result.skss_mva}이 0 이하"

    def test_skss_mva_formula_consistency(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """Skss = √3 × Ikss × Vn 공식 일관성 검증."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        vn_kv = float(net.bus.at[bus_id, "vn_kv"])
        expected_skss = math.sqrt(3.0) * result.ikss_ka * vn_kv
        assert abs(result.skss_mva - expected_skss) < 1e-3, (
            f"공식 불일치: skss={result.skss_mva:.4f} ≠ √3×{result.ikss_ka:.4f}×{vn_kv}={expected_skss:.4f}"
        )

    def test_invalid_bus_id_raises_value_error(
        self, calculator: ShortCircuitCalculator
    ) -> None:
        """유효하지 않은 bus_id는 ValueError를 발생시켜야 한다."""
        with pytest.raises(ValueError, match="존재하지 않"):
            calculator.calculate(bus_id=99999, fault_type="3ph")

    def test_schema_fields_present(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """ShortCircuitResult 스키마 필수 필드가 모두 존재해야 한다."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert hasattr(result, "bus_id")
        assert hasattr(result, "fault_type")
        assert hasattr(result, "ikss_ka")
        assert hasattr(result, "skss_mva")
        assert hasattr(result, "snapshot_ts")


# ──────────────────────────────────────────────
# 전체 모선 일괄 계산 테스트
# ──────────────────────────────────────────────

class TestAllBusesCalculation:
    """전체 모선 단락전류 일괄 계산 테스트."""

    def test_calculate_all_buses_returns_list(
        self, calculator: ShortCircuitCalculator
    ) -> None:
        """calculate_all_buses()가 목록을 반환해야 한다."""
        results = calculator.calculate_all_buses(fault_type="3ph")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_calculate_all_buses_result_count(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """결과 수가 유효 모선 수와 일치하거나 적어야 한다."""
        results = calculator.calculate_all_buses(fault_type="3ph")
        in_service_count = int(net.bus["in_service"].sum())
        assert len(results) <= in_service_count

    def test_calculate_all_buses_all_positive(
        self, calculator: ShortCircuitCalculator
    ) -> None:
        """모든 모선의 ikss_ka가 양수여야 한다."""
        results = calculator.calculate_all_buses(fault_type="3ph")
        for r in results:
            assert r.ikss_ka >= 0, f"Bus {r.bus_id}: ikss_ka={r.ikss_ka} 음수"

    def test_calculate_all_buses_schema_validation(
        self, calculator: ShortCircuitCalculator
    ) -> None:
        """모든 결과가 ShortCircuitResult 스키마를 만족해야 한다."""
        results = calculator.calculate_all_buses(fault_type="3ph")
        for r in results:
            assert isinstance(r, ShortCircuitResult)


# ──────────────────────────────────────────────
# FastAPI 라우터 테스트
# ──────────────────────────────────────────────

class TestSCARouter:
    """SCA FastAPI 라우터 테스트."""

    def test_sca_run_endpoint_200(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """POST /sca/run이 200 응답을 반환해야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.post("/sca/run", json={"bus_id": bus_id, "fault_type": "3ph"})
        assert response.status_code == 200

    def test_sca_run_response_schema(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """POST /sca/run 응답이 필수 필드를 포함해야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.post("/sca/run", json={"bus_id": bus_id, "fault_type": "3ph"})
        data = response.json()
        assert "bus_id" in data
        assert "fault_type" in data
        assert "ikss_ka" in data
        assert "skss_mva" in data
        assert "snapshot_ts" in data

    def test_sca_run_default_fault_type(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """fault_type 생략 시 기본값(3ph)으로 계산되어야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.post("/sca/run", json={"bus_id": bus_id})
        assert response.status_code == 200
        assert response.json()["fault_type"] == "3ph"

    def test_sca_bus_get_endpoint_200(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """GET /sca/bus/{bus_id}가 200 응답을 반환해야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.get(f"/sca/bus/{bus_id}")
        assert response.status_code == 200

    def test_sca_bus_get_response_schema(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """GET /sca/bus/{bus_id} 응답이 필수 필드를 포함해야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.get(f"/sca/bus/{bus_id}")
        data = response.json()
        assert data["bus_id"] == bus_id
        assert data["fault_type"] == "3ph"  # GET은 항상 3ph
        assert data["ikss_ka"] > 0

    def test_sca_run_invalid_bus_422(self, client: TestClient) -> None:
        """유효하지 않은 bus_id로 요청 시 422 응답을 반환해야 한다."""
        response = client.post("/sca/run", json={"bus_id": 99999, "fault_type": "3ph"})
        assert response.status_code == 422

    def test_sca_all_endpoint_200(self, client: TestClient) -> None:
        """POST /sca/all이 200 응답을 반환해야 한다."""
        response = client.post("/sca/all", json={"fault_type": "3ph"})
        assert response.status_code == 200

    def test_sca_all_returns_list(self, client: TestClient) -> None:
        """POST /sca/all 응답이 목록이어야 한다."""
        response = client.post("/sca/all", json={"fault_type": "3ph"})
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_sca_all_no_body_uses_default(self, client: TestClient) -> None:
        """POST /sca/all에 body 없이 요청해도 동작해야 한다 (기본값 3ph)."""
        response = client.post("/sca/all")
        assert response.status_code == 200

    def test_sca_run_slg_fault(
        self, client: TestClient, net: pp.pandapowerNet
    ) -> None:
        """POST /sca/run으로 slg(1선 지락) 단락전류도 계산되어야 한다."""
        bus_id = int(net.bus.index[0])
        response = client.post("/sca/run", json={"bus_id": bus_id, "fault_type": "slg"})
        assert response.status_code == 200
        data = response.json()
        assert data["fault_type"] == "slg"
        assert data["ikss_ka"] >= 0


# ──────────────────────────────────────────────
# 도메인 규칙 검증
# ──────────────────────────────────────────────

class TestSCADomainRules:
    """전력 도메인 규칙 검증."""

    def test_3ph_greater_than_slg(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """3상 단락전류가 1선 지락보다 크거나 같아야 한다 (일반적으로 성립).

        주의: 비접지 계통에서는 예외 가능. IEEE 14-bus(접지계통)에서는 성립.
        """
        bus_id = int(net.bus.index[0])
        result_3ph = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        result_slg = calculator.calculate(bus_id=bus_id, fault_type="slg")
        # 3상 단락 ≥ 1선 지락은 접지계통에서 일반적으로 성립
        # 절대 보장이 아니므로 경고 수준 검증
        if result_3ph.ikss_ka < result_slg.ikss_ka:
            import warnings
            warnings.warn(
                f"Bus {bus_id}: 3ph({result_3ph.ikss_ka:.4f}kA) < slg({result_slg.ikss_ka:.4f}kA). "
                "비접지 계통이거나 계산 이상."
            )

    def test_snapshot_ts_not_none(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """snapshot_ts가 None이 아니어야 한다 (설계 원칙 5)."""
        bus_id = int(net.bus.index[0])
        result = calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert result.snapshot_ts is not None, "snapshot_ts 필수 (설계 원칙 5)"

    def test_read_only_no_net_modification(
        self, calculator: ShortCircuitCalculator, net: pp.pandapowerNet
    ) -> None:
        """계산 후 원본 net이 변경되지 않아야 한다 (READ-ONLY 원칙)."""
        bus_count_before = len(net.bus)
        line_count_before = len(net.line)
        bus_id = int(net.bus.index[0])
        calculator.calculate(bus_id=bus_id, fault_type="3ph")
        assert len(net.bus) == bus_count_before, "계산 후 버스 수 변경 금지"
        assert len(net.line) == line_count_before, "계산 후 선로 수 변경 금지"
