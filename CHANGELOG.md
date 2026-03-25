# Changelog

All notable changes to AI-EMS v5.1 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Layer 2 AI 에이전트 구현 완료 (2026-03-26)**:
  - Layer 2 오케스트레이터 + Intent 분류기 구현
    (5개 Intent: QUERY_STATUS, ALARM_ANALYSIS, WHAT_IF_STUDY, NAVIGATE, DOMAIN_QA)
  - 5개 하위 에이전트 구현 (NL2App, RAG, AlarmAnalysis, Study, NLNavigation)
  - HITL Priority Queue 승인 모듈 구현 (CRITICAL/HIGH/MEDIUM/LOW 4등급)
  - AgentContext 세션 관리 + SessionSummarizer 구현
    (structured_facts FIFO 20건, evidence_chain 5단계 압축 금지)
  - MCP Gateway read_only 강제 + Provenance 로그 구현
    (ops: write 시도 HTTP 403 차단, 설계 원칙 2 완전 준수)
  - 전체 테스트 495개 통과 (Layer 1 334개 + Layer 2 161개)
- **Phase 1 게이트 A/B/C 전체 통과 (2026-03-26)**:
  - PSS/E v33 직접 파서 구현 (pandapower 3.x `from_psse` 제거 대응, ~700줄)
  - 한국 실계통 .raw (KEPCO 2034버스·2640버스) pandapower 수렴 성공 (게이트 A)
  - 알람 dead-band 하드코딩 → 도메인 JSON 참조로 변경 (frequency_limits.json)
  - AGC controller structlog 구조화 로깅 추가
  - SCADA/Redis 파이프라인 E2E 테스트 7종 추가 (게이트 C)
  - 전체 테스트 334개 통과, ops: write 위반 0건
- Phase 1 MDP 초기 구조 설정
- 공유 Pydantic v2 스키마 (grid, se, tp, agc, alarm, study, agent, common)
- 도메인 데이터 파일 (glossary, voltage_limits, frequency_limits, thermal_ratings, n1_criteria)
- DevOps 스크립트 (pre-commit-check, track-changes)
- **Layer 1 핵심 컴포넌트 구현**:
  - SCADA 시뮬레이터: IEEE 14-bus, APScheduler 4초 주기, Redis ops: 저장
  - 토폴로지 프로세서: 차단기 개폐, 전기적 섬 감지, 버전 관리
  - SE 스텁: WLS 상태추정, 관측성 분석, FastAPI 엔드포인트
  - TP 스텁: 조류계산, N-1 2-Tier (PTDF screening), VSA, FastAPI 엔드포인트
  - AGC 스텁: Δf/ACE 계산, 예비력 5종, GET-only (안전)
  - 알람 모델: 4유형, dead-band, 유지보수 억제, 에스컬레이션
  - EMS 스텁 통합 FastAPI 앱 (SE+TP+AGC)
  - Golden Case 검증 (편차 <1%)
- Layer 1 테스트 207개 (전체 통과)
- **Layer 1 2차 보강 (2026-03-25)**:
  - SCA 단락전류 스텁 신규 구현 (IEC 60909, 3상/1선지락/선간 고장)
  - Topology Processor 완성: Union-Find 알고리즘, Redis 연동, 이중모선 처리
  - SCADA Simulator 보강: Switched Shunt, 3권선 변압기, 스케줄러 개선
  - SE Bad Data Detection (BDD) 알고리즘, Pseudo-measurement 지원 추가
  - TP PTDF/LODF 민감도 행렬 계산 구현
  - shared/config 모듈 구현 (Redis 키 네임스페이스, API 경로 상수)
- 전체 테스트 327개 통과, 커버리지 84%

### Changed
- requirements.txt: pandapower>=3.0으로 업데이트
- shared/schemas/study.py: bus_id 제약 완화 (0 허용, IEEE 14-bus 호환)

### Fixed
- (없음)

## [0.1.0] - 2026-03-25

### Added
- 프로젝트 초기 디렉토리 구조
- CLAUDE.md 프로젝트 컨텍스트 문서
- docs/design/ 설계 문서
- docs/domain/ 도메인 데이터 (glossary.json, voltage_limits.json)
