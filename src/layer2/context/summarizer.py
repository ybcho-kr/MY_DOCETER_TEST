"""SessionSummarizer — 세션 대화 히스토리 요약.

핵심 규칙:
  structured_facts는 절대 요약/압축하지 않는다.
  히스토리 요약은 대화 흐름 파악용이며 수치 데이터는 항상 facts를 참조한다.
"""
from __future__ import annotations

import structlog

from src.layer2.context.session import SessionState

logger = structlog.get_logger(__name__)

# 요약 기본 최대 길이 (문자 수)
_DEFAULT_MAX_LENGTH: int = 500


class SessionSummarizer:
    """세션 대화 요약기.

    structured_facts는 절대 압축/요약하지 않는다.
    대화 흐름(turn_count, 모드, 네임스페이스, 초기 질의)만 요약한다.
    """

    def summarize(self, context: "SessionState", max_length: int = _DEFAULT_MAX_LENGTH) -> str:
        """세션 히스토리를 요약한다.

        structured_facts와 evidence_chain의 수치 데이터는 포함하지 않는다.
        대화 흐름 파악을 위한 메타 정보만 기술한다.

        Args:
            context: 요약할 SessionState 인스턴스.
            max_length: 요약 최대 문자 수. 초과 시 잘라낸다.

        Returns:
            요약 문자열 (facts 수치 미포함).
        """
        agent_ctx = context.context

        # evidence_chain의 tool 이름만 나열 (수치 데이터 제외)
        tool_sequence: list[str] = [e.tool_name for e in context.evidence_chain]
        tool_summary = ", ".join(tool_sequence) if tool_sequence else "없음"

        summary = (
            f"[세션 요약] "
            f"세션 ID: {agent_ctx.session_id[:8]}... | "
            f"모드: {agent_ctx.mode} | "
            f"네임스페이스: {agent_ctx.namespace} | "
            f"대화 회전: {context.turn_count}회 | "
            f"초기 질의: '{agent_ctx.user_query[:50]}{'...' if len(agent_ctx.user_query) > 50 else ''}' | "
            f"호출 Tool 순서: [{tool_summary}] | "
            f"facts 건수: {len(context.structured_facts)}건 (수치 생략) | "
            f"기준 시각: {agent_ctx.snapshot_ts.isoformat()}"
        )

        if len(summary) > max_length:
            summary = summary[:max_length - 3] + "..."

        logger.debug(
            "session_summarized",
            session_id=agent_ctx.session_id,
            summary_length=len(summary),
            facts_excluded=True,
        )
        return summary
