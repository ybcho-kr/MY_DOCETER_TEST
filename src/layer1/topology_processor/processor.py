"""토폴로지 프로세서 — 차단기 상태 기반 계통 토폴로지 관리.

차단기(CB) 개폐에 따른 bus merge/split, 전기적 섬(island) 감지.

v5.1 Phase 1 구현 범위:
  - 차단기 개폐 및 토폴로지 버전 관리
  - Physical bus ↔ Electrical bus 2계층 매핑
  - 전기적 섬(island) 감지
  - Redis ops:switch:{sw_id}:status 연동 (ops: write 전용)
  - 이중모선(double-bus) 기초 지원

설계 원칙:
  - ops: 네임스페이스만 write. study: 절대 금지.
  - snapshot_ts 필수 포함.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandapower as pp
import pandapower.topology as top

from src.shared.schemas.grid import TopologyVersion

logger = logging.getLogger(__name__)


class BusMapping:
    """Physical bus ↔ Electrical bus 2계층 매핑 컨테이너.

    Physical bus: 변전소 내 실제 설비 위치 (예: 신서울 1번 모선).
    Electrical bus: 차단기 투입 상태에 따라 동일 전위로 연결된 버스 묶음.

    이중모선(double-bus) 변전소에서 모선 선택기 위치에 따라
    Physical bus 1개가 서로 다른 Electrical bus에 연결될 수 있다.
    """

    def __init__(self) -> None:
        # physical_bus_id → electrical_bus_id 매핑
        self._phys_to_elec: dict[int, int] = {}
        # electrical_bus_id → set of physical_bus_id
        self._elec_to_phys: dict[int, set[int]] = {}

    def register(self, physical_bus: int, electrical_bus: int) -> None:
        """Physical bus를 Electrical bus에 등록한다.

        Args:
            physical_bus: Physical bus ID (pandapower bus index).
            electrical_bus: Electrical bus ID.
        """
        # 기존 매핑이 있으면 이전 Electrical bus 그룹에서 제거
        old_elec = self._phys_to_elec.get(physical_bus)
        if old_elec is not None and old_elec != electrical_bus:
            self._elec_to_phys.setdefault(old_elec, set()).discard(physical_bus)

        self._phys_to_elec[physical_bus] = electrical_bus
        self._elec_to_phys.setdefault(electrical_bus, set()).add(physical_bus)

    def get_electrical_bus(self, physical_bus: int) -> int | None:
        """Physical bus에 대응하는 Electrical bus ID 반환.

        Args:
            physical_bus: Physical bus ID.

        Returns:
            Electrical bus ID. 등록되지 않은 경우 None.
        """
        return self._phys_to_elec.get(physical_bus)

    def get_physical_buses(self, electrical_bus: int) -> set[int]:
        """Electrical bus에 속한 Physical bus ID 집합 반환.

        Args:
            electrical_bus: Electrical bus ID.

        Returns:
            Physical bus ID 집합. 없으면 빈 집합.
        """
        return set(self._elec_to_phys.get(electrical_bus, set()))

    def all_mappings(self) -> dict[int, int]:
        """전체 physical→electrical 매핑 사전 반환 (불변 복사본)."""
        return dict(self._phys_to_elec)

    def build_from_network(self, net: pp.pandapowerNet) -> None:
        """pandapower 네트워크의 스위치 상태를 기반으로 매핑 재구성.

        투입된(closed) bus-bus 스위치로 연결된 Physical bus들을
        동일 Electrical bus로 매핑한다.
        Union-Find(Disjoint Set) 알고리즘 사용.

        Args:
            net: pandapower 네트워크 (switch 테이블 포함).
        """
        # 초기화
        self._phys_to_elec.clear()
        self._elec_to_phys.clear()

        all_bus_ids = list(net.bus.index)
        # 초기에는 각 physical bus가 자기 자신의 electrical bus
        parent: dict[int, int] = {b: b for b in all_bus_ids}

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # path compression
                x = parent[x]
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        # bus-bus 스위치(et='b') 중 closed인 것으로 union
        if not net.switch.empty and "et" in net.switch.columns:
            for sw_idx in net.switch.index:
                if (
                    net.switch.at[sw_idx, "et"] == "b"
                    and bool(net.switch.at[sw_idx, "closed"])
                ):
                    bus_a = int(net.switch.at[sw_idx, "bus"])
                    bus_b = int(net.switch.at[sw_idx, "element"])
                    if bus_a in parent and bus_b in parent:
                        _union(bus_a, bus_b)

        # 최종 매핑 등록
        for b in all_bus_ids:
            self.register(b, _find(b))

        logger.debug(
            "Bus 매핑 재구성 완료: physical=%d, electrical=%d",
            len(self._phys_to_elec),
            len(self._elec_to_phys),
        )


class TopologyProcessor:
    """계통 토폴로지 프로세서.

    pandapower 네트워크의 스위치 상태를 변경하고
    토폴로지 버전 및 전기적 섬 정보를 관리.

    Redis 클라이언트가 주입되면 스위치 상태 변경 시
    ops:switch:{sw_id}:status 키에 저장한다.
    """

    def __init__(
        self,
        net: pp.pandapowerNet,
        redis_client: Any = None,
    ) -> None:
        """초기화.

        Args:
            net: pandapower 네트워크 (switch 테이블 포함).
            redis_client: Redis 클라이언트 (None이면 Redis 저장 생략).
        """
        self._net = net
        self._redis = redis_client
        self._version = 0
        self._bus_mapping = BusMapping()
        # 초기 매핑 구성
        self._bus_mapping.build_from_network(net)

    @property
    def net(self) -> pp.pandapowerNet:
        """pandapower 네트워크."""
        return self._net

    @property
    def bus_mapping(self) -> BusMapping:
        """Physical ↔ Electrical bus 매핑 객체."""
        return self._bus_mapping

    def _publish_switch_status(self, switch_id: int, closed: bool) -> None:
        """스위치 상태를 Redis ops:switch:{sw_id}:status에 저장.

        Args:
            switch_id: pandapower switch index.
            closed: 투입(True) / 개방(False).
        """
        if self._redis is None:
            return
        key = f"ops:switch:{switch_id}:status"
        value = "CLOSED" if closed else "OPEN"
        snapshot_ts = datetime.now(timezone.utc).isoformat()
        try:
            self._redis.set(
                key,
                f'{{"status":"{value}","snapshot_ts":"{snapshot_ts}"}}',
            )
            logger.debug("Redis 저장: %s = %s", key, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 저장 실패: key=%s, error=%s", key, exc)

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
        # 버스 매핑 재구성 (bus-bus 스위치 개방 시 electrical bus 분리 가능)
        self._bus_mapping.build_from_network(self._net)
        self._publish_switch_status(switch_id, closed=False)
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
        # 버스 매핑 재구성 (bus-bus 스위치 투입 시 electrical bus 병합 가능)
        self._bus_mapping.build_from_network(self._net)
        self._publish_switch_status(switch_id, closed=True)
        logger.info("차단기 %d 투입. 토폴로지 버전 %d", switch_id, self._version)
        return self.get_topology_version()

    def detect_islands(self) -> list[set[int]]:
        """전기적 섬(island) 감지.

        pandapower topology 모듈의 create_nxgraph를 사용하여
        연결 컴포넌트를 계산한다.

        Returns:
            섬별 모선 인덱스 집합 리스트. 정상 시 1개 섬.
        """
        import networkx as nx  # noqa: PLC0415

        mg = top.create_nxgraph(self._net, respect_switches=True)
        components = list(nx.connected_components(mg))
        n_islands = len(components)

        if n_islands > 1:
            logger.warning(
                "계통 분리 감지: %d개 섬 발생. 운영자 확인 필요.",
                n_islands,
            )
        return [set(c) for c in components]

    def get_topology_version(self) -> TopologyVersion:
        """현재 토폴로지 버전 정보 반환.

        Returns:
            TopologyVersion 스키마 객체.
        """
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

    def get_bus_mapping_summary(self) -> dict[str, Any]:
        """Physical ↔ Electrical bus 매핑 요약 정보 반환.

        Returns:
            sdict: physical_count, electrical_count, mappings(일부 샘플).
        """
        all_maps = self._bus_mapping.all_mappings()
        elec_groups = self._bus_mapping._elec_to_phys
        return {
            "physical_count": len(all_maps),
            "electrical_count": len(elec_groups),
            "merged_groups": [
                {"electrical_bus": elec, "physical_buses": sorted(phys)}
                for elec, phys in elec_groups.items()
                if len(phys) > 1  # 2개 이상 묶인 그룹만 표시
            ],
            "snapshot_ts": datetime.now(timezone.utc).isoformat(),
        }


# -------------------------------------------------------------------
# 이중모선(double-bus) 기초 지원 헬퍼
# -------------------------------------------------------------------

def create_double_bus_switches(
    net: pp.pandapowerNet,
    bus_a: int,
    bus_b: int,
    line_id: int,
    *,
    bus_coupler_closed: bool = True,
) -> tuple[int, int, int]:
    """이중모선 변전소 스위치 구조 생성.

    이중모선 변전소에서 선로는 두 모선 중 하나에 연결된다.
    선로 → Bus_A 또는 선로 → Bus_B 경로를 모선 분리기로 선택.
    Bus_A ↔ Bus_B 사이에 모선 연결기(bus coupler)도 추가.

    Args:
        net: pandapower 네트워크 (in-place 수정).
        bus_a: 이중모선 A (pandapower bus index).
        bus_b: 이중모선 B (pandapower bus index).
        line_id: 대상 선로 index.
        bus_coupler_closed: 모선 연결기 초기 상태.

    Returns:
        (sw_a_id, sw_b_id, coupler_id) — 생성된 스위치 인덱스 3개.

    Raises:
        ValueError: bus_a == bus_b 이거나 line_id가 없을 때.
    """
    if bus_a == bus_b:
        raise ValueError("이중모선: bus_a와 bus_b가 같으면 안 됩니다.")
    if line_id not in net.line.index:
        raise ValueError(f"line_id {line_id}가 네트워크에 없습니다.")

    # 선로 → Bus_A 연결 분리기 (기본 투입, Bus_A 선택)
    sw_a = pp.create_switch(
        net,
        bus=bus_a,
        element=line_id,
        et="l",
        closed=True,
        type="DS",  # Disconnector (단로기)
        name=f"DS_L{line_id}_BusA",
    )
    # 선로 → Bus_B 연결 분리기 (기본 개방, Bus_B 미선택)
    sw_b = pp.create_switch(
        net,
        bus=bus_b,
        element=line_id,
        et="l",
        closed=False,
        type="DS",
        name=f"DS_L{line_id}_BusB",
    )
    # Bus_A ↔ Bus_B 모선 연결기 (Bus Coupler)
    coupler = pp.create_switch(
        net,
        bus=bus_a,
        element=bus_b,
        et="b",
        closed=bus_coupler_closed,
        type="CB",
        name=f"BC_BusA{bus_a}_BusB{bus_b}",
    )
    logger.info(
        "이중모선 스위치 생성: line=%d, sw_a=%d, sw_b=%d, coupler=%d",
        line_id, sw_a, sw_b, coupler,
    )
    return sw_a, sw_b, coupler
