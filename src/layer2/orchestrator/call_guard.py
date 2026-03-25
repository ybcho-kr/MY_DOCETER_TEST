"""CallGuard — 에이전트 호출 깊이/빈도 제한기 — AI-EMS v5.1 Layer 2.

에이전트 무한 루프, 자기 호출 폭주, 동일 에이전트 연속 호출을 방지한다.

설계 원칙:
  CallGuard: depth ≤ 5, 동일 에이전트 연속 2회 제한 (CLAUDE.md)
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class CallGuardState(BaseModel):
    """CallGuard 내부 상태 스냅샷 (디버깅/모니터링용).

    depth: 현재 호출 깊이
    call_history: 최근 호출 이력 (에이전트 이름 목록)
    agent_consecutive_count: 에이전트별 연속 호출 횟수
    """

    depth: int = Field(ge=0, description="현재 호출 깊이")
    call_history: list[str] = Field(description="최근 호출 이력")
    agent_consecutive_count: Dict[str, int] = Field(description="에이전트별 연속 호출 횟수")
    last_agent: Optional[str] = Field(default=None, description="직전 호출 에이전트")


class CallGuardError(Exception):
    """CallGuard 호출 차단 예외.

    이 예외가 발생하면 해당 에이전트 호출이 차단되었음을 의미한다.
    Dispatcher는 이 예외를 잡아 적절한 오류 응답을 반환해야 한다.
    """

    def __init__(self, reason: str, agent_name: str) -> None:
        """CallGuardError 초기화.

        Args:
            reason: 차단 사유 설명
            agent_name: 차단된 에이전트 이름
        """
        self.reason = reason
        self.agent_name = agent_name
        super().__init__(f"[CallGuard] {agent_name} 차단: {reason}")


class CallGuard:
    """에이전트 호출 깊이 및 빈도 제한기.

    다음 두 가지 제한을 적용한다:
    1. 최대 호출 깊이(max_depth=5): depth 초과 시 차단
    2. 동일 에이전트 연속 호출(max_consecutive_same=2): 초과 시 차단

    세션당 하나의 CallGuard 인스턴스를 생성하고, reset()으로 초기화한다.
    """

    MAX_HISTORY_SIZE: int = 20  # 이력 보관 최대 건수

    def __init__(
        self,
        max_depth: int = 5,
        max_consecutive_same: int = 2,
    ) -> None:
        """CallGuard 초기화.

        Args:
            max_depth: 최대 허용 호출 깊이 (기본 5)
            max_consecutive_same: 동일 에이전트 최대 연속 허용 횟수 (기본 2)
        """
        self.max_depth = max_depth
        self.max_consecutive_same = max_consecutive_same

        # 내부 상태
        self._depth: int = 0
        self._call_history: Deque[str] = deque(maxlen=self.MAX_HISTORY_SIZE)
        self._last_agent: Optional[str] = None
        self._consecutive_count: int = 0  # 현재 연속 호출 횟수

        logger.debug(
            "call_guard_init",
            max_depth=max_depth,
            max_consecutive_same=max_consecutive_same,
        )

    def check(self, agent_name: str) -> bool:
        """에이전트 호출 가능 여부를 확인한다.

        CallGuardError를 발생시키지 않고 bool을 반환한다.
        사전 확인용 메서드. 실제 호출 전 check() 후 record() 순서로 사용.

        Args:
            agent_name: 호출 대상 에이전트 이름

        Returns:
            True: 호출 가능
            False: 차단 대상 (depth 초과 또는 연속 횟수 초과)
        """
        # 깊이 초과 확인
        if self._depth >= self.max_depth:
            logger.warning(
                "call_guard_depth_exceeded",
                agent_name=agent_name,
                current_depth=self._depth,
                max_depth=self.max_depth,
            )
            return False

        # 동일 에이전트 연속 호출 초과 확인
        if self._last_agent == agent_name:
            next_consecutive = self._consecutive_count + 1
            if next_consecutive > self.max_consecutive_same:
                logger.warning(
                    "call_guard_consecutive_exceeded",
                    agent_name=agent_name,
                    consecutive=next_consecutive,
                    max_consecutive_same=self.max_consecutive_same,
                )
                return False

        return True

    def record(self, agent_name: str) -> None:
        """에이전트 호출을 기록하고 깊이를 증가시킨다.

        check() 통과 후 실제 에이전트 호출 직전에 호출해야 한다.

        Args:
            agent_name: 호출한 에이전트 이름

        Raises:
            CallGuardError: 호출 제한 초과 시
        """
        # 재확인 (thread-safety 보강)
        if self._depth >= self.max_depth:
            raise CallGuardError(
                reason=f"호출 깊이 초과 (현재 {self._depth}/{self.max_depth})",
                agent_name=agent_name,
            )

        if self._last_agent == agent_name:
            next_consecutive = self._consecutive_count + 1
            if next_consecutive > self.max_consecutive_same:
                raise CallGuardError(
                    reason=(
                        f"동일 에이전트 연속 호출 초과 "
                        f"(현재 {next_consecutive}/{self.max_consecutive_same})"
                    ),
                    agent_name=agent_name,
                )
            self._consecutive_count = next_consecutive
        else:
            # 다른 에이전트 → 연속 카운트 초기화
            self._consecutive_count = 1
            self._last_agent = agent_name

        self._depth += 1
        self._call_history.append(agent_name)

        logger.debug(
            "call_guard_recorded",
            agent_name=agent_name,
            depth=self._depth,
            consecutive=self._consecutive_count,
        )

    def release(self) -> None:
        """에이전트 호출 완료 후 깊이를 감소시킨다.

        record()와 쌍으로 사용. try/finally 블록으로 보장해야 한다.
        """
        if self._depth > 0:
            self._depth -= 1

    def reset(self) -> None:
        """세션 초기화 — 모든 호출 기록을 리셋한다.

        새 사용자 질의 처리 시작 전 호출해야 한다.
        """
        self._depth = 0
        self._call_history.clear()
        self._last_agent = None
        self._consecutive_count = 0
        logger.debug("call_guard_reset")

    @property
    def current_depth(self) -> int:
        """현재 호출 깊이를 반환한다."""
        return self._depth

    @property
    def state(self) -> CallGuardState:
        """현재 CallGuard 상태 스냅샷을 반환한다 (디버깅/로깅용)."""
        return CallGuardState(
            depth=self._depth,
            call_history=list(self._call_history),
            agent_consecutive_count={
                self._last_agent: self._consecutive_count
            } if self._last_agent else {},
            last_agent=self._last_agent,
        )
