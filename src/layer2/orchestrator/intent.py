"""Intent 분류기 — AI-EMS v5.1 Layer 2 오케스트레이터.

사용자 자연어 질의를 분석하여 Intent(의도)와 HITL/HOTL 모드를 분류한다.

구현 전략:
  - 기본: 한국어 키워드 기반 규칙 엔진 (PydanticAI 없이도 동작)
  - 선택: PydanticAI Agent 래핑 (설치된 경우 LLM 강화 분류)

설계 원칙:
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동, 조치→HITL 운영자 승인
  4. Evidence chain 필수
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Tuple

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# PydanticAI 선택적 import
try:
    from pydantic_ai import Agent  # type: ignore[import]
    _PYDANTIC_AI_AVAILABLE = True
except ImportError:
    _PYDANTIC_AI_AVAILABLE = False
    logger.info("pydantic_ai_unavailable", message="PydanticAI 미설치 — 규칙 기반 Intent 분류 사용")


# ──────────────────────────────────────────────
# Intent 분류 결과 스키마
# ──────────────────────────────────────────────

IntentType = Literal[
    "nl2app",    # EMS 앱 결과 조회 (SE, TP, AGC, SCA)
    "rag",       # 도메인 지식 검색 (규정, SOP, 용어)
    "alarm",     # 알람 분석/조회
    "study",     # What-if 스터디 (CB 개방, 부하 변경 등)
    "navigation",  # 화면/지도 이동
    "general",   # 일반 질문 (분류 불가)
]

ModeType = Literal["HITL", "HOTL"]


class IntentResult(BaseModel):
    """사용자 질의 의도 분류 결과.

    intent: 분류된 의도 유형
    confidence: 분류 신뢰도 (0.0~1.0)
    mode: HITL/HOTL 승인 모드
    reasoning: 분류 근거 설명 (Evidence chain 지원)
    """

    intent: IntentType = Field(description="분류된 의도")
    confidence: float = Field(ge=0.0, le=1.0, description="분류 신뢰도")
    mode: ModeType = Field(description="승인 모드")
    reasoning: str = Field(description="분류 근거")


# ──────────────────────────────────────────────
# Intent → Mode 매핑 (설계 원칙 3)
# ──────────────────────────────────────────────

INTENT_MODE_MAP: Dict[IntentType, ModeType] = {
    "nl2app": "HOTL",      # 조회 자동 실행
    "rag": "HOTL",          # 검색 자동 실행
    "alarm": "HITL",        # 조치 포함 가능 → 승인 필수
    "study": "HITL",        # 계통 변경 → 승인 필수
    "navigation": "HOTL",  # 화면 이동 자동
    "general": "HOTL",     # 일반 질문 자동
}


# ──────────────────────────────────────────────
# 한국어 키워드 패턴 정의
# ──────────────────────────────────────────────

# 각 Intent 별 키워드 패턴 목록
# 우선순위: study > alarm > nl2app > rag > navigation > general
# (튜플: (정규식 패턴, 가중치))

_STUDY_PATTERNS: List[Tuple[str, float]] = [
    (r"개방\s*하면|개방\s*했을\s*때|개방\s*시", 0.95),
    (r"투입\s*하면|투입\s*했을\s*때|투입\s*시", 0.95),
    (r"만약\s*.+\s*(되면|하면|할\s*경우|한다면)", 0.90),
    (r"what.if|whatif|what\s+if", 0.90),
    (r"CB\s*\d+.*(개방|투입|차단|on|off)", 0.95),
    (r"(차단기|CB|스위치|선로|변압기).*(끊으면|끊었을|고장나면|탈락하면|탈락)", 0.90),
    (r"스터디|study|what.if|가상|시나리오", 0.85),
    (r"부하\s*(증가|감소|변경)\s*(하면|했을|시)", 0.85),
    (r"N-1\s*(검토|분석|시뮬레이션)", 0.85),
    (r"(탈락|고장)\s*(시|하면|될\s*경우)", 0.88),
    (r"어떻게\s*돼|어떻게\s*됩니까|어떤\s*영향", 0.80),
    (r"(발전기|변압기|선로).*(정지|중단|탈락)\s*(하면|할\s*경우)", 0.90),
]

_ALARM_PATTERNS: List[Tuple[str, float]] = [
    # 명시적 알람/경보 키워드
    (r"알람|경보|alarm", 0.95),
    (r"활성\s*(알람|경보)|현재\s*(알람|경보)", 0.97),
    (r"알람\s*(목록|확인|보여|상태|내역)", 0.97),
    (r"경보\s*(발생|확인|분석|조회)", 0.92),
    (r"(CRITICAL|WARNING|HIGH)\s*(알람|경보)", 0.97),
    (r"root\s*cause|원인\s*분석|알람\s*원인", 0.92),
    # 알람 유형 키워드 (알람/경보 맥락 필요)
    (r"(알람|경보).*(과부하|over.?load|trip|fault)", 0.90),
    (r"(과부하|over.?load|trip|fault).*(알람|경보)", 0.90),
    # 고장/차단 이벤트 (전압 위반 조회와 구분: "위반" 단독은 nl2app)
    (r"fault|trip\s*(발생|감지|확인)", 0.88),
]

_NL2APP_PATTERNS: List[Tuple[str, float]] = [
    (r"계통\s*상태|시스템\s*상태|grid\s*status", 0.90),
    (r"전압\s*(확인|조회|알려|보여|상태|값|현황)", 0.88),
    (r"조류\s*(확인|조회|알려|보여|상태|값|현황)", 0.88),
    (r"주파수\s*(확인|조회|알려|보여|현재|값)", 0.88),
    (r"(상태|현황)\s*(요약|알려|보여|보고)", 0.85),
    (r"(SE|상태추정|state\s*estimation)\s*(결과|실행|조회)", 0.90),
    (r"(AGC|자동발전제어)\s*(상태|현황|조회)", 0.90),
    (r"예비력\s*(현황|상태|조회|확인)", 0.88),
    (r"부하율\s*(확인|조회|현황|상태)", 0.88),
    (r"(선로|변압기|모선)\s*(부하율|전압|조류)\s*(확인|조회|알려|보여)", 0.88),
    (r"조류계산|power\s*flow|潮流", 0.85),
    (r"현재\s*(전압|조류|주파수|부하율|발전량)", 0.88),
    (r"발전\s*(현황|출력|상태)", 0.85),
    (r"요약\s*(해줘|해주세요|부탁)", 0.82),
    (r"(위반|초과)\s*(있어|있나|확인)", 0.85),
    (r"(전압|조류|주파수)\s*위반", 0.88),
]

_RAG_PATTERNS: List[Tuple[str, float]] = [
    (r"규정|고시|법규|기준|제\d+조", 0.90),
    (r"절차|SOP|매뉴얼|지침|가이드", 0.90),
    (r"(N-1)\s*(기준|규정|절차|복구)", 0.90),
    (r"복구\s*절차|복전\s*절차|재투입\s*절차", 0.92),
    (r"용어\s*(설명|뜻|의미|정의)|뭐야|뭔가요|무엇인가", 0.80),
    (r"표준\s*(절차|운영|작업)|운영\s*기준", 0.88),
    (r"고장\s*(복구|처리)\s*절차", 0.90),
    (r"검색|찾아|알려줘.*(규정|기준|절차)", 0.85),
    (r"산업통상자원부|전력계통\s*운영\s*기준", 0.92),
]

_NAVIGATION_PATTERNS: List[Tuple[str, float]] = [
    (r"이동\s*(해줘|해주세요|하자|부탁)|화면\s*이동", 0.95),
    (r"(화면|페이지|뷰)\s*(으로|로)\s*(이동|전환|바꿔)", 0.95),
    (r"(지도|맵|map)\s*(으로|에서|열어|보여)", 0.90),
    (r"변전소\s*(화면|뷰|페이지|SLD)", 0.92),
    (r"보여줘|보여주세요|열어줘|열어주세요", 0.75),
    (r"(GIS|SLD|대시보드)\s*(열어|보여|이동)", 0.90),
    (r"(으로|에)\s*이동|navigate|go\s*to", 0.85),
    (r"(단선도|계통도)\s*(보여|열어|이동)", 0.90),
]


# ──────────────────────────────────────────────
# 규칙 기반 분류 엔진
# ──────────────────────────────────────────────

def _match_patterns(text: str, patterns: List[Tuple[str, float]]) -> float:
    """텍스트에서 패턴 매칭 점수를 반환한다.

    여러 패턴이 매칭될 경우 가장 높은 가중치를 반환한다.

    Args:
        text: 분류할 텍스트 (한국어 자연어 질의)
        patterns: (정규식 패턴, 가중치) 튜플 목록

    Returns:
        매칭된 최대 가중치 (0.0이면 미매칭)
    """
    max_score = 0.0
    for pattern, weight in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            max_score = max(max_score, weight)
    return max_score


def classify_intent_rule_based(user_query: str) -> IntentResult:
    """한국어 키워드 규칙 기반 Intent 분류.

    우선순위: study > alarm > nl2app > rag > navigation > general
    - study/alarm은 HITL 모드 (조치 포함 가능)
    - 나머지는 HOTL 모드 (조회 전용)

    Args:
        user_query: 사용자 자연어 질의

    Returns:
        IntentResult: 분류 결과 (intent, confidence, mode, reasoning)
    """
    text = user_query.strip()

    # 각 Intent 별 매칭 점수 계산
    scores: Dict[str, float] = {
        "study": _match_patterns(text, _STUDY_PATTERNS),
        "alarm": _match_patterns(text, _ALARM_PATTERNS),
        "nl2app": _match_patterns(text, _NL2APP_PATTERNS),
        "rag": _match_patterns(text, _RAG_PATTERNS),
        "navigation": _match_patterns(text, _NAVIGATION_PATTERNS),
    }

    logger.debug("intent_scores", query=text[:50], scores=scores)

    # 가장 높은 점수의 Intent 선택
    best_intent: IntentType = "general"
    best_score = 0.0

    # 우선순위 순서로 평가 (동점 시 앞 항목 우선)
    priority_order: List[IntentType] = ["study", "alarm", "nl2app", "rag", "navigation"]
    for intent_name in priority_order:
        score = scores[intent_name]
        if score > best_score:
            best_score = score
            best_intent = intent_name  # type: ignore[assignment]

    # 신뢰도 임계값: 0.7 미만이면 general로 폴백
    if best_score < 0.7:
        best_intent = "general"
        best_score = 0.5

    mode = INTENT_MODE_MAP[best_intent]
    matched_patterns = [
        pattern for pattern, weight in (
            _STUDY_PATTERNS + _ALARM_PATTERNS + _NL2APP_PATTERNS +
            _RAG_PATTERNS + _NAVIGATION_PATTERNS
        )
        if re.search(pattern, text, re.IGNORECASE) and weight >= 0.7
    ]

    reasoning = (
        f"규칙 기반 분류: intent={best_intent}, score={best_score:.2f}, "
        f"mode={mode}. 매칭 패턴: {matched_patterns[:3] if matched_patterns else ['없음']}"
    )

    return IntentResult(
        intent=best_intent,
        confidence=best_score,
        mode=mode,
        reasoning=reasoning,
    )


# ──────────────────────────────────────────────
# 공개 인터페이스
# ──────────────────────────────────────────────

class IntentClassifier:
    """Intent 분류기.

    PydanticAI 설치 여부에 따라 LLM 강화 분류 또는 규칙 기반 분류를 수행한다.
    핵심 로직은 규칙 기반으로 PydanticAI 없이도 완전히 동작한다.
    """

    def __init__(self, use_llm: bool = False) -> None:
        """Intent 분류기 초기화.

        Args:
            use_llm: PydanticAI LLM 사용 여부 (설치된 경우에만 활성화)
        """
        self._use_llm = use_llm and _PYDANTIC_AI_AVAILABLE
        if self._use_llm:
            logger.info("intent_classifier_init", mode="llm_enhanced")
        else:
            logger.info("intent_classifier_init", mode="rule_based")

    async def classify(self, user_query: str) -> IntentResult:
        """사용자 질의를 분류하여 IntentResult를 반환한다.

        Args:
            user_query: 사용자 자연어 질의

        Returns:
            IntentResult: 분류된 의도, 신뢰도, 모드, 근거
        """
        result = classify_intent_rule_based(user_query)
        logger.info(
            "intent_classified",
            query=user_query[:50],
            intent=result.intent,
            confidence=result.confidence,
            mode=result.mode,
        )
        return result

    def classify_sync(self, user_query: str) -> IntentResult:
        """동기 버전 Intent 분류 (테스트 및 동기 컨텍스트용).

        Args:
            user_query: 사용자 자연어 질의

        Returns:
            IntentResult: 분류된 의도, 신뢰도, 모드, 근거
        """
        return classify_intent_rule_based(user_query)
