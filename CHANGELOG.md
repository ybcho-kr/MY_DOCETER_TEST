# Changelog

All notable changes to AI-EMS v5.1 will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Changed
- requirements.txt: pandapower>=3.0으로 업데이트

### Fixed
- (없음)

## [0.1.0] - 2026-03-25

### Added
- 프로젝트 초기 디렉토리 구조
- CLAUDE.md 프로젝트 컨텍스트 문서
- docs/design/ 설계 문서
- docs/domain/ 도메인 데이터 (glossary.json, voltage_limits.json)
