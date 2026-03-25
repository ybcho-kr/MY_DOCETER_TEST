# AI-EMS v5.1 MCP Gateway 인터페이스 설계

## 1. 개요

AI-EMS v5.1의 핵심 아키텍처는 **MCP(Model Context Protocol) 기반의 API Gateway**로서, AI 에이전트와 EMS(에너지관리시스템) 간의 표준화된 인터페이스 역할을 한다.

### 1.1 핵심 목표
- **표준화**: JSON-RPC 기반 MCP Protocol 도입으로 모든 AI ↔ EMS 상호작용 통일
- **보안**: read_only 강제 정책, AI write 차단, 구조화된 권한 관리
- **추적성**: Evidence Chain 자동 생성으로 모든 Tool 호출의 완전성, 진정성, 원산지 검증
- **확장성**: 22개 Tool 통합 허브로 기존 EMS 시스템과의 유연한 연계

### 1.2 MCP Protocol 선택 이유
- JSON-RPC 2.0 기반 경량화
- Tool 호출 및 리소스 접근의 표준 방식
- Evidence 및 Provenance 메타데이터 자동 생성
- AI 에이전트 간 일관된 인터페이스

---

## 2. Gateway 아키텍처

### 2.1 시스템 구성도
```
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent Layer                             │
│  (NL Navigation, NL2App, Insights, RAG, Alarms, TP, SCADA)   │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼────────────┐  ┌────────▼─────────────┐
│  MCP Gateway       │  │  Tool Registry       │
│  (FastAPI)         │  │  (22 Tool 메타)      │
│  - JSON-RPC        │  │  - read_only 검증    │
│  - Pydantic        │  │  - namespace 관리    │
│  - Evidence Gen    │  │  - endpoint 매핑     │
│  - Provenance Log  │  │  - schema 저장       │
└───────┬────────────┘  └────────┬─────────────┘
        │                         │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼─────────┐     ┌────────▼──────────┐
│  Layer 1        │     │  Layer 2 / Ext    │
│  (SE, OPF,      │     │  (Obs, Study,     │
│   VSA, N-1CA)   │     │   SCA)             │
└─────────────────┘     └───────────────────┘
```

### 2.2 Gateway 핵심 컴포넌트

#### 2.2.1 FastAPI 서버
```python
# 주요 엔드포인트
POST /rpc                    # MCP JSON-RPC 요청
GET  /tools                  # Tool 목록 조회
GET  /tools/{tool_name}      # 특정 Tool 상세
GET  /evidence/{session_id}  # Evidence Chain 조회
GET  /provenance/audit       # Provenance 로그 조회
```

#### 2.2.2 Pydantic 스키마 검증
- 모든 Tool 호출 입력값 자동 검증
- Tool 결과값 스키마 검증
- Type hint 기반 자동 문서화
- 검증 실패 시 422 Unprocessable Entity 반환

#### 2.2.3 Evidence Chain 생성기
- Tool 호출 시점, 파라미터, 결과를 자동 캡처
- Result hash (SHA-256) 계산
- Snapshot timestamp 기록
- RAG 참조 정보 추출
- 결과 요약문(result_summary) 자동 생성

#### 2.2.4 Provenance 로거
- JSONL 형식의 구조화 로그
- 타임스탬프, 에이전트 ID, Tool 이름, 결과 해시 기록
- 감시 및 감사 추적용 중앙 로그

---

## 3. MCP Tool Registry — 22개 Tool 전체 목록

### 3.1 Tool 분류별 목록

| 카테고리 | Tool 이름 | 읽기전용 | 에이전트 | 설명 |
|---------|----------|---------|---------|------|
| **NL 네비게이션** | navigate_to | ✓ | NL Nav | 화면 이동 |
| | get_screen_list | ✓ | NL Nav | 화면 목록 조회 |
| | highlight_elements | ✓ | NL Nav | UI 요소 강조 표시 |
| **NL2App 쿼리** | query_app | ✓ | NL2App | 앱 결과 조회 (SE, OPF 등) |
| | get_powerflow_violations | ✓ | NL2App | 전력흐름 위반 목록 |
| | compare_se | ✓ | NL2App | 상태추정 비교 분석 |
| | get_agc_status | ✓ | NL2App | AGC(자동발전제어) 현황 |
| **인사이트** | get_forecast | ✓ | Insights | 부하/재생에너지 예측 |
| | get_risk_assessment | ✓ | Insights | 리스크 평가 결과 |
| | run_grid_health_check | ✓ | Insights | 계통 건전성 진단 |
| **RAG** | search_documents | ✓ | RAG | 벡터 검색 (운영 매뉴얼) |
| | query_db | ✓ | RAG | 자연어→SQL 변환 및 조회 |
| **알람 관리** | get_active_alarms | ✓ | Alarms | 활성 알람 목록 |
| | cluster_alarms | ✓ | Alarms | 알람 클러스터링 분석 |
| **검토 (격리 환경)** | create_study | study전용 | Review | Study 세션 생성 |
| | run_study | study전용 | Review | 격리 시뮬레이션 실행 |
| | run_shortcircuit | study전용 | Review | 단락 회로 분석 |
| **TP (분석)** | run_acopf | ✓ | TP | AC OPF 실행 |
| | run_n1_contingency | ✓ | TP | N-1 응급 상황 분석 |
| | run_vsa | ✓ | TP | 전압 안정성 분석 |
| **SCADA** | get_topology | ✓ | SCADA | 계통 토폴로지 조회 |
| **SE** | get_se_observability | ✓ | SE | 상태추정 관측성 결과 |

### 3.2 Tool 상세 규격

#### 3.2.1 query_app
- **설명**: EMS 애플리케이션 결과 조회
- **파라미터**:
  - `app` (str): "SE", "OPF", "VSA", "N1CA" 중 하나
  - `mode` (str): "snapshot" (실시간) 또는 "historical" (과거)
  - `timestamp` (optional, str): ISO 8601 형식
- **응답**: 해당 앱의 실행 결과 (케이스별 다름)
- **read_only**: ✓

#### 3.2.2 get_powerflow_violations
- **설명**: 현재 계통의 전력흐름 제약 위반 목록
- **파라미터**: 없음
- **응답**:
  ```json
  {
    "violations": [
      {"element": "LINE_001", "type": "MVA_LIMIT", "value": 250.5, "limit": 250.0},
      ...
    ]
  }
  ```
- **read_only**: ✓

#### 3.2.3 compare_se
- **설명**: 두 시점의 상태추정 결과 비교
- **파라미터**:
  - `timestamp1` (str): ISO 8601
  - `timestamp2` (str): ISO 8601
  - `elements` (optional, list): 비교할 요소 (기본: 모든 요소)
- **응답**: 시간대별 상태 변화
- **read_only**: ✓

#### 3.2.4 get_agc_status
- **설명**: 자동발전제어(AGC) 현황 조회
- **파라미터**: 없음
- **응답**:
  ```json
  {
    "agc_active": true,
    "target_frequency": 60.0,
    "current_frequency": 59.98,
    "available_reserve": 2500.0,
    "participants": [{"plant": "GEN_001", "mw": 100.0}, ...]
  }
  ```
- **read_only**: ✓

#### 3.2.5 search_documents
- **설명**: 벡터 기반 문서 검색
- **파라미터**:
  - `query` (str): 자연어 질문
  - `doc_type` (optional, str): "manual", "sop", "log"
  - `top_k` (optional, int): 반환할 문서 수 (기본: 5)
- **응답**: 관련도 순서로 정렬된 문서 목록
- **read_only**: ✓

#### 3.2.6 query_db
- **설명**: 자연어를 SQL로 변환하여 데이터베이스 조회
- **파라미터**:
  - `question` (str): 자연어 질문
  - `table_context` (optional, str): 스키마 힌트
- **응답**: SQL 실행 결과
- **read_only**: ✓

#### 3.2.7 create_study
- **설명**: 격리된 연구 세션 생성
- **파라미터**:
  - `study_name` (str): 세션 이름
  - `base_case` (str): 초기 케이스 (기본: "snapshot")
- **응답**: `study_id` 반환
- **read_only**: ✗ (study 전용)
- **권한**: study 네임스페이스만 접근 가능

#### 3.2.8 run_study
- **설명**: Study 내에서 격리된 시뮬레이션 실행
- **파라미터**:
  - `study_id` (str)
  - `action` (str): "powerflow", "sc", "vsa" 등
  - `params` (dict): 분석 파라미터
- **응답**: 분석 결과
- **read_only**: ✗ (study 전용)

#### 3.2.9 run_shortcircuit
- **설명**: Study 내 단락 회로 분석
- **파라미터**:
  - `study_id` (str)
  - `bus_number` (int): 대상 모선 번호
- **응답**: 단락 전류, 지속시간 등
- **read_only**: ✗ (study 전용)

#### 3.2.10 run_acopf
- **설명**: AC OPF(최적전력흐름) 실행
- **파라미터**:
  - `objective` (str): "cost", "loss", "emission"
  - `constraints` (optional, list): 추가 제약
- **응답**: 최적화 결과 (발전량, 전압, 탭)
- **read_only**: ✓

#### 3.2.11 run_n1_contingency
- **설명**: N-1 응급 상황 분석 (모든 선로 탈락)
- **파라미터**:
  - `elements` (optional, list): 특정 요소만 분석
- **응답**: 각 탈락 시나리오별 위반 목록
- **read_only**: ✓

#### 3.2.12 run_vsa
- **설명**: 전압 안정성 분석
- **파라미터**:
  - `mode` (str): "pv_curve" 또는 "qv_curve"
  - `load_bus` (int): 대상 모선
- **응답**: 안정성 한계, 마진 등
- **read_only**: ✓

#### 3.2.13 get_topology
- **설명**: 실시간 계통 토폴로지 조회
- **파라미터**: 없음
- **응답**:
  ```json
  {
    "buses": [...],
    "branches": [...],
    "generators": [...],
    "loads": [...]
  }
  ```
- **read_only**: ✓

#### 3.2.14 get_se_observability
- **설명**: 상태추정 관측성 분석 결과
- **파라미터**: 없음
- **응답**:
  ```json
  {
    "observability_rank": 85,
    "unobservable_islands": [],
    "bad_data_indicators": [...]
  }
  ```
- **read_only**: ✓

---

## 4. 보안 정책

### 4.1 read_only 정책

모든 Tool 등록 시 `read_only` 필드 필수 설정:
- **read_only: true** (21개): AI 에이전트는 조회만 가능, write 차단
- **read_only: false** (1개): study 전용, study 네임스페이스만 허용

**정책 규칙**:
1. read_only 미설정 Tool은 등록 거부 (400 Bad Request)
2. read_only: true인 Tool에 대한 write 시도 → 403 Forbidden
3. read_only: false인 Tool은 자동으로 `study:` 네임스페이스로 격리

### 4.2 AI write 차단 정책

```
AI Agent → Tool 호출 → Gateway 검증
                       ↓
                   read_only?
                   ↙         ↘
                YES           NO
                 ↓             ↓
              허용           study: NS?
                            ↙       ↘
                           YES       NO
                            ↓         ↓
                          허용      403 차단
```

**403 차단 메시지**:
```json
{
  "error": "ForbiddenError",
  "message": "Write not allowed for AI agents. Tool 'run_study' requires 'study:' namespace",
  "tool": "run_study",
  "policy": "AI write restriction"
}
```

### 4.3 네임스페이스 격리

- **ops:** 실시간 계통 운영 (AI read-only)
- **study:** 격리된 연구 환경 (AI + 인증된 사용자 write)
- **admin:** 시스템 관리 (AI 접근 불가)

### 4.4 Provenance 로깅

모든 Tool 호출에 대해 다음을 기록:
```json
{
  "ts": "2025-03-25T14:23:08.123Z",
  "agent_id": "nl2app",
  "tool": "query_app",
  "namespace": "ops",
  "result_hash": "sha256:abc1234567890def",
  "params_hash": "sha256:xyz0987654321",
  "execution_time_ms": 125,
  "error": null
}
```

**감시 목적**:
- Tool 호출 추적
- 이상 행동 탐지 (반복된 실패, 비정상 패턴)
- 규정 준수 감시

---

## 5. Tool 호출 프로토콜

### 5.1 요청 형식 (JSON-RPC 2.0)

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "tool_name": "query_app",
    "arguments": {
      "app": "SE",
      "mode": "snapshot"
    },
    "session_id": "sess-abc123",
    "agent_id": "nl2app"
  },
  "id": 1
}
```

**필수 필드**:
- `jsonrpc`: "2.0"
- `method`: "tools/call"
- `params.tool_name`: Tool 이름 (정확한 대소문자)
- `params.arguments`: Tool별 파라미터 (스키마 검증)
- `params.session_id`: AI 세션 ID (추적용)
- `params.agent_id`: 호출 에이전트 (audit trail)

### 5.2 응답 형식

#### 5.2.1 성공 응답 (200 OK)

```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": "SE latest snapshot retrieved",
    "data": {
      "case_id": "20250325_143000",
      "bus_voltages": [...],
      "branch_flows": [...]
    }
  },
  "evidence": {
    "tool_called": "query_app",
    "params": {
      "app": "SE",
      "mode": "snapshot"
    },
    "result_summary": "SE case 20250325_143000 with 100 buses, 150 branches",
    "snapshot_ts": "2025-03-25T14:30:00+09:00",
    "result_hash": "sha256:abc1234567890def..."
  },
  "provenance": {
    "ts": "2025-03-25T14:23:08.123Z",
    "agent_id": "nl2app",
    "tool": "query_app",
    "namespace": "ops",
    "result_hash": "sha256:abc1234567890def...",
    "execution_time_ms": 125
  },
  "id": 1
}
```

#### 5.2.2 에러 응답

**403 Forbidden (write 차단)**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32603,
    "message": "InternalError",
    "data": {
      "error_type": "ForbiddenError",
      "detail": "Write not allowed for AI agents. Tool requires 'study:' namespace",
      "tool": "run_study"
    }
  },
  "id": 1
}
```

**404 Not Found**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32601,
    "message": "MethodNotFound",
    "data": {
      "tool": "query_nonexistent"
    }
  },
  "id": 1
}
```

**422 Unprocessable Entity (스키마 검증 실패)**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32602,
    "message": "InvalidParams",
    "data": {
      "validation_errors": [
        {
          "field": "app",
          "message": "value must be one of ['SE', 'OPF', 'VSA', 'N1CA']",
          "received": "INVALID_APP"
        }
      ]
    }
  },
  "id": 1
}
```

**500 Internal Server Error (Tool 실행 오류)**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32603,
    "message": "InternalError",
    "data": {
      "error_type": "ToolExecutionError",
      "detail": "SE server connection timeout",
      "tool": "query_app",
      "retry_count": 3,
      "retry_exhausted": true
    }
  },
  "id": 1
}
```

**501 Not Implemented (미구현 Tool)**:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32603,
    "message": "InternalError",
    "data": {
      "error_type": "NotImplementedError",
      "detail": "SCA tool not yet available in v5.1",
      "tool": "run_sca"
    }
  },
  "id": 1
}
```

### 5.3 Retry 메커니즘

Tool 실행 오류 발생 시 자동 재시도:
- **최대 재시도**: 3회
- **Backoff 전략**: Exponential (1s, 2s, 4s)
- **재시도 대상**: 5xx, timeout, connection error
- **재시도 제외**: 4xx (클라이언트 오류), 403 (정책 위반)

---

## 6. Evidence Chain 구조

### 6.1 Evidence 메타데이터

모든 AI 응답에는 다음 Evidence 정보를 포함:

```python
class Evidence(BaseModel):
    tool_called: str              # 호출된 Tool 이름
    params: dict                  # 입력 파라미터
    result_summary: str           # 결과 요약 (한 줄)
    snapshot_ts: str              # 데이터 스냅샷 시각 (ISO 8601)
    result_hash: str              # SHA-256 해시
    rag_reference: Optional[str]  # RAG 참조 (있는 경우)
    execution_time_ms: int        # 실행 시간
    data_quality: str             # "good", "fair", "poor"
```

### 6.2 Evidence 적용 예시

**시나리오**: AI가 사용자에게 "지금 계통 상태는 안정적입니다"라고 보고

```json
{
  "response": "지금 계통 상태는 안정적입니다. 모든 선로가 용량 내이고, AGC 예비력이 충분합니다.",
  "evidence_chain": [
    {
      "tool_called": "query_app",
      "params": {"app": "SE", "mode": "snapshot"},
      "result_summary": "SE snapshot 20250325_143000: 100 buses OK, 150 branches within limits",
      "snapshot_ts": "2025-03-25T14:30:00+09:00",
      "result_hash": "sha256:abc..."
    },
    {
      "tool_called": "get_agc_status",
      "result_summary": "AGC active, reserve 2500 MW available",
      "snapshot_ts": "2025-03-25T14:30:00+09:00",
      "result_hash": "sha256:def..."
    },
    {
      "tool_called": "get_powerflow_violations",
      "result_summary": "Zero violations detected",
      "snapshot_ts": "2025-03-25T14:30:00+09:00",
      "result_hash": "sha256:ghi..."
    }
  ]
}
```

### 6.3 Evidence Chain 검증

사용자 또는 감시자가 AI 응답 검증 시:
1. 각 tool_called의 result_hash 확인
2. Provenance 로그에서 동일 hash 조회
3. snapshot_ts 재확인
4. result_summary와 실제 Tool 결과 비교

---

## 7. Tool 등록 스키마

### 7.1 Tool 등록 형식

```json
{
  "tool_name": "query_app",
  "endpoint": "http://layer1:8001/se/latest",
  "description": "EMS 애플리케이션 결과 조회 (SE, OPF, VSA, N-1 CA)",
  "read_only": true,
  "agent_targets": ["NL2App", "Insights"],
  "schema": {
    "input": {
      "type": "object",
      "properties": {
        "app": {
          "type": "string",
          "enum": ["SE", "OPF", "VSA", "N1CA"],
          "description": "EMS 애플리케이션 선택"
        },
        "mode": {
          "type": "string",
          "enum": ["snapshot", "historical"],
          "description": "조회 모드",
          "default": "snapshot"
        },
        "timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "과거 데이터 조회 시간 (ISO 8601)"
        }
      },
      "required": ["app"]
    },
    "output": {
      "type": "object",
      "properties": {
        "status": {"type": "string"},
        "data": {
          "type": "object",
          "description": "앱별 결과"
        }
      }
    }
  },
  "namespace": "ops",
  "timeout_ms": 5000,
  "retry_max": 3
}
```

### 7.2 Tool 등록 API

**POST /admin/tools/register**

```bash
curl -X POST http://localhost:8000/admin/tools/register \
  -H "Content-Type: application/json" \
  -d @tool_definition.json
```

**응답**:
```json
{
  "tool_id": "tool_query_app_001",
  "registered_at": "2025-03-25T14:00:00Z",
  "status": "active",
  "schema_version": "1.0"
}
```

### 7.3 Tool 검증 규칙

Tool 등록 전 Gateway에서 자동 검증:

1. **read_only 필드 필수**: 미설정 시 400 Bad Request
2. **endpoint 유효성**: HTTP/HTTPS URL 형식
3. **schema 완전성**: input/output 모두 정의
4. **timeout 범위**: 100ms ~ 60,000ms
5. **agent_targets 유효성**: 등록된 에이전트만

---

## 8. 에러 처리

### 8.1 HTTP 상태 코드 매핑

| HTTP 코드 | 설명 | 예시 |
|----------|------|------|
| 200 OK | Tool 실행 성공 | 쿼리 반환 |
| 400 Bad Request | 요청 형식 오류 | 필드 누락 |
| 403 Forbidden | AI write 차단 또는 권한 부족 | ops: write 시도 |
| 404 Not Found | Tool 미존재 | tool_name 오류 |
| 422 Unprocessable Entity | 스키마 검증 실패 | 파라미터 타입 오류 |
| 429 Too Many Requests | 속도 제한 | 과도한 호출 |
| 500 Internal Server Error | Tool 실행 오류 (재시도 후) | SE 서버 다운 |
| 501 Not Implemented | 미구현 Tool | SCA stub |
| 503 Service Unavailable | Gateway 과부하 | CPU/메모리 부족 |

### 8.2 재시도 정책

**자동 재시도 대상**:
- 500 Internal Server Error
- 503 Service Unavailable
- Connection timeout
- EOF (연결 끊김)

**재시도 제외**:
- 4xx (클라이언트 오류)
- 403 (정책 위반)
- 429 (속도 제한, 하지만 나중에 재시도 가능)

**Backoff 계산**:
```
wait_time = 2^(retry_count - 1) + random(0, 1)
retry_1: ~1s
retry_2: ~2-3s
retry_3: ~4-5s
```

### 8.3 에러 응답 구조

```python
class ErrorResponse(BaseModel):
    error: str                    # "ForbiddenError", "ValidationError" 등
    message: str                  # 사용자 친화적 메시지
    tool: Optional[str]           # Tool 이름 (해당 시)
    details: Optional[dict]       # 추가 디버깅 정보
    timestamp: str                # ISO 8601
    request_id: str               # 추적용 ID
```

---

## 9. NL→지도(Map) MCP Tool 상세 설계 (7종)

AI 에이전트가 지도 인터페이스를 제어하는 도구 모음. 모두 **read_only: true**, 시각화 전용.

### 9.1 map_fly_to

**목적**: 지도 중심을 특정 좌표로 이동 (카메라 비행)

**파라미터**:
```python
class MapFlyToInput(BaseModel):
    latitude: float               # 위도 (-90 ~ 90)
    longitude: float              # 경도 (-180 ~ 180)
    zoom: Optional[int]           # 줌 레벨 (0 ~ 20, 기본: 자동)
    duration_ms: Optional[int]    # 애니메이션 시간 (기본: 1000)
    pitch: Optional[float]        # 기울기 (0 ~ 60, 기본: 0)
    bearing: Optional[float]      # 방향 (0 ~ 360, 기본: 0)
```

**응답**:
```json
{
  "status": "map_fly_to_executed",
  "center": {"lat": 37.5665, "lng": 126.9780},
  "zoom": 12,
  "viewport_bounds": {
    "north": 37.6,
    "south": 37.5,
    "east": 127.0,
    "west": 126.95
  }
}
```

**사용 예시**:
```
사용자: "서울 전역 지도를 보여줘"
AI → map_fly_to(latitude=37.5665, longitude=126.9780, zoom=11)
→ 지도가 서울 중심으로 부드럽게 이동
```

**구현 세부사항**:
- Mapbox GL JS의 `flyTo()` 메서드 연동
- 좌표 검증 (범위 체크)
- 줌 레벨 자동 조정 (기본값 논리)

---

### 9.2 map_set_filter

**목적**: 지도 표시 요소 필터링 (선로, 발전기, 모선 등)

**파라미터**:
```python
class MapSetFilterInput(BaseModel):
    element_type: str             # "lines", "buses", "generators", "loads", "all"
    filters: dict                 # 필터 규칙
    operator: Optional[str]       # "and", "or" (기본: "and")
    clear_previous: Optional[bool] # 이전 필터 삭제 (기본: true)
```

**filters 예시**:
```json
{
  "voltage_level": {"$in": [110, 220, 345]},
  "status": "in_service",
  "loading_percent": {"$gt": 80}
}
```

**응답**:
```json
{
  "status": "filter_applied",
  "element_type": "lines",
  "matched_count": 245,
  "visible_count": 245,
  "filter_expression": "voltage_level IN [110, 220, 345] AND status='in_service' AND loading>80%"
}
```

**사용 예시**:
```
사용자: "345kV 선로 중 부하가 80% 이상인 것만 표시"
AI → map_set_filter(
  element_type="lines",
  filters={"voltage_level": {"$in": [345]}, "loading_percent": {"$gt": 80}}
)
→ 지도에서 해당 조건의 선로만 강조
```

**구현 세부사항**:
- MongoDB 스타일의 필터 표현식
- Mapbox 레이어 필터링
- 실시간 요소 카운팅

---

### 9.3 map_highlight

**목적**: 특정 요소를 지도에서 강조 표시 (색상, 굵기 변경)

**파라미터**:
```python
class MapHighlightInput(BaseModel):
    elements: List[str]           # 요소 ID 목록 ["BUS_001", "LINE_002", ...]
    color: Optional[str]          # 16진수 색상 (기본: "#FF0000")
    style: Optional[str]          # "solid", "dashed", "dotted"
    width: Optional[float]        # 선로 폭 (기본: 3)
    opacity: Optional[float]      # 투명도 (0 ~ 1, 기본: 1.0)
    label_show: Optional[bool]    # ID 라벨 표시 (기본: true)
    duration_ms: Optional[int]    # 강조 지속 시간 (밀리초, 0=무한)
```

**응답**:
```json
{
  "status": "highlight_applied",
  "highlighted_count": 3,
  "elements": [
    {"id": "BUS_001", "type": "bus", "lat": 37.5, "lng": 126.9},
    {"id": "LINE_002", "type": "line", "color": "#FF0000"}
  ],
  "highlight_duration_ms": 0
}
```

**사용 예시**:
```
사용자: "LINE_001과 BUS_002를 빨강으로 강조해줄래?"
AI → map_highlight(
  elements=["LINE_001", "BUS_002"],
  color="#FF0000",
  width=5
)
→ 두 요소가 굵은 빨간색으로 표시됨
```

**구현 세부사항**:
- 레이어 선택자 기반 스타일 변경
- 상태 추적 (강조 목록 관리)
- 시간 기반 자동 해제 (duration_ms > 0)

---

### 9.4 map_set_mode

**목적**: 지도 표시 모드 전환

**파라미터**:
```python
class MapSetModeInput(BaseModel):
    mode: str                     # "heat", "topology", "3d", "compare"
    view_options: Optional[dict]  # 모드별 옵션
```

**모드별 설명**:

| 모드 | 설명 | view_options |
|------|------|-------------|
| heat | 선로 부하 히트맵 | `{"scale": "linear\|log", "colormap": "viridis\|plasma"}` |
| topology | 토폴로지 다이어그램 | `{"layout": "force\|tree\|circular"}` |
| 3d | 3D 계통도 | `{"perspective": "aerial\|side", "extrude_height": 0-100}` |
| compare | 두 시나리오 비교 | `{"left_case": "case_id", "right_case": "case_id"}` |

**응답**:
```json
{
  "status": "mode_changed",
  "mode": "heat",
  "applied_options": {
    "scale": "linear",
    "colormap": "viridis"
  },
  "layers_visible": ["heat_layer", "topology_overlay"]
}
```

**사용 예시**:
```
사용자: "선로 부하를 히트맵으로 보여줄래?"
AI → map_set_mode(mode="heat", view_options={"scale": "linear"})
→ 지도가 히트맵 모드로 전환, 선로가 부하 수준별 색상으로 표시
```

**구현 세부사항**:
- 레이어 그룹 관리
- 모드별 초기화 로직
- 성능 최적화 (3D 모드에서 LOD 적용)

---

### 9.5 map_set_layer

**목적**: 특정 레이어의 가시성, 투명도, 스타일 조정

**파라미터**:
```python
class MapSetLayerInput(BaseModel):
    layer_id: str                 # "lines_110kv", "buses", "weather_overlay" 등
    visible: Optional[bool]       # 표시 여부
    opacity: Optional[float]      # 투명도 (0 ~ 1)
    paint: Optional[dict]         # Mapbox paint 속성
    layout: Optional[dict]        # Mapbox layout 속성
    z_index: Optional[int]        # 레이어 순서 (-10 ~ 10)
```

**응답**:
```json
{
  "status": "layer_updated",
  "layer_id": "lines_110kv",
  "changes": {
    "visible": true,
    "opacity": 0.8,
    "z_index": 5
  }
}
```

**사용 예시**:
```
사용자: "110kV 선로를 반투명으로 줄여"
AI → map_set_layer(layer_id="lines_110kv", opacity=0.3)
→ 110kV 선로가 희미해짐
```

**구현 세부사항**:
- Mapbox layer 직접 조정
- 레이어 존재 검증
- z-index 충돌 방지 로직

---

### 9.6 map_fit_bounds

**목적**: 지도 뷰를 특정 영역에 맞춤 (모든 선택 요소 표시)

**파라미터**:
```python
class MapFitBoundsInput(BaseModel):
    elements: Optional[List[str]]  # 요소 ID 목록 (없으면 현재 필터 적용)
    padding_px: Optional[int]      # 여백 픽셀 (기본: 50)
    duration_ms: Optional[int]     # 애니메이션 시간 (기본: 1000)
    max_zoom: Optional[int]        # 최대 줌 레벨 (기본: 20)
```

**응답**:
```json
{
  "status": "bounds_fitted",
  "bounds": {
    "north": 37.8,
    "south": 37.2,
    "east": 127.2,
    "west": 126.7
  },
  "fitted_elements": 45,
  "final_zoom": 11,
  "center": {"lat": 37.5, "lng": 126.95}
}
```

**사용 예시**:
```
사용자: "위반이 있는 모든 선로를 한 화면에 보여"
AI → map_fit_bounds(elements=[violations list])
→ 지도가 자동 축소/이동하여 모든 위반 선로가 보임
```

**구현 세부사항**:
- 좌표 바운딩박스 계산
- Mapbox `fitBounds()` 사용
- 극값(pole) 처리

---

### 9.7 map_show_comparison

**목적**: 두 시나리오를 나란히 비교

**파라미터**:
```python
class MapShowComparisonInput(BaseModel):
    left_case: str                # 왼쪽 케이스 ID
    right_case: str               # 오른쪽 케이스 ID
    diff_mode: Optional[str]      # "highlight_changes", "color_diff", "side_by_side"
    elements_to_compare: Optional[List[str]]  # 비교할 요소 (기본: 모두)
```

**응답**:
```json
{
  "status": "comparison_shown",
  "left_case": "case_20250325_140000",
  "right_case": "case_20250325_143000",
  "diff_mode": "highlight_changes",
  "changes_summary": {
    "lines_changed": 12,
    "bus_voltage_deltas": [{"bus": "BUS_001", "delta_pu": 0.02}, ...],
    "new_violations": 3,
    "resolved_violations": 2
  }
}
```

**사용 예시**:
```
사용자: "지금과 30분 전 상태를 비교해줄래?"
AI → map_show_comparison(
  left_case="case_20250325_130000",
  right_case="case_20250325_143000",
  diff_mode="highlight_changes"
)
→ 분할 화면: 좌측(30분 전), 우측(현재), 변화 요소는 빨강으로 강조
```

**구현 세부사항**:
- 분할 화면 렌더링
- 케이스별 상태 조회
- 차분(diff) 계산 및 시각화

---

## 10. MCP Gateway 구현 로드맵

### 10.1 Phase 1 (4주)
- FastAPI Gateway 기본 구조
- JSON-RPC 라우터 구현
- 5개 Tool 통합 (query_app, get_agc_status, get_powerflow_violations, run_acopf, get_topology)
- Pydantic 스키마 검증

### 10.2 Phase 2 (4주)
- Evidence Chain 생성 로직
- Provenance 로거 (JSONL)
- 나머지 17개 Tool 통합
- Tool Registry 완성

### 10.3 Phase 3 (3주)
- 지도 Tool 7개 (map_fly_to 등)
- AI 에이전트 통합 테스트
- 성능 튜닝 (caching, connection pooling)

### 10.4 Phase 4 (2주)
- 보안 감시 (이상 탐지)
- 문서화 완성
- Production 배포

---

## 11. 부록: Tool 스키마 완전 정의

### 11.1 주요 데이터 타입

```python
# 공통 모델
class ToolRequest(BaseModel):
    tool_name: str
    arguments: dict
    session_id: str
    agent_id: str

class ToolResponse(BaseModel):
    result: dict
    evidence: Evidence
    provenance: Provenance

class Evidence(BaseModel):
    tool_called: str
    params: dict
    result_summary: str
    snapshot_ts: str
    result_hash: str
    rag_reference: Optional[str]
    execution_time_ms: int
    data_quality: str

class Provenance(BaseModel):
    ts: str
    agent_id: str
    tool: str
    namespace: str
    result_hash: str
    execution_time_ms: int
    error: Optional[str]

# SE 결과 (query_app 응답)
class SEResult(BaseModel):
    case_id: str
    timestamp: str
    convergence_status: str  # "converged", "diverged"
    bus_count: int
    branch_count: int
    bus_data: List[dict]
    branch_data: List[dict]

# 위반 정보
class Violation(BaseModel):
    element_id: str
    element_type: str  # "line", "bus", "transformer"
    violation_type: str  # "MVA_LIMIT", "VOLTAGE_LIMIT", "FREQUENCY"
    value: float
    limit: float
    severity: str  # "warning", "critical"

# AGC 상태
class AGCStatus(BaseModel):
    agc_active: bool
    target_frequency: float
    current_frequency: float
    available_reserve: float
    participants: List[dict]
```

### 11.2 Tool 호출 타임라인 예시

```
[14:23:00.000] AI 에이전트: "현재 계통 상태 확인"
              → map_fly_to(37.5665, 126.9780)
              → query_app(app="SE", mode="snapshot")
              → get_powerflow_violations()
              → get_agc_status()

[14:23:00.100] Gateway: SE 스냅샷 요청
[14:23:00.125] Layer 1: SE 반환 (hash: abc123...)
[14:23:00.125] Gateway: Evidence 생성 및 Provenance 기록

[14:23:00.200] Gateway: 위반 쿼리 요청
[14:23:00.225] Layer 1: 위반 목록 반환 (hash: def456...)

[14:23:00.300] Gateway: AGC 상태 요청
[14:23:00.325] Layer 1: AGC 정보 반환 (hash: ghi789...)

[14:23:00.325] Gateway: 모든 응답 수집 완료
              → 최종 Evidence Chain 생성
              → JSON-RPC 응답 반환

[14:23:00.350] AI 에이전트: "계통은 안정적입니다. [Evidence Chain 포함]"
```

---

## 12. 결론

AI-EMS v5.1의 MCP Gateway는 다음을 실현한다:

1. **표준화**: JSON-RPC 2.0 기반 모든 AI ↔ EMS 상호작용 통일
2. **보안**: read_only 정책과 네임스페이스 격리로 write 차단
3. **추적성**: Evidence Chain과 Provenance 로그로 완전한 감시 추적
4. **확장성**: 22개 Tool Registry로 기존 시스템과 유연한 연계

이 설계는 **AI 에이전트의 신뢰성, 투명성, 감시성**을 동시에 확보하는 현대적 에너지 관리 시스템의 토대가 된다.
