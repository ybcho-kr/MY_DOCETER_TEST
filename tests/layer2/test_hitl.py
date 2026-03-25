"""HITL 승인 모듈 단위 테스트.

검증 항목:
  - ApprovalRequest 생성 및 Pydantic 검증
  - HITLQueue: submit → get_pending (우선순위 정렬)
  - HITLQueue: 동일 설비 중복 제거 (최신 건만)
  - HITLQueue: approve/reject 처리
  - HITLQueue: 타임아웃 처리 (datetime mock)
  - HITLQueue: 연속 3건 타임아웃 → operator_absent_warning
  - HITLQueue: MAX_DISPLAY=3 제한
  - Priority별 타임아웃 값 확인
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.layer2.hitl.approval import (
    ApprovalRequest,
    HITLQueue,
    Priority,
    _TIMEOUT_MAP,
)


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_request(
    priority: Priority = Priority.MEDIUM,
    equipment_id: str | None = "line_001",
    agent_name: str = "alarm_analysis",
) -> ApprovalRequest:
    """테스트용 ApprovalRequest를 생성한다."""
    return ApprovalRequest.create(
        agent_name=agent_name,
        action_summary="선로 부하율 95% 초과 — 부하 전환 검토 필요",
        priority=priority,
        equipment_id=equipment_id,
    )


# ──────────────────────────────────────────────
# Priority별 타임아웃 값 확인
# ──────────────────────────────────────────────

class TestPriorityTimeouts:
    """Priority별 타임아웃 값 및 ApprovalRequest.create() 검증."""

    def test_critical_timeout(self) -> None:
        """CRITICAL 우선순위 타임아웃은 600초여야 한다."""
        assert _TIMEOUT_MAP[Priority.CRITICAL] == 600

    def test_high_timeout(self) -> None:
        """HIGH 우선순위 타임아웃은 300초여야 한다."""
        assert _TIMEOUT_MAP[Priority.HIGH] == 300

    def test_medium_timeout(self) -> None:
        """MEDIUM 우선순위 타임아웃은 180초여야 한다."""
        assert _TIMEOUT_MAP[Priority.MEDIUM] == 180

    def test_low_timeout(self) -> None:
        """LOW 우선순위 타임아웃은 120초여야 한다."""
        assert _TIMEOUT_MAP[Priority.LOW] == 120

    def test_create_sets_correct_timeout(self) -> None:
        """ApprovalRequest.create()가 Priority에 맞는 timeout_sec를 설정한다."""
        req = ApprovalRequest.create(
            agent_name="test_agent",
            action_summary="테스트 조치",
            priority=Priority.HIGH,
        )
        assert req.timeout_sec == 300
        assert req.priority == Priority.HIGH
        assert req.status == "pending"

    def test_priority_ordering(self) -> None:
        """CRITICAL > HIGH > MEDIUM > LOW 정렬 순서 확인."""
        assert Priority.CRITICAL > Priority.HIGH
        assert Priority.HIGH > Priority.MEDIUM
        assert Priority.MEDIUM > Priority.LOW


# ──────────────────────────────────────────────
# ApprovalRequest Pydantic 검증
# ──────────────────────────────────────────────

class TestApprovalRequest:
    """ApprovalRequest Pydantic v2 스키마 검증."""

    def test_create_factory_method(self) -> None:
        """create() 클래스 메서드가 올바른 ApprovalRequest를 생성한다."""
        req = ApprovalRequest.create(
            agent_name="study",
            action_summary="5번 CB 개방 시뮬레이션 결과 조치 필요",
            priority=Priority.CRITICAL,
            equipment_id="cb_005",
            details={"voltage_pu": 0.95},
        )
        assert req.agent_name == "study"
        assert req.priority == Priority.CRITICAL
        assert req.timeout_sec == 600
        assert req.equipment_id == "cb_005"
        assert req.status == "pending"
        assert req.details["voltage_pu"] == 0.95

    def test_default_status_is_pending(self) -> None:
        """생성 시 기본 status는 'pending'이어야 한다."""
        req = _make_request()
        assert req.status == "pending"

    def test_request_id_is_uuid(self) -> None:
        """request_id는 UUID 형식이어야 한다."""
        req = _make_request()
        import uuid
        uuid.UUID(req.request_id)  # 유효하지 않으면 ValueError 발생

    def test_created_at_is_utc(self) -> None:
        """created_at은 UTC timezone을 포함해야 한다."""
        req = _make_request()
        assert req.created_at.tzinfo is not None

    def test_optional_equipment_id(self) -> None:
        """equipment_id는 None이어도 유효하다."""
        req = ApprovalRequest.create(
            agent_name="test",
            action_summary="장비 없는 조치",
            priority=Priority.LOW,
            equipment_id=None,
        )
        assert req.equipment_id is None


# ──────────────────────────────────────────────
# HITLQueue 기본 동작
# ──────────────────────────────────────────────

class TestHITLQueueBasic:
    """HITLQueue 기본 제출/조회 동작 검증."""

    def test_submit_and_get_pending(self) -> None:
        """제출한 요청이 get_pending()에서 반환되어야 한다."""
        queue = HITLQueue()
        req = _make_request()
        queue.submit(req)
        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0].request_id == req.request_id

    def test_get_pending_priority_sort(self) -> None:
        """get_pending()은 우선순위 내림차순으로 반환해야 한다."""
        queue = HITLQueue()
        low_req = _make_request(Priority.LOW, equipment_id="line_001")
        critical_req = _make_request(Priority.CRITICAL, equipment_id="line_002")
        medium_req = _make_request(Priority.MEDIUM, equipment_id="line_003")

        queue.submit(low_req)
        queue.submit(critical_req)
        queue.submit(medium_req)

        pending = queue.get_pending(limit=10)
        priorities = [r.priority for r in pending]
        assert priorities == sorted(priorities, reverse=True), \
            f"우선순위 정렬 실패: {priorities}"

    def test_max_display_limit(self) -> None:
        """get_pending()은 MAX_DISPLAY(3)건을 초과하지 않아야 한다."""
        queue = HITLQueue()
        for i in range(5):
            req = _make_request(Priority.MEDIUM, equipment_id=f"line_{i:03d}")
            queue.submit(req)

        pending = queue.get_pending()
        assert len(pending) <= HITLQueue.MAX_DISPLAY
        assert len(pending) == 3

    def test_get_pending_custom_limit(self) -> None:
        """get_pending(limit=2)는 최대 2건만 반환한다."""
        queue = HITLQueue()
        for i in range(4):
            req = _make_request(Priority.MEDIUM, equipment_id=f"bus_{i:03d}")
            queue.submit(req)
        pending = queue.get_pending(limit=2)
        assert len(pending) == 2


# ──────────────────────────────────────────────
# 중복 제거
# ──────────────────────────────────────────────

class TestHITLQueueDuplicates:
    """동일 설비 중복 제거 검증."""

    def test_duplicate_equipment_id_keeps_latest(self) -> None:
        """동일 equipment_id 재제출 시 기존 건이 제거되고 최신 건만 유지한다."""
        queue = HITLQueue()
        old_req = _make_request(Priority.LOW, equipment_id="line_001")
        queue.submit(old_req)

        new_req = _make_request(Priority.HIGH, equipment_id="line_001")
        queue.submit(new_req)

        pending = queue.get_pending(limit=10)
        request_ids = [r.request_id for r in pending]

        assert old_req.request_id not in request_ids, "기존 요청이 제거되어야 함"
        assert new_req.request_id in request_ids, "최신 요청이 유지되어야 함"
        assert len(pending) == 1

    def test_none_equipment_id_no_dedup(self) -> None:
        """equipment_id가 None이면 중복 제거를 하지 않는다."""
        queue = HITLQueue()
        req1 = _make_request(Priority.LOW, equipment_id=None)
        req2 = _make_request(Priority.LOW, equipment_id=None)
        queue.submit(req1)
        queue.submit(req2)

        pending = queue.get_pending(limit=10)
        assert len(pending) == 2

    def test_different_equipment_ids_no_dedup(self) -> None:
        """서로 다른 equipment_id는 중복 제거 대상이 아니다."""
        queue = HITLQueue()
        req1 = _make_request(Priority.LOW, equipment_id="line_001")
        req2 = _make_request(Priority.LOW, equipment_id="line_002")
        queue.submit(req1)
        queue.submit(req2)

        pending = queue.get_pending(limit=10)
        assert len(pending) == 2


# ──────────────────────────────────────────────
# approve / reject
# ──────────────────────────────────────────────

class TestHITLQueueDecisions:
    """승인/거부 처리 검증."""

    def test_approve(self) -> None:
        """approve() 호출 시 요청 status가 'approved'로 변경된다."""
        queue = HITLQueue()
        req = _make_request()
        queue.submit(req)

        resp = queue.approve(req.request_id, operator_id="op_001", reason="확인 완료")

        assert resp.decision == "approved"
        assert resp.request_id == req.request_id
        assert resp.operator_id == "op_001"
        assert resp.reason == "확인 완료"

        # 승인 후 pending에서 제거
        pending = queue.get_pending(limit=10)
        assert all(r.request_id != req.request_id for r in pending)

    def test_reject(self) -> None:
        """reject() 호출 시 요청 status가 'rejected'로 변경된다."""
        queue = HITLQueue()
        req = _make_request()
        queue.submit(req)

        resp = queue.reject(req.request_id, operator_id="op_002", reason="위험 판단")

        assert resp.decision == "rejected"
        assert resp.request_id == req.request_id
        assert resp.reason == "위험 판단"

        pending = queue.get_pending(limit=10)
        assert all(r.request_id != req.request_id for r in pending)

    def test_approve_not_found_raises(self) -> None:
        """존재하지 않는 request_id 승인 시 KeyError가 발생한다."""
        queue = HITLQueue()
        with pytest.raises(KeyError):
            queue.approve("nonexistent-id")

    def test_reject_not_found_raises(self) -> None:
        """존재하지 않는 request_id 거부 시 KeyError가 발생한다."""
        queue = HITLQueue()
        with pytest.raises(KeyError):
            queue.reject("nonexistent-id")

    def test_approve_resets_consecutive_timeouts(self) -> None:
        """승인 처리 시 연속 타임아웃 카운터가 리셋된다."""
        queue = HITLQueue()
        queue._consecutive_timeouts = 2

        req = _make_request()
        queue.submit(req)
        queue.approve(req.request_id)

        assert queue._consecutive_timeouts == 0


# ──────────────────────────────────────────────
# 타임아웃 처리
# ──────────────────────────────────────────────

class TestHITLQueueTimeout:
    """타임아웃 처리 및 운영자 부재 경고 검증."""

    def test_timeout_processing(self) -> None:
        """timeout_sec 초과 시 status가 'timeout'으로 변경되어 pending에서 제거된다."""
        queue = HITLQueue()
        # 타임아웃이 이미 지난 과거 시각으로 요청 생성
        past_time = _utcnow() - timedelta(seconds=200)

        req = ApprovalRequest(
            agent_name="test",
            action_summary="타임아웃 테스트",
            priority=Priority.LOW,
            equipment_id="line_001",
            timeout_sec=120,  # 120초 타임아웃
            created_at=past_time,  # 200초 전 생성 → 이미 만료
        )
        queue.submit(req)

        timed_out = queue.check_timeouts()

        assert len(timed_out) == 1
        assert timed_out[0].request_id == req.request_id
        assert timed_out[0].status == "timeout"

        # pending에서 제거 확인
        pending = queue.get_pending(limit=10)
        assert all(r.request_id != req.request_id for r in pending)

    def test_not_timed_out_stays_pending(self) -> None:
        """타임아웃이 아직 되지 않은 요청은 pending 상태를 유지한다."""
        queue = HITLQueue()
        req = _make_request()  # 방금 생성 → 아직 만료 아님
        queue.submit(req)

        timed_out = queue.check_timeouts()
        assert len(timed_out) == 0

        pending = queue.get_pending(limit=10)
        assert len(pending) == 1

    def test_consecutive_timeout_warn_threshold(self) -> None:
        """연속 3건 타임아웃 시 operator_absent_warning이 True가 된다."""
        queue = HITLQueue()

        for i in range(HITLQueue.CONSECUTIVE_TIMEOUT_WARN):
            past = _utcnow() - timedelta(seconds=200)
            req = ApprovalRequest(
                agent_name="test",
                action_summary=f"타임아웃 테스트 {i}",
                priority=Priority.LOW,
                equipment_id=f"line_{i:03d}",
                timeout_sec=120,
                created_at=past,
            )
            queue.submit(req)
            queue.check_timeouts()

        assert queue.operator_absent_warning is True
        assert queue._consecutive_timeouts >= HITLQueue.CONSECUTIVE_TIMEOUT_WARN

    def test_operator_absent_warning_false_initially(self) -> None:
        """초기 상태에서 operator_absent_warning은 False이어야 한다."""
        queue = HITLQueue()
        assert queue.operator_absent_warning is False

    def test_consecutive_timeouts_below_threshold(self) -> None:
        """연속 2건 타임아웃은 경고를 발생시키지 않는다."""
        queue = HITLQueue()

        for i in range(HITLQueue.CONSECUTIVE_TIMEOUT_WARN - 1):
            past = _utcnow() - timedelta(seconds=200)
            req = ApprovalRequest(
                agent_name="test",
                action_summary=f"타임아웃 테스트 {i}",
                priority=Priority.LOW,
                equipment_id=f"gen_{i:03d}",
                timeout_sec=120,
                created_at=past,
            )
            queue.submit(req)
            queue.check_timeouts()

        assert queue.operator_absent_warning is False
