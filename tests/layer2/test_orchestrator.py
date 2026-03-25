"""Layer 2 오케스트레이터 테스트 — AI-EMS v5.1.

테스트 범위:
  - Intent 분류 정확도 (최소 20건 시나리오)
  - HITL/HOTL 분류 정확도 100%
  - CallGuard 깊이 제한 (depth > 5 차단)
  - CallGuard 연속 호출 제한 (동일 에이전트 3회 차단)
  - AgentContext 생성 및 snapshot_ts 포함 확인
  - Dispatcher 파이프라인 E2E (mock 에이전트)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.layer2.orchestrator.intent import (
    IntentClassifier,
    IntentResult,
    INTENT_MODE_MAP,
    classify_intent_rule_based,
)
from src.layer2.orchestrator.call_guard import CallGuard, CallGuardError
from src.layer2.orchestrator.router import AgentRouter
from src.layer2.orchestrator.dispatcher import Dispatcher
from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def make_dummy_response(intent: str = "general") -> AIResponse:
    """테스트용 더미 AIResponse 생성."""
    return AIResponse(
        answer=f"[테스트 응답] intent={intent}",
        facts=[],
        evidence_chain=[
            EvidenceStep(
                tool_name="test_tool",
                input_params={"intent": intent},
                output_summary="테스트 응답 생성됨",
                duration_ms=1.0,
            )
        ],
        confidence=0.9,
        snapshot_ts=datetime.now(timezone.utc),
        warnings=[],
        suggestions=[],
    )


# ──────────────────────────────────────────────
# Intent 분류 정확도 테스트 (20건 시나리오)
# ──────────────────────────────────────────────

class TestIntentClassification:
    """Intent 분류 정확도 테스트.

    최소 20건의 시나리오를 검증한다.
    HITL/HOTL 분류 정확도 100% 달성이 목표.
    """

    # (질의, 예상 intent, 예상 mode)
    SCENARIOS = [
        # ── nl2app (HOTL) 시나리오 ──
        ("계통 상태 요약해줘", "nl2app", "HOTL"),
        ("현재 전압 위반 있어?", "nl2app", "HOTL"),
        ("현재 주파수 확인해줘", "nl2app", "HOTL"),
        ("조류 현황 보여줘", "nl2app", "HOTL"),
        ("AGC 상태 알려줘", "nl2app", "HOTL"),
        ("예비력 현황 조회해줘", "nl2app", "HOTL"),
        ("상태 요약 부탁해", "nl2app", "HOTL"),
        ("현재 전압 값 알려줘", "nl2app", "HOTL"),

        # ── study (HITL) 시나리오 ──
        ("5번 CB 개방하면 어떻게 돼?", "study", "HITL"),
        ("만약 1번 선로가 고장나면?", "study", "HITL"),
        ("CB 3 개방했을 때 영향은?", "study", "HITL"),
        ("부하 증가하면 어떻게 됩니까?", "study", "HITL"),
        ("N-1 스터디 실행해줘", "study", "HITL"),
        ("변압기 탈락할 경우 분석해줘", "study", "HITL"),

        # ── rag (HOTL) 시나리오 ──
        ("N-1 복구 절차 알려줘", "rag", "HOTL"),
        ("산업통상자원부 고시 제15조 내용은?", "rag", "HOTL"),
        ("복구 절차 SOP 검색해줘", "rag", "HOTL"),
        ("고장 복구 절차 알려줘", "rag", "HOTL"),

        # ── alarm (HITL) 시나리오 ──
        ("활성 알람 보여줘", "alarm", "HITL"),
        ("현재 경보 현황 알려줘", "alarm", "HITL"),
        ("전압 위반 알람 확인해줘", "alarm", "HITL"),
        ("과부하 경보 분석해줘", "alarm", "HITL"),

        # ── navigation (HOTL) 시나리오 ──
        ("변전소 화면으로 이동", "navigation", "HOTL"),
        ("GIS 지도로 이동해줘", "navigation", "HOTL"),
        ("단선도 보여줘", "navigation", "HOTL"),
        ("대시보드 열어줘", "navigation", "HOTL"),
    ]

    @pytest.mark.parametrize("query,expected_intent,expected_mode", SCENARIOS)
    def test_intent_classification_scenario(
        self,
        query: str,
        expected_intent: str,
        expected_mode: str,
    ) -> None:
        """개별 시나리오 Intent 분류 검증."""
        result = classify_intent_rule_based(query)

        assert result.intent == expected_intent, (
            f"질의: '{query}'\n"
            f"예상 intent: {expected_intent}, 실제 intent: {result.intent}\n"
            f"근거: {result.reasoning}"
        )
        assert result.mode == expected_mode, (
            f"질의: '{query}'\n"
            f"예상 mode: {expected_mode}, 실제 mode: {result.mode}"
        )

    def test_total_scenario_count(self) -> None:
        """시나리오 최소 20건 확인."""
        assert len(self.SCENARIOS) >= 20, f"시나리오 수가 20건 미만: {len(self.SCENARIOS)}"

    def test_hitl_hotl_accuracy_100_percent(self) -> None:
        """HITL/HOTL 분류 정확도 100% 확인."""
        errors = []
        for query, expected_intent, expected_mode in self.SCENARIOS:
            result = classify_intent_rule_based(query)
            if result.mode != expected_mode:
                errors.append(
                    f"질의: '{query}' → 예상: {expected_mode}, 실제: {result.mode}"
                )

        assert len(errors) == 0, (
            f"HITL/HOTL 분류 오류 {len(errors)}건:\n" + "\n".join(errors)
        )

    def test_intent_result_schema_valid(self) -> None:
        """IntentResult 스키마 유효성 확인."""
        result = classify_intent_rule_based("계통 상태 요약해줘")

        assert isinstance(result, IntentResult)
        assert 0.0 <= result.confidence <= 1.0
        assert result.intent in ["nl2app", "rag", "alarm", "study", "navigation", "general"]
        assert result.mode in ["HITL", "HOTL"]
        assert len(result.reasoning) > 0

    def test_intent_mode_map_completeness(self) -> None:
        """INTENT_MODE_MAP이 모든 Intent 유형을 커버하는지 확인."""
        all_intents = {"nl2app", "rag", "alarm", "study", "navigation", "general"}
        mapped_intents = set(INTENT_MODE_MAP.keys())
        assert all_intents == mapped_intents, (
            f"누락된 Intent: {all_intents - mapped_intents}"
        )

    def test_hitl_intents(self) -> None:
        """HITL 분류 Intent 확인 (alarm, study만 HITL이어야 함)."""
        hitl_intents = {k for k, v in INTENT_MODE_MAP.items() if v == "HITL"}
        assert hitl_intents == {"alarm", "study"}, (
            f"HITL Intent 불일치: {hitl_intents}"
        )

    def test_hotl_intents(self) -> None:
        """HOTL 분류 Intent 확인 (nl2app, rag, navigation, general)."""
        hotl_intents = {k for k, v in INTENT_MODE_MAP.items() if v == "HOTL"}
        assert hotl_intents == {"nl2app", "rag", "navigation", "general"}, (
            f"HOTL Intent 불일치: {hotl_intents}"
        )

    def test_low_confidence_fallback_to_general(self) -> None:
        """매칭 패턴 없는 질의는 general로 폴백하는지 확인."""
        result = classify_intent_rule_based("오늘 날씨 어때?")
        assert result.intent == "general"
        assert result.mode == "HOTL"

    def test_confidence_range(self) -> None:
        """신뢰도 범위가 0~1 사이인지 확인."""
        test_queries = [
            "계통 상태 요약해줘",
            "CB 5 개방하면?",
            "알람 보여줘",
            "절차 알려줘",
            "화면 이동",
            "안녕하세요",
        ]
        for query in test_queries:
            result = classify_intent_rule_based(query)
            assert 0.0 <= result.confidence <= 1.0, (
                f"신뢰도 범위 초과: query='{query}', confidence={result.confidence}"
            )


# ──────────────────────────────────────────────
# IntentClassifier (비동기) 테스트
# ──────────────────────────────────────────────

class TestIntentClassifier:
    """IntentClassifier 클래스 테스트."""

    @pytest.mark.asyncio
    async def test_classify_async_nl2app(self) -> None:
        """비동기 분류 — nl2app 확인."""
        classifier = IntentClassifier()
        result = await classifier.classify("현재 전압 상태 알려줘")
        assert result.intent == "nl2app"
        assert result.mode == "HOTL"

    @pytest.mark.asyncio
    async def test_classify_async_study(self) -> None:
        """비동기 분류 — study (HITL) 확인."""
        classifier = IntentClassifier()
        result = await classifier.classify("5번 CB 개방하면 어떻게 돼?")
        assert result.intent == "study"
        assert result.mode == "HITL"

    def test_classify_sync(self) -> None:
        """동기 분류 메서드 확인."""
        classifier = IntentClassifier()
        result = classifier.classify_sync("N-1 복구 절차 알려줘")
        assert result.intent == "rag"
        assert result.mode == "HOTL"

    @pytest.mark.asyncio
    async def test_classify_returns_intent_result(self) -> None:
        """반환 타입이 IntentResult인지 확인."""
        classifier = IntentClassifier()
        result = await classifier.classify("계통 상태 요약해줘")
        assert isinstance(result, IntentResult)


# ──────────────────────────────────────────────
# CallGuard 테스트
# ──────────────────────────────────────────────

class TestCallGuard:
    """CallGuard 호출 제한 테스트."""

    def test_normal_calls_within_limit(self) -> None:
        """정상 범위 내 호출은 허용되어야 함."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        # 5번 호출 (다른 에이전트) — 모두 통과해야 함
        agents = ["nl2app", "rag", "alarm", "study", "navigation"]
        for agent in agents:
            assert guard.check(agent), f"{agent} 호출이 차단됨"
            guard.record(agent)
            guard.release()

    def test_depth_limit_blocks_6th_call(self) -> None:
        """6번째 호출은 depth 초과로 차단되어야 함 (max_depth=5)."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        # 5번 호출 기록 (release 없이)
        for i in range(5):
            guard.record(f"agent_{i}")

        # 6번째 호출 → 차단
        assert not guard.check("agent_5"), "6번째 호출이 차단되지 않음"

        # record()도 예외 발생해야 함
        with pytest.raises(CallGuardError) as exc_info:
            guard.record("agent_5")
        assert "깊이 초과" in str(exc_info.value)

    def test_depth_limit_exact_boundary(self) -> None:
        """max_depth=5일 때 5번째 호출은 허용, 6번째는 차단."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        for i in range(4):
            guard.record(f"agent_{i}")

        # 5번째 호출 — 허용 (depth가 4 → 5로 증가)
        assert guard.check("agent_4"), "5번째 호출이 차단됨"
        guard.record("agent_4")
        assert guard.current_depth == 5

        # 6번째 호출 — 차단 (depth가 5이므로)
        assert not guard.check("agent_5"), "6번째 호출이 차단되지 않음"

    def test_consecutive_same_agent_blocks_3rd(self) -> None:
        """동일 에이전트 3번째 연속 호출은 차단되어야 함 (max_consecutive_same=2)."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        # nl2app 1번 → 통과
        assert guard.check("nl2app")
        guard.record("nl2app")

        # nl2app 2번 연속 → 통과 (max_consecutive_same=2이므로)
        assert guard.check("nl2app")
        guard.record("nl2app")

        # nl2app 3번 연속 → 차단
        assert not guard.check("nl2app"), "동일 에이전트 3번째 연속 호출이 차단되지 않음"

        with pytest.raises(CallGuardError) as exc_info:
            guard.record("nl2app")
        assert "연속 호출 초과" in str(exc_info.value)

    def test_different_agent_resets_consecutive(self) -> None:
        """다른 에이전트 호출 시 연속 카운터가 초기화되어야 함."""
        guard = CallGuard(max_depth=10, max_consecutive_same=2)

        guard.record("nl2app")
        guard.record("nl2app")  # 2번 연속

        # 다른 에이전트 호출 → 연속 카운터 초기화
        guard.record("rag")

        # nl2app 다시 호출 가능
        assert guard.check("nl2app"), "연속 카운터 초기화 후 nl2app 호출이 차단됨"

    def test_reset_clears_all_state(self) -> None:
        """reset() 후 모든 상태가 초기화되어야 함."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        # 깊이 한계까지 채우기
        for i in range(5):
            guard.record(f"agent_{i}")

        assert guard.current_depth == 5
        assert not guard.check("new_agent")

        # reset 후
        guard.reset()
        assert guard.current_depth == 0
        assert guard.check("new_agent"), "reset 후 호출이 차단됨"

    def test_release_decrements_depth(self) -> None:
        """release() 호출 시 깊이가 감소해야 함."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        guard.record("nl2app")
        assert guard.current_depth == 1

        guard.release()
        assert guard.current_depth == 0

    def test_state_snapshot(self) -> None:
        """state 프로퍼티가 현재 상태를 올바르게 반환해야 함."""
        guard = CallGuard(max_depth=5, max_consecutive_same=2)

        guard.record("nl2app")
        guard.record("rag")

        state = guard.state
        assert state.depth == 2
        assert "nl2app" in state.call_history
        assert "rag" in state.call_history
        assert state.last_agent == "rag"

    def test_release_does_not_go_below_zero(self) -> None:
        """release() 호출 시 깊이가 0 미만으로 내려가지 않아야 함."""
        guard = CallGuard()
        guard.release()  # 0 상태에서 release
        assert guard.current_depth == 0


# ──────────────────────────────────────────────
# AgentContext 테스트
# ──────────────────────────────────────────────

class TestAgentContext:
    """AgentContext 생성 및 스키마 유효성 테스트."""

    def test_agent_context_creation_with_snapshot_ts(self) -> None:
        """AgentContext 생성 시 snapshot_ts가 자동 포함되어야 함."""
        context = AgentContext(
            session_id="test-session-001",
            user_query="계통 상태 요약해줘",
            namespace="ops",
            mode="HOTL",
        )

        assert context.session_id == "test-session-001"
        assert context.user_query == "계통 상태 요약해줘"
        assert context.namespace == "ops"
        assert context.mode == "HOTL"
        assert context.snapshot_ts is not None
        assert isinstance(context.snapshot_ts, datetime)

    def test_agent_context_snapshot_ts_is_utc(self) -> None:
        """snapshot_ts가 UTC 시간대인지 확인."""
        context = AgentContext(
            session_id="test-session-002",
            user_query="테스트 질의",
            namespace="ops",
            mode="HOTL",
        )
        assert context.snapshot_ts.tzinfo is not None

    def test_agent_context_hitl_mode(self) -> None:
        """HITL 모드 AgentContext 생성 확인."""
        context = AgentContext(
            session_id="test-session-003",
            user_query="5번 CB 개방하면?",
            namespace="ops",
            mode="HITL",
        )
        assert context.mode == "HITL"

    def test_agent_context_study_namespace(self) -> None:
        """study 네임스페이스 AgentContext 생성 확인."""
        context = AgentContext(
            session_id="test-session-004",
            user_query="스터디 실행",
            namespace="study",
            mode="HITL",
        )
        assert context.namespace == "study"


# ──────────────────────────────────────────────
# Dispatcher 파이프라인 E2E 테스트
# ──────────────────────────────────────────────

class TestDispatcher:
    """Dispatcher 전체 파이프라인 E2E 테스트."""

    @pytest.mark.asyncio
    async def test_dispatch_nl2app_query(self) -> None:
        """nl2app 질의 파이프라인 정상 동작 확인."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="현재 전압 상태 알려줘",
            session_id="test-e2e-001",
        )

        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1
        assert response.snapshot_ts is not None
        assert response.confidence >= 0.0

    @pytest.mark.asyncio
    async def test_dispatch_study_query_hitl(self) -> None:
        """study 질의 HITL 모드 확인."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="5번 CB 개방하면 어떻게 돼?",
            session_id="test-e2e-002",
        )

        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1
        # HITL 모드 경고 포함 확인
        hitl_warnings = [w for w in response.warnings if "HITL" in w]
        assert len(hitl_warnings) >= 1, "HITL 경고가 포함되지 않음"

    @pytest.mark.asyncio
    async def test_dispatch_alarm_query_hitl(self) -> None:
        """alarm 질의 HITL 모드 확인."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="활성 알람 보여줘",
            session_id="test-e2e-003",
        )

        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_generates_session_id_if_none(self) -> None:
        """session_id가 None이면 UUID가 자동 생성되어야 함."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="계통 상태 요약해줘",
            session_id=None,
        )
        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_evidence_chain_min_1(self) -> None:
        """모든 응답에 evidence_chain이 최소 1개 포함되어야 함."""
        dispatcher = Dispatcher()
        test_queries = [
            "현재 전압 상태",
            "5번 CB 개방하면?",
            "알람 보여줘",
            "절차 알려줘",
            "화면 이동",
            "안녕하세요",
        ]
        for query in test_queries:
            response = await dispatcher.dispatch(
                user_query=query,
                session_id=str(uuid.uuid4()),
            )
            assert len(response.evidence_chain) >= 1, (
                f"질의 '{query}'에 대한 evidence_chain이 비어있음"
            )

    @pytest.mark.asyncio
    async def test_dispatch_snapshot_ts_always_present(self) -> None:
        """모든 응답에 snapshot_ts가 포함되어야 함 (설계 원칙 5)."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="계통 상태 요약해줘",
            session_id="test-snapshot-001",
        )
        assert response.snapshot_ts is not None
        assert isinstance(response.snapshot_ts, datetime)

    @pytest.mark.asyncio
    async def test_dispatch_with_mock_handler(self) -> None:
        """커스텀 mock 핸들러로 라우팅 테스트."""
        mock_response = make_dummy_response("nl2app")
        mock_handler = AsyncMock(return_value=mock_response)

        router = AgentRouter(handlers={"nl2app": mock_handler})  # type: ignore[arg-type]
        dispatcher = Dispatcher(agent_router=router)

        response = await dispatcher.dispatch(
            user_query="현재 전압 상태 알려줘",
            session_id="test-mock-001",
        )

        assert response.answer == mock_response.answer
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_call_guard_blocks_depth_exceeded(self) -> None:
        """CallGuard depth 초과 시 오류 응답을 반환해야 함."""
        dispatcher = Dispatcher()
        session_id = "test-guard-depth-001"
        guard = dispatcher._get_or_create_guard(session_id)

        # depth를 최대치까지 채우기 (release 없이)
        for i in range(5):
            guard.record(f"agent_{i}")

        # 다음 호출 → CallGuard 차단 → 오류 응답
        response = await dispatcher.dispatch(
            user_query="현재 전압 상태",
            session_id=session_id,
        )

        assert len(response.evidence_chain) >= 1
        assert len(response.warnings) >= 1
        assert response.confidence == 0.0

    @pytest.mark.asyncio
    async def test_dispatch_rag_query(self) -> None:
        """RAG 질의 파이프라인 정상 동작 확인."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="N-1 복구 절차 알려줘",
            session_id="test-rag-001",
        )
        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_navigation_query(self) -> None:
        """navigation 질의 파이프라인 정상 동작 확인."""
        dispatcher = Dispatcher()
        response = await dispatcher.dispatch(
            user_query="변전소 화면으로 이동",
            session_id="test-nav-001",
        )
        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_multiple_sessions_independent(self) -> None:
        """서로 다른 세션은 독립적인 CallGuard를 가져야 함."""
        dispatcher = Dispatcher()

        session_a = "session-a-001"
        session_b = "session-b-001"

        # 세션 A: 깊이를 최대까지 채우기
        guard_a = dispatcher._get_or_create_guard(session_a)
        for i in range(5):
            guard_a.record(f"agent_{i}")

        # 세션 B: 정상 동작해야 함
        response_b = await dispatcher.dispatch(
            user_query="현재 전압 상태",
            session_id=session_b,
        )
        assert isinstance(response_b, AIResponse)
        assert response_b.confidence > 0.0, "세션 B가 차단되면 안 됨"

    def test_reset_session(self) -> None:
        """세션 CallGuard 초기화 동작 확인."""
        dispatcher = Dispatcher()
        session_id = "test-reset-001"

        guard = dispatcher._get_or_create_guard(session_id)
        for i in range(5):
            guard.record(f"agent_{i}")

        assert guard.current_depth == 5

        dispatcher.reset_session(session_id)
        assert guard.current_depth == 0


# ──────────────────────────────────────────────
# AgentRouter 테스트
# ──────────────────────────────────────────────

class TestAgentRouter:
    """AgentRouter 라우팅 테스트."""

    @pytest.mark.asyncio
    async def test_route_nl2app(self) -> None:
        """nl2app Intent 라우팅 확인."""
        router = AgentRouter()
        context = AgentContext(
            session_id="test-router-001",
            user_query="현재 전압 상태 알려줘",
            namespace="ops",
            mode="HOTL",
        )
        intent = IntentResult(
            intent="nl2app",
            confidence=0.9,
            mode="HOTL",
            reasoning="테스트",
        )
        response = await router.route(context, intent)
        assert isinstance(response, AIResponse)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_route_hitl_adds_warning(self) -> None:
        """HITL 모드 라우팅 시 경고 메시지가 추가되어야 함."""
        router = AgentRouter()
        context = AgentContext(
            session_id="test-router-002",
            user_query="5번 CB 개방하면?",
            namespace="ops",
            mode="HITL",
        )
        intent = IntentResult(
            intent="study",
            confidence=0.95,
            mode="HITL",
            reasoning="테스트",
        )
        response = await router.route(context, intent)
        hitl_warnings = [w for w in response.warnings if "HITL" in w]
        assert len(hitl_warnings) >= 1

    def test_register_custom_handler(self) -> None:
        """커스텀 핸들러 등록 확인."""
        router = AgentRouter()
        custom_handler = AsyncMock(return_value=make_dummy_response("nl2app"))
        router.register("nl2app", custom_handler)  # type: ignore[arg-type]
        assert router._handlers["nl2app"] == custom_handler

    @pytest.mark.asyncio
    async def test_route_all_intents(self) -> None:
        """모든 Intent 유형에 대해 라우팅이 성공해야 함."""
        router = AgentRouter()
        all_intents = ["nl2app", "rag", "alarm", "study", "navigation", "general"]

        for intent_type in all_intents:
            mode = INTENT_MODE_MAP[intent_type]  # type: ignore[index]
            context = AgentContext(
                session_id=f"test-router-{intent_type}",
                user_query=f"테스트 질의 ({intent_type})",
                namespace="ops",
                mode=mode,
            )
            intent = IntentResult(
                intent=intent_type,  # type: ignore[arg-type]
                confidence=0.9,
                mode=mode,
                reasoning="테스트",
            )
            response = await router.route(context, intent)
            assert isinstance(response, AIResponse), (
                f"intent={intent_type} 라우팅 실패"
            )
            assert len(response.evidence_chain) >= 1, (
                f"intent={intent_type} evidence_chain 비어있음"
            )
