"""SCADA 시뮬레이터 — pandapower 조류계산 실행 및 Redis 게시.

Redis Key Structure:
  ops:bus:{bus_id}:voltage     → BusVoltage JSON
  ops:line:{line_id}:loading   → LineLoading JSON
  ops:powerflow:latest         → PowerFlowResult JSON
  ops:powerflow:status         → "OK" | "FAILED"
  ops:snapshot_ts              → ISO 8601 timestamp

설계 원칙:
  - LLM 수치 생성 절대 금지 — pandapower 솔버 반환값만 사용
  - ops: 네임스페이스만 write (study: 절대 금지)
  - snapshot_ts 필수
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandapower as pp

from src.shared.schemas.grid import BusVoltage, LineLoading
from src.shared.schemas.tp import PowerFlowResult

logger = logging.getLogger(__name__)


class ScadaSimulator:
    """pandapower 기반 SCADA 시뮬레이터.

    4초 주기로 조류계산을 실행하고 결과를 Redis ops: 키에 저장.
    수렴 실패 시 이전 스냅샷 유지 + FAILED 플래그.
    """

    def __init__(self, net: pp.pandapowerNet, redis_client: Any = None) -> None:
        """초기화.

        Args:
            net: pandapower 네트워크 객체.
            redis_client: Redis 클라이언트 (None이면 Redis 게시 생략).
        """
        self._net = net
        self._redis = redis_client
        self._last_snapshot_ts: datetime | None = None
        self._last_converged: bool = False

    @property
    def net(self) -> pp.pandapowerNet:
        """pandapower 네트워크 객체."""
        return self._net

    def run_powerflow(self) -> PowerFlowResult:
        """조류계산 실행 및 결과 반환.

        Returns:
            PowerFlowResult 스키마 객체.
        """
        now = datetime.now(timezone.utc)
        try:
            pp.runpp(self._net)
            converged = True
        except pp.powerflow.LoadflowNotConverged:
            converged = False

        if converged:
            res_bus = self._net.res_bus
            res_line = self._net.res_line
            res_gen = self._net.res_gen
            res_load = self._net.res_load
            res_ext = self._net.res_ext_grid

            # ext_grid도 발전원으로 포함
            total_gen = float(res_gen["p_mw"].sum())
            if not res_ext.empty:
                total_gen += float(res_ext["p_mw"].sum())
            total_load = float(res_load["p_mw"].sum())

            result = PowerFlowResult(
                converged=True,
                iterations=0,
                max_vm_pu=float(res_bus["vm_pu"].max()),
                min_vm_pu=float(res_bus["vm_pu"].min()),
                max_loading_pct=float(res_line["loading_percent"].max()) if len(res_line) > 0 else 0.0,
                total_p_gen_mw=total_gen,
                total_p_load_mw=total_load,
                total_loss_mw=max(0.0, total_gen - total_load),
                snapshot_ts=now,
            )
        else:
            # 수렴 실패: 이전 값 없이 기본 응답
            result = PowerFlowResult(
                converged=False,
                iterations=0,
                max_vm_pu=0.0,
                min_vm_pu=0.0,
                max_loading_pct=0.0,
                total_p_gen_mw=0.0,
                total_p_load_mw=0.0,
                total_loss_mw=0.0,
                snapshot_ts=now,
            )

        self._last_converged = converged
        self._last_snapshot_ts = now
        return result

    def get_bus_voltages(self) -> list[BusVoltage]:
        """모선 전압 추출.

        pandapower res_bus 결과에서 BusVoltage 스키마 리스트 생성.
        runpp() 미실행 시 빈 리스트 반환.
        """
        if self._net.res_bus.empty:
            return []

        now = datetime.now(timezone.utc)
        voltages: list[BusVoltage] = []

        # 한국 계통 표준 공칭 전압 (BusVoltage 스키마 validator)
        valid_kv = {765.0, 345.0, 154.0, 66.0, 22.9}

        # 비표준 전압 → 가장 가까운 표준 전압으로 매핑
        def _nearest_valid_kv(kv: float) -> float:
            return min(valid_kv, key=lambda v: abs(v - kv))

        for bus_idx in self._net.res_bus.index:
            vm_pu = float(self._net.res_bus.at[bus_idx, "vm_pu"])
            vn_kv = float(self._net.bus.at[bus_idx, "vn_kv"])
            name = str(self._net.bus.at[bus_idx, "name"]) if "name" in self._net.bus.columns else f"Bus_{bus_idx}"

            # pandapower bus index는 0부터 → BusVoltage.bus_id는 1 이상
            bus_id = int(bus_idx) + 1
            # IEEE 케이스의 비표준 전압은 가장 가까운 한국 표준으로 매핑
            nominal_kv = vn_kv if vn_kv in valid_kv else _nearest_valid_kv(vn_kv)

            voltages.append(
                BusVoltage(
                    bus_id=bus_id,
                    name=name,
                    voltage_pu=vm_pu,
                    voltage_kv=vm_pu * vn_kv,
                    nominal_kv=nominal_kv,
                    in_service=bool(self._net.bus.at[bus_idx, "in_service"]),
                    snapshot_ts=now,
                )
            )

        return voltages

    def get_line_loadings(self) -> list[LineLoading]:
        """선로 부하율 추출.

        pandapower res_line 결과에서 LineLoading 스키마 리스트 생성.
        """
        if self._net.res_line.empty:
            return []

        now = datetime.now(timezone.utc)
        loadings: list[LineLoading] = []

        for line_idx in self._net.res_line.index:
            loading_pct = float(self._net.res_line.at[line_idx, "loading_percent"])
            p_from = float(self._net.res_line.at[line_idx, "p_from_mw"])
            q_from = float(self._net.res_line.at[line_idx, "q_from_mvar"])
            from_bus = int(self._net.line.at[line_idx, "from_bus"]) + 1
            to_bus = int(self._net.line.at[line_idx, "to_bus"]) + 1

            # 정격 용량 계산: max_i_ka * vn_kv * sqrt(3)
            max_i_ka = float(self._net.line.at[line_idx, "max_i_ka"])
            vn_kv = float(self._net.bus.at[self._net.line.at[line_idx, "from_bus"], "vn_kv"])
            rating_mva = max_i_ka * vn_kv * (3**0.5)

            loadings.append(
                LineLoading(
                    line_id=int(line_idx),
                    from_bus=from_bus,
                    to_bus=to_bus,
                    loading_pct=loading_pct,
                    p_from_mw=p_from,
                    q_from_mvar=q_from,
                    rating_mva=rating_mva,
                    in_service=bool(self._net.line.at[line_idx, "in_service"]),
                    snapshot_ts=now,
                )
            )

        return loadings

    def publish_to_redis(self) -> None:
        """조류계산 결과를 Redis ops: 키에 저장.

        Redis 클라이언트가 None이면 아무 동작도 하지 않음.
        """
        if self._redis is None:
            return

        now = datetime.now(timezone.utc)

        # 모선 전압
        for bv in self.get_bus_voltages():
            key = f"ops:bus:{bv.bus_id}:voltage"
            self._redis.set(key, bv.model_dump_json())

        # 선로 부하율
        for ll in self.get_line_loadings():
            key = f"ops:line:{ll.line_id}:loading"
            self._redis.set(key, ll.model_dump_json())

        # 조류계산 결과 요약
        pf_result = self.run_powerflow()
        self._redis.set("ops:powerflow:latest", pf_result.model_dump_json())
        self._redis.set(
            "ops:powerflow:status",
            "OK" if pf_result.converged else "FAILED",
        )
        self._redis.set("ops:snapshot_ts", now.isoformat())

    def run_cycle(self) -> PowerFlowResult:
        """SCADA 1주기 실행: 조류계산 → Redis 게시.

        수렴 실패 시 이전 스냅샷 유지 + FAILED 플래그.

        Returns:
            PowerFlowResult — 이번 주기 결과.
        """
        result = self.run_powerflow()

        if result.converged:
            self.publish_to_redis()
            logger.info(
                "SCADA 주기 완료: converged=%s, max_vm=%.4f pu, max_loading=%.1f%%",
                result.converged,
                result.max_vm_pu,
                result.max_loading_pct,
            )
        else:
            # 수렴 실패: FAILED 플래그만 저장, 이전 스냅샷 유지
            if self._redis is not None:
                self._redis.set("ops:powerflow:status", "FAILED")
            logger.warning("SCADA 주기 실패: 조류계산 수렴 실패. 이전 스냅샷 유지.")

        return result
