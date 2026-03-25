"""Layer 2 오케스트레이터 모듈 — AI-EMS v5.1.

사용자 자연어 질의를 Intent로 분류하고, 적절한 에이전트로 라우팅하는
오케스트레이션 계층.

주요 컴포넌트:
  - IntentClassifier: 한국어 키워드 기반 Intent 분류기
  - IntentResult: Intent 분류 결과 스키마
  - AgentRouter: Intent별 에이전트 라우터
  - CallGuard: 에이전트 호출 깊이/빈도 제한기
  - Dispatcher: 전체 파이프라인 통합 디스패처

사용 예시::

    from src.layer2.orchestrator import Dispatcher

    dispatcher = Dispatcher()
    response = await dispatcher.dispatch(
        user_query="현재 전압 위반 있어?",
        session_id="session-001",
    )
    # response.answer        → 자연어 응답 문자열
    # response.evidence_chain → Tool 호출 근거 목록
"""
from src.layer2.orchestrator.intent import (
    IntentClassifier,
    IntentResult,
    IntentType,
    ModeType,
    INTENT_MODE_MAP,
    classify_intent_rule_based,
)
from src.layer2.orchestrator.call_guard import (
    CallGuard,
    CallGuardError,
    CallGuardState,
)
from src.layer2.orchestrator.router import AgentRouter
from src.layer2.orchestrator.dispatcher import Dispatcher

__all__ = [
    # Intent 분류
    "IntentClassifier",
    "IntentResult",
    "IntentType",
    "ModeType",
    "INTENT_MODE_MAP",
    "classify_intent_rule_based",
    # CallGuard
    "CallGuard",
    "CallGuardError",
    "CallGuardState",
    # 라우터
    "AgentRouter",
    # 디스패처
    "Dispatcher",
]
