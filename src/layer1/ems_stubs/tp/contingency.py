"""N-1 상정고장 분석 — 2-Tier 방식 (PTDF screening + AC powerflow).

산업통상자원부고시 제2023-65호 제15조: 단일 설비 탈락 시 나머지 위반 없어야 함.

v0.2.0 개선사항:
  - PTDF 기반 Tier-1 screening 정확도 개선
  - DC 기반 감도 분석으로 선로 과부하 예측
  - 단순 절대 조류값 대신 LODFs(Line Outage Distribution Factors) 활용
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


def _build_ptdf_matrix(net: pp.pandapowerNet) -> np.ndarray | None:
    """DC 기반 PTDF(Power Transfer Distribution Factor) 행렬 계산.

    PTDF[l, b] = 선로 l의 조류가 모선 b 주입 전력 1MW 변화 시 변하는 비율.

    pandapower makePTDF(또는 직접 B-matrix 역행렬)를 사용하여 계산한다.
    수렴 실패 또는 계통 규모 과대 시 None 반환.

    Args:
        net: pandapower 계통 모델 (runpp() 실행 완료 상태).

    Returns:
        PTDF 행렬 (n_lines × n_buses). 계산 실패 시 None.
    """
    try:
        # pandapower 내장 PTDF 계산 시도
        from pandapower.pypower.makePTDF import makePTDF
        from pandapower.pd2ppc import _pd2ppc

        # ppc 변환
        ppc, _ = _pd2ppc(net)
        ptdf = makePTDF(ppc["baseMVA"], ppc["bus"], ppc["branch"])
        return ptdf  # type: ignore[return-value]
    except Exception as exc:
        logger.debug("pandapower makePTDF 실패, 대안 방법 시도: %s", exc)

    # 대안: 직접 B-matrix 기반 DC-PTDF 계산
    try:
        return _calc_dc_ptdf(net)
    except Exception as exc:
        logger.warning("DC-PTDF 계산 실패: %s", exc)
        return None


def _calc_dc_ptdf(net: pp.pandapowerNet) -> np.ndarray:
    """DC 기반 PTDF 행렬 직접 계산.

    B-matrix(DC susceptance matrix)의 역행렬을 이용한 감도 계산.
    PTDF[l, b] = x_l^{-1} × (A × B_red^{-1})[l, b]
    여기서 x_l은 선로 l의 리액턴스, A는 incidence matrix, B_red는 감소 B-matrix.

    Args:
        net: pandapower 계통 모델.

    Returns:
        PTDF 행렬 (n_lines × n_buses).

    Raises:
        np.linalg.LinAlgError: B-matrix가 특이 행렬인 경우.
    """
    n_bus = len(net.bus)
    n_line = len(net.line[net.line["in_service"]])

    if n_bus == 0 or n_line == 0:
        return np.zeros((n_line, n_bus))

    # 버스 인덱스 매핑 (0-based)
    bus_index = {bus_id: i for i, bus_id in enumerate(net.bus.index)}
    active_lines = net.line[net.line["in_service"]]

    # B-matrix 구성 (DC 가정: r ≈ 0, b_l = 1/x_l)
    B = np.zeros((n_bus, n_bus))
    line_indices = []
    b_lines = []  # 선로별 서셉턴스

    for _, row in active_lines.iterrows():
        f_bus = bus_index[row["from_bus"]]
        t_bus = bus_index[row["to_bus"]]
        x_pu = float(row["x_ohm_per_km"]) * float(row["length_km"]) / (
            float(net.bus.at[row["from_bus"], "vn_kv"]) ** 2
            / float(net.sn_mva if hasattr(net, "sn_mva") else 100.0)
        ) if float(row.get("length_km", 0)) > 0 else 1e-6

        # 리액턴스가 0에 가까우면 대용량 차단기로 처리
        if abs(x_pu) < 1e-10:
            x_pu = 1e-6

        b_l = 1.0 / x_pu
        B[f_bus, f_bus] += b_l
        B[t_bus, t_bus] += b_l
        B[f_bus, t_bus] -= b_l
        B[t_bus, f_bus] -= b_l
        line_indices.append((f_bus, t_bus))
        b_lines.append(b_l)

    # Slack 버스 제거 (첫 번째 버스 = slack 가정)
    # B_red = B[1:, 1:]
    B_red = B[1:, 1:]
    try:
        B_red_inv = np.linalg.inv(B_red)
    except np.linalg.LinAlgError:
        # 특이 행렬 → pseudo-inverse 사용
        B_red_inv = np.linalg.pinv(B_red)

    # PTDF[l, b] = b_l × (e_f - e_t) @ B_red_inv @ e_b
    ptdf = np.zeros((len(line_indices), n_bus))
    for l_idx, ((f_bus, t_bus), b_l) in enumerate(zip(line_indices, b_lines)):
        for b_idx in range(n_bus):
            if b_idx == 0:  # slack bus
                ptdf[l_idx, b_idx] = 0.0
                continue
            col = b_idx - 1  # B_red 인덱스
            psi_f = B_red_inv[f_bus - 1, col] if f_bus > 0 else 0.0
            psi_t = B_red_inv[t_bus - 1, col] if t_bus > 0 else 0.0
            ptdf[l_idx, b_idx] = b_l * (psi_f - psi_t)

    return ptdf


def _calc_lodf(
    ptdf: np.ndarray,
    net: pp.pandapowerNet,
) -> np.ndarray:
    """LODF(Line Outage Distribution Factor) 행렬 계산.

    LODF[l, k] = 선로 k 탈락 시 선로 l에 발생하는 조류 변화 비율.
    LODF[l, k] = PTDF[l, f_k→t_k] / (1 - PTDF[k, f_k→t_k])

    ptdf 행렬의 행 수(n_branches)가 active_lines 수와 다를 수 있으므로
    min(ptdf_rows, n_lines)으로 맞춰서 계산한다.

    Args:
        ptdf: PTDF 행렬 (n_branches × n_buses). 행 수는 선로 수 이상.
        net: pandapower 계통 모델.

    Returns:
        LODF 행렬 (n_lines × n_lines). 여기서 n_lines = in_service 선로 수.
    """
    active_lines = net.line[net.line["in_service"]]
    n_line = len(active_lines)
    n_ptdf_rows = ptdf.shape[0]
    bus_index = {bus_id: i for i, bus_id in enumerate(net.bus.index)}

    lodf = np.zeros((n_line, n_line))

    for k_idx, (_, k_row) in enumerate(active_lines.iterrows()):
        f_k = bus_index[k_row["from_bus"]]
        t_k = bus_index[k_row["to_bus"]]

        # 선로 k의 감도: PTDF[l, f_k] - PTDF[l, t_k]
        # ptdf 행 수 범위 내에서만 계산
        ptdf_rows_to_use = min(n_ptdf_rows, n_line)
        ptdf_k = ptdf[:ptdf_rows_to_use, f_k] - ptdf[:ptdf_rows_to_use, t_k]

        if k_idx < ptdf_rows_to_use:
            ptdf_kk = ptdf_k[k_idx]
        else:
            ptdf_kk = 0.0

        denom = 1.0 - ptdf_kk
        if abs(denom) > 1e-6:
            lodf[:ptdf_rows_to_use, k_idx] = ptdf_k / denom
        else:
            lodf[:ptdf_rows_to_use, k_idx] = 0.0  # 특이 케이스 (방사형 선로)

        lodf[k_idx, k_idx] = -1.0  # 탈락 선로 자체

    return lodf


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
        """LODF/PTDF 기반 Tier-1 선별 (개선된 DC 감도 분석).

        각 케이스 탈락 시 나머지 선로에 발생하는 최대 조류 변화를 예측하여
        상위 N건 선별. LODF 계산 가능 시 LODF 기반 정확한 예측 사용,
        실패 시 기존 방식(탈락 설비 절대 조류값) fallback.

        LODF 기반 선별 절차:
          1. 현재 기저 조류계산 실행
          2. DC-PTDF 행렬 계산
          3. LODF[l, k] = 선로 k 탈락 시 선로 l의 추가 조류 비율
          4. 케이스별 worst_lodf = max_l(|LODF[l,k]| × |p_l|) 계산
          5. worst_lodf 기준 상위 top_n 선별

        Args:
            cases: 전체 N-1 케이스 목록.
            top_n: 선별할 상위 건수.

        Returns:
            선별된 케이스 목록 (최대 top_n건).
        """
        if len(cases) <= top_n:
            return cases

        # 현재 조류계산 실행
        try:
            pp.runpp(self._net, verbose=False)
        except pp.powerflow.LoadflowNotConverged:
            logger.warning("PTDF screening: 조류계산 실패, 전체 케이스 상위 %d 반환", top_n)
            return cases[:top_n]

        # LODF/PTDF 기반 정확한 선별 시도
        ptdf = _build_ptdf_matrix(self._net)

        if ptdf is not None and len(self._net.line[self._net.line["in_service"]]) > 0:
            return self._lodf_screening(cases, top_n, ptdf)

        # Fallback: 탈락 설비의 절대 조류값 기준 정렬 (기존 방식)
        logger.debug("PTDF 계산 실패, 절대 조류값 기준 fallback 사용")
        return self._flow_based_screening(cases, top_n)

    def _lodf_screening(
        self,
        cases: list[ContingencyCase],
        top_n: int,
        ptdf: np.ndarray,
    ) -> list[ContingencyCase]:
        """LODF 기반 케이스 선별.

        각 선로 탈락 케이스에 대해 나머지 선로의 예상 최대 조류 증가를 계산.
        LODF[l, k] × |P_l_base| = 선로 k 탈락 시 선로 l의 조류 변화 (MW).

        Args:
            cases: N-1 케이스 목록 (선로 탈락 케이스만 LODF 사용).
            top_n: 선별 건수.
            ptdf: DC-PTDF 행렬.

        Returns:
            선별된 케이스 목록.
        """
        try:
            lodf = _calc_lodf(ptdf, self._net)
        except Exception as exc:
            logger.warning("LODF 계산 실패: %s. Fallback 사용.", exc)
            return self._flow_based_screening(cases, top_n)

        # 선로 기저 조류 (MW)
        active_lines = self._net.line[self._net.line["in_service"]]
        line_flows = np.array([
            abs(float(self._net.res_line.at[idx, "p_from_mw"]))
            for idx in active_lines.index
        ])

        # 선로 ID → LODF 행렬 인덱스 매핑
        line_id_to_idx: dict[int, int] = {
            int(lid): i for i, lid in enumerate(active_lines.index)
        }

        scored: list[tuple[float, ContingencyCase]] = []
        for case in cases:
            score = 0.0
            if case.element_type == "line" and case.element_id in line_id_to_idx:
                k_idx = line_id_to_idx[case.element_id]
                # worst-case 조류 변화: max_l(|LODF[l,k]| × |P_l|)
                score = float(np.max(np.abs(lodf[:, k_idx]) * line_flows))
            elif case.element_type == "trafo" and case.element_id in self._net.res_trafo.index:
                # 변압기는 LODF 미적용, 절대 조류값 사용
                score = abs(float(self._net.res_trafo.at[case.element_id, "p_hv_mw"]))
            scored.append((score, case))

        scored.sort(key=lambda x: x[0], reverse=True)
        logger.info(
            "LODF 기반 Tier-1 선별 완료: 전체 %d건 → 상위 %d건",
            len(cases),
            min(top_n, len(cases)),
        )
        return [c for _, c in scored[:top_n]]

    def _flow_based_screening(
        self,
        cases: list[ContingencyCase],
        top_n: int,
    ) -> list[ContingencyCase]:
        """절대 조류값 기반 케이스 선별 (Fallback).

        탈락 설비의 현재 조류가 클수록 영향이 크다고 가정하여 정렬.

        Args:
            cases: N-1 케이스 목록.
            top_n: 선별 건수.

        Returns:
            선별된 케이스 목록.
        """
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
