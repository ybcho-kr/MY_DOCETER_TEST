"""통합 디스패처 — AI-EMS v5.1 Layer 2 오케스트레이터.

사용자 질의 → Intent 분류 → CallGuard 검증 → 에이전트 라우팅 → AIResponse 반환.
전체 오케스트레이션 파이프라인의 진입점.

설계 원칙:
  2. ops/study 네임스페이스 격리 — AI는 ops: 절대 write 불가
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동, 조치→HITL 운영자 승인
  4. Evidence chain 필수 — AI 응답에 Tool 호출 근거 항상 포함
  5. snapshot_ts 필수 — 모든 응답에 분석 기준 시각 포함
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Literal, Optional

import structlog

from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep
from src.layer2.orchestrator.intent import IntentClassifier, IntentResult, INTENT_MODE_MAP
from src.layer2.orchestrator.router import AgentRouter
from src.layer2.orchestrator.call_guard import CallGuard, CallGuardError

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    """현재 UTC 시각을 반환한다 (snapshot_ts 생성용)."""
    return datetime.now(timezone.utc)


class Dispatcher:
    """사용자 질의 전체 파이프라인을 실행하는 통합 디스패처.

    파이프라인 순서:
      1. AgentContext 생성 (snapshot_ts 포함)
      2. Intent 분류 (IntentClassifier)
      3. CallGuard 검증 (깊이/연속 호출 제한)
      4. 에이전트 라우팅 (AgentRouter)
      5. AIResponse 반환 (evidence_chain 최소 1개 보장)

    세션별 CallGuard 상태를 관리한다.
    """

    def __init__(
        self,
        intent_classifier: Optional[IntentClassifier] = None,
        agent_router: Optional[AgentRouter] = None,
        default_namespace: Literal["ops", "study"] = "ops",
    ) -> None:
        """Dispatcher 초기화.

        Args:
            intent_classifier: Intent 분류기. None이면 기본 규칙 기반 분류기 사용.
            agent_router: 에이전트 라우터. None이면 기본 스텁 라우터 사용.
            default_namespace: 기본 네임스페이스 (기본: ops — AI read_only).
        """
        self._classifier = intent_classifier or IntentClassifier()
        self._router = agent_router or AgentRouter()
        self._default_namespace = default_namespace

        # 세션별 CallGuard 관리
        self._session_guards: Dict[str, CallGuard] = {}

        logger.info(
            "dispatcher_init",
            default_namespace=default_namespace,
        )

    def _get_or_create_guard(self, session_id: str) -> CallGuard:
        """세션 ID에 해당하는 CallGuard를 반환하거나 새로 생성한다.

        Args:
            session_id: 세션 고유 식별자

        Returns:
            해당 세션의 CallGuard 인스턴스
        """
        if session_id not in self._session_guards:
            self._session_guards[session_id] = CallGuard()
            logger.debug("call_guard_created", session_id=session_id)
        return self._session_guards[session_id]

    def reset_session(self, session_id: str) -> None:
        """세션 CallGuard를 초기화한다.

        새 대화 시작 또는 오류 복구 시 호출한다.

        Args:
            session_id: 초기화할 세션 고유 식별자
        """
        if session_id in self._session_guards:
            self._session_guards[session_id].reset()
            logger.info("session_guard_reset", session_id=session_id)

    async def dispatch(
        self,
        user_query: str,
        session_id: Optional[str] = None,
        namespace: Optional[Literal["ops", "study"]] = None,
    ) -> AIResponse:
        """사용자 질의 전체 파이프라인을 실행한다.

        파이프라인:
          1. AgentContext 생성 (snapshot_ts, session_id, HITL/HOTL 모드 포함)
          2. Intent 분류 (키워드 규칙 기반 또는 LLM 강화)
          3. CallGuard 검증 (depth ≤ 5, 동일 에이전트 연속 ≤ 2)
          4. 에이전트 라우팅 및 응답 생성
          5. AIResponse 반환 (evidence_chain 최소 1개 필수)

        Args:
            user_query: 사용자 자연어 질의
            session_id: 세션 고유 식별자. None이면 새 UUID 생성.
            namespace: 네임스페이스 override. None이면 default_namespace 사용.

        Returns:
            AIResponse: Evidence chain 포함 AI 응답

        Note:
            - CallGuard 차단 시 오류 응답 AIResponse를 반환 (예외 전파 안 함)
            - 미처리 예외는 로그 후 오류 응답 반환
        """
        # 세션 ID 확보
        resolved_session_id = session_id or str(uuid.uuid4())
        resolved_namespace = namespace or self._default_namespace
        snapshot_ts = _utcnow()

        logger.info(
            "dispatch_start",
            session_id=resolved_session_id,
            query=user_query[:50],
            namespace=resolved_namespace,
        )

        dispatch_start = time.monotonic()

        # ── Step 1: Intent 분류 ──────────────────────────────
        try:
            intent: IntentResult = await self._classifier.classify(user_query)
        except Exception as exc:
            logger.error("intent_classification_failed", error=str(exc))
            return self._build_error_response(
                error_msg=f"Intent 분류 실패: {exc}",
                user_query=user_query,
                snapshot_ts=snapshot_ts,
                step="intent_classification",
            )

        # Intent 기반 모드 결정
        mode = INTENT_MODE_MAP[intent.intent]

        # ── Step 2: AgentContext 생성 ────────────────────────
        context = AgentContext(
            session_id=resolved_session_id,
            user_query=user_query,
            namespace=resolved_namespace,
            mode=mode,
            snapshot_ts=snapshot_ts,
        )

        # ── Step 3: CallGuard 검증 ───────────────────────────
        guard = self._get_or_create_guard(resolved_session_id)
        agent_name = intent.intent  # 에이전트 이름으로 Intent 사용

        if not guard.check(agent_name):
            guard_state = guard.state
            logger.warning(
                "call_guard_blocked",
                agent_name=agent_name,
                depth=guard_state.depth,
                session_id=resolved_session_id,
            )
            return self._build_error_response(
                error_msg=(
                    f"CallGuard 차단: '{agent_name}' 에이전트 호출이 제한되었습니다. "
                    f"(깊이: {guard_state.depth}/{guard.max_depth}, "
                    f"연속: {guard_state.agent_consecutive_count})"
                ),
                user_query=user_query,
                snapshot_ts=snapshot_ts,
                step="call_guard",
            )

        # CallGuard 기록
        try:
            guard.record(agent_name)
        except CallGuardError as exc:
            logger.warning("call_guard_error", error=str(exc))
            return self._build_error_response(
                error_msg=str(exc),
                user_query=user_query,
                snapshot_ts=snapshot_ts,
                step="call_guard",
            )

        # ── Step 4: 에이전트 라우팅 ─────────────────────────
        try:
            response = await self._router.route(context, intent)
        except Exception as exc:
            logger.error(
                "agent_routing_failed",
                intent=intent.intent,
                error=str(exc),
                session_id=resolved_session_id,
            )
            response = self._build_error_response(
                error_msg=f"에이전트 라우팅 실패: {exc}",
                user_query=user_query,
                snapshot_ts=snapshot_ts,
                step="agent_routing",
            )
        finally:
            guard.release()

        elapsed_ms = (time.monotonic() - dispatch_start) * 1000
        logger.info(
            "dispatch_complete",
            session_id=resolved_session_id,
            intent=intent.intent,
            mode=mode,
            elapsed_ms=round(elapsed_ms, 2),
            evidence_steps=len(response.evidence_chain),
        )

        return response

    @staticmethod
    def _build_error_response(
        error_msg: str,
        user_query: str,
        snapshot_ts: datetime,
        step: str,
    ) -> AIResponse:
        """오류 응답 AIResponse를 생성한다.

        Evidence chain 최소 1개를 포함하여 스키마 제약을 만족한다.

        Args:
            error_msg: 오류 메시지
            user_query: 원본 사용자 질의
            snapshot_ts: 오류 발생 시각
            step: 오류 발생 파이프라인 단계

        Returns:
            AIResponse: 오류 정보를 담은 최소 응답
        """
        evidence = EvidenceStep(
            tool_name=f"error_handler_{step}",
            input_params={"query": user_query, "step": step},
            output_summary=f"오류 발생: {error_msg}",
            duration_ms=0.0,
        )
        return AIResponse(
            answer=f"처리 중 오류가 발생했습니다: {error_msg}",
            facts=[],
            evidence_chain=[evidence],
            confidence=0.0,
            snapshot_ts=snapshot_ts,
            warnings=[f"파이프라인 오류 ({step}): {error_msg}"],
            suggestions=["다시 시도하거나 관리자에게 문의하세요."],
        )
