# AI-EMS v5.1 Phase별 로드맵

## 개요

v5.0 → v5.1 핵심 전략: MDP 기반 Phase 재편. Phase 1은 최소 동작 프로토타입으로 축소, 능동형 인사이트는 Phase 4로 이동.

---

## Phase 1: 최소 동작 프로토타입 (MDP) — 2~3주

### Phase 1 게이트 (3개만 통과하면 Phase 2 진입)

#### 게이트 A: 실계통 수렴

- **작업**: 한국 계통 .raw → pandapower from_psse() 변환 → runpp() 조류계산 수렴 확인
- **판정**: 조류계산 수렴 성공 (Newton-Raphson)
- **허용**: 일부 설비(shunt, FACTS 등) 누락 시 수동 보정 후 수렴이면 OK

#### 게이트 B: EMS 스텁 동작

4대 EMS 앱 스텁이 FastAPI로 동작하고 올바른 Pydantic 스키마를 반환

| EMS 앱 | 엔드포인트 | 설명 |
|--------|----------|------|
| TP (Topology Processor) | POST /tp/powerflow | 조류계산 |
| | GET /tp/violations | 위반사항 조회 |
| SE (State Estimator) | GET /se/run | 상태추정 실행 |
| | GET /se/latest | 최신 결과 조회 |
| CA (Contingency Analyzer) | POST /tp/contingency | 기본 N-1 분석 |
| SCA (Short Circuit Analyzer) | POST /study/shortcircuit | 3상 단락전류 |

#### 게이트 C: Redis 실시간

- **작업**: SCADA 시뮬이 4초 주기로 Redis ops 키에 결과 저장하고 API에서 읽기 가능
- **키 포맷**:
  - `ops:bus:{id}:voltage`
  - `ops:line:{id}:loading`
- **네임스페이스**: study 격리 확인

### Phase 1 세부 태스크

#### 필수 태스크 (1.1~1.10)

| 태스크 ID | 내용 | 담당팀 |
|----------|------|--------|
| 1.1 | 한국 .raw → pandapower 변환. from_psse() 실행. 누락 항목 목록화 | scada-dev |
| 1.2 | 수동 보정: 누락 shunt/FACTS 등 패치. runpp() 수렴 확인 | scada-dev |
| 1.3 | SCADA 시뮬: APScheduler 4초 주기 runpp(). Redis ops: 키 저장 | scada-dev |
| 1.4 | TP 스텁: POST /tp/powerflow, GET /tp/violations. Pydantic 스키마 | stub-dev |
| 1.5 | SE 스텁: GET /se/run, GET /se/latest. WLS 기본 동작 | stub-dev |
| 1.6 | CA 스텁: POST /tp/contingency. 기본 N-1 | stub-dev |
| 1.7 | SCA 스텁: POST /study/shortcircuit. 3상 단락전류 | stub-dev |
| 1.8 | 공유 Pydantic 스키마 (SEResult, PowerFlowResult 등 8개) | infra-dev |
| 1.9 | Redis ops:/study 네임스페이스 분리. study TTL 1800s | infra-dev |
| 1.10 | 기본 전력 용어 사전 glossary.json (핵심 200개) | infra-dev |

#### 보너스 태스크 (B.1~B.6)

- **B.1**: 토폴로지 프로세서 (bus merge/split). 차단기 개폐 시나리오
- **B.2**: SE 관측성 분석 (Jacobian rank). pseudo-measurement
- **B.3**: N-1 2-Tier (Tier-1 상위 20건 실시간). PTDF screening
- **B.4**: AGC 간이 주파수 모델
- **B.5**: 알람 모델 4유형 + dead-band + 억제
- **B.6**: SLM 벤치마크 (Intent 분류 50건)

### Phase 1 Agent Teams

| 팀 | 모델 | 책임 |
|----|------|------|
| scada-dev | Sonnet | .raw 변환, 수동 보정, SCADA 시뮬, Redis 저장 |
| stub-dev | Sonnet | TP/SE/CA/SCA 스텁, 테스트 |
| infra-dev + devops | Sonnet | Pydantic 스키마, glossary, Redis 설정, CHANGELOG |

### 한국 .raw 변환 시 예상 이슈 & 대응

| 이슈 | 대응 방안 |
|------|----------|
| Switched Shunt 미지원 | 수동 pandapower shunt 변환 |
| FACTS 장치 미지원 | 정적 shunt/generator 근사 |
| .raw v35 미파싱 | v30~v33 재저장 |
| 한글 bus_name 인코딩 | UTF-8/EUC-KR 확인 |
| 대규모 계통 수렴 실패 | lightsim2grid + init='results' + tolerance 조정 |

---

## Phase 2: AI Agent — 반응형 전용 — 2~3주

### 포함 항목 (반응형)

- 오케스트레이터 (Orchestrator)
- NL Navigation (HOTL)
- NL2App (HOTL)
- RAG (4계층)
- 알람분석 (HITL)
- 계통검토 (HITL)
- API Gateway (MCP + read_only + Evidence chain)
- HITL 기본
- AgentContext + CallGuard + snapshot_ts

### 제외 항목 → Phase 4로 이동

- APScheduler 기반 5분 건전성
- 1시간 리스크 분석
- 알람 스톰 자동 분석
- 기상 영향 분석
- 이상 패턴 탐지
- 일일 자동 리포트

### Phase 2 게이트

| 게이트 | 조건 | 설명 |
|--------|------|------|
| 게이트 D | NL→Tool 동작 | "계통 상태 요약해줘" → 결과 + Evidence chain |
| 게이트 E | Study 격리 | "5번 CB 개방하면?" → study 격리 → HITL |
| 게이트 F | RAG 문서 검색 | "N-1 복구 절차" → SOP + 조항번호 |

### Phase 2 Agent Teams

- orchestrator-dev
- agents-dev
- gateway-dev
- devops-commit

---

## Phase 3: 시각화 (축소) + 예측 — 2~3주

### 구현 항목

| 항목 | 설명 |
|------|------|
| L1 (전국 345kV) | 전국 네트워크 개요 |
| L2 (권역 345+154kV) | 권역별 상세 도면 |
| L4 (변전소 SLD D3.js) | 단일선 결선도 |
| Streamlit 3열 | 반응형 UI 레이아웃 |
| SCADA 오버레이 | 실시간 데이터 표시 |
| 알람 마커 | 지도 위 알람 포인트 |
| NL→지도 MCP Tool 기본 | 자연어로 지도 제어 |
| HITL 팝업 | 사용자 상호작용 |

### 설계만 유지 (구현 지연)

- L3 (광역)
- L5 (기기)
- 2.5D
- 3D
- 기상레이어
- Study 비교
- 고급 MCP Tool

### Phase 3 게이트

| 게이트 | 조건 |
|--------|------|
| 게이트 G | GIS 지도 동작 |
| 게이트 H | SLD 렌더링 |
| 게이트 I | NL→지도 |

### 예측 기능

- **Prophet 부하예측**: 1~24시간
- **Open-Meteo 기상**: 실시간 기상 데이터
- **Pvlib 태양광**: 태양광 발전 예측

---

## Phase 4: 능동형 인사이트 + 통합 + 검증 — 2~3주

### 능동형 AI 인사이트 6종

| 인사이트 | 주기 | 설명 |
|---------|------|------|
| 1. 건전성 분석 | 5분 | 계통 전반의 건전성 자동 평가 |
| 2. 알람 스톰 | 즉시 | 대량 알람 발생 시 원인 자동 분석 |
| 3. 리스크 분석 | 1시간 | 향후 1시간 내 리스크 예측 |
| 4. 일일 리포트 | 매일 | 자동 생성 요약 리포트 |
| 5. 기상 영향 | 1시간 | 기상이 계통에 미치는 영향 분석 |
| 6. 이상 패턴 | 15분 | 비정상 패턴 자동 탐지 |

### 통합 테스트 (S1~S5)

| 시나리오 | 유형 | 내용 |
|---------|------|------|
| S1 | HOTL | 계통 조회 |
| S2 | HOTL | NL 지도 이동 |
| S3 | HITL | What-if Study |
| S4 | HITL | 알람 + 복구 |
| S5 | - | 능동형 인사이트 |

### Phase 4 추가 작업

- AI write 불가 검증
- SLM vs Cloud 비교
- 자동 리포트 생성
- CHANGELOG 작성
- 데모 시나리오 구성

---

## 주요 약자 및 용어

| 약자 | 의미 |
|------|------|
| MDP | Minimum Deployable Product (최소 동작 프로토타입) |
| HOTL | Human-Out-of-The-Loop (인간 제외) |
| HITL | Human-In-The-Loop (인간 참여) |
| TP | Topology Processor (토폴로지 프로세서) |
| SE | State Estimator (상태 추정기) |
| CA | Contingency Analyzer (상정사고 분석) |
| SCA | Short Circuit Analyzer (단락전류 분석) |
| RAG | Retrieval-Augmented Generation (검색 증강 생성) |
| SLM | Small Language Model (소형 언어 모델) |
| GIS | Geographic Information System (지리정보시스템) |
| SLD | Single Line Diagram (단일선 결선도) |
| MCP | Model Context Protocol |
| WLS | Weighted Least Squares (가중 최소제곱) |
| PTDF | Power Transfer Distribution Factor (조류분배계수) |
| AGC | Automatic Generation Control (자동발전제어) |
| SOP | Standard Operating Procedure (표준운영절차) |
| CB | Circuit Breaker (차단기) |

---

**최종 업데이트**: 2026-03-25
