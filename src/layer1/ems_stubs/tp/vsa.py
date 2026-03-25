"""전압 안정도 분석(VSA) — P-V 곡선 기반.

부하 증가 시 전압 붕괴 한계점(nose point) 탐색.
모든 수치는 pandapower 솔버 반환값 — LLM 생성 금지.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone

import pandapower as pp

from src.shared.schemas.tp import VSAResult

logger = logging.getLogger(__name__)


class VoltageStabilityAnalyzer:
    """전압 안정도 분석기.

    간이 P-V 곡선 분석: 부하를 단계적으로 증가시켜 수렴 한계 탐색.
    """

    def __init__(self, net: pp.pandapowerNet) -> None:
        self._net = net

    def run(self, load_steps: int = 20, max_scale: float = 2.0) -> VSAResult:
        """전압 안정도 분석 실행.

        Args:
            load_steps: 부하 증가 단계 수.
            max_scale: 최대 부하 배율 (2.0 = 200%).

        Returns:
            VSAResult 스키마.
        """
        now = datetime.now(timezone.utc)

        # 기준 조류계산
        try:
            pp.runpp(self._net)
        except pp.powerflow.LoadflowNotConverged:
            # 기준 케이스 수렴 실패
            return VSAResult(
                critical_bus_id=1,
                p_margin_mw=0.0,
                q_margin_mvar=0.0,
                nose_point_mw=0.0,
                snapshot_ts=now,
            )

        base_load_mw = float(self._net.res_load["p_mw"].sum())
        base_voltages = self._net.res_bus["vm_pu"].copy()

        # 단계적 부하 증가
        last_converged_scale = 1.0
        critical_bus_idx = int(base_voltages.idxmin())

        for step in range(1, load_steps + 1):
            scale = 1.0 + (max_scale - 1.0) * step / load_steps
            net_copy = copy.deepcopy(self._net)

            # 모든 부하 스케일링
            net_copy.load["p_mw"] *= scale
            net_copy.load["q_mvar"] *= scale

            try:
                pp.runpp(net_copy)
                last_converged_scale = scale

                # 전압이 가장 낮은 모선 추적
                min_v_idx = int(net_copy.res_bus["vm_pu"].idxmin())
                min_v = float(net_copy.res_bus["vm_pu"].min())
                if min_v < float(base_voltages.min()):
                    critical_bus_idx = min_v_idx

            except pp.powerflow.LoadflowNotConverged:
                # 수렴 실패 = nose point 도달
                break

        nose_point_mw = base_load_mw * last_converged_scale
        p_margin = nose_point_mw - base_load_mw

        # 무효전력 여유 추정 (간이)
        base_q_load = float(self._net.res_load["q_mvar"].sum())
        q_margin = base_q_load * (last_converged_scale - 1.0) if base_q_load > 0 else 0.0

        # critical_bus_id는 1 이상이어야 함 (스키마 제약)
        critical_bus_id = max(critical_bus_idx + 1, 1)

        return VSAResult(
            critical_bus_id=critical_bus_id,
            p_margin_mw=max(0.0, p_margin),
            q_margin_mvar=max(0.0, q_margin),
            nose_point_mw=max(0.0, nose_point_mw),
            snapshot_ts=now,
        )
