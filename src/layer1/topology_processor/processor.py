"""토폴로지 프로세서 — 차단기 상태 기반 계통 토폴로지 관리.

차단기(CB) 개폐에 따른 bus merge/split, 전기적 섬(island) 감지.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandapower as pp
import pandapower.topology as top

from src.shared.schemas.grid import TopologyVersion

logger = logging.getLogger(__name__)


class TopologyProcessor:
    """계통 토폴로지 프로세서.

    pandapower 네트워크의 스위치 상태를 변경하고
    토폴로지 버전 및 전기적 섬 정보를 관리.
    """

    def __init__(self, net: pp.pandapowerNet) -> None:
        """초기화.

        Args:
            net: pandapower 네트워크 (switch 테이블 포함).
        """
        self._net = net
        self._version = 0

    @property
    def net(self) -> pp.pandapowerNet:
        """pandapower 네트워크."""
        return self._net

    def open_switch(self, switch_id: int) -> TopologyVersion:
        """차단기 개방 (선로 차단).

        Args:
            switch_id: pandapower switch index.

        Returns:
            갱신된 TopologyVersion.

        Raises:
            KeyError: switch_id가 존재하지 않을 때.
        """
        if switch_id not in self._net.switch.index:
            raise KeyError(f"Switch {switch_id} not found in network.")

        self._net.switch.at[switch_id, "closed"] = False
        self._version += 1
        logger.info("차단기 %d 개방. 토폴로지 버전 %d", switch_id, self._version)
        return self.get_topology_version()

    def close_switch(self, switch_id: int) -> TopologyVersion:
        """차단기 투입 (선로 연결).

        Args:
            switch_id: pandapower switch index.

        Returns:
            갱신된 TopologyVersion.

        Raises:
            KeyError: switch_id가 존재하지 않을 때.
        """
        if switch_id not in self._net.switch.index:
            raise KeyError(f"Switch {switch_id} not found in network.")

        self._net.switch.at[switch_id, "closed"] = True
        self._version += 1
        logger.info("차단기 %d 투입. 토폴로지 버전 %d", switch_id, self._version)
        return self.get_topology_version()

    def detect_islands(self) -> list[set[int]]:
        """전기적 섬(island) 감지.

        Returns:
            섬별 모선 인덱스 집합 리스트. 정상 시 1개 섬.
        """
        mg = top.create_nxgraph(self._net, respect_switches=True)
        import networkx as nx

        components = list(nx.connected_components(mg))
        return [set(c) for c in components]

    def get_topology_version(self) -> TopologyVersion:
        """현재 토폴로지 버전 정보 반환."""
        islands = self.detect_islands()
        in_service_buses = self._net.bus[self._net.bus["in_service"]].index
        in_service_lines = self._net.line[self._net.line["in_service"]].index
        in_service_gens = self._net.gen[self._net.gen["in_service"]].index

        return TopologyVersion(
            version=self._version,
            timestamp=datetime.now(timezone.utc),
            total_buses=len(in_service_buses),
            total_lines=len(in_service_lines),
            total_gens=len(in_service_gens),
            islands=max(len(islands), 1),
        )
