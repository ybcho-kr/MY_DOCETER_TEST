# API Gateway — MCP Protocol

## 이 디렉토리의 역할
AI Agent(Layer 2) ↔ EMS Digital Twin(Layer 1) 사이의 표준화 허브.
MCP Protocol 기반. read_only 강제. Evidence chain 생성. Provenance 로그.

## v5.1 Phase 2에서 구현

## 핵심 기능
1. **MCP Protocol**: JSON-RPC 기반 Tool 호출 프로토콜
2. **read_only 강제**: ops: 네임스페이스 write = 403 차단
3. **Evidence chain**: 모든 Tool 호출에 대해 자동 생성
4. **Provenance 로그**: {ts, agent_id, tool, result_hash} JSONL 기록
5. **Pydantic 검증**: 입출력 스키마 자동 검증

## Tool 등록 규칙
- read_only 미설정 Tool → 등록 거부
- study: 전용 Tool만 write 허용 (create_study, run_study, run_shortcircuit)
- 모든 Tool에 Pydantic 입출력 스키마 필수

## 22개 MCP Tool (요약)
- NL Navigation: navigate_to, get_screen_list, highlight_elements
- NL2App: query_app, get_powerflow_violations, compare_se, get_agc_status
- 인사이트: get_forecast, get_risk_assessment, run_grid_health_check
- RAG: search_documents, query_db
- 알람: get_active_alarms, cluster_alarms
- 계통검토: create_study(write), run_study(write), run_shortcircuit(write)
- TP: run_acopf, run_n1_contingency, run_vsa
- SCADA: get_topology
- SE: get_se_observability

## 보안 정책
- AI Agent → ops: write 시도 = HTTP 403 + 감사 로그
- study: write 허용 (TTL 1800s 자동 삭제)
- Provenance 로그 append-only
- 모든 Tool 호출 JSONL 기록

## 에러 처리
- 403: ops: write 차단
- 404: Tool not found
- 422: Pydantic 검증 실패
- 500: Tool 실행 오류 (3회 재시도 후 명시 오류)
- 501: 미구현 Tool

## Evidence Chain 구조
```json
{
  "tool_called": "query_app",
  "params": {"app": "SE", "mode": "snapshot"},
  "result_summary": "SE latest retrieved",
  "snapshot_ts": "2025-03-25T14:23:08+09:00"
}
```

## 필수 규칙
1. 모든 Tool 호출에 Evidence chain 자동 생성
2. read_only 미설정 Tool 등록 거부
3. ops: write = 403 무조건 차단
4. Provenance 로그 JSONL append-only
5. Pydantic 스키마 검증 실패 = 422 반환
