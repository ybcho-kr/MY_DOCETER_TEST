"""HITL 승인 모듈 — Priority Queue 기반 운영자 승인 처리.

설계 원칙:
  3. HITL/HOTL 이원 분류 — 조치→HITL 운영자 승인 필수
  4. Evidence chain 필수 — 조치 요약 및 근거 포함

Priority별 타임아웃:
  - CRITICAL (4): 600초
  - HIGH (3): 300초
  - MEDIUM (2): 180초
  - LOW (1): 120초
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import IntEnum
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# 우선순위별 타임아웃 (초)
_TIMEOUT_MAP: dict[int, int] = {
    4: 600,  # CRITICAL
    3: 300,  # HIGH
    2: 180,  # MEDIUM
    1: 120,  # LOW
}


def _utcnow() -> datetime:
    """현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


class Priority(IntEnum):
    """HITL 승인 요청 우선순위.

    값이 클수록 높은 우선순위. 타임아웃은 우선순위에 반비례한다.
    """

    CRITICAL = 4  # 타임아웃 600s — 계통 안정성 직결 조치
    HIGH = 3       # 타임아웃 300s — 주요 설비 조작
    MEDIUM = 2     # 타임아웃 180s — 일반 조정 조치
    LOW = 1        # 타임아웃 120s — 참고용 확인 요청


class ApprovalRequest(BaseModel):
    """HITL 승인 요청 스키마.

    운영자에게 표시되는 조치 요청의 전체 정보를 담는다.
    created_at + timeout_sec 으로 만료 시각을 계산한다.
    """

    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="승인 요청 고유 식별자 (UUID).",
    )
    agent_name: str = Field(
        description="요청을 생성한 에이전트 이름 (예: 'alarm_analysis', 'study').",
    )
    action_summary: str = Field(
        description="운영자에게 표시할 조치 요약 (한국어, 1~3문장).",
    )
    priority: Priority = Field(
        description="요청 우선순위. 큐 정렬 및 타임아웃 결정에 사용.",
    )
    equipment_id: Optional[str] = Field(
        default=None,
        description="조치 대상 설비 ID (예: 'line_001', 'bus_003'). 중복 제거 키.",
    )
    details: dict = Field(
        default_factory=dict,
        description="추가 상세 정보 (Evidence chain, 파라미터 등).",
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        description="요청 생성 시각 (UTC).",
    )
    timeout_sec: int = Field(
        description="타임아웃 (초). Priority에 따라 자동 할당.",
    )
    status: Literal["pending", "approved", "rejected", "timeout"] = Field(
        default="pending",
        description="승인 요청 상태.",
    )

    @classmethod
    def create(
        cls,
        agent_name: str,
        action_summary: str,
        priority: Priority,
        equipment_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> "ApprovalRequest":
        """Priority에 맞는 timeout_sec을 자동으로 설정해 인스턴스를 생성한다."""
        return cls(
            agent_name=agent_name,
            action_summary=action_summary,
            priority=priority,
            equipment_id=equipment_id,
            details=details or {},
            timeout_sec=_TIMEOUT_MAP[int(priority)],
        )


class ApprovalResponse(BaseModel):
    """운영자 승인/거부 응답 스키마.

    HITLQueue.approve() 또는 HITLQueue.reject() 호출 시 반환된다.
    """

    request_id: str = Field(
        description="원본 승인 요청 ID.",
    )
    decision: Literal["approved", "rejected"] = Field(
        description="운영자 결정.",
    )
    operator_id: str = Field(
        default="operator_default",
        description="결정한 운영자 ID.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="거부/승인 사유 (선택).",
    )
    decided_at: datetime = Field(
        default_factory=_utcnow,
        description="결정 시각 (UTC).",
    )


class HITLQueue:
    """HITL 승인 요청 Priority Queue.

    동시 표시 최대 3건, 동일 설비 중복 제거, 연속 타임아웃 경고 지원.

    사용 예:
        queue = HITLQueue()
        req = ApprovalRequest.create(...)
        queue.submit(req)
        pending = queue.get_pending()
        resp = queue.approve(req.request_id)
    """

    MAX_DISPLAY: int = 3          # 동시 표시 최대 건수
    CONSECUTIVE_TIMEOUT_WARN: int = 3  # 연속 타임아웃 → 운영자 부재 경고

    def __init__(self) -> None:
        """HITLQueue 초기화."""
        self._queue: list[ApprovalRequest] = []    # 대기 중인 요청
        self._history: list[ApprovalRequest] = []  # 처리 완료된 요청
        self._consecutive_timeouts: int = 0        # 연속 타임아웃 카운터

    def submit(self, request: ApprovalRequest) -> ApprovalRequest:
        """승인 요청을 큐에 제출한다.

        동일 equipment_id가 이미 pending 상태면 기존 건을 제거하고
        최신 건만 유지한다. equipment_id가 None이면 중복 검사를 생략한다.
        """
        if request.equipment_id is not None:
            # 동일 설비의 기존 pending 요청 제거 (최신 건만 유지)
            before = len(self._queue)
            self._queue = [
                r for r in self._queue
                if not (
                    r.equipment_id == request.equipment_id
                    and r.status == "pending"
                )
            ]
            removed = before - len(self._queue)
            if removed > 0:
                logger.info(
                    "hitl_duplicate_removed",
                    equipment_id=request.equipment_id,
                    removed_count=removed,
                )

        self._queue.append(request)
        logger.info(
            "hitl_request_submitted",
            request_id=request.request_id,
            agent=request.agent_name,
            priority=request.priority.name,
            equipment_id=request.equipment_id,
        )
        return request

    def get_pending(self, limit: int = MAX_DISPLAY) -> list[ApprovalRequest]:
        """대기 중인 요청을 우선순위 내림차순으로 반환한다.

        타임아웃 체크를 먼저 수행하여 만료 건을 제거한 뒤 정렬한다.
        최대 limit건만 반환한다 (기본값 MAX_DISPLAY=3).
        """
        self.check_timeouts()
        pending = [r for r in self._queue if r.status == "pending"]
        # 우선순위 내림차순 → 동일 우선순위는 생성 시각 오름차순 (FIFO)
        pending.sort(key=lambda r: (-int(r.priority), r.created_at))
        return pending[:limit]

    def approve(
        self,
        request_id: str,
        operator_id: str = "operator_default",
        reason: Optional[str] = None,
    ) -> ApprovalResponse:
        """지정 요청을 승인 처리한다.

        Args:
            request_id: 승인할 요청 ID.
            operator_id: 승인한 운영자 ID.
            reason: 승인 사유 (선택).

        Returns:
            ApprovalResponse 인스턴스.

        Raises:
            KeyError: request_id가 큐에 없거나 pending 상태가 아닐 때.
        """
        request = self._find_pending(request_id)
        request.status = "approved"
        self._consecutive_timeouts = 0  # 승인 성공 시 타임아웃 카운터 리셋
        self._move_to_history(request)

        response = ApprovalResponse(
            request_id=request_id,
            decision="approved",
            operator_id=operator_id,
            reason=reason,
        )
        logger.info(
            "hitl_approved",
            request_id=request_id,
            operator_id=operator_id,
        )
        return response

    def reject(
        self,
        request_id: str,
        operator_id: str = "operator_default",
        reason: Optional[str] = None,
    ) -> ApprovalResponse:
        """지정 요청을 거부 처리한다.

        Args:
            request_id: 거부할 요청 ID.
            operator_id: 거부한 운영자 ID.
            reason: 거부 사유 (선택).

        Returns:
            ApprovalResponse 인스턴스.

        Raises:
            KeyError: request_id가 큐에 없거나 pending 상태가 아닐 때.
        """
        request = self._find_pending(request_id)
        request.status = "rejected"
        self._consecutive_timeouts = 0  # 거부 성공 시 타임아웃 카운터 리셋
        self._move_to_history(request)

        response = ApprovalResponse(
            request_id=request_id,
            decision="rejected",
            operator_id=operator_id,
            reason=reason,
        )
        logger.info(
            "hitl_rejected",
            request_id=request_id,
            operator_id=operator_id,
            reason=reason,
        )
        return response

    def check_timeouts(self) -> list[ApprovalRequest]:
        """현재 시각 기준 만료된 pending 요청을 처리한다.

        만료된 요청의 status를 'timeout'으로 변경하고 히스토리로 이동한다.
        연속 타임아웃이 CONSECUTIVE_TIMEOUT_WARN 이상이면 경고를 기록한다.

        Returns:
            이번에 타임아웃 처리된 요청 목록.
        """
        now = _utcnow()
        timed_out: list[ApprovalRequest] = []

        for request in list(self._queue):
            if request.status != "pending":
                continue
            elapsed = (now - request.created_at).total_seconds()
            if elapsed >= request.timeout_sec:
                request.status = "timeout"
                timed_out.append(request)

        for request in timed_out:
            self._consecutive_timeouts += 1
            self._move_to_history(request)
            logger.warning(
                "hitl_timeout",
                request_id=request.request_id,
                equipment_id=request.equipment_id,
                consecutive_timeouts=self._consecutive_timeouts,
            )

        if self._consecutive_timeouts >= self.CONSECUTIVE_TIMEOUT_WARN:
            logger.error(
                "hitl_operator_absent_warning",
                consecutive_timeouts=self._consecutive_timeouts,
                message="연속 타임아웃 감지 — 운영자 부재 가능성",
            )

        return timed_out

    @property
    def operator_absent_warning(self) -> bool:
        """연속 타임아웃이 CONSECUTIVE_TIMEOUT_WARN 이상이면 True를 반환한다."""
        return self._consecutive_timeouts >= self.CONSECUTIVE_TIMEOUT_WARN

    # ──────────────────────────────────────────────
    # 내부 헬퍼 메서드
    # ──────────────────────────────────────────────

    def _find_pending(self, request_id: str) -> ApprovalRequest:
        """큐에서 pending 상태의 요청을 찾아 반환한다.

        Raises:
            KeyError: 해당 request_id가 없거나 pending 상태가 아닐 때.
        """
        for request in self._queue:
            if request.request_id == request_id and request.status == "pending":
                return request
        raise KeyError(
            f"pending 상태의 승인 요청을 찾을 수 없음: request_id={request_id}"
        )

    def _move_to_history(self, request: ApprovalRequest) -> None:
        """큐에서 제거하고 히스토리에 추가한다."""
        self._queue = [r for r in self._queue if r.request_id != request.request_id]
        self._history.append(request)
