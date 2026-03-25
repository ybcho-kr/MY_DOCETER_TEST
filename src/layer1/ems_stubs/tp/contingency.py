"""N-1 상정고장 분석 — 2-Tier 방식 (PTDF screening + AC powerflow).

산업통상자원부고시 제2023-65호 제15조: 단일 설비 탈락 시 나머지 위반 없어야 함.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandapower as pp

from src.shared.schemas.tp import ContingencyCase, ContingencyResult

logger = logging.getLogger(__name__)


class ContingencyAnalyzer:
    """N-1 상정고장 분석기.

    2-Tier 방식:
      Tier-1: PTDF 기반 선별 (상위 20건)
      Tier-2: 선별된 케이스에 대해 AC 조류계산
    """

    def __init__(self, net: pp.pandapowerNet) -> None:
        self._net = net

    def generate_cases(self) -> list[ContingencyCase]:
        """N-1 케이스 자동 생성 (모든 선로 + 변압기).

        Returns:
            ContingencyCase 리스트.
        """
        cases: list[ContingencyCase] = []

        # 선로 탈락 케이스
        for line_idx in self._net.line[self._net.line["in_service"]].index:
            from_bus = int(self._net.line.at[line_idx, "from_bus"])
            to_bus = int(self._net.line.at[line_idx, "to_bus"])
            cases.append(
                ContingencyCase(
                    case_id=f"N1_LINE_{line_idx:03d}",
                    element_type="line",
                    element_id=int(line_idx),
                    description=f"선로 {line_idx} 탈락 (Bus {from_bus}→{to_bus})",
                )
            )

        # 변압기 탈락 케이스
        for trafo_idx in self._net.trafo[self._net.trafo["in_service"]].index:
            hv_bus = int(self._net.trafo.at[trafo_idx, "hv_bus"])
            lv_bus = int(self._net.trafo.at[trafo_idx, "lv_bus"])
            cases.append(
                ContingencyCase(
                    case_id=f"N1_TRAFO_{trafo_idx:03d}",
                    element_type="trafo",
                    element_id=int(trafo_idx),
                    description=f"변압기 {trafo_idx} 탈락 (Bus {hv_bus}→{lv_bus})",
                )
            )

        return cases

    def _ptdf_screening(
        self, cases: list[ContingencyCase], top_n: int = 20
    ) -> list[ContingencyCase]:
        """PTDF 기반 Tier-1 선별.

        각 케이스의 예상 부하율 변화를 계산하여 상위 N건 선별.
        간이 PTDF: 탈락 설비의 현재 조류가 큰 순서로 정렬.
        """
        if len(cases) <= top_n:
            return cases

        # 현재 조류계산 실행
        try:
            pp.runpp(self._net)
        except pp.powerflow.LoadflowNotConverged:
            return cases[:top_n]

        scored: list[tuple[float, ContingencyCase]] = []
        for case in cases:
            score = 0.0
            if case.element_type == "line" and case.element_id in self._net.res_line.index:
                score = abs(float(self._net.res_line.at[case.element_id, "p_from_mw"]))
            elif case.element_type == "trafo" and case.element_id in self._net.res_trafo.index:
                score = abs(float(self._net.res_trafo.at[case.element_id, "p_hv_mw"]))
            scored.append((score, case))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_n]]

    def run_n1(
        self,
        cases: list[ContingencyCase] | None = None,
        use_tier: bool = True,
        top_n: int = 20,
    ) -> ContingencyResult:
        """N-1 분석 실행.

        Args:
            cases: 분석할 케이스. None이면 자동 생성.
            use_tier: True면 2-Tier, False면 전체 AC.
            top_n: Tier-1 선별 건수.

        Returns:
            ContingencyResult 스키마.
        """
        now = datetime.now(timezone.utc)

        if cases is None:
            cases = self.generate_cases()

        # Tier-1: PTDF screening
        if use_tier:
            screened = self._ptdf_screening(cases, top_n)
        else:
            screened = cases

        violations: list[dict[str, Any]] = []
        converged_count = 0
        diverged_count = 0
        worst_voltage: float | None = None
        worst_loading: float | None = None

        for case in screened:
            # 네트워크 복사 → 설비 탈락 → 조류계산
            net_copy = copy.deepcopy(self._net)

            try:
                if case.element_type == "line":
                    net_copy.line.at[case.element_id, "in_service"] = False
                elif case.element_type == "trafo":
                    net_copy.trafo.at[case.element_id, "in_service"] = False
                elif case.element_type == "gen":
                    net_copy.gen.at[case.element_id, "in_service"] = False

                pp.runpp(net_copy)
                converged_count += 1

                # 위반 검사
                max_vm = float(net_copy.res_bus["vm_pu"].max())
                min_vm = float(net_copy.res_bus["vm_pu"].min())
                max_loading = float(net_copy.res_line["loading_percent"].max()) if len(net_copy.res_line) > 0 else 0.0

                # 전압 위반 (운용범위 ±10%)
                if max_vm > 1.1:
                    violations.append({
                        "case_id": case.case_id,
                        "element_type": "bus",
                        "element_id": int(net_copy.res_bus["vm_pu"].idxmax()),
                        "violation_type": "voltage",
                        "value": max_vm,
                        "limit": 1.1,
                    })
                if min_vm < 0.9:
                    violations.append({
                        "case_id": case.case_id,
                        "element_type": "bus",
                        "element_id": int(net_copy.res_bus["vm_pu"].idxmin()),
                        "violation_type": "voltage",
                        "value": min_vm,
                        "limit": 0.9,
                    })

                # 열용량 위반 (100%)
                if max_loading > 100.0:
                    overloaded = net_copy.res_line[
                        net_copy.res_line["loading_percent"] > 100.0
                    ]
                    for lidx in overloaded.index:
                        violations.append({
                            "case_id": case.case_id,
                            "element_type": "line",
                            "element_id": int(lidx),
                            "violation_type": "loading",
                            "value": float(overloaded.at[lidx, "loading_percent"]),
                            "limit": 100.0,
                        })

                # worst 갱신
                if worst_voltage is None or min_vm < worst_voltage:
                    worst_voltage = min_vm
                if worst_loading is None or max_loading > worst_loading:
                    worst_loading = max_loading

            except pp.powerflow.LoadflowNotConverged:
                diverged_count += 1
                violations.append({
                    "case_id": case.case_id,
                    "element_type": case.element_type,
                    "element_id": case.element_id,
                    "violation_type": "diverged",
                    "value": 0.0,
                    "limit": 0.0,
                })
            except Exception as e:
                diverged_count += 1
                logger.error("N-1 케이스 %s 오류: %s", case.case_id, e)

        return ContingencyResult(
            tier=1,
            contingencies=screened,
            violations=violations,
            converged_count=converged_count,
            diverged_count=diverged_count,
            worst_voltage_pu=worst_voltage,
            worst_loading_pct=worst_loading,
            snapshot_ts=now,
        )
