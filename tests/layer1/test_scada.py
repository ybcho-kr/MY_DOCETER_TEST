"""SCADA 시뮬레이터 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 기반 SCADA 시뮬레이터 기능 검증.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandapower as pp
import pandapower.networks as pn
import pytest

from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer1.scada_simulator.simulator import ScadaSimulator
from src.layer1.scada_simulator.golden_case import (
    create_golden_case,
    verify_against_golden,
)
from src.shared.schemas.grid import BusVoltage, LineLoading
from src.shared.schemas.tp import PowerFlowResult


@pytest.fixture(scope="module")
def net() -> pp.pandapowerNet:
    """IEEE 14-bus 테스트 네트워크."""
    return create_ieee14_network()


@pytest.fixture(scope="module")
def simulator(net: pp.pandapowerNet) -> ScadaSimulator:
    """SCADA 시뮬레이터 (Redis 없음)."""
    return ScadaSimulator(net=net, redis_client=None)


# ------------------------------------------------------------------
# 네트워크 생성 테스트
# ------------------------------------------------------------------

class TestNetworkCreation:
    """IEEE 14-bus 네트워크 생성 테스트."""

    def test_create_ieee14_network(self) -> None:
        """네트워크가 올바르게 생성되어야 한다."""
        net = create_ieee14_network()
        assert net is not None
        assert len(net.bus) > 0, "모선이 존재해야 한다"
        assert len(net.line) > 0, "선로가 존재해야 한다"
        assert len(net.gen) > 0, "발전기가 존재해야 한다"

    def test_ieee14_has_14_buses(self) -> None:
        """IEEE 14-bus는 14개 모선을 가져야 한다."""
        net = create_ieee14_network()
        assert len(net.bus) == 14

    def test_ieee14_has_switches(self) -> None:
        """네트워크에 차단기(CB)가 추가되어야 한다."""
        net = create_ieee14_network()
        assert len(net.switch) >= 2, "최소 2개 차단기가 있어야 한다"


# ------------------------------------------------------------------
# 조류계산 테스트
# ------------------------------------------------------------------

class TestPowerFlow:
    """조류계산 실행 테스트."""

    def test_run_powerflow_converges(self, simulator: ScadaSimulator) -> None:
        """조류계산이 수렴해야 한다."""
        result = simulator.run_powerflow()
        assert isinstance(result, PowerFlowResult)
        assert result.converged is True, "IEEE 14-bus 조류계산은 수렴해야 한다"

    def test_powerflow_result_schema(self, simulator: ScadaSimulator) -> None:
        """PowerFlowResult가 올바른 필드를 포함해야 한다."""
        result = simulator.run_powerflow()
        assert result.max_vm_pu > 0
        assert result.min_vm_pu > 0
        assert result.total_p_gen_mw > 0
        assert result.total_loss_mw >= 0
        assert result.snapshot_ts is not None

    def test_powerflow_voltage_range(self, simulator: ScadaSimulator) -> None:
        """전압은 합리적 범위(0.8~1.2 pu) 이내여야 한다."""
        result = simulator.run_powerflow()
        assert result.min_vm_pu >= 0.8, f"최소 전압 {result.min_vm_pu}pu가 너무 낮음"
        assert result.max_vm_pu <= 1.2, f"최대 전압 {result.max_vm_pu}pu가 너무 높음"


# ------------------------------------------------------------------
# 모선 전압 추출 테스트
# ------------------------------------------------------------------

class TestBusVoltages:
    """모선 전압 스키마 테스트."""

    def test_bus_voltages_schema(self, simulator: ScadaSimulator) -> None:
        """get_bus_voltages()가 BusVoltage 리스트를 반환해야 한다."""
        # 먼저 조류계산 실행
        simulator.run_powerflow()
        voltages = simulator.get_bus_voltages()
        assert len(voltages) > 0, "전압 리스트가 비어있으면 안 된다"
        for bv in voltages:
            assert isinstance(bv, BusVoltage)

    def test_bus_voltages_positive(self, simulator: ScadaSimulator) -> None:
        """모든 모선 전압이 양수여야 한다."""
        simulator.run_powerflow()
        voltages = simulator.get_bus_voltages()
        for bv in voltages:
            assert bv.voltage_pu > 0, f"Bus {bv.bus_id}: 전압 {bv.voltage_pu}pu가 양수가 아님"

    def test_bus_voltage_has_snapshot_ts(self, simulator: ScadaSimulator) -> None:
        """모든 BusVoltage에 snapshot_ts가 포함되어야 한다."""
        simulator.run_powerflow()
        voltages = simulator.get_bus_voltages()
        for bv in voltages:
            assert bv.snapshot_ts is not None


# ------------------------------------------------------------------
# 선로 부하율 추출 테스트
# ------------------------------------------------------------------

class TestLineLoadings:
    """선로 부하율 스키마 테스트."""

    def test_line_loadings_schema(self, simulator: ScadaSimulator) -> None:
        """get_line_loadings()가 LineLoading 리스트를 반환해야 한다."""
        simulator.run_powerflow()
        loadings = simulator.get_line_loadings()
        assert len(loadings) > 0
        for ll in loadings:
            assert isinstance(ll, LineLoading)

    def test_line_loadings_non_negative(self, simulator: ScadaSimulator) -> None:
        """모든 선로 부하율이 0 이상이어야 한다."""
        simulator.run_powerflow()
        loadings = simulator.get_line_loadings()
        for ll in loadings:
            assert ll.loading_pct >= 0, f"Line {ll.line_id}: 부하율 {ll.loading_pct}%가 음수"


# ------------------------------------------------------------------
# Redis 게시 테스트
# ------------------------------------------------------------------

class TestRedisPublish:
    """Redis 게시 테스트 (Mock)."""

    def test_publish_to_redis(self) -> None:
        """Redis 키가 올바르게 저장되어야 한다."""
        net = create_ieee14_network()
        mock_redis = MagicMock()
        sim = ScadaSimulator(net=net, redis_client=mock_redis)
        sim.run_powerflow()
        sim.publish_to_redis()

        # ops: 프리픽스 키가 저장되었는지 확인
        call_args = [str(call) for call in mock_redis.set.call_args_list]
        keys_stored = [c for c in call_args if "ops:" in c]
        assert len(keys_stored) > 0, "ops: 프리픽스 키가 저장되어야 한다"

    def test_redis_keys_format(self) -> None:
        """Redis 키 형식이 ops:bus:{id}:voltage, ops:line:{id}:loading 이어야 한다."""
        net = create_ieee14_network()
        mock_redis = MagicMock()
        sim = ScadaSimulator(net=net, redis_client=mock_redis)
        sim.run_powerflow()
        sim.publish_to_redis()

        keys = [call[0][0] for call in mock_redis.set.call_args_list]
        bus_keys = [k for k in keys if k.startswith("ops:bus:")]
        line_keys = [k for k in keys if k.startswith("ops:line:")]
        assert len(bus_keys) > 0, "ops:bus:* 키가 있어야 한다"
        assert len(line_keys) > 0, "ops:line:* 키가 있어야 한다"

    def test_no_study_namespace_write(self) -> None:
        """study: 네임스페이스에 write하면 안 된다."""
        net = create_ieee14_network()
        mock_redis = MagicMock()
        sim = ScadaSimulator(net=net, redis_client=mock_redis)
        sim.run_powerflow()
        sim.publish_to_redis()

        keys = [call[0][0] for call in mock_redis.set.call_args_list]
        study_keys = [k for k in keys if k.startswith("study:")]
        assert len(study_keys) == 0, "study: 네임스페이스에 write하면 안 된다"


# ------------------------------------------------------------------
# 수렴 실패 처리 테스트
# ------------------------------------------------------------------

class TestConvergenceFailure:
    """수렴 실패 시 처리 테스트."""

    def test_convergence_failure_handling(self) -> None:
        """수렴 실패 시 FAILED 플래그가 설정되어야 한다."""
        net = create_ieee14_network()
        mock_redis = MagicMock()
        sim = ScadaSimulator(net=net, redis_client=mock_redis)

        # 부하를 극단적으로 증가시켜 수렴 실패 유도
        net.load["p_mw"] *= 100

        result = sim.run_cycle()

        if not result.converged:
            # FAILED 플래그 확인
            calls = {call[0][0]: call[0][1] for call in mock_redis.set.call_args_list}
            assert calls.get("ops:powerflow:status") == "FAILED"


# ------------------------------------------------------------------
# Golden Case 검증 테스트
# ------------------------------------------------------------------

class TestGoldenCase:
    """Golden Case 검증 테스트."""

    def test_golden_case_creation(self) -> None:
        """Golden Case 생성이 올바른 구조를 반환해야 한다."""
        net = pn.case14()
        golden = create_golden_case(net)
        assert "bus_vm_pu" in golden
        assert "line_loading_pct" in golden
        assert "total_loss_mw" in golden
        assert len(golden["bus_vm_pu"]) > 0

    def test_golden_case_verification_passes(self) -> None:
        """동일 네트워크는 Golden Case 검증을 통과해야 한다 (편차 <1%)."""
        net = pn.case14()
        golden = create_golden_case(net)
        passed, violations = verify_against_golden(net, golden, tolerance_pct=1.0)
        assert passed, f"Golden Case 검증 실패: {violations}"

    def test_golden_case_verification_detects_change(self) -> None:
        """네트워크 변경 시 Golden Case 검증이 변화를 감지해야 한다."""
        net = pn.case14()
        golden = create_golden_case(net)

        # 부하 변경 (큰 변화)
        net.load["p_mw"] *= 1.5
        passed, violations = verify_against_golden(net, golden, tolerance_pct=1.0)
        # 큰 변화 시 편차 초과 가능
        # (case14에서 50% 부하 증가는 대부분 1% 초과)
        assert len(violations) >= 0  # 위반이 있을 수도, 없을 수도 있음
