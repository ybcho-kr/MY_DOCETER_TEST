# AI-EMS v5.1 통합 아키텍처 설계

## 1. 개요

### 프로젝트 목적
전력 EMS(에너지 관리 시스템) 운영을 자연어 기반 agentic AI로 지원하는 한국 실계통 기반 프로토타입

### v5.0 → v5.1 핵심 변경사항

| 변경 항목 | 내용 |
|---------|------|
| **Phase 1 범위 축소** | 12개 체크항목 → MDP(최소 동작 프로토타입) 3개 게이트 + 보너스 |
| **계통 데이터** | IEEE 테스트 계통 → 한국 실계통 .raw 파일 기반 |
| **능동형 AI 인사이트** | Phase 2 → Phase 4로 이동 |
| **시각화 축소** | L1~L5 + 4뷰 → L1~L2(2D GIS) + L4(변전소 SLD)만 |
| **pandapower 한계** | Phase 1 해결 → 이슈 관리 후 Phase 2+ 이후 처리 |

---

## 2. 2-Layer + Gateway 아키텍처

### 전체 구조도

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 2: AI Agent                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Orchestrator (PydanticAI + Intent Classification)   │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  6개 에이전트 시스템                            │  │  │
│  │  │  - NL Navigation (자연어 네비게이션)            │  │  │
│  │  │  - NL2App (자연어→앱 매핑)                     │  │  │
│  │  │  - RAG 4계층 (도메인 지식)                     │  │  │
│  │  │  - 알람분석 에이전트                           │  │  │
│  │  │  - 계통검토 에이전트                           │  │  │
│  │  │  - AI인사이트 에이전트                         │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │  HITL 승인 모듈 (Priority Queue)                      │  │
│  │  AgentContext + CallGuard + SessionSummarizer        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│          API Gateway / Tool Registry (MCP Protocol)         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  read_only 강제 (ops: write = 403 차단)              │  │
│  │  Evidence Chain 생성                                 │  │
│  │  Provenance 로그 (JSONL)                             │  │
│  │  Pydantic 스키마 검증                                │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│              Layer 1: EMS Digital Twin                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SCADA 시뮬레이터 + 토폴로지 프로세서                 │  │
│  │                                                       │  │
│  │  EMS 스텁 (TP/SE/CA/SCA):                            │  │
│  │  - TP (조류계산 / Tri-power EMTP)                    │  │
│  │  - SE (상태추정)                                     │  │
│  │  - CA (상정고장 / Contingency Analysis)              │  │
│  │  - SCA (단락전류 / Short-Circuit Analysis)           │  │
│  │                                                       │  │
│  │  Study 스텁 (격리 실행)                               │  │
│  │  알람 모델 (4유형: LIMIT/STATE/COMM/QUALITY)         │  │
│  │  예측 모듈 (Prophet + Open-Meteo)                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          Application Database Layer                 │  │
│  │  ┌─────────────────┐         ┌──────────────────┐  │  │
│  │  │  Redis 7.x      │         │ PostgreSQL 16    │  │  │
│  │  │  (Hot-Cache)    │         │ + TimescaleDB    │  │  │
│  │  │                 │         │ (Cold-Storage)   │  │  │
│  │  │  - ops:*        │         │                  │  │  │
│  │  │  - study:{sid}:*│         │ 시계열 데이터    │  │  │
│  │  └─────────────────┘         │ 알람/이벤트 로그 │  │  │
│  │                              │ Provenance      │  │  │
│  │                              └──────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

### 2.1 Layer 1: EMS Digital Twin

#### SCADA 시뮬레이터 및 토폴로지 프로세서
- **입력**: 한국 실계통 .raw 파일(PowerWorld Simulator 포맷)
- **기능**: 계통 상태 주기적 갱신, 토폴로지 변화 감지
- **출력**: ops 네임스페이스에 실시간 상태 저장

#### EMS 스텁 (4대 통합)
```
┌─────────────────────────────────────────────────────┐
│              EMS Application Suite                  │
├─────────────────────────────────────────────────────┤
│ TP (Tri-power 조류계산)                             │
│  - AC 최적 전력조류 계산                            │
│  - 수렴성 검토                                      │
├─────────────────────────────────────────────────────┤
│ SE (상태추정)                                       │
│  - 측정값 기반 계통 상태 추정                       │
│  - 관측성 분석                                      │
├─────────────────────────────────────────────────────┤
│ CA (상정고장 분석)                                  │
│  - N-1 선로/기기 탈락 시나리오                      │
│  - 운영 제약 위반 감지                              │
├─────────────────────────────────────────────────────┤
│ SCA (단락전류 계산)                                 │
│  - 각 모선의 단락용량 산정                          │
│  - 차단기 정정 데이터와 비교                        │
└─────────────────────────────────────────────────────┘
```

**v5.1에서의 위치**: Phase 1에 통합되어 기본 제공
- TP + SE: 기본 제공 (ops 기반 실시간)
- CA + SCA: Phase 1 보너스 기능

#### Study 스텁 (격리 실행)
- ops 데이터를 study 네임스페이스에 COPY 후 수정
- 원본 ops 데이터 미접촉 보장
- 실험적 What-if 시뮬레이션 지원

#### 알람 모델 (4유형)
```python
class AlarmType(str, Enum):
    LIMIT = "LIMIT"        # 전압/주파수/전류 범위 초과
    STATE = "STATE"        # 기기 상태 변화 (ON→OFF 등)
    COMM = "COMM"          # 통신 두절/지연
    QUALITY = "QUALITY"    # 데이터 품질 저하

class Alarm(BaseModel):
    alarm_id: str
    type: AlarmType
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    facility_id: str
    description: str
    timestamp: datetime
    cleared_at: Optional[datetime] = None
```

#### 예측 모듈
- **Prophet** (Facebook): 계절성 포함 부하 예측
- **Open-Meteo API**: 기상 데이터 (풍속, 태양광 예측)
- **통합 예측**: 신재생 출력 + 부하 예측
- **위치**: Phase 3 (변경 없음)

### 2.2 API Gateway / Tool Registry (MCP Protocol)

#### 핵심 기능

| 기능 | 설명 |
|------|------|
| **read_only 강제** | ops 네임스페이스 write 요청 → 403 Forbidden |
| **Evidence Chain** | 모든 Tool 호출의 입출력 메타데이터 기록 |
| **Provenance 로그** | JSONL 형식으로 호출 이력 저장 (PostgreSQL) |
| **Pydantic 검증** | 요청/응답 스키마 사전 검증 |

#### MCP Tool 예시 구조
```python
@mcp_tool(name="read_ops_voltage")
async def read_ops_voltage(
    bus_id: str,
    snapshot_ts: Optional[datetime] = None
) -> dict:
    """
    ops 네임스페이스에서 모선 전압 조회

    Args:
        bus_id: 모선 ID (e.g., "BUS001")
        snapshot_ts: 스냅샷 타임스탬프 (미지정 시 최신)

    Returns:
        {
            "bus_id": str,
            "vm_pu": float,
            "va_deg": float,
            "ts": datetime,
            "source": "SCADA" | "SE"
        }
    """
    # 실제 구현...

@mcp_tool(name="write_study_data", read_only=False)
async def write_study_data(
    session_id: str,
    data_key: str,
    value: Any,
    snapshot_ts: datetime
) -> dict:
    """
    study 네임스페이스에 데이터 기록
    Gateway는 ops: 접두사 요청을 자동 거부
    """
    # 실제 구현...
```

### 2.3 Layer 2: AI Agent

#### 오케스트레이터 (Orchestrator)
- **Framework**: PydanticAI v0.7+
- **Intent Classification**: 사용자 입력을 6개 에이전트 중 하나로 라우팅
- **Context Management**: AgentContext를 통한 세션 상태 유지
- **Safety**: CallGuard를 통한 위험 호출 사전 차단

#### 6개 에이전트 시스템

```
┌──────────────────────────────────────────────────────────────────┐
│                    Intent Classification                         │
├──────────────────────────────────────────────────────────────────┤
│  사용자 쿼리 → NLP 분석 → 의도 판정                              │
└──────────────────────────────────────────────────────────────────┘
  ↓         ↓           ↓              ↓            ↓           ↓
 NL Nav   NL2App      RAG         알람분석        계통검토    AI인사이트
  에이전트  에이전트   에이전트       에이전트        에이전트    에이전트
(Navigator)(Mapper) (QA/Search) (Analysis)    (Review)   (Insight)
```

| 에이전트 | 담당 기능 | 예시 입력 |
|---------|---------|---------|
| **NL Navigation** | UI 네비게이션 유도 | "조류계산 보고서 보여줘" |
| **NL2App** | 자연어→실행 매핑 | "선로 THD 측정값 기록" |
| **RAG (4계층)** | 도메인 QA 및 검색 | "N-1에서 비상 발동기 역할?" |
| **알람분석** | 알람 이벤트 해석 | "최근 전압 알람 이유?" |
| **계통검토** | 운영 제약 검토 | "현재 계통 운영 안정?" |
| **AI인사이트** | 능동형 추천 | "예측된 부하 피크?" (Phase 4) |

#### RAG 4계층 구조

```
Layer 4: 알고리즘/기준
├─ 전력계통 운영 기준 (전기공사협회)
├─ IEC 표준 (61970, 61968)
└─ 한전 내부 지침

Layer 3: 한국 계통 특성
├─ 동부/중부/서부/제주 특성
├─ 계절별 운영 패턴
└─ 실계통 신재생 통합 현황

Layer 2: 사용자 계통 정보
├─ .raw 파일 구조
├─ 모선/선로/기기 메타데이터
└─ 알람 임계값 정의

Layer 1: 실시간 운영 데이터
├─ ops 측정값 (SCADA)
├─ TP/SE 계산 결과
└─ 예측 데이터 (Prophet)
```

#### HITL 승인 모듈 (Human-In-The-Loop)

```python
class ApprovalItem(BaseModel):
    request_id: str
    agent_id: str
    action: str  # "write_study_data", "execute_study", etc.
    params: dict
    priority: Literal["CRITICAL", "HIGH", "NORMAL", "LOW"]
    proposed_by: str  # Agent 또는 사용자 ID
    created_at: datetime
    expires_at: datetime
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
    approval_feedback: Optional[str] = None

# Priority Queue 처리
# CRITICAL → 즉시 사용자 알림
# HIGH → 배치 5분 단위
# NORMAL → 배치 1시간 단위
# LOW → 통합 리포트
```

#### AgentContext + CallGuard + SessionSummarizer

```python
class AgentContext(BaseModel):
    """에이전트 실행 컨텍스트"""
    session_id: str
    user_id: str
    timestamp: datetime
    snapshot_ts: datetime  # 데이터 기준점
    namespace: Literal["ops", "study"]
    recent_history: List[Message]
    rag_search_results: List[Dict]
    active_alarms: List[Alarm]

class CallGuard:
    """위험 호출 사전 차단"""
    def validate_call(self, tool_name: str, args: dict) -> bool:
        # LLM이 수치를 생성하지 않는지 확인
        # study 네임스페이스만 write 가능한지 확인
        # snapshot_ts가 명시되었는지 확인
        ...

class SessionSummarizer:
    """세션별 대화 요약"""
    async def summarize_turn(
        self,
        messages: List[Message],
        max_tokens: int = 500
    ) -> str:
        # 사용자 의도 + 핵심 결과 + 다음 단계 제안
        ...
```

---

## 3. 핵심 설계 원칙 (5대 원칙)

### 원칙 1: LLM 수치 생성 절대 금지
```
❌ 금지
Agent: "모선 002의 전압은 1.05 p.u.일 것 같습니다."

✅ 올바름
Agent: "모선 002의 현재 전압을 조회하겠습니다."
[Tool Call] read_ops_voltage(bus_id="BUS002")
→ 결과: 1.0523 p.u.
```

**구현**: CallGuard에서 모든 수치 응답을 Tool 호출로 검증

### 원칙 2: ops/study 네임스페이스 격리
```
ops 네임스페이스:
├─ SCADA 시뮬레이터만 write 가능
├─ 모든 에이전트는 read-only
└─ 예: ops:bus:001:voltage

study 네임스페이스:
├─ 에이전트 write 가능 (HITL 승인 후)
├─ TTL 1800초 자동 삭제
└─ 예: study:session_abc:bus:001:voltage
```

**구현**: API Gateway의 read_only 강제 + Middleware 검사

### 원칙 3: HITL/HOTL 이원 분류

| 분류 | 내용 | 예시 |
|------|------|------|
| **HITL** (Human-In-The-Loop) | 사람 승인 필수 | write_study_data, execute_study |
| **HOTL** (Human-On-The-Loop) | 사람 모니터링 필수 | read_ops_voltage, run_tp |

### 원칙 4: Evidence Chain 필수
모든 Tool 호출은 다음 메타데이터와 함께 기록:
```json
{
  "call_id": "uuid",
  "timestamp": "2026-03-25T14:30:00Z",
  "agent_id": "nl_nav_001",
  "tool_name": "read_ops_voltage",
  "args": {"bus_id": "BUS002", "snapshot_ts": "2026-03-25T14:00:00Z"},
  "result": {"vm_pu": 1.0523, "va_deg": -2.1},
  "duration_ms": 45,
  "namespace": "ops"
}
```

### 원칙 5: snapshot_ts 필수
모든 데이터 조회는 명시적 시간 기준점 필요:
```python
# ❌ 금지
read_ops_voltage(bus_id="BUS002")

# ✅ 올바름
read_ops_voltage(
    bus_id="BUS002",
    snapshot_ts=datetime(2026, 3, 25, 14, 0, 0)
)
```

**이유**: 과거 데이터 추적, 감사 추적성 확보

---

## 4. 기술 스택

### 백엔드
| 기술 | 버전 | 용도 |
|------|------|------|
| **Python** | 3.11+ | 코어 언어 |
| **FastAPI** | 0.104+ | REST API / WebSocket |
| **PydanticAI** | v0.7+ | AI Agent 프레임워크 |
| **pandapower** | 3.x | 전력계통 모델링 |
| **Redis** | 7.x | Hot-cache (ops/study) |
| **PostgreSQL** | 16 | 관계형 DB |
| **TimescaleDB** | 2.x | 시계열 데이터 (시간별 이력) |

### 프론트엔드 / 시각화
| 기술 | 버전 | 용도 |
|------|------|------|
| **Streamlit** | 1.x | 기본 UI |
| **MapLibre GL JS** | 3.x | L1~L2 GIS 맵 |
| **D3.js** | 7.x | 구성도, 트렌드 |
| **Plotly** | 5.x | 대시보드 차트 |

### AI/ML
| 기술 | 버전 | 용도 |
|------|------|------|
| **vLLM / Ollama** | Latest | Qwen2.5-7B 로컬 실행 |
| **Claude API** | Latest | SLM 벤치마크 (Phase 1 보너스) |
| **Chroma** | Latest | Vector DB (RAG 임베딩) |
| **BGE-M3** | Latest | 다언어 임베딩 (한영 혼용) |
| **Prophet** | 1.1+ | 시계열 부하 예측 |
| **Open-Meteo API** | Free Tier | 기상 데이터 (예측 입력) |

---

## 5. ops/study 네임스페이스 설계

### 5.1 ops 네임스페이스 구조

**목적**: 실시간 운영 데이터 (SCADA 시뮬 기반)

#### 주요 Key 패턴
```
# 모선 데이터
ops:bus:{bus_id}:voltage
  → {"vm_pu": 1.0523, "va_deg": -2.1, "ts": "2026-03-25T14:30:00Z"}

ops:bus:{bus_id}:frequency
  → {"freq_hz": 60.001, "ts": "2026-03-25T14:30:00Z"}

# 선로 데이터
ops:line:{line_id}:loading
  → {
      "loading_pct": 65.2,
      "p_from_mw": 120.5,
      "p_to_mw": 119.8,
      "ts": "2026-03-25T14:30:00Z"
    }

ops:line:{line_id}:status
  → {"connected": true, "ts": "2026-03-25T14:30:00Z"}

# 토폴로지
ops:topology:version
  → {
      "version_id": "topo_v123",
      "changed_switches": ["SW001", "SW003"],
      "ts": "2026-03-25T14:30:00Z"
    }

# 알람
ops:alarms:active
  → [
      {
        "alarm_id": "ALARM_20260325_001",
        "type": "LIMIT",
        "facility_id": "BUS002",
        "severity": "HIGH",
        "ts": "2026-03-25T14:28:00Z"
      }
    ]

# 예측 데이터
ops:forecast:load_mw
  → {
      "horizon_hours": 24,
      "values": [450, 455, 460, ...],
      "ts": "2026-03-25T14:00:00Z"
    }
```

#### 접근 제어
```
권한: Read-only
Write 권한: SCADA 시뮬레이터만
정책: 모든 에이전트 write 요청 → 403 Forbidden
```

### 5.2 study 네임스페이스 구조

**목적**: 격리된 What-if 시뮬레이션

#### 주요 Key 패턴
```
# study 기본 구조
study:{session_id}:metadata
  → {
      "session_id": "sess_abc123",
      "user_id": "user_001",
      "created_at": "2026-03-25T14:00:00Z",
      "namespace_type": "study",
      "ttl_seconds": 1800
    }

# ops에서 COPY한 데이터
study:{session_id}:bus:{bus_id}:voltage
study:{session_id}:line:{line_id}:loading
study:{session_id}:topology:version

# What-if 수정 내역
study:{session_id}:modifications
  → [
      {
        "mod_id": "mod_001",
        "type": "switch_open",
        "facility_id": "SW001",
        "timestamp": "2026-03-25T14:15:00Z"
      }
    ]

# Study 실행 결과
study:{session_id}:tp_result
  → {
      "status": "converged",
      "iterations": 4,
      "mismatch": 0.0001,
      "buses": [...],
      "lines": [...],
      "timestamp": "2026-03-25T14:16:00Z"
    }

study:{session_id}:ca_result
  → {
      "contingencies_analyzed": 47,
      "violations": [
        {
          "contingency": "LINE001_open",
          "violation_type": "VOLTAGE_LOW",
          "facility": "BUS005",
          "value": 0.92
        }
      ],
      "timestamp": "2026-03-25T14:17:00Z"
    }
```

#### 접근 제어 및 라이프사이클
```
권한: Read/Write (HITL 승인 후)
TTL: 1800초 (30분) 자동 삭제
정책: study:{session_id}:* 모두 독립적 관리
스냅샷: 생성 시 ops → study 전체 COPY
```

### 5.3 ops → study 데이터 플로우

```
1단계: Study 세션 생성
  POST /study/create
  ├─ session_id 생성
  ├─ ops:* 전체 COPY → study:{session_id}:*
  └─ TTL 1800초 설정

2단계: 수정 및 시뮬 (에이전트)
  POST /study/{session_id}/modify
  ├─ 토폴로지 변경 (스위치 개폐)
  ├─ 기기 상태 변경
  └─ Provenance 기록

3단계: 시뮬레이션 실행
  POST /study/{session_id}/run_tp
  ├─ study 데이터 기반 TP 계산
  ├─ 결과 저장
  └─ 위반사항 정리

4단계: HITL 승인
  POST /approval/{request_id}/approve
  ├─ 사용자 검토
  ├─ 승인 또는 거부
  └─ 감사 기록 남김

5단계: TTL 만료
  자동 삭제 (Redis TTL)
  └─ 명시적 cleanup 불필요
```

---

## 6. v5.1에서 변경되지 않는 것들 (v5.0 유지사항)

| 항목 | v5.0 | v5.1 | 설명 |
|------|------|------|------|
| **아키텍처** | 2-Layer + API Gateway | 동일 | 기본 구조 불변 |
| **네임스페이스** | ops/study 격리 | 동일 | 격리 원칙 유지 |
| **LLM 수치 금지** | ✓ | ✓ | 핵심 안전 원칙 |
| **HITL/HOTL 분류** | ✓ | ✓ | 승인 구조 유지 |
| **Evidence Chain** | ✓ | ✓ | 감사 추적성 필수 |
| **snapshot_ts** | ✓ | ✓ | 시간 기준점 필수 |
| **Pydantic v2** | ✓ | ✓ | 스키마 검증 표준 |
| **4계층 도메인 지식** | ✓ | ✓ | RAG 구조 불변 |
| **MCP Protocol** | ✓ | ✓ | Tool Registry 표준 |
| **Agent Teams** | ✓ | ✓ | 개발 프로세스 유지 |
| **CLAUDE.md 계층** | ✓ | ✓ | 문서 구조 유지 |
| **디렉토리 구조** | ✓ | ✓ | 전체 구조 유지 |

---

## 7. v5.1 항목별 변경 추적 (상세 표)

| 항목 | v5.0 | v5.1 | 변경 유형 | 설명 |
|------|------|------|---------|------|
| **테스트 계통** | IEEE 14/118-bus | 한국 실계통 .raw | 변경 | PowerWorld Simulator 포맷 사용 |
| **Phase 1 범위** | 12개 체크항목 | MDP 3개 게이트 + 보너스 | 축소 | 최소 운영 기능 중심 재구성 |
| **Phase 1 EMS 스텁** | SE + TP (별도) | TP+SE+CA+SCA 4대 통합 | 변경 | 모듈식 설계로 확장성 개선 |
| **능동형 인사이트** | Phase 2에서 구현 | Phase 4로 이동 | 이동 | AI 인사이트 에이전트 후기 추가 |
| **시각화 줌 레벨** | L1~L5 + 4개 뷰 | L1~L2 + L4만 | 축소 | GIS (L1~L2) + 변전소 SLD (L4) |
| **토폴로지 프로세서** | Phase 1 필수 | Phase 1 보너스 | 완화 | 선택 기능으로 변경 |
| **SE 관측성 분석** | Phase 1~2 필수 | Phase 1 보너스 | 완화 | 선택 기능으로 변경 |
| **N-1 2-Tier 분석** | Phase 1~3 필수 | Phase 1 보너스 | 완화 | CA 모듈이 포함하면 실행 가능 |
| **AGC 간이 주파수** | Phase 1 필수 | Phase 1 보너스 | 완화 | 간단한 드룹 제어로 선택적 구현 |
| **알람 4유형 모델** | Phase 1 필수 | Phase 1 보너스 | 완화 | 기본 2개(LIMIT/STATE) + 선택 |
| **pandapower 한계** | Phase 1에서 해결 | 이슈 관리 후 Phase 2+ | 후연 | 제약사항 문서화 → 단계적 해결 |
| **SLM 벤치마크** | Phase 1 필수 (≥80%) | Phase 1 보너스, Claude API | 완화 | 로컬 Qwen + Claude 선택 |
| **예측 모듈** | Phase 3 | Phase 3 (변경 없음) | 유지 | Prophet + Open-Meteo |
| **HITL Priority Queue** | Phase 3에서 고도화 | Phase 2 기본 + Phase 4 고도화 | 분리 | 승인 구조 조기 도입 |

---

## 8. Phase 1 MDP (최소 동작 프로토타입) 정의

### 8.1 3개 핵심 게이트

#### Gate 1: 자연어 네비게이션 + 기본 조회
```
사용자 입력: "현재 계통 상태 알려줘"
↓
1. Intent Classification → NL Navigation 에이전트
2. ops:bus:* 조회 (top 5 High-risk buses)
3. ops:line:* 조회 (top 5 High-loading lines)
4. Streamlit L1 GIS 렌더링 + 수치 표시
↓
출력: 지도 + 수표 (위반 장비 강조)
```

#### Gate 2: 실시간 알람 분석
```
사용자 입력: "최근 알람 뭔데?"
↓
1. Intent Classification → 알람분석 에이전트
2. ops:alarms:active 조회
3. RAG (L4 기준 + L3 특성) → 알람 해석
4. 시간순 정렬 + 심각도 표시
↓
출력: 알람 리스트 + AI 해석 텍스트
```

#### Gate 3: What-if 조류계산 (보너스)
```
사용자 입력: "만약 선로 010이 떨어지면?"
↓
1. Intent Classification → NL2App 에이전트
2. study 세션 생성 (ops → study COPY)
3. 선로 010 disconnect 수정
4. TP 실행 (study 데이터 기반)
5. 위반사항 요약
↓
출력: TP 수렴성 + 위반 선로/모선 리스트
```

### 8.2 보너스 기능

- **토폴로지 프로세서**: 스위치 변화 감지
- **CA 모듈**: N-1 상정고장 분석
- **SCA 모듈**: 단락전류 계산
- **SE 관측성**: 치 분석
- **알람 4유형**: QUALITY/COMM 포함
- **Claude API 벤치마크**: SLM vs Claude 비교

---

## 9. 데이터베이스 스키마 (핵심)

### 9.1 PostgreSQL 주요 테이블

```sql
-- 메타데이터
CREATE TABLE IF NOT EXISTS network_metadata (
    id SERIAL PRIMARY KEY,
    raw_file_path VARCHAR(255),
    case_name VARCHAR(255),
    case_date TIMESTAMP,
    num_buses INT,
    num_lines INT,
    num_generators INT,
    import_date TIMESTAMP DEFAULT NOW()
);

-- Provenance 로그
CREATE TABLE IF NOT EXISTS provenance_log (
    id BIGSERIAL PRIMARY KEY,
    call_id UUID UNIQUE,
    timestamp TIMESTAMP,
    agent_id VARCHAR(100),
    tool_name VARCHAR(100),
    args JSONB,
    result JSONB,
    duration_ms INT,
    namespace VARCHAR(20),  -- 'ops' or 'study'
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_provenance_timestamp ON provenance_log(timestamp DESC);
CREATE INDEX idx_provenance_agent ON provenance_log(agent_id);

-- 세션 메타
CREATE TABLE IF NOT EXISTS study_sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(100),
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    modifications JSONB,  -- 수정 이력
    approval_status VARCHAR(20),  -- PENDING, APPROVED, REJECTED
    created_at_db TIMESTAMP DEFAULT NOW()
);
```

### 9.2 TimescaleDB 시계열 테이블

```sql
-- 모선 전압 시계열
CREATE TABLE IF NOT EXISTS ts_bus_voltage (
    time TIMESTAMP NOT NULL,
    bus_id VARCHAR(50),
    vm_pu FLOAT,
    va_deg FLOAT,
    source VARCHAR(20)  -- 'SCADA', 'SE'
);
SELECT create_hypertable('ts_bus_voltage', 'time', if_not_exists => TRUE);
SELECT add_compression_policy('ts_bus_voltage', INTERVAL '24 hours', if_not_exists => TRUE);

-- 선로 전력 시계열
CREATE TABLE IF NOT EXISTS ts_line_power (
    time TIMESTAMP NOT NULL,
    line_id VARCHAR(50),
    p_from_mw FLOAT,
    p_to_mw FLOAT,
    loading_pct FLOAT
);
SELECT create_hypertable('ts_line_power', 'time', if_not_exists => TRUE);

-- 알람 이벤트
CREATE TABLE IF NOT EXISTS ts_alarms (
    time TIMESTAMP NOT NULL,
    alarm_id VARCHAR(100),
    facility_id VARCHAR(50),
    alarm_type VARCHAR(20),  -- LIMIT, STATE, COMM, QUALITY
    severity VARCHAR(20),
    description TEXT,
    cleared_at TIMESTAMP
);
SELECT create_hypertable('ts_alarms', 'time', if_not_exists => TRUE);
```

---

## 10. 배포 및 운영 가이드

### 10.1 환경 구성

```bash
# .env 예시
PYTHON_VERSION=3.11
FASTAPI_HOST=0.0.0.0
FASTAPI_PORT=8000

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ems_v51
POSTGRES_USER=ems_admin
POSTGRES_PASSWORD=***

TIMESCALEDB_ENABLED=true

OPENAI_API_KEY=***  # Optional for SLM benchmark
QWEN_MODEL=qwen2.5-7b

STREAMLIT_PORT=8501
MAPLIBRE_API_KEY=***  # Optional

DATA_RAW_FILE=./data/case_data.raw
```

### 10.2 시작 순서

```bash
# 1. 데이터베이스 초기화
python -m ems_v51.db.init_db

# 2. Redis 시작
redis-server --port 6379

# 3. SCADA 시뮬레이터 시작
python -m ems_v51.layer1.scada_simulator

# 4. FastAPI 백엔드 시작
uvicorn ems_v51.api.main:app --host 0.0.0.0 --port 8000

# 5. Streamlit 프론트엔드 시작
streamlit run ems_v51/ui/app.py --server.port 8501
```

---

## 11. 결론

AI-EMS v5.1은 **한국 실계통 기반 MDP(최소 동작 프로토타입)**로, 다음을 달성합니다:

1. **실용성**: 실계통 .raw 파일 기반 검증
2. **안정성**: 5대 설계 원칙과 HITL 승인 구조
3. **확장성**: Phase 2~4 로드맵을 위한 모듈식 설계
4. **투명성**: Evidence Chain 및 Provenance 로그 필수

Phase 1 완성 후, AI 인사이트 고도화(Phase 4), 실시간 제어 시연(Phase 5) 등으로 단계적 확대를 계획합니다.

