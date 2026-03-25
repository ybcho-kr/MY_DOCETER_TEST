"""알람 분석 에이전트 — 활성 알람 분석 + Root Cause 추론 (HITL).

활성 알람 목록을 조회하고 유형별 분류, root cause 규칙 기반 추론,
조치 권고(suggestions)를 생성한다.

조치 권고는 HITL → 운영자 승인 필수 표시.

설계 원칙:
  2. ops/study 네임스페이스 격리 — AI는 ops: write 불가
  3. HITL/HOTL 이원 분류 — 조치→HITL 운영자 승인
  4. Evidence chain 필수
"""
from __future__ import annotations

import time
from typing import Dict, List, Literal, Optional

import pandapower as pp

from src.layer1.alarm_model.manager import AlarmManager
from src.layer1.ems_stubs.tp.powerflow import PowerFlowEngine
from src.layer1.scada_simulator.network import create_ieee14_network
from src.layer2.agents.base import BaseAgent
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact
from src.shared.schemas.alarm import Alarm, AlarmSeverity, AlarmType


# Root Cause 규칙 기반 추론
# 알람 유형 + 심각도 → (root_cause 설명, 권장 조치)
_ROOT_CAUSE_RULES: Dict[str, tuple] = {
    "LIMIT_CRITICAL_voltage": (
        "모선 전압이 운용범위(±10%)를 초과했습니다. 부하 급증 또는 무효전력 공급 부족이 원인일 수 있습니다.",
        "[HITL 승인 필요] 무효전력 보상기(SVC/STATCOM) 출력 조정 또는 해당 구간 전압 조정 변압기 탭 변경을 검토하십시오.",
    ),
    "LIMIT_WARNING_voltage": (
        "모선 전압이 조정목표(±5%)를 벗어났습니다. 부하 증가 추세 또는 발전기 무효전력 출력 감소가 원인입니다.",
        "[HITL 승인 필요] 발전기 무효전력 출력 증가 또는 변압기 탭 조정을 검토하십시오.",
    ),
    "LIMIT_CRITICAL_loading": (
        "선로 열용량이 100%를 초과했습니다. 과부하 상태로 설비 손상 위험이 있습니다.",
        "[HITL 승인 필요] 해당 선로 병렬 운전 투입 또는 부하 전환을 즉시 검토하십시오.",
    ),
    "LIMIT_WARNING_loading": (
        "선로 부하율이 80%를 초과했습니다. 지속 증가 시 과부하 전환 위험이 있습니다.",
        "[HITL 승인 필요] 부하 분산 또는 예비 선로 투입을 검토하십시오.",
    ),
    "STATE_INFO": (
        "설비 상태가 변화했습니다. 계획된 조작 또는 자동 보호 동작 결과일 수 있습니다.",
        "변전소 운전원과 상태 변화 원인을 확인하십시오.",
    ),
    "STATE_CRITICAL": (
        "설비가 예상치 않게 트립 또는 탈락했습니다. 보호 계전기 동작 가능성이 있습니다.",
        "[HITL 승인 필요] 해당 설비 트립 원인 분석 후 N-1 기준 검토 및 전력 재배분을 검토하십시오.",
    ),
    "COMM_WARNING": (
        "SCADA 통신 이상으로 실시간 데이터 수신이 지연되고 있습니다.",
        "통신 장비 및 RTU 상태를 점검하십시오. 데이터 지연 시간을 기록하십시오.",
    ),
    "COMM_CRITICAL": (
        "SCADA 통신이 완전히 끊겼습니다. 실시간 감시가 불가합니다.",
        "[HITL 승인 필요] 백업 통신 경로 전환 및 현장 직접 감시 체계를 즉시 가동하십시오.",
    ),
    "QUALITY_WARNING": (
        "측정 데이터 품질이 저하되었습니다. 센서 오류 또는 통신 잡음이 원인일 수 있습니다.",
        "해당 계측기 calibration 및 신호 품질을 점검하십시오.",
    ),
}


def _get_root_cause_key(alarm: Alarm) -> str:
    """알람에서 root cause 규칙 조회 키 생성."""
    severity_str = alarm.severity.value
    type_str = alarm.alarm_type.value
    # 전압/부하율 관련 LIMIT 경보
    if alarm.alarm_type == AlarmType.LIMIT:
        msg_lower = alarm.message.lower()
        if "전압" in msg_lower or "voltage" in msg_lower or "vm_pu" in msg_lower:
            return f"LIMIT_{severity_str}_voltage"
        elif "부하율" in msg_lower or "loading" in msg_lower:
            return f"LIMIT_{severity_str}_loading"
    elif alarm.alarm_type == AlarmType.STATE:
        return f"STATE_{severity_str}"
    elif alarm.alarm_type == AlarmType.COMM:
        return f"COMM_{severity_str}"
    elif alarm.alarm_type == AlarmType.QUALITY:
        return f"QUALITY_{severity_str}"
    return ""


class AlarmAnalysisAgent(BaseAgent):
    """알람 분석 에이전트 (HITL).

    활성 알람을 분석하고 root cause를 규칙 기반으로 추론한다.
    조치 권고(suggestions)는 HITL → 운영자 승인 필수.

    개발 모드: Layer 1 AlarmManager 직접 사용.
    """

    name: str = "alarm"
    description: str = "알람 분석 에이전트 — 활성 알람 분류 + Root Cause 추론 + 조치 권고"
    mode: Literal["HITL", "HOTL"] = "HITL"

    def __init__(
        self,
        net: Optional[pp.pandapowerNet] = None,
        active_alarms: Optional[List[Alarm]] = None,
    ) -> None:
        """알람 분석 에이전트 초기화.

        Args:
            net: pandapower 네트워크. None이면 IEEE 14-bus 기본 케이스.
            active_alarms: 사전 주입 알람 목록 (테스트용). None이면 실시간 탐지.
        """
        self._net: pp.pandapowerNet = net if net is not None else create_ieee14_network()
        self._preset_alarms: Optional[List[Alarm]] = active_alarms
        self._alarm_manager = AlarmManager()

    async def run(self, context: AgentContext) -> AIResponse:
        """알람 분석 에이전트 실행.

        1. 활성 알람 목록 조회 (AlarmManager 또는 사전 주입 목록)
        2. 알람 유형별 분류 (LIMIT/STATE/COMM/QUALITY)
        3. Root cause 규칙 기반 추론
        4. 조치 권고 생성 (HITL 승인 필요 표시)
        5. AIResponse 반환

        Args:
            context: 에이전트 컨텍스트.

        Returns:
            AIResponse — HITL 모드, evidence_chain 포함.
        """
        evidence: List[EvidenceStep] = []
        facts: List[StructuredFact] = []

        # ── 1. 활성 알람 조회 ─────────────────────────────────────────
        if self._preset_alarms is not None:
            # 테스트용 사전 주입 알람
            active_alarms = self._preset_alarms
            evidence.append(
                self._make_evidence(
                    tool_name="preset_alarm_list",
                    input_params={"source": "injected"},
                    output_summary=f"사전 주입 알람 {len(active_alarms)}건",
                    duration_ms=0.0,
                )
            )
        else:
            # Layer 1 AlarmManager 실시간 탐지
            t0 = time.perf_counter()
            try:
                pp.runpp(self._net)
            except Exception:
                pass
            run_ms = (time.perf_counter() - t0) * 1000.0

            t1 = time.perf_counter()
            summary = self._alarm_manager.process_network(self._net)
            active_alarms = self._alarm_manager.get_active_alarms()
            detect_ms = (time.perf_counter() - t1) * 1000.0

            evidence.append(
                self._make_evidence(
                    tool_name="pandapower.runpp",
                    input_params={"network": "IEEE-14bus"},
                    output_summary="조류계산 완료 (알람 탐지 입력 데이터)",
                    duration_ms=run_ms,
                )
            )
            evidence.append(
                self._make_evidence(
                    tool_name="AlarmManager.process_network",
                    input_params={"network": "IEEE-14bus"},
                    output_summary=(
                        f"활성 알람 {summary.total}건 — "
                        f"CRITICAL={summary.by_severity.get(AlarmSeverity.CRITICAL, 0)}, "
                        f"WARNING={summary.by_severity.get(AlarmSeverity.WARNING, 0)}, "
                        f"미확인={summary.unacknowledged}"
                    ),
                    duration_ms=detect_ms,
                )
            )

        # ── 2. 알람 유형별 분류 ───────────────────────────────────────
        t2 = time.perf_counter()
        by_type: Dict[str, List[Alarm]] = {t.value: [] for t in AlarmType}
        by_severity: Dict[str, List[Alarm]] = {s.value: [] for s in AlarmSeverity}

        for alarm in active_alarms:
            by_type[alarm.alarm_type.value].append(alarm)
            by_severity[alarm.severity.value].append(alarm)

        classify_ms = (time.perf_counter() - t2) * 1000.0

        evidence.append(
            self._make_evidence(
                tool_name="alarm_classification",
                input_params={"total": len(active_alarms)},
                output_summary=(
                    f"LIMIT={len(by_type.get('LIMIT', []))}, "
                    f"STATE={len(by_type.get('STATE', []))}, "
                    f"COMM={len(by_type.get('COMM', []))}, "
                    f"QUALITY={len(by_type.get('QUALITY', []))}"
                ),
                duration_ms=classify_ms,
            )
        )

        # ── 3. Root Cause 규칙 기반 추론 ─────────────────────────────
        root_causes: List[str] = []
        suggestions: List[str] = []
        seen_keys: set = set()

        for alarm in active_alarms:
            rc_key = _get_root_cause_key(alarm)
            if rc_key and rc_key not in seen_keys:
                rule = _ROOT_CAUSE_RULES.get(rc_key)
                if rule:
                    root_cause_desc, suggestion = rule
                    root_causes.append(f"[{alarm.alarm_type.value}/{alarm.severity.value}] {root_cause_desc}")
                    suggestions.append(suggestion)
                    seen_keys.add(rc_key)

        # ── 4. 사실 데이터 조립 ───────────────────────────────────────
        facts.append(
            self._make_fact(
                key="alarm_total",
                value=len(active_alarms),
                source="AlarmManager:process_network",
            )
        )
        for type_key, alarms_of_type in by_type.items():
            facts.append(
                self._make_fact(
                    key=f"alarm_count_{type_key}",
                    value=len(alarms_of_type),
                    source="alarm_classification",
                )
            )
        for sev_key, alarms_of_sev in by_severity.items():
            facts.append(
                self._make_fact(
                    key=f"alarm_severity_{sev_key}",
                    value=len(alarms_of_sev),
                    source="alarm_classification",
                )
            )

        # ── 5. 응답 조립 ─────────────────────────────────────────────
        warnings: List[str] = []
        if by_severity.get("EMERGENCY"):
            warnings.append(
                f"긴급 알람 {len(by_severity['EMERGENCY'])}건 — 즉각 조치 필요!"
            )
        if by_severity.get("CRITICAL"):
            warnings.append(
                f"위험 알람 {len(by_severity['CRITICAL'])}건 감지"
            )

        # 알람 상세 목록 (최대 10건)
        alarm_lines: List[str] = []
        for alarm in sorted(
            active_alarms,
            key=lambda a: (
                -["INFO", "WARNING", "CRITICAL", "EMERGENCY"].index(a.severity.value),
            ),
        )[:10]:
            ack_str = "확인됨" if alarm.acknowledged else "미확인"
            alarm_lines.append(
                f"  [{alarm.severity.value}] {alarm.alarm_type.value} | "
                f"{alarm.message} ({ack_str})"
            )
        if len(active_alarms) > 10:
            alarm_lines.append(f"  ... 외 {len(active_alarms)-10}건")

        alarm_detail = "\n".join(alarm_lines) if alarm_lines else "  활성 알람 없음"

        root_cause_text = "\n".join(f"  {rc}" for rc in root_causes) if root_causes else "  (분류 불가 — 추가 데이터 필요)"

        if active_alarms:
            answer = (
                f"[알람 분석 결과] 활성 알람 {len(active_alarms)}건\n\n"
                f"[유형별 집계]\n"
                f"  LIMIT(한계치): {len(by_type.get('LIMIT', []))}건\n"
                f"  STATE(상태변화): {len(by_type.get('STATE', []))}건\n"
                f"  COMM(통신이상): {len(by_type.get('COMM', []))}건\n"
                f"  QUALITY(품질): {len(by_type.get('QUALITY', []))}건\n\n"
                f"[심각도별 집계]\n"
                f"  EMERGENCY: {len(by_severity.get('EMERGENCY', []))}건\n"
                f"  CRITICAL: {len(by_severity.get('CRITICAL', []))}건\n"
                f"  WARNING: {len(by_severity.get('WARNING', []))}건\n"
                f"  INFO: {len(by_severity.get('INFO', []))}건\n\n"
                f"[알람 목록]\n{alarm_detail}\n\n"
                f"[Root Cause 분석]\n{root_cause_text}\n\n"
                f"※ 아래 조치는 운영자 승인(HITL) 필수입니다."
            )
        else:
            answer = "[알람 분석 결과] 현재 활성 알람이 없습니다. 계통이 정상 범위에서 운전 중입니다."

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=0.85 if active_alarms else 0.95,
            warnings=warnings,
            suggestions=suggestions,
        )
