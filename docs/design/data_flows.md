# AI-EMS v5.1 데이터 흐름 설계서

## 1. 개요

AI-EMS v5.1은 5가지 핵심 데이터 흐름 시나리오를 통해 운영자의 자연어 발화부터 최종 응답까지의 전체 경로를 추적합니다. 각 시나리오는 실제 운영 환경에서 자주 발생하는 사용 사례를 반영하며, HOTL(Hands-Off-The-Loop)과 HITL(Human-In-The-Loop) 모드를 구분하여 운영자의 의사결정 권한을 보장합니다.

---

## 2. 핵심 설계 원칙

### 2.1 HOTL vs HITL 구분
- **HOTL (자동 실행)**: 조회, 화면 이동, 정보 표시 등 운영자 인프라에 영향을 주지 않는 작업
- **HITL (운영자 승인)**: 조치 추천, 스터디 결과 적용, 복구 절차 등 계통 상태 변경이 필요한 작업
- **Study 격리**: 운영자가 'What-if' 분석을 수행할 때, 운영 데이터(ops)에서 스터디 전용 네임스페이스로 복사하여 격리된 환경에서 수행

### 2.2 Evidence Chain
모든 AI 응답에는 다음 정보가 포함되어 투명성과 추적 가능성을 보장합니다:
- 호출된 도구(tool_called)
- 도구 파라미터(params)
- 결과 요약(result_summary)
- RAG 참조 정보(rag_reference)
- 데이터 스냅샷 타임스탬프(snapshot_ts)

### 2.3 계층적 아키텍처
```
운영자 (Operator)
  ↓
오케스트레이터 (Orchestrator) — Intent 분류, 모드 결정
  ↓
기능 모듈 (HOTL/HITL 모듈) — 실제 로직 수행
  ↓
Gateway (통합 게이트웨이) — 외부 시스템 호출
  ↓
백엔드 스텁 (Stub Services) — 계통상태(SE), 조류(TP), 스터디(Study) 등
```

---

## 3. 데이터 흐름 시나리오

### F1: 계통 상태 조회 (HOTL)

**발화**: "현재 계통 상태 요약해줘. 전압 낮은 모선 있어?"

**목적**: 운영자가 현재 계통의 전압 상태를 파악하고, 위반 항목이 있는지 신속하게 확인

**데이터 흐름**:

```
1. 운영자 → 오케스트레이터
   • 자연어 쿼리: "현재 계통 상태 요약해줘. 전압 낮은 모선 있어?"
   • 요청 타입: 조회(Query)

2. 오케스트레이터 (Intent 분류)
   • Intent 결정: 조회
   • 모드 결정: HOTL (정보 조회만 수행)
   • 타겟 도구: NL2App의 query_app()

3. 오케스트레이터 → NL2App
   • 도구 호출: query_app('SE', 'snapshot')
   • 파라미터: namespace='ops', query_type='latest_state'

4. NL2App (자연어-앱 변환)
   • 자연어를 구조화된 API 호출로 변환
   • Gateway를 통해 계통상태(SE) 백엔드 조회

5. Gateway → SE 스텁
   • HTTP GET /se/latest?namespace=ops
   • read_only=true (조회 전용)

6. SE 스텁 → 데이터 처리
   • 데이터베이스에서 최신 스냅샷 조회
   • 모선 전압, 신뢰도, 관측율 등 정량화
   • 예시 결과:
     ```json
     {
       "bus_vm_pu": [
         {"bus_id": 3, "vm_pu": 0.92, "status": "VIOLATION_LOW"},
         {"bus_id": 5, "vm_pu": 1.08, "status": "WARNING_HIGH"}
       ],
       "confidence": 0.97,
       "observable_ratio": 0.94,
       "snapshot_ts": "2025-03-25T14:23:08+09:00"
     }
     ```

7. SE 스텁 → NL2App
   • 결과 반환: bus_vm_pu, confidence:0.97, observable_ratio:0.94

8. NL2App → 오케스트레이터
   • 분석된 자연어 응답: "3번 모선 0.92pu 감지 (관측율 94%)"

9. 오케스트레이터 → 운영자 (최종 응답)
   • **모드**: HOTL (자동 제공)
   • **응답 내용**:
     ```
     '3번 모선 0.92pu 하한 위반 (신뢰도 97%)'
     + 증거 정보(Evidence chain)
     + 스냅샷 타임스탬프: 2025-03-25T14:23:08+09:00
     ```
```

**Evidence Chain 예시**:
```json
{
  "tool_called": "query_app",
  "params": {
    "app": "SE",
    "query_type": "snapshot",
    "namespace": "ops"
  },
  "result_summary": "voltage_violations: [bus_3: 0.92pu]",
  "rag_reference": "표준운영절차 2.1절 - 전압 감시",
  "snapshot_ts": "2025-03-25T14:23:08+09:00"
}
```

---

### F2: 자연어 화면 이동 + 분석 (HOTL)

**발화**: "154kV 계통도 보여주고 전압 낮은 모선 강조해줘"

**목적**: 운영자가 특정 전압등급의 계통도를 보면서 현재 이상 상태를 시각적으로 파악

**데이터 흐름**:

```
1. 운영자 → 오케스트레이터
   • 자연어 발화: "154kV 계통도 보여주고 전압 낮은 모선 강조해줘"
   • 요청 타입: 화면 이동 + 분석 (복합)

2. 오케스트레이터 (Intent 분류)
   • Intent 결정: 화면 이동 + 데이터 강조
   • 모드 결정: HOTL (정보 표시 작업)
   • 병렬 처리: 화면 이동과 분석을 동시 수행

3. 오케스트레이터 → NL Nav (화면 네비게이션)
   [HOTL - 즉시 실행]
   • 도구 호출: navigate_to('sld_154kv')
   • 파라미터: voltage_level='154kV'

4. NL Nav (네비게이션 모듈)
   • 세션 상태 업데이트: session_state = 'sld_154kv'
   • 시각화 엔진에 신호 전송

5. 오케스트레이터 → NL2App (병렬 처리)
   [HOTL - 즉시 실행]
   • 도구 호출: get_powerflow_violations()
   • 파라미터: voltage_level='154kV'

6. NL2App → Gateway → TP 스텁
   • HTTP GET /tp/violations?voltage_level=154kV&namespace=ops
   • 조류계산 애플리케이션에서 위반 데이터 조회

7. TP 스텁 → 결과 처리
   • 과부하 선로, 전압 위반 버스 ID 목록 반환
   • 예시:
     ```json
     {
       "violations": [
         {"type": "VOLTAGE_LOW", "bus_id": 45, "voltage_pu": 0.91},
         {"type": "LINE_OVERLOAD", "line_id": "L089", "loading_pct": 112}
       ],
       "snapshot_ts": "2025-03-25T14:23:08+09:00"
     }
     ```

8. NL2App → NL Nav (결과 전달)
   • 위반 버스 ID 목록: [45, 47, ...]

9. NL Nav → 시각화 엔진
   • 도구 호출: highlight_elements(bus_ids=[45, 47])
   • CSS 클래스 적용: 'violation-highlight'

10. 시각화 엔진 → 운영자 (최종 결과)
    • **모드**: HOTL (자동 표시)
    • **화면 표시**:
      ```
      [154kV 단선도 표시]
      - 이상 모선 45, 47 빨간색 표시
      - 과부하 선로 L089 두께 강조
      - 현재 상태: 2025-03-25T14:23:08+09:00
      ```
```

**Evidence Chain 예시**:
```json
{
  "tool_called": "get_powerflow_violations",
  "params": {
    "voltage_level": "154kV",
    "namespace": "ops"
  },
  "result_summary": "violations: [bus_45: 0.91pu, L089: 112%]",
  "rag_reference": "계통도 시각화 기준 2.3절",
  "snapshot_ts": "2025-03-25T14:23:08+09:00"
}
```

---

### F3: What-if 스터디 (HITL)

**발화**: "5번 차단기 개방하면 과부하 선로 생기나?"

**목적**: 운영자가 제안한 운영 조치(차단기 개방)를 스터디 환경에서 가상 실행하고, 결과를 검토한 후 실제 적용 여부를 결정

**데이터 흐름**:

```
1. 운영자 → 오케스트레이터
   • 자연어 발화: "5번 차단기 개방하면 과부하 선로 생기나?"
   • 요청 타입: What-if 스터디

2. 오케스트레이터 (Intent 분류)
   • Intent 결정: 스터디/분석
   • 모드 결정: Study 격리 모드 (운영 데이터 보호)
   • 타겟 모듈: 계통검토(System Review)

3. 오케스트레이터 → 계통검토 모듈
   • 도구 호출: analyze_study_scenario()
   • 파라미터: scenario_type='breaker_open', breaker_id=5

4. 계통검토 → Gateway
   • 도구 호출: create_study({open_breaker: 5})
   • 파라미터: namespace='study:{sid}'

5. Gateway → Study 스텁
   • HTTP POST /study/create?study_id={sid}
   • 헤더: namespace='study:{sid}'

6. Study 스텁 (데이터 격리)
   • 운영 데이터 복사: COPY ops:* → study:{sid}:*
   • Redis에서 ops 네임스페이스의 모든 데이터를 스터디 전용 네임스페이스로 복사
   • 이제부터 모든 수정은 study:{sid} 네임스페이스에서만 발생

7. Study 스텁 → 계산 수행
   • 차단기 5 상태를 'OPEN'으로 변경
   • pandapower 라이브러리를 사용하여 조류 재계산
   • N-1 기준에 따른 신뢰성 확인

8. Study 스텁 → 계통검토 (결과 반환)
   • StudyResult 반환:
     ```json
     {
       "study_id": "STD-20250325-001",
       "scenario": "breaker_5_open",
       "violations": [
         {
           "type": "LINE_OVERLOAD",
           "line_id": "L089",
           "loading_before": "98%",
           "loading_after": "112%",
           "emergency_rating": "120%"
         }
       ],
       "requires_hitl": true,
       "recommendations": [
         {
           "action": "increase_generation",
           "generator_id": "G3",
           "mw_delta": 15,
           "reason": "reduce_L089_loading"
         }
       ],
       "snapshot_ts": "2025-03-25T14:23:08+09:00"
     }
     ```

9. 계통검토 → 오케스트레이터
   • 스터디 결과 분석
   • HITL 필요 여부 판단

10. 오케스트레이터 → HITL 모듈
    • 도구 호출: request_human_approval()
    • 파라미터:
      ```json
      {
        "request_type": "study_result_review",
        "study_id": "STD-20250325-001",
        "violations": ["L089: 98% → 112%"],
        "recommendations": ["G3 +15MW"],
        "evidence_chain": {...},
        "requires_action": true
      }
      ```

11. HITL → 운영자 (승인 대기)
    • **모드**: HITL (운영자 승인 필수)
    • **요청 사항**:
      ```
      [스터디 결과 요약]
      • 시나리오: 5번 차단기 개방
      • 발생 위반: L089 선로 112% 과부하
      • 복구 권고사항:
        - G3 발전기 +15MW 증가
        - 또는 5번 차단기 개방 불가

      [승인/거부 선택]
      ☐ 승인 (G3 +15MW 권고 수용)
      ☐ 거부 (5번 차단기 개방 취소)
      ☐ 대체안 검토 (다른 시나리오)
      ```

12. 운영자 → HITL (의사결정)
    • 승인/거부 의사 전달
    • 예시: "승인" 선택 시, 실제 G3 발전기 출력 증가 조치가 권고됨
    • 예시: "거부" 선택 시, 스터디 결과는 폐기되고 차단기는 원래 상태 유지

13. Study 스텁 → 정리
    • 운영자가 거부한 경우: study:{sid} 네임스페이스의 모든 데이터 삭제
    • 운영자가 승인한 경우: 권고사항을 HITL 이력에 기록
```

**Evidence Chain 예시**:
```json
{
  "tool_called": "run_n1_contingency",
  "params": {
    "namespace": "study:STD-20250325-001",
    "scenario": "breaker_5_open",
    "tier": 1
  },
  "result_summary": "violations: [L089: 112%], recommendations: [G3+15MW]",
  "rag_reference": "N-1 연쇄탈락 대응절차 5.2절",
  "snapshot_ts": "2025-03-25T14:23:08+09:00"
}
```

**Study 격리 모드의 이점**:
- 운영 데이터(ops) 보호: 가상 시뮬레이션이 실제 계통 데이터를 변경하지 않음
- 다중 스터디 병렬 처리: 여러 스터디를 동시에 수행 가능
- 감사(Audit) 용이: 스터디 시나리오와 결과를 별도로 추적

---

### F4: 알람 분석 + 복구 조치 (HITL)

**발화**: "지금 심각한 알람 분석하고 관련 화면 열어줘"

**목적**: 운영자가 현재 발생 중인 알람의 근본 원인을 파악하고, AI가 제시하는 복구 조치를 검토한 후 승인

**데이터 흐름**:

```
1. 운영자 → 오케스트레이터
   • 자연어 발화: "지금 심각한 알람 분석하고 관련 화면 열어줘"
   • 요청 타입: 알람 분석 + 화면 이동

2. 오케스트레이터 (Intent 분류 및 병렬 처리)
   • Intent 결정: 알람 분석 + 정보 표시
   • 모드 분류:
     - 화면 이동: HOTL (즉시 실행)
     - 알람 분석 및 권고: HITL (운영자 검토 필요)
   • 병렬 처리 시작

3-1. 오케스트레이터 → NL Nav [병렬, HOTL]
    • 도구 호출: navigate_to('alarm_list')
    • 즉시 알람 목록 화면으로 이동

3-2. 오케스트레이터 → 알람 분석 모듈 [병렬, HITL]
    • 도구 호출: get_active_alarms()
    • 파라미터: severity_filter='CRITICAL'

4. 알람 분석 (데이터 수집)
   • Gateway를 통해 알람 시스템 조회
   • 현재 활성 알람 목록 획득:
     ```json
     {
       "alarms": [
         {
           "alarm_id": "ALM-2025-03-25-001",
           "severity": "CRITICAL",
           "type": "LINE_OVERLOAD",
           "line_id": "L089",
           "message": "L089 과부하 112%",
           "timestamp": "2025-03-25T14:23:00+09:00"
         }
       ]
     }
     ```

5. 알람 분석 → 클러스터링 (근본 원인 그룹화)
   • 도구 호출: cluster_alarms()
   • 관련 알람들을 함께 분석:
     ```
     클러스터 A (근본 원인: 트립):
     - ALM-001: L089 과부하
     - ALM-002: 5번 모선 저전압
     - ALM-003: G3 출력 감소

     원인 가설: 5번 차단기 트립 → L089 우회 → 과부하
     ```

6. 알람 분석 → RAG (유사 이력 검색)
   • 도구 호출: search_rag()
   • 파라미터: query='L089 과부하 + 저전압', context='alarm_history'
   • RAG 데이터베이스 검색:
     ```
     [관련 이력]
     • 2025-03-20: 동일 선로 112% → G3 +20MW로 해결
     • 2024-11-15: L089 과부하 → 수요 감축 권고

     [SOP 참조]
     • SOP-3.2절 "과부하 선로 복구 절차"
       - 우선 순위 1: 발전기 출력 증가
       - 우선 순위 2: 수요 차단
       - 우선 순위 3: 회선 절체
     ```

7. 알람 분석 → 복구 계획 수립
   • 도구 호출: generate_recovery_plan()
   • RAG와 SOP를 기반으로 권고사항 생성:
     ```json
     {
       "root_cause": "Breaker_5_trip",
       "root_cause_confidence": 0.92,
       "recovery_plan": {
         "primary_action": "increase_generation_G3_by_15MW",
         "backup_actions": [
           "reduce_demand_zone_B",
           "switch_line_L090"
         ],
         "expected_result": "L089 loading: 112% → 95%"
       },
       "sop_reference": "SOP-3.2절 과부하 선로 복구",
       "estimated_execution_time": "5분"
     }
     ```

8. 알람 분석 → 오케스트레이터
   • 분석 완료: root_causes, RecoveryPlan, SOP 참조 전달

9. 오케스트레이터 → HITL 모듈
   • 도구 호출: request_human_approval()
   • HITL 요청 생성:
     ```json
     {
       "request_type": "alarm_recovery",
       "alarms": [...],
       "analysis": {
         "root_cause": "Breaker_5_trip",
         "confidence": 0.92
       },
       "recovery_plan": {...},
       "sop_reference": "SOP-3.2절",
       "evidence_chain": {...}
     }
     ```

10. HITL → 운영자 (승인 대기)
    • **모드**: HITL (운영자 승인 필수)
    • **화면 표시**:
      ```
      [알람 목록 화면]
      알람 ID         | 심각도     | 메시지                | 시간
      ALM-2025-03-25-001 | CRITICAL | L089 과부하 112% | 14:23:00
      ALM-2025-03-25-002 | WARNING  | 5번 모선 0.92pu  | 14:23:00

      [근본 원인 분석]
      원인: 5번 차단기 트립으로 인한 L089 우회
      신뢰도: 92%

      [복구 조치 권고]
      ☑ 1순위: G3 발전기 +15MW 증가
      ☐ 2순위: B 지역 수요 차단
      ☐ 3순위: L090 회선 절체

      관련 SOP: SOP-3.2절 과부하 선로 복구
      예상 소요 시간: 5분

      [승인/거부 선택]
      [승인] [거부] [대체안 검토]
      ```

11. 운영자 → HITL (의사결정)
    • 예시 1: "승인" → G3 +15MW 조치가 SCADA에 전달 (별도 공정)
    • 예시 2: "거부" → 운영자가 다른 방법으로 해결
    • 예시 3: "대체안 검토" → 2순위 또는 3순위 방안으로 다시 분석

12. HITL → 이력 기록
    • 운영자의 의사결정 결과를 감사 로그에 기록
    • 결과: 승인 여부, 실행 시간, 효과 측정
```

**Evidence Chain 예시**:
```json
{
  "tool_called": "generate_recovery_plan",
  "params": {
    "alarms": ["ALM-2025-03-25-001"],
    "include_rag": true,
    "sop_version": "latest"
  },
  "result_summary": "root_cause: Breaker_5_trip (92%), recovery: G3+15MW",
  "rag_reference": "SOP-3.2절 과부하 선로 복구, 이력: 2025-03-20",
  "snapshot_ts": "2025-03-25T14:23:08+09:00"
}
```

**알람 분석의 핵심 기능**:
- **근본 원인 분석(RCA)**: 단순 증상이 아닌 실제 원인 파악
- **RAG 활용**: 과거 이력과 SOP를 자동으로 검색
- **다단계 권고**: 1차, 2차, 3차 복구 방안을 체계적으로 제시
- **신뢰도 표시**: 분석 신뢰도를 정량화하여 운영자가 판단할 수 있도록 함

---

### F5: 능동형 AI 인사이트 (자동 트리거) — Phase 4

**트리거**: (운영자 질의 없음) APScheduler에 의한 정기적 자동 실행

**목적**: 운영자의 사전 요청 없이도, 계통 이상 징후를 자동 감지하고 미리 경고하는 사전 예방 기능

**데이터 흐름**:

```
1. APScheduler (일정 관리)
   • 매 5분마다 자동 트리거
   • 예약된 작업: run_proactive_insights()

2. 인사이트 모듈 활성화
   • 도구 호출: run_grid_health_check()
   • 파라미터: evaluation_period='last_5min'
   • 목표: 정량 기준에 따른 계통 건강도 평가

3. 인사이트 → Gateway (데이터 수집)
   • 도구 호출: query_app('SE', 'snapshot')
   • 도구 호출: query_app('TP', 'snapshot')
   • 최신 계통상태 스냅샷 조회 (5분마다 최신)

4. SE/TP 백엔드 (데이터 반환)
   • 계통상태: 모선 전압, 주파수
   • 조류상태: 선로 부하, 발전기 출력
   • 예시:
     ```json
     {
       "bus_voltages": [
         {"bus_id": 12, "vm_pu": 0.98},
         {"bus_id": 45, "vm_pu": 0.88, "trend": "DECREASING"}
       ],
       "line_loadings": [
         {"line_id": "L089", "loading_pct": 95}
       ],
       "frequency": 59.95,
       "snapshot_ts": "2025-03-25T14:28:00+09:00"
     }
     ```

5. 인사이트 → 예측 모듈 (1시간 후 부하 예측)
   • 도구 호출: get_forecast()
   • 파라미터: forecast_horizon='1hour', granularity='5min'
   • 기상 데이터, 과거 수요 패턴 활용
   • 예측 결과:
     ```json
     {
       "forecast_time": "2025-03-25T15:30:00+09:00",
       "predicted_demand": 8500,
       "predicted_renewable_gen": 1200,
       "predicted_line_loadings": [
         {"line_id": "L089", "loading_pct": 105}
       ],
       "confidence_interval": 0.85
     }
     ```

6. 인사이트 (이상 징후 감지)
   • 정량 기준 검토 (JSON으로 정의된 기준 직접 참조):
     ```json
     {
       "voltage_threshold_high": 1.10,
       "voltage_threshold_low": 0.90,
       "line_loading_warning": 90,
       "line_loading_emergency": 110,
       "frequency_threshold": [59.5, 60.5],
       "forecast_margin": 0.05
     }
     ```
   • 현재 상태 평가:
     ```
     ✓ 모든 모선 전압 정상 (0.90~1.10 범위)
     ✓ 선로 부하 정상 (95% < 110%)
     ✓ 주파수 정상 (59.95)
     ⚠ 1시간 후 부하 예측: L089 105% (경고 단계)
       → VSM(Voltage Stability Margin) 12% 감소 예상
     ```

7. 인사이트 → 오케스트레이터 (이상 징후 전달)
   • 도구 호출: report_grid_anomaly()
   • 파라미터:
     ```json
     {
       "anomaly_type": "FORECAST_WARNING",
       "severity": "LOW_MEDIUM",
       "description": "VSM 12% 주의 - 1시간 후",
       "affected_elements": ["L089"],
       "recommendation": "pre_positioning_required",
       "confidence": 0.85,
       "snapshot_ts": "2025-03-25T14:28:00+09:00"
     }
     ```

8. 오케스트레이터 (모드 분류)
   • HOTL 부분: 경고 배너 표시 (즉시)
   • HITL 부분: 예방 조치 등록 (운영자 검토)

9. 오케스트레이터 → 시각화 (HOTL)
   • 도구 호출: display_alert_banner()
   • HOTL 배너 즉시 표시:
     ```
     ⚠️ [주의] VSM 12% 주의
     예상 발생 시간: 15:30경
     관련 선로: L089
     현재 조치: 없음
     ```

10. 오케스트레이터 → HITL 모듈 (HITL)
    • 도구 호출: register_preventive_action()
    • HITL 요청 생성:
      ```json
      {
        "request_type": "preventive_action",
        "forecast_risk": "HIGH_1HOUR",
        "anomaly": "VSM 12% 감소",
        "suggested_actions": [
          "Increase_G3_by_10MW",
          "Pre_position_for_contingency"
        ],
        "execution_deadline": "2025-03-25T15:25:00+09:00",
        "evidence_chain": {...}
      }
      ```

11. HITL → 운영자 (승인 대기)
    • **모드**: HITL (운영자 검토 필수)
    • **요청 사항**:
      ```
      [예보 정보]
      • 현재 시간: 14:28:00
      • 예보 시간: 15:30경 (약 1시간 후)
      • 이상 징후: L089 선로 부하 95% → 105% 예상
      • VSM(전압 안정도 여유): 12% 감소 예상
      • 신뢰도: 85%

      [사전 조치 권고]
      ☐ G3 발전기 +10MW 사전 증가
      ☐ 수요 감축 준비

      [실행 기한]
      15:25:00까지 조치 필수 (5분 전)

      [승인/거부 선택]
      [조치 동의] [검토 미연기] [취소]
      ```

12. 운영자 → HITL (의사결정)
    • 예시 1: "조치 동의" → G3 +10MW 조치가 우선순위 대기열에 등록
    • 예시 2: "검토 미연기" → 15분 후 재확인 (현재 상태 재평가)
    • 예시 3: "취소" → 경고 무시 (운영자 판단)

13. HITL → 이력 기록 및 모니터링
    • 운영자의 의사결정 기록
    • 예보 시간 도래 후 실제 결과와 비교
    • 예측 정확도 피드백 → AI 모델 개선
```

**Evidence Chain 예시**:
```json
{
  "tool_called": "run_grid_health_check",
  "params": {
    "evaluation_period": "last_5min",
    "include_forecast": true,
    "criteria_version": "v5.1"
  },
  "result_summary": "forecast_warning: VSM 12% decrease in 1 hour",
  "rag_reference": "예방 운영 기준 4.1절",
  "snapshot_ts": "2025-03-25T14:28:00+09:00"
}
```

**능동형 인사이트의 핵심 가치**:
- **자동 감지**: 운영자의 질의 없이 자동으로 이상 징후 감지
- **예측 기반**: 현재뿐 아니라 미래 1시간 상태 예측
- **사전 경고**: 문제 발생 전에 운영자에게 알림
- **의사결정 지원**: HOTL 배너로는 정보만 표시, HITL로는 구체적 조치 승인 요청
- **지속적 개선**: 운영자의 의사결정 결과와 예측 결과를 비교하여 모델 개선

---

## 4. HITL/HOTL 모드 분류 규칙

### 4.1 HOTL (Hands-Off-The-Loop) — 자동 실행
**특징**: 계통 상태 변경 없음, 순수 정보 제공

| 활동 | 예시 | 특성 |
|------|------|------|
| 조회(Query) | 현재 전압 조회, 과부하 선로 검색 | Read-only, 실시간 데이터 |
| 화면 이동 | 계통도 전환, 알람 목록 이동 | UI 상태 변경만, 계통 영향 없음 |
| 정보 표시 | 배너, 팝업, 강조 표시 | 시각적 표시만 |
| 분석 결과 조회 | 원인 분석, 유사 사례 검색 | 읽기 전용 분석 결과 |

**처리 흐름**:
```
운영자 발화
  ↓
오케스트레이터 (Intent=조회/표시 판정)
  ↓
HOTL 모듈 (즉시 실행)
  ↓
결과 제공 (운영자 승인 불필요)
```

**응답 시간**: 수 초 이내

---

### 4.2 HITL (Human-In-The-Loop) — 운영자 승인 필수
**특징**: 계통 상태 변경 또는 운영자 판단 필요

| 활동 | 예시 | 특성 |
|------|------|------|
| 조치 권고 | "G3 +15MW 권고" | 실제 적용이 가능한 구체적 조치 |
| Study 적용 | What-if 시나리오 결과 적용 | 계통 상태 변경 수반 |
| 알람 복구 | 자동 복구 조치 제안 | 운영자 의사결정 필요 |
| 사전 조치 | 예방적 발전기 증발 | 미래 대비 조치 |

**처리 흐름**:
```
운영자 발화
  ↓
오케스트레이터 (Intent=조치/분석 판정)
  ↓
분석 모듈 (시나리오 계산)
  ↓
HITL 모듈 (승인 요청)
  ↓
운영자 검토 (승인/거부)
  ↓
결과 적용 또는 폐기
```

**응답 시간**: 운영자 승인까지 (보통 1~5분)

**운영자 승인 형식**:
```json
{
  "hitl_request_id": "HITL-20250325-001",
  "operator_decision": "approved",
  "decision_timestamp": "2025-03-25T14:25:00+09:00",
  "operator_notes": "선호 조치 확인"
}
```

---

### 4.3 Study 격리 모드
**특징**: 운영 데이터를 보호하면서 가상 시뮬레이션 수행

| 단계 | 동작 | 데이터 영향 |
|------|------|-----------|
| 생성 | 운영 데이터 복사 | ops → study:{sid} |
| 실행 | 격리된 네임스페이스에서 계산 | study:{sid}만 수정 |
| 평가 | 시뮬레이션 결과 제시 | ops 데이터 미수정 |
| 완료 | 승인 시 권고 기록, 거부 시 삭제 | 실제 적용은 별도 HITL |

**격리의 이점**:
- **안전성**: 운영 데이터 자동 보호
- **병렬 처리**: 다중 What-if 분석 동시 수행 가능
- **감사**: 스터디 과정과 결과의 완전 추적

---

## 5. Evidence Chain 상세 구조

모든 AI 응답에 포함되는 증거 체인은 다음과 같은 구조를 따릅니다:

### 5.1 Evidence Chain JSON 스키마

```json
{
  "evidence_id": "EV-20250325-001",
  "timestamp": "2025-03-25T14:23:08+09:00",
  "tool_called": "query_app",
  "params": {
    "app": "SE",
    "query_type": "snapshot",
    "namespace": "ops"
  },
  "result_summary": "voltage_violations: [bus_3: 0.92pu, bus_5: 1.08pu]",
  "data_source": "SE_backend",
  "confidence_score": 0.97,
  "observable_ratio": 0.94,
  "rag_reference": [
    {
      "type": "SOP",
      "reference": "SOP 2.1절 - 전압 감시",
      "relevance": "high"
    },
    {
      "type": "historical_case",
      "reference": "2025-03-20 L089 과부하 사건",
      "relevance": "medium"
    }
  ],
  "model_version": "v5.1.2",
  "execution_time_ms": 850
}
```

### 5.2 Evidence Chain 구성 요소 설명

| 요소 | 설명 | 예시 |
|------|------|------|
| **evidence_id** | 증거 체인 고유 ID | EV-20250325-001 |
| **timestamp** | 데이터 생성 시간 (스냅샷 시간) | 2025-03-25T14:23:08+09:00 |
| **tool_called** | 호출된 도구/함수 명칭 | query_app, run_n1_contingency |
| **params** | 도구에 전달된 파라미터 | {app: "SE", namespace: "ops"} |
| **result_summary** | 도구 실행 결과 요약 | "voltage_violations: [bus_3: 0.92pu]" |
| **data_source** | 데이터 출처 | SE_backend, TP_backend, RAG_db |
| **confidence_score** | 결과의 신뢰도 (0~1) | 0.97 = 97% 신뢰도 |
| **observable_ratio** | 관측된 데이터 비율 | 0.94 = 94% 관측됨 |
| **rag_reference** | RAG에서 검색된 관련 정보 | [SOP 2.1절, 과거 사례] |
| **model_version** | 사용된 AI 모델 버전 | v5.1.2 |
| **execution_time_ms** | 도구 실행 소요 시간 | 850ms |

### 5.3 Evidence Chain 활용 사례

**사례 1**: 오케스트레이터의 권고 거부
```
운영자: "G3 +15MW가 정말 필요해? 근거 보여줘."
응답:
[Evidence chain]
Tool: run_n1_contingency
Result: L089 loading 112% → 98% (G3+15MW 시)
Confidence: 92%
RAG: SOP-3.2절 "과부하 선로 복구", 2025-03-20 유사 사례
```

**사례 2**: 감사(Audit) 목적
```
감사자: "3월 25일 14:23의 AI 분석 근거는?"
조회: HITL-20250325-001의 Evidence chain
결과:
- 데이터 출처: SE 스냅샷 (관측율 94%)
- 신뢰도: 97%
- 참고 SOP: SOP 2.1절
- 운영자 의사결정: 승인 (14:25)
- 결과: 실제 L089 부하 98%로 감소 확인 ✓
```

---

## 6. 데이터 흐름 아키텍처

### 6.1 계층 구조도

```
┌─────────────────────────────────────────────────────────┐
│                    운영자 (Operator UI)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │ 자연어 발화
                       ↓
┌─────────────────────────────────────────────────────────┐
│         오케스트레이터 (Orchestrator)                    │
│  • Intent 분류 (조회/표시/조치)                         │
│  • 모드 결정 (HOTL/HITL)                                │
│  • 병렬/순차 처리 판정                                  │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ↓            ↓            ↓
      ┌──────┐    ┌──────┐    ┌──────────┐
      │HOTL  │    │HOTL  │    │HITL      │
      │모듈  │    │모듈  │    │모듈      │
      └──┬───┘    └──┬───┘    └──┬───────┘
         │           │           │
    NL Nav      NL2App      계통검토
    알람분석      인사이트    HITL 분석
         │           │           │
         └────────────┼───────────┘
                      │
                      ↓
          ┌───────────────────────┐
          │  Gateway (통합 게이트웨이) │
          │  • Tool 호출 관리      │
          │  • 접근 제어          │
          │  • 에러 처리          │
          └────────┬──────────────┘
                   │
      ┌────────────┼───────────────────┐
      │            │                   │
      ↓            ↓                   ↓
    ┌────┐      ┌────┐             ┌──────┐
    │SE  │      │TP  │             │Study │
    │스텁 │      │스텁 │             │스텁  │
    │    │      │    │             │      │
    │계통 │      │조류 │             │격리  │
    │상태 │      │계산 │             │시뮬  │
    └────┘      └────┘             └──────┘
```

### 6.2 데이터 흐름 경로 (Path Flow)

**경로 1**: HOTL 조회 (F1)
```
운영자 → 오케스트레이터 → NL2App → Gateway → SE/TP → 결과 → 운영자
소요 시간: ~2-3초
```

**경로 2**: HOTL 화면 이동 (F2)
```
운영자 → 오케스트레이터 → [병렬] (NL Nav, NL2App) → 시각화 → 운영자
소요 시간: ~3-4초
```

**경로 3**: HITL Study (F3)
```
운영자 → 오케스트레이터 → 계통검토 → Gateway → Study → 계산 → HITL
→ 운영자 (승인 대기) → 결과 기록
소요 시간: ~30초 + 운영자 의사결정 시간
```

**경로 4**: HITL 알람 분석 (F4)
```
운영자 → 오케스트레이터 → [병렬] (NL Nav, 알람분석) → RAG + SOP 검색
→ HITL → 운영자 (승인 대기)
소요 시간: ~5-10초 + 운영자 의사결정 시간
```

**경로 5**: 자동 인사이트 (F5)
```
APScheduler (5분 주기) → 인사이트 → Gateway → SE/TP/예측
→ [병렬] (시각화 배너, HITL 요청) → 운영자
소요 시간: ~3-5초 (자동)
```

---

## 7. 네임스페이스 관리

### 7.1 네임스페이스 종류

| 네임스페이스 | 용도 | 수정 가능 | 격리 | 예시 |
|-------------|------|---------|------|------|
| **ops** | 운영 데이터 (현재 상태) | SCADA만 | 없음 | 모선 전압, 선로 부하 |
| **study:{sid}** | What-if 시뮬레이션 | Study 엔진 | 완전 격리 | 차단기 개방 시나리오 |
| **forecast** | 예측 데이터 (1시간 후) | 예측 모듈 | 읽기 전용 | 예상 부하, VSM |
| **rag** | 역사 데이터 + SOP | 없음 | 읽기 전용 | 과거 사건, 절차 |

### 7.2 네임스페이스 라이프사이클

**ops 네임스페이스** (영구):
- SCADA에서 실시간 갱신
- AI는 읽기만 수행
- 모든 조회의 기본 대상

**study:{sid} 네임스페이스** (임시):
```
1. 생성: 운영자가 What-if 분석 시작
   → Redis COPY ops:* study:{sid}:*

2. 수행: Study 엔진이 격리 환경에서 계산
   → study:{sid}:* 만 수정

3. 평가: 시뮬레이션 결과 제시
   → study:{sid} 읽기만

4. 완료: 운영자 의사결정 후
   → 승인: study:{sid} 데이터만 기록
   → 거부: study:{sid} 전체 삭제
```

---

## 8. 에러 처리 및 복구

### 8.1 주요 에러 시나리오

| 에러 | 발생 상황 | 대응 |
|------|---------|------|
| **Gateway 타임아웃** | SE/TP 응답 지연 | 재시도 + 캐시 데이터 사용 + 운영자 알림 |
| **Study 생성 실패** | Redis 할당 실패 | HITL 요청 거부 + 관리자 알림 |
| **RAG 검색 오류** | 문서 DB 접속 불가 | RAG 참조 없이 응답 제공 (신뢰도 ↓) |
| **예측 모듈 오류** | 예보 계산 실패 | 인사이트 트리거 연기 (다음 주기) |

### 8.2 복구 전략

**자동 복구**:
- 재시도: 최대 3회, 1초 간격
- 캐시 폴백: 최신 캐시 데이터 사용
- 부분 응답: 불가능한 부분만 제외

**수동 복구**:
- 운영자 알림: 에러 메시지 + Evidence chain
- 관리자 알림: 시스템 에러 자동 보고
- 절차 변경: 자동 트리거 일시 중지

---

## 9. 성능 및 확장성

### 9.1 응답 시간 목표

| 시나리오 | 목표 | 실제 기준 |
|---------|------|---------|
| F1 (조회) | < 3초 | 0.8~2.5초 |
| F2 (화면+분석) | < 5초 | 2~4초 |
| F3 (Study) | < 30초 | 5~25초 |
| F4 (알람 분석) | < 10초 | 3~8초 |
| F5 (자동 인사이트) | < 5초 | 2~4초 |

### 9.2 동시 처리 능력

- **동시 조회**: 최대 50개 (HOTL)
- **동시 Study**: 최대 5개 (격리)
- **동시 HITL**: 최대 3개 (운영자 검토 순차)

### 9.3 확장 방안

- **캐싱**: 5분 내 반복 조회는 캐시 사용
- **비동기 처리**: 알람 분석 + RAG 검색 병렬화
- **데이터 분할**: 대용량 Study는 영역별 계산

---

## 10. 감시 및 로깅

### 10.1 감시 지표

```json
{
  "monitoring": {
    "tool_execution_time_ms": 850,
    "cache_hit_ratio": 0.42,
    "error_rate": 0.02,
    "hitl_approval_rate": 0.78,
    "ai_recommendation_acceptance": 0.85,
    "predictive_accuracy_horizon_1h": 0.88
  }
}
```

### 10.2 로깅 포맷

모든 AI 응답에 포함되는 구조화된 로그:

```json
{
  "log_id": "LOG-20250325-001",
  "timestamp": "2025-03-25T14:23:08+09:00",
  "operator_id": "OP-001",
  "scenario": "F1_query_system_state",
  "intent": "query",
  "mode": "HOTL",
  "tool_called": "query_app",
  "response_time_ms": 850,
  "result": "success",
  "evidence_chain": {...},
  "operator_action": "none (HOTL)",
  "outcome": "information_provided"
}
```

### 10.3 감사 추적 (Audit Trail)

모든 HITL 의사결정의 완전한 추적:

```json
{
  "audit_id": "AUDIT-20250325-001",
  "hitl_request_id": "HITL-20250325-001",
  "operator_id": "OP-001",
  "request_timestamp": "2025-03-25T14:23:00+09:00",
  "request_content": "G3 +15MW 권고",
  "decision_timestamp": "2025-03-25T14:25:00+09:00",
  "decision": "approved",
  "decision_rationale": "선호 조치 확인",
  "execution_status": "executed",
  "actual_outcome": "L089 loading 98% (target achieved)"
}
```

---

## 11. 보안 및 접근 제어

### 11.1 read_only vs read_write

**read_only 도구 (HOTL)**:
- Gateway는 Tool 호출 시 read_only=true 강제
- 운영자 권한 불문 실행 가능
- 예: query_app('SE', 'snapshot')

**read_write 도구 (HITL)**:
- 운영자 승인 필수
- Gateway는 HITL 승인 후에만 실행
- 예: run_study(), generate_recovery_plan()

### 11.2 네임스페이스 접근 제어

```
ops (운영 데이터):
  ├─ 읽기: AI 모듈 (모두)
  ├─ 쓰기: SCADA만 (AI 불가)

study:{sid} (격리 데이터):
  ├─ 읽기: 해당 Study 엔진만
  ├─ 쓰기: 해당 Study 엔진만
  ├─ 삭제: HITL 결정 후

forecast (예측 데이터):
  ├─ 읽기: 인사이트 모듈만
  ├─ 쓰기: 예측 엔진만

rag (기록 데이터):
  ├─ 읽기: AI 모듈 (모두)
  ├─ 쓰기: 없음 (읽기 전용)
```

---

## 12. 요약

AI-EMS v5.1의 5가지 핵심 데이터 흐름은 다음 원칙으로 설계되었습니다:

1. **명확한 HOTL/HITL 구분**: 자동 실행과 운영자 승인을 명확히 구분하여 안전성과 효율성 균형
2. **Evidence Chain**: 모든 응답에 투명한 증거 제시로 신뢰도와 추적 가능성 보장
3. **Study 격리**: 운영 데이터를 보호하면서 병렬 시뮬레이션 지원
4. **RAG + SOP**: 과거 사례와 표준 절차를 자동 활용하여 운영자 의사결정 지원
5. **능동형 인사이트**: 자동 감시와 예측으로 사전 예방 가능
6. **완전한 감시 및 감사**: 모든 AI 행동과 운영자 의사결정을 기록하여 지속적 개선 가능

이 설계는 운영자의 최종 의사결정 권한을 보장하면서도, AI가 효과적으로 계통 운영을 지원할 수 있도록 구성되었습니다.

---

**문서 버전**: v1.0
**작성 일자**: 2025-03-25
**언어**: 한국어
**AI-EMS 버전**: v5.1
