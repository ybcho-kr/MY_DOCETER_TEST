# AI-EMS v5.1 컴포넌트 명세

## 개요

AI-EMS v5.1은 3계층(Layer) 아키텍처로 구성되며, 각 계층은 독립적인 역할을 수행합니다. 본 문서는 모든 컴포넌트의 명세를 상세히 기술합니다.

---

## 제1계층 — EMS 디지털 쌍둥이 (Layer 1)

계통의 실시간 상태를 모델링하고, 전기적 특성을 분석하는 계층입니다.

### C-L1-01: SCADA 시뮬레이터 + 토폴로지 프로세서

**컴포넌트 ID**: `C-L1-01`
**컴포넌트명**: SCADA 시뮬레이터 + 토폴로지 프로세서
**역할**: PSS/E .raw 형식의 계통 모델을 pandapower로 변환하여 SCADA 데이터로 생성. 4초 주기로 Redis에 발행. 토폴로지 프로세서는 버스 병합/분할 처리.

**기술스택**:
- pandapower 3.x (from_psse() 함수)
- TopologyProcessor (커스텀)
- APScheduler (4초 주기)
- lightsim2grid (300+ 버스 필수)
- Redis Pub/Sub
- Golden Case 검증 (±1% 오차 기준)

**입력**:
- `grid_model.raw`: PSS/E RAW 형식 (v30~v35)
- `golden_case.json`: 기준 사례 (조류계산 기준값)
- `ops:switch:*`: 스위치 상태 (Redis)

**출력**:
- `ops:bus:{id}:voltage`: {vm_pu, va_deg, ts}
- `ops:line:{id}:loading`: {loading_pct, p_from_mw, q_from_mvar, ts}
- `ops:topology:version`: 토폴로지 변경 버전번호

**제약사항**:
- `ops:` 네임스페이스는 쓰기 전용 (읽기는 타 컴포넌트만)
- 수렴 실패 시: 이전 스냅샷 유지 + FAILED 플래그
- Golden Case 오차 >1% → 경고 알람 발생
- 300+버스 이상 계통: lightsim2grid 필수 사용
- 4초 주기 보장 (지연 시 큐 누적 방지)

**v5.1 기본사항**:
- 한국 실계통 .raw 파일 기반 초기화
- 토폴로지 프로세서는 Phase 1 보너스 기능

---

### C-L1-02: 응용 데이터베이스 (Application DB)

**컴포넌트 ID**: `C-L1-02`
**컴포넌트명**: Application DB (Redis + TimescaleDB)
**역할**: 실시간 스냅샷(Redis 60분 보관) + 시계열 이력 관리(TimescaleDB 5분 집계). ops/study 데이터 격리.

**기술스택**:
- Redis 7.x (실시간 KV 저장)
- TimescaleDB (시계열 이력)
- PostgreSQL 16 (메타데이터)
- JSON Schema 검증

**입력**:
- SCADA 시뮬레이터의 ops: 데이터
- SE 스텁의 상태추정 결과
- TP 스텁의 조류계산 결과

**출력**:
- `ops:bus:*` GET: 실시간 전압 데이터
- `ops:line:*` GET: 실시간 계통운영 데이터
- `time_series.*`: 5분 집계 시계열 (TimescaleDB)
- `SUBSCRIBE ops:alarm`: 알람 발생 시 구독

**제약사항**:
- AI Agent는 ops: 네임스페이스에 쓰기 불가
- study: TTL은 1800초(30분)
- 부동소수점 반올림: 4자리 (가독성 + 저장소 최적화)

**v5.1 기본사항**:
- Phase 1 필수 기능

---

### C-L1-03: SE 스텁 (상태추정 + 관측성 분석)

**컴포넌트 ID**: `C-L1-03`
**컴포넌트명**: SE 스텁 (상태추정 + 관측성 분석)
**역할**: pandapower WLS(가중최소제곱) 상태추정 + Jacobian 행렬 기반 관측성 분석. Pseudo-measurement 생성으로 관측성 개선.

**기술스택**:
- FastAPI
- pandapower.estimation (WLS)
- 관측성 분석 (Jacobian rank)
- Pseudo-measurement (Prophet 기반)
- confidence_level = f(residual, observable_ratio, pseudo_ratio)

**API 엔드포인트**:
- `GET /se/run`: 상태추정 실행 (비동기)
- `GET /se/latest`: 최신 결과 조회
- `GET /se/observability`: 관측성 보고서 조회

**입력**:
- SCADA 측정값 (전압, 주입전력, 변압기 탭 등)
- 계통 토폴로지
- 측정 오차 기준

**출력**:
```
SEResult {
  solved: bool,
  bus_vm_pu: [float],      # 상태추정 전압 (pu)
  bus_va_deg: [float],     # 상태추정 위상각 (deg)
  residual: float,         # WLS 잔차
  confidence_level: float, # 0.0~1.0
  observable_ratio: float, # 관측 비율 (%)
  unobservable_buses: [int], # 미관측 버스 ID
  ts: str                  # ISO 8601 타임스탬프
}
```

**제약사항**:
- 측정값 부재 시 pseudo-measurement 자동 생성
- 미관측 버스 존재 시 경고

**v5.1 기본사항**:
- 기본 WLS 상태추정 필수
- 관측성 분석은 Phase 1 보너스 기능

---

### C-L1-04: TP 스텁 (조류계산 + N-1 + VSA)

**컴포넌트 ID**: `C-L1-04`
**컴포넌트명**: TP 스텁 (조류계산 + N-1 + VSA)
**역할**: pandapower runpp/runopp를 이용한 조류계산. N-1 우발상황 분석(2-Tier). VSA(Voltage Stability Analysis).

**기술스택**:
- pandapower (runpp, runopp)
- N-1 우발상황 분석 (2-Tier: Screening + Full AC OPF)
- VSA (전압 안정성 마진)
- PTDF 기반 Fast Screening

**API 엔드포인트**:
- `POST /tp/powerflow`: 조류계산 실행
- `POST /tp/contingency`: N-1 우발상황 분석
- `POST /tp/vsa`: 전압 안정성 분석

**입력**:
- 계통 토폴로지
- 발전기/부하 설정값
- 제약사항 (선로 용량, 전압 범위 등)

**출력**:
```
PowerFlowResult {
  converged: bool,
  bus_vm_pu: [float],
  line_loading_pct: [float],
  ts: str
}

ContingencyResult {
  contingencies: [{
    element_type: str,
    element_id: int,
    status: str,      # "OK" | "VIOLATION" | "DIVERGENCE"
    max_loading_pct: float,
    violated_elements: [str]
  }],
  severity: str      # "NONE" | "MINOR" | "MAJOR"
}

VSAResult {
  margin_pct: float,
  critical_buses: [int],
  remedial_actions: [str]
}
```

**제약사항**:
- LLM에 수치 입력 금지 (강제)
- Tier-1 스크리닝: 5분 내 20개 우발상황 처리
- Tier-2 상세분석: 1시간 배치 모드
- PTDF 기반 고속 스크리닝으로 계산 시간 최소화

**v5.1 기본사항**:
- Phase 1 필수: 기본 조류계산 + 기본 N-1 분석
- 2-Tier N-1, VSA는 보너스 기능

---

### C-L1-05: AGC 스텁 (간이 주파수 모델)

**컴포넌트 ID**: `C-L1-05`
**커포넌트명**: AGC 스텁 (간이 주파수 모델)
**역할**: 간단한 주파수 동적 모델. 계통 불평형 추정 및 ACE(Area Control Error) 계산.

**기술스택**:
- 동역학 모델 (신영사 교안 기반)
- 주파수 편차 방정식: Δf = -ΔP/(D+1/R)
- ACE 계산: ACE = ΔP_tie + 10·B·Δf

**API 엔드포인트**:
- `GET /agc/status`: 현재 주파수, ACE 조회 (읽기 전용)
- `GET /agc/history`: 주파수 이력 조회 (읽기 전용)

**입력**:
- 계통 불평형전력 (ΔP)
- 계통 주파수
- 연결선 전력

**출력**:
```
AGCStatus {
  frequency_hz: float,
  delta_f: float,
  ace: float,
  status: str         # "NORMAL" | "WARNING" | "CRITICAL"
}
```

**한국 계통 주파수 기준 (산업통상자원부고시 제2023-65호)**:
- 정상 범위: 60Hz ±0.2Hz (59.8~60.2Hz) — 고시 제4조
- 최소 허용: 단일고장 59.7Hz, 연쇄고장 59.5Hz
- 계통 관성상수: B≈5800 MW/0.1Hz
- 조속기 속도조정률(droop): 수력 3~5%, 가스터빈 4~6%, 기력 4~6%, ESS 3% — 고시 별표2
- PSS(전력계통안정화장치): 100MW 이상 발전기 의무 설치 — 고시 제23조
- 예비력 5종 (고시 제6조):
  - 주파수제어예비력: 5분 이내 동원
  - 초속응성예비력: 1초 이내 동원 (ESS 등)
  - 1차예비력: 10초 이내 동원 (조속기 응답)
  - 2차예비력: 10분 이내 동원 (AGC 응답)
  - 3차예비력: 30분 이내 동원 (수동 기동)

**제약사항**:
- POST/PUT/DELETE 메서드 미등록 (읽기 전용)
- Gateway에서 `read_only=True` 강제

**v5.1 기본사항**:
- Phase 1 보너스 기능

---

### C-L1-06: SCA 스텁 (단락전류 계산)

**컴포넌트 ID**: `C-L1-06`
**컴포넌트명**: SCA 스텁 (단락전류 계산)
**역할**: 3상 단락전류 계산 및 영향 범위 분석. 계기용변압기(CT) 특성 고려.

**기술스택**:
- pandapower 또는 Powerfactory 인터페이스
- 3상 단락전류 계산 (IEC 60909 기준)
- 영향 범위 분석 (차단기 특성 포함)

**API 엔드포인트**:
- `POST /study/shortcircuit`: 단락전류 계산 요청 (study 격리)

**입력**:
- 계통 토폴로지 (study 격리 복사본)
- 단락점(fault point) 위치
- 계기용변압기 정보

**출력**:
```
ShortCircuitResult {
  fault_current_ka: float,
  affected_relays: [{
    relay_id: str,
    pickup_current: float,
    operating_time: float
  }],
  ts: str
}
```

**제약사항**:
- ops: 데이터에 대한 직접 단락 금지
- study 격리 공간 내에서만 실행

**v5.1 기본사항**:
- Phase 1: API 정의 + 3상 단락전류 기본 계산 구현 (v5.0 변경)

---

### C-L1-07: Study 스텁 (격리 실행)

**컴포넌트 ID**: `C-L1-07`
**컴포넌트명**: Study 스텁 (격리 실행)
**역할**: ops: 데이터를 격리된 study: 공간으로 복사하여 What-if 분석 및 단락전류 계산 실행.

**기술스택**:
- TimescaleDB 격리 스키마 (study_*)
- Copy-on-Write 메커니즘
- TTL 기반 자동 정리

**API 엔드포인트**:
- `POST /study/create`: 새 연구 공간 생성
- `POST /study/shortcircuit`: 격리 공간에서 단락 계산
- `POST /study/powerflow`: 격리 공간에서 조류계산

**입력**:
- ops: 현재 스냅샷
- 분석 시나리오 파라미터

**출력**:
```
StudyResult {
  study_id: str,
  scenario: {...},
  results: {...},
  ts: str
}
```

**제약사항**:
- ops: 데이터에 대한 쓰기 금지 (읽기만)
- TTL 1800초(30분) 경과 후 자동 삭제
- 복구 권고사항 생성 → HITL 승인 필요

**v5.1 기본사항**:
- Phase 1 필수 기능

---

### C-L1-08: 시각화 화면

**컴포넌트 ID**: `C-L1-08`
**컴포넌트명**: 시각화 화면
**역할**: 계통 상태 시각화 (GIS + 선단도) 및 분석 결과 표시.

**기술스택**:
- Streamlit (대시보드 프레임워크)
- MapLibre (GIS 기반 토폴로지 표시)
- D3.js (시계열 차트, SLD)
- WebGL (고속 렌더링)

**주요 화면**:
- L1 GIS: 계통 토폴로지, 버스 전압, 선로 로딩
- L2 GIS: 제어 자동화 및 제어 상태
- L4 SLD: 단선도(Single-Line Diagram) 상세 표시

**입력**:
- Redis 실시간 데이터 (ops:*)
- TimescaleDB 시계열
- 분석 결과 (TP, SE 등)

**출력**:
- 웹 UI (HTTP)
- PNG/SVG 내보내기

**v5.1 기본사항**:
- Phase 1: L1~L2 GIS + L4 SLD만 구현
- 고도화는 Phase 2 이후

---

### C-L1-09: 예측 모듈

**컴포넌트 ID**: `C-L1-09`
**컴포넌트명**: 예측 모듈
**역할**: 부하 및 재생에너지 예측 (1~24시간 선도).

**기술스택**:
- Prophet (부하 예측)
- Open-Meteo API (기상 데이터)
- Pvlib (태양광 예측)
- LSTM (고도화 버전)

**API 엔드포인트**:
- `GET /forecast/load`: 부하 예측 조회
- `GET /forecast/pv`: 태양광 예측 조회

**입력**:
- 과거 부하 시계열
- 기상 데이터
- 계절/요일 정보

**출력**:
```
ForecastResult {
  horizon: int,           # 예측 시간수
  values: [float],        # 예측값
  confidence_interval: [{lower, upper}],
  ts: str
}
```

**제약사항**:
- 예측 신뢰도 낮음 시 경고

**v5.1 기본사항**:
- Phase 3에서 구현 예정 (v5.1에서 변경 사항 없음)
- v5.1은 기본 구조만 정의

---

## API 게이트웨이 계층

### C-GW-01: API Gateway / Tool Registry (MCP)

**컴포넌트 ID**: `C-GW-01`
**컴포넌트명**: API Gateway / Tool Registry (MCP)
**역할**: 모든 Layer 1 API를 MCP(Model Context Protocol) Tool로 등록. 읽기 전용 강제, Evidence Chain 관리, Provenance 로깅, 스키마 검증.

**기술스택**:
- FastAPI (API 서버)
- MCP Python SDK (Tool 정의)
- Pydantic (스키마 검증)
- 아우디트 로깅 (Provenance)

**주요 기능**:
- 22개 MCP Tool 등록:
  - 21개: 읽기 전용 (read_only=True)
  - 3개: study 전용 (POST /study/*)
- Tool Call 형식:
  ```json
  {
    "tool_name": "get_voltage",
    "params": {"bus_id": 101},
    "session_id": "uuid",
    "timestamp": "2026-03-25T10:00:00Z"
  }
  ```
- Evidence Chain: 각 Tool Call 추적
- Provenance 로그: 누가, 언제, 무엇을 호출했는지 기록

**제약사항**:
- read_only 플래그 강제 (Gateway 레벨)
- study 도구는 ops: 데이터 쓰기 금지
- 모든 요청에 session_id 필수

**v5.1 기본사항**:
- Phase 1 필수 기능

---

## 제2계층 — AI Agent (Layer 2)

AI 기반 의사결정 및 자동화 계층입니다.

### C-L2-01: 오케스트레이터 Agent

**컴포넌트 ID**: `C-L2-01`
**컴포넌트명**: 오케스트레이터 Agent
**역할**: 사용자 요청 분석 및 적절한 서브에이전트로 라우팅. Intent 분류 및 구조화된 사실 보존.

**기술스택**:
- PydanticAI
- Qwen2.5-7B (프로덕션 타겟) / Claude 3.5 Sonnet (개발)
- Intent 분류기 (추가학습)
- AgentContext (세션 상태 관리)

**주요 기능**:
- Intent 분류:
  - QUERY: 조회 (전압, 부하 등)
  - ANALYSIS: 분석 (N-1, VSA 등)
  - CONTROL: 제어 제안 (리모팅 등)
  - TROUBLESHOOT: 문제 진단
- CallGuard: 최대 깊이 5 (무한 루프 방지)
- 세션 요약: AgentContext에 structured_facts 보존

**입력**:
- 자연어 사용자 요청
- 세션 히스토리

**출력**:
```
OrchestratorResponse {
  intent: str,
  routed_agent: str,
  confidence: float,
  response: str
}
```

**제약사항**:
- CallGuard depth ≤ 5
- 구조화된 사실만 보존 (토큰 효율)

**v5.1 기본사항**:
- Phase 2에서 구현
- v5.1: 반응형 모드만 (능동형 아님)

---

### C-L2-02: HITL 승인 모듈

**컴포넌트 ID**: `C-L2-02`
**커포넌트명**: HITL 승인 모듈 (Human-in-the-Loop)
**역할**: 제어 작업 승인 관리. 우선순위 큐 기반 작업 스케줄링.

**기술스택**:
- Priority Queue (Celery, Redis)
- Web UI (Streamlit)
- 세션 추적 (운영자 인증)

**우선순위 설정**:
- CRITICAL (자동 차단): 600초 응답 제한
- HIGH: 300초 응답 제한
- MEDIUM: 180초 응답 제한
- LOW: 120초 응답 제한

**주요 기능**:
- 동시 표시: 최대 3건
- 중복 자동 취소: 동일 제어 작업 중복 배제
- 부재 감지: 운영자 응답 없음 → 알림 확대

**입력**:
- Agent에서 제어 제안
- 우선순위 등급
- 운영자 응답

**출력**:
```
ApprovalTask {
  task_id: str,
  action: str,
  priority: str,
  expires_at: str,
  status: str         # "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED"
}
```

**제약사항**:
- 운영자 재량권 존중 (AI는 제안만)
- 감사 로그 필수

**v5.1 기본사항**:
- Phase 2: 기본 HITL (큐 관리)
- Phase 4: PQ 고도화 (ML 기반 우선순위 학습)

---

### C-L2-03: NL Navigation Agent

**컴포넌트 ID**: `C-L2-03`
**컴포넌트명**: NL Navigation Agent
**역할**: 자연어로 시스템 네비게이션. "어디서 메뉴 찾아?" → 화면 제시.

**기술스택**:
- 네비게이션 그래프 (화면 간 관계)
- Intent 매칭

**주요 API**:
- `navigate(intent: str) → Screen`

**v5.1 기본사항**:
- Phase 2: HOTL(Human-on-the-Loop) 구현
- 기본 네비게이션만

---

### C-L2-04: NL2App 조회 Agent

**컴포넌트 ID**: `C-L2-04`
**컴포넌트명**: NL2App 조회 Agent
**역할**: 자연어 조회를 Layer 1 API로 변환 (예: "버스 101의 전압은?" → GET /bus/101).

**기술스택**:
- Intent 분류
- Entity 추출 (버스 ID, 시간 범위 등)
- API 매핑

**주요 API**:
- `query(nl_question: str) → APICall → Result`

**입력**:
- 자연어 질문

**출력**:
- 정형화된 결과 + 자연어 설명

**v5.1 기본사항**:
- Phase 2: HOTL 구현
- 조회만 (제어 제안 아님)

---

### C-L2-05: AI 인사이트 Agent (능동형)

**컴포넌트 ID**: `C-L2-05`
**컴포넌트명**: AI 인사이트 Agent (능동형)
**역할**: 계통 이상 자동 감지 및 인사이트 제공 (능동형). 예: "모선 301 전압이 정상범위 벗어남" 자동 알림.

**기술스택**:
- 규칙 엔진 (정상범위 검사)
- 이상 탐지 모델 (Isolation Forest 등)
- 추천 엔진

**주요 기능**:
- 실시간 이상 감지
- 근본 원인 분석 (RCA)
- 완화 조치 추천

**출력**:
```
InsightAlert {
  severity: str,        # "INFO" | "WARNING" | "CRITICAL"
  title: str,
  description: str,
  root_cause: str,
  remedial_actions: [str]
}
```

**v5.1 기본사항**:
- Phase 4로 이동 (v5.1에서는 미구현)

---

### C-L2-06: RAG Agent (4계층 지식)

**컴포넌트 ID**: `C-L2-06`
**컴포넌트명**: RAG Agent (4계층 지식)
**역할**: 문서 기반 지식 검색 및 답변. 4계층 지식 구조 활용.

**기술스택**:
- Vector DB (Milvus 또는 Weaviate)
- Embedding (OpenAI, Qwen)
- 4계층 지식:
  1. 공식 기술 매뉴얼 (pandapower 문서 등)
  2. 한국 계통 운영 지침
  3. 사내 운영 프로세스
  4. AI 학습 결과 (피드백)

**주요 API**:
- `retrieve_and_generate(query: str) → Answer`

**제약사항**:
- 출처 명시 필수 (Provenance)

**v5.1 기본사항**:
- Phase 2 이후 구현 (기본 구조 정의)

---

### C-L2-07: 알람 분석 Agent

**컴포넌트 ID**: `C-L2-07`
**컴포넌트명**: 알람 분석 Agent
**역할**: 계통 알람 자동 분류, 근본 원인 분석, 통합 보고.

**기술스택**:
- 알람 분류 모델 (LLM 기반)
- 상관 분석 (이벤트 그래프)
- 우선순위 산정

**주요 기능**:
- 알람 그룹화 (동시 다중 알람 통합)
- RCA 자동화
- 추천 조치

**입력**:
- ops:alarm 구독 (Redis)

**출력**:
```
AlarmAnalysis {
  alarms: [Alarm],
  severity: str,
  root_cause: str,
  recommended_actions: [str]
}
```

**v5.1 기본사항**:
- Phase 2 이후 구현

---

### C-L2-08: NL2 계통검토 Agent (Study)

**컴포넌트 ID**: `C-L2-08`
**컴포넌트명**: NL2 계통검토 Agent (Study)
**역할**: 자연어로 연구 시나리오 정의 및 시뮬레이션. "만약 발전소 A가 정지하면?" → Study 격리 환경에서 분석.

**기술스택**:
- 시나리오 파서 (자연어 → 파라미터)
- Study API 연동
- 결과 시각화

**주요 API**:
- `scenario_to_api(nl_scenario: str) → StudyCall`

**입력**:
- 자연어 시나리오
  - 예: "버스 201에서 100 MW 부하 증가 시뮬레이션"

**출력**:
- Study 결과 (조류계산, N-1 등)
- 자연어 해석

**제약사항**:
- ops: 데이터 직접 수정 금지
- study 격리 공간에서만 실행

**v5.1 기본사항**:
- Phase 2 이후 구현
- 기본 시나리오 파서만

---

## 컴포넌트 상호작용

### 데이터 흐름

```
┌─────────────────────────────────────────┐
│    사용자 입력 (자연어 / UI)            │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  C-L2-01: 오케스트레이터 Agent          │
│  (Intent 분류 → 라우팅)                 │
└────────┬────────────────┬───────────────┘
         │                │
    ┌────▼────┐      ┌────▼────┐
    │ L2 조회  │      │ L2 제어  │
    │ Agents   │      │ 제안     │
    └────┬────┘      └────┬────┘
         │                │
    ┌────▼──────────────▼────┐
    │  C-GW-01: API Gateway  │
    │  (MCP Tool Registry)   │
    └────┬──────────────┬────┘
         │              │
┌────────▼──┐  ┌───────▼────────┐
│  L1 조회   │  │  L1 제어 검증  │
│  APIs      │  │  (시뮬레이션)  │
│ (읽기)     │  │  (study)       │
└────┬───┬──┘  └───┬──────┬─────┘
     │   │         │      │
  ┌──▼─▼─────────▼─┐  ┌──▼─────┐
  │ C-L1-02: DB    │  │ C-L1-07:│
  │ (ops/study)    │  │ Study   │
  └────────────────┘  └─────────┘
```

### 읽기 경로 (예: 전압 조회)
1. 사용자: "버스 101 전압?"
2. C-L2-01: Intent = QUERY
3. C-L2-04: "버스 101" → bus_id = 101
4. C-GW-01: `get_voltage(101)` MCP Tool 호출
5. Layer 1 API: Redis에서 ops:bus:101:voltage 조회
6. 결과: {vm_pu: 0.998, va_deg: -2.5, ts: ...}

### 제어 경로 (예: 제어 제안)
1. 사용자: "부하 200MW 증가 시 계통 안정?"
2. C-L2-01: Intent = ANALYSIS
3. C-L2-08: 시나리오 파서 → Study 파라미터
4. C-GW-01: `create_study()` + `run_powerflow()` MCP Tool
5. C-L1-07: ops 복사 → study 격리 공간
6. C-L1-04: study 공간에서 TP 실행
7. C-L2-02: HITL 승인 모듈 (필요 시)
8. 결과: 분석 보고서 + 완화 조치 제안

---

## Phase 별 구현 계획

### Phase 1 (기본)
- **필수 컴포넌트**:
  - C-L1-01: SCADA 시뮬레이터 (토폴로지 프로세서 제외)
  - C-L1-02: DB
  - C-L1-03: SE (기본 WLS만)
  - C-L1-04: TP (기본 조류계산 + 기본 N-1만)
  - C-L1-06: SCA (API 정의 + 3상 단락 기본)
  - C-L1-07: Study 스텁
  - C-L1-08: 시각화 (L1~L2 GIS + L4 SLD)
  - C-GW-01: API Gateway / MCP
- **보너스**:
  - C-L1-01: 토폴로지 프로세서
  - C-L1-03: 관측성 분석
  - C-L1-04: 2-Tier N-1, VSA
  - C-L1-05: AGC 스텁

### Phase 2
- C-L2-01: 오케스트레이터 Agent (반응형)
- C-L2-02: HITL 승인 모듈 (기본)
- C-L2-03: NL Navigation Agent (HOTL)
- C-L2-04: NL2App 조회 Agent (HOTL)
- C-L2-06: RAG Agent (기본)
- C-L2-07: 알람 분석 Agent
- C-L2-08: NL2 계통검토 Agent (Study)

### Phase 3
- C-L1-09: 예측 모듈
- L2 고도화 (능동형 기능)

### Phase 4
- C-L2-05: AI 인사이트 Agent (능동형)
- C-L2-02: HITL PQ 고도화 (ML 기반)
- 에러 처리, 로깅 강화

---

## 문제 해결 및 제약사항

### 일반 제약사항
1. **데이터 격리**: ops: vs study: 엄격한 분리
2. **읽기 전용**: Layer 1 API는 기본 read_only (제어는 study를 통함)
3. **Provenance**: 모든 API Call은 감사 로그 필수
4. **토큰 효율**: 구조화된 사실만 보존 (AgentContext)
5. **LLM 보호**: 수치 직접 입력 금지 (강제)

### 성능 요구사항
- SCADA 4초 주기 보장
- Tier-1 N-1: 5분 내 20건 처리
- SE 실행: 60초 이내
- UI 응답: 3초 이내

### 보안 요구사항
- MCP Tool Registry 필수 (전문 도구만 노출)
- 세션 추적 (운영자 인증)
- 암호화 (Redis TLS, PostgreSQL SSL)

---

## 버전 이력

| 버전  | 날짜       | 변경사항                          |
|-------|-----------|----------------------------------|
| 5.0   | 2026-01   | 초기 설계                         |
| 5.1   | 2026-03   | C-L1-06 단락 기본 계산 추가       |
| 5.1   | 2026-03   | Phase 맵핑 명시화                |
| 5.1   | 2026-03   | Study 격리 강화                  |

---

## 참고자료

- **기술 스택**: pandapower 3.x, FastAPI, Redis 7.x, TimescaleDB, PydanticAI
- **한국 계통 기준**: PSS/E .raw (v30~v35), 주파수 60Hz ±0.2Hz (고시 제4조), B값 5800 MW/0.1Hz
- **고시 기준**: 산업통상자원부고시 제2023-65호 (전력계통 신뢰도 및 전기품질 유지기준)
- **표준**: IEC 60909 (단락전류), IEEE 1547 (분산전원)

---

**문서 작성**: 2026-03-25
**버전**: 5.1
**상태**: 최종
