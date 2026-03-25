"""계통검토 에이전트 — ops→study 격리 What-if 스터디 (HITL).

사용자 질의에서 계통 변경 사항(CB 개방, 부하 변경 등)을 파악하고,
ops 네트워크를 study: 네임스페이스에 복사하여 격리된 환경에서 실행한다.

ops: AI write 절대 불가. study: AI write 허용.
결과는 변경 전후 비교 + 위반사항 검출 후 HITL 승인 필요.

설계 원칙:
  1. LLM 수치 생성 절대 금지 — pandapower 솔버 반환값만
  2. ops/study 네임스페이스 격리
  3. HITL/HOTL 이원 분류 — 계통 변경→HITL
  4. Evidence chain 필수
"""
from __future__ import annotations

import copy
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

import pandapower as pp

from src.layer1.ems_stubs.tp.powerflow import PowerFlowEngine
from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer2.agents.base import BaseAgent
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact
from src.shared.schemas.study import StudyResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# CB 개방/폐로 키워드
_CB_OPEN_KEYWORDS = [
    r"cb[_\s]*(\d+)\s*개방",
    r"cb[_\s]*(\d+)\s*open",
    r"선로[_\s]*(\d+)\s*개방",
    r"line[_\s]*(\d+)\s*개방",
    r"switch[_\s]*(\d+)\s*개방",
    r"(\d+)번\s*cb\s*개방",
    r"(\d+)번\s*선로\s*개방",
    r"(\d+)번\s*차단기\s*개방",
]
_CB_CLOSE_KEYWORDS = [
    r"cb[_\s]*(\d+)\s*폐로",
    r"cb[_\s]*(\d+)\s*close",
    r"선로[_\s]*(\d+)\s*폐로",
    r"line[_\s]*(\d+)\s*폐로",
    r"switch[_\s]*(\d+)\s*폐로",
    r"(\d+)번\s*cb\s*폐로",
    r"(\d+)번\s*선로\s*폐로",
    r"(\d+)번\s*차단기\s*폐로",
]
_LOAD_CHANGE_KEYWORDS = [
    r"부하[_\s]*(\d+).*?(\d+(?:\.\d+)?)\s*mw",
    r"load[_\s]*(\d+).*?(\d+(?:\.\d+)?)\s*mw",
]


def _parse_cb_action(query: str) -> Optional[Tuple[str, int]]:
    """질의에서 CB 개방/폐로 액션 파싱.

    Args:
        query: 사용자 질의.

    Returns:
        (action, element_id) 튜플 또는 None.
        action: 'open' 또는 'close'.
    """
    query_lower = query.lower()
    for pattern in _CB_OPEN_KEYWORDS:
        m = re.search(pattern, query_lower)
        if m:
            return ("open", int(m.group(1)))
    for pattern in _CB_CLOSE_KEYWORDS:
        m = re.search(pattern, query_lower)
        if m:
            return ("close", int(m.group(1)))
    return None


def _parse_load_change(query: str) -> Optional[Tuple[int, float]]:
    """질의에서 부하 변경 액션 파싱.

    Args:
        query: 사용자 질의.

    Returns:
        (load_id, new_p_mw) 튜플 또는 None.
    """
    query_lower = query.lower()
    for pattern in _LOAD_CHANGE_KEYWORDS:
        m = re.search(pattern, query_lower)
        if m:
            return (int(m.group(1)), float(m.group(2)))
    return None


class StudyAgent(BaseAgent):
    """계통검토 에이전트 (HITL).

    ops 네트워크 → study 네임스페이스 복사 → 변경 적용 → 조류계산 → 비교.

    개발 모드: Layer 1 PowerFlowEngine 직접 사용.
    namespace='study' 고정 — AI는 ops: write 절대 불가 (설계 원칙 2).
    """

    name: str = "study"
    description: str = "계통검토 에이전트 — ops→study 격리 What-if 스터디 + 변경 전후 비교"
    mode: Literal["HITL", "HOTL"] = "HITL"

    def __init__(self, net: Optional[pp.pandapowerNet] = None) -> None:
        """계통검토 에이전트 초기화.

        Args:
            net: 기준 ops 네트워크. None이면 IEEE 14-bus 기본 케이스.
                 이 네트워크는 절대 수정되지 않음 (ops 격리 원칙).
        """
        # ops 네트워크 — 읽기 전용 원본 (AI write 불가)
        self._ops_net: pp.pandapowerNet = net if net is not None else create_ieee14_network()

    async def run(self, context: AgentContext) -> AIResponse:
        """계통검토 에이전트 실행.

        1. 사용자 질의에서 변경 사항 파악 (CB 개방, 부하 변경 등)
        2. namespace='study' 설정
        3. ops 네트워크 복사 → 변경 적용 (ops 원본 절대 수정 않음)
        4. pandapower runpp() 실행
        5. 변경 전후 비교
        6. 위반사항 검출
        7. AIResponse 반환 (HITL 승인 필요)

        Args:
            context: 에이전트 컨텍스트.

        Returns:
            AIResponse — HITL 모드, evidence_chain 포함.
        """
        study_id = f"study_{uuid.uuid4().hex[:8]}"
        evidence: List[EvidenceStep] = []
        facts: List[StructuredFact] = []
        warnings: List[str] = []
        suggestions: List[str] = []

        # ── 1. ops 기준 조류계산 (베이스케이스) ──────────────────────
        t0 = time.perf_counter()
        base_engine = PowerFlowEngine(self._ops_net)
        base_result = base_engine.run()
        base_ms = (time.perf_counter() - t0) * 1000.0

        evidence.append(
            self._make_evidence(
                tool_name="PowerFlowEngine.run [ops:base]",
                input_params={"network": "IEEE-14bus", "namespace": "ops"},
                output_summary=(
                    f"converged={base_result.converged}, "
                    f"max_vm={base_result.max_vm_pu:.4f}pu, "
                    f"min_vm={base_result.min_vm_pu:.4f}pu, "
                    f"max_loading={base_result.max_loading_pct:.1f}%"
                ),
                duration_ms=base_ms,
            )
        )

        if not base_result.converged:
            warnings.append("기준 조류계산(base case) 수렴 실패 — 스터디 신뢰도 낮음")

        # ── 2. 질의에서 변경 사항 파악 ───────────────────────────────
        cb_action = _parse_cb_action(context.user_query)
        load_change = _parse_load_change(context.user_query)

        if not cb_action and not load_change:
            # 변경 사항 없음 — 베이스케이스만 반환
            evidence.append(
                self._make_evidence(
                    tool_name="study_change_parser",
                    input_params={"query": context.user_query},
                    output_summary="변경 사항을 파악할 수 없음 — 베이스케이스 결과 반환",
                    duration_ms=0.0,
                )
            )
            facts.append(
                self._make_fact(
                    key="study_base_max_vm_pu", value=base_result.max_vm_pu,
                    source="ops:PowerFlowEngine:run", unit="pu"
                )
            )
            return self._build_response(
                answer=(
                    f"[계통검토] 변경 사항을 파악할 수 없습니다.\n"
                    f"'CB 5 개방', '3번 선로 개방', '부하 2 50MW 변경' 등의 형식으로 입력해 주세요.\n\n"
                    f"[기준 계통 상태]\n"
                    f"- 수렴 여부: {base_result.converged}\n"
                    f"- 최대 전압: {base_result.max_vm_pu:.4f} pu\n"
                    f"- 최소 전압: {base_result.min_vm_pu:.4f} pu\n"
                    f"- 최대 부하율: {base_result.max_loading_pct:.1f} %"
                ),
                facts=facts,
                evidence=evidence,
                confidence=0.5,
                warnings=warnings,
            )

        # ── 3. study 네임스페이스 — ops 네트워크 복사 ─────────────────
        # 설계 원칙 2: ops 원본은 절대 수정하지 않음
        t1 = time.perf_counter()
        study_net = copy.deepcopy(self._ops_net)
        copy_ms = (time.perf_counter() - t1) * 1000.0

        change_desc = ""

        evidence.append(
            self._make_evidence(
                tool_name="network_deep_copy",
                input_params={"namespace": "study", "study_id": study_id},
                output_summary=f"ops → study:{study_id} 네트워크 복사 완료",
                duration_ms=copy_ms,
            )
        )

        # ── 4. 변경 적용 ─────────────────────────────────────────────
        t2 = time.perf_counter()
        apply_success = True
        apply_error = ""

        if cb_action:
            action, elem_id = cb_action
            action_ko = "개방" if action == "open" else "폐로"
            try:
                if action == "open":
                    # 선로 비활성화 또는 스위치 개방
                    if elem_id < len(study_net.line):
                        study_net.line.at[elem_id, "in_service"] = False
                        change_desc = f"선로 {elem_id} {action_ko}"
                    elif elem_id < len(study_net.switch):
                        study_net.switch.at[elem_id, "closed"] = False
                        change_desc = f"스위치 {elem_id} {action_ko}"
                    else:
                        apply_success = False
                        apply_error = f"요소 ID {elem_id}가 범위를 벗어납니다."
                else:  # close
                    if elem_id < len(study_net.line):
                        study_net.line.at[elem_id, "in_service"] = True
                        change_desc = f"선로 {elem_id} {action_ko}"
                    elif elem_id < len(study_net.switch):
                        study_net.switch.at[elem_id, "closed"] = True
                        change_desc = f"스위치 {elem_id} {action_ko}"
                    else:
                        apply_success = False
                        apply_error = f"요소 ID {elem_id}가 범위를 벗어납니다."
            except Exception as exc:
                apply_success = False
                apply_error = str(exc)

        elif load_change:
            load_id, new_p_mw = load_change
            try:
                if load_id < len(study_net.load):
                    old_p = float(study_net.load.at[load_id, "p_mw"])
                    study_net.load.at[load_id, "p_mw"] = new_p_mw
                    change_desc = f"부하 {load_id} 변경 ({old_p:.1f}MW → {new_p_mw:.1f}MW)"
                else:
                    apply_success = False
                    apply_error = f"부하 ID {load_id}가 범위를 벗어납니다."
            except Exception as exc:
                apply_success = False
                apply_error = str(exc)

        apply_ms = (time.perf_counter() - t2) * 1000.0

        evidence.append(
            self._make_evidence(
                tool_name="study_change_apply",
                input_params={
                    "study_id": study_id,
                    "namespace": "study",
                    "change": change_desc,
                },
                output_summary=(
                    f"변경 적용 {'성공' if apply_success else '실패'}: {change_desc}"
                    + (f" — 오류: {apply_error}" if apply_error else "")
                ),
                duration_ms=apply_ms,
            )
        )

        if not apply_success:
            warnings.append(f"변경 적용 실패: {apply_error}")
            return self._build_response(
                answer=f"[계통검토] 변경 적용 실패: {apply_error}",
                facts=facts,
                evidence=evidence,
                confidence=0.1,
                warnings=warnings,
            )

        # ── 5. study 조류계산 ─────────────────────────────────────────
        t3 = time.perf_counter()
        study_engine = PowerFlowEngine(study_net)
        study_result = study_engine.run()
        study_ms = (time.perf_counter() - t3) * 1000.0

        t4 = time.perf_counter()
        violations = study_engine.get_violations()
        viol_ms = (time.perf_counter() - t4) * 1000.0

        evidence.append(
            self._make_evidence(
                tool_name="PowerFlowEngine.run [study]",
                input_params={"study_id": study_id, "namespace": "study", "change": change_desc},
                output_summary=(
                    f"converged={study_result.converged}, "
                    f"max_vm={study_result.max_vm_pu:.4f}pu, "
                    f"min_vm={study_result.min_vm_pu:.4f}pu, "
                    f"max_loading={study_result.max_loading_pct:.1f}%"
                ),
                duration_ms=study_ms,
            )
        )
        evidence.append(
            self._make_evidence(
                tool_name="PowerFlowEngine.get_violations [study]",
                input_params={"study_id": study_id, "namespace": "study"},
                output_summary=f"위반 {len(violations)}건 검출",
                duration_ms=viol_ms,
            )
        )

        # ── 6. 변경 전후 비교 ─────────────────────────────────────────
        delta_max_vm = study_result.max_vm_pu - base_result.max_vm_pu
        delta_min_vm = study_result.min_vm_pu - base_result.min_vm_pu
        delta_loading = study_result.max_loading_pct - base_result.max_loading_pct
        delta_loss = study_result.total_loss_mw - base_result.total_loss_mw

        facts.extend([
            self._make_fact("study_id", study_id, f"study:{study_id}"),
            self._make_fact("base_max_vm_pu", base_result.max_vm_pu,
                            "ops:PowerFlowEngine:run", unit="pu"),
            self._make_fact("base_min_vm_pu", base_result.min_vm_pu,
                            "ops:PowerFlowEngine:run", unit="pu"),
            self._make_fact("base_max_loading_pct", base_result.max_loading_pct,
                            "ops:PowerFlowEngine:run", unit="%"),
            self._make_fact("study_max_vm_pu", study_result.max_vm_pu,
                            f"study:{study_id}:PowerFlowEngine:run", unit="pu"),
            self._make_fact("study_min_vm_pu", study_result.min_vm_pu,
                            f"study:{study_id}:PowerFlowEngine:run", unit="pu"),
            self._make_fact("study_max_loading_pct", study_result.max_loading_pct,
                            f"study:{study_id}:PowerFlowEngine:run", unit="%"),
            self._make_fact("study_violation_count", len(violations),
                            f"study:{study_id}:PowerFlowEngine:get_violations"),
        ])

        # ── 7. 위반사항 및 권고사항 ───────────────────────────────────
        if not study_result.converged:
            warnings.append("스터디 조류계산 수렴 실패 — 변경 후 계통 불안정 가능성")
            suggestions.append("[HITL 승인 필요] 해당 변경 작업 시행 금지 권고 — 계통 불안정 우려")

        critical_viols = [v for v in violations if v.get("severity") == "CRITICAL"]
        warning_viols = [v for v in violations if v.get("severity") == "WARNING"]

        if critical_viols:
            warnings.append(f"CRITICAL 위반 {len(critical_viols)}건 — N-1 기준 위배 가능성")
            suggestions.append(
                f"[HITL 승인 필요] 위반 {len(critical_viols)}건 해소 전까지 해당 조작 금지"
            )
        if delta_loading > 20:
            suggestions.append(
                f"[HITL 승인 필요] 최대 부하율 {delta_loading:+.1f}% 증가 — "
                f"병렬 선로 투입 검토"
            )
        if abs(delta_min_vm) > 0.05:
            suggestions.append(
                f"[HITL 승인 필요] 최소 전압 {delta_min_vm:+.4f}pu 변화 — "
                f"무효전력 보상 검토"
            )

        # 위반 사항 요약 (최대 5건)
        viol_lines: List[str] = []
        for v in violations[:5]:
            viol_lines.append(f"  [{v.get('severity')}] {v.get('message', '')}")
        if len(violations) > 5:
            viol_lines.append(f"  ... 외 {len(violations)-5}건")
        viol_text = "\n".join(viol_lines) if viol_lines else "  없음"

        def _sign(val: float) -> str:
            return f"+{val:.4f}" if val >= 0 else f"{val:.4f}"

        answer = (
            f"[계통검토 결과] Study ID: {study_id}\n"
            f"적용 변경: {change_desc}\n\n"
            f"[변경 전후 비교]\n"
            f"{'항목':<25} {'변경 전':>12} {'변경 후':>12} {'차이':>12}\n"
            f"{'-'*65}\n"
            f"{'최대 전압 (pu)':<25} {base_result.max_vm_pu:>12.4f} {study_result.max_vm_pu:>12.4f} {_sign(delta_max_vm):>12}\n"
            f"{'최소 전압 (pu)':<25} {base_result.min_vm_pu:>12.4f} {study_result.min_vm_pu:>12.4f} {_sign(delta_min_vm):>12}\n"
            f"{'최대 부하율 (%)':<25} {base_result.max_loading_pct:>12.1f} {study_result.max_loading_pct:>12.1f} {_sign(delta_loading):>11}%\n"
            f"{'계통 손실 (MW)':<25} {base_result.total_loss_mw:>12.2f} {study_result.total_loss_mw:>12.2f} {_sign(delta_loss):>12}\n\n"
            f"[위반사항]\n{viol_text}\n\n"
            f"[스터디 결과] 수렴: {'성공' if study_result.converged else '실패'}\n"
            f"namespace=study:{study_id} (ops: 원본 변경 없음)\n"
            f"※ 아래 조치는 운영자 승인(HITL) 필수입니다."
        )

        confidence = 0.85 if study_result.converged else 0.3
        if critical_viols:
            confidence *= 0.8

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=confidence,
            warnings=warnings,
            suggestions=suggestions,
        )
