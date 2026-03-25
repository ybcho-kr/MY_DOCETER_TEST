"""NL Navigation 에이전트 — 화면/지도 이동 (HOTL).

사용자 자연어 질의에서 목적 화면을 파악하고,
화면 전환 명령(navigation command)을 AIResponse에 담아 반환한다.

설계 원칙:
  3. HITL/HOTL 이원 분류 — 화면 이동→HOTL 자동
  4. Evidence chain 필수
  5. snapshot_ts 필수
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Literal, Optional, Tuple

from src.layer2.agents.base import BaseAgent
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact


# 지원 화면 목록 — 한국어 키워드 → 화면 식별자
# 키워드가 많을수록 매칭 우선순위가 높음
SCREENS: Dict[str, str] = {
    "계통도": "system_overview",
    "계통 개요": "system_overview",
    "시스템 개요": "system_overview",
    "변전소": "substation_sld",
    "SLD": "substation_sld",
    "단선도": "substation_sld",
    "계통도면": "substation_sld",
    "GIS": "gis_map",
    "지도": "gis_map",
    "맵": "gis_map",
    "지리": "gis_map",
    "알람": "alarm_panel",
    "경보": "alarm_panel",
    "알람패널": "alarm_panel",
    "경보창": "alarm_panel",
    "조류계산": "powerflow_view",
    "조류": "powerflow_view",
    "전력흐름": "powerflow_view",
    "power flow": "powerflow_view",
    "powerflow": "powerflow_view",
    "상태추정": "se_view",
    "상태 추정": "se_view",
    "SE": "se_view",
    "state estimation": "se_view",
    "AGC": "agc_view",
    "자동발전제어": "agc_view",
    "주파수": "agc_view",
    "예비력": "reserve_view",
    "예비력 현황": "reserve_view",
    "reserve": "reserve_view",
}

# 화면 식별자 → 한국어 표시 이름
SCREEN_NAMES: Dict[str, str] = {
    "system_overview": "계통 개요 화면",
    "substation_sld": "변전소 단선도(SLD)",
    "gis_map": "GIS 지리 지도",
    "alarm_panel": "알람/경보 패널",
    "powerflow_view": "조류계산 결과 화면",
    "se_view": "상태추정 결과 화면",
    "agc_view": "AGC/주파수 제어 화면",
    "reserve_view": "예비력 현황 화면",
}

# 변전소 ID 추출 패턴 (SLD 이동 시)
_SUBSTATION_PATTERNS = [
    r"변전소[_\s]*(\w+)",
    r"(\w+)\s*변전소",
    r"substation[_\s]*(\w+)",
]


def _detect_screen(query: str) -> Tuple[str, float]:
    """질의에서 목적 화면 감지.

    키워드 매칭 점수 기반으로 최적 화면을 반환한다.
    매칭 실패 시 'system_overview'를 기본값으로 반환한다.

    Args:
        query: 사용자 자연어 질의.

    Returns:
        (screen_id, confidence) 튜플.
    """
    query_upper = query.upper()
    scores: Dict[str, float] = {}

    for keyword, screen_id in SCREENS.items():
        if keyword.upper() in query_upper:
            # 키워드 길이 기반 점수 (긴 키워드 = 더 구체적)
            score = len(keyword)
            scores[screen_id] = max(scores.get(screen_id, 0), score)

    if not scores:
        return ("system_overview", 0.4)

    best_screen = max(scores, key=lambda k: scores[k])
    # 점수를 0.5~0.95 범위로 정규화
    max_score = max(scores.values())
    confidence = min(0.95, 0.5 + max_score / 20.0)
    return (best_screen, confidence)


def _extract_substation_id(query: str) -> Optional[str]:
    """질의에서 변전소 ID 추출 (SLD 이동 시 사용).

    Args:
        query: 사용자 자연어 질의.

    Returns:
        변전소 ID 문자열 또는 None.
    """
    for pattern in _SUBSTATION_PATTERNS:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


class NLNavigationAgent(BaseAgent):
    """NL Navigation 에이전트 (HOTL).

    자연어 질의에서 목적 화면을 파악하고 화면 전환 명령을 반환한다.
    화면 이동은 HOTL — 운영자 승인 불필요 (조회/이동 범주).
    """

    name: str = "navigation"
    description: str = "NL Navigation 에이전트 — 자연어로 화면/지도 이동 명령 생성"
    mode: Literal["HITL", "HOTL"] = "HOTL"

    async def run(self, context: AgentContext) -> AIResponse:
        """NL Navigation 에이전트 실행.

        1. 질의에서 목적 화면 파악
        2. SCREENS 매핑
        3. AIResponse (navigation 명령 포함)

        Args:
            context: 에이전트 컨텍스트.

        Returns:
            AIResponse — HOTL 모드, navigation 명령 포함.
        """
        t0 = time.perf_counter()
        screen_id, confidence = _detect_screen(context.user_query)
        screen_name = SCREEN_NAMES.get(screen_id, screen_id)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # 변전소 SLD일 경우 변전소 ID 추가 추출
        substation_id: Optional[str] = None
        if screen_id == "substation_sld":
            substation_id = _extract_substation_id(context.user_query)

        facts: List[StructuredFact] = [
            self._make_fact(
                key="nav_target_screen",
                value=screen_id,
                source="NLNavigationAgent:screen_detection",
            ),
            self._make_fact(
                key="nav_confidence",
                value=confidence,
                source="NLNavigationAgent:keyword_matching",
            ),
        ]

        if substation_id:
            facts.append(
                self._make_fact(
                    key="nav_substation_id",
                    value=substation_id,
                    source="NLNavigationAgent:substation_extraction",
                )
            )

        evidence: List[EvidenceStep] = [
            self._make_evidence(
                tool_name="screen_keyword_matching",
                input_params={
                    "query": context.user_query,
                    "supported_screens": list(set(SCREENS.values())),
                },
                output_summary=(
                    f"목적 화면: {screen_id} ({screen_name}), "
                    f"신뢰도: {confidence:.2f}"
                    + (f", 변전소ID: {substation_id}" if substation_id else "")
                ),
                duration_ms=elapsed_ms,
            )
        ]

        # 화면 전환 명령을 suggestions에 포함 (프론트엔드가 파싱)
        nav_command = f"NAVIGATE:{screen_id}"
        if substation_id:
            nav_command += f":substation={substation_id}"

        suggestions: List[str] = [nav_command]

        warnings: List[str] = []
        if confidence < 0.5:
            warnings.append(
                f"화면 인식 신뢰도가 낮습니다 ({confidence:.0%}). "
                f"'{screen_name}'로 이동하시겠습니까?"
            )

        location_hint = ""
        if substation_id:
            location_hint = f" (변전소: {substation_id})"

        answer = (
            f"'{screen_name}'{location_hint}(으)로 이동합니다.\n"
            f"화면 식별자: {screen_id}\n"
            f"인식 신뢰도: {confidence:.0%}"
        )

        return self._build_response(
            answer=answer,
            facts=facts,
            evidence=evidence,
            confidence=confidence,
            warnings=warnings,
            suggestions=suggestions,
        )
