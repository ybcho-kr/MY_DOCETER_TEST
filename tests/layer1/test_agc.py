"""AGC 스텁 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 계통을 기반으로 AGC 컨트롤러와 라우터를 검증한다.
"""
from __future__ import annotations

import math

import pandapower as pp
import pandapower.networks as pn
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.layer1.ems_stubs.agc.controller import AGCController
from src.layer1.ems_stubs.agc.router import router as agc_router
from src.shared.schemas.agc import AGCStatus


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 계통 (조류계산 완료)."""
    n = pn.case14()
    pp.runpp(n, verbose=False)
    return n


@pytest.fixture(scope="module")
def controller(net: pp.pandapowerNet) -> AGCController:
    """AGC 컨트롤러 인스턴스."""
    return AGCController(net=net, nominal_freq=60.0)


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI 테스트 클라이언트."""
    app = FastAPI()
    app.include_router(agc_router)
    return TestClient(app)


# ------------------------------------------------------------------
# AGC 계산 테스트
# ------------------------------------------------------------------

class TestAGCFormulas:
    """AGC 공식 단위 테스트."""

    def test_frequency_deviation_calculation(self, controller: AGCController) -> None:
        """알려진 ΔP → 기대 Δf 검증.

        Δf = -ΔP / (D + 1/R)
        D=1.0, R=0.05 → D + 1/R = 1.0 + 20.0 = 21.0
        ΔP = 100 MW → Δf = -100 / 21 ≈ -4.762 Hz
        """
        delta_p_mw = 100.0
        expected_delta_f = -100.0 / (controller.D + 1.0 / controller.R)
        result = controller.calculate_frequency_deviation(delta_p_mw)
        assert math.isclose(result, expected_delta_f, rel_tol=1e-9), (
            f"주파수 편차 계산 오류: 기대 {expected_delta_f:.4f} Hz, 실제 {result:.4f} Hz"
        )

    def test_frequency_deviation_zero(self, controller: AGCController) -> None:
        """전력 균형(ΔP=0)이면 주파수 편차 0."""
        assert controller.calculate_frequency_deviation(0.0) == 0.0

    def test_frequency_deviation_negative_dp(self, controller: AGCController) -> None:
        """발전 부족(ΔP<0)이면 주파수 상승 (Δf > 0)."""
        result = controller.calculate_frequency_deviation(-50.0)
        assert result > 0, "발전 부족이면 Δf는 양수여야 한다"

    def test_ace_calculation(self, controller: AGCController) -> None:
        """알려진 주파수 → 기대 ACE 검증.

        ACE = 10 * B * Δf
        B = 10 * (D + 1/R) = 10 * 21 = 210
        freq = 59.9 Hz → Δf = -0.1 → ACE = 10 * 210 * (-0.1) = -210 MW
        """
        freq_hz = 59.9
        delta_f = freq_hz - controller.nominal_freq
        expected_ace = 10.0 * controller.B * delta_f
        result = controller.calculate_ace(freq_hz)
        assert math.isclose(result, expected_ace, rel_tol=1e-9), (
            f"ACE 계산 오류: 기대 {expected_ace:.4f} MW, 실제 {result:.4f} MW"
        )

    def test_ace_at_nominal_frequency(self, controller: AGCController) -> None:
        """공칭 주파수(60.0 Hz)에서 ACE = 0."""
        result = controller.calculate_ace(60.0)
        assert result == 0.0, f"공칭 주파수에서 ACE는 0이어야 한다, 실제: {result}"

    def test_bias_constant_formula(self, controller: AGCController) -> None:
        """B = 10 * (D + 1/R) 검증."""
        expected_b = 10.0 * (controller.D + 1.0 / controller.R)
        assert math.isclose(controller.B, expected_b, rel_tol=1e-9)


# ------------------------------------------------------------------
# AGC 상태 스키마 테스트
# ------------------------------------------------------------------

class TestAGCStatus:
    """AGCStatus 스키마 반환 테스트."""

    def test_agc_status_schema(self, controller: AGCController) -> None:
        """get_status()가 유효한 AGCStatus 반환 검증."""
        status = controller.get_status(freq_hz=60.0)
        assert isinstance(status, AGCStatus)
        assert status.frequency_hz == 60.0
        assert status.model_type == "tie-line bias"
        assert status.snapshot_ts is not None

    def test_agc_status_frequency_range(self, controller: AGCController) -> None:
        """반환 주파수가 스키마 유효 범위(58~62 Hz) 내에 있어야 한다."""
        status = controller.get_status()
        assert 58.0 <= status.frequency_hz <= 62.0, (
            f"주파수 {status.frequency_hz} Hz가 유효 범위(58~62) 밖임"
        )

    def test_agc_status_regulation_non_negative(self, controller: AGCController) -> None:
        """조정 가능 용량은 0 이상이어야 한다."""
        status = controller.get_status(freq_hz=60.0)
        assert status.total_regulation_mw >= 0
        assert status.participating_units >= 0

    def test_agc_status_ace_type(self, controller: AGCController) -> None:
        """ACE는 float 타입이어야 한다."""
        status = controller.get_status(freq_hz=59.95)
        assert isinstance(status.ace_mw, float)


# ------------------------------------------------------------------
# 예비력 현황 테스트
# ------------------------------------------------------------------

class TestAGCReserves:
    """예비력 5종 현황 테스트."""

    def test_reserves_breakdown(self, controller: AGCController) -> None:
        """예비력 5종 키가 모두 존재하고 값이 0 이상이어야 한다."""
        reserves = controller.get_reserves()
        required_keys = {
            "frequency_control_mw",
            "fast_response_mw",
            "primary_mw",
            "secondary_mw",
            "tertiary_mw",
        }
        assert required_keys == set(reserves.keys()), (
            f"예비력 키 불일치. 기대: {required_keys}, 실제: {set(reserves.keys())}"
        )
        for key, value in reserves.items():
            assert value >= 0, f"예비력 '{key}' 값이 음수: {value}"

    def test_reserves_all_five_types(self, controller: AGCController) -> None:
        """예비력 5종이 모두 반환되어야 한다 (고시 제6조)."""
        reserves = controller.get_reserves()
        assert len(reserves) == 5, f"예비력 항목 수 오류: {len(reserves)} (기대: 5)"

    def test_reserves_values_are_float(self, controller: AGCController) -> None:
        """예비력 값이 모두 float 타입이어야 한다."""
        reserves = controller.get_reserves()
        for key, value in reserves.items():
            assert isinstance(value, float), f"예비력 '{key}' 값이 float가 아님: {type(value)}"


# ------------------------------------------------------------------
# 라우터 테스트
# ------------------------------------------------------------------

class TestAGCRouter:
    """AGC FastAPI 라우터 테스트."""

    def test_agc_router_get_status(self, client: TestClient) -> None:
        """GET /agc/status 가 200 응답을 반환해야 한다."""
        response = client.get("/agc/status")
        assert response.status_code == 200, f"상태 코드 오류: {response.status_code}"

    def test_agc_router_get_reserves(self, client: TestClient) -> None:
        """GET /agc/reserves 가 200 응답을 반환해야 한다."""
        response = client.get("/agc/reserves")
        assert response.status_code == 200, f"상태 코드 오류: {response.status_code}"

    def test_agc_router_get_only_post_returns_405(self, client: TestClient) -> None:
        """POST /agc/status 는 405 Method Not Allowed 여야 한다."""
        response = client.post("/agc/status", json={})
        assert response.status_code == 405, (
            f"POST /agc/status: 기대 405, 실제 {response.status_code}"
        )

    def test_agc_router_get_only_put_returns_405(self, client: TestClient) -> None:
        """PUT /agc/status 는 405 Method Not Allowed 여야 한다."""
        response = client.put("/agc/status", json={})
        assert response.status_code == 405, (
            f"PUT /agc/status: 기대 405, 실제 {response.status_code}"
        )

    def test_agc_router_get_only_delete_returns_405(self, client: TestClient) -> None:
        """DELETE /agc/status 는 405 Method Not Allowed 여야 한다."""
        response = client.delete("/agc/status")
        assert response.status_code == 405, (
            f"DELETE /agc/status: 기대 405, 실제 {response.status_code}"
        )

    def test_agc_router_get_only_patch_returns_405(self, client: TestClient) -> None:
        """PATCH /agc/status 는 405 Method Not Allowed 여야 한다."""
        response = client.patch("/agc/status", json={})
        assert response.status_code == 405, (
            f"PATCH /agc/status: 기대 405, 실제 {response.status_code}"
        )

    def test_no_write_routes(self) -> None:
        """라우터에 POST/PUT/PATCH/DELETE 핸들러가 없어야 한다 (안전 요구사항)."""
        from src.layer1.ems_stubs.agc.router import router as agc_router_import

        write_methods = {"POST", "PUT", "PATCH", "DELETE"}
        for route in agc_router_import.routes:
            route_methods = getattr(route, "methods", set()) or set()
            overlap = route_methods & write_methods
            assert not overlap, (
                f"쓰기 라우트 발견 (안전 위반): {route} 메서드={route_methods}"
            )

    def test_status_response_has_required_fields(self, client: TestClient) -> None:
        """GET /agc/status 응답에 필수 필드가 포함되어야 한다."""
        response = client.get("/agc/status")
        data = response.json()
        required = {"frequency_hz", "ace_mw", "model_type", "total_regulation_mw",
                    "participating_units", "snapshot_ts"}
        assert required.issubset(data.keys()), (
            f"응답 필드 누락: {required - data.keys()}"
        )
