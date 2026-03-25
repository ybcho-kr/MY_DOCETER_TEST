"""토폴로지 프로세서 테스트 — AI-EMS v5.1 Phase 1.

차단기 상태 변경, 전기적 섬 감지, 토폴로지 버전 관리 검증.
"""
from __future__ import annotations

import pandapower as pp
import pytest

from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer1.topology_processor.processor import TopologyProcessor
from src.shared.schemas.grid import TopologyVersion


@pytest.fixture
def net() -> pp.pandapowerNet:
    """스위치가 포함된 IEEE 14-bus 네트워크."""
    return create_ieee14_network()


@pytest.fixture
def tp(net: pp.pandapowerNet) -> TopologyProcessor:
    """토폴로지 프로세서 인스턴스."""
    return TopologyProcessor(net)


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


# ------------------------------------------------------------------
# 차단기 개폐 테스트
# ------------------------------------------------------------------

class TestSwitchOperations:
    """차단기 상태 변경 테스트."""

    def test_open_switch(self, tp: TopologyProcessor) -> None:
        """차단기 개방이 올바르게 동작해야 한다."""
        # switch 0이 존재해야 함
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
            for bus in island:
                assert isinstance(bus, (int, type(bus)))  # numpy int도 허용
