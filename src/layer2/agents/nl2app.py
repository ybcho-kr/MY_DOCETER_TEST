"""NL2App 에이전트 — EMS 앱 결과 조회 (HOTL).

사용자 자연어 질의에서 앱 종류(SE/TP/AGC/SCA)를 파악하고,
Layer 1 모듈을 직접 호출하여 결과를 AIResponse로 조립한다.

지원 앱:
  - SE: 상태추정 결과 조회
  - TP: 조류계산 및 위반사항 조회
  - AGC: 주파수/예비력 조회
  - SCA: 단락전류 해석

설계 원칙:
  1. LLM 수치 생성 절대 금지 — Layer 1 솔버 반환값만 사용
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동
  4. Evidence chain 필수
"""
from __future__ import annotations

import time
from typing import Dict, List, Literal, Optional

import pandapower as pp

from src.layer1.ems_stubs.agc.controller import AGCController
from src.layer1.ems_stubs.se.estimator import StateEstimator
from src.layer1.ems_stubs.tp.powerflow import PowerFlowEngine
from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer2.agents.base import BaseAgent
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact


# 앱 키워드 → 앱 유형 매핑 (한국어 자연어 키워드)
_APP_KEYWORDS: Dict[str, str] = {
    # SE — 상태추정
    "상태추정": "SE",
    "상태 추정": "SE",
    "SE": "SE",
    "state estimation": "SE",
    "상태": "SE",
    # TP — 조류계산
    "조류계산": "TP",
    "조류 계산": "TP",
    "TP": "TP",
    "powerflow": "TP",
    "power flow": "TP",
    "조류": "TP",
    "전압위반": "TP",
    "과부하": "TP",
    "위반": "TP",
    "violations": "TP",
    # AGC — 자동발전제어
    "AGC": "AGC",
    "주파수": "AGC",
    "예비력": "AGC",
    "frequency": "AGC",
    "reserve": "AGC",
    "자동발전제어": "AGC",
    "ACE": "AGC",
    # SCA — 단락전류
    "단락": "SCA",
    "단락전류": "SCA",
    "SCA": "SCA",
    "shortcircuit": "SCA",
    "short circuit": "SCA",
}


def _detect_app(query: str) -> str:
    """질의에서 앱 유형 감지.

    키워드 매칭 기반으로 SE/TP/AGC/SCA 중 하나를 반환.
    감지 실패 시 기본값 'TP' 반환.

    Args:
        query: 사용자 자연어 질의.

    Returns:
        앱 유형 문자열 ('SE', 'TP', 'AGC', 'SCA').
    """
    query_upper = query.upper()
    for keyword, app in _APP_KEYWORDS.items():
        if keyword.upper() in query_upper:
            return app
    # 기본값: 조류계산 (가장 범용적)
    return "TP"


def _detect_bus_id(query: str) -> Optional[int]:
    """질의에서 모선 ID 감지 (SCA 용).

    '버스 3', 'bus 5', '3번 모선' 등 패턴에서 정수 추출.

    Args:
        query: 사용자 자연어 질의.

    Returns:
        감지된 모선 ID 또는 None.
    """
    import re

    patterns = [
        r"버스\s*(\d+)",
        r"bus\s*(\d+)",
        r"(\d+)번\s*모선",
        r"모선\s*(\d+)",
        r"bus_id[=:]\s*(\d+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


class NL2AppAgent(BaseAgent):
    """EMS 앱 결과 조회 에이전트 (HOTL).

    사용자 질의에서 앱 종류를 파악하고 Layer 1 모듈을 직접 호출한다.
    개발 모드: Layer 1 모듈 직접 import (httpx API 호출 대신).
    프로덕션 모드: httpx를 통한 API 호출로 전환 예정 (Phase 2+).
    """

    name: str = "nl2app"
    description: str = "EMS 앱 결과 조회 에이전트 — SE/TP/AGC/SCA 결과를 자연어로 반환"
    mode: Literal["HITL", "HOTL"] = "HOTL"

    def __init__(self, net: Optional[pp.pandapowerNet] = None) -> None:
        """NL2App 에이전트 초기화.

        Args:
            net: pandapower 네트워크. None이면 IEEE 14-bus 기본 케이스 사용.
        """
        # Layer 1 네트워크 — 개발 모드에서는 IEEE 14-bus 사용
        self._net: pp.pandapowerNet = net if net is not None else create_ieee14_network()

    async def run(self, context: AgentContext) -> AIResponse:
        """NL2App 에이전트 실행.

        1. 사용자 질의에서 앱 종류 파악 (SE/TP/AGC/SCA)
        2. 해당 Layer 1 모듈 직접 호출
        3. 결과를 AIResponse로 조립

        Args:
            context: 에이전트 컨텍스트.

        Returns:
            AIResponse — evidence_chain 포함.
        """
        app_type = _detect_app(context.user_query)

        if app_type == "SE":
            return await self._run_se(context)
        elif app_type == "TP":
            return await self._run_tp(context)
        elif app_type == "AGC":
            return await self._run_agc(context)
        elif app_type == "SCA":
            return await self._run_sca(context)
        else:
            return await self._run_tp(context)

    async def _run_se(self, context: AgentContext) -> AIResponse:
        """상태추정(SE) 실행 및 결과 반환.

        StateEstimator.run_estimation() 호출 — 수치는 솔버 반환값만.
        """
        t0 = time.perf_counter()
        estimator = StateEstimator(self._net)
        result = estimator.run_estimation()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        facts: List[StructuredFact] = [
            self._make_fact(
                "se_solved", result.solved, "pandapower:estimation:WLS"
            ),
            self._make_fact(
                "se_confidence_level",
                result.confidence_level,
                "pandapower:estimation:WLS",
                unit=None,
            ),
            self._make_fact(
                "se_observable_ratio",
                result.observable_ratio,
                "pandapower:estimation:observability",
                unit=None,
            ),
            self._make_fact(
                "se_max_residual",
                result.max_residual,
                "pandapower:estimation:LNR",
                unit=None,
            ),
        ]

        evidence: List[EvidenceStep] = [
            self._make_evidence(
                tool_name="StateEstimator.run_estimation",
                input_params={"network": "IEEE-14bus", "method": "WLS"},
                output_summary=(
                    f"solved={result.solved}, "
                    f"confidence_level={result.confidence_level:.3f}, "
                    f"observable_ratio={result.observable_ratio:.3f}, "
                    f"max_residual={result.max_residual:.4f}, "
                    f"iterations={result.iterations}"
                ),
                duration_ms=elapsed_ms,
            )
        ]

        warnings: List[str] = []
        if not result.solved:
            warnings.append("상태추정 수렴 실패 — 조류계산 fallback 결과입니다.")
        if result.max_residual > 3.0:
            warnings.append(f"나쁜 데이터(bad data) 의심 — LNR={result.max_residual:.2f} > 3σ")
        if result.unobservable_buses:
            warnings.append(
                f"관측 불가 모선 {len(result.unobservable_buses)}개: {result.unobservable_buses[:5]}"
            )

        status_text = "수렴 성공" if result.solved else "수렴 실패 (조류계산 fallback)"
        answer = (
            f"[상태추정 결과] {status_text}\n"
            f"- 신뢰도: {result.confidence_level:.1%}\n"
            f"- 관측성: {result.observable_ratio:.1%} "
            f"({len(self._net.bus) - len(result.unobservable_buses)}/{len(self._net.bus)} 모선)\n"
            f"- 최대 잔차 (LNR): {result.max_residual:.4f}\n"
            f"- 반복 횟수: {result.iterations}\n"
            f"- 기준 시각: {result.snapshot_ts.isoformat()}"
        )

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=result.confidence_level,
            warnings=warnings,
        )

    async def _run_tp(self, context: AgentContext) -> AIResponse:
        """조류계산(TP) 실행 및 결과 반환.

        PowerFlowEngine.run() + get_violations() 호출.
        """
        t0 = time.perf_counter()
        engine = PowerFlowEngine(self._net)
        result = engine.run()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        violations = engine.get_violations()
        viol_ms = (time.perf_counter() - t1) * 1000.0

        facts: List[StructuredFact] = [
            self._make_fact(
                "pf_converged", result.converged, "pandapower:runpp"
            ),
            self._make_fact(
                "pf_max_vm_pu", result.max_vm_pu, "pandapower:runpp:res_bus", unit="pu"
            ),
            self._make_fact(
                "pf_min_vm_pu", result.min_vm_pu, "pandapower:runpp:res_bus", unit="pu"
            ),
            self._make_fact(
                "pf_max_loading_pct",
                result.max_loading_pct,
                "pandapower:runpp:res_line",
                unit="%",
            ),
            self._make_fact(
                "pf_total_p_gen_mw",
                result.total_p_gen_mw,
                "pandapower:runpp:res_gen",
                unit="MW",
            ),
            self._make_fact(
                "pf_total_p_load_mw",
                result.total_p_load_mw,
                "pandapower:runpp:res_load",
                unit="MW",
            ),
            self._make_fact(
                "pf_total_loss_mw",
                result.total_loss_mw,
                "pandapower:runpp:res_ext_grid",
                unit="MW",
            ),
        ]

        evidence: List[EvidenceStep] = [
            self._make_evidence(
                tool_name="PowerFlowEngine.run",
                input_params={"network": "IEEE-14bus", "algorithm": "NR"},
                output_summary=(
                    f"converged={result.converged}, "
                    f"max_vm_pu={result.max_vm_pu:.4f}pu, "
                    f"min_vm_pu={result.min_vm_pu:.4f}pu, "
                    f"max_loading={result.max_loading_pct:.1f}%, "
                    f"gen={result.total_p_gen_mw:.1f}MW, "
                    f"load={result.total_p_load_mw:.1f}MW, "
                    f"loss={result.total_loss_mw:.2f}MW"
                ),
                duration_ms=elapsed_ms,
            ),
            self._make_evidence(
                tool_name="PowerFlowEngine.get_violations",
                input_params={"network": "IEEE-14bus"},
                output_summary=f"위반 {len(violations)}건 검출",
                duration_ms=viol_ms,
            ),
        ]

        warnings: List[str] = []
        if not result.converged:
            warnings.append("조류계산 수렴 실패 — 결과값 신뢰 불가")

        critical_viols = [v for v in violations if v.get("severity") == "CRITICAL"]
        warning_viols = [v for v in violations if v.get("severity") == "WARNING"]

        if critical_viols:
            warnings.append(f"CRITICAL 위반 {len(critical_viols)}건 감지")
        if warning_viols:
            warnings.append(f"WARNING 위반 {len(warning_viols)}건 감지")

        viol_summary = ""
        if violations:
            viol_lines = []
            for v in violations[:5]:  # 최대 5건만 표시
                viol_lines.append(
                    f"  [{v.get('severity', 'UNKNOWN')}] {v.get('message', '')}"
                )
            viol_summary = "\n위반 사항:\n" + "\n".join(viol_lines)
            if len(violations) > 5:
                viol_summary += f"\n  ... 외 {len(violations)-5}건"
        else:
            viol_summary = "\n위반 사항: 없음"

        conv_text = "수렴 성공" if result.converged else "수렴 실패"
        answer = (
            f"[조류계산 결과] {conv_text}\n"
            f"- 최대 전압: {result.max_vm_pu:.4f} pu\n"
            f"- 최소 전압: {result.min_vm_pu:.4f} pu\n"
            f"- 최대 선로 부하율: {result.max_loading_pct:.1f} %\n"
            f"- 총 발전: {result.total_p_gen_mw:.1f} MW\n"
            f"- 총 부하: {result.total_p_load_mw:.1f} MW\n"
            f"- 계통 손실: {result.total_loss_mw:.2f} MW"
            f"{viol_summary}\n"
            f"- 기준 시각: {result.snapshot_ts.isoformat()}"
        )

        confidence = 0.95 if result.converged else 0.2
        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=confidence,
            warnings=warnings,
        )

    async def _run_agc(self, context: AgentContext) -> AIResponse:
        """AGC 상태 조회 및 결과 반환.

        AGCController.get_status() + get_reserves() 호출.
        """
        # 조류계산 먼저 실행 (AGC는 runpp() 결과 필요)
        t0 = time.perf_counter()
        try:
            pp.runpp(self._net)
        except Exception:
            pass
        run_ms = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        agc = AGCController(self._net)
        status = agc.get_status()
        elapsed_ms = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        reserves = agc.get_reserves()
        res_ms = (time.perf_counter() - t2) * 1000.0

        facts: List[StructuredFact] = [
            self._make_fact(
                "agc_frequency_hz", status.frequency_hz,
                "pandapower:AGCController:get_status", unit="Hz"
            ),
            self._make_fact(
                "agc_ace_mw", status.ace_mw,
                "pandapower:AGCController:calculate_ace", unit="MW"
            ),
            self._make_fact(
                "agc_total_regulation_mw", status.total_regulation_mw,
                "pandapower:AGCController:_calc_regulation", unit="MW"
            ),
            self._make_fact(
                "agc_participating_units", status.participating_units,
                "pandapower:AGCController:_calc_regulation"
            ),
            self._make_fact(
                "agc_reserve_primary_mw", reserves.get("primary_mw", 0.0),
                "pandapower:AGCController:get_reserves", unit="MW"
            ),
            self._make_fact(
                "agc_reserve_secondary_mw", reserves.get("secondary_mw", 0.0),
                "pandapower:AGCController:get_reserves", unit="MW"
            ),
        ]

        evidence: List[EvidenceStep] = [
            self._make_evidence(
                tool_name="pandapower.runpp",
                input_params={"network": "IEEE-14bus"},
                output_summary="조류계산 완료 (AGC 입력 데이터 준비)",
                duration_ms=run_ms,
            ),
            self._make_evidence(
                tool_name="AGCController.get_status",
                input_params={"network": "IEEE-14bus"},
                output_summary=(
                    f"frequency_hz={status.frequency_hz:.3f}Hz, "
                    f"ace_mw={status.ace_mw:.2f}MW, "
                    f"regulation_mw={status.total_regulation_mw:.1f}MW, "
                    f"participating={status.participating_units}대"
                ),
                duration_ms=elapsed_ms,
            ),
            self._make_evidence(
                tool_name="AGCController.get_reserves",
                input_params={"network": "IEEE-14bus"},
                output_summary=(
                    f"primary={reserves.get('primary_mw', 0.0):.1f}MW, "
                    f"secondary={reserves.get('secondary_mw', 0.0):.1f}MW, "
                    f"tertiary={reserves.get('tertiary_mw', 0.0):.1f}MW"
                ),
                duration_ms=res_ms,
            ),
        ]

        warnings: List[str] = []
        # 주파수 이상 감지
        freq = status.frequency_hz
        if freq < 59.5:
            warnings.append(f"긴급: 주파수 {freq:.3f}Hz — 연쇄고장 최소 허용(59.5Hz) 미달!")
        elif freq < 59.7:
            warnings.append(f"경고: 주파수 {freq:.3f}Hz — 단일고장 최소 허용(59.7Hz) 미달")
        elif freq < 59.8 or freq > 60.2:
            warnings.append(f"주파수 {freq:.3f}Hz — 정상 범위(59.8~60.2Hz) 이탈")

        # ACE 이상 감지
        if abs(status.ace_mw) > 200:
            warnings.append(f"ACE 편차 큰: {status.ace_mw:.1f}MW")

        freq_status = "정상" if 59.8 <= freq <= 60.2 else "이상"
        answer = (
            f"[AGC 상태] 주파수 {freq_status}\n"
            f"- 현재 주파수: {status.frequency_hz:.3f} Hz (기준: 60.0 Hz)\n"
            f"- ACE: {status.ace_mw:.2f} MW\n"
            f"- 제어 모델: {status.model_type}\n"
            f"- AGC 참여 발전기: {status.participating_units}대\n"
            f"- 조정 가능 용량: {status.total_regulation_mw:.1f} MW\n\n"
            f"[예비력 현황 (고시 제6조)]\n"
            f"- 주파수제어 (5분): {reserves.get('frequency_control_mw', 0.0):.1f} MW\n"
            f"- 초속응성 (1초): {reserves.get('fast_response_mw', 0.0):.1f} MW\n"
            f"- 1차예비력 (10초): {reserves.get('primary_mw', 0.0):.1f} MW\n"
            f"- 2차예비력 (10분): {reserves.get('secondary_mw', 0.0):.1f} MW\n"
            f"- 3차예비력 (30분): {reserves.get('tertiary_mw', 0.0):.1f} MW\n"
            f"- 기준 시각: {status.snapshot_ts.isoformat()}"
        )

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=0.9,
            warnings=warnings,
        )

    async def _run_sca(self, context: AgentContext) -> AIResponse:
        """단락전류(SCA) 해석 결과 반환.

        pandapower.shortcircuit 모듈 호출.
        대상 모선 ID를 질의에서 추출하며, 없으면 모선 0 기본.
        """
        import pandapower.shortcircuit as sc

        bus_id = _detect_bus_id(context.user_query) or 0

        t0 = time.perf_counter()
        try:
            sc.calc_sc(self._net, fault="3ph", case="max")
            ikss_ka = float(self._net.res_bus_sc.at[bus_id, "ikss_ka"])
            skss_mva = float(self._net.res_bus_sc.at[bus_id, "skss_mva"])
            success = True
        except Exception as exc:
            ikss_ka = 0.0
            skss_mva = 0.0
            success = False
            err_msg = str(exc)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        facts: List[StructuredFact] = []
        warnings: List[str] = []

        if success:
            facts = [
                self._make_fact(
                    "sca_bus_id", bus_id,
                    f"pandapower:shortcircuit:calc_sc:bus_{bus_id}"
                ),
                self._make_fact(
                    "sca_ikss_ka", ikss_ka,
                    f"pandapower:shortcircuit:res_bus_sc:bus_{bus_id}",
                    unit="kA",
                ),
                self._make_fact(
                    "sca_skss_mva", skss_mva,
                    f"pandapower:shortcircuit:res_bus_sc:bus_{bus_id}",
                    unit="MVA",
                ),
            ]
            output_summary = (
                f"bus_id={bus_id}, "
                f"ikss_ka={ikss_ka:.4f}kA, "
                f"skss_mva={skss_mva:.2f}MVA"
            )
        else:
            warnings.append(f"단락전류 계산 실패: {err_msg}")
            output_summary = f"단락전류 계산 실패 (bus_id={bus_id})"

        evidence: List[EvidenceStep] = [
            self._make_evidence(
                tool_name="pandapower.shortcircuit.calc_sc",
                input_params={"bus_id": bus_id, "fault": "3ph", "case": "max"},
                output_summary=output_summary,
                duration_ms=elapsed_ms,
            )
        ]

        if success:
            answer = (
                f"[단락전류 해석 결과] 모선 {bus_id}\n"
                f"- 고장 유형: 3상 단락 (3ph, IEC 60909)\n"
                f"- 초기 대칭 단락전류 (Ikss): {ikss_ka:.4f} kA\n"
                f"- 초기 대칭 단락용량 (Skss): {skss_mva:.2f} MVA\n"
                f"- 기준 시각: {context.snapshot_ts.isoformat()}"
            )
        else:
            answer = (
                f"[단락전류 해석 실패] 모선 {bus_id}\n"
                f"단락전류 계산 중 오류가 발생했습니다.\n"
                f"자세한 내용: {err_msg if not success else ''}"
            )

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=0.85 if success else 0.1,
            warnings=warnings,
        )
