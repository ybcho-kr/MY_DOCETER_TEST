# Layer 1 — EMS Digital Twin

## 이 디렉토리의 역할
pandapower 기반 전력 시뮬레이션 + SCADA 데이터 생성 + EMS 앱 스텁.
AI Agent(Layer 2)가 호출하는 "물리적 진실의 원천(source of truth)".

## v5.1 Phase 1 MDP 범위
Phase 1은 최소 동작 프로토타입(MDP). 아래 3개 게이트만 통과하면 Phase 2 진입:
- **게이트 A**: 한국 실계통 .raw → pandapower from_psse() → runpp() 수렴
- **게이트 B**: 4대 EMS 스텁(TP, SE, CA, SCA) FastAPI + Pydantic 반환
- **게이트 C**: SCADA 시뮬 4초 주기 Redis ops: 저장 + API 읽기

## 핵심 컴포넌트

### scada_simulator/ (Phase 1 필수)
- PSS/E .raw → pandapower from_psse() 변환
- APScheduler 4초 주기 runpp() 실행
- 결과를 Redis ops:bus:{id}:voltage, ops:line:{id}:loading 저장
- 한국 실계통 .raw 기반 (IEEE 테스트 케이스 아님)
- 수렴 실패 시: 이전 스냅샷 유지 + solved=false 플래그

### topology_processor/ (Phase 1 보너스)
- 차단기 상태 → bus merge/split → 네트워크 재구성
- Physical bus → Electrical bus 2계층 매핑
- 이중모선 지원
- ops:switch:{sw_id}:status 변경 시 Pub/Sub 트리거

### ems_stubs/ (Phase 1 필수: 4대 스텁)
- **tp/** (조류계산): POST /tp/powerflow, GET /tp/violations
  - Phase 1: 기본 runpp() + violations 반환
  - 보너스: ACOPF(runopp), N-1 2-Tier, VSA(CPF nose point)
- **se/** (상태추정): GET /se/run, GET /se/latest
  - Phase 1: WLS 기본 동작 + SEResult 반환
  - 보너스: 관측성 분석(Jacobian rank), pseudo-measurement, confidence_level
- **ca/** (상정고장): POST /tp/contingency
  - Phase 1: 기본 N-1 (전체 선로 순차 탈락)
  - 보너스: 2-Tier (Tier-1 상위 20건 실시간, PTDF screening)
- **sca/** (단락전류): POST /study/shortcircuit
  - Phase 1: 3상 단락전류 기본 계산
- **study/** (격리): POST /study/create
  - ops: COPY → study:{sid}:* → 격리 실행

### alarm_model/ (Phase 1 보너스)
- 4유형: LIMIT_VIOLATION, STATE_CHANGE, COMM_FAILURE, QUALITY
- Dead-band: 전압 ±0.005pu, 조류 ±2%, 주파수 ±0.01Hz
- 억제 규칙: 유지보수 억제, 조작 후 30초 과도기 억제
- 에스컬레이션: 동일 설비 3회/10분 → 심각도 상향
- 전압 기준 (고시 제3조): 345kV 조정목표 ±5%, 운용범위 ±10%
- 주파수 기준 (고시 제4조): 정상 60Hz ±0.2Hz, 최소 단일고장 59.7Hz

### forecast/ (Phase 3)
- Prophet 부하 예측 (1~24h)
- Open-Meteo API 기상 연동 (기온·일사·풍속)
- Pvlib 태양광 출력 추정
- Redis ops:forecast:load 저장

## 한국 전력 기준 (산업통상자원부고시 제2023-65호)
- 주파수: 60Hz ±0.2Hz 정상 (제4조). 최소: 단일고장 59.7Hz, 연쇄 59.5Hz
- 전압 조정목표: 345kV ±5%, 154kV 95~105%, 66kV 97~103%, 22.9kV 99~101% (제3조)
- 전압 운용범위: 345kV/154kV/66kV ±10% (제3조)
- 고장제거시간: 345kV 4사이클(66.7ms), 154kV 5사이클(83.3ms) (제25조)
- 조속기 droop: 수력 3~5%, 가스터빈 4~6%, 기력 4~6% (별표2)
- 예비력 5종: 주파수제어(5분), 초속응성(1초), 1차(10초), 2차(10분), 3차(30분) (제6조)

## 필수 규칙
1. pandapower 조류계산 수렴 실패 → 이전 스냅샷 유지 + FAILED 플래그
2. Golden Case 검증: 전압 편차 ±1% 이내
3. Redis 키 패턴: ops:bus:{id}:voltage, ops:line:{id}:loading
4. study: 네임스페이스 TTL 1800s 자동 삭제
5. lightsim2grid 백엔드 300+버스 시 필수 사용
6. 모든 API는 Pydantic v2 스키마 + FastAPI
7. **한국 실계통 .raw 기반** — IEEE 테스트 케이스 대신 보유 .raw 사용

## 한국 .raw 변환 시 예상 이슈
- Switched Shunt 미지원 → 수동 pandapower shunt 변환
- FACTS(SVC, STATCOM) 미지원 → 정적 shunt/generator 근사
- .raw v35 미파싱 → v30~v33 포맷 재저장
- 한글 bus_name 인코딩 → UTF-8/EUC-KR 확인
- 대규모 계통 수렴 실패 → lightsim2grid + init='results' + tolerance 조정

## Pydantic 공유 스키마 (src/shared/schemas/)
- PowerFlowResult: {converged, violations[], bus_results[], line_results[]}
- SEResult: {solved, bus_vm_pu[], residual, confidence_level, observable_ratio, ts}
- ContingencyResult: {tier, contingencies:[{element, violations[], rank}]}
- ShortCircuitResult: {fault_current_ka, affected_relays[]}
- StudyResult: {violations[], recommendations[], requires_hitl}
- AGCStatus: {frequency_hz, ace_mw, imbalance_mw, model_type, ts}
- AlarmEvent: {type, severity, element_id, value, threshold, ts}
- TopologyVersion: {version_id, changed_switches[], ts}

## 테스트 기준
- 한국 실계통 .raw: runpp() 수렴 성공
- Golden Case: 전압 편차 <1%
- Redis: ops: 키 저장/읽기 성공
- API: 4대 스텁 정상 응답 (Pydantic 검증 통과)
