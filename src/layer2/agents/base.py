"""에이전트 기본 클래스 — AI-EMS v5.1 Layer 2.

모든 하위 에이전트가 상속하는 BaseAgent.
HITL/HOTL 분류, Evidence chain, snapshot_ts 규칙을 강제한다.

설계 원칙:
  3. HITL/HOTL 이원 분류 — 조회→HOTL 자동, 조치→HITL 운영자 승인
  4. Evidence chain 필수 — AI 응답에 Tool 호출 근거 항상 포함
  5. snapshot_ts 필수 — 모든 응답에 분석 기준 시각 포함
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Literal, Optional

from src.shared.schemas.agent import AgentContext, AIResponse, EvidenceStep, StructuredFact


def _utcnow() -> datetime:
    """UTC 현재 시각 반환."""
    return datetime.now(timezone.utc)


class BaseAgent(ABC):
    """모든 에이전트의 기본 클래스.

    하위 클래스는 name, description, mode를 클래스 변수로 정의하고,
    run() 추상 메서드를 구현해야 한다.

    Attributes:
        name: 에이전트 식별자 (예: 'nl2app', 'rag', 'alarm', 'study', 'navigation').
        description: 에이전트 역할 설명 (한국어).
        mode: 'HITL' (운영자 승인 필수) 또는 'HOTL' (자동 실행).
    """

    name: str = "base"
    description: str = "기본 에이전트"
    mode: Literal["HITL", "HOTL"] = "HOTL"

    @abstractmethod
    async def run(self, context: AgentContext) -> AIResponse:
        """에이전트 실행 — 반드시 evidence_chain 포함.

        Args:
            context: 에이전트 컨텍스트 (세션, 질의, 네임스페이스, 모드).

        Returns:
            AIResponse 스키마. evidence_chain 최소 1개 이상 필수.
        """

    def _build_response(
        self,
        answer: str,
        facts: List[StructuredFact],
        evidence: List[EvidenceStep],
        confidence: float,
        warnings: Optional[List[str]] = None,
        suggestions: Optional[List[str]] = None,
    ) -> AIResponse:
        """표준 AIResponse 빌더.

        Args:
            answer: AI 자연어 응답 텍스트 (한국어).
            facts: 근거 구조화 사실 목록 (pandapower/Redis 조회값만).
            evidence: Evidence chain (최소 1개 이상 필수).
            confidence: 응답 신뢰도 (0.0~1.0).
            warnings: 경고 메시지 목록 (선택).
            suggestions: 권장 조치 목록 (선택, HITL이면 '운영자 승인 필요' 표시).

        Returns:
            AIResponse 스키마 인스턴스.

        Raises:
            ValueError: evidence가 비어있으면 설계 원칙 4 위반.
        """
        if not evidence:
            raise ValueError(
                f"[{self.name}] Evidence chain은 최소 1개 이상 필수 (설계 원칙 4). "
                "Tool 호출 없이 응답을 생성할 수 없습니다."
            )

        return AIResponse(
            answer=answer,
            facts=facts,
            evidence_chain=evidence,
            confidence=max(0.0, min(1.0, confidence)),
            snapshot_ts=_utcnow(),
            warnings=warnings or [],
            suggestions=suggestions or [],
        )

    def _make_evidence(
        self,
        tool_name: str,
        input_params: dict,
        output_summary: str,
        duration_ms: float = 0.0,
    ) -> EvidenceStep:
        """단일 EvidenceStep 생성 헬퍼.

        Args:
            tool_name: 호출한 Tool 또는 엔드포인트 이름.
            input_params: Tool 호출 입력 파라미터.
            output_summary: Tool 호출 결과 요약.
            duration_ms: Tool 호출 소요 시간 (ms).

        Returns:
            EvidenceStep 스키마 인스턴스.
        """
        return EvidenceStep(
            tool_name=tool_name,
            input_params=input_params,
            output_summary=output_summary,
            duration_ms=duration_ms,
        )

    def _make_fact(
        self,
        key: str,
        value: object,
        source: str,
        unit: Optional[str] = None,
    ) -> StructuredFact:
        """단일 StructuredFact 생성 헬퍼.

        Args:
            key: 사실 항목 식별자.
            value: 사실 항목 값 (pandapower 솔버 반환값만).
            source: 데이터 출처 경로.
            unit: 측정 단위 (선택).

        Returns:
            StructuredFact 스키마 인스턴스.
        """
        return StructuredFact(
            key=key,
            value=value,
            unit=unit,
            source=source,
        )
