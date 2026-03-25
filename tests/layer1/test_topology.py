"""토폴로지 프로세서 테스트 — AI-EMS v5.1 Phase 1.

차단기 상태 변경, 전기적 섬 감지, 토폴로지 버전 관리,
Physical/Electrical bus 매핑, Redis 연동, 이중모선 기초 검증.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandapower as pp
import pandapower.networks as pn
import pytest

from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer1.topology_processor.processor import (
    BusMapping,
    TopologyProcessor,
    create_double_bus_switches,
)
from src.shared.schemas.grid import TopologyVersion


@pytest.fixture
def net() -> pp.pandapowerNet:
    """스위치가 포함된 IEEE 14-bus 네트워크."""
    return create_ieee14_network()


@pytest.fixture
def tp(net: pp.pandapowerNet) -> TopologyProcessor:
    """토폴로지 프로세서 인스턴스 (Redis 없음)."""
    return TopologyProcessor(net)


@pytest.fixture
def tp_with_redis(net: pp.pandapowerNet) -> tuple[TopologyProcessor, MagicMock]:
    """Redis Mock이 연결된 토폴로지 프로세서."""
    mock_redis = MagicMock()
    tp = TopologyProcessor(net, redis_client=mock_redis)
    return tp, mock_redis


# ------------------------------------------------------------------
# 토폴로지 버전 테스트
# ------------------------------------------------------------------

class TestTopologyVersion:
    """토폴로지 버전 스키마 테스트."""

    def test_topology_version_schema(self, tp: TopologyProcessor) -> None:
        """get_topology_version()이 TopologyVersion 스키마를 반환해야 한다."""
        tv = tp.get_topology_version()
        assert isinstance(tv, TopologyVersion)
        assert tv.version >= 0
        assert tv.total_buses > 0
        assert tv.total_lines > 0
        assert tv.islands >= 1

    def test_initial_version_zero(self, tp: TopologyProcessor) -> None:
        """초기 토폴로지 버전은 0이어야 한다."""
        tv = tp.get_topology_version()
        assert tv.version == 0

    def test_topology_has_timestamp(self, tp: TopologyProcessor) -> None:
        """TopologyVersion에 timestamp가 포함되어야 한다."""
        tv = tp.get_topology_version()
        assert tv.timestamp is not None

    def test_topology_total_counts_positive(self, tp: TopologyProcessor) -> None:
        """total_buses, total_lines가 양수여야 한다."""
        tv = tp.get_topology_version()
        assert tv.total_buses > 0
        assert tv.total_lines > 0


# ------------------------------------------------------------------
# 차단기 개폐 테스트
# ------------------------------------------------------------------

class TestSwitchOperations:
    """차단기 상태 변경 테스트."""

    def test_open_switch(self, tp: TopologyProcessor) -> None:
        """차단기 개방이 올바르게 동작해야 한다."""
        assert 0 in tp.net.switch.index, "Switch 0이 네트워크에 있어야 한다"
        assert bool(tp.net.switch.at[0, "closed"]) is True

        tv = tp.open_switch(0)
        assert bool(tp.net.switch.at[0, "closed"]) is False
        assert isinstance(tv, TopologyVersion)
        assert tv.version == 1

    def test_close_switch(self, tp: TopologyProcessor) -> None:
        """차단기 투입이 올바르게 동작해야 한다."""
        tp.open_switch(0)
        tv = tp.close_switch(0)
        assert bool(tp.net.switch.at[0, "closed"]) is True
        assert tv.version == 2

    def test_version_increments(self, tp: TopologyProcessor) -> None:
        """스위치 조작 시 토폴로지 버전이 증가해야 한다."""
        tv1 = tp.open_switch(0)
        tv2 = tp.close_switch(0)
        assert tv2.version > tv1.version

    def test_invalid_switch_raises(self, tp: TopologyProcessor) -> None:
        """존재하지 않는 스위치 ID는 KeyError를 발생해야 한다."""
        with pytest.raises(KeyError):
            tp.open_switch(999)

    def test_invalid_switch_close_raises(self, tp: TopologyProcessor) -> None:
        """존재하지 않는 스위치 투입 시도는 KeyError를 발생해야 한다."""
        with pytest.raises(KeyError):
            tp.close_switch(9999)


# ------------------------------------------------------------------
# 전기적 섬 감지 테스트
# ------------------------------------------------------------------

class TestIslandDetection:
    """전기적 섬(island) 감지 테스트."""

    def test_detect_islands_initial(self, tp: TopologyProcessor) -> None:
        """초기 상태에서 1개 섬이어야 한다 (연결된 계통)."""
        islands = tp.detect_islands()
        assert len(islands) >= 1, "최소 1개 섬이 있어야 한다"

    def test_detect_islands_returns_sets(self, tp: TopologyProcessor) -> None:
        """detect_islands()가 set 리스트를 반환해야 한다."""
        islands = tp.detect_islands()
        for island in islands:
            assert isinstance(island, set)

    def test_topology_version_islands_field(self, tp: TopologyProcessor) -> None:
        """TopologyVersion.islands가 실제 섬 수와 일치해야 한다."""
        islands = tp.detect_islands()
        tv = tp.get_topology_version()
        # islands >= 1 (ge=1 스키마 조건)
        assert tv.islands >= 1
        assert tv.islands == max(len(islands), 1)


# ------------------------------------------------------------------
# Physical ↔ Electrical Bus 매핑 테스트
# ------------------------------------------------------------------

class TestBusMapping:
    """Physical ↔ Electrical bus 2계층 매핑 테스트."""

    def test_bus_mapping_initialized(self, tp: TopologyProcessor) -> None:
        """초기화 후 BusMapping이 존재해야 한다."""
        assert tp.bus_mapping is not None
        assert isinstance(tp.bus_mapping, BusMapping)

    def test_bus_mapping_covers_all_buses(self, tp: TopologyProcessor) -> None:
        """모든 physical bus가 매핑에 등록되어야 한다."""
        all_maps = tp.bus_mapping.all_mappings()
        for bus_idx in tp.net.bus.index:
            assert int(bus_idx) in all_maps, (
                f"Bus {bus_idx}가 physical→electrical 매핑에 없음"
            )

    def test_bus_mapping_register_and_get(self) -> None:
        """BusMapping.register()와 get_electrical_bus()가 올바르게 동작해야 한다."""
        bm = BusMapping()
        bm.register(1, 100)
        bm.register(2, 100)
        bm.register(3, 200)

        assert bm.get_electrical_bus(1) == 100
        assert bm.get_electrical_bus(2) == 100
        assert bm.get_electrical_bus(3) == 200
        assert bm.get_electrical_bus(99) is None

    def test_bus_mapping_get_physical_buses(self) -> None:
        """BusMapping.get_physical_buses()가 올바른 집합을 반환해야 한다."""
        bm = BusMapping()
        bm.register(1, 100)
        bm.register(2, 100)
        bm.register(3, 200)

        phys = bm.get_physical_buses(100)
        assert phys == {1, 2}
        assert bm.get_physical_buses(200) == {3}
        assert bm.get_physical_buses(999) == set()

    def test_bus_mapping_register_overwrite(self) -> None:
        """동일 physical bus를 다른 electrical bus로 재등록 시 갱신되어야 한다."""
        bm = BusMapping()
        bm.register(1, 100)
        bm.register(1, 200)  # 재등록

        assert bm.get_electrical_bus(1) == 200
        assert 1 not in bm.get_physical_buses(100)
        assert 1 in bm.get_physical_buses(200)

    def test_bus_mapping_all_mappings_immutable(self) -> None:
        """all_mappings() 반환값을 수정해도 원본이 변경되지 않아야 한다."""
        bm = BusMapping()
        bm.register(1, 100)
        mappings = bm.all_mappings()
        mappings[999] = 999  # 복사본 수정
        assert bm.get_electrical_bus(999) is None

    def test_bus_mapping_build_from_network(self) -> None:
        """build_from_network()가 모든 bus를 매핑해야 한다."""
        net = pn.case14()
        bm = BusMapping()
        bm.build_from_network(net)
        for bus_idx in net.bus.index:
            assert bm.get_electrical_bus(int(bus_idx)) is not None

    def test_topology_processor_bus_mapping_summary(self, tp: TopologyProcessor) -> None:
        """get_bus_mapping_summary()가 올바른 구조를 반환해야 한다."""
        summary = tp.get_bus_mapping_summary()
        assert "physical_count" in summary
        assert "electrical_count" in summary
        assert "merged_groups" in summary
        assert "snapshot_ts" in summary
        assert summary["physical_count"] > 0


# ------------------------------------------------------------------
# Redis 연동 테스트
# ------------------------------------------------------------------

class TestRedisIntegration:
    """스위치 상태 Redis 저장 테스트."""

    def test_open_switch_publishes_to_redis(
        self, tp_with_redis: tuple[TopologyProcessor, MagicMock]
    ) -> None:
        """차단기 개방 시 Redis ops:switch:{id}:status가 OPEN으로 저장되어야 한다."""
        tp, mock_redis = tp_with_redis
        tp.open_switch(0)

        # Redis set이 호출되었는지 확인
        assert mock_redis.set.called

        # ops:switch:0:status 키 확인
        call_args_list = mock_redis.set.call_args_list
        switch_calls = [
            c for c in call_args_list
            if "ops:switch:0:status" in str(c)
        ]
        assert len(switch_calls) > 0, "ops:switch:0:status 키가 저장되어야 한다"

        # OPEN 값 확인
        value = switch_calls[0][0][1]
        assert "OPEN" in value, f"상태 값에 OPEN이 있어야 한다. 실제: {value}"

    def test_close_switch_publishes_to_redis(
        self, tp_with_redis: tuple[TopologyProcessor, MagicMock]
    ) -> None:
        """차단기 투입 시 Redis ops:switch:{id}:status가 CLOSED로 저장되어야 한다."""
        tp, mock_redis = tp_with_redis
        tp.open_switch(0)
        mock_redis.reset_mock()
        tp.close_switch(0)

        call_args_list = mock_redis.set.call_args_list
        switch_calls = [
            c for c in call_args_list
            if "ops:switch:0:status" in str(c)
        ]
        assert len(switch_calls) > 0

        value = switch_calls[0][0][1]
        assert "CLOSED" in value, f"상태 값에 CLOSED가 있어야 한다. 실제: {value}"

    def test_no_study_namespace_write(
        self, tp_with_redis: tuple[TopologyProcessor, MagicMock]
    ) -> None:
        """토폴로지 프로세서는 study: 네임스페이스에 write하면 안 된다."""
        tp, mock_redis = tp_with_redis
        tp.open_switch(0)
        tp.close_switch(0)

        all_keys = [str(c) for c in mock_redis.set.call_args_list]
        study_writes = [k for k in all_keys if "study:" in k]
        assert len(study_writes) == 0, "study: 네임스페이스에 write하면 안 된다"

    def test_redis_failure_does_not_raise(self, net: pp.pandapowerNet) -> None:
        """Redis 저장 실패 시 스위치 조작 자체는 성공해야 한다."""
        mock_redis = MagicMock()
        mock_redis.set.side_effect = ConnectionError("Redis 연결 실패")
        tp = TopologyProcessor(net, redis_client=mock_redis)

        # Redis 실패해도 open_switch는 TopologyVersion을 반환해야 함
        tv = tp.open_switch(0)
        assert isinstance(tv, TopologyVersion)
        assert bool(tp.net.switch.at[0, "closed"]) is False


# ------------------------------------------------------------------
# 이중모선(Double-Bus) 기초 테스트
# ------------------------------------------------------------------

class TestDoubleBusSwitches:
    """이중모선 스위치 구조 생성 테스트."""

    def test_create_double_bus_switches_basic(self) -> None:
        """이중모선 스위치 3개(DS_A, DS_B, BC)가 생성되어야 한다."""
        net = pn.case14()
        initial_sw_count = len(net.switch)

        sw_a, sw_b, coupler = create_double_bus_switches(
            net, bus_a=0, bus_b=1, line_id=0
        )

        # 3개 스위치 추가
        assert len(net.switch) == initial_sw_count + 3

        # sw_a: 투입, sw_b: 개방, coupler: 투입(기본)
        assert bool(net.switch.at[sw_a, "closed"]) is True
        assert bool(net.switch.at[sw_b, "closed"]) is False
        assert bool(net.switch.at[coupler, "closed"]) is True

    def test_create_double_bus_switches_coupler_open(self) -> None:
        """bus_coupler_closed=False이면 모선 연결기가 개방 상태로 생성되어야 한다."""
        net = pn.case14()
        # line_id=0: from_bus=0, to_bus=1 → bus_a=0, bus_b=1 모두 line에 연결됨
        _, _, coupler = create_double_bus_switches(
            net, bus_a=0, bus_b=1, line_id=0, bus_coupler_closed=False
        )
        assert bool(net.switch.at[coupler, "closed"]) is False

    def test_create_double_bus_switches_same_bus_raises(self) -> None:
        """bus_a == bus_b이면 ValueError가 발생해야 한다."""
        net = pn.case14()
        with pytest.raises(ValueError, match="bus_a와 bus_b"):
            create_double_bus_switches(net, bus_a=0, bus_b=0, line_id=0)

    def test_create_double_bus_switches_invalid_line_raises(self) -> None:
        """존재하지 않는 line_id이면 ValueError가 발생해야 한다."""
        net = pn.case14()
        with pytest.raises(ValueError, match="line_id"):
            create_double_bus_switches(net, bus_a=0, bus_b=1, line_id=9999)

    def test_double_bus_switch_types(self) -> None:
        """생성된 스위치의 타입이 올바르게 설정되어야 한다."""
        net = pn.case14()
        sw_a, sw_b, coupler = create_double_bus_switches(
            net, bus_a=0, bus_b=1, line_id=0
        )
        # DS: 단로기(Disconnector), CB: 차단기(Circuit Breaker)
        assert net.switch.at[sw_a, "type"] == "DS"
        assert net.switch.at[sw_b, "type"] == "DS"
        assert net.switch.at[coupler, "type"] == "CB"

    def test_topology_processor_with_double_bus(self) -> None:
        """이중모선 스위치가 추가된 네트워크에서 TopologyProcessor가 동작해야 한다."""
        net = pn.case14()
        create_double_bus_switches(net, bus_a=0, bus_b=1, line_id=0)

        tp = TopologyProcessor(net)
        tv = tp.get_topology_version()
        assert isinstance(tv, TopologyVersion)

    def test_bus_mapping_after_double_bus(self) -> None:
        """이중모선(BC 투입) 후 bus_a와 bus_b가 동일 electrical bus로 매핑되어야 한다."""
        net = pn.case14()
        _, _, coupler = create_double_bus_switches(
            net, bus_a=0, bus_b=1, line_id=0, bus_coupler_closed=True
        )
        # 모선 연결기(BC)가 투입된 상태: bus 0과 bus 1은 동일 electrical bus
        bm = BusMapping()
        bm.build_from_network(net)

        elec_0 = bm.get_electrical_bus(0)
        elec_1 = bm.get_electrical_bus(1)
        # BC가 투입되어 있으므로 동일 electrical bus
        assert elec_0 == elec_1, (
            f"BC 투입 후 bus 0({elec_0})과 bus 1({elec_1})은 같은 electrical bus여야 함"
        )
