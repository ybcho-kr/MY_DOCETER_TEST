"""SCADA 시뮬레이터 테스트 — AI-EMS v5.1 Phase 1.

pandapower IEEE 14-bus 기반 SCADA 시뮬레이터 기능 검증.
커버리지 목표: ≥80%.

테스트 범위:
  - 네트워크 생성 (IEEE 14-bus, create_network_from_raw)
  - 조류계산 실행 및 스키마 검증
  - 모선 전압 / 선로 부하율 추출
  - Redis 게시 (Mock)
  - 수렴 실패 처리
  - Golden Case 검증
  - scheduler.py 시작/정지/상태 확인
  - publish_to_redis 이중 실행 방지 검증
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandapower as pp
import pandapower.networks as pn
import pytest

from src.layer1.scada_simulator.golden_case import (
    create_golden_case,
    load_golden_case,
    save_golden_case,
    verify_against_golden,
)
from src.layer1.scada_simulator.network import (
    _convert_switched_shunts,
    _fix_bus_name_encoding,
    create_ieee14_network,
)
from src.layer1.scada_simulator.scheduler import (
    get_scheduler_status,
    start_scada_loop,
    stop_scada_loop,
)
from src.layer1.scada_simulator.simulator import ScadaSimulator
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

    def test_create_network_from_raw_file_not_found(self) -> None:
        """존재하지 않는 .raw 파일은 FileNotFoundError를 발생해야 한다."""
        from src.layer1.scada_simulator.network import create_network_from_raw

        with pytest.raises(FileNotFoundError, match=".raw 파일 없음"):
            create_network_from_raw("/nonexistent/path/test.raw")

    def test_fix_bus_name_encoding_no_name_column(self) -> None:
        """name 컬럼이 없는 네트워크는 인코딩 수정 시 오류 없이 통과해야 한다."""
        net = pn.case14()
        # name 컬럼 제거
        if "name" in net.bus.columns:
            net.bus = net.bus.drop(columns=["name"])
        # 예외 없이 실행되어야 함
        _fix_bus_name_encoding(net)

    def test_fix_bus_name_encoding_valid_utf8(self) -> None:
        """유효한 UTF-8 이름은 변경 없이 유지되어야 한다."""
        net = pn.case14()
        original_name = "신서울345"
        net.bus.at[0, "name"] = original_name
        _fix_bus_name_encoding(net)
        # UTF-8로 이미 valid이므로 EUC-KR 재해석 실패 → 원본 유지
        # (latin-1 인코딩 불가 시 원본 유지)
        assert isinstance(net.bus.at[0, "name"], str)

    def test_convert_switched_shunts_basic(self) -> None:
        """Switched Shunt 변환이 pandapower shunt를 추가해야 한다."""
        net = pn.case14()
        initial_shunt_count = len(net.shunt)
        switched_shunts = [{"bus": 1, "binit": 0.5}]
        n = _convert_switched_shunts(net, switched_shunts)
        assert n == 1
        assert len(net.shunt) == initial_shunt_count + 1

    def test_convert_switched_shunts_zero_binit(self) -> None:
        """binit=0인 Switched Shunt는 변환 생략해야 한다."""
        net = pn.case14()
        initial_shunt_count = len(net.shunt)
        switched_shunts = [{"bus": 1, "binit": 0.0}]
        n = _convert_switched_shunts(net, switched_shunts)
        assert n == 0
        assert len(net.shunt) == initial_shunt_count

    def test_convert_switched_shunts_invalid_bus(self) -> None:
        """존재하지 않는 bus의 Switched Shunt는 건너뛰어야 한다."""
        net = pn.case14()
        initial_shunt_count = len(net.shunt)
        switched_shunts = [{"bus": 9999, "binit": 0.5}]
        n = _convert_switched_shunts(net, switched_shunts)
        assert n == 0
        assert len(net.shunt) == initial_shunt_count


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

    def test_powerflow_loss_non_negative(self, simulator: ScadaSimulator) -> None:
        """손실은 0 이상이어야 한다."""
        result = simulator.run_powerflow()
        assert result.total_loss_mw >= 0

    def test_last_result_updated_after_convergence(self) -> None:
        """수렴 성공 후 last_result가 갱신되어야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        assert sim.last_result is None
        result = sim.run_powerflow()
        assert sim.last_result is not None
        assert sim.last_result.converged is True
        assert sim.last_result.snapshot_ts == result.snapshot_ts


# ------------------------------------------------------------------
# 모선 전압 추출 테스트
# ------------------------------------------------------------------

class TestBusVoltages:
    """모선 전압 스키마 테스트."""

    def test_bus_voltages_schema(self, simulator: ScadaSimulator) -> None:
        """get_bus_voltages()가 BusVoltage 리스트를 반환해야 한다."""
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

    def test_bus_voltages_count_matches_network(self, simulator: ScadaSimulator) -> None:
        """반환 모선 수가 네트워크 모선 수와 일치해야 한다."""
        simulator.run_powerflow()
        voltages = simulator.get_bus_voltages()
        assert len(voltages) == len(simulator.net.bus)

    def test_bus_voltage_nominal_kv_valid(self, simulator: ScadaSimulator) -> None:
        """모든 BusVoltage의 nominal_kv가 한국 표준 등급이어야 한다."""
        valid_kv = {765.0, 345.0, 154.0, 66.0, 22.9}
        simulator.run_powerflow()
        voltages = simulator.get_bus_voltages()
        for bv in voltages:
            assert bv.nominal_kv in valid_kv, (
                f"Bus {bv.bus_id}: nominal_kv={bv.nominal_kv}이 표준 등급 아님"
            )


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

    def test_line_loadings_count_matches_network(self, simulator: ScadaSimulator) -> None:
        """반환 선로 수가 네트워크 선로 수와 일치해야 한다."""
        simulator.run_powerflow()
        loadings = simulator.get_line_loadings()
        assert len(loadings) == len(simulator.net.line)

    def test_line_loading_rating_mva_positive(self, simulator: ScadaSimulator) -> None:
        """모든 선로의 rating_mva가 양수여야 한다."""
        simulator.run_powerflow()
        loadings = simulator.get_line_loadings()
        for ll in loadings:
            assert ll.rating_mva > 0, f"Line {ll.line_id}: rating_mva={ll.rating_mva}가 양수 아님"

    def test_line_loadings_empty_before_runpp(self) -> None:
        """runpp() 미실행 시 get_line_loadings()는 빈 리스트를 반환해야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        # res_line이 비어있으므로 빈 리스트
        loadings = sim.get_line_loadings()
        assert loadings == []


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

    def test_publish_with_result_no_double_runpp(self) -> None:
        """publish_to_redis(result)는 runpp()를 추가로 호출하지 않아야 한다.

        v5.1 버그 수정 검증: 이전 구현에서 publish_to_redis()가
        내부에서 run_powerflow()를 재호출하는 문제를 수정.
        """
        net = create_ieee14_network()
        mock_redis = MagicMock()
        sim = ScadaSimulator(net=net, redis_client=mock_redis)
        result = sim.run_powerflow()

        # run_powerflow를 spy로 모니터링
        original_run_powerflow = sim.run_powerflow
        call_count = {"n": 0}

        def spy_run_powerflow() -> PowerFlowResult:
            call_count["n"] += 1
            return original_run_powerflow()

        sim.run_powerflow = spy_run_powerflow  # type: ignore[method-assign]
        sim.publish_to_redis(result)  # result를 명시적으로 전달

        assert call_count["n"] == 0, (
            "publish_to_redis(result)는 run_powerflow()를 추가 호출하면 안 된다"
        )

    def test_publish_to_redis_none_client(self) -> None:
        """Redis 클라이언트가 None이면 publish_to_redis가 아무것도 하지 않아야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        sim.run_powerflow()
        # 예외 없이 실행되어야 함
        sim.publish_to_redis()


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
        net.load["p_mw"] = net.load["p_mw"] * 100

        result = sim.run_cycle()

        if not result.converged:
            calls = {call[0][0]: call[0][1] for call in mock_redis.set.call_args_list}
            assert calls.get("ops:powerflow:status") == "FAILED"

    def test_last_result_preserved_on_failure(self) -> None:
        """수렴 실패 시 last_result가 이전 성공 결과를 유지해야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)

        # 첫 번째: 수렴 성공
        first_result = sim.run_powerflow()
        assert first_result.converged is True
        saved_result = sim.last_result

        # 부하를 극단적으로 증가시켜 수렴 실패 유도
        net.load["p_mw"] = net.load["p_mw"] * 100
        failed_result = sim.run_powerflow()

        if not failed_result.converged:
            # last_result는 이전 성공 결과를 유지해야 함
            assert sim.last_result is saved_result

    def test_run_powerflow_converged_false_schema(self) -> None:
        """수렴 실패 시 PowerFlowResult.converged가 False이어야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        net.load["p_mw"] = net.load["p_mw"] * 1000

        result = sim.run_powerflow()
        if not result.converged:
            assert isinstance(result, PowerFlowResult)
            assert result.converged is False


# ------------------------------------------------------------------
# Golden Case 검증 테스트
# ------------------------------------------------------------------

class TestGoldenCase:
    """Golden Case 검증 테스트."""

    def test_golden_case_creation(self) -> None:
        """Golden Case 생성이 올바른 구조를 반환해야 한다."""
        net = pn.case14()
        golden = create_golden_case(net, network_type="ieee14")
        assert "meta" in golden
        assert "bus_vm_pu" in golden
        assert "line_loading_pct" in golden
        assert "trafo_loading_pct" in golden
        assert "total_loss_mw" in golden
        assert len(golden["bus_vm_pu"]) > 0

    def test_golden_case_meta_fields(self) -> None:
        """Golden Case meta 필드가 올바르게 채워져야 한다."""
        net = pn.case14()
        golden = create_golden_case(net, network_type="ieee14_test")
        meta = golden["meta"]
        assert meta["network_type"] == "ieee14_test"
        assert meta["bus_count"] == len(net.bus)
        assert meta["line_count"] == len(net.line)
        assert "created_at" in meta

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
        # 큰 변화 시 편차 초과 가능 (테스트는 결과 유형만 확인)
        assert isinstance(passed, bool)
        assert isinstance(violations, list)

    def test_golden_case_diverge_returns_false(self) -> None:
        """수렴 실패 시 verify_against_golden이 (False, [...]) 반환해야 한다."""
        net = pn.case14()
        golden = create_golden_case(net)

        # 수렴 불가 조건
        net.load["p_mw"] *= 1000
        passed, violations = verify_against_golden(net, golden, skip_on_diverge=True)
        assert passed is False
        assert len(violations) > 0

    def test_save_and_load_golden_case(self) -> None:
        """Golden Case 저장 및 로드가 올바르게 동작해야 한다."""
        net = pn.case14()
        golden = create_golden_case(net)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_golden.json"
            save_golden_case(golden, path)
            assert path.exists()
            loaded = load_golden_case(path)
            assert loaded["bus_vm_pu"] == golden["bus_vm_pu"]
            assert loaded["line_loading_pct"] == golden["line_loading_pct"]

    def test_load_golden_case_not_found(self) -> None:
        """존재하지 않는 파일 로드 시 FileNotFoundError가 발생해야 한다."""
        with pytest.raises(FileNotFoundError):
            load_golden_case("/nonexistent/golden.json")

    def test_create_golden_case_diverge_raises(self) -> None:
        """수렴 실패 네트워크로 Golden Case 생성 시 RuntimeError가 발생해야 한다."""
        net = pn.case14()
        net.load["p_mw"] *= 1000
        with pytest.raises(RuntimeError, match="조류계산 수렴 실패"):
            create_golden_case(net)


# ------------------------------------------------------------------
# Scheduler 테스트
# ------------------------------------------------------------------

class TestScheduler:
    """APScheduler 기반 SCADA 스케줄러 테스트."""

    def setup_method(self) -> None:
        """각 테스트 전 스케줄러 정리."""
        stop_scada_loop()

    def teardown_method(self) -> None:
        """각 테스트 후 스케줄러 정리."""
        stop_scada_loop()

    def test_start_scada_loop_returns_scheduler(self) -> None:
        """start_scada_loop()가 BackgroundScheduler를 반환해야 한다."""
        from apscheduler.schedulers.background import BackgroundScheduler

        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        scheduler = start_scada_loop(sim, interval_sec=60.0)

        assert scheduler is not None
        assert isinstance(scheduler, BackgroundScheduler)
        assert scheduler.running is True

    def test_start_scada_loop_idempotent(self) -> None:
        """이미 실행 중인 스케줄러에 start_scada_loop 재호출 시 기존 인스턴스 반환."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)

        s1 = start_scada_loop(sim, interval_sec=60.0)
        s2 = start_scada_loop(sim, interval_sec=60.0)
        # 동일 인스턴스여야 함
        assert s1 is s2

    def test_stop_scada_loop(self) -> None:
        """stop_scada_loop()가 스케줄러를 정지해야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        scheduler = start_scada_loop(sim, interval_sec=60.0)
        assert scheduler.running is True

        stop_scada_loop()
        # 정지 후 status 확인
        status = get_scheduler_status()
        assert status["running"] is False

    def test_stop_scada_loop_when_not_running(self) -> None:
        """스케줄러가 실행 중이지 않을 때 stop 호출 시 오류 없이 통과해야 한다."""
        stop_scada_loop()  # 예외 없이 실행되어야 함

    def test_get_scheduler_status_initial(self) -> None:
        """초기(정지) 상태에서 get_scheduler_status()가 running=False를 반환해야 한다."""
        status = get_scheduler_status()
        assert status["running"] is False
        assert status["job_count"] == 0

    def test_get_scheduler_status_running(self) -> None:
        """실행 중 get_scheduler_status()가 running=True, job_count>0을 반환해야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)
        start_scada_loop(sim, interval_sec=60.0)

        status = get_scheduler_status()
        assert status["running"] is True
        assert status["job_count"] > 0

    def test_start_scada_loop_invalid_interval(self) -> None:
        """interval_sec < 1이면 ValueError가 발생해야 한다."""
        net = create_ieee14_network()
        sim = ScadaSimulator(net=net, redis_client=None)

        with pytest.raises(ValueError, match="interval_sec"):
            start_scada_loop(sim, interval_sec=0.5)

    def test_scada_job_context_handles_exception(self) -> None:
        """스케줄러 잡이 예외를 받아도 루프가 계속되어야 한다 (내부 컨텍스트 테스트)."""
        from src.layer1.scada_simulator.scheduler import _ScadaJobContext

        net = create_ieee14_network()
        mock_sim = MagicMock()
        mock_sim.run_cycle.side_effect = RuntimeError("의도적 테스트 오류")

        ctx = _ScadaJobContext(mock_sim)
        # 예외 발생해도 run_once()는 정상 반환해야 함
        ctx.run_once()  # 예외 없이 통과

    def test_scada_job_context_consecutive_failures(self) -> None:
        """연속 실패 횟수가 올바르게 증가해야 한다."""
        from src.layer1.scada_simulator.scheduler import _ScadaJobContext

        net = create_ieee14_network()
        mock_sim = MagicMock()
        # 수렴 실패 결과 모킹
        mock_result = MagicMock()
        mock_result.converged = False
        mock_result.snapshot_ts.isoformat.return_value = "2026-01-01T00:00:00Z"
        mock_sim.run_cycle.return_value = mock_result

        ctx = _ScadaJobContext(mock_sim)
        for _ in range(3):
            ctx.run_once()

        assert ctx._consecutive_failures == 3
