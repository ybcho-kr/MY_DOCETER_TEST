"""조류계산 엔진 — pandapower runpp() 기반.

모든 수치는 pandapower 솔버 반환값만 사용 — LLM 수치 생성 절대 금지.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandapower as pp

from src.shared.schemas.tp import PowerFlowResult
from src.shared.domain import get_voltage_limits

logger = logging.getLogger(__name__)


class PowerFlowEngine:
    """조류계산 엔진.

    pandapower runpp() 실행 및 위반사항 검출.
    """

    def __init__(
        self, net: pp.pandapowerNet, redis_client: Any = None
    ) -> None:
        self._net = net
        self._redis = redis_client
        self._voltage_limits = get_voltage_limits()

    @property
    def net(self) -> pp.pandapowerNet:
        return self._net

    def run(self) -> PowerFlowResult:
        """조류계산 실행.

        Returns:
            PowerFlowResult 스키마.
        """
        now = datetime.now(timezone.utc)
        try:
            pp.runpp(self._net)
            converged = True
        except pp.powerflow.LoadflowNotConverged:
            converged = False

        if not converged:
            return PowerFlowResult(
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

        res_bus = self._net.res_bus
        res_line = self._net.res_line
        res_gen = self._net.res_gen
        res_load = self._net.res_load
        res_ext = self._net.res_ext_grid

        total_gen = float(res_gen["p_mw"].sum())
        if not res_ext.empty:
            total_gen += float(res_ext["p_mw"].sum())
        total_load = float(res_load["p_mw"].sum())

        return PowerFlowResult(
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

    def get_violations(self) -> list[dict[str, Any]]:
        """전압 및 열용량 위반사항 검출.

        voltage_limits.json 기준값 사용.
        """
        if self._net.res_bus.empty:
            return []

        violations: list[dict[str, Any]] = []
        vs = self._voltage_limits.get("voltage_standards", {})
        levels = vs.get("levels", {}) if isinstance(vs, dict) else {}

        # 전압 등급별 기준 매핑: kV → 기준값
        limits_by_kv: dict[float, dict] = {}
        kv_key_map = {345.0: "345kV", 154.0: "154kV", 66.0: "66kV", 22.9: "22.9kV", 765.0: "765kV"}
        for kv_val, key in kv_key_map.items():
            if key in levels:
                limits_by_kv[kv_val] = levels[key]

        # 모선 전압 위반 검사
        for bus_idx in self._net.res_bus.index:
            if not self._net.bus.at[bus_idx, "in_service"]:
                continue
            vm_pu = float(self._net.res_bus.at[bus_idx, "vm_pu"])
            vn_kv = float(self._net.bus.at[bus_idx, "vn_kv"])

            limit = limits_by_kv.get(vn_kv)
            if limit:
                op_min = limit.get("operating_min_pu", 0.9)
                op_max = limit.get("operating_max_pu", 1.1)
                target_min = limit.get("target_min_pu", 0.95)
                target_max = limit.get("target_max_pu", 1.05)

                if vm_pu < op_min or vm_pu > op_max:
                    violations.append({
                        "element_type": "bus",
                        "element_id": int(bus_idx),
                        "violation_type": "voltage",
                        "value": vm_pu,
                        "limit": op_min if vm_pu < op_min else op_max,
                        "severity": "CRITICAL",
                        "message": f"Bus {bus_idx}: 전압 {vm_pu:.4f}pu 운용범위 초과",
                    })
                elif vm_pu < target_min or vm_pu > target_max:
                    violations.append({
                        "element_type": "bus",
                        "element_id": int(bus_idx),
                        "violation_type": "voltage",
                        "value": vm_pu,
                        "limit": target_min if vm_pu < target_min else target_max,
                        "severity": "WARNING",
                        "message": f"Bus {bus_idx}: 전압 {vm_pu:.4f}pu 조정목표 초과",
                    })

        # 선로 열용량 위반 검사
        for line_idx in self._net.res_line.index:
            if not self._net.line.at[line_idx, "in_service"]:
                continue
            loading = float(self._net.res_line.at[line_idx, "loading_percent"])
            if loading >= 100.0:
                violations.append({
                    "element_type": "line",
                    "element_id": int(line_idx),
                    "violation_type": "loading",
                    "value": loading,
                    "limit": 100.0,
                    "severity": "CRITICAL",
                    "message": f"Line {line_idx}: 부하율 {loading:.1f}% 과부하",
                })
            elif loading >= 80.0:
                violations.append({
                    "element_type": "line",
                    "element_id": int(line_idx),
                    "violation_type": "loading",
                    "value": loading,
                    "limit": 80.0,
                    "severity": "WARNING",
                    "message": f"Line {line_idx}: 부하율 {loading:.1f}% 경고",
                })

        return violations
