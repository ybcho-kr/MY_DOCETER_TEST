"""AI-EMS 공유 설정 모듈 — v5.1 Phase 1.

Redis 키 패턴, API 경로, 네임스페이스 상수, SCADA 주기 등
프로젝트 전역 상수를 정의한다.

중요 규칙:
  - OPS_PREFIX("ops:") 키는 AI(Layer 2)가 절대 write 불가 (설계 원칙 2)
  - STUDY_PREFIX("study:") 키만 AI write 허용
  - 모든 상수는 이 모듈에서 import하여 사용 (매직 문자열 금지)
"""
from __future__ import annotations

# ──────────────────────────────────────────────
# 네임스페이스 접두사
# ──────────────────────────────────────────────

#: 운영 네임스페이스 — AI write 절대 금지 (설계 원칙 2)
OPS_PREFIX: str = "ops:"

#: 해석 스터디 네임스페이스 — AI write 허용
STUDY_PREFIX: str = "study:"

#: SCADA 원시 데이터 네임스페이스
SCADA_PREFIX: str = "scada:"

#: 알람 네임스페이스
ALARM_PREFIX: str = "alarm:"

# ──────────────────────────────────────────────
# Redis 키 패턴 (ops: 네임스페이스)
# ──────────────────────────────────────────────

#: 모선 전압 키 패턴. 사용: OPS_BUS_VOLTAGE.format(bus_id=1)
OPS_BUS_VOLTAGE: str = "ops:bus:{bus_id}:voltage"

#: 선로 부하율 키 패턴
OPS_LINE_LOADING: str = "ops:line:{line_id}:loading"

#: 발전기 출력 키 패턴
OPS_GEN_OUTPUT: str = "ops:gen:{gen_id}:output"

#: 계통 주파수 키 (전역 단일 값)
OPS_FREQ_HZ: str = "ops:system:frequency_hz"

#: 조류계산 최신 결과 키
OPS_POWERFLOW_LATEST: str = "ops:powerflow:latest"

#: 상태 추정 최신 결과 키
OPS_SE_LATEST: str = "ops:se:latest"

#: AGC 상태 키
OPS_AGC_STATUS: str = "ops:agc:status"

#: 차단기(스위치) 상태 키 패턴
OPS_SWITCH_STATUS: str = "ops:switch:{sw_id}:status"

#: 예비력 현황 키
OPS_RESERVES: str = "ops:reserves:summary"

# ──────────────────────────────────────────────
# Redis 키 패턴 (study: 네임스페이스)
# ──────────────────────────────────────────────

#: 스터디 결과 키 패턴. 사용: STUDY_RESULT.format(sid="abc123")
STUDY_RESULT: str = "study:{sid}:result"

#: 단락전류 해석 결과 키 패턴
STUDY_SC_RESULT: str = "study:{sid}:shortcircuit"

#: 스터디 네임스페이스 TTL (초) — 설계 원칙: 1800s 자동 삭제
STUDY_TTL_SECONDS: int = 1800

# ──────────────────────────────────────────────
# Redis 키 패턴 (alarm: 네임스페이스)
# ──────────────────────────────────────────────

#: 활성 알람 목록 키 (Redis List)
ALARM_ACTIVE_LIST: str = "alarm:active"

#: 알람 상세 키 패턴
ALARM_DETAIL: str = "alarm:{alarm_id}:detail"

# ──────────────────────────────────────────────
# API 엔드포인트 경로
# ──────────────────────────────────────────────

#: Layer 1 EMS 스텁 API 기본 URL (로컬 개발)
LAYER1_API_BASE_URL: str = "http://localhost:8001"

#: Layer 2 AI 에이전트 API 기본 URL (로컬 개발)
LAYER2_API_BASE_URL: str = "http://localhost:8002"

#: MCP Gateway API 기본 URL (로컬 개발)
GATEWAY_API_BASE_URL: str = "http://localhost:8000"

# TP 엔드포인트
TP_POWERFLOW_PATH: str = "/tp/powerflow"
TP_CONTINGENCY_PATH: str = "/tp/contingency"
TP_VSA_PATH: str = "/tp/vsa"
TP_VIOLATIONS_PATH: str = "/tp/violations"

# SE 엔드포인트
SE_RUN_PATH: str = "/se/run"
SE_LATEST_PATH: str = "/se/latest"
SE_OBSERVABILITY_PATH: str = "/se/observability"

# AGC 엔드포인트
AGC_STATUS_PATH: str = "/agc/status"
AGC_RESERVES_PATH: str = "/agc/reserves"

# SCA 엔드포인트
SCA_RUN_PATH: str = "/sca/run"
SCA_BUS_PATH: str = "/sca/bus/{bus_id}"

# ──────────────────────────────────────────────
# SCADA 시뮬레이터 설정
# ──────────────────────────────────────────────

#: SCADA 데이터 수집 주기 (초). 4초 = 표준 EMS 스캔 주기
SCADA_SCAN_INTERVAL_SEC: int = 4

#: 수렴 실패 시 Redis 키 만료 유예 (초)
SCADA_STALE_TTL_SEC: int = 30

#: pandapower Newton-Raphson 최대 반복 횟수
PP_MAX_ITERATION: int = 30

#: pandapower 수렴 허용 오차
PP_TOLERANCE_MVA: float = 1e-8

# ──────────────────────────────────────────────
# 전력 도메인 임계값 — 산업통상자원부고시 제2023-65호
# ──────────────────────────────────────────────

#: 한국 공칭 주파수 (Hz)
NOMINAL_FREQ_HZ: float = 60.0

#: 정상 주파수 편차 허용 범위 (Hz) — 고시 제4조
FREQ_NORMAL_DEVIATION_HZ: float = 0.2

#: 단일 고장 시 최소 허용 주파수 (Hz) — 고시 제4조
FREQ_MIN_SINGLE_FAULT_HZ: float = 59.7

#: 연쇄 고장 시 최소 허용 주파수 (Hz) — 고시 제4조
FREQ_MIN_CASCADE_HZ: float = 59.5

#: 전압 운용 하한 (pu) — 345kV/154kV/66kV ±10% 운용범위
VOLTAGE_OP_MIN_PU: float = 0.9

#: 전압 운용 상한 (pu)
VOLTAGE_OP_MAX_PU: float = 1.1

#: 선로 과부하 임계값 (%) — 이 이상이면 CRITICAL
LINE_OVERLOAD_CRITICAL_PCT: float = 100.0

#: 선로 과부하 경고 임계값 (%) — 이 이상이면 WARNING
LINE_OVERLOAD_WARNING_PCT: float = 80.0

#: 알람 dead-band — 전압 (pu)
ALARM_DEADBAND_VOLTAGE_PU: float = 0.005

#: 알람 dead-band — 조류 (%)
ALARM_DEADBAND_LOADING_PCT: float = 2.0

#: 알람 dead-band — 주파수 (Hz)
ALARM_DEADBAND_FREQ_HZ: float = 0.01

#: 알람 에스컬레이션 기준: 동일 설비 N회/10분 → 심각도 상향
ALARM_ESCALATION_COUNT: int = 3

#: 알람 에스컬레이션 시간 창 (초)
ALARM_ESCALATION_WINDOW_SEC: int = 600

#: 조작 후 과도기 억제 시간 (초)
ALARM_SUPPRESSION_POST_ACTION_SEC: int = 30

# ──────────────────────────────────────────────
# 단락전류 분석 설정
# ──────────────────────────────────────────────

#: 기본 단락전류 고장 유형 — 3상 단락 (Phase 1 기본)
SCA_DEFAULT_FAULT_TYPE: str = "3ph"

#: IEC 60909 전압 계수 c (3상 단락 최대)
SCA_VOLTAGE_FACTOR_C_MAX: float = 1.1

#: IEC 60909 전압 계수 c (3상 단락 최소)
SCA_VOLTAGE_FACTOR_C_MIN: float = 1.0

# ──────────────────────────────────────────────
# N-1 상정고장 설정
# ──────────────────────────────────────────────

#: Tier-1 PTDF screening 기본 선별 건수
N1_TIER1_TOP_N: int = 20

#: N-1 조류계산 타임아웃 (초) — 단일 케이스
N1_POWERFLOW_TIMEOUT_SEC: int = 10
