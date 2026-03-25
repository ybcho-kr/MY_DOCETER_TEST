"""에이전트 라우터 — AI-EMS v5.1 Layer 2 오케스트레이터.

Intent 분류 결과에 따라 적절한 에이전트로 라우팅하고 AIResponse를 조립한다.

설계 원칙:
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동, 조치→HITL 운영자 승인
  4. Evidence chain 필수 — AI 응답에 Tool 호출 근거 항상 포함
  5. snapshot_ts 필수 — 모든 응답에 분석 기준 시각 포함
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

import structlog

from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact
from src.layer2.orchestrator.intent import IntentResult, IntentType

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────
# 에이전트 핸들러 타입 정의
# ──────────────────────────────────────────────

AgentHandler = Callable[
    [AgentContext, IntentResult],
    Coroutine[Any, Any, AIResponse],
]


# ──────────────────────────────────────────────
# 스텁 에이전트 핸들러 (Phase 2에서 실제 구현으로 교체)
# ──────────────────────────────────────────────

async def _stub_nl2app_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """NL2App 에이전트 스텁 핸들러.

    EMS 앱 결과 조회 (SE, TP, AGC, SCA) — Phase 2에서 실제 구현.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="nl2app_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] EMS 앱 결과 조회 요청 처리됨 (Phase 2 구현 예정)",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"계통 상태 조회 요청을 받았습니다. "
            f"(NL2App 에이전트 Phase 2 구현 예정)\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=0.5,
        snapshot_ts=context.snapshot_ts,
        warnings=["NL2App 에이전트가 아직 구현되지 않았습니다 (스텁 응답)."],
        suggestions=["Phase 2 구현 후 실제 SE/TP 결과를 반환합니다."],
    )


async def _stub_rag_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """RAG 에이전트 스텁 핸들러.

    도메인 지식 검색 (규정, SOP, 용어) — Phase 2에서 실제 구현.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="rag_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] 도메인 지식 검색 요청 처리됨 (Phase 2 구현 예정)",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"도메인 지식 검색 요청을 받았습니다. "
            f"(RAG 에이전트 Phase 2 구현 예정)\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=0.5,
        snapshot_ts=context.snapshot_ts,
        warnings=["RAG 에이전트가 아직 구현되지 않았습니다 (스텁 응답)."],
        suggestions=["Phase 2 구현 후 규정/SOP 검색 결과를 반환합니다."],
    )


async def _stub_alarm_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """알람 분석 에이전트 스텁 핸들러.

    알람 분석/조회 (HITL 모드) — Phase 2에서 실제 구현.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="alarm_analysis_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] 알람 분석 요청 처리됨 — HITL 승인 대기 (Phase 2 구현 예정)",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"알람 분석 요청을 받았습니다 (HITL 모드 — 운영자 승인 필요).\n"
            f"(알람 분석 에이전트 Phase 2 구현 예정)\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=0.5,
        snapshot_ts=context.snapshot_ts,
        warnings=[
            "알람 분석 에이전트가 아직 구현되지 않았습니다 (스텁 응답).",
            "HITL 모드: 운영자 승인이 필요합니다.",
        ],
        suggestions=["Phase 2 구현 후 실제 알람 분석 결과를 반환합니다."],
    )


async def _stub_study_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """계통검토 에이전트 스텁 핸들러.

    What-if 스터디 (HITL 모드) — Phase 2에서 실제 구현.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="study_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] What-if 스터디 요청 처리됨 — HITL 승인 대기 (Phase 2 구현 예정)",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"계통 스터디 요청을 받았습니다 (HITL 모드 — 운영자 승인 필요).\n"
            f"(계통검토 에이전트 Phase 2 구현 예정)\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=0.5,
        snapshot_ts=context.snapshot_ts,
        warnings=[
            "계통검토 에이전트가 아직 구현되지 않았습니다 (스텁 응답).",
            "HITL 모드: 운영자 승인 후 study: 네임스페이스에서 실행됩니다.",
        ],
        suggestions=[
            "Phase 2 구현 후 ops→study 격리 What-if 결과를 반환합니다.",
            "운영자 승인 전 ops: 네임스페이스는 변경되지 않습니다.",
        ],
    )


async def _stub_navigation_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """NL Navigation 에이전트 스텁 핸들러.

    화면/지도 이동 (HOTL 모드) — Phase 2에서 실제 구현.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="nl_navigation_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] 화면 이동 요청 처리됨 (Phase 2 구현 예정)",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"화면 이동 요청을 받았습니다. "
            f"(NL Navigation 에이전트 Phase 2 구현 예정)\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=0.5,
        snapshot_ts=context.snapshot_ts,
        warnings=["NL Navigation 에이전트가 아직 구현되지 않았습니다 (스텁 응답)."],
        suggestions=["Phase 2 구현 후 GIS/SLD 화면 이동을 지원합니다."],
    )


async def _stub_general_handler(
    context: AgentContext,
    intent: IntentResult,
) -> AIResponse:
    """일반 질문 스텁 핸들러.

    분류 불가 일반 질문 처리.
    """
    start = time.monotonic()
    evidence = EvidenceStep(
        tool_name="general_stub",
        input_params={"query": context.user_query, "intent": intent.intent},
        output_summary="[스텁] 일반 질문 처리됨 — 분류 불가 응답",
        duration_ms=(time.monotonic() - start) * 1000,
    )
    return AIResponse(
        answer=(
            f"질의를 분류하지 못했습니다. "
            f"더 구체적인 질문을 입력해 주세요.\n"
            f"질의: {context.user_query}"
        ),
        facts=[],
        evidence_chain=[evidence],
        confidence=intent.confidence,
        snapshot_ts=context.snapshot_ts,
        warnings=["Intent 분류 신뢰도가 낮아 일반 응답으로 처리되었습니다."],
        suggestions=[
            "계통 상태 조회: '현재 전압 상태 알려줘'",
            "알람 조회: '현재 활성 알람 보여줘'",
            "규정 검색: 'N-1 복구 절차 알려줘'",
            "스터디: '5번 CB 개방하면 어떻게 돼?'",
        ],
    )


# ──────────────────────────────────────────────
# 에이전트 라우터
# ──────────────────────────────────────────────

# 기본 스텁 핸들러 레지스트리 (Phase 2에서 실제 에이전트로 교체)
_DEFAULT_HANDLERS: Dict[IntentType, AgentHandler] = {
    "nl2app": _stub_nl2app_handler,
    "rag": _stub_rag_handler,
    "alarm": _stub_alarm_handler,
    "study": _stub_study_handler,
    "navigation": _stub_navigation_handler,
    "general": _stub_general_handler,
}


class AgentRouter:
    """Intent 분류 결과에 따라 적절한 에이전트로 라우팅한다.

    에이전트 핸들러 레지스트리를 관리하며, Intent별 핸들러를 등록/조회할 수 있다.
    HITL 모드의 경우 승인 요청 메타데이터를 응답에 포함한다.
    """

    def __init__(
        self,
        handlers: Optional[Dict[IntentType, AgentHandler]] = None,
    ) -> None:
        """AgentRouter 초기화.

        Args:
            handlers: Intent별 에이전트 핸들러 딕셔너리.
                      None이면 기본 스텁 핸들러를 사용한다.
        """
        self._handlers: Dict[IntentType, AgentHandler] = (
            handlers if handlers is not None else dict(_DEFAULT_HANDLERS)
        )
        logger.info(
            "agent_router_init",
            registered_intents=list(self._handlers.keys()),
        )

    def register(self, intent: IntentType, handler: AgentHandler) -> None:
        """에이전트 핸들러를 등록한다.

        Phase 2 에이전트 구현 후 이 메서드로 실제 핸들러를 등록한다.

        Args:
            intent: 등록할 Intent 유형
            handler: 비동기 에이전트 핸들러 함수
        """
        self._handlers[intent] = handler
        logger.info("agent_handler_registered", intent=intent)

    async def route(
        self,
        context: AgentContext,
        intent: IntentResult,
    ) -> AIResponse:
        """Intent에 따른 에이전트를 디스패치하고 AIResponse를 반환한다.

        HITL 모드의 경우 응답에 승인 필요 경고를 추가한다.
        Evidence chain은 반드시 1개 이상 포함된다.

        Args:
            context: 에이전트 컨텍스트 (세션, 질의, 네임스페이스, 모드 포함)
            intent: Intent 분류 결과

        Returns:
            AIResponse: Evidence chain 포함 AI 응답
        """
        handler = self._handlers.get(intent.intent, _stub_general_handler)

        logger.info(
            "agent_routing",
            intent=intent.intent,
            mode=intent.mode,
            confidence=intent.confidence,
            session_id=context.session_id,
        )

        start = time.monotonic()
        response = await handler(context, intent)
        elapsed_ms = (time.monotonic() - start) * 1000

        logger.info(
            "agent_routing_complete",
            intent=intent.intent,
            elapsed_ms=round(elapsed_ms, 2),
            evidence_steps=len(response.evidence_chain),
        )

        # HITL 모드 승인 요청 메타데이터 추가
        if intent.mode == "HITL" and context.mode == "HITL":
            hitl_warning = (
                f"[HITL] 이 응답은 운영자 승인이 필요합니다. "
                f"Intent: {intent.intent}, 신뢰도: {intent.confidence:.2f}"
            )
            if hitl_warning not in response.warnings:
                response.warnings.insert(0, hitl_warning)

        return response
