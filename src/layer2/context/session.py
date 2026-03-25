"""세션 관리자 — 다중 회전 대화 컨텍스트 추적.

설계 원칙:
  5. snapshot_ts 필수 — 모든 AgentContext에 분석 기준 시각 포함
  Layer 2 CLAUDE.md 규칙:
  - structured_facts: 최근 20건 FIFO, 압축 금지
  - evidence_chain: 최근 5단계 압축 금지
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, Field

from src.shared.schemas.agent import AgentContext, EvidenceStep, StructuredFact

logger = structlog.get_logger(__name__)

# 세션에서 유지할 최대 structured_facts 건수 (FIFO)
_MAX_FACTS: int = 20

# 세션에서 유지할 최대 evidence_chain 단계 수 (압축 금지, FIFO)
_MAX_EVIDENCE: int = 5


def _utcnow() -> datetime:
    """현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


class SessionState(BaseModel):
    """단일 세션의 전체 상태.

    AgentContext(Pydantic v2) 외에 세션별 부가 상태를 포함한다.
    """

    context: AgentContext = Field(
        description="현재 AgentContext 스냅샷.",
    )
    structured_facts: list[StructuredFact] = Field(
        default_factory=list,
        description="구조화된 사실 목록. 최근 max_facts건만 유지 (FIFO, 압축 금지).",
    )
    evidence_chain: list[EvidenceStep] = Field(
        default_factory=list,
        description="Evidence chain. 최근 max_evidence단계만 유지 (압축 금지).",
    )
    turn_count: int = Field(
        default=0,
        description="대화 회전 수.",
    )
    closed: bool = Field(
        default=False,
        description="세션 종료 여부.",
    )


class SessionManager:
    """에이전트 세션 관리자. 다중 회전 대화를 추적한다.

    structured_facts는 최근 max_facts건 FIFO로 관리하며 절대 압축하지 않는다.
    evidence_chain은 최근 max_evidence단계 FIFO로 관리하며 압축하지 않는다.

    사용 예:
        manager = SessionManager()
        ctx = manager.create_session("모선 전압 요약해줘")
        manager.update_facts(ctx.session_id, [StructuredFact(...)])
        manager.add_evidence(ctx.session_id, EvidenceStep(...))
        manager.close_session(ctx.session_id)
    """

    def __init__(self, max_facts: int = _MAX_FACTS, max_evidence: int = _MAX_EVIDENCE) -> None:
        """SessionManager 초기화.

        Args:
            max_facts: 세션당 유지할 최대 structured_facts 건수.
            max_evidence: 세션당 유지할 최대 evidence_chain 단계 수.
        """
        self._sessions: dict[str, SessionState] = {}
        self._max_facts = max_facts
        self._max_evidence = max_evidence

    def create_session(
        self,
        user_query: str,
        mode: Literal["HITL", "HOTL"] = "HOTL",
        namespace: Literal["ops", "study"] = "ops",
        session_id: Optional[str] = None,
    ) -> AgentContext:
        """새 에이전트 세션을 생성하고 AgentContext를 반환한다.

        Args:
            user_query: 사용자 자연어 질의 원문.
            mode: HITL(조치) 또는 HOTL(조회) 분류.
            namespace: 'ops'(read_only) 또는 'study'(write 허용).
            session_id: 지정 세션 ID. None이면 UUID 자동 생성.

        Returns:
            생성된 AgentContext (snapshot_ts 포함).
        """
        sid = session_id or str(uuid.uuid4())
        context = AgentContext(
            session_id=sid,
            user_query=user_query,
            namespace=namespace,
            mode=mode,
            snapshot_ts=_utcnow(),
        )
        self._sessions[sid] = SessionState(context=context)
        logger.info(
            "session_created",
            session_id=sid,
            mode=mode,
            namespace=namespace,
        )
        return context

    def get_session(self, session_id: str) -> Optional[AgentContext]:
        """세션 ID로 AgentContext를 조회한다.

        Args:
            session_id: 조회할 세션 ID.

        Returns:
            AgentContext 또는 None (세션 없음 또는 종료됨).
        """
        state = self._sessions.get(session_id)
        if state is None or state.closed:
            return None
        return state.context

    def get_session_state(self, session_id: str) -> Optional[SessionState]:
        """세션 ID로 SessionState 전체를 조회한다. (내부 및 테스트 용도)

        Args:
            session_id: 조회할 세션 ID.

        Returns:
            SessionState 또는 None.
        """
        state = self._sessions.get(session_id)
        if state is None or state.closed:
            return None
        return state

    def update_facts(self, session_id: str, facts: list[StructuredFact]) -> None:
        """세션의 structured_facts를 업데이트한다.

        새 facts를 추가하고 최대 max_facts건을 초과하면
        가장 오래된 항목부터 제거한다 (FIFO). 절대 압축하지 않는다.

        Args:
            session_id: 업데이트할 세션 ID.
            facts: 추가할 StructuredFact 목록.

        Raises:
            KeyError: 세션이 없거나 종료된 경우.
        """
        state = self._get_active_state(session_id)
        state.structured_facts.extend(facts)
        # FIFO: 최대 max_facts건 유지, 초과 시 앞에서 제거
        if len(state.structured_facts) > self._max_facts:
            state.structured_facts = state.structured_facts[-self._max_facts:]
        logger.debug(
            "session_facts_updated",
            session_id=session_id,
            total_facts=len(state.structured_facts),
        )

    def add_evidence(self, session_id: str, step: EvidenceStep) -> None:
        """세션의 evidence_chain에 단계를 추가한다.

        최대 max_evidence단계를 초과하면 가장 오래된 항목부터 제거한다 (FIFO).
        절대 압축하지 않는다.

        Args:
            session_id: 업데이트할 세션 ID.
            step: 추가할 EvidenceStep.

        Raises:
            KeyError: 세션이 없거나 종료된 경우.
        """
        state = self._get_active_state(session_id)
        state.evidence_chain.append(step)
        # FIFO: 최대 max_evidence단계 유지
        if len(state.evidence_chain) > self._max_evidence:
            state.evidence_chain = state.evidence_chain[-self._max_evidence:]
        logger.debug(
            "session_evidence_added",
            session_id=session_id,
            tool_name=step.tool_name,
            total_evidence=len(state.evidence_chain),
        )

    def increment_turn(self, session_id: str) -> int:
        """대화 회전 수를 증가시키고 현재 값을 반환한다.

        Args:
            session_id: 세션 ID.

        Returns:
            증가 후 turn_count.
        """
        state = self._get_active_state(session_id)
        state.turn_count += 1
        return state.turn_count

    def close_session(self, session_id: str) -> None:
        """세션을 종료한다.

        종료 후 get_session()은 None을 반환한다.

        Args:
            session_id: 종료할 세션 ID.
        """
        state = self._sessions.get(session_id)
        if state is not None:
            state.closed = True
            logger.info(
                "session_closed",
                session_id=session_id,
                turn_count=state.turn_count,
            )

    # ──────────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────────

    def _get_active_state(self, session_id: str) -> SessionState:
        """활성 세션 상태를 반환한다.

        Raises:
            KeyError: 세션이 없거나 이미 종료된 경우.
        """
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(f"세션을 찾을 수 없음: session_id={session_id}")
        if state.closed:
            raise KeyError(f"이미 종료된 세션: session_id={session_id}")
        return state
