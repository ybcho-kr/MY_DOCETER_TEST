# Layer 2 — AI Agent

## 이 디렉토리의 역할
PydanticAI 기반 다중 에이전트 오케스트레이션.
사용자 자연어 → Intent 분류 → 에이전트 라우팅 → Tool 호출 → 응답 생성.

## v5.1 Phase 2 범위 — 반응형만
Phase 2에서는 **반응형 에이전트만** 구현. 능동형 AI 인사이트(APScheduler 기반)는 Phase 4로 이동.

### 포함 (Phase 2)
- 오케스트레이터: Intent 분류 → 에이전트 라우팅
- NL Navigation: 화면/지도 이동 (HOTL)
- NL2App: EMS 앱 결과 조회 (HOTL)
- RAG: 4계층 지식 활용 (벡터+BM25+NL→SQL)
- 알람 분석: 활성 알람 조회 + root cause (HITL)
- 계통검토: ops→study 격리 What-if (HITL)
- API Gateway: MCP + read_only + Evidence chain
- HITL 기본 승인 모듈
- AgentContext + CallGuard + snapshot_ts

### 제외 → Phase 4
- APScheduler 기반 5분 건전성 점검
- 1시간 리스크 평가
- 알람 스톰 자동 분석
- 기상 영향 분석
- 이상 패턴 탐지 (15분)
- 일일 자동 리포트

## 에이전트 구조
- **orchestrator/**: Intent 분류 → 하위 에이전트 디스패치
- **agents/nl_navigation.py**: 화면/지도 이동 (HOTL)
- **agents/nl2app.py**: EMS 앱 결과 조회 (HOTL)
- **agents/rag.py**: 4계층 지식 활용 (벡터+BM25+NL→SQL)
- **agents/alarm_analysis.py**: 4유형 알람 분석 + root cause
- **agents/study.py**: ops→study 격리 What-if
- **agents/insight.py**: APScheduler 능동형 6종 (Phase 4)
- **hitl/**: Priority Queue + 승인 위젯
- **context/**: AgentContext + CallGuard + SessionSummarizer

## 절대 규칙
1. LLM이 수치를 직접 생성하면 Pydantic 검증에서 거부
2. Tool 호출 결과만으로 수치 응답 생성
3. 조회/이동 → HOTL (자동), 조치/추천 → HITL (승인)
4. Evidence chain 항상 포함
5. CallGuard: depth ≤ 5, 동일 에이전트 연속 2회 제한
6. structured_facts (최근 20건 수치) 절대 압축 금지
7. snapshot_ts 모든 AIResponse에 필수

## PydanticAI 패턴
```python
from pydantic_ai import Agent, RunContext

agent = Agent(
    model="qwen2.5:7b",  # 타겟 SLM (개발 시 Claude API)
    system_prompt="한국 전력계통 운영 전문 AI...",
    result_type=AIResponse,
)

@agent.tool
async def query_app(ctx: RunContext[AgentContext], app: str, mode: str) -> SEResult:
    """EMS 앱 결과를 조회합니다."""
    result = await ctx.deps.gateway.call_tool("query_app", {"app": app, "mode": mode})
    ctx.deps.evidence_chain.append({"tool": "query_app", "result": result.summary})
    return result
```

## AgentContext 스키마
```python
class AgentContext(BaseModel):
    session_id: str
    current_screen: str
    structured_facts: list[StructuredFact]  # 최근 20건 FIFO, 압축 금지
    evidence_chain: list[EvidenceItem]       # 최근 5단계 압축 금지
    history_summary: str
    active_alarms: list[AlarmEvent]
    mode: Literal["HITL", "HOTL"]

class StructuredFact(BaseModel):
    entity_id: str      # bus_003
    attribute: str       # voltage_pu
    value: float         # 0.92
    unit: str            # pu
    source_app: str      # SE
    calc_ts: datetime
```

## HITL Priority Queue (Phase 2 기본 → Phase 4 고도화)
- CRITICAL: 타임아웃 600s
- HIGH: 300s
- MEDIUM: 180s
- LOW: 120s
- 동시 표시 최대 3건
- 동일 설비 중복 → 최신 건만 유지
- 3건 연속 타임아웃 → 운영자 부재 경고

## Phase 2 게이트
- **게이트 D**: "계통 상태 요약해줘" → 오케스트레이터 → NL2App → SE → 결과+Evidence
- **게이트 E**: "5번 CB 개방하면?" → 계통검토 → study: 격리 → 결과 → HITL
- **게이트 F**: "N-1 복구 절차" → RAG → SOP 검색 → 조항번호+본문

## 테스트 기준
- Intent 분류 정확도 ≥ 80% (50건 시나리오)
- Tool 선택 정확도 ≥ 85%
- Evidence chain 포함율 100%
- HITL/HOTL 분류 정확도 100%
