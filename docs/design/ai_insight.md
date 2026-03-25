# AI-EMS v5.1 능동형 AI 인사이트 6종 상세 설계

## 1. 개요

### 1.1 설계 목표
AI-EMS v5.1은 능동형 AI 인사이트 6종을 Phase 4로 이동하여 구현한다. 계통 안정성 보장과 운영 효율성 극대화를 위해 APScheduler 기반의 자동 실행 체계를 구축한다. 운영자의 능동적 질의 없이 계통이 자체적으로 이상을 감지·분석·보고하는 지능형 시스템을 구현한다.

### 1.2 핵심 설계 원칙
- **능동 모니터링**: 운영자 질의 없이 계통을 지속적으로 감시
- **정량 기준 우선**: JSON 설정값 직접 참조, RAG 검색으로 인한 지연 제거
- **자동 일정 실행**: APScheduler를 통한 주기적·이벤트 기반 실행
- **HOTL/HITL 자동 분류**: 인사이트 유형에 따른 자동 라우팅
- **Redis 기반 상태 관리**: 실시간 결과 저장 및 조회

### 1.3 Phase 별 구현 전략
- **Phase 2**: 센서 데이터, 선조류 계산(SE), 부하 예측 기반 확보
- **Phase 3**: 기상 API 연동, 알람 처리, 예측 모델 정확도 향상
- **Phase 4**: APScheduler 통합, 6종 인사이트 구현, 통합 테스트

---

## 2. 인사이트 6종 상세 설계

### J1: 계통 건전성 점검 (Grid Health Check)

#### 2.1.1 목적 및 범위
실시간으로 계통의 물리적 안전 조건을 점검하여 한계 접근 상황을 조기에 감지하고 운영자에게 정보를 제공한다. 정상 범위 내에서는 침묵(Silent)하여 정보 과잉을 방지한다.

#### 2.1.2 실행 일정
```python
scheduler.add_job(
    grid_health_check,
    'interval',
    minutes=5,
    id='j1_grid_health_check',
    name='Grid Health Check',
    coalesce=True,
    max_instances=1
)
```
- **주기**: 5분 (300초)
- **타임아웃**: 30초
- **실패 재시도**: 최대 2회 (1분 간격)

#### 2.1.3 점검 기준 및 임계값

##### 2.1.3.1 전압 (Voltage) — 산업통상자원부고시 제2023-65호 기준
- **조정목표(345kV)**: ±5% (0.95~1.05 p.u.) — 고시 제3조
- **경계 범위**: 조정목표 이탈 시 (전압별 상이)
  - 345kV: ±5% 이탈 시 경고, 154kV: 95~105% 이탈 시 경고
  - 경계 진입 시: 운영자 주의 경고
  - 정상 복귀: 침묵
- **운용범위(한계)**: ±10% (345kV/154kV/66kV 공통) — 고시 제3조
  - 사전 경고 + 원인 추정
  - 예: '11번 모선 전압 110.2%, 과여자 발전기 G5 원인 추정'

**설정 파일 (voltage_limits.json)** — 고시 기반:
```json
{
  "voltage_criteria": {
    "345kV": {"target_min": 95.0, "target_max": 105.0, "operating_min": 90.0, "operating_max": 110.0},
    "154kV": {"target_min": 95.0, "target_max": 105.0, "operating_min": 90.0, "operating_max": 110.0},
    "66kV": {"target_min": 97.0, "target_max": 103.0, "operating_min": 90.0, "operating_max": 110.0},
    "22.9kV": {"target_min": 99.0, "target_max": 101.0, "operating_min": 94.0, "operating_max": 106.0},
    "unit": "percentage",
    "reference": "산업통상자원부고시 제2023-65호 제3조"
  }
}
```

##### 2.1.3.2 선로 조류 (Line Current)
- **한계**: 열용량(열적 제한)의 75%
- **경계**: 70%
  - 70~75%: 과부하 경향 경고
  - 경계 진입 이유: '방한기 최대 부하, 북부 라인 과부하, 모선 3·4 선로 쌍도선'

**설정 파일 (thermal_limits.json)**:
```json
{
  "line_limits": {
    "L001": {
      "thermal_limit_amp": 1200,
      "warning_threshold": 0.70,
      "critical_threshold": 0.75,
      "description": "345kV 북부 메인 라인"
    }
  }
}
```

##### 2.1.3.3 발전기 (Generator)
- **용량 대비 출력**: 최대 90%
- **90% 초과**: '발전기 G2 출력 95%, 과부하 위험'

##### 2.1.3.4 전압 안정도 마진 (VSM, Voltage Stability Margin)
- **한계**: 10% 미만
- **경계**: 15%
  - VSM < 15%: '계통 전압 안정도 악화, 무효전력 공급 필요'

#### 2.1.4 실행 알고리즘

```
def grid_health_check():
    1. 최신 상태 데이터 조회 (Redis: SCADA)
       - 모든 모선 전압
       - 모든 선로 조류
       - 모든 발전기 출력
       - VSM 계산값

    2. voltage_limits.json에서 임계값 로드
    3. thermal_limits.json에서 열제한 로드
    4. 모든 데이터에 대해 점검 루프:

       FOR EACH 모선:
           현재 전압 vs. 임계값 비교
           IF 초과한 카테고리 있음:
               root cause 추정 (기여도 분석)
               insight 생성 및 저장

       FOR EACH 선로:
           현재 조류 / 열용량 비율 계산
           IF 비율 > 임계값:
               과부하 원인 분석
               insight 생성

       FOR EACH 발전기:
           현재 출력 vs. 용량 비교
           IF 출력 > 90%:
               insight 생성

       IF VSM < 10%:
           무효전력 추천

    5. 모든 이상 insights을 ops:insight:health에 저장 (TTL: 5분)
    6. 정상이면 Redis 업데이트만 수행 (보고 없음)
```

#### 2.1.5 출력 형식
```json
{
  "timestamp": "2026-03-25T14:30:45.123Z",
  "type": "J1_GRID_HEALTH",
  "severity": "WARNING",
  "findings": [
    {
      "category": "VOLTAGE",
      "bus_id": "BUS_011",
      "bus_name": "인천 345kV",
      "current_value": 105.2,
      "unit": "%",
      "threshold": 105.0,
      "status": "CRITICAL",
      "root_cause_estimate": "발전기 G5 과여자 (출력 92%), 북부 라인 과부하 조합"
    },
    {
      "category": "THERMAL",
      "line_id": "L089",
      "line_name": "서부-남부 345kV",
      "current_amp": 950,
      "thermal_limit_amp": 1200,
      "ratio": 0.792,
      "threshold": 0.75,
      "status": "WARNING",
      "root_cause_estimate": "방한기 냉방 부하 +12%, 태양광 발전 50% 감소"
    }
  ],
  "actions_recommended": [
    "가동중인 발전기 중 출력 제어 가능한 기저부하 발전소 확인",
    "선로 3번 모선 선로 전력 이동 가능성 검토"
  ],
  "mode": "HOTL",
  "related_insights": []
}
```

#### 2.1.6 HOTL 분류 근거
- 정보 제공 목적
- 운영자 판단을 위한 배경 제공
- 즉시 조치 불필요
- 모니터링 강화 권고

---

### J2: 알람 스톰 자동 분석 (Alarm Storm Analysis)

#### 2.2.1 목적 및 범위
계통 이상 시 순간적으로 폭증하는 연쇄 알람(Alarm Storm)을 자동으로 감지하고, 시간·공간 클러스터링을 통해 근본 원인을 파악한 후 운영자가 효과적인 복구 조치를 취하도록 지원한다.

#### 2.2.2 실행 메커니즘

##### 2.2.2.1 이벤트 기반 트리거
```python
redis_pubsub = redis.StrictRedis().pubsub()
redis_pubsub.subscribe('ops:alarm')

def alarm_handler(message):
    # 알람 도착 시 즉시 처리
    alarm_storm_detector.check_storm(message)
```

##### 2.2.2.2 알람 스톰 판정 기준
```
알람 스톰 조건:
  5초 내에 3건 이상의 연쇄 알람 발생

판정 알고리즘:
  1. 알람 도착 시 timestamp 기록
  2. 5초 내 이전 알람들과 비교
  3. 누적 건수 >= 3 시 스톰으로 인정
  4. 스톰 시작 후 10초 동안 추가 알람 수집
```

#### 2.2.3 분석 알고리즘

##### 2.2.3.1 시간·공간 클러스터링
```
DBSCAN (Density-Based Spatial Clustering):
  - Feature 1: 알람 발생 시간 (초 단위)
  - Feature 2: 알람 발생 위치 (모선/선로 ID를 벡터로 변환)
  - eps: 10초, min_samples: 2
  - 클러스터 개수 및 구성 파악

결과:
  Cluster 1: 시간적으로 근접 + 공간적으로 근접 (주요 이상지점)
  Cluster 2: 원격 영향 알람 (파생)
  Outlier: 독립적 발생 알람
```

##### 2.2.3.2 근본 원인 상위 3개 추론
```
Root Cause 후보 추출:
  1. Cluster 1의 알람 내용 분석
     - '과부하', '저전압', '과전류' 등 키워드 추출

  2. 각 알람의 발생 지점 모선/선로 수집

  3. 과거 알람 데이터 RAG 검색
     - Query: "모선 L089 과부하 알람 연쇄 발생 원인"
     - Top 5 과거 유사 패턴 검색

  4. 점수 계산 (가중치 적용):
     score = (시간적 근접도 × 0.4) + (공간적 근접도 × 0.4) +
             (과거 패턴 일치도 × 0.2)

  5. 상위 3개 순위 결정
```

#### 2.2.4 분석 결과 출력

```json
{
  "timestamp": "2026-03-25T14:32:12.456Z",
  "type": "J2_ALARM_STORM",
  "severity": "CRITICAL",
  "storm_detected": true,
  "storm_duration_sec": 12,
  "total_alarms": 18,
  "analysis": {
    "clustering": {
      "cluster_1": {
        "size": 12,
        "description": "L089 과부하 + 모선 3·4 저전압",
        "primary_location": "L089, BUS_003, BUS_004",
        "time_window": "2026-03-25T14:32:00-14:32:10Z"
      },
      "cluster_2": {
        "size": 5,
        "description": "파생 알람 (영향 전파)",
        "affected_areas": ["G2 출력 제한", "선로 L045 선로탈출"]
      },
      "outlier": {
        "size": 1,
        "description": "독립적 센서 이상"
      }
    },
    "root_cause_candidates": [
      {
        "rank": 1,
        "cause": "L089 과부하가 근본 원인",
        "confidence": 0.92,
        "reasoning": "L089 과부하 알람이 시간적·공간적 클러스터 중심",
        "supporting_evidence": [
          "15:32:00 L089 과부하 알람 첫 발생",
          "15:32:02 모선 3 저전압 알람 (L089 영향권역)",
          "15:32:04 모선 4 저전압 알람 (연쇄)",
          "과거 유사 패턴 2023-08-15, 2024-11-20 (일치도 0.85)"
        ],
        "affected_count": 8
      },
      {
        "rank": 2,
        "cause": "모선 3 컨버터 고장",
        "confidence": 0.68,
        "reasoning": "모선 3 저전압이 초기 원인일 가능성",
        "affected_count": 7
      },
      {
        "rank": 3,
        "cause": "북부 라인 선로탈출 (낙뢰)",
        "confidence": 0.55,
        "reasoning": "동일 시간대 기상 이상 기록",
        "affected_count": 6
      }
    ],
    "historical_patterns": {
      "similar_events_count": 2,
      "recovery_time_avg_min": 18,
      "most_recent": "2024-11-20T09:45:00Z (복구 시간 22분)"
    }
  },
  "recovery_actions": [
    {
      "priority": 1,
      "action": "L089 트립 확인 및 즉시 복구",
      "sop_reference": "SOP 3.2.1",
      "expected_impact": "8개 파생 알람 해결"
    },
    {
      "priority": 2,
      "action": "무효전력 공급 확대 (G1, G3 동기조상기 활용)",
      "sop_reference": "SOP 2.4.3",
      "expected_impact": "모선 3·4 전압 회복"
    },
    {
      "priority": 3,
      "action": "선로 L045 수동 폐쇄 검토 (파생 알람 경감)",
      "sop_reference": "SOP 3.1.2",
      "expected_impact": "부하 재분배, 안정도 향상"
    }
  ],
  "mode": "HITL",
  "urgency": "IMMEDIATE"
}
```

#### 2.2.5 HITL 분류 근거
- 즉시 조치 필요 (운영자 판단 필수)
- 구체적 복구 절차 제시 (SOP 참조)
- 조치 우선순위 제공
- 복구 후 영향도 예측

---

### J3: 단기 리스크 평가 (Short-term Risk Assessment)

#### 2.3.1 목적 및 범위
향후 1시간의 계통 부하 변화를 예측하고, 예측된 부하 기반의 선조류 계산을 통해 N-1 상황에서의 위험도 변화를 평가한다. 피크 시간대 임박한 한계 접근을 조기에 감지하여 예방적 조치를 권고한다.

#### 2.3.2 실행 일정
```python
scheduler.add_job(
    risk_assessment,
    'interval',
    hours=1,
    id='j3_risk_assessment',
    name='Short-term Risk Assessment',
    coalesce=True,
    max_instances=1
)
```
- **주기**: 1시간
- **예측 범위**: 현재 시각으로부터 1시간
- **타임아웃**: 120초

#### 2.3.3 분석 3단계 파이프라인

##### 2.3.3.1 Stage 1: 부하 예측 (1시간 예측)
```
도구: Prophet (Facebook의 시계열 예측 라이브러리)

입력 데이터:
  - 과거 30일 시간별 부하 데이터
  - 계절성 (일별, 주별)
  - 외부 회귀변수: 기온, 휴일, 요일

출력:
  - 향후 1시간 부하 예측값 (yhat)
  - 신뢰도 상한 (yhat_upper)
  - 신뢰도 하한 (yhat_lower)
  - 신뢰도 = 95%

모델 파라미터:
  - interval_width: 0.95
  - seasonality_mode: 'additive'
  - changepoint_prior_scale: 0.05
```

**예측 결과 예시**:
```
현재: 14:30, 부하 3,200 MW
예측:
  14:35: 3,240 MW (신뢰도 3,100~3,380)
  14:40: 3,290 MW (신뢰도 3,140~3,440)
  14:45: 3,350 MW (신뢰도 3,180~3,520)
  14:50: 3,420 MW (신뢰도 3,220~3,620)  <- 피크 임박
  14:55: 3,480 MW (신뢰도 3,260~3,700)
  15:00: 3,500 MW (신뢰도 3,280~3,720)
  15:30: 3,350 MW (신뢰도 3,140~3,560)
```

##### 2.3.3.2 Stage 2: 조류 재계산 (최악의 경우 분석)
```
조류 계산 엔진 (Power Flow):
  입력: 예측된 부하 분포

  N-1 분석:
    FOR EACH 주요 발전기/선로:
        1) 해당 발전기/선로 제거 시뮬레이션
        2) 재조류 계산
        3) 선로 조류 & 모선 전압 확인
        4) 한계 초과 여부 판정
        5) 위험도 점수 계산

  위험도 점수 = (선로 조류 비율) × 0.6 + (전압 이탈도) × 0.4
  - 비율 = 현재 조류 / 열용량
  - 전압 이탈도 = |Vactual - Vnominal| / Vnominal
```

**N-1 분석 결과 예시**:
```
현재 (N):
  - L089 조류 비율: 0.68
  - 모선 3 전압: 99.5%
  - 종합 위험도: 0.25 (안전)

N-1 분석 (발전기 G2 탈락 시나리오 @ 15:00 예측 부하):
  - L089 조류 비율: 0.92 <- 한계 (0.75) 초과!
  - 모선 3 전압: 94.2% <- 경계 (97%)
  - 종합 위험도: 0.78 (위험)

N-1 분석 (발전기 G3 탈락 시나리오):
  - L089 조류 비율: 0.81
  - 모선 3 전압: 96.1%
  - 종합 위험도: 0.68 (경고)

N-1 분석 (선로 L045 탈락 시나리오):
  - 영향 최소 (주변 선로 분산 가능)
  - 종합 위험도: 0.35 (안전)
```

##### 2.3.3.3 Stage 3: VSM 추이 분석
```
VSM (Voltage Stability Margin) 계산:
  - 현재 VSM: 22%
  - 예측 VSM (15:00): 15% <- 경계 접근
  - 변화 추이: -7% (악화)

VSM 악화 요인:
  - 무효전력 수요 증가 (냉방 부하 +8%)
  - 발전기 여유 용량 감소 (G2 출력 제한)
  - 선로 부하 증가로 손실 증가
```

#### 2.3.4 분석 결과 출력

```json
{
  "timestamp": "2026-03-25T14:30:00.000Z",
  "type": "J3_RISK_ASSESSMENT",
  "severity": "WARNING",
  "forecast_horizon": "2026-03-25T15:30:00Z",
  "stage_1_load_forecast": {
    "current_load_mw": 3200,
    "forecast_points": [
      {
        "time": "2026-03-25T14:50:00Z",
        "forecast_mw": 3420,
        "confidence_upper_mw": 3620,
        "confidence_lower_mw": 3220,
        "trend": "RISING"
      },
      {
        "time": "2026-03-25T15:00:00Z",
        "forecast_mw": 3500,
        "confidence_upper_mw": 3720,
        "confidence_lower_mw": 3280,
        "trend": "PEAK",
        "note": "냉방 부하 피크 예상"
      },
      {
        "time": "2026-03-25T15:30:00Z",
        "forecast_mw": 3350,
        "confidence_upper_mw": 3560,
        "confidence_lower_mw": 3140,
        "trend": "FALLING"
      }
    ],
    "model_confidence": 0.87
  },
  "stage_2_n1_analysis": {
    "reference_time": "2026-03-25T15:00:00Z",
    "reference_load_mw": 3500,
    "contingencies": [
      {
        "contingency_id": "G2_OUTAGE",
        "contingency_name": "발전기 G2 탈락",
        "risk_score": 0.78,
        "risk_level": "HIGH",
        "critical_elements": [
          {
            "element_id": "L089",
            "element_name": "서부-남부 345kV",
            "current_ratio": 0.92,
            "limit": 0.75,
            "violation": true,
            "overload_margin_percent": 17.0,
            "recovery_action": "G1 출력 증가 또는 L045 폐쇄"
          },
          {
            "element_id": "BUS_003",
            "element_name": "인천 345kV",
            "voltage_pu": 0.942,
            "limit_lower": 0.97,
            "violation": true,
            "recovery_action": "동기조상기 가동 또는 콘덴서 투입"
          }
        ]
      },
      {
        "contingency_id": "G3_OUTAGE",
        "contingency_name": "발전기 G3 탈락",
        "risk_score": 0.68,
        "risk_level": "MEDIUM",
        "critical_elements": [
          {
            "element_id": "L089",
            "element_name": "서부-남부 345kV",
            "current_ratio": 0.81,
            "limit": 0.75,
            "violation": true,
            "overload_margin_percent": 8.0
          }
        ]
      },
      {
        "contingency_id": "L045_OUTAGE",
        "contingency_name": "선로 L045 탈락",
        "risk_score": 0.35,
        "risk_level": "LOW",
        "critical_elements": []
      }
    ]
  },
  "stage_3_vsm_analysis": {
    "current_vsm_percent": 22.0,
    "forecast_vsm_percent": 15.0,
    "vsm_trend": "DETERIORATING",
    "vsm_change_percent": -7.0,
    "warning_threshold_percent": 15.0,
    "critical_threshold_percent": 10.0,
    "degradation_factors": [
      {
        "factor": "냉방 부하 증가",
        "impact_percent": -4.2,
        "controllability": "LOW"
      },
      {
        "factor": "발전기 여유 용량 감소",
        "impact_percent": -2.1,
        "controllability": "HIGH"
      },
      {
        "factor": "선로 손실 증가",
        "impact_percent": -0.7,
        "controllability": "MEDIUM"
      }
    ]
  },
  "recommended_actions": [
    {
      "priority": 1,
      "time_window": "14:45~15:00",
      "action": "발전기 G2 출력 예약 (현재 대비 +150MW)",
      "sop_reference": "SOP 2.2.1",
      "expected_impact": "N-1 위험도 0.78 → 0.42 감소",
      "feasibility": "HIGH"
    },
    {
      "priority": 2,
      "time_window": "14:50~15:00",
      "action": "동기조상기 용량 증가 (STATCOM 50MVAr 투입)",
      "sop_reference": "SOP 2.4.3",
      "expected_impact": "VSM 회복 15% → 18%, 모선 3 전압 개선",
      "feasibility": "HIGH"
    },
    {
      "priority": 3,
      "time_window": "14:55~15:05",
      "action": "부하 분산 검토 (수요 관리 프로그램 활성화)",
      "sop_reference": "SOP 5.1.2",
      "expected_impact": "피크 부하 -3% (약 100MW), 여유 제공",
      "feasibility": "MEDIUM"
    }
  ],
  "mode": "HITL",
  "urgency": "HIGH"
}
```

#### 2.3.5 HITL 분류 근거
- 조치 권고 필수 (운영자 판단)
- 구체적 실행 시간 윈도우 제시
- 조치 효과 정량 평가
- 실행 가능성 평가

---

### J4: 일일 리포트 (Daily Report)

#### 2.4.1 목적 및 범위
지난 24시간의 계통 운영 현황을 종합적으로 정리하여 운영 조직에 보고한다. 통계 기반의 객관적 정보와 이상 징후를 정리하여 야간 또는 다음 근무 시작 시점의 운영 상황 파악을 지원한다.

#### 2.4.2 실행 일정
```python
scheduler.add_job(
    daily_report,
    'cron',
    hour=6,
    minute=0,
    timezone='Asia/Seoul',
    id='j4_daily_report',
    name='Daily Report',
    coalesce=True,
    max_instances=1
)
```
- **실행 시각**: 매일 06:00 (한국 표준시)
- **보고 범위**: 전일 00:00~23:59 (24시간)
- **생성 포맷**: PDF + Markdown
- **배포**: 이메일 자동 전송

#### 2.4.3 리포트 구성

##### 2.4.3.1 전압 통계
```json
{
  "section": "전압 현황 통계",
  "metrics": [
    {
      "bus_id": "BUS_001",
      "bus_name": "서울 345kV",
      "min_voltage_pu": 0.968,
      "max_voltage_pu": 1.043,
      "avg_voltage_pu": 1.002,
      "std_dev": 0.018,
      "time_min_volt": "2026-03-24T22:15:00Z",
      "time_max_volt": "2026-03-24T10:30:00Z",
      "violations_count": 0,
      "warnings_count": 2,
      "status": "NORMAL"
    },
    {
      "bus_id": "BUS_003",
      "bus_name": "인천 345kV",
      "min_voltage_pu": 0.954,
      "max_voltage_pu": 1.052,
      "avg_voltage_pu": 0.998,
      "std_dev": 0.024,
      "time_min_volt": "2026-03-24T18:45:00Z",
      "time_max_volt": "2026-03-24T07:20:00Z",
      "violations_count": 1,
      "warnings_count": 5,
      "status": "WARNING",
      "note": "18:45 저전압 한계 일시 도달, 원인: 남부 부하 급증 + G2 출력 제한"
    }
  ],
  "summary": {
    "total_buses": 12,
    "normal_count": 10,
    "warning_count": 2,
    "critical_count": 0,
    "overall_status": "NORMAL"
  }
}
```

##### 2.4.3.2 조류 통계
```json
{
  "section": "선로 조류 현황 통계",
  "metrics": [
    {
      "line_id": "L089",
      "line_name": "서부-남부 345kV",
      "thermal_limit_amp": 1200,
      "min_current_amp": 420,
      "max_current_amp": 980,
      "avg_current_amp": 680,
      "max_ratio": 0.817,
      "time_max_current": "2026-03-24T15:30:00Z",
      "hours_above_70pct": 2.5,
      "hours_above_75pct": 0.0,
      "status": "NORMAL"
    },
    {
      "line_id": "L045",
      "line_name": "남부-동부 345kV",
      "thermal_limit_amp": 950,
      "min_current_amp": 210,
      "max_current_amp": 820,
      "avg_current_amp": 550,
      "max_ratio": 0.863,
      "time_max_current": "2026-03-24T14:50:00Z",
      "hours_above_70pct": 4.2,
      "hours_above_75pct": 1.1,
      "status": "WARNING",
      "note": "오후 피크 시간 선로 과부하 경향, N-1 위험도 상승"
    }
  ],
  "summary": {
    "total_lines": 8,
    "normal_count": 6,
    "warning_count": 2,
    "critical_count": 0,
    "critical_hours": 0.0
  }
}
```

##### 2.4.3.3 알람 통계 및 처리 현황
```json
{
  "section": "알람 통계",
  "summary": {
    "total_alarms": 47,
    "resolved_count": 45,
    "unresolved_count": 2,
    "resolution_rate_percent": 95.7,
    "avg_resolution_time_min": 8.3,
    "max_resolution_time_min": 32.0,
    "alarms_by_severity": {
      "CRITICAL": 2,
      "WARNING": 15,
      "INFO": 30
    }
  },
  "critical_alarms": [
    {
      "timestamp": "2026-03-24T18:45:23Z",
      "alarm_code": "AL_087_LV",
      "description": "모선 3 저전압",
      "duration_sec": 180,
      "resolution_time_min": 3.0,
      "root_cause": "남부 부하 급증 (냉방)",
      "action_taken": "G1 출력 +80MW, 콘덴서 투입"
    },
    {
      "timestamp": "2026-03-24T22:12:05Z",
      "alarm_code": "AL_089_OL",
      "description": "선로 L089 과부하",
      "duration_sec": 420,
      "resolution_time_min": 7.0,
      "root_cause": "선로 L045 일시 차단, 부하 집중",
      "action_taken": "L045 재폐쇄, 부하 분산"
    }
  ],
  "unresolved_alarms": [
    {
      "timestamp": "2026-03-24T23:45:50Z",
      "alarm_code": "AL_051_SENSOR",
      "description": "모선 7 센서 이상",
      "duration_sec": 280,
      "status": "INVESTIGATING",
      "notes": "센서 신호 간헐적 두절, 교체 필요"
    }
  ]
}
```

##### 2.4.3.4 State Estimator 수렴 실패 목록
```json
{
  "section": "상태추정기 수렴 실패 기록",
  "summary": {
    "total_se_runs": 288,
    "convergence_success_count": 285,
    "convergence_failure_count": 3,
    "success_rate_percent": 98.96
  },
  "failures": [
    {
      "timestamp": "2026-03-24T10:32:15Z",
      "failure_reason": "센서 데이터 불일치 (모선 3 전압)",
      "affected_buses": ["BUS_003", "BUS_004"],
      "recovery_time_sec": 300,
      "root_cause": "SCADA 데이터 일시 전송 지연",
      "corrective_action": "SCADA 센서 타임싱크 확인"
    },
    {
      "timestamp": "2026-03-24T15:48:02Z",
      "failure_reason": "위상각 센서 미동기",
      "affected_buses": ["BUS_011"],
      "recovery_time_sec": 180,
      "root_cause": "GPS 신호 약화 (공사 중)",
      "corrective_action": "임시 안테나 설치"
    },
    {
      "timestamp": "2026-03-24T21:05:33Z",
      "failure_reason": "발전기 모델 부정합",
      "affected_buses": ["GEN_G2"],
      "recovery_time_sec": 450,
      "root_cause": "발전기 파라미터 변경 미반영",
      "corrective_action": "발전기 파라미터 갱신"
    }
  ]
}
```

##### 2.4.3.5 이상 구간 Top-3
```json
{
  "section": "이상 구간 Top-3",
  "anomalies": [
    {
      "rank": 1,
      "time_window": "2026-03-24T14:30~15:45",
      "anomaly_type": "오후 피크 + 냉방 부하 동시 증가",
      "severity_score": 8.5,
      "key_metrics": {
        "max_system_load_mw": 3650,
        "max_line_current_ratio": 0.863,
        "min_vsm_percent": 14.2,
        "voltage_excursions": 5
      },
      "description": "기상 이상 (고기압, 32도 기온)으로 냉방 부하 +15% 발생. 동시에 태양광 발전 급감(-40%)으로 대형 발전기 출력 집중. L045 및 L089 선로 한계 접근, VSM 경계 도달.",
      "contributing_factors": [
        "기상 악화 (고기압 영향)",
        "태양광 발전 감소",
        "부하 예측 모델 편차 ±8%"
      ],
      "recommended_review": "냉방 부하 예측 정확도 향상, 수요 관리 프로그램 강화"
    },
    {
      "rank": 2,
      "time_window": "2026-03-24T18:45~19:15",
      "anomaly_type": "모선 3 저전압 사건",
      "severity_score": 7.2,
      "key_metrics": {
        "min_voltage_pu": 0.947,
        "voltage_recovery_time_sec": 180,
        "alarm_storm_alarms": 8
      },
      "description": "L045 선로 일시 차단으로 인해 남부 부하가 L089로 집중. 무효전력 공급 부족으로 모선 3 저전압 도달.",
      "contributing_factors": [
        "L045 차단 (과부하 보호)",
        "무효전력 예비 부족",
        "발전기 G2 출력 제한"
      ],
      "recommended_review": "무효전력 기본 공급 용량 증대, G2 예비 운영 정책 재검토"
    },
    {
      "rank": 3,
      "time_window": "2026-03-24T22:10~22:35",
      "anomaly_type": "야간 부하 이동 + 선로 과부하",
      "severity_score": 6.8,
      "key_metrics": {
        "line_current_ratio_l089": 0.817,
        "overload_duration_min": 25.0,
        "predicted_vs_actual_error_percent": 12.0
      },
      "description": "야간 부하 재편성으로 인해 L089에 부하 집중. 부하 예측 오류(±12%)로 사전 대비 불충분.",
      "contributing_factors": [
        "야간 부하 패턴 변화 (산업 운영 시간 조정)",
        "부하 예측 모델 편차"
      ],
      "recommended_review": "야간 부하 패턴 재학습, 산업용 대형 고객 부하 사전 공지"
    }
  ]
}
```

#### 2.4.4 리포트 생성 템플릿 (Jinja2)
```jinja2
# AI-EMS 일일 운영 리포트
**{{ report_date }}** ({{ report_day_name }})

## 요약 (Executive Summary)

### 계통 상태
- **종합 평가**: {{ overall_status }}
- **이상 건수**: {{ total_anomalies }} 건
- **알람 처리율**: {{ alarm_resolution_rate }}%
- **평균 복구 시간**: {{ avg_resolution_time }} 분

### 주요 사건
{% for event in top_events %}
- {{ event.timestamp }}: {{ event.description }} (심각도: {{ event.severity }})
{% endfor %}

---

## 전압 현황 통계

| 모선 | 최소 (p.u.) | 최대 (p.u.) | 평균 (p.u.) | 표준편차 | 상태 |
|------|-----------|-----------|-----------|---------|------|
{% for bus in voltage_stats %}
| {{ bus.name }} | {{ bus.min }} | {{ bus.max }} | {{ bus.avg }} | {{ bus.std }} | {{ bus.status }} |
{% endfor %}

**주의 사항**:
{% for bus in voltage_warnings %}
- {{ bus.name }}: {{ bus.warning_message }}
{% endfor %}

---

## 선로 조류 현황

| 선로 | 최대 조류 (A) | 한계 (A) | 비율 (%) | 한계 초과 시간 | 상태 |
|------|-------------|---------|---------|-------------|------|
{% for line in line_stats %}
| {{ line.name }} | {{ line.max_current }} | {{ line.limit }} | {{ line.ratio }} | {{ line.overload_hours }} h | {{ line.status }} |
{% endfor %}

---

## 알람 통계

- **총 알람**: {{ total_alarms }} 건
- **해결 완료**: {{ resolved_alarms }} 건 ({{ resolution_rate }}%)
- **미해결**: {{ unresolved_alarms }} 건
- **평균 복구 시간**: {{ avg_resolution_time }} 분

**미해결 알람**:
{% for alarm in unresolved_alarms %}
- {{ alarm.timestamp }}: {{ alarm.description }} (지속 시간: {{ alarm.duration }} 분)
{% endfor %}

---

## 상태 추정기 (SE) 현황

- **운영 횟수**: {{ se_runs }} 회
- **수렴 성공**: {{ se_success }} 회 ({{ se_success_rate }}%)
- **수렴 실패**: {{ se_failures }} 회

**수렴 실패 내역**:
{% for failure in se_failure_details %}
- {{ failure.timestamp }}: {{ failure.reason }} → {{ failure.action }}
{% endfor %}

---

## 이상 구간 분석

### 1위: {{ anomaly_1.name }}
**시간**: {{ anomaly_1.time }} | **심각도**: {{ anomaly_1.severity }}/10

{{ anomaly_1.description }}

**권고 사항**: {{ anomaly_1.recommendation }}

### 2위: {{ anomaly_2.name }}
**시간**: {{ anomaly_2.time }} | **심각도**: {{ anomaly_2.severity }}/10

{{ anomaly_2.description }}

**권고 사항**: {{ anomaly_2.recommendation }}

### 3위: {{ anomaly_3.name }}
**시간**: {{ anomaly_3.time }} | **심각도**: {{ anomaly_3.severity }}/10

{{ anomaly_3.description }}

**권고 사항**: {{ anomaly_3.recommendation }}

---

## 운영 권고

{% for recommendation in operational_recommendations %}
1. **{{ recommendation.title }}**
   - 실행 시점: {{ recommendation.timing }}
   - 예상 효과: {{ recommendation.impact }}
   - 담당자: {{ recommendation.owner }}
{% endfor %}

---

**리포트 생성**: {{ report_generated_time }}
**다음 리포트**: {{ next_report_time }}

---

*본 리포트는 AI-EMS의 자동 생성 리포트입니다.*
```

#### 2.4.5 HOTL 분류 근거
- 정보 제공 목적
- 과거 24시간 이력 정리
- 즉시 조치 불필요 (권고사항만 제시)
- 조직 차원의 의사결정 지원

---

### J5: 기상 영향 분석 (Weather Impact Analysis)

#### 2.5.1 목적 및 범위
실시간 기상 데이터를 부하 모델과 신재생 발전 모델에 적용하여 향후 계통 상태 변화를 예측한다. 극한 기상 조건에서의 계통 취약성을 조기에 파악하고, 필요한 운영 조치를 권고한다.

#### 2.5.2 실행 일정
```python
scheduler.add_job(
    weather_impact,
    'interval',
    hours=1,
    id='j5_weather_impact',
    name='Weather Impact Analysis',
    coalesce=True,
    max_instances=1
)
```
- **주기**: 1시간
- **기상 데이터 소스**: Open-Meteo API (무료, 공개)
- **예측 범위**: 24시간
- **타임아웃**: 60초

#### 2.5.3 기상 데이터 수집 및 처리

##### 2.5.3.1 Open-Meteo API 연동
```python
import requests

def fetch_weather_data():
    """
    Open-Meteo API에서 기상 데이터 조회
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 37.5665,  # 서울 기준
        "longitude": 126.9780,
        "hourly": [
            "temperature_2m",      # 기온 (°C)
            "relative_humidity_2m", # 상대습도 (%)
            "precipitation",        # 강수량 (mm)
            "weather_code",         # 기상 코드
            "wind_speed_10m",      # 풍속 (km/h)
            "cloud_cover",         # 운량 (%)
            "global_horizontal_irradiance"  # 일사량 (W/m²)
        ],
        "timezone": "Asia/Seoul",
        "forecast_days": 1
    }

    response = requests.get(url, params=params)
    return response.json()
```

##### 2.5.3.2 기상 인자별 영향 분석

**2.5.3.2.1 기온 → 냉난방 부하**
```
부하 모델 (냉방):
  Q_cooling = α × (T_outdoor - T_base) × N_buildings

  α: 냉방 동특성 계수 (MW/°C) = 1.2
  T_base: 기준 온도 = 24°C
  N_buildings: 건물 수 = 3,500개

예측 로직:
  IF T_current >= 25°C:
      냉방 부하 = 0.8 × 실제 부하 + 0.2 × 냉방 기여
      냉방 기여도 = 80% (여름철)

  IF T_current <= 5°C:
      난방 부하 증가
      난방 기여도 = 60% (겨울철)

  기온 변화 1°C = 부하 변화 ±1.2%

예시:
  현재 기온: 28°C
  기준 온도: 24°C
  냉방 부하 증가분 = 1.2 × (28-24) = 4.8%
  → 부하 3,200MW × 1.048 = 3,353MW 예상
```

**2.5.3.2.2 일사량 → 태양광 발전**
```
태양광 발전 모델:
  P_pv = η × A × I_solar × (1 - 0.005 × (T_cell - 25))

  η: 패널 효율 = 0.18
  A: 전체 설치 용량 = 5,000 MW
  I_solar: 일사량 (W/m²)
  T_cell: 셀 온도 (기온 + 20°C 추정)

예측 로직:
  IF 구름 없음 (cloud_cover < 20%):
      피크 태양광 = 5,000 × 0.18 × 1,000W/m² × 회로온도 계수
      실제 출력 = 4,200MW (약 84% 이용률)

  IF 구름 많음 (cloud_cover > 70%):
      태양광 출력 = 1,500~2,000MW (약 30~40%)
      → 기저부하 발전소 출력 증가 필요

예시:
  현재 일사량: 800 W/m², 구름: 30%
  태양광 출력 예측: 3,500MW

  1시간 후 일사량: 500 W/m², 구름: 80% (스콜)
  태양광 출력 예측: 1,200MW (급감, -2,300MW)
  → 기저부하 발전소 즉시 증설 필요
```

**2.5.3.2.3 풍속 → 풍력 발전**
```
풍력 발전 모델:
  P_wind = 0.5 × ρ × A × v³ × C_p × η

  ρ: 공기 밀도 = 1.225 kg/m³
  A: 로터 면적
  v: 풍속 (m/s)
  C_p: 전력 계수 = 0.35~0.45

풍속별 발전량 (설치 용량 2,000MW 기준):
  v < 3 m/s: 발전 거의 없음 (P ≈ 0)
  v = 5 m/s: P ≈ 400MW (20%)
  v = 10 m/s: P ≈ 1,200MW (60%)
  v = 12 m/s: P ≈ 1,600MW (80%) ← 최대 이전
  v > 15 m/s: 안전 셧다운 (P = 0) ← 극한기상

극한 풍속 처리:
  IF 풍속 > 15 m/s (시간 평균):
      풍력 발전 차단 경보 발령
      발전량 급격히 감소 예상
      기저부하 발전소 예비 확보 필수
```

**2.5.3.2.4 극한 기상 조건**
```
극한 기상 판정 기준:

1) 폭염 (Extreme Heat):
   - 기온 >= 35°C (Red Alert)
   - 냉방 부하 +20% 이상
   - 열용량 소비 극대

2) 한파 (Extreme Cold):
   - 기온 <= -10°C (Red Alert)
   - 난방 부하 +15% 이상
   - 연료 소비 급증

3) 폭우 (Extreme Rainfall):
   - 강수량 > 50mm/hr
   - 태양광 발전 중단
   - 수력 발전소 방수로 운영

4) 강풍 (Extreme Wind):
   - 풍속 > 15 m/s
   - 풍력 발전 셧다운
   - 송전선 영향 (기계적 진동)

5) 뇌우 (Thunderstorm):
   - weather_code 80-82
   - 낙뢰 위험 (선로탈출)
   - SCADA 센서 오작동 위험
```

#### 2.5.4 분석 결과 출력

```json
{
  "timestamp": "2026-03-25T14:00:00.000Z",
  "type": "J5_WEATHER_IMPACT",
  "severity": "WARNING",
  "forecast_horizon": "2026-03-26T14:00:00Z",
  "current_weather": {
    "temperature_c": 28.5,
    "humidity_percent": 65,
    "wind_speed_kmh": 12.3,
    "precipitation_mm": 0.0,
    "cloud_cover_percent": 35,
    "global_horizontal_irradiance_wm2": 750,
    "weather_description": "흐림 (Partly Cloudy)"
  },
  "impact_analysis": {
    "cooling_load_impact": {
      "current_temperature_c": 28.5,
      "base_temperature_c": 24.0,
      "delta_c": 4.5,
      "cooling_coefficient_mw_per_c": 1.2,
      "estimated_cooling_load_increase_mw": 5.4,
      "cooling_load_increase_percent": 5.4,
      "status": "ELEVATED"
    },
    "solar_generation_impact": {
      "current_irradiance_wm2": 750,
      "cloud_cover_percent": 35,
      "expected_solar_output_mw": 3200,
      "expected_solar_output_percent": 64,
      "forecast_next_4h": [
        {
          "time": "2026-03-25T14:00Z",
          "irradiance_wm2": 750,
          "expected_output_mw": 3200
        },
        {
          "time": "2026-03-25T15:00Z",
          "irradiance_wm2": 650,
          "expected_output_mw": 2800
        },
        {
          "time": "2026-03-25T16:00Z",
          "irradiance_wm2": 500,
          "expected_output_mw": 2100
        },
        {
          "time": "2026-03-25T17:00Z",
          "irradiance_wm2": 200,
          "expected_output_mw": 800
        }
      ],
      "status": "DECLINING"
    },
    "wind_generation_impact": {
      "current_wind_speed_kmh": 12.3,
      "current_wind_speed_ms": 3.42,
      "expected_wind_output_mw": 380,
      "expected_wind_output_percent": 19,
      "wind_forecast_next_6h": [
        {
          "time": "2026-03-25T14:00Z",
          "wind_speed_kmh": 12.3,
          "expected_output_mw": 380
        },
        {
          "time": "2026-03-25T15:00Z",
          "wind_speed_kmh": 11.5,
          "expected_output_mw": 350
        },
        {
          "time": "2026-03-25T16:00Z",
          "wind_speed_kmh": 14.8,
          "expected_output_mw": 520
        },
        {
          "time": "2026-03-25T17:00Z",
          "wind_speed_kmh": 18.2,
          "expected_output_mw": 950
        },
        {
          "time": "2026-03-25T18:00Z",
          "wind_speed_kmh": 22.5,
          "expected_output_mw": 1400
        },
        {
          "time": "2026-03-25T19:00Z",
          "wind_speed_kmh": 25.3,
          "expected_output_mw": 1650
        }
      ],
      "status": "INCREASING",
      "extreme_wind_alert": false
    },
    "extreme_weather_alerts": [
      {
        "alert_type": "ELEVATED_COOLING_LOAD",
        "severity": "MEDIUM",
        "trigger_condition": "기온 28.5°C, 냉방 부하 +5.4%",
        "forecast_peak_time": "2026-03-25T16:00:00Z",
        "forecast_peak_cooling_load_increase": "8.2%",
        "recommendation": "오후 4~5시 피크 시간 냉방 부하 +200MW 예상, 발전기 예비 확보"
      },
      {
        "alert_type": "SOLAR_GENERATION_DECLINE",
        "severity": "MEDIUM",
        "trigger_condition": "구름 증가 예상 (현재 35% → 65%)",
        "forecast_start_time": "2026-03-25T15:00:00Z",
        "expected_solar_loss_mw": 2400,
        "expected_solar_loss_duration_hour": 4.0,
        "recommendation": "태양광 급감 대비, 기저부하 발전소 출력 증설 준비"
      }
    ]
  },
  "grid_vulnerability_assessment": {
    "n1_risk_at_peak": {
      "time": "2026-03-25T17:00:00Z",
      "expected_load_mw": 3450,
      "expected_solar_mw": 800,
      "expected_wind_mw": 950,
      "system_margin_percent": 8.5,
      "n1_risk_level": "HIGH",
      "critical_contingencies": [
        {
          "contingency": "Large Coal Plant Outage (500MW)",
          "risk_score": 0.76,
          "expected_blackout_duration_sec": 180
        },
        {
          "contingency": "Large Transmission Line Outage",
          "risk_score": 0.68,
          "expected_load_shed_mw": 400
        }
      ]
    }
  },
  "operational_recommendations": [
    {
      "priority": 1,
      "time_window": "15:00~17:00",
      "recommendation": "태양광 급감 대비 기저부하 발전 출력 +2,000MW 준비",
      "sop_reference": "SOP 2.2.1",
      "expected_impact": "발전기 예비 확보, 블랙아웃 위험 감소"
    },
    {
      "priority": 2,
      "time_window": "16:00~17:00",
      "recommendation": "오후 피크 냉방 부하 대비 무효전력 공급 증대 (콘덴서 투입)",
      "sop_reference": "SOP 2.4.3",
      "expected_impact": "전압 안정도 유지, VSM >= 15% 보장"
    },
    {
      "priority": 3,
      "time_window": "14:30~15:00",
      "recommendation": "가동 중인 발전기 정시 운영 확인 (예비 부족 시 외부 발전 수입)",
      "sop_reference": "SOP 1.1.2",
      "expected_impact": "공급 여유 확보"
    }
  ],
  "mode": "HOTL"
}
```

#### 2.5.5 HOTL 분류 근거
- 정보 제공 목적
- 기상 기반 운영 권고
- 즉시 조치보다는 사전 준비
- 예방적 대응 지원

---

### J6: 이상 패턴 탐지 (Anomaly Detection)

#### 2.6.1 목적 및 범위
센서 데이터 및 계통 상태 데이터에서 비정상적인 패턴을 자동으로 탐지하여 센서 고장, 데이터 오류, 또는 계통의 숨겨진 이상을 조기에 발견한다.

#### 2.6.2 실행 일정
```python
scheduler.add_job(
    anomaly_detection,
    'interval',
    minutes=15,
    id='j6_anomaly_detection',
    name='Anomaly Detection',
    coalesce=True,
    max_instances=1
)
```
- **주기**: 15분
- **윈도우 크기**: 최근 30분 데이터
- **타임아웃**: 45초

#### 2.6.3 이상 탐지 기법

##### 2.6.3.1 Z-score 기반 통계적 이상
```
Z-score 계산:
  z = (x - μ) / σ

  x: 현재 측정값
  μ: 과거 30일 평균
  σ: 과거 30일 표준편차

이상 판정:
  IF |z| > 3.0:  강한 이상 (CRITICAL)
  IF |z| > 2.5:  중간 이상 (WARNING)
  IF |z| > 2.0:  약한 이상 (INFO)

예시:
  모선 1 전압:
    과거 평균 (μ) = 1.00 p.u.
    표준편차 (σ) = 0.02 p.u.
    현재값 (x) = 1.10 p.u. (매우 높음)
    z = (1.10 - 1.00) / 0.02 = 5.0
    → 강한 이상 (|z| > 3.0)
    → 원인: 발전기 과여자 또는 센서 고장
```

##### 2.6.3.2 정상 프로파일 비교
```
일주기 정상 프로파일:
  - 월요일 06:00~09:00: 부하 상승 (출근시간)
  - 월요일 12:00~13:00: 부하 하강 (점심시간)
  - 월요일 17:00~19:00: 부하 피크 (저녁시간)
  - 월요일 22:00~06:00: 저부하 (야간)

이상 탐지:
  현재 월요일 06:30, 부하 = 2,100MW
  예상 범위 (95% 신뢰도) = 2,800~3,400MW
  → 부하 700MW 부족 (비정상 낮음)
  → 가능 원인: 대형 산업용 고객 가동 중단, 수용가 정전
```

##### 2.6.3.3 센서 고착 탐지 (Sensor Stuck)
```
고착 판정 알고리즘:
  IF 값이 정확히 동일하게 반복 && 지속시간 >= 3시간:
      → 센서 고착 의심

예시:
  모선 7 전압 센서:
    14:00: 1.001 p.u.
    14:15: 1.001 p.u.  ← 동일
    14:30: 1.001 p.u.  ← 동일
    14:45: 1.001 p.u.  ← 동일 (45분 동안 무변화)
    ...
    17:00: 1.001 p.u.  ← 동일 (3시간 동안 무변화)

  → 센서 고착 경고: '모선 7 센서 3시간째 변화 없음. 센서 이상 의심'
  → 액션: 수동 계기 확인, 센서 교체 검토
```

##### 2.6.3.4 발전기 급변 탐지
```
급변 판정 기준:
  발전기 출력 변화율 = |P(t) - P(t-Δt)| / P(t-Δt)

  Δt = 5분 (SCADA 갱신 주기)

  IF 변화율 > 5% (고속 변화):
      → 급변 의심
      → 가능 원인: 제어기 오작동, 설정값 급변, 센서 잡음

  IF 변화율 > 10% (극심한 급변):
      → 위험 상황
      → 원인 조사 필수

예시:
  발전기 G2 출력:
    14:00: 500MW
    14:05: 475MW (변화율 5.0%)  ← 경계
    14:10: 450MW (변화율 5.3%)  ← 경계
    14:15: 420MW (변화율 6.7%)  ← 경고 (>5%)
    14:20: 380MW (변화율 9.5%)  ← 경고
    14:25: 330MW (변화율 13.2%) ← 위험 (>10%)

  누적 변화: 500MW → 330MW (34% 감소, 10분 내)
  → 심각한 급변 감지
  → 즉시 원인 조사 및 대응 필요
```

#### 2.6.4 이상 탐지 결과 출력

```json
{
  "timestamp": "2026-03-25T14:30:00.000Z",
  "type": "J6_ANOMALY_DETECTION",
  "severity": "WARNING",
  "analysis_window": "2026-03-25T14:00~14:30Z",
  "anomalies_detected": [
    {
      "id": "ANM_001",
      "anomaly_type": "SENSOR_STUCK",
      "severity": "HIGH",
      "element_id": "BUS_007",
      "element_name": "광주 345kV",
      "metric": "voltage_pu",
      "stuck_value": 1.0010,
      "stuck_duration_minutes": 180,
      "first_stuck_time": "2026-03-25T11:30:00Z",
      "confidence": 0.98,
      "root_cause_estimate": "센서 신호 전송 오류 또는 센서 내부 고장",
      "recommended_action": [
        "1. 수동 계기로 모선 7 실제 전압 확인",
        "2. SCADA 센서 케이블 연결 상태 점검",
        "3. 센서 교체 일정 수립"
      ]
    },
    {
      "id": "ANM_002",
      "anomaly_type": "STATISTICAL_OUTLIER",
      "severity": "MEDIUM",
      "element_id": "GEN_G2",
      "element_name": "발전기 G2",
      "metric": "output_mw",
      "current_value": 480.0,
      "historical_mean": 520.0,
      "historical_std": 15.0,
      "z_score": 2.67,
      "confidence": 0.95,
      "root_cause_estimate": "발전기 출력 저하, 터빈 성능 저하 또는 제어기 설정 변경 가능성",
      "anomaly_duration_minutes": 45,
      "recommended_action": [
        "1. 발전기 G2 상태 점검 (터빈 출력, 온도, 진동)",
        "2. 발전소 제어 시스템 로그 확인",
        "3. 성능 저하 시 점검 일정 수립"
      ]
    },
    {
      "id": "ANM_003",
      "anomaly_type": "RAPID_RAMP_RATE",
      "severity": "MEDIUM",
      "element_id": "GEN_G5",
      "element_name": "발전기 G5",
      "metric": "output_mw",
      "ramp_rate_mw_per_min": 8.5,
      "threshold_mw_per_min": 5.0,
      "current_trend": "DECREASING",
      "trend_duration_minutes": 12,
      "confidence": 0.92,
      "root_cause_estimate": "급격한 부하 변화 또는 발전기 제어 조정 (예: 주파수 지원)",
      "affected_system_frequency_hz": 59.85,
      "recommended_action": [
        "1. 발전기 제어기 동작 상태 확인",
        "2. 주파수 응답 특성 검토",
        "3. 라운드 로빈 제어 설정 확인"
      ]
    },
    {
      "id": "ANM_004",
      "anomaly_type": "PROFILE_MISMATCH",
      "severity": "LOW",
      "element_id": "BUS_001",
      "element_name": "서울 345kV",
      "metric": "voltage_pu",
      "expected_range_lower": 0.975,
      "expected_range_upper": 1.025,
      "current_value": 1.042,
      "deviation_percent": 1.7,
      "confidence": 0.85,
      "root_cause_estimate": "일별 부하 패턴 변화 또는 기상 영향 (기온 상승 → 냉방 부하 감소)",
      "expected_normalization_time": "2026-03-25T17:00:00Z",
      "recommended_action": [
        "1. 모니터링 강화 (다음 1시간)",
        "2. 정상 범위 이내 여부 확인"
      ]
    }
  ],
  "summary": {
    "total_anomalies": 4,
    "critical_count": 0,
    "high_count": 1,
    "medium_count": 2,
    "low_count": 1,
    "new_anomalies": 2,
    "resolved_anomalies": 0,
    "ongoing_anomalies": 2
  },
  "mode": "HOTL"
}
```

#### 2.6.5 HOTL 분류 근거
- 정보 제공 목적
- 센서 교체 등 점검 권고
- 즉시 조치보다는 모니터링
- 후속 분석 지원

---

## 3. APScheduler 통합 설정

### 3.1 스케줄러 초기화
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import pytz

# 스케줄러 생성
scheduler = BackgroundScheduler(
    daemon=True,
    timezone=pytz.timezone('Asia/Seoul')
)

# 스케줄러 시작
scheduler.start()
```

### 3.2 6종 인사이트 작업 등록
```python
# J1: 계통 건전성 점검 (5분 주기)
scheduler.add_job(
    func=grid_health_check,
    trigger=IntervalTrigger(minutes=5),
    id='j1_grid_health_check',
    name='J1: Grid Health Check',
    coalesce=True,
    max_instances=1,
    replace_existing=True
)

# J2: 알람 스톰 자동 분석 (즉시 이벤트 기반)
redis_pubsub = redis.StrictRedis().pubsub()
redis_pubsub.subscribe('ops:alarm')
redis_pubsub.get_message = lambda: alarm_storm_handler()
# (별도 스레드에서 리스닝)

# J3: 단기 리스크 평가 (1시간 주기)
scheduler.add_job(
    func=risk_assessment,
    trigger=IntervalTrigger(hours=1),
    id='j3_risk_assessment',
    name='J3: Short-term Risk Assessment',
    coalesce=True,
    max_instances=1,
    replace_existing=True
)

# J4: 일일 리포트 (매일 06:00)
scheduler.add_job(
    func=daily_report,
    trigger=CronTrigger(hour=6, minute=0, timezone='Asia/Seoul'),
    id='j4_daily_report',
    name='J4: Daily Report',
    coalesce=True,
    max_instances=1,
    replace_existing=True
)

# J5: 기상 영향 분석 (1시간 주기)
scheduler.add_job(
    func=weather_impact,
    trigger=IntervalTrigger(hours=1),
    id='j5_weather_impact',
    name='J5: Weather Impact Analysis',
    coalesce=True,
    max_instances=1,
    replace_existing=True
)

# J6: 이상 패턴 탐지 (15분 주기)
scheduler.add_job(
    func=anomaly_detection,
    trigger=IntervalTrigger(minutes=15),
    id='j6_anomaly_detection',
    name='J6: Anomaly Detection',
    coalesce=True,
    max_instances=1,
    replace_existing=True
)
```

### 3.3 에러 핸들링 및 로깅
```python
def job_error_handler(event):
    """작업 실패 시 처리"""
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
        # Slack/Email 알림
        notify_operations(f"AI Insight {event.job_id} failed")
    else:
        logger.info(f"Job {event.job_id} completed successfully")

scheduler.add_listener(job_error_handler, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
```

---

## 4. HOTL/HITL 자동 분류 규칙

### 4.1 분류 기준표

| 인사이트 | 유형 | 자동 분류 | 근거 |
|---------|------|---------|------|
| J1 | 정보 | HOTL | 운영자 모니터링 강화만 필요 |
| J2 | 복구 | HITL | 즉시 복구 절차 필요 |
| J3 | 조치 | HITL | 조치 권고 후 운영자 판단 |
| J4 | 보고 | HOTL | 과거 이력 정리 |
| J5 | 정보 | HOTL | 기상 기반 정보 제공 |
| J6 | 정보 | HOTL | 센서 점검 권고 |

### 4.2 라우팅 규칙
```python
def classify_insight(insight):
    """인사이트 자동 분류"""

    if insight.type == 'J1_GRID_HEALTH':
        return 'HOTL'  # 정보 제공

    elif insight.type == 'J2_ALARM_STORM':
        return 'HITL'  # 즉시 조치 필요

    elif insight.type == 'J3_RISK_ASSESSMENT':
        if insight.severity == 'CRITICAL':
            return 'HITL'  # 즉시 조치 권고
        else:
            return 'HOTL'  # 정보 제공

    elif insight.type == 'J4_DAILY_REPORT':
        return 'HOTL'  # 보고

    elif insight.type == 'J5_WEATHER_IMPACT':
        if insight.has_extreme_weather_alert:
            return 'HITL'  # 극한기상 조치 권고
        else:
            return 'HOTL'  # 정보 제공

    elif insight.type == 'J6_ANOMALY_DETECTION':
        return 'HOTL'  # 정보 제공
```

---

## 5. 정량 기준 JSON 직접 참조

### 5.1 voltage_limits.json
```json
{
  "voltage_criteria": {
    "normal_max_percent": 105.0,
    "normal_min_percent": 95.0,
    "warning_max_percent": 103.0,
    "warning_min_percent": 97.0,
    "critical_max_percent": 110.0,
    "critical_min_percent": 90.0,
    "unit": "percentage",
    "base_voltage_kv": 345.0
  },
  "bus_specific_limits": {
    "BUS_001": {
      "name": "서울 345kV",
      "voltage_class_kv": 345,
      "normal_max_pu": 1.05,
      "normal_min_pu": 0.95
    },
    "BUS_003": {
      "name": "인천 345kV",
      "voltage_class_kv": 345,
      "normal_max_pu": 1.05,
      "normal_min_pu": 0.95
    }
  }
}
```

### 5.2 thermal_limits.json
```json
{
  "line_limits": {
    "L089": {
      "name": "서부-남부 345kV",
      "thermal_limit_amp": 1200,
      "warning_threshold_ratio": 0.70,
      "critical_threshold_ratio": 0.75,
      "emergency_threshold_ratio": 0.85
    },
    "L045": {
      "name": "남부-동부 345kV",
      "thermal_limit_amp": 950,
      "warning_threshold_ratio": 0.70,
      "critical_threshold_ratio": 0.75,
      "emergency_threshold_ratio": 0.85
    }
  }
}
```

### 5.3 frequency_criteria.json
```json
{
  "frequency_limits": {
    "nominal_hz": 60.0,
    "normal_band_hz": 0.2,
    "warning_band_hz": 0.5,
    "critical_band_hz": 0.8,
    "normal_lower_hz": 59.8,
    "normal_upper_hz": 60.2,
    "warning_lower_hz": 59.5,
    "warning_upper_hz": 60.5,
    "critical_lower_hz": 59.2,
    "critical_upper_hz": 60.8
  }
}
```

### 5.4 generator_limits.json
```json
{
  "generator_limits": {
    "GEN_G1": {
      "name": "발전기 G1",
      "rated_capacity_mw": 500,
      "max_output_percent": 100,
      "warning_output_percent": 90,
      "critical_output_percent": 95
    },
    "GEN_G2": {
      "name": "발전기 G2",
      "rated_capacity_mw": 600,
      "max_output_percent": 100,
      "warning_output_percent": 90,
      "critical_output_percent": 95
    }
  }
}
```

### 5.5 vsm_criteria.json
```json
{
  "vsm_limits": {
    "critical_percent": 10.0,
    "warning_percent": 15.0,
    "normal_percent": 20.0,
    "healthy_percent": 25.0,
    "calculation_method": "PV_curve_based",
    "minimum_reserve_percent": 5.0
  }
}
```

---

## 6. 인사이트 결과 Redis 저장 구조

### 6.1 Redis 키 설계
```
ops:insight:health               # J1 계통 건전성 (최근 5분)
ops:insight:alarm_storm          # J2 알람 스톰 (이벤트)
ops:insight:risk_assessment      # J3 단기 리스크 (최근 1시간)
ops:insight:daily_report         # J4 일일 리포트 (최근 24시간)
ops:insight:weather_impact       # J5 기상 영향 (최근 1시간)
ops:insight:anomaly_detection    # J6 이상 패턴 (최근 15분)
ops:insight:all_recent           # 모든 인사이트 최신 목록 (TTL: 1일)
```

### 6.2 Redis 저장 구현
```python
def save_insight_to_redis(insight, ttl_seconds):
    """인사이트 결과를 Redis에 저장"""

    key = f"ops:insight:{insight.type.lower()}"

    # JSON 직렬화
    value = json.dumps(insight.to_dict())

    # Redis 저장 (TTL 적용)
    redis_client.setex(
        key,
        ttl_seconds,
        value
    )

    # 최신 목록에도 추가
    redis_client.lpush('ops:insight:all_recent', key)
    redis_client.ltrim('ops:insight:all_recent', 0, 99)  # 최근 100개만 유지
    redis_client.expire('ops:insight:all_recent', 86400)  # 1일 TTL

    logger.info(f"Insight saved: {key}")

# TTL 설정
INSIGHT_TTL = {
    'J1_GRID_HEALTH': 300,           # 5분
    'J2_ALARM_STORM': 3600,          # 1시간
    'J3_RISK_ASSESSMENT': 3600,      # 1시간
    'J4_DAILY_REPORT': 86400,        # 24시간
    'J5_WEATHER_IMPACT': 3600,       # 1시간
    'J6_ANOMALY_DETECTION': 900,     # 15분
}
```

### 6.3 Redis 조회 API
```python
def get_latest_insight(insight_type):
    """최신 인사이트 조회"""
    key = f"ops:insight:{insight_type.lower()}"
    value = redis_client.get(key)
    if value:
        return json.loads(value)
    return None

def get_all_recent_insights():
    """모든 최신 인사이트 조회"""
    keys = redis_client.lrange('ops:insight:all_recent', 0, -1)
    insights = []
    for key in keys:
        value = redis_client.get(key)
        if value:
            insights.append(json.loads(value))
    return insights
```

---

## 7. Phase 4 구현 계획

### 7.1 Phase별 구현 범위

#### Phase 2: 기반 구축
- SCADA 센서 데이터 수집 및 정규화
- 선조류 계산 (State Estimator) 안정화
- 부하 예측 모델 (Prophet) 초기 학습
- Redis 기본 인프라 구성
- 알람 처리 시스템 개발

#### Phase 3: 고도화
- 기상 API (Open-Meteo) 연동
- 신재생 발전 예측 모델 (태양광, 풍력)
- 이상 탐지 알고리즘 (Z-score, DBSCAN)
- RAG 기반 과거 패턴 검색 시스템
- 부하 예측 정확도 향상 (정확도 >= 95%)

#### Phase 4: 통합 및 배포
- APScheduler 기반 6종 인사이트 통합 구현
- HOTL/HITL 자동 라우팅 시스템
- 인사이트 대시보드 및 알림 시스템
- 통합 테스트 (Scenario S5 연동)
- 운영자 훈련 및 배포

### 7.2 Phase 4 상세 작업 계획

#### 7.2.1 J1 구현 (1주)
```
작업:
  1. voltage_limits.json, thermal_limits.json 등 설정 파일 검증
  2. grid_health_check() 함수 작성
  3. 모선/선로/발전기 임계값 처리 로직
  4. Root cause 분석 (기여도 분석)
  5. 단위 테스트 및 통합 테스트

산출물:
  - grid_health_check.py (300~400 줄)
  - 테스트 케이스 10개 이상
  - 문서
```

#### 7.2.2 J2 구현 (1.5주)
```
작업:
  1. Redis Pub/Sub 연동
  2. 알람 스톰 판정 로직 (5초 내 3건)
  3. 시간·공간 클러스터링 (DBSCAN)
  4. RAG 기반 과거 패턴 검색
  5. Root cause 상위 3개 추론 알고리즘
  6. SOP 기반 복구 액션 매핑
  7. 단위/통합 테스트

산출물:
  - alarm_storm_analyzer.py (400~500 줄)
  - RAG 쿼리 템플릿 5개
  - 테스트 케이스 15개 이상
```

#### 7.2.3 J3 구현 (1.5주)
```
작업:
  1. Prophet 모델 통합 (1시간 예측)
  2. 선조류 계산 엔진 연동 (N-1 분석)
  3. VSM 계산 및 추이 분석
  4. 조치 권고 생성 로직
  5. 실제 데이터 기반 검증 (정확도 >= 90%)
  6. 단위/통합 테스트

산출물:
  - risk_assessor.py (400~500 줄)
  - Prophet 모델 파일
  - 테스트 케이스 12개 이상
```

#### 7.2.4 J4 구현 (1주)
```
작업:
  1. Jinja2 리포트 템플릿 작성
  2. 통계 계산 로직 (Min/Max/Avg/Std)
  3. 알람 통계 집계
  4. SE 수렴 실패 분석
  5. 이상 구간 Top-3 추출
  6. PDF/Markdown 생성
  7. 이메일 배포 설정

산출물:
  - daily_report_generator.py (300~400 줄)
  - Jinja2 템플릿 (report_template.html)
  - 테스트 케이스 8개 이상
```

#### 7.2.5 J5 구현 (1주)
```
작업:
  1. Open-Meteo API 연동
  2. 기온→냉난방 부하 모델
  3. 일사량→태양광 발전 모델
  4. 풍속→풍력 발전 모델
  5. 극한기상 판정 로직
  6. N-1 취약성 평가
  7. 단위/통합 테스트

산출물:
  - weather_impact_analyzer.py (300~400 줄)
  - 기상 API 래퍼
  - 테스트 케이스 10개 이상
```

#### 7.2.6 J6 구현 (1주)
```
작업:
  1. Z-score 기반 통계 이상 탐지
  2. 정상 프로파일 생성 및 비교
  3. 센서 고착 탐지 알고리즘
  4. 발전기 급변 탐지
  5. 이상 점수화 및 순위 매김
  6. 권고 액션 생성
  7. 단위/통합 테스트

산출물:
  - anomaly_detector.py (350~450 줄)
  - 정상 프로파일 저장소
  - 테스트 케이스 12개 이상
```

#### 7.2.7 통합 및 배포 (2주)
```
작업:
  1. APScheduler 통합 설정
  2. 6종 인사이트 연결
  3. Redis 저장소 설정
  4. HOTL/HITL 라우팅
  5. 대시보드 UI 개발 (Optional)
  6. 통합 시나리오 테스트 (S5)
  7. 운영자 훈련 자료 작성
  8. 운영 절차서 작성

산출물:
  - 통합 설정 파일
  - 대시보드 (선택)
  - 통합 테스트 리포트
  - 운영 절차서
  - 훈련 자료
```

### 7.3 테스트 전략

#### 7.3.1 단위 테스트
```
범위: 각 J1~J6 함수 개별 테스트
커버리지: >= 80%
예시:
  test_grid_health_check_voltage_violation()
  test_alarm_storm_detection()
  test_risk_assessment_n1_analysis()
  test_daily_report_generation()
  test_weather_impact_calculation()
  test_anomaly_detection_zscore()
```

#### 7.3.2 통합 테스트
```
범위: J1~J6 간 데이터 흐름, Redis 저장소, HOTL/HITL 라우팅
시나리오:
  S1: 정상 운영 시나리오 (24시간)
  S2: 알람 스톰 시나리오
  S3: 극한기상 시나리오
  S4: N-1 사건 시나리오
  S5: 복합 이상 시나리오
```

#### 7.3.3 성능 테스트
```
목표:
  - J1 실행 시간 < 30초
  - J2 실행 시간 < 15초
  - J3 실행 시간 < 120초
  - J4 실행 시간 < 300초
  - J5 실행 시간 < 60초
  - J6 실행 시간 < 45초

도구: pytest-benchmark, locust (부하 테스트)
```

#### 7.3.4 검증 테스트
```
범위: 실제 계통 데이터 기반 검증
방법:
  - 과거 1개월 데이터 재생 (Replay)
  - 인사이트 결과 운영자 검증
  - 정확도 측정

목표:
  - 알람 스톰 탐지율: >= 95%
  - 근본 원인 정확도: >= 85%
  - 부하 예측 정확도: >= 90%
```

---

## 8. 결론

AI-EMS v5.1의 능동형 AI 인사이트 6종은 운영자의 능동적 질의 없이 계통을 자동으로 모니터링·분석·보고하는 지능형 운영 시스템을 구현한다. APScheduler 기반의 자동 실행, 정량 기준의 직접 참조, 그리고 HOTL/HITL의 명확한 분류를 통해 빠르고 효율적인 계통 운영을 지원한다.

Phase 2~3에서 확보된 기반 데이터와 분석 기술을 바탕으로 Phase 4에서 6종 인사이트를 통합 구현하며, 통합 테스트 시나리오 S5와 연동하여 실제 운영 환경의 적용 가능성을 검증한다.
