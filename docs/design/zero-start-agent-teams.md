# AI-EMS — Agent Teams 기반 제로 스타트 가이드

> **Agent Teams ≠ Subagents**
> - **Subagents**: 메인 세션 안에서 Task로 스폰. 메인에게만 보고. 서로 소통 불가.
> - **Agent Teams**: 독립 Claude 세션 여러 개가 각자 worktree에서 병렬 작업. **공유 태스크 리스트 + 메일박스**로 서로 소통. 팀리더가 조율.
>
> **모델 구성**: 팀리더(Opus) → 팀원 스폰 시 `model: "sonnet"` 지정 → 비용 최적화
> Agent Teams는 Opus 4.6이 필수지만, 팀원 스폰 시 Task tool의 model 파라미터로 Sonnet 지정 가능

---

## STEP 0: 사전 준비

### 필수 조건
- **Claude Max 구독** ($100~200/월) — Agent Teams는 Opus 4.6 필수
- **Claude Code v2.1.32+** (`claude --version`으로 확인)
- **Git** 설치 완료
- **Python 3.11+**
- **tmux** 설치 (팀원별 분할 패널 보기용, 강력 추천)

```bash
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt install tmux

# Windows — WSL 안에서
sudo apt install tmux
```

### Claude Code 설치

```bash
# 네이티브 설치 (Node.js 불필요)
curl -fsSL https://claude.ai/install.sh | bash

# 설치 확인
claude --version
# v2.1.32 이상이어야 Agent Teams 사용 가능

# 첫 인증 (브라우저 자동 열림)
claude
# → 로그인 후 Ctrl+C로 종료
```

---

## STEP 1: 프로젝트 생성 + Git 초기화

```bash
# 1. GitHub 저장소 생성 (웹 또는 CLI)
mkdir ai-ems-prototype && cd ai-ems-prototype
git init
git checkout -b main

# 2. 디렉토리 골격 생성
mkdir -p .claude/agents .claude/commands scripts
mkdir -p docs/{design,domain,devlog/{decisions,benchmarks,retrospectives},references}
mkdir -p src/layer1/{scada_simulator,topology_processor}
mkdir -p src/layer1/ems_stubs/{se,tp,agc,sca,study}
mkdir -p src/layer1/{alarm_model,forecast}
mkdir -p src/layer2/{orchestrator,agents,hitl,context}
mkdir -p src/gateway
mkdir -p src/visualization/{map,sld,streamlit_app}
mkdir -p src/shared/{schemas,config,domain}
mkdir -p tests/{layer1,layer2,integration}
mkdir -p data/{psse_models,golden_cases,geo}

# 3. Python 패키지 인식
find src -type d -exec touch {}/__init__.py \;

# 4. 기본 파일
touch requirements.txt CHANGELOG.md .gitignore

# 5. develop 브랜치 생성
git add -A && git commit -m "chore: 프로젝트 초기 디렉토리 구조"
git checkout -b develop
```

---

## STEP 2: Agent Teams 활성화 설정

### settings.json — 이것이 핵심

```bash
# 수동으로 만들거나, Claude Code 안에서 만들어도 됩니다
mkdir -p .claude
```

`.claude/settings.json` 파일을 아래 내용으로 생성:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(python *)",
      "Bash(pip install *)",
      "Bash(pytest *)",
      "Bash(mkdir *)",
      "Bash(touch *)",
      "Bash(chmod *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(grep *)",
      "Bash(find *)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "MultiEdit(*)",
      "Grep(*)",
      "Glob(*)"
    ]
  }
}
```

> **중요**: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`가 `"1"`로 설정되어야 Agent Teams가 활성화됩니다. 이 설정 후 Claude Code를 **재시작**해야 합니다.

---

## STEP 3: CLAUDE.md 작성 — Claude Code 첫 진입

```bash
# Opus(팀리더)로 Claude Code 시작
claude --model claude-opus-4-6
```

> **이 터미널이 앞으로 "팀리더 세션"입니다.** 여기서 모든 지시가 나갑니다.

### 첫 번째 프롬프트 — CLAUDE.md 생성

```
프로젝트 루트에 CLAUDE.md를 작성해줘. 이건 모든 에이전트(팀리더+팀원 모두)가 읽는 프로젝트 컨텍스트야.

## 프로젝트: AI-EMS 독립 프로토타입
- 전력 EMS 운영을 자연어 기반 agentic AI로 지원하는 프로토타입
- 2-Layer(EMS Digital Twin + AI Agent) + API Gateway 아키텍처

## 절대 규칙 (모든 에이전트 필수 준수)
1. LLM 수치 생성 금지 — pandapower 솔버 반환값만 사용
2. Redis ops: 네임스페이스에 SCADA 시뮬 외 write 금지
3. 조회→HOTL(자동), 조치→HITL(운영자 승인)
4. 모든 AI 응답에 evidence_chain + snapshot_ts 포함
5. Pydantic v2 스키마 필수 (모든 API 입출력)
6. 테스트: pytest. 각 모듈에 test_ 파일 필수
7. 로깅: structlog (JSON). print() 금지
8. 타입힌트 필수

## 기술 스택
Python 3.11+, FastAPI, PydanticAI v0.7+, pandapower 3.x,
Redis 7.x, PostgreSQL 16+TimescaleDB, Streamlit, MapLibre GL JS,
Chroma+BGE-M3, vLLM/Ollama(Qwen2.5-7B)

## 전력 도메인 (산업통상자원부고시 제2023-65호)
- 전압: pu 단위. 조정목표: 345kV ±5%, 154kV 95~105%, 66kV 97~103%, 22.9kV 99~101%. 운용범위: ±10%
- 전력: MW/Mvar
- 주파수: 60Hz(한국), 정상 ±0.2Hz (고시 제4조). 최소: 단일고장 59.7Hz, 연쇄 59.5Hz
- N-1: 단일 설비 탈락 시 나머지 위반 없어야 함 (고시 제15조)
- 고장제거: 345kV 4사이클(66.7ms), 154kV 5사이클(83.3ms)
- 예비력 5종: 주파수제어(5분), 초속응성(1초), 1차(10초), 2차(10분), 3차(30분)

## 현재 Phase: Phase 1 — 기반 구축

## Agent Teams 작업 규칙
- 각 팀원은 자기 담당 디렉토리만 수정
- 공유 스키마(src/shared/schemas/)는 infra 팀원이 먼저 확정 후 다른 팀원이 참조
- 커밋은 Conventional Commits 형식: type(scope): 설명
- 커밋 footer에 Ref: C-XX-XX (설계 문서 컴포넌트 ID) 포함
```

### 두 번째 프롬프트 — 보조 파일

```
다음 파일들도 작성해줘:

1. .gitignore — Python 프로젝트 + __pycache__ + .claude/tmp/ + *.raw(큰 파일) + .env
2. requirements.txt — Phase 1 패키지:
   pandapower, lightsim2grid, fastapi, uvicorn[standard], pydantic>=2.0,
   redis, psycopg2-binary, apscheduler, structlog,
   pytest, pytest-asyncio, httpx, python-dotenv
3. src/layer1/CLAUDE.md — Layer 1 전용 규칙 (pandapower, Redis ops:, Golden Case ±1%)
4. src/layer2/CLAUDE.md — Layer 2 전용 규칙 (PydanticAI, HITL/HOTL, Evidence chain)
5. src/visualization/CLAUDE.md — 시각화 전용 규칙 (MapLibre, 시맨틱 줌, GIS)
```

---

## STEP 4: 첫 커밋

```
지금까지 만든 파일들을 커밋해줘.
git add -A && git commit -m "chore(infra): CLAUDE.md + 프로젝트 설정 + requirements.txt

프로젝트 초기 설정 완료:
- CLAUDE.md (루트 + Layer별 3개)
- .gitignore, requirements.txt
- Agent Teams 활성화 설정 (.claude/settings.json)
- 디렉토리 구조 (21개 컴포넌트 대응)

Ref: 프로젝트 초기화"
```

```
git push -u origin develop도 해줘.
```

---

## STEP 5: Agent Teams로 첫 팀 작업 — 공유 스키마

> **여기서부터 Agent Teams의 진짜 힘을 사용합니다.**

### 팀 생성 프롬프트

```
Phase 1 첫 번째 작업을 시작할 거야.
에이전트 팀을 만들어서 병렬로 작업하자.

팀을 만들어줘:

팀원 1 — "schema-builder":
  역할: 공유 Pydantic v2 스키마를 src/shared/schemas/에 작성
  Sonnet 모델 사용
  작성할 스키마:
  - grid.py: BusVoltage, LineLoading, GenDispatch, TopologyVersion
  - se.py: SEResult (solved, confidence_level, observable_ratio, unobservable_buses)
  - tp.py: PowerFlowResult, ContingencyResult(tier, contingencies), VSAResult
  - agc.py: AGCStatus (frequency_hz, ace_mw, model_type)
  - alarm.py: AlarmType(Enum: LIMIT/STATE/COMM/QUALITY), Alarm, AlarmSummary
  - study.py: StudyResult, ShortCircuitResult
  - agent.py: AgentContext, StructuredFact, EvidenceStep, AIResponse
  - common.py: Timestamp, ErrorResponse
  모든 필드에 Field(description=...) + 범위 검증 validator
  테스트: tests/layer1/test_schemas.py

팀원 2 — "domain-data":
  역할: 도메인 데이터 파일을 src/shared/domain/에 작성
  Sonnet 모델 사용
  ✅ 완료된 파일 (docs/domain/에 이미 구축됨 — src/shared/domain/으로 복사 필요):
  - glossary.json: 178개 EMS 핵심 용어 (KPX+KEPCO+고시 기반, pandapower 매핑 포함)
  - voltage_limits.json: 전압/주파수/예비력/고장제거/droop 등 13개 섹션 정량 기준
  추가 작성 필요:
  - frequency_limits.json: 주파수 기준 (voltage_limits.json에 포함되어 있으나 별도 파일 옵션)
  - thermal_ratings.json: 선로 열용량 기준 템플릿 (summer/winter/emergency)
  - n1_criteria.json: N-1 판단 기준
  schema-builder 팀원이 만드는 스키마를 참조해야 하니,
  진행 상황을 schema-builder에게 메시지로 확인해.

팀원 3 — "devops":
  역할: DevOps 인프라 설정
  Sonnet 모델 사용
  작성할 파일:
  - scripts/pre-commit-check.sh: pytest + ops: write 보호 검사 + 스키마 검증
  - scripts/track-changes.sh: 파일 변경 추적
  - CHANGELOG.md 초기 템플릿 (Keep a Changelog 형식)
  - docs/devlog/ 오늘 날짜 파일 초기 생성
  다른 팀원들의 작업 완료 후, 전체 변경사항을 정리해서
  각각 적절한 커밋으로 분리 커밋해줘.

모든 팀원은 CLAUDE.md의 규칙을 반드시 읽고 준수해.
공유 태스크 리스트로 진행 상황을 조율해줘.
```

### 이 프롬프트 실행 후 일어나는 일

1. **Opus(팀리더)**: 태스크 리스트 생성, 팀원 3명 스폰
2. **schema-builder(Sonnet)**: 자기 worktree에서 스키마 작성 시작
3. **domain-data(Sonnet)**: 용어 사전·기준값 JSON 작성 시작
4. **devops(Sonnet)**: 스크립트·CHANGELOG 작성 시작
5. 팀원들은 **메일박스**로 서로 진행 상황 공유
6. devops 팀원이 마지막에 **커밋 정리**

### tmux로 팀원들 실시간 관찰

Agent Teams 실행 중에 터미널에서 **↓ 화살표**를 누르면 팀원 패널로 이동할 수 있습니다. tmux 분할 모드(`split-pane`)를 사용하면 모든 팀원의 작업을 동시에 볼 수 있습니다.

---

## STEP 6: Phase 1 Layer 1 개발 — 두 번째 팀

스키마가 확정되면 다음 팀을 만듭니다:

```
스키마와 도메인 데이터가 확정됐어. 좋아.
이제 Layer 1 핵심 컴포넌트를 개발할 팀을 만들자.

에이전트 팀 생성:

팀원 1 — "scada-dev":
  역할: SCADA 시뮬레이터 + 토폴로지 프로세서
  Sonnet 모델
  위치: src/layer1/scada_simulator/ + src/layer1/topology_processor/
  작업:
  1. pandapower 내장 case14()로 IEEE 14-bus 네트워크 생성
  2. APScheduler 4초 주기 runpp() 실행
  3. Redis ops:bus:{id}:voltage, ops:line:{id}:loading 저장
  4. TopologyProcessor: 차단기 상태 → bus merge/split
  5. Golden Case 자동 검증 (편차 <1%)
  6. 수렴 실패 → 이전 스냅샷 유지 + FAILED 플래그
  src/shared/schemas/grid.py 스키마 사용해.
  테스트: tests/layer1/test_scada.py, test_topology.py

팀원 2 — "se-tp-dev":
  역할: SE 스텁 + TP 스텁
  Sonnet 모델
  위치: src/layer1/ems_stubs/se/ + src/layer1/ems_stubs/tp/
  작업 A — SE:
  1. FastAPI: GET /se/run, GET /se/latest, GET /se/observability
  2. pandapower WLS 상태추정
  3. 관측성 분석 (Jacobian rank)
  4. confidence_level = f(residual, observable_ratio, pseudo_ratio)
  작업 B — TP:
  1. POST /tp/powerflow, POST /tp/contingency, POST /tp/vsa
  2. N-1 CA 2-Tier (Tier-1: 상위20건, Tier-2: 전체)
  3. PTDF 기반 screening
  scada-dev에게 메시지 보내서 Redis 키 구조 확인하고 사용해.
  src/shared/schemas/se.py, tp.py 사용.
  테스트: tests/layer1/test_se.py, test_tp.py

팀원 3 — "agc-alarm-dev":
  역할: AGC 스텁 + 알람 모델
  Sonnet 모델
  위치: src/layer1/ems_stubs/agc/ + src/layer1/alarm_model/
  AGC:
  1. FastAPI GET만. Δf=-ΔP/(D+1/R), ACE=10·B·Δf
  2. POST/PUT 라우터 절대 없음
  알람 모델:
  1. 4유형: LIMIT_VIOLATION, STATE_CHANGE, COMM_FAILURE, QUALITY
  2. Dead-band: 전압 ±0.005pu, 조류 ±2%
  3. 억제 규칙: 유지보수 중 억제, 조작 후 30초 억제
  4. 에스컬레이션: 3회/10분 반복 시 심각도 상향
  src/shared/schemas/agc.py, alarm.py 사용.
  테스트 포함.

팀원 4 — "devops-commit":
  역할: 다른 팀원들 작업 완료 후 검수·커밋
  Sonnet 모델
  작업:
  1. 다른 3명의 작업 완료까지 대기 (태스크 리스트 모니터링)
  2. pytest 전체 실행
  3. ops: write 보호 위반 검사
  4. 팀원별로 적절한 브랜치에 커밋
  5. docs/devlog/오늘날짜.md 업데이트
  6. CHANGELOG.md 업데이트
  코드를 수정하지 않음. 문제 발견 시 해당 팀원에게 메시지로 알림.

작업 진행 상황은 공유 태스크 리스트로 관리해줘.
의존성: schema → scada/se-tp/agc-alarm → devops 순서.
```

---

## 매일 반복하는 워크플로우

### 아침 — 세션 시작

```bash
cd ai-ems-prototype
claude --model claude-opus-4-6
```

```
오늘의 devlog를 만들어줘.
어제 작업 이어서 확인해줘:
- git log --oneline -10
- 열린 이슈 목록
- 마지막 팀 작업 결과 요약
```

### 작업 중 — 팀 운영

```
# 새 팀 작업 시작
에이전트 팀을 만들어서 [작업 설명] 을 진행해줘.
팀원 구성: ...

# 기존 팀원에게 직접 지시 (↓ 화살표로 팀원 선택 후)
schema-builder, alarm.py에 AlarmConfig 스키마도 추가해줘.
dead_band 값과 suppression 규칙을 설정하는 모델이야.

# 팀 상태 확인
전체 팀 진행 상황 보여줘. 태스크 리스트 현황은?

# 특정 팀원의 작업 결과 확인
scada-dev의 Golden Case 검증 결과를 보여줘.
```

### 저녁 — 마무리

```
오늘 작업 마무리해줘.
1. 모든 팀원 작업 완료 확인
2. 미커밋 변경 있으면 정리해서 커밋
3. docs/devlog/오늘날짜.md 최종화
4. 내일 작업 계획
5. git push origin develop
```

---

## Phase별 팀 구성 요약

### Phase 1 (2-3주): 기반 구축

| 팀 | 팀원 | 모델 | 작업 |
|---|------|------|------|
| 팀1 | schema-builder | Sonnet | 공유 스키마 12개 |
| | domain-data | Sonnet | 용어사전·기준값 JSON |
| | devops | Sonnet | 스크립트·CHANGELOG |
| 팀2 | scada-dev | Sonnet | SCADA 시뮬+토폴로지 |
| | se-tp-dev | Sonnet | SE+TP 스텁 |
| | agc-alarm-dev | Sonnet | AGC+알람 모델 |
| | devops-commit | Sonnet | 검수·커밋·로그 |

### Phase 2 (2-3주): AI Agent

| 팀 | 팀원 | 모델 | 작업 |
|---|------|------|------|
| 팀3 | orchestrator-dev | Sonnet | 오케스트레이터+AgentContext |
| | agents-dev | Sonnet | 6종 에이전트 |
| | gateway-dev | Sonnet | MCP Gateway+Evidence |
| | devops-commit | Sonnet | 검수·커밋 |

### Phase 3 (2-3주): 시각화+예측

| 팀 | 팀원 | 모델 | 작업 |
|---|------|------|------|
| 팀4 | gis-dev | Sonnet | MapLibre+시맨틱 줌 |
| | sld-dev | Sonnet | D3 SLD+전기 심볼 |
| | forecast-dev | Sonnet | Prophet+Open-Meteo |
| | devops-commit | Sonnet | 검수·커밋 |

---

## 명령어 치트시트

| 명령 | 설명 |
|------|------|
| `claude --model claude-opus-4-6` | Opus(팀리더)로 시작 |
| `↓ 화살표 → Enter` | 팀원 패널로 이동 (직접 지시 가능) |
| `Shift+↑/↓` | 팀원 간 이동 |
| `Shift+Tab` (2회) | Plan Mode (팀리더를 조율만 하게) |
| `Ctrl+C` | 현재 작업 취소 |
| `Ctrl+D` | 세션 종료 |

---

## 트러블슈팅

### Agent Teams가 활성화 안 될 때

```bash
# settings.json 확인
cat .claude/settings.json | python3 -c "import sys,json; print(json.load(sys.stdin))"

# env 섹션에 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1" 확인
# Claude Code 재시작 필수
```

### 팀원 스폰이 느릴 때

팀원은 보통 20~30초 내에 스폰되어 1분 내에 결과를 생성하기 시작합니다. 3인 팀은 단일 세션 대비 약 3~4배 토큰을 사용하지만, 시간은 2배 이상 절약됩니다.

### 팀원 간 파일 충돌

팀원별 담당 디렉토리를 명확히 분리하세요. 같은 파일을 2명이 수정하면 충돌합니다.
- **좋음**: scada-dev→src/layer1/scada_simulator/, se-tp-dev→src/layer1/ems_stubs/
- **나쁨**: 두 팀원이 모두 src/shared/schemas/를 수정

### 비용 관리

- 3팀원 팀 1회 = 단일 세션의 약 3~4배 토큰
- Max 구독($100~200/월)이면 토큰 비용 포함
- 불필요한 팀 생성 자제. 순차 의존성이 큰 작업은 단일 세션이 효율적

---

## Phase 1 완료 체크리스트

```
Phase 1 완료 검증해줘:

- [ ] IEEE 14-bus 조류계산 수렴 100%
- [ ] Golden Case 편차 < 1%
- [ ] 토폴로지 프로세서 차단기 10건 시나리오 통과
- [ ] SE 관측성 분석 동작 확인
- [ ] N-1 Tier-1 (20건) < 2초
- [ ] AGC 간이 주파수 모델 동작
- [ ] 알람 4유형 + dead-band + 억제 정의 완료
- [ ] Pydantic 스키마 12개 정의 + 테스트 통과
- [x] 전력 용어 사전 178개 EMS 핵심 용어 (glossary.json 구축 완료)
- [x] 정량 기준값 파일 (voltage_limits.json 구축 완료 — 13개 섹션)
- [ ] 전체 pytest 통과
- [ ] CHANGELOG Phase 1 완성
- [ ] develop → main 머지 + v0.1.0 태그

모든 항목 통과하면 release/v0.1.0 브랜치 만들고 태그해줘.
```
