"""AgentContext 관리 및 MCPGateway 단위 테스트.

검증 항목:
  - SessionManager: create_session → AgentContext 검증
  - SessionManager: snapshot_ts 포함
  - SessionManager: update_facts FIFO (21번째 → 1번째 제거)
  - SessionManager: add_evidence (최대 5단계 FIFO)
  - SessionManager: close_session
  - SessionSummarizer: summarize (facts 수치 미포함 확인)
  - MCPGateway: read tool 허용
  - MCPGateway: write tool 차단 (ops: namespace)
  - MCPGateway: study: namespace에서 write 허용 여부
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from src.layer2.context.session import SessionManager, SessionState
from src.layer2.context.summarizer import SessionSummarizer
from src.gateway.mcp_gateway import (
    MCPAccessDeniedError,
    MCPGateway,
    MCPToolNotFoundError,
)
from src.shared.schemas.agent import AgentContext, EvidenceStep, StructuredFact


# ──────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────

def _make_fact(key: str = "bus_voltage", value: float = 0.98) -> StructuredFact:
    """테스트용 StructuredFact를 생성한다."""
    return StructuredFact(
        key=key,
        value=value,
        unit="pu",
        source="redis:ops:state:bus:1",
    )


def _make_evidence(tool_name: str = "read_bus_voltage") -> EvidenceStep:
    """테스트용 EvidenceStep을 생성한다."""
    return EvidenceStep(
        tool_name=tool_name,
        input_params={"bus_id": 1},
        output_summary="모선 전압 0.98 pu 조회 완료",
        duration_ms=12.5,
    )


# ──────────────────────────────────────────────
# SessionManager 테스트
# ──────────────────────────────────────────────

class TestSessionManager:
    """SessionManager 세션 생성/조회/업데이트 검증."""

    def test_create_session_returns_agent_context(self) -> None:
        """create_session()이 AgentContext를 반환해야 한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="모선 전압 요약해줘")
        assert isinstance(ctx, AgentContext)
        assert ctx.user_query == "모선 전압 요약해줘"
        assert ctx.mode == "HOTL"
        assert ctx.namespace == "ops"

    def test_create_session_snapshot_ts_included(self) -> None:
        """생성된 AgentContext에 snapshot_ts가 포함되어야 한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="계통 상태 확인")
        assert ctx.snapshot_ts is not None
        assert ctx.snapshot_ts.tzinfo is not None  # UTC timezone 포함

    def test_create_session_with_hitl_mode(self) -> None:
        """HITL 모드로 세션을 생성할 수 있다."""
        manager = SessionManager()
        ctx = manager.create_session(
            user_query="CB 5번 개방 검토",
            mode="HITL",
            namespace="study",
        )
        assert ctx.mode == "HITL"
        assert ctx.namespace == "study"

    def test_create_session_generates_unique_ids(self) -> None:
        """두 세션의 session_id는 서로 달라야 한다."""
        manager = SessionManager()
        ctx1 = manager.create_session(user_query="질의 1")
        ctx2 = manager.create_session(user_query="질의 2")
        assert ctx1.session_id != ctx2.session_id

    def test_get_session_returns_context(self) -> None:
        """get_session()이 생성된 컨텍스트를 반환해야 한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="테스트")
        retrieved = manager.get_session(ctx.session_id)
        assert retrieved is not None
        assert retrieved.session_id == ctx.session_id

    def test_get_session_unknown_id_returns_none(self) -> None:
        """존재하지 않는 session_id는 None을 반환한다."""
        manager = SessionManager()
        result = manager.get_session("nonexistent-session-id")
        assert result is None

    def test_update_facts_appends(self) -> None:
        """update_facts()가 facts를 추가해야 한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="테스트")
        manager.update_facts(ctx.session_id, [_make_fact("voltage", 0.98)])

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.structured_facts) == 1

    def test_update_facts_fifo_max_20(self) -> None:
        """21번째 fact 추가 시 첫 번째 fact가 제거된다 (FIFO, 최대 20건)."""
        manager = SessionManager(max_facts=20)
        ctx = manager.create_session(user_query="FIFO 테스트")

        # 20건 추가
        for i in range(20):
            manager.update_facts(ctx.session_id, [_make_fact(f"key_{i}", float(i))])

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.structured_facts) == 20
        # 첫 번째 key는 'key_0'이어야 함
        assert state.structured_facts[0].key == "key_0"

        # 21번째 추가
        manager.update_facts(ctx.session_id, [_make_fact("key_20", 20.0)])

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.structured_facts) == 20  # 여전히 20건
        # key_0이 제거되어 key_1이 첫 번째여야 함
        assert state.structured_facts[0].key == "key_1"
        # key_20이 마지막이어야 함
        assert state.structured_facts[-1].key == "key_20"

    def test_update_facts_no_compression(self) -> None:
        """FIFO로 제거된 항목의 내용은 압축/변형되지 않는다."""
        manager = SessionManager(max_facts=3)
        ctx = manager.create_session(user_query="압축 금지 테스트")

        for i in range(3):
            manager.update_facts(ctx.session_id, [_make_fact(f"k{i}", float(i * 0.01))])

        # 4번째 추가 시 첫 번째 제거
        manager.update_facts(ctx.session_id, [_make_fact("k3", 3.0)])

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        # 남은 facts의 값이 원본 그대로인지 확인
        remaining_keys = [f.key for f in state.structured_facts]
        assert "k0" not in remaining_keys
        assert "k1" in remaining_keys
        assert "k2" in remaining_keys
        assert "k3" in remaining_keys

    def test_add_evidence_appends(self) -> None:
        """add_evidence()가 evidence_chain에 단계를 추가한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="테스트")
        manager.add_evidence(ctx.session_id, _make_evidence("read_bus_voltage"))

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.evidence_chain) == 1
        assert state.evidence_chain[0].tool_name == "read_bus_voltage"

    def test_add_evidence_fifo_max_5(self) -> None:
        """evidence_chain은 최대 5단계를 유지하고 초과 시 FIFO로 제거한다."""
        manager = SessionManager(max_evidence=5)
        ctx = manager.create_session(user_query="Evidence FIFO 테스트")

        tools = ["tool_0", "tool_1", "tool_2", "tool_3", "tool_4"]
        for tool in tools:
            manager.add_evidence(ctx.session_id, _make_evidence(tool))

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.evidence_chain) == 5

        # 6번째 추가
        manager.add_evidence(ctx.session_id, _make_evidence("tool_5"))

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        assert len(state.evidence_chain) == 5
        assert state.evidence_chain[0].tool_name == "tool_1"  # tool_0 제거
        assert state.evidence_chain[-1].tool_name == "tool_5"

    def test_close_session(self) -> None:
        """close_session() 후 get_session()은 None을 반환한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="종료 테스트")
        session_id = ctx.session_id

        manager.close_session(session_id)
        result = manager.get_session(session_id)
        assert result is None

    def test_update_facts_on_closed_session_raises(self) -> None:
        """종료된 세션에 facts 업데이트 시 KeyError가 발생한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="테스트")
        manager.close_session(ctx.session_id)

        with pytest.raises(KeyError):
            manager.update_facts(ctx.session_id, [_make_fact()])

    def test_add_evidence_on_closed_session_raises(self) -> None:
        """종료된 세션에 evidence 추가 시 KeyError가 발생한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query="테스트")
        manager.close_session(ctx.session_id)

        with pytest.raises(KeyError):
            manager.add_evidence(ctx.session_id, _make_evidence())


# ──────────────────────────────────────────────
# SessionSummarizer 테스트
# ──────────────────────────────────────────────

class TestSessionSummarizer:
    """SessionSummarizer 요약 검증 — facts 수치 미포함 확인."""

    def _make_state(self, query: str = "테스트 질의") -> SessionState:
        """테스트용 SessionState를 생성한다."""
        manager = SessionManager()
        ctx = manager.create_session(user_query=query)

        # facts와 evidence 추가
        manager.update_facts(ctx.session_id, [
            _make_fact("bus_voltage", 0.98),
            _make_fact("line_loading", 85.0),
        ])
        manager.add_evidence(ctx.session_id, _make_evidence("read_bus_voltage"))
        manager.add_evidence(ctx.session_id, _make_evidence("read_line_loading"))

        state = manager.get_session_state(ctx.session_id)
        assert state is not None
        return state

    def test_summarize_returns_string(self) -> None:
        """summarize()가 문자열을 반환해야 한다."""
        summarizer = SessionSummarizer()
        state = self._make_state()
        result = summarizer.summarize(state)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_summarize_does_not_include_numeric_values(self) -> None:
        """요약에 facts의 수치값(0.98, 85.0)이 포함되지 않아야 한다."""
        summarizer = SessionSummarizer()
        state = self._make_state()
        result = summarizer.summarize(state)
        # facts 수치가 직접 노출되어서는 안 됨
        assert "0.98" not in result
        assert "85.0" not in result

    def test_summarize_includes_tool_names(self) -> None:
        """요약에 호출한 Tool 이름이 포함되어야 한다."""
        summarizer = SessionSummarizer()
        state = self._make_state()
        result = summarizer.summarize(state)
        assert "read_bus_voltage" in result or "read_line_loading" in result

    def test_summarize_includes_facts_count(self) -> None:
        """요약에 facts 건수가 포함되어야 한다 (수치는 제외)."""
        summarizer = SessionSummarizer()
        state = self._make_state()
        result = summarizer.summarize(state)
        assert "2건" in result  # facts 건수

    def test_summarize_respects_max_length(self) -> None:
        """max_length를 초과하지 않는 요약을 반환해야 한다."""
        summarizer = SessionSummarizer()
        state = self._make_state("매우 긴 질의" * 100)
        result = summarizer.summarize(state, max_length=100)
        assert len(result) <= 100

    def test_summarize_includes_snapshot_ts(self) -> None:
        """요약에 기준 시각(snapshot_ts)이 포함되어야 한다."""
        summarizer = SessionSummarizer()
        state = self._make_state()
        result = summarizer.summarize(state)
        assert "기준 시각" in result or "snapshot_ts" in result or "T" in result


# ──────────────────────────────────────────────
# MCPGateway 테스트
# ──────────────────────────────────────────────

class TestMCPGateway:
    """MCPGateway 보안 정책 및 Tool 호출 검증."""

    @pytest.fixture
    def gateway(self, tmp_path) -> MCPGateway:
        """임시 경로에 Provenance 로그를 기록하는 게이트웨이."""
        log_path = str(tmp_path / "provenance.jsonl")
        return MCPGateway(provenance_log_path=log_path)

    @pytest.mark.asyncio
    async def test_read_tool_allowed_in_ops(self, gateway: MCPGateway) -> None:
        """ops: 네임스페이스에서 read tool 호출이 허용된다."""
        response = await gateway.call_tool(
            tool_name="read_bus_voltage",
            params={"bus_id": 1},
            namespace="ops",
        )
        assert response.tool_name == "read_bus_voltage"
        assert response.evidence is not None
        assert response.evidence.tool_name == "read_bus_voltage"

    @pytest.mark.asyncio
    async def test_read_tool_allowed_in_study(self, gateway: MCPGateway) -> None:
        """study: 네임스페이스에서도 read tool 호출이 허용된다."""
        response = await gateway.call_tool(
            tool_name="query_app",
            params={"app": "SE", "mode": "snapshot"},
            namespace="study",
        )
        assert response.tool_name == "query_app"

    @pytest.mark.asyncio
    async def test_blocked_write_tool_denied_in_ops(self, gateway: MCPGateway) -> None:
        """ops: 네임스페이스에서 BLOCKED_WRITE_TOOLS 호출은 403 거부된다."""
        with pytest.raises(MCPAccessDeniedError) as exc_info:
            await gateway.call_tool(
                tool_name="write_bus",
                params={"bus_id": 1, "voltage_pu": 1.05},
                namespace="ops",
            )
        assert exc_info.value.tool_name == "write_bus"

    @pytest.mark.asyncio
    async def test_blocked_write_tool_denied_in_study(self, gateway: MCPGateway) -> None:
        """BLOCKED_WRITE_TOOLS는 study: 네임스페이스에서도 차단된다."""
        with pytest.raises(MCPAccessDeniedError):
            await gateway.call_tool(
                tool_name="set_switch",
                params={"sw_id": "sw_001", "status": "open"},
                namespace="study",
            )

    @pytest.mark.asyncio
    async def test_study_write_tool_blocked_in_ops(self, gateway: MCPGateway) -> None:
        """study: 전용 write Tool은 ops: 네임스페이스에서 차단된다."""
        with pytest.raises(MCPAccessDeniedError):
            await gateway.call_tool(
                tool_name="create_study",
                params={"name": "test_study"},
                namespace="ops",
            )

    @pytest.mark.asyncio
    async def test_study_write_tool_allowed_in_study(self, gateway: MCPGateway) -> None:
        """study: 네임스페이스에서 STUDY_WRITE_TOOLS 호출은 허용된다."""
        response = await gateway.call_tool(
            tool_name="create_study",
            params={"name": "test_study"},
            namespace="study",
        )
        assert response.tool_name == "create_study"

    @pytest.mark.asyncio
    async def test_run_study_allowed_in_study(self, gateway: MCPGateway) -> None:
        """run_study는 study: 네임스페이스에서 허용된다."""
        response = await gateway.call_tool(
            tool_name="run_study",
            params={"study_id": "abc123"},
            namespace="study",
        )
        assert response.tool_name == "run_study"

    @pytest.mark.asyncio
    async def test_unknown_tool_raises_not_found(self, gateway: MCPGateway) -> None:
        """등록되지 않은 Tool 호출 시 MCPToolNotFoundError가 발생한다."""
        with pytest.raises(MCPToolNotFoundError) as exc_info:
            await gateway.call_tool(
                tool_name="nonexistent_tool",
                params={},
                namespace="ops",
            )
        assert exc_info.value.tool_name == "nonexistent_tool"

    @pytest.mark.asyncio
    async def test_evidence_chain_auto_generated(self, gateway: MCPGateway) -> None:
        """Tool 호출 성공 시 Evidence chain이 자동 생성된다."""
        response = await gateway.call_tool(
            tool_name="get_alarm_list",
            params={},
            namespace="ops",
        )
        evidence = response.evidence
        assert evidence.tool_name == "get_alarm_list"
        assert evidence.duration_ms >= 0
        assert len(evidence.output_summary) > 0

    @pytest.mark.asyncio
    async def test_provenance_log_written(self, gateway: MCPGateway, tmp_path) -> None:
        """Tool 호출 성공 시 Provenance 로그가 기록된다."""
        import json
        log_path = str(tmp_path / "provenance.jsonl")
        gw = MCPGateway(provenance_log_path=log_path)

        await gw.call_tool(
            tool_name="read_bus_voltage",
            params={"bus_id": 5},
            namespace="ops",
            agent_id="alarm_analysis",
        )

        import os
        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["tool"] == "read_bus_voltage"
        assert record["namespace"] == "ops"
        assert record["agent_id"] == "alarm_analysis"

    @pytest.mark.asyncio
    async def test_snapshot_ts_in_response(self, gateway: MCPGateway) -> None:
        """Tool 호출 응답에 snapshot_ts가 포함되어야 한다."""
        response = await gateway.call_tool(
            tool_name="read_gen_output",
            params={"gen_id": "gen_001"},
            namespace="ops",
        )
        assert response.snapshot_ts is not None
        assert response.snapshot_ts.tzinfo is not None
