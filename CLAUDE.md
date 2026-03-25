# AI-EMS 독립 프로토타입 v5.1

## 프로젝트 개요
재생에너지·DER 확대 환경에서 전력 EMS 운영을 자연어 기반 agentic AI로
지원하는 프로토타입. 기존 EMS를 대체하지 않고 위에 얹히는 지능형 운영 계층.

**v5.1 핵심 변경 (v5.0 대비):**
1. Phase 1을 MDP(최소 동작 프로토타입)로 축소 — 한국 실계통 .raw 기반
2. 능동형 AI 인사이트 6종 → Phase 4로 이동
3. 시각화를 L1~L2(2D GIS) + L4(변전소 SLD)로 축소
4. pandapower 한계 탐구는 Phase 2+ 이후

## 핵심 설계 원칙 — 반드시 준수
1. **LLM 수치 생성 절대 금지** — 모든 수치는 pandapower 솔버 반환값만 사용
2. **ops/study 네임스페이스 격리** — AI는 ops: 절대 write 불가
3. **HITL/HOTL 이원 분류** — 조회→HOTL 자동, 조치→HITL 운영자 승인
4. **Evidence chain 필수** — AI 응답에 Tool 호출 근거 항상 포함
5. **snapshot_ts 필수** — 모든 응답에 분석 기준 시각 포함

## 아키텍처 (2-Layer + Gateway)
- **Layer 1**: EMS Digital Twin (pandapower, Redis, PostgreSQL, TimescaleDB)
- **API Gateway**: MCP Protocol. read_only 강제. Provenance 로그.
- **Layer 2**: AI Agent (PydanticAI, Qwen2.5-7B/Claude, 6개 에이전트)

## 기술 스택
- Python 3.11+, FastAPI, PydanticAI v0.7+, pandapower 3.x
- Redis 7.x, PostgreSQL 16 + TimescaleDB
- Streamlit 1.x, MapLibre GL JS, D3.js, Plotly
- Chroma (벡터DB), BGE-M3 (임베딩)
- vLLM / Ollama (SLM 서빙)

## 전력 도메인 핵심 규칙 (산업통상자원부고시 제2023-65호 기준)
- 전압 단위: pu (per unit). 전압별 조정목표: 345kV ±5%, 154kV 95~105%, 66kV 97~103%, 22.9kV 99~101%. 운용범위: 345kV/154kV/66kV ±10%
- 조류 단위: MW (유효전력), Mvar (무효전력)
- 부하율: loading_pct (100% 이상 = 과부하)
- 주파수: 60Hz 기준 (한국). 정상 ±0.2Hz (고시 제4조). 최소 허용: 단일고장 59.7Hz, 연쇄고장 59.5Hz
- N-1 기준: 단일 설비 탈락 시 나머지 위반 없어야 함 (고시 제15조)
- 고장제거시간: 345kV 4사이클(66.7ms), 154kV 5사이클(83.3ms) (고시 제25조)
- 예비력 5종: 주파수제어(5분), 초속응성(1초), 1차(10초), 2차(10분), 3차(30분) (고시 제6조)
- 한국 전력 용어: src/shared/domain/glossary.json 참조 (원본: docs/domain/glossary.json)

## 코드 컨벤션
- Pydantic v2 스키마 필수 (모든 API 입출력)
- 비동기: asyncio + httpx (FastAPI 간 통신)
- 로깅: structlog (JSON 구조화 로그)
- 테스트: pytest + pytest-asyncio
- 타입힌트 필수. mypy strict 호환 지향

## v5.1 MDP 철학 — Phase 1 진짜 목표
한국 .raw → pandapower 수렴 → Redis ops: 저장 → EMS 스텁 API → 결과 반환
이 한 줄의 파이프라인이 한국 실계통 .raw 파일에서 끊김 없이 동작하면 Phase 1은 성공.
토폴로지 프로세서, 관측성 분석, N-1 2-Tier 같은 고도화는 Phase 2+ "보너스".

## 디렉토리 구조
```
ai-ems/
├── CLAUDE.md                    # 프로젝트 전체 컨텍스트 (이 파일)
├── .cursorrules                 # Cursor IDE 룰 파일
├── docs/
│   ├── design/                  # 설계 문서 (.md)
│   │   ├── v51_architecture.md  # v5.1 아키텍처 설계
│   │   ├── v51_roadmap.md       # Phase별 로드맵
│   │   ├── component_specs.md   # 컴포넌트 명세
│   │   ├── data_flows.md        # 데이터 흐름 시나리오
│   │   ├── ui_gis_design.md     # GIS 시각화 설계
│   │   ├── domain_knowledge.md  # 도메인 지식 체계
│   │   ├── mcp_interface.md     # MCP Gateway 인터페이스
│   │   └── ai_insight.md        # 능동형 AI 인사이트
│   ├── domain/                  # 도메인 데이터 (JSON/CSV)
│   │   ├── glossary.json        # 전력 용어 사전
│   │   ├── voltage_limits.json  # 정량 기준
│   │   ├── alarm_codes.csv      # 알람 코드 사전
│   │   └── equipment_mapping.csv# 설비명↔bus_id
│   └── references/              # 참조 논문/보고서
├── src/
│   ├── layer1/                  # EMS Digital Twin
│   │   ├── CLAUDE.md
│   │   ├── scada_simulator/
│   │   ├── topology_processor/
│   │   ├── ems_stubs/           # TP, SE, CA, SCA, Study
│   │   ├── alarm_model/
│   │   └── forecast/
│   ├── layer2/                  # AI Agent
│   │   ├── CLAUDE.md
│   │   ├── orchestrator/
│   │   ├── agents/              # NL Nav, NL2App, RAG, Alarm, Study, Insight
│   │   ├── hitl/
│   │   └── context/             # AgentContext, CallGuard
│   ├── gateway/                 # API Gateway (MCP)
│   │   └── CLAUDE.md
│   ├── visualization/           # GIS + SLD + UI
│   │   ├── CLAUDE.md
│   │   ├── map/
│   │   ├── sld/
│   │   └── streamlit_app/
│   └── shared/
│       ├── schemas/             # Pydantic 공유 스키마
│       ├── config/              # Redis 키, API 경로
│       └── domain/              # 용어사전, 기준값 JSON
├── tests/
│   ├── layer1/
│   ├── layer2/
│   └── integration/
└── data/
    ├── psse_models/             # PSS/E .raw 파일
    ├── golden_cases/            # 검증 기준
    └── geo/                     # GeoJSON, PMTiles
```

## 언어 정책
- CLAUDE.md, 설계 문서, 코드 주석, docstring: **한국어**
- .cursorrules: 영어 (Cursor IDE 호환용)
- 변수명, 함수명, 클래스명: **영어** (PEP 8)
- AI 에이전트 응답 언어: **한국어** (사용자 대면)
- git 커밋 메시지: `type(scope):` 영어 + 본문 한국어 허용

## 테스트 기준
- 단위 테스트: 모든 스키마·스텁 모듈에 test_ 파일 필수
- 라인 커버리지 목표: ≥ 80% (pytest-cov)
- 통합 테스트: Redis 연동, API 엔드포인트 E2E
- 도메인 교차 검증: JSON 기준값 ↔ 스키마 validator 범위 일치

## 파일 참조
- 설계 문서: docs/design/v51_architecture.md
- 로드맵: docs/design/v51_roadmap.md
- 용어 사전 (원본): docs/domain/glossary.json
- 용어 사전 (런타임): src/shared/domain/glossary.json
- 정량 기준 (원본): docs/domain/voltage_limits.json
- 정량 기준 (런타임): src/shared/domain/voltage_limits.json
- 주파수 기준: src/shared/domain/frequency_limits.json
- N-1 기준: src/shared/domain/n1_criteria.json
- 열용량 기준: src/shared/domain/thermal_ratings.json
- 설비 매핑: docs/domain/equipment_mapping.csv
- 에이전트 역할: .claude/agents/*.md
