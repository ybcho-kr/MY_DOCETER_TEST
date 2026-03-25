"""
AI 에이전트 스키마 모듈 — AI-EMS v5.1 Phase 1
에이전트 컨텍스트, Evidence chain, AI 응답 스키마.

설계 원칙:
  4. Evidence chain 필수 — AI 응답에 Tool 호출 근거 항상 포함
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동, 조치→HITL 운영자 승인
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StructuredFact(BaseModel):
    """구조화된 사실 데이터 단위.

    AI 응답에서 인용하는 개별 계측/계산 사실.
    source는 Tool 호출 경로를 명시하여 출처 추적을 지원한다.
    """

    key: str = Field(
        description="사실 항목 식별자 (예: 'bus_voltage', 'line_loading', 'frequency_hz').",
    )
    value: Any = Field(
        description="사실 항목 값. pandapower 솔버 반환값 또는 Redis 조회값만 사용.",
    )
    unit: Optional[str] = Field(
        default=None,
        description="측정 단위 (예: 'pu', 'MW', 'Mvar', 'Hz', '%'). 무차원이면 None.",
    )
    source: str = Field(
        description=(
            "데이터 출처 경로 (예: 'mcp://grid/bus_voltage?bus_id=1', "
            "'redis:ops:state:bus:1', 'pandapower:runpp')."
        ),
    )


class EvidenceStep(BaseModel):
    """Evidence chain 단일 단계.

    AI 응답 생성을 위해 호출한 Tool 또는 MCP 엔드포인트의 호출 기록.
    Evidence chain 은 AI 응답의 신뢰성을 보장하며 감사 로그로 활용된다.
    """

    tool_name: str = Field(
        description="호출한 Tool 또는 MCP 엔드포인트 이름 (예: 'read_bus_voltage', 'run_powerflow').",
    )
    input_params: Dict[str, Any] = Field(
        description="Tool 호출 입력 파라미터 (직렬화 가능한 dict).",
    )
    output_summary: str = Field(
        description="Tool 호출 결과 요약 (AI가 참조한 핵심 수치/상태 포함).",
    )
    duration_ms: float = Field(
        ge=0,
        description="Tool 호출 소요 시간 (밀리초). 성능 모니터링에 사용.",
    )


class AgentContext(BaseModel):
    """AI 에이전트 요청 컨텍스트.

    세션, 사용자 질의, 네임스페이스, HITL/HOTL 모드를 포함.
    namespace='ops': AI는 read_only. namespace='study': AI write 가능.
    """

    session_id: str = Field(
        description="세션 고유 식별자 (UUID). 다중 회전 대화 추적에 사용.",
    )
    user_query: str = Field(
        description="사용자 자연어 질의 원문.",
    )
    namespace: Literal["ops", "study"] = Field(
        description=(
            "운영 네임스페이스. "
            "ops: AI read_only (조회만), study: AI write 가능 (해석 스터디). "
            "설계 원칙 2: ops/study 네임스페이스 격리."
        ),
    )
    mode: Literal["HITL", "HOTL"] = Field(
        description=(
            "HITL/HOTL 분류. "
            "HOTL: 조회 자동 실행 (Human On The Loop), "
            "HITL: 조치 전 운영자 승인 필수 (Human In The Loop). "
            "설계 원칙 3."
        ),
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="에이전트 컨텍스트 기준 시각 (UTC).",
    )


class AIResponse(BaseModel):
    """AI 에이전트 응답 스키마.

    evidence_chain: 최소 1개 이상 필수 (설계 원칙 4: Evidence chain 필수).
    facts: AI가 응답에서 인용한 구조화 사실 목록.
    snapshot_ts: 분석 기준 시각 (설계 원칙 5).
    LLM 수치 생성 절대 금지 — facts의 모든 value는 Tool 호출 결과여야 함.
    """

    answer: str = Field(
        description="AI 자연어 응답 텍스트 (운영자 가독성 중심).",
    )
    facts: List[StructuredFact] = Field(
        default_factory=list,
        description="응답 근거 구조화 사실 목록. pandapower/Redis 조회 수치만 포함.",
    )
    evidence_chain: List[EvidenceStep] = Field(
        min_length=1,
        description=(
            "Tool 호출 Evidence chain. 최소 1개 이상 필수. "
            "설계 원칙 4: AI 응답에 Tool 호출 근거 항상 포함."
        ),
    )
    confidence: float = Field(
        ge=0,
        le=1.0,
        description="AI 응답 신뢰도 (0.0~1.0). evidence_chain 품질 기반.",
    )
    snapshot_ts: datetime = Field(
        default_factory=_utcnow,
        description="AI 응답 분석 기준 시각 (UTC). 설계 원칙 5.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="응답 관련 경고 메시지 목록 (예: '데이터 지연 15분 초과', 'N-1 위반 감지').",
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="운영자 권장 조치 제안 목록 (HITL 승인 필요 조치는 별도 표시).",
    )
