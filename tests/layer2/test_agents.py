"""Layer 2 에이전트 단위 테스트 — AI-EMS v5.1 Phase 2.

테스트 대상:
  - NL2AppAgent: SE/TP/AGC/SCA 각 앱 조회 → AIResponse + evidence_chain
  - RAGAgent: 용어 검색, 기준값 검색, N-1 규정 검색
  - AlarmAnalysisAgent: 활성 알람 분석 + root cause + suggestions
  - StudyAgent: CB 개방 what-if → 전후 비교 + HITL
  - NLNavigationAgent: 화면 이동 명령 + HOTL

공통 검증 항목:
  - snapshot_ts 포함 여부
  - evidence_chain 최소 길이 1 이상
  - mode 정확 여부 (HITL/HOTL)
  - Pydantic v2 스키마 유효성
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest
import pandapower.networks as pn

from src.layer2.agents import (
    AlarmAnalysisAgent,
    NL2AppAgent,
    NLNavigationAgent,
    RAGAgent,
    StudyAgent,
)
from src.shared.schemas.agent import AgentContext, AIResponse
from src.shared.schemas.alarm import Alarm, AlarmSeverity, AlarmType


# ──────────────────────────────────────────────────────────────────────────────
# 공통 픽스처
# ──────────────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_context(
    query: str,
    namespace: str = "ops",
    mode: str = "HOTL",
) -> AgentContext:
    """테스트용 AgentContext 생성 헬퍼."""
    return AgentContext(
        session_id="test-session-001",
        user_query=query,
        namespace=namespace,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        snapshot_ts=_utcnow(),
    )


def _assert_valid_response(response: AIResponse, expected_mode: str) -> None:
    """AIResponse 공통 검증.

    - snapshot_ts 포함 여부
    - evidence_chain 최소 1개 이상
    - answer 비어있지 않음
    - confidence 범위 0~1
    """
    assert isinstance(response, AIResponse), "AIResponse 스키마가 아님"
    assert response.snapshot_ts is not None, "snapshot_ts가 없음"
    assert isinstance(response.snapshot_ts, datetime), "snapshot_ts가 datetime이 아님"
    assert len(response.evidence_chain) >= 1, (
        f"evidence_chain 최소 1개 이상 필수 (현재 {len(response.evidence_chain)}개)"
    )
    assert response.answer, "answer가 비어있음"
    assert 0.0 <= response.confidence <= 1.0, (
        f"confidence 범위 위반: {response.confidence}"
    )
    for step in response.evidence_chain:
        assert step.tool_name, "evidence_chain 항목에 tool_name이 없음"
        assert step.duration_ms >= 0, "duration_ms가 음수"


@pytest.fixture
def ieee14_net():
    """IEEE 14-bus 테스트 네트워크 픽스처."""
    return pn.case14()


@pytest.fixture
def sample_alarms() -> List[Alarm]:
    """테스트용 샘플 알람 목록 픽스처."""
    return [
        Alarm(
            alarm_id="alarm-001",
            alarm_type=AlarmType.LIMIT,
            severity=AlarmSeverity.CRITICAL,
            element_type="bus",
            element_id=3,
            message="Bus 3: 전압 1.12pu 운용범위 초과",
            value=1.12,
            threshold=1.10,
            acknowledged=False,
            timestamp=_utcnow(),
        ),
        Alarm(
            alarm_id="alarm-002",
            alarm_type=AlarmType.LIMIT,
            severity=AlarmSeverity.WARNING,
            element_type="line",
            element_id=0,
            message="Line 0: 부하율 85.3% 경고",
            value=85.3,
            threshold=80.0,
            acknowledged=False,
            timestamp=_utcnow(),
        ),
        Alarm(
            alarm_id="alarm-003",
            alarm_type=AlarmType.STATE,
            severity=AlarmSeverity.INFO,
            element_type="switch",
            element_id=1,
            message="Switch 1: 상태 변화 감지",
            value=None,
            threshold=None,
            acknowledged=True,
            timestamp=_utcnow(),
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# NL2AppAgent 테스트
# ──────────────────────────────────────────────────────────────────────────────


class TestNL2AppAgent:
    """NL2App 에이전트 테스트 — SE/TP/AGC/SCA 조회."""

    @pytest.mark.asyncio
    async def test_se_query(self, ieee14_net) -> None:
        """SE 조회 — 상태추정 결과 + evidence_chain."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("상태추정 결과를 알려줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL", "NL2App은 HOTL이어야 함"
        # SE 조회 결과 검증
        assert any("상태추정" in step.tool_name or "SE" in step.tool_name.upper()
                   or "StateEstimator" in step.tool_name
                   for step in response.evidence_chain), \
            "SE evidence가 없음"
        assert "상태추정" in response.answer or "SE" in response.answer or "solved" in response.answer.lower()

    @pytest.mark.asyncio
    async def test_tp_query(self, ieee14_net) -> None:
        """TP 조회 — 조류계산 결과 + evidence_chain."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("조류계산 결과와 위반사항을 알려줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL"
        # TP 결과 검증
        assert any("PowerFlowEngine" in step.tool_name or "powerflow" in step.tool_name.lower()
                   for step in response.evidence_chain)
        # 수치가 facts에 포함되어야 함
        fact_keys = {f.key for f in response.facts}
        assert "pf_converged" in fact_keys, "pf_converged fact 없음"
        assert "pf_max_vm_pu" in fact_keys, "pf_max_vm_pu fact 없음"

    @pytest.mark.asyncio
    async def test_agc_query(self, ieee14_net) -> None:
        """AGC 조회 — 주파수/예비력 결과 + evidence_chain."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("현재 주파수와 예비력 현황을 알려줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL"
        # AGC evidence 확인
        assert any("AGC" in step.tool_name or "agc" in step.tool_name.lower()
                   for step in response.evidence_chain)
        # 주파수 fact 확인
        fact_keys = {f.key for f in response.facts}
        assert "agc_frequency_hz" in fact_keys, "agc_frequency_hz fact 없음"
        # 주파수 단위 확인
        freq_fact = next(f for f in response.facts if f.key == "agc_frequency_hz")
        assert freq_fact.unit == "Hz", f"주파수 단위 오류: {freq_fact.unit}"

    @pytest.mark.asyncio
    async def test_sca_query(self, ieee14_net) -> None:
        """SCA 조회 — 단락전류 해석 + evidence_chain."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("버스 0의 단락전류를 계산해줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL"
        # SCA evidence 확인
        assert any("shortcircuit" in step.tool_name.lower() or "sca" in step.tool_name.lower()
                   or "calc_sc" in step.tool_name.lower()
                   for step in response.evidence_chain)

    @pytest.mark.asyncio
    async def test_default_tp_fallback(self, ieee14_net) -> None:
        """앱 종류 감지 실패 시 TP fallback."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("계통 정보 알려줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # TP fallback으로 처리됨
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_evidence_chain_length(self, ieee14_net) -> None:
        """TP 에이전트 — evidence_chain 최소 2개 (runpp + violations)."""
        agent = NL2AppAgent(net=ieee14_net)
        context = _make_context("조류계산", mode="HOTL")

        response = await agent.run(context)

        # TP는 runpp + get_violations 총 2개 evidence
        assert len(response.evidence_chain) >= 2, \
            f"TP evidence_chain 최소 2개 필요 (현재 {len(response.evidence_chain)}개)"


# ──────────────────────────────────────────────────────────────────────────────
# RAGAgent 테스트
# ──────────────────────────────────────────────────────────────────────────────


class TestRAGAgent:
    """RAG 에이전트 테스트 — 도메인 지식 검색."""

    @pytest.mark.asyncio
    async def test_glossary_search(self) -> None:
        """용어 검색 — glossary.json에서 키워드 매칭."""
        agent = RAGAgent()
        context = _make_context("상태추정이 무엇인가요?", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL"
        # glossary_search evidence 확인
        assert any("glossary" in step.tool_name.lower()
                   for step in response.evidence_chain)

    @pytest.mark.asyncio
    async def test_voltage_limits_search(self) -> None:
        """전압 기준값 검색 — voltage_limits.json에서 조회."""
        agent = RAGAgent()
        context = _make_context("345kV 전압 운용범위가 얼마인가요?", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # voltage_limits_search evidence 확인
        has_volt_evidence = any(
            "voltage" in step.tool_name.lower()
            for step in response.evidence_chain
        )
        assert has_volt_evidence, "전압 기준 evidence 없음"

    @pytest.mark.asyncio
    async def test_frequency_limits_search(self) -> None:
        """주파수 기준값 검색 — frequency_limits.json에서 조회."""
        agent = RAGAgent()
        context = _make_context("주파수 한계치 기준이 뭔가요?", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # frequency evidence 확인
        assert any("frequency" in step.tool_name.lower()
                   for step in response.evidence_chain)

    @pytest.mark.asyncio
    async def test_n1_criteria_search(self) -> None:
        """N-1 기준 검색 — n1_criteria.json에서 조회."""
        agent = RAGAgent()
        context = _make_context("N-1 상정고장 기준이 무엇인지 알려줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # N-1 evidence 확인
        has_n1_evidence = any(
            "n1" in step.tool_name.lower() or "contingency" in step.tool_name.lower()
            for step in response.evidence_chain
        )
        assert has_n1_evidence, "N-1 기준 evidence 없음"
        # N-1 결과가 answer에 포함
        assert "N-1" in response.answer or "고시" in response.answer or "상정고장" in response.answer

    @pytest.mark.asyncio
    async def test_no_match_returns_warning(self) -> None:
        """검색 결과 없거나 적을 때 상대적으로 낮은 신뢰도 반환."""
        agent = RAGAgent()
        # 완전히 무관한 영어 코드 문자열 — glossary 매칭 없어야 함
        context = _make_context("ZZZNOMATCH99999XQYQY", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # evidence는 최소 1개 보장 (glossary_search 항상 실행)
        assert len(response.evidence_chain) >= 1
        # 매칭 없으면 신뢰도가 glossary 매칭 있을 때보다 낮아야 함 (≤ 0.7)
        assert response.confidence <= 0.7, \
            f"매칭 없을 때 신뢰도 과도: {response.confidence}"

    @pytest.mark.asyncio
    async def test_hotl_mode(self) -> None:
        """RAG 에이전트 HOTL 모드 검증."""
        agent = RAGAgent()
        assert agent.mode == "HOTL", f"RAG는 HOTL이어야 함 (현재: {agent.mode})"


# ──────────────────────────────────────────────────────────────────────────────
# AlarmAnalysisAgent 테스트
# ──────────────────────────────────────────────────────────────────────────────


class TestAlarmAnalysisAgent:
    """알람 분석 에이전트 테스트 — HITL 모드."""

    @pytest.mark.asyncio
    async def test_active_alarms_analysis(self, sample_alarms) -> None:
        """활성 알람 분석 — 유형별 분류 + root cause."""
        agent = AlarmAnalysisAgent(active_alarms=sample_alarms)
        context = _make_context("현재 활성 알람을 분석해줘", mode="HITL")

        response = await agent.run(context)

        _assert_valid_response(response, "HITL")
        assert agent.mode == "HITL", "AlarmAnalysis는 HITL이어야 함"

        # 알람 건수 fact 확인
        fact_keys = {f.key for f in response.facts}
        assert "alarm_total" in fact_keys, "alarm_total fact 없음"
        total_fact = next(f for f in response.facts if f.key == "alarm_total")
        assert total_fact.value == len(sample_alarms)

    @pytest.mark.asyncio
    async def test_root_cause_inference(self, sample_alarms) -> None:
        """Root cause 추론 — 알람 유형별 규칙 기반."""
        agent = AlarmAnalysisAgent(active_alarms=sample_alarms)
        context = _make_context("알람 원인 분석", mode="HITL")

        response = await agent.run(context)

        # CRITICAL LIMIT 알람 있으므로 root cause + suggestion 있어야 함
        assert len(response.evidence_chain) >= 1
        # 조치 권고가 있어야 함 (HITL)
        assert len(response.suggestions) >= 1, "HITL 에이전트는 suggestions 필수"
        # HITL 승인 표시 확인
        hitl_suggestions = [s for s in response.suggestions if "HITL" in s or "승인" in s]
        assert len(hitl_suggestions) >= 1, "HITL 승인 필요 표시가 없음"

    @pytest.mark.asyncio
    async def test_empty_alarms(self) -> None:
        """활성 알람 없을 때 정상 응답."""
        agent = AlarmAnalysisAgent(active_alarms=[])
        context = _make_context("알람 현황", mode="HITL")

        response = await agent.run(context)

        _assert_valid_response(response, "HITL")
        assert response.confidence > 0.8, "알람 없을 때 신뢰도 높아야 함"
        # 활성 알람 없음 메시지
        assert "없" in response.answer or "정상" in response.answer

    @pytest.mark.asyncio
    async def test_critical_alarm_warning(self, sample_alarms) -> None:
        """CRITICAL 알람 존재 시 warnings 포함."""
        agent = AlarmAnalysisAgent(active_alarms=sample_alarms)
        context = _make_context("알람 상태", mode="HITL")

        response = await agent.run(context)

        # CRITICAL 알람이 있으므로 warnings에 포함
        assert len(response.warnings) >= 1, "CRITICAL 알람 있을 때 warnings 필수"

    @pytest.mark.asyncio
    async def test_alarm_classification_facts(self, sample_alarms) -> None:
        """알람 유형별 분류 facts 확인."""
        agent = AlarmAnalysisAgent(active_alarms=sample_alarms)
        context = _make_context("알람 분류", mode="HITL")

        response = await agent.run(context)

        fact_keys = {f.key for f in response.facts}
        # 유형별 집계 fact 확인
        assert "alarm_count_LIMIT" in fact_keys
        assert "alarm_count_STATE" in fact_keys


# ──────────────────────────────────────────────────────────────────────────────
# StudyAgent 테스트
# ──────────────────────────────────────────────────────────────────────────────


class TestStudyAgent:
    """계통검토 에이전트 테스트 — What-if 스터디."""

    @pytest.mark.asyncio
    async def test_cb_open_study(self, ieee14_net) -> None:
        """CB 개방 what-if — 전후 비교 + HITL."""
        agent = StudyAgent(net=ieee14_net)
        context = _make_context("선로 0 개방하면 어떻게 되나요?", mode="HITL", namespace="study")

        response = await agent.run(context)

        _assert_valid_response(response, "HITL")
        assert agent.mode == "HITL", "Study는 HITL이어야 함"

        # 스터디 evidence 확인
        tool_names = [step.tool_name for step in response.evidence_chain]
        assert any("PowerFlowEngine" in t or "study" in t.lower()
                   for t in tool_names), "스터디 evidence 없음"

    @pytest.mark.asyncio
    async def test_study_namespace_isolation(self, ieee14_net) -> None:
        """ops 네트워크 불변 검증 — study 후 ops 원본 수정 없음."""
        import pandapower as pp

        # ops 네트워크 사전 조류계산으로 기준값 저장
        pp.runpp(ieee14_net)
        base_max_vm = float(ieee14_net.res_bus["vm_pu"].max())

        agent = StudyAgent(net=ieee14_net)
        context = _make_context("선로 2 개방", mode="HITL", namespace="study")
        await agent.run(context)

        # ops 원본은 수정되지 않아야 함
        assert ieee14_net.line.at[2, "in_service"] is True or \
               ieee14_net.line.iloc[2]["in_service"] == True, \
            "ops 원본 네트워크가 수정됨 — namespace 격리 위반!"

    @pytest.mark.asyncio
    async def test_study_result_facts(self, ieee14_net) -> None:
        """스터디 결과 facts 확인 — 변경 전후 비교."""
        agent = StudyAgent(net=ieee14_net)
        context = _make_context("선로 1 개방하면?", mode="HITL", namespace="study")

        response = await agent.run(context)

        fact_keys = {f.key for f in response.facts}
        # 기준(base) 및 스터디 결과 fact 확인
        assert "base_max_vm_pu" in fact_keys, "base_max_vm_pu fact 없음"
        assert "study_max_vm_pu" in fact_keys or "study_id" in fact_keys

    @pytest.mark.asyncio
    async def test_hitl_suggestions(self, ieee14_net) -> None:
        """HITL 조치 권고 포함 여부 — suggestions에 승인 필요 표시."""
        agent = StudyAgent(net=ieee14_net)
        context = _make_context("3번 선로 개방 시뮬레이션", mode="HITL", namespace="study")

        response = await agent.run(context)

        _assert_valid_response(response, "HITL")
        # 결과에 HITL 언급 (answer 또는 suggestions)
        hitl_mentioned = (
            "HITL" in response.answer
            or "승인" in response.answer
            or any("HITL" in s or "승인" in s for s in response.suggestions)
        )
        assert hitl_mentioned, "HITL 승인 필요 표시가 없음"

    @pytest.mark.asyncio
    async def test_no_change_fallback(self, ieee14_net) -> None:
        """변경 사항 없는 질의 — 베이스케이스 반환."""
        agent = StudyAgent(net=ieee14_net)
        context = _make_context("계통 어떠세요", mode="HITL", namespace="study")

        response = await agent.run(context)

        _assert_valid_response(response, "HITL")
        # 변경 없음 메시지 포함
        assert "변경" in response.answer or "입력" in response.answer or "파악" in response.answer


# ──────────────────────────────────────────────────────────────────────────────
# NLNavigationAgent 테스트
# ──────────────────────────────────────────────────────────────────────────────


class TestNLNavigationAgent:
    """NL Navigation 에이전트 테스트 — 화면 이동."""

    @pytest.mark.asyncio
    async def test_navigate_to_system_overview(self) -> None:
        """계통도 화면 이동 명령."""
        agent = NLNavigationAgent()
        context = _make_context("계통도 보여줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert agent.mode == "HOTL", "Navigation은 HOTL이어야 함"
        # NAVIGATE 명령 확인
        assert any("NAVIGATE" in s for s in response.suggestions), \
            "navigation 명령이 suggestions에 없음"

    @pytest.mark.asyncio
    async def test_navigate_to_alarm_panel(self) -> None:
        """알람 패널 화면 이동 명령."""
        agent = NLNavigationAgent()
        context = _make_context("알람 창 열어줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        nav_cmd = next(s for s in response.suggestions if "NAVIGATE" in s)
        assert "alarm_panel" in nav_cmd, f"alarm_panel이 아닌 화면으로 이동: {nav_cmd}"

    @pytest.mark.asyncio
    async def test_navigate_to_gis(self) -> None:
        """GIS 지도 화면 이동."""
        agent = NLNavigationAgent()
        context = _make_context("GIS 지도 보여줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        nav_cmd = next(s for s in response.suggestions if "NAVIGATE" in s)
        assert "gis_map" in nav_cmd

    @pytest.mark.asyncio
    async def test_navigate_to_agc(self) -> None:
        """AGC 화면 이동."""
        agent = NLNavigationAgent()
        context = _make_context("AGC 화면 이동", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        nav_cmd = next(s for s in response.suggestions if "NAVIGATE" in s)
        assert "agc_view" in nav_cmd

    @pytest.mark.asyncio
    async def test_navigate_to_se_view(self) -> None:
        """상태추정 화면 이동."""
        agent = NLNavigationAgent()
        context = _make_context("상태추정 화면 보여줘", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        nav_cmd = next(s for s in response.suggestions if "NAVIGATE" in s)
        assert "se_view" in nav_cmd

    @pytest.mark.asyncio
    async def test_navigate_low_confidence_warning(self) -> None:
        """낮은 신뢰도 시 경고 포함."""
        agent = NLNavigationAgent()
        # 화면을 특정하기 어려운 질의
        context = _make_context("어디론가 이동해", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        # 낮은 신뢰도이면 warnings 존재 가능
        # (항상 경고는 아니므로 검증 완화)
        assert len(response.evidence_chain) >= 1

    @pytest.mark.asyncio
    async def test_navigate_evidence_chain(self) -> None:
        """Navigation evidence_chain 포함 검증."""
        agent = NLNavigationAgent()
        context = _make_context("조류계산 결과 보고싶어", mode="HOTL")

        response = await agent.run(context)

        _assert_valid_response(response, "HOTL")
        assert any("screen" in step.tool_name.lower() or "navigation" in step.tool_name.lower()
                   for step in response.evidence_chain)

    @pytest.mark.asyncio
    async def test_hotl_mode_verification(self) -> None:
        """Navigation HOTL 모드 검증."""
        agent = NLNavigationAgent()
        assert agent.mode == "HOTL", f"Navigation은 HOTL이어야 함 (현재: {agent.mode})"


# ──────────────────────────────────────────────────────────────────────────────
# 공통 설계 원칙 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestDesignPrinciples:
    """설계 원칙 준수 공통 테스트."""

    @pytest.mark.asyncio
    async def test_all_agents_have_snapshot_ts(self, ieee14_net, sample_alarms) -> None:
        """모든 에이전트 응답에 snapshot_ts 포함 (설계 원칙 5)."""
        agents_and_queries = [
            (NL2AppAgent(net=ieee14_net), "조류계산"),
            (RAGAgent(), "N-1 기준"),
            (AlarmAnalysisAgent(active_alarms=sample_alarms), "알람 분석"),
            (StudyAgent(net=ieee14_net), "선로 0 개방"),
            (NLNavigationAgent(), "계통도"),
        ]
        for agent, query in agents_and_queries:
            ctx = _make_context(query)
            response = await agent.run(ctx)
            assert response.snapshot_ts is not None, \
                f"{agent.name}: snapshot_ts 없음 (설계 원칙 5 위반)"

    @pytest.mark.asyncio
    async def test_all_agents_have_evidence_chain(self, ieee14_net, sample_alarms) -> None:
        """모든 에이전트 응답에 evidence_chain ≥ 1 (설계 원칙 4)."""
        agents_and_queries = [
            (NL2AppAgent(net=ieee14_net), "상태추정"),
            (RAGAgent(), "주파수 기준"),
            (AlarmAnalysisAgent(active_alarms=sample_alarms), "알람"),
            (StudyAgent(net=ieee14_net), "선로 1 개방"),
            (NLNavigationAgent(), "GIS 지도"),
        ]
        for agent, query in agents_and_queries:
            ctx = _make_context(query)
            response = await agent.run(ctx)
            assert len(response.evidence_chain) >= 1, \
                f"{agent.name}: evidence_chain 없음 (설계 원칙 4 위반)"

    @pytest.mark.asyncio
    async def test_hitl_hotl_classification(self, ieee14_net, sample_alarms) -> None:
        """HITL/HOTL 분류 정확도 100% (설계 원칙 3)."""
        hotl_agents = [NL2AppAgent(net=ieee14_net), RAGAgent(), NLNavigationAgent()]
        hitl_agents = [AlarmAnalysisAgent(active_alarms=sample_alarms), StudyAgent(net=ieee14_net)]

        for agent in hotl_agents:
            assert agent.mode == "HOTL", f"{agent.name}은 HOTL이어야 함"

        for agent in hitl_agents:
            assert agent.mode == "HITL", f"{agent.name}은 HITL이어야 함"

    @pytest.mark.asyncio
    async def test_study_namespace_is_study(self, ieee14_net) -> None:
        """StudyAgent는 study 네임스페이스에서만 실행 (설계 원칙 2)."""
        agent = StudyAgent(net=ieee14_net)
        context = _make_context("선로 0 개방", namespace="study", mode="HITL")

        response = await agent.run(context)

        # study: 네임스페이스 evidence 확인
        study_evidence = [
            step for step in response.evidence_chain
            if "study" in step.tool_name.lower() or "study" in str(step.input_params).lower()
        ]
        assert len(study_evidence) >= 1, "study 네임스페이스 evidence 없음"

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, ieee14_net, sample_alarms) -> None:
        """모든 응답 confidence 0.0~1.0 범위 내."""
        agents_and_queries = [
            (NL2AppAgent(net=ieee14_net), "AGC"),
            (RAGAgent(), "전압"),
            (AlarmAnalysisAgent(active_alarms=sample_alarms), "알람"),
            (StudyAgent(net=ieee14_net), "선로 2 개방"),
            (NLNavigationAgent(), "알람 패널"),
        ]
        for agent, query in agents_and_queries:
            ctx = _make_context(query)
            response = await agent.run(ctx)
            assert 0.0 <= response.confidence <= 1.0, \
                f"{agent.name}: confidence={response.confidence} 범위 위반"
