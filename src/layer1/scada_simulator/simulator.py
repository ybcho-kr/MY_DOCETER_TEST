"""SCADA 시뮬레이터 — pandapower 조류계산 실행 및 Redis 게시.

Redis Key Structure:
  ops:bus:{bus_id}:voltage     → BusVoltage JSON
  ops:line:{line_id}:loading   → LineLoading JSON
  ops:trafo:{trafo_id}:loading → 변압기 부하율 JSON (선택)
  ops:powerflow:latest         → PowerFlowResult JSON
  ops:powerflow:status         → "OK" | "FAILED"
  ops:snapshot_ts              → ISO 8601 timestamp

설계 원칙:
  - LLM 수치 생성 절대 금지 — pandapower 솔버 반환값만 사용
  - ops: 네임스페이스만 write (study: 절대 금지)
  - snapshot_ts 필수
  - 수렴 실패 시 이전 스냅샷 유지 + FAILED 플래그
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

# 한국 계통 표준 공칭 전압 등급 (kV)
_VALID_KV: frozenset[float] = frozenset({765.0, 345.0, 154.0, 66.0, 22.9})


def _nearest_valid_kv(kv: float) -> float:
    """입력 전압과 가장 가까운 한국 표준 공칭 전압을 반환.

    Args:
        kv: 임의 전압 값 (kV).

    Returns:
        _VALID_KV 중 가장 가까운 값.
    """
    return min(_VALID_KV, key=lambda v: abs(v - kv))


class ScadaSimulator:
    """pandapower 기반 SCADA 시뮬레이터.

    4초 주기로 조류계산을 실행하고 결과를 Redis ops: 키에 저장.
    수렴 실패 시 이전 스냅샷 유지 + FAILED 플래그.

    버그 수정 (v5.1):
      - publish_to_redis()가 run_powerflow()를 중복 호출하는 문제 수정.
        run_cycle() → run_powerflow() 1회 → publish_to_redis(result) 순서로 처리.
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
        self._last_result: PowerFlowResult | None = None

    @property
    def net(self) -> pp.pandapowerNet:
        """pandapower 네트워크 객체."""
        return self._net

    @property
    def last_result(self) -> PowerFlowResult | None:
        """마지막 조류계산 결과. run_powerflow() 미실행 시 None."""
        return self._last_result

    def run_powerflow(self) -> PowerFlowResult:
        """조류계산 실행 및 결과 반환.

        pandapower runpp() 결과를 PowerFlowResult 스키마로 변환.
        수렴 실패 시 converged=False인 결과 반환 (이전 스냅샷은 유지됨).

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

            # ext_grid, sgen도 발전원으로 포함
            total_gen = float(res_gen["p_mw"].sum()) if not res_gen.empty else 0.0
            if not res_ext.empty:
                total_gen += float(res_ext["p_mw"].sum())
            if hasattr(self._net, "res_sgen") and not self._net.res_sgen.empty:
                total_gen += float(self._net.res_sgen["p_mw"].sum())

            total_load = float(res_load["p_mw"].sum()) if not res_load.empty else 0.0

            result = PowerFlowResult(
                converged=True,
                iterations=0,
                max_vm_pu=float(res_bus["vm_pu"].max()),
                min_vm_pu=float(res_bus["vm_pu"].min()),
                max_loading_pct=(
                    float(res_line["loading_percent"].max()) if len(res_line) > 0 else 0.0
                ),
                total_p_gen_mw=total_gen,
                total_p_load_mw=total_load,
                total_loss_mw=max(0.0, total_gen - total_load),
                snapshot_ts=now,
            )
        else:
            # 수렴 실패: converged=False, 이전 결과는 _last_result로 유지
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
        if converged:
            self._last_result = result  # 수렴 성공 시만 갱신 (이전 스냅샷 보존)
        return result

    def get_bus_voltages(self) -> list[BusVoltage]:
        """모선 전압 추출.

        pandapower res_bus 결과에서 BusVoltage 스키마 리스트 생성.
        runpp() 미실행 시 빈 리스트 반환.

        Returns:
            BusVoltage 리스트.
        """
        if self._net.res_bus.empty:
            return []

        import math  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        voltages: list[BusVoltage] = []

        for bus_idx in self._net.res_bus.index:
            vm_pu = float(self._net.res_bus.at[bus_idx, "vm_pu"])
            vn_kv = float(self._net.bus.at[bus_idx, "vn_kv"])

            # 비서비스 버스 또는 NaN 결과 건너뜀
            # (고립 버스 비활성화 후 res_bus에 NaN이 채워질 수 있음)
            if math.isnan(vm_pu) or math.isinf(vm_pu) or vm_pu <= 0:
                continue

            name = (
                str(self._net.bus.at[bus_idx, "name"])
                if "name" in self._net.bus.columns
                else f"Bus_{bus_idx}"
            )

            # pandapower bus index는 0부터 → BusVoltage.bus_id는 1 이상
            bus_id = int(bus_idx) + 1
            # IEEE 케이스의 비표준 전압은 가장 가까운 한국 표준으로 매핑
            nominal_kv = vn_kv if vn_kv in _VALID_KV else _nearest_valid_kv(vn_kv)

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

        Returns:
            LineLoading 리스트.
        """
        if self._net.res_line.empty:
            return []

        import math  # noqa: PLC0415

        now = datetime.now(timezone.utc)
        loadings: list[LineLoading] = []

        for line_idx in self._net.res_line.index:
            loading_pct = float(self._net.res_line.at[line_idx, "loading_percent"])
            p_from = float(self._net.res_line.at[line_idx, "p_from_mw"])
            q_from = float(self._net.res_line.at[line_idx, "q_from_mvar"])

            # NaN 결과 건너뜀 (비서비스 선로 또는 고립 버스 연결 선로)
            if math.isnan(loading_pct) or math.isnan(p_from):
                continue

            from_bus = int(self._net.line.at[line_idx, "from_bus"]) + 1
            to_bus = int(self._net.line.at[line_idx, "to_bus"]) + 1

            # 정격 용량 계산: max_i_ka * vn_kv * sqrt(3)
            max_i_ka = float(self._net.line.at[line_idx, "max_i_ka"])
            vn_kv = float(
                self._net.bus.at[self._net.line.at[line_idx, "from_bus"], "vn_kv"]
            )
            rating_mva = max_i_ka * vn_kv * (3**0.5)
            # rating_mva가 0 이하면 기본값 100 MVA (스키마 gt=0 조건 충족)
            if rating_mva <= 0:
                rating_mva = 100.0
                logger.warning(
                    "Line %d: rating_mva 계산 불가 (max_i_ka=%.4f, vn_kv=%.1f). "
                    "기본값 100 MVA 사용.",
                    line_idx, max_i_ka, vn_kv,
                )

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

    def publish_to_redis(self, result: PowerFlowResult | None = None) -> None:
        """조류계산 결과를 Redis ops: 키에 저장.

        [수정 v5.1] 이전 구현은 publish_to_redis() 내부에서 run_powerflow()를
        다시 호출하여 조류계산이 2회 실행되는 버그가 있었다.
        수정 후: result 인수로 이미 실행된 결과를 전달받아 재사용.

        Args:
            result: run_powerflow()로 얻은 결과. None이면 내부에서 1회 실행.

        Note:
            Redis 클라이언트가 None이면 아무 동작도 하지 않음.
        """
        if self._redis is None:
            return

        # result가 없으면 1회 실행 (단독 호출 시 하위 호환)
        if result is None:
            result = self.run_powerflow()

        now = result.snapshot_ts

        # 모선 전압
        for bv in self.get_bus_voltages():
            key = f"ops:bus:{bv.bus_id}:voltage"
            self._redis.set(key, bv.model_dump_json())

        # 선로 부하율
        for ll in self.get_line_loadings():
            key = f"ops:line:{ll.line_id}:loading"
            self._redis.set(key, ll.model_dump_json())

        # 조류계산 결과 요약
        self._redis.set("ops:powerflow:latest", result.model_dump_json())
        self._redis.set(
            "ops:powerflow:status",
            "OK" if result.converged else "FAILED",
        )
        self._redis.set("ops:snapshot_ts", now.isoformat())

        logger.debug(
            "Redis 게시 완료: buses=%d, lines=%d, status=%s",
            len(self._net.res_bus),
            len(self._net.res_line),
            "OK" if result.converged else "FAILED",
        )

    def run_cycle(self) -> PowerFlowResult:
        """SCADA 1주기 실행: 조류계산 → Redis 게시.

        수렴 실패 시 이전 스냅샷 유지 + FAILED 플래그.

        Returns:
            PowerFlowResult — 이번 주기 결과.
        """
        result = self.run_powerflow()

        if result.converged:
            # 수렴 성공: 최신 결과를 Redis에 게시
            self.publish_to_redis(result)
            logger.info(
                "SCADA 주기 완료: converged=%s, max_vm=%.4f pu, "
                "min_vm=%.4f pu, max_loading=%.1f%%, snapshot_ts=%s",
                result.converged,
                result.max_vm_pu,
                result.min_vm_pu,
                result.max_loading_pct,
                result.snapshot_ts.isoformat(),
            )
        else:
            # 수렴 실패: FAILED 플래그만 저장, 이전 스냅샷 유지
            if self._redis is not None:
                self._redis.set("ops:powerflow:status", "FAILED")
                self._redis.set(
                    "ops:snapshot_ts",
                    result.snapshot_ts.isoformat(),
                )
            logger.warning(
                "SCADA 주기 실패: 조류계산 수렴 실패. 이전 스냅샷 유지. "
                "snapshot_ts=%s",
                result.snapshot_ts.isoformat(),
            )

        return result
