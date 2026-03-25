# 전력 도메인 지식 체계 (Domain Knowledge Framework)

**문서 버전:** v5.1
**작성일:** 2026-03-25
**대상:** AI-EMS 독립 프로토타입 (Layer 1 + Layer 2)
**핵심 원칙:** 모든 도메인 지식은 한국 전력규제(산업통상자원부고시)와 공식 전력거래체계(KPX, KEPCO)에 기반

---

## 1. 개요

AI-EMS 프로토타입이 한국 전력계통을 안전하고 신뢰성있게 운영하기 위해서는 다음 3가지 공식 출처의 도메인 지식이 필수적이다:

1. **한국전력거래소 (KPX) 전력거래용어 해설집** (2003.12)
   - 계통 운영자(SO), 급전 담당자, 시장 운영 담당자가 사용하는 공식 용어 400+개
   - 계통기술처, 급전처, 시장운영처 등 부처별 용어 정의
   - 접두어/약자/기술용어 완전 수록

2. **한국전력공사 (KEPCO) 전력관련 용어사전** (2019.08.28)
   - 총 4,372개 항목의 전기공학·전력계통 용어
   - CSV 형식 [순번, 용어, 용어설명]
   - 변전소, 차단기, 계전기, 유연송전시스템(FACTS) 등 광범위한 기술용어

3. **전력계통 신뢰도 및 전기품질 유지기준** (산업통상자원부고시 제2023-65호, 2023.04.25)
   - 법적 근거: 전기사업법 제16조
   - 전압, 주파수, 예비력, 안정도, 상정고장 등 정량적 기준의 유일한 공식 소스
   - Phase 1 MDP에서 모든 정규화(normalization) 기준으로 사용

---

## 2. 참조 문서 목록

### 2.1 핵심 3대 공식 문서

| 문서명 | 발행처 | 발행일 | 항목 수 | 용도 |
|--------|--------|--------|---------|------|
| 전력거래용어 해설집 | 한국전력거래소(KPX) | 2003.12 | 400+ | 계통운영 용어, 거래용어, EMS 용어 |
| 전력관련 용어사전 정보 | 한국전력공사(KEPCO) | 2019.08.28 | 4,372 | 기술용어, 설비명, 부품명 |
| 전력계통 신뢰도 및 전기품질 유지기준 | 산업통상자원부 | 2023.04.25 | 법정 기준 | 전압, 주파수, 예비력, N-1, 고장기준 |

### 2.2 추가 참조 자료 (구축 예정)

- 변전소 단선도(SLD) 도면 기준 및 용어 정의
- 한국 실계통 PSS/E .raw 포맷 및 bus_id 매핑 규칙
- pandapower 네트워크 모델 구축 가이드
- 급전 지시 프로토콜 및 상정고장 평가 절차
- DER/신재생 계통연계 규칙 및 제약조건
- 알람 발생 기준 및 운영자 조치 지침

---

## 3. 6대 도메인 지식 카테고리

AI 에이전트가 효과적으로 한국 전력계통을 이해하고 조작하기 위해, 다음 6개 카테고리로 도메인 지식을 조직화한다:

### 3.1 계통 구조 및 토폴로지 (Grid Topology)

#### 3.1.1 기본 개념 (KPX, KEPCO 정의)

- **전력계통** (전력네트워크)
  - 발전소 → 송전선로 → 변전소 → 배전선로 → 부하 로 구성된 연결망
  - 한국 전력계통은 중앙급전발전기(dispatchable) + 비중앙급전발전기(non-dispatchable) + DER + 부하의 복합계통
  - 주파수: 60Hz 기준 (AC, 3상 시스템)

- **모선 (Bus)** — KPX, KEPCO 용어
  - 발전기, 부하, 변압기, 송전선로가 연결되는 노드
  - pandapower에서 `pp.create_bus()` 객체
  - 고유 식별자: `bus_id` (정수) 또는 `name` (문자열)

- **모선 분리 (Bus Splitting)**
  - 단일 물리 모선을 여러 개의 전기적 구획으로 분할
  - 차단기(CB) 분리 시 발생 가능
  - pandapower 시뮬레이션에서 특별한 처리 필요

- **모선 방식 (Bus Arrangement)**
  - 변전소 내 모선과 차단기의 배치 방식
  - KPX/KEPCO 용어: 일과이분의일차단기방식, 환형방식, 복층방식 등
  - EMS/SCADA에서 토폴로지 프로세싱 입력값

#### 3.1.2 송전선로 (Transmission Line)

- **특성 정수 (Line Constant)** — KPX 정의
  - 저항(R), 리액턴스(X), 수용량(Susceptance) 등
  - 거리당 단위값: R/km, X/km
  - pandapower: `length_km`, `r_ohm_per_km`, `x_ohm_per_km`

- **이중회선 (Parallel Lines)**
  - 같은 구간에 2회선 이상 송전선
  - 이중고장(Double Contingency): 병행회선 가공송전선로 동시 고장 (산업통상자원부고시)
  - N-1 기준에서는 회선 1개 탈락 검토, N-2는 회선 2개 동시 탈락

#### 3.1.3 변전소 (Substation)

- **변전소 종류** (KEPCO 분류)
  - 일차변전소: 발전소 접속 (발전소 인근)
  - 특고변전소: 154kV~345kV 전압 레벨
  - 고압변전소: 66kV~154kV 전압 레벨
  - 자가용변전소: 산업용 대형 부하 소유
  - 수배전변전소: 22.9kV~66kV 저전압 계통

- **단선도 (SLD; Single Line Diagram)**
  - 변전소 내부 구조를 2D 다이어그램으로 표현
  - 모선(Bus), 차단기(CB), 단로기(Switch), 변압기(TR), 계전기(Relay) 등 표시
  - pandapower의 `pp.to_json()` / `pp.from_json()` 기반으로 SLD 디지털화

#### 3.1.4 변압기 (Transformer)

- **변압기 탭 (Transformer Tap)**
  - 1차(고압)와 2차(저압) 권선 비율 조정
  - 정상 범위: 90%~110% (공칭값의)
  - 전압 조정에 사용: `vn_hv_kv`, `vn_lv_kv`, `tap_pos`, `tap_neutral`

- **변성기 (Current Transformer; CT, Potential Transformer; PT)**
  - 계측용 변성기: SCADA/보호 계전기 신호 취득
  - KPX 약자: CT, PT
  - 오류나 포화 고려 필요 (실제 계통 모델에서)

- **병렬 리액터 (Shunt Reactor)**
  - 무효전력 보상용, 송전선 개방 시 과전압 억제
  - pandapower: `pp.create_shunt()`
  - MVar 단위 정격용량

#### 3.1.5 회로차단기 (Circuit Breaker; CB)

- **차단기 종류** (KEPCO 분류)
  - 자기차단기 (Magnetic Breaker)
  - 가스차단기 (Gas-Insulated Breaker; GIS)
  - 진공차단기 (Vacuum Breaker)
  - 유입차단기 (Oil Breaker)

- **차단 동작**
  - 정상 운영: CB는 Closed 상태
  - 보호: 고장 감지 시 계전기 신호로 자동 또는 수동으로 Open
  - pandapower: `in_service` (True=Closed, False=Open)

- **차단 실패 (Breaker Failure)**
  - CB가 고장 신호를 받았으나 실제로 개방되지 않는 경우
  - 이중고장(Double Contingency) 형태: 고장선 1회선 + 차단기 차단실패
  - 산업통상자원부고시에서 명시적 정의

---

### 3.2 전력 흐름 및 조류 (Power Flow)

#### 3.2.1 전력 흐름의 기본 개념

- **유효전력 (Active Power; P)** — KPX, KEPCO 정의
  - 단위: MW (메가와트)
  - 발전기가 공급하는 실제 일 (에너지)
  - 부하가 소비하는 유효 전력

- **무효전력 (Reactive Power; Q)** — KPX 정의
  - 단위: Mvar (메가바르)
  - 발전기가 공급하거나 부하/설비가 소비
  - 전압 유지에 필수적 (송전선 인덕턴스 때문)
  - 정의: Q = V × I × sin(θ)

- **전력 조류 (Power Flow)**
  - 발전기 → 송전선 → 변압기 → 부하 로 흐르는 P, Q 흐름
  - pandapower `pp.runpf()` / `pp.runopp()` 로 계산
  - 선로 조류: MW, Mvar 단위
  - 부하율: loading_pct = 실제조류 / 정격용량 × 100% (100% 이상 = 과부하)

- **조류 방정식 (Power Flow Equation)**
  - ACPF (AC Power Flow): 비선형
  - DCPF (DC Power Flow): 선형화 근사
  - pandapower는 ACPF 기반 (비선형 방정식 시스템 풀이)

#### 3.2.2 역률 (Power Factor)

- **정의** — KPX/KEPCO
  - cos(θ) = P / S, 여기서 S = √(P² + Q²)
  - 값 범위: 0 ~ 1

- **선행(Lagging) vs 후행(Leading)**
  - Lagging (지상): Q > 0, 부하 특성 (저항-귀납성)
  - Leading (진상): Q < 0, 발전기 또는 커패시터 특성

- **정규화 기준**
  - 한국 전력계통 운영 기준: 역률 0.85 뒤짐 ~ 0.95 앞섬
  - 산업통상자원부고시 제23조: 발전설비 무효전력 운영기준

#### 3.2.3 전압 강하 (Voltage Drop)

- **정의** — KPX/KEPCO
  - V_drop = V_source - V_load = I × Z (근사)
  - 송전선로와 변압기에서 발생

- **계산식** (선로)
  - P_loss = I² × R = (P² + Q²) / V² × R
  - 손실 전력은 부하 크기(P², Q²)에 비례

- **전압 조정 (Voltage Regulation)**
  - 부하 변화 시 수전단 전압을 목표치 근처로 유지
  - 수단: 변압기 탭, 동기발전기 여자(AVR), SVC/STATCOM 등
  - 산업통상자원부고시 제5조: 전압조정목표

---

### 3.3 전압 안정도 및 기준 (Voltage Standards)

#### 3.3.1 전압 기준 — 산업통상자원부고시 제2023-65호 제5조, 6조

**한국 전력계통의 정법 전압 기준:**

| 계통 레벨 | 공칭전압 | 조정목표 | 유지범위 |
|-----------|---------|---------|---------|
| 345kV | 345kV | ±5% (328~362kV) | ±10% (311~380kV) |
| 154kV | 154kV | 95~105% (146~162kV) | ±10% (139~170kV) |
| 66kV | 66kV | 97~103% (64~68kV) | ±10% (59~73kV) |
| 22.9kV | 22.9kV | 99~101% (22.7~23.1kV) | (미규정) |

- **정규화 단위: pu (per unit)**
  - pu = 실제전압(kV) / 공칭전압(kV)
  - 345kV, 154kV, 66kV 각각 고유의 base voltage
  - pandapower에서 자동 계산: `vm_pu` (전압 크기, pu)

- **전압 조정목표 (제5조)**
  - 이 범위를 벗어나면 EMS/운영자에 알람 발생
  - AI 에이전트: "전압이 목표범위 밖입니다" 진단

- **전압 유지범위 (제6조)**
  - 비상상황(고장, 과도현상) 포함
  - 이 범위를 벗어나면 기기 손상 위험
  - 운영자 긴급 조치 필요

#### 3.3.2 전압 불안정 현상

- **전압붕괴 (Voltage Collapse)** — KPX 정의
  - 송전선 과부하 또는 부하/발전기 제약으로 전압이 급격히 저하
  - 복구 불가능한 급격한 저하 특징
  - 광역정전(Blackout) 전조 현상

- **전압변동률 (Voltage Fluctuation)** — KPX/KEPCO
  - 전압이 진동하는 현상 (예: ±3%)
  - 풍력발전, DER 변동성으로 악화 가능

- **전압불평형 (Voltage Unbalance)** — 산업통상자원부고시 제7조
  - 3상 전압 크기가 균형을 이루지 못함
  - 정상 운영: 송전설비 불평형률 ≤ 3%, 발전기 상간전압불평형 ≤ 3%
  - pandapower: 3상 모델에서 검토 필요

#### 3.3.3 전압 안정도 (Voltage Stability) — KPX 정의

- **정의**
  - 계통이 부하 또는 외란(고장, 발전기 탈락)에 대응하여 안전 전압 범위 내에서 안정을 유지하는 능력
  - 시간 스케일: 중간~장기 (수초~수십초)

- **평가 기준**
  - 민감도 분석: dV/dQ (전압에 대한 무효전력 감응도)
  - dV/dQ < 0: 안정, > 0: 불안정 임박
  - 매뉴얼 또는 자동 조정 필요

- **대응 수단**
  - 동기발전기 여자(Excitation) 증가 → Q 공급
  - SVC(Static Var Compensator) / STATCOM 운영
  - 부하차단 또는 발전기 탈락 방지

---

### 3.4 주파수 및 시간 척도 기준 (Frequency Standards)

#### 3.4.1 주파수 기준 — 산업통상자원부고시 제2023-65호 제4조

**한국 계통주파수 정규화 기준:**

| 운영 상태 | 기준 주파수 | 범위 | 회복시간 |
|-----------|-----------|------|---------|
| 평상시 | 60 Hz | ±0.2 Hz (59.8~60.2Hz) | - |
| 최대발전기 고장 | 최저 59.7 Hz 이상 | - | 5분 내 59.8Hz 이상 |
| 고장파급방지장치(UFR) 동작 시 | 최저 59.5 Hz | - | 3분 내 59.8Hz, 10분 내 60Hz |

- **주파수 침하(Frequency Dip)**
  - 발전기 대규모 탈락 시 순간적으로 주파수 저하
  - 조속기(Governor) + 1차 예비력이 자동으로 복구
  - 시간: 초(seconds) 단위

- **저주파수계전기 (UnderFrequency Relay; UFR)** — KPX/산업통상자원부고시
  - 주파수가 59.X Hz까지 저하되면 부하를 단계적으로 차단
  - 목적: 주파수 붕괴(Frequency Collapse) 방지 → 광역정전 방지
  - 산업통상자원부고시 제20조: UFR 계전기 기반 부하차단계획

#### 3.4.2 시간 척도 분류 (Timescale)

전력계통의 동적 현상은 반응 속도에 따라 분류:

| 시간 척도 | 범위 | 현상 | 제어 기구 |
|----------|------|------|---------|
| **초고속 (Transient)** | 밀리초~초 | 발전기 단자전압 변화, 조속기 1차 응답 | AVR(자동전압조정기), 조속기 |
| **속동(Sub-transient)** | 수십ms | 발전기 내부 과도 | 발전기 내부 특성 |
| **비상응성(Fast)** | 1~10초 | 주파수 회복, 1차 예비력 동작 | 조속기 1차, ESS |
| **중간 (Intermediate)** | 10초~분 | 2차 예비력 동작, AGC 시작 | AGC, 수동 제어 |
| **장기(Long-term)** | 분~시간 | 3차 예비력 동원, 발전소 기동 | 급전 지시, 발전기 기동 |

#### 3.4.3 주파수 운전 기준 — 산업통상자원부고시 제22조

- **연속 운전 범위**: 60 ± 0.5 Hz
- **허용 최소 범위**: 57 ~ 63 Hz (최소 1초 이상)
- **발전기 운영**: 이 범위 내에서만 안전하게 운전

#### 3.4.4 일차 예비력 (Primary Reserve; 조속기 예비력) — 산업통상자원부고시 제8조, 제26조

| 항목 | 기준 |
|------|------|
| 응답 시간 | 10초 이내 |
| 지속 시간 | 30분 이상 유지 |
| 조속기 속도조정률(드룹 설정) | 수력/내연: 3~5%, 가스터빈: 4~6%, 기력/석탄: 4~6%, 석탄가스화복합: 5% 이내, ESS: 3% 이내 |
| 법적 근거 | 산업통상자원부고시 제26조 |

- **작동 원리**
  - 주파수 저하 감지 → 터빈 입구 밸브 자동 개방 → 발전기 출력 증가
  - 자동 작동 (운영자 개입 없음)
  - 계통주파수가 60Hz로 복구되면 자동으로 정상 출력으로 복귀

---

### 3.5 안정도 및 상정고장 기준 (Stability & Contingency)

#### 3.5.1 안정도 정의 — KPX 용어

- **안정도 (Stability)**
  - 계통이 외란(고장, 부하 변화, 발전기 탈락)에 대응하여 동기 운전을 유지하는 능력

- **과도안정도 (Transient Stability)** — KPX 정의
  - 대규모 외란(송전선 고장 등) 후 동기성 유지 여부
  - 시간 스케일: 1~10초
  - 평가 기준: 시간 영역 시뮬레이션 (예: pandapower + pandapower-dynamics)
  - 발전기 로터 각도(δ) 발산 여부 확인

- **정상상태안정도 (Steady-State Stability)**
  - 소규모 외란에서 시간 경과에 따라 안정 상태로 복구
  - 시간 스케일: 초~분
  - 선형 시스템 이론 기반 평가

- **전압안정도 (Voltage Stability)** — 3.3.3 참조
- **주파수안정도 (Frequency Stability)** — 3.4 참조

#### 3.5.2 상정고장 (Contingency Event; 상정사고)

**정의 — 산업통상자원부고시 제2023-65호 제2조:**

계통이 예상할 수 있는 정상적인 운영 중 발생할 수 있는 단일 또는 복합 고장

**분류:**

| 고장 유형 | 정의 | 예시 |
|-----------|------|------|
| **단일고장** | 단 1개 설비 탈락 | 송전선 1회선 탈락, 변압기 1뱅크 탈락, 발전기 1기 탈락 |
| **이중고장** | 2개 설비 동시/연속 탈락 | 병행회선 가공송전선로 동시 탈락, 차단기 차단실패(고장선+CB) |
| **다중고장** | 3개 이상 설비 탈락 | 동일철탑의 다회선 동시 탈락, 동일 발전소 전체 탈락 |

- **비상상황 (Emergency; 비상상황)** — 산업통상자원부고시 제2조
  - 다중고장, 예비력 부족, 폭풍/지진, 사회혼란 등
  - 운영 기준 완화 가능 (긴급 모드)

#### 3.5.3 N-1 기준 — 산업통상자원부고시 제10조

**345kV 계통:**
- 단일고장 시: 공급지장 없어야 함
- 이중고장 시: 다음 중 1개 이상 없어야 함
  - 발전기 탈조(Loss of Synchronism)
  - 대규모 공급지장(Cascading Outage) 발생
  - 고장 파급 확대
  - 전압 불안정

**154kV 계통:**
- 단일고장 시: 공급지장 없어야 함
- 이중고장 시: 대규모 공급지장 방지

**66kV 이하:**
- 단일고장 시: 공급지장 없어야 함

#### 3.5.4 고장 제거 시간 (Fault Clearing Time) — 산업통상자원부고시 제12조

**3상 단락고장(3-Phase Fault) 기준:**

| 계통 레벨 | 고장 제거 시간 | 비고 |
|-----------|--------------|------|
| 345kV | 4 사이클 (66.7ms @ 60Hz) | 차단기 동작 + 신호 전송 포함 |
| 154kV | 5 사이클 (83.3ms @ 60Hz) | |
| 66kV | 미규정 | (지방 배전 수준) |

- **사이클(Cycle)** = 1 / 주파수
  - 60Hz 기준: 1 사이클 = 16.67ms

- **의미**
  - 송전선 고장 검출 후 4~5 사이클 내에 차단기가 개방되어야 함
  - 이 시간 내에 발전기가 안정성 보장

---

### 3.6 예비력 및 운영 여유 (Reserve Margin)

#### 3.6.1 예비력 체계 — 산업통상자원부고시 제2023-65호 제2조, 제8조

**정의 — 산업통상자원부고시 제2조:**

예비력 = 공급예비력(Supply Capacity Reserve) + 운영예비력(Operating Reserve)

#### 3.6.2 공급예비력 (Supply Capacity Reserve)

- **정의**: 계통의 순시 공급능력과 최대부하 간 차이
- **평가**: 연간 수급 계획 기반 (수급계획처 담당)
- **목표**: 여름철 피크 로드 대비 15~20% 이상
- **법적근거**: 전력수급기본계획 (5년 단위)

#### 3.6.3 운영예비력 (Operating Reserve) — 산업통상자원부고시 제8조, 제24조

**분류 및 기준:**

| 예비력 종류 | 응답 시간 | 지속 시간 | 용도 |
|------------|----------|---------|------|
| **주파수제어예비력** (AGC 예비력) | 5분 이내 | 30분 이상 | 주파수 편차 자동 제어 |
| **초속응성예비력** | 1초 이내 | 5분 이상 | 발전기 탈락 직후 주파수 회복 |
| **1차예비력** (Primary Reserve) | 10초 이내 | 30분 이상 | 조속기 자동 응답 |
| **2차예비력** (Secondary Reserve) | 10분 이내 | 30분 이상 | AGC 기반 조정 |
| **3차예비력** (Tertiary Reserve) | 30분 이내 | 제한 없음 | 발전기 온라인 기동 |

- **주파수제어예비력 (AGC 예비력)**
  - 중앙급전발전기(150MW 이상) 대상
  - 산업통상자원부고시 제24조: AGC 기준
  - 비중앙급전, 원자력, 수력 등은 제외 대상 다양

- **초속응성예비력**
  - 신규 기준 (신청에너지 기술 반영)
  - ESS(에너지저장장치), 동기모터 등
  - 제주, 강원 풍력 계통 안정화 용도

#### 3.6.4 중앙급전 vs 비중앙급전 — 산업통상자원부고시 제2조

- **중앙급전발전기 (Central-Dispatch Generator)**
  - 설비용량 ≥ 150 MW
  - KPX 급전지시(Dispatch Order) 대상
  - AGC, 예비력 편성 의무
  - 예: 석탄, 원자력, LNG 발전소 중 대규모

- **비중앙급전발전기 (Non-Dispatch Generator)**
  - 설비용량 < 150 MW
  - 독립적 운영, 급전 지시 미수령
  - 신재생, 자가발전, 중소 수력 등

- **신재생발전기** — 산업통상자원부고시 제2조
  - 수력 제외 신재생에너지 기반 발전기
  - 풍력, 태양광, 바이오, 지열 등
  - 변동성 큰 자원 (수력은 조절 가능)

---

## 4. 4계층 지식 활용 구조 (Knowledge Layers)

AI 에이전트가 실시간 운영 상황에서 필요한 지식을 효율적으로 활용하기 위해, 다음 4계층으로 구성:

### 4.1 Layer 0: 기본 정의 및 법적 기준 (Normative Knowledge)

**내용:**
- 산업통상자원부고시 제2023-65호의 모든 정량 기준
  - 전압 조정목표/유지범위 (345kV ±5% 등)
  - 주파수 기준 (60 ±0.2Hz, 59.7Hz 최저 등)
  - 상정고장 정의 (단일/이중/다중)
  - 고장 제거 시간 (345kV 4사이클 등)
  - 조속기 드룹 설정 (수력 3~5% 등)
  - PSS, AGC, ESS 기준 (산업통상자원부고시 제28, 24, 29조)

**저장소:**
- `docs/domain/voltage_limits.json`
  - 각 계통 레벨별 조정목표, 유지범위, pu 환산값
  - 정규화 계수 (base_kv)
  - 알람 시 임계값 참조

- `docs/domain/frequency_limits.json`
  - 정상시 ±0.2Hz
  - 긴급 시 최저값
  - 회복 시간

- `docs/domain/operating_standards.json`
  - 조속기 설정, PSS 기준, AGC 요구사항
  - N-1 조건
  - 고장 제거 시간

**사용자:**
- Layer 2 AI 에이전트의 모든 정규화 기준
- EMS 스텁의 제약 조건 검증
- 알람 생성 임계값

---

### 4.2 Layer 1: 용어사전 및 매핑 (Terminology & Reference)

**내용:**
- KPX 전력거래용어 해설집 (400+ 항목)
  - 계통 용어: 모선, 선로, 변전소, 차단기, 변압기 등
  - 운영 용어: 급전, AGC, 예비력, 보호협조 등
  - 거래 용어: SMP, 입찰, 결제 등

- KEPCO 전력관련 용어사전 (4,372 항목)
  - 기술 용어: 계전기, 유도전압조정기, FACTS 등
  - 설비 명칭: 변전소 종류, 차단기 종류 등
  - 부품명: CT, PT, 리액터 등

**저장소:**
- `docs/domain/glossary.json`
  - 구조: `{"term_ko": "모선", "term_en": "Bus", "term_hanja": "母線", "definition": "...", "source": "KPX 또는 KEPCO", "domain": "계통기술처", "examples": [...]}`
  - 색인: 한글명, 영문명, 약자 모두에서 검색 가능

- `docs/domain/equipment_mapping.csv`
  - bus_id ↔ 변전소명 매핑
  - 설비명 → pandapower 객체 타입 매핑
  - 예: "서울-345" → bus_id=1001, "한전-154" → bus_id=1002

**사용자:**
- 운영자 쿼리 "모선 전압은?" → "모선(Bus)"의 정의와 예 제공
- 장치명 "FACTS" 해석
- NL2App 에이전트: 운영자 입력 → 정규화된 용어 매핑

---

### 4.3 Layer 2: 실시간 계통 상태 데이터 (Operational Data)

**내용:**
- pandapower 네트워크 모델의 현재 스냅샷
  - Bus: vm_pu (전압 pu), va_degree (각도), 부하/발전기 연결 상태
  - Line: loading_pct (부하율), P/Q 조류
  - Transformer: 탭 위치, 부하율
  - Generator: P_mw, Q_mvar, 온라인/오프라인
  - Load: P_mw, Q_mvar

- Redis ops: 네임스페이스
  - Key: `ops:snapshot_ts`, 분석 기준 시각
  - Value: ISO 8601 타임스탐프

- Alarm history (시계열 DB)
  - 발생 시각, 설비명, 알람 유형, 임계값, 현재값

**수집 주기:**
- Bus/Line/Transformer: 1~5분 (SCADA 기반)
- Generator: 1분 (AGC 신호)
- Weather/Forecast: 30분 (외부 서비스)

**사용자:**
- Layer 2 HOTL/HITL 에이전트: 조회 기반 응답 생성
- RAG 파이프라인: 예시 사례 검색

---

### 4.4 Layer 3: 도메인 규칙 및 제약 (Domain Rules & Constraints)

**내용:**
- 한국 전력계통의 암묵적 규칙
  - 345kV 고장 제거 4사이클: 차단기 개방 시간 ≤ 66.7ms
  - N-1 조건: 모든 단일 고장 후 345kV ±10% 범위 내 전압 유지
  - 발전기 탈조 방지: 과도안정도(δ < 90도) 유지
  - 무효전력 균형: Q_generation ≈ Q_demand + Q_loss

- ops: 네임스페이스 쓰기 보호 규칙
  - AI는 `study:` 네임스페이스에만 쓰기 가능
  - `ops:` 읽기 전용
  - EMS stub이 `study:` → `ops:` 동기화 (검증 후)

- HITL/HOTL 분류 규칙
  - 조회(Query): `get_bus_voltage()` → HOTL 자동 응답
  - 조치(Action): `dispatch_generator()` → HITL 운영자 승인 필수

**저장소:**
- `src/layer2/agents/constraints.yaml`
  - 상정고장 템플릿
  - 운영 제약 (예: "발전기 기동시간 30분")

- `src/layer2/orchestrator/rules.py`
  - HITL/HOTL 분류 로직
  - Evidence chain 생성 함수

**사용자:**
- Layer 2 Orchestrator: HITL/HOTL 판단
- Constraint checker: 에이전트 응답 검증

---

## 5. RAG 파이프라인 설계

AI 에이전트가 운영자 질문에 대해 정확하고 신뢰성있는 답변을 생성하기 위해 RAG(Retrieval-Augmented Generation) 파이프라인을 구성.

### 5.1 RAG 아키텍처

```
운영자 질문 (자연어)
    ↓
[1] 벡터 임베딩 (BGE-M3)
    ↓
[2] Chroma 벡터DB 검색 (상위 K=3개 문서)
    ↓
[3] 검색된 문서 + 쿼리 맥락 + 현재 계통 상태
    ↓
[4] LLM (Qwen 또는 Claude) 프롬프트 입력
    ↓
[5] 응답 생성 + Evidence chain
    ↓
운영자 응답 (텍스트 + 도표)
```

### 5.2 벡터DB 구축 (Chroma)

**임베딩 대상 텍스트:**

| 출처 | 항목 | 크기 | 임베딩 모델 |
|------|------|------|----------|
| docs/domain/glossary.json | KPX/KEPCO 용어 정의 | 4,400+ | BGE-M3 (다국어) |
| docs/domain/voltage_limits.json | 전압 기준, 임계값 | 20개 | BGE-M3 |
| docs/design/domain_knowledge.md | 도메인 지식 본문 | 500개 청크 | BGE-M3 |
| 설계 문서 (v51_architecture.md 등) | 시스템 아키텍처, MCP 프로토콜 | 300개 청크 | BGE-M3 |
| 알람 코드 및 대응 가이드 | 알람 발생 조건, 운영자 조치 | 200개 | BGE-M3 |

**청킹 전략:**
- 용어사전: 각 항목을 1개 청크
- 기준값: 표 단위로 청킹
- 가이드 문서: 섹션 단위 (300~500 토큰)

**임베딩 모델:**
- BGE-M3 (BAAI/bge-m3)
  - 다국어(한글, 영문) 지원
  - 768차원 벡터
  - 로컬 호스팅 가능 (ollama/vLLM)

### 5.3 검색 쿼리 개선

**단계별 처리:**

1. **사용자 쿼리 정규화**
   - 입력: "345kv 버스 전압이 뭐지?"
   - 정규화: ["345kV 버스", "전압", "기준값"]

2. **벡터 검색**
   - 쿼리 임베딩: BGE-M3
   - 상위 K=3개 문서 검색
   - 예: ["345kV 전압 조정목표", "모선(Bus) 정의", "전압 유지범위"]

3. **문맥 보강**
   - 검색된 문서 + 현재 계통 상태 (ops:snapshot_ts)
   - 예: "345kV 버스 #1001의 현재 전압은 0.98pu (341kV)입니다."

4. **LLM 프롬프트 구성**
   ```
   # 도메인 지식
   - 345kV 조정목표: ±5% (328~362kV, 0.95~1.05pu)
   - 345kV 유지범위: ±10% (311~380kV, 0.90~1.10pu)

   # 현재 상태 (2026-03-25 14:30 KST)
   - 버스 #1001 전압: 0.98pu (341kV)
   - 상태: 정상 (조정목표 범위 내)

   # 운영자 질문
   "345kV 버스 전압이 뭐지?"

   # 응답 생성 지시
   - 질문에 직접 답변
   - 현재 값과 기준 비교
   - 근거 명시 (어느 문서, 어느 항목)
   ```

### 5.4 Evidence Chain 생성

모든 AI 응답에는 근거 출처를 명시:

```json
{
  "query": "345kV 버스 전압이 뭐지?",
  "response": "345kV 버스 #1001의 현재 전압은 0.98pu (341kV)로, 조정목표 0.95~1.05pu 범위 내에서 정상입니다.",
  "evidence_chain": [
    {
      "tool": "read_bus_state",
      "input": {"bus_id": 1001},
      "output": {"vm_pu": 0.98, "name": "345kV-BUS1"},
      "timestamp": "2026-03-25T14:30:00+09:00"
    },
    {
      "source": "산업통상자원부고시 제2023-65호 제5조",
      "reference": "voltage_limits.json",
      "value": {"voltage_class": "345kV", "target_range": "±5%", "target_pu": "0.95~1.05"}
    }
  ]
}
```

---

## 6. SLM 도메인 적응 전략 (Domain Adaptation for Small Language Models)

### 6.1 개요

Qwen2.5-7B 또는 유사 규모의 SLM(Small Language Model)을 한국 전력 도메인에 최적화하기 위한 전략.

### 6.2 파인튜닝 데이터셋 구축

**데이터 소스:**

| 카테고리 | 데이터 | 크기 | 용도 |
|---------|--------|------|------|
| 도메인 용어 | glossary.json (KPX 400+ + KEPCO 4,372) | ~1,000개 pair | 용어 이해 |
| 기준값 설명 | voltage_limits.json, frequency_limits.json | ~100개 pair | 기준값 적용 |
| Q&A 쌍 | 운영자 FAQ 수집 | ~500개 pair | 실제 운영 질문 대응 |
| 케이스 스터디 | 실제 운영 사례 (익명화) | ~200개 pair | 문제 진단 |
| 기술 규칙 | 산업통상자원부고시 조항별 | ~100개 pair | 법적 기준 준수 |

**파인튜닝 포맷 (LoRA):**

```json
{
  "instruction": "345kV 전압 조정목표가 무엇인가?",
  "input": "",
  "output": "345kV 조정목표는 ±5%, 즉 328kV~362kV (0.95~1.05pu)입니다. 산업통상자원부고시 제2023-65호 제5조에 따릅니다."
}
```

### 6.3 프롬프트 엔지니어링

**시스템 프롬프트:**

```
당신은 한국 전력계통 EMS(전력관리시스템) 조작 보조 AI 에이전트입니다.

[역할]
- 운영자의 자연어 질문을 이해하고 정확한 기술 답변 제공
- 산업통상자원부고시 제2023-65호의 정규화 기준 적용
- KPX/KEPCO 공식 용어 사용
- 모든 응답에 근거(Evidence) 명시

[핵심 규칙]
1. 전압 단위: pu (per unit). 345kV 기준: 0.95~1.05pu (조정목표)
2. 주파수: 60Hz ±0.2Hz (정상), 최저 59.7Hz (대규모 고장시)
3. N-1 원칙: 단일 설비 탈락해도 계통 안정 유지
4. 모든 수치는 pandapower 솔버 결과만 사용. 추정/추측 금지
5. AI 의견: 운영자 승인(HITL) 필요. 조회(HOTL) 자동 응답 가능

[금지 사항]
- LLM이 수치를 생성하면 안됨 (팩트 기반만)
- ops: 네임스페이스 쓰기
- 의료/금융 조언
- 운영자 의사결정 강제

[대응 방식]
- 용어 설명 필요: glossary.json 참조
- 기준값 필요: voltage_limits.json, frequency_limits.json 참조
- 계통 상태 필요: Redis ops: 네임스페이스 조회
- 운영 조치 필요: HITL 프로세스 호출
```

### 6.4 In-context Learning (ICL) 활용

**Few-shot 예제 추가:**

```
# 예제 1: 용어 설명
Q: "모선이 뭐지?"
A: 모선(Bus)는 발전기, 부하, 변압기, 송전선로가 연결되는 노드입니다.
[출처: KPX 전력거래용어 해설집]
[예시: 345kV-BUS1, 154kV-BUS2]

# 예제 2: 기준값 비교
Q: "버스 전압이 0.92pu인데 괜찮아?"
A: 0.92pu는 345kV 유지범위(0.90~1.10pu, ±10%) 내이나, 조정목표(0.95~1.05pu, ±5%) 밖입니다.
권장: 변압기 탭 조정으로 0.95~1.05pu로 복구.
[출처: 산업통상자원부고시 제5조]

# 예제 3: N-1 검토
Q: "345kV 선로 L1이 고장나면?"
A: N-1 기준에 따라 L1 탈락 후에도:
- 나머지 송전선로 부하율 < 100% (과부하 없음)
- 모든 버스 전압 345kV ±10% 내 (311~380kV)
- 발전기 동기성 유지 (과도안정도)
이들을 만족해야 안전합니다.
[근거: 산업통상자원부고시 제10조]
```

### 6.5 폐쇄형 도메인 구축

**제약:**
- SLM은 web search 금지
- Chroma RAG로만 외부 정보 수집
- 검색된 문서 + 현재 계통 상태만 활용

**이점:**
- 환각(Hallucination) 감소
- 일관성 있는 기준값 적용
- 감시 가능한 응답 생성

---

## 7. glossary.json 구축 계획

### 7.1 데이터 구조

**JSON 스키마:**

```json
{
  "terms": [
    {
      "id": "term_0001",
      "term_ko": "모선",
      "term_en": "Bus",
      "term_hanja": "母線",
      "pronunciation": "모선",
      "abbreviations": ["BUS", "B"],
      "definition": "발전기, 부하, 변압기, 송전선로가 연결되는 노드",
      "detailed_explanation": "전력계통에서 전압과 전류를 공급받고 분배하는 점. 여러 설비가 병렬로 연결됨.",
      "source": "KPX 전력거래용어 해설집",
      "domain": "계통기술처",
      "related_terms": ["모선분리", "슬랙모선"],
      "examples": [
        {
          "context": "345kV 모선",
          "explanation": "345kV 계통 레벨의 모선"
        },
        {
          "context": "서울 345kV-BUS1",
          "explanation": "서울 변전소의 345kV 모선 #1"
        }
      ],
      "pandapower_mapping": "pp.bus",
      "units": "없음",
      "normalization_key": "bus_id"
    }
  ]
}
```

### 7.2 수집 전략

**Phase 1: KPX 용어 (400+개)**

계통기술처:
- 계통감시, 계통계획, 계통모의, 계통병입/병해, 계통보호, 계통분리
- 계통설비용량, 계통안정화장치(PSS), 계통연계, 계통운영(SO)
- 계통운영보조서비스(Ancillary Services), 계통운영시스템(EMS)
- 계통전압, 계통정수, 계통주파수특성정수, 계통주파수(System Frequency)
- 계통해석, 계통현상분석장치(PQVF), 계통혼잡, 고장계산(Fault Study)
- 고장분석, 고장용량, 고장파급방지시스템, 과도안정도(Transient Stability)
- 과부하보호, 과전압계전기, 단결선도(SLD), 리액턴스(Reactance)
- 모선(Bus), 모선분리, 변성기, 변압기 탭, 병렬리액터, 보호장치
- 보호협조, 복합고장, 비상발전기, 상정고장(Contingency Event)
- 상정고장예비력, 상정사고계획(Contingency Plan), 상호임피던스
- 선로정수(Line Constant), 안정도(Stability), 역률, 유연송전시스템(FACTS)
- 유효전력(Active Power), 무효전력(Reactive Power), 임피던스(Impedance)
- 저전압계전기(UnderVoltage Relay), 저주파수, 전력계통안전도(PSSA)
- 전력조류(Power Flow), 전압(Voltage), 전압강하(Voltage Drop)
- 전압불평형, 전압붕괴(Voltage Collapse), 전압변동률(Voltage Regulation)
- 전압안정도(Voltage Stability), VCAS, 슬랙모선/스윙모선, 단독계통
- 단락용량, AGC, CT/PT, DCS, EMS, FCAS, NCAS, PQVF, PSS/E
- PSSA, RTU, S.C.C, S.O.E, S/S, SCADA, Set-Point, SMP, SVC, UFR

급전처:
- 가동율(Availability Factor), 가용발전력, 급전계획(Dispatching Schedule)
- 급전대기, 급전명령, 급전지시, 기동대기(Start Stand-by)
- 기동시간(Starting Time), 기동절차, 내연발전(Internal Combustion)
- 발전기 가용도(Availability), 발전기 정격용량, 순동예비력(Spinning Reserve)
- 순시발전력, 자동급전시스템, AGC 운전범위, Circuit Breaker
- EMS, SCADA, Set-Point

**Phase 2: KEPCO 용어 (4,372개)**

자동 추출 후 분류:
- 전력계통 용어 (500+)
- 발전 설비 용어 (200+)
- 변전소/선로 용어 (300+)
- 계전기/보호 용어 (200+)
- 제어/감시 용어 (200+)
- 신재생/DER 용어 (100+)
- 기타 기술용어 (1,500+)

### 7.3 검색 최적화

**다중 인덱스:**

```python
# glossary.json 로드
glossary = load_glossary()

# 검색 함수
def search_term(query, language="ko"):
    """
    query: 사용자 입력 (한글/영문)
    language: "ko" (한글), "en" (영문)

    returns: [term_id, term_ko, definition, source, ...]
    """
    results = []

    # 1. 정확 매칭 (term_ko, term_en, abbreviations)
    for term in glossary["terms"]:
        if (query == term.get("term_ko") or
            query == term.get("term_en") or
            query in term.get("abbreviations", [])):
            results.append(term)

    # 2. 부분 매칭 (definition 포함)
    for term in glossary["terms"]:
        if query in term.get("definition", ""):
            results.append(term)

    # 3. 벡터 유사도 (Chroma RAG)
    if not results:
        rag_results = chroma_search(query, k=3)
        results.extend(rag_results)

    return results
```

---

## 8. voltage_limits.json 구축 계획

### 8.1 데이터 구조

**JSON 스키마:**

```json
{
  "voltage_standards": [
    {
      "id": "vol_345kv",
      "voltage_class": "345kV",
      "base_kv": 345.0,
      "phase_count": 3,
      "frequency_hz": 60.0,
      "standards": {
        "target_range": {
          "name": "조정목표",
          "min_percent": 95.0,
          "max_percent": 105.0,
          "min_pu": 0.95,
          "max_pu": 1.05,
          "min_kv": 328.0,
          "max_kv": 362.0,
          "reference": "산업통상자원부고시 제2023-65호 제5조"
        },
        "operating_range": {
          "name": "유지범위",
          "min_percent": 90.0,
          "max_percent": 110.0,
          "min_pu": 0.90,
          "max_pu": 1.10,
          "min_kv": 311.0,
          "max_kv": 380.0,
          "reference": "산업통상자원부고시 제2023-65호 제6조"
        },
        "emergency_range": {
          "name": "비상운영범위",
          "min_percent": 85.0,
          "max_percent": 115.0,
          "min_pu": 0.85,
          "max_pu": 1.15,
          "min_kv": 293.0,
          "max_kv": 397.0,
          "note": "비상상황에서만 허용"
        }
      },
      "alarm_thresholds": {
        "warning_high": {"pu": 1.08, "kv": 373.0},
        "warning_low": {"pu": 0.92, "kv": 317.0},
        "critical_high": {"pu": 1.12, "kv": 386.0},
        "critical_low": {"pu": 0.88, "kv": 304.0}
      },
      "control_actions": {
        "voltage_high": [
          "변압기 탭 저하(Tap Down)",
          "SVC 무효전력 감소(흡수)",
          "발전기 여자 약화(Field Weakening)",
          "부하 차단(Load Shedding)"
        ],
        "voltage_low": [
          "변압기 탭 상승(Tap Up)",
          "SVC 무효전력 증가(공급)",
          "발전기 여자 강화(Field Forcing)",
          "부하 증가 또는 발전기 기동"
        ]
      }
    },
    {
      "id": "vol_154kv",
      "voltage_class": "154kV",
      "base_kv": 154.0,
      "standards": {
        "target_range": {
          "min_percent": 95.0,
          "max_percent": 105.0,
          "min_pu": 0.95,
          "max_pu": 1.05,
          "min_kv": 146.3,
          "max_kv": 161.7,
          "reference": "산업통상자원부고시 제2023-65호 제5조"
        },
        "operating_range": {
          "min_percent": 90.0,
          "max_percent": 110.0,
          "min_pu": 0.90,
          "max_pu": 1.10,
          "min_kv": 138.6,
          "max_kv": 169.4,
          "reference": "산업통상자원부고시 제2023-65호 제6조"
        }
      }
    },
    {
      "id": "vol_66kv",
      "voltage_class": "66kV",
      "base_kv": 66.0,
      "standards": {
        "target_range": {
          "min_percent": 97.0,
          "max_percent": 103.0,
          "min_pu": 0.97,
          "max_pu": 1.03,
          "min_kv": 64.02,
          "max_kv": 67.98,
          "reference": "산업통상자원부고시 제2023-65호 제5조"
        },
        "operating_range": {
          "min_percent": 90.0,
          "max_percent": 110.0,
          "min_pu": 0.90,
          "max_pu": 1.10,
          "min_kv": 59.4,
          "max_kv": 72.6,
          "reference": "산업통상자원부고시 제2023-65호 제6조"
        }
      }
    },
    {
      "id": "vol_22_9kv",
      "voltage_class": "22.9kV",
      "base_kv": 22.9,
      "standards": {
        "target_range": {
          "min_percent": 99.0,
          "max_percent": 101.0,
          "min_pu": 0.99,
          "max_pu": 1.01,
          "min_kv": 22.671,
          "max_kv": 23.129,
          "reference": "산업통상자원부고시 제2023-65호 제5조"
        }
      }
    }
  ]
}
```

### 8.2 활용

**전압 정규화 함수:**

```python
def normalize_voltage(vm_kv, voltage_class):
    """
    실제 전압 → pu로 변환
    input: vm_kv (kV), voltage_class ("345kV" 등)
    output: vm_pu (pu), vm_percent (%)
    """
    standards = voltage_limits["voltage_standards"]
    std = next(s for s in standards if s["voltage_class"] == voltage_class)
    base_kv = std["base_kv"]

    vm_pu = vm_kv / base_kv
    vm_percent = vm_pu * 100

    return {"vm_pu": vm_pu, "vm_percent": vm_percent}

def check_voltage_alarm(vm_pu, voltage_class):
    """
    전압 알람 판정
    """
    std = next(s for s in voltage_standards if s["voltage_class"] == voltage_class)
    thresholds = std["alarm_thresholds"]

    if vm_pu > thresholds["critical_high"]["pu"]:
        return {"level": "CRITICAL", "message": "고전압 위험", "action": "조기조치"}
    elif vm_pu > thresholds["warning_high"]["pu"]:
        return {"level": "WARNING", "message": "고전압 경고"}
    elif vm_pu < thresholds["critical_low"]["pu"]:
        return {"level": "CRITICAL", "message": "저전압 위험"}
    elif vm_pu < thresholds["warning_low"]["pu"]:
        return {"level": "WARNING", "message": "저전압 경고"}
    else:
        return {"level": "NORMAL", "message": "정상"}
```

---

## 9. 주파수 기준 (frequency_limits.json)

### 9.1 데이터 구조

```json
{
  "frequency_standards": {
    "base_frequency": 60.0,
    "unit": "Hz",
    "standards": {
      "normal_operation": {
        "name": "정상운영범위",
        "min_hz": 59.8,
        "max_hz": 60.2,
        "tolerance_hz": 0.2,
        "reference": "산업통상자원부고시 제2023-65호 제4조"
      },
      "max_generator_outage": {
        "name": "최대발전기 고장 시",
        "min_hz": 59.7,
        "min_recovery_time_sec": 300,
        "recovery_target_hz": 59.8,
        "reference": "산업통상자원부고시 제2023-65호 제4조"
      },
      "ufr_activation": {
        "name": "고장파급방지장치(UFR) 동작 시",
        "min_hz": 59.5,
        "stage_1_recovery_time_sec": 180,
        "stage_1_recovery_hz": 59.8,
        "stage_2_recovery_time_sec": 600,
        "stage_2_recovery_hz": 60.0,
        "reference": "산업통상자원부고시 제2023-65호 제4조"
      },
      "generator_continuous_operation": {
        "name": "발전기 연속운전범위",
        "min_hz": 57.0,
        "max_hz": 63.0,
        "reference": "산업통상자원부고시 제2023-65호 제22조"
      },
      "generator_minimum_operation": {
        "name": "발전기 최소허용범위",
        "min_hz": 57.0,
        "max_hz": 63.0,
        "min_duration_sec": 1.0,
        "reference": "산업통상자원부고시 제2023-65호 제22조"
      }
    },
    "reserve_categories": [
      {
        "id": "fcr",
        "name_ko": "주파수제어예비력",
        "name_en": "Frequency Control Reserve (FCR)",
        "response_time_sec": 300,
        "min_duration_min": 30,
        "control_method": "AGC (Automatic Generation Control)",
        "target_generators": "중앙급전발전기 (≥150MW)",
        "reference": "산업통상자원부고시 제2023-65호 제24조"
      },
      {
        "id": "prr",
        "name_ko": "초속응성예비력",
        "name_en": "Primary Response Reserve (PRR)",
        "response_time_sec": 1,
        "min_duration_min": 5,
        "control_method": "ESS, Synchronous Motors",
        "target_equipment": "에너지저장장치, 동기모터",
        "reference": "산업통상자원부고시 제2023-65호 제8조"
      },
      {
        "id": "prm",
        "name_ko": "1차예비력",
        "name_en": "Primary Reserve (PRM)",
        "response_time_sec": 10,
        "min_duration_min": 30,
        "control_method": "Governor (조속기) 자동 응답",
        "droop_setting_percent": "3~5% (수력/내연), 4~6% (가스터빈/기력)",
        "reference": "산업통상자원부고시 제2023-65호 제26조"
      },
      {
        "id": "sec",
        "name_ko": "2차예비력",
        "name_en": "Secondary Reserve (SEC)",
        "response_time_sec": 600,
        "min_duration_min": 30,
        "control_method": "AGC (자동발전제어)",
        "reference": "산업통상자원부고시 제2023-65호 제8조"
      },
      {
        "id": "ter",
        "name_ko": "3차예비력",
        "name_en": "Tertiary Reserve (TER)",
        "response_time_sec": 1800,
        "min_duration_min": 0,
        "control_method": "발전기 온라인 기동",
        "reference": "산업통상자원부고시 제2023-65호 제8조"
      }
    ]
  }
}
```

---

## 10. 알람 코드 및 대응 가이드 (Alarm System)

### 10.1 알람 체계

**알람 3단계:**

| 레벨 | 색상 | 의미 | 운영자 조치 | 응답시간 |
|------|------|------|----------|---------|
| **NORMAL** | 녹색 | 정상 범위 내 | 없음 | - |
| **WARNING** | 황색 | 경고, 추이 감시 필요 | 모니터링 강화 | 실시간 |
| **CRITICAL** | 빨간색 | 위험, 즉시 조치 필요 | HITL 절차 | 분초 단위 |

### 10.2 대표적 알람 코드

**전압 관련:**

```json
{
  "alarms": [
    {
      "id": "ALM_VOLT_HIGH",
      "title": "고전압",
      "severity": "WARNING",
      "condition": "vm_pu > target_max (예: 345kV에서 1.05pu 초과)",
      "threshold": "1.05pu (조정목표 초과)",
      "cause": [
        "가벼운 부하 (수요 부족)",
        "발전기 여자 과잉",
        "변압기 탭 오프셋",
        "SVC 무효전력 과잉"
      ],
      "corrective_actions": [
        "변압기 탭 저하(Tap Down)",
        "발전기 여자 약화(Field Weakening)",
        "SVC 무효전력 감소(흡수)",
        "부하 차단 또는 발전기 탈락"
      ],
      "reference": "산업통상자원부고시 제2023-65호 제5조"
    },
    {
      "id": "ALM_VOLT_CRITICAL_HIGH",
      "title": "극고전압",
      "severity": "CRITICAL",
      "condition": "vm_pu > 1.10pu (유지범위 초과)",
      "threshold": "1.10pu",
      "cause": "변압기 탭 설정 오류 또는 제어 실패",
      "corrective_actions": [
        "긴급 탭 조정",
        "즉시 부하 차단",
        "발전기 탈락 명령"
      ],
      "reference": "산업통상자원부고시 제2023-65호 제6조"
    },
    {
      "id": "ALM_VOLT_CRITICAL_LOW",
      "title": "극저전압",
      "severity": "CRITICAL",
      "condition": "vm_pu < 0.90pu (유지범위 초과)",
      "cause": [
        "과부하(부하 > 발전용량)",
        "발전기 탈락",
        "무효전력 부족",
        "전압붕괴 임박"
      ],
      "corrective_actions": [
        "긴급 부하 차단",
        "발전기 또는 ESS 기동",
        "무효전력 보상장치(SVC/STATCOM) 가동",
        "거리에 따른 UFR 절단 고려"
      ],
      "reference": "산업통상자원부고시 제2023-65호, 제20조"
    }
  ]
}
```

**주파수 관련:**

```json
{
    {
      "id": "ALM_FREQ_LOW",
      "title": "저주파수",
      "severity": "WARNING",
      "condition": "freq_hz < 59.8Hz (정상범위 이하)",
      "threshold": "59.8Hz",
      "cause": [
        "대규모 부하 증가",
        "발전기 탈락",
        "조속기 응답 지연"
      ],
      "corrective_actions": [
        "발전기 출력 증가(AGC/수동)",
        "부하 감소(수요 억제 또는 차단)",
        "예비력 투입"
      ],
      "reference": "산업통상자원부고시 제2023-65호 제4조"
    },
    {
      "id": "ALM_FREQ_CRITICAL_LOW",
      "title": "극저주파수(UFR 단계)",
      "severity": "CRITICAL",
      "condition": "freq_hz < 59.5Hz (UFR 기동)",
      "threshold": "59.5Hz",
      "cause": "대규모 발전기 탈락, 광역정전 임박",
      "corrective_actions": [
        "자동 부하 차단 (UFR 계전기 동작)",
        "긴급 발전기 기동",
        "고장파급방지 절차 개시"
      ],
      "reference": "산업통상자원부고시 제2023-65호 제20조"
    }
}
```

**선로 과부하 관련:**

```json
{
      "id": "ALM_LINE_OVERLOAD",
      "title": "선로 과부하",
      "severity": "WARNING",
      "condition": "loading_pct > 100% (정격 초과)",
      "threshold": "100%",
      "cause": [
        "평행선 탈락으로 부하 집중",
        "부하 증가",
        "발전기 출력 제약"
      ],
      "corrective_actions": [
        "조류 재배분(설비 투입/탈락)",
        "부하 차단",
        "발전기 기동",
        "N-1 조건 재검토"
      ],
      "reference": "산업통상자원부고시 제2023-65호 제10조"
    }
}
```

### 10.3 알람 생성 로직

**알람 발생 절차:**

```python
def check_alarms(network_state, voltage_limits, frequency_limits):
    """
    현재 계통 상태 → 알람 생성
    """
    alarms = []

    # 1. 모든 버스 전압 확인
    for bus in network_state["buses"]:
        v_limits = get_voltage_limits(bus["voltage_class"])
        vm_pu = bus["vm_pu"]

        if vm_pu > v_limits["critical_high"]:
            alarms.append({
                "id": "ALM_VOLT_CRITICAL_HIGH",
                "bus_id": bus["bus_id"],
                "value": vm_pu,
                "threshold": v_limits["critical_high"],
                "severity": "CRITICAL"
            })
        elif vm_pu > v_limits["warning_high"]:
            alarms.append({
                "id": "ALM_VOLT_HIGH",
                "bus_id": bus["bus_id"],
                "value": vm_pu,
                "threshold": v_limits["warning_high"],
                "severity": "WARNING"
            })

    # 2. 주파수 확인
    freq_hz = network_state["frequency"]

    if freq_hz < frequency_limits["critical_low"]:
        alarms.append({
            "id": "ALM_FREQ_CRITICAL_LOW",
            "value": freq_hz,
            "threshold": frequency_limits["critical_low"],
            "severity": "CRITICAL"
        })
    elif freq_hz < frequency_limits["warning_low"]:
        alarms.append({
            "id": "ALM_FREQ_LOW",
            "value": freq_hz,
            "threshold": frequency_limits["warning_low"],
            "severity": "WARNING"
        })

    # 3. 선로 과부하 확인
    for line in network_state["lines"]:
        if line["loading_pct"] > 100:
            alarms.append({
                "id": "ALM_LINE_OVERLOAD",
                "line_id": line["line_id"],
                "value": line["loading_pct"],
                "threshold": 100.0,
                "severity": "WARNING"
            })

    return alarms
```

---

## 11. 최종 체크리스트

AI-EMS 프로토타입이 한국 전력 도메인을 올바르게 이해하는지 확인하기 위한 체크리스트:

- [ ] 모든 전압 기준이 산업통상자원부고시 제2023-65호를 따르는가?
  - [ ] 345kV ±5% (328~362kV)
  - [ ] 154kV 95~105% (146~162kV)
  - [ ] 66kV 97~103%
  - [ ] 22.9kV 99~101%

- [ ] 모든 주파수 기준이 정확한가?
  - [ ] 정상운영: 60±0.2Hz
  - [ ] 대규모 고장: 최저 59.7Hz, 5분 내 59.8Hz 회복
  - [ ] UFR 동작: 최저 59.5Hz, 3분 내 59.8Hz, 10분 내 60Hz

- [ ] 예비력 정의가 법정 기준과 일치하는가?
  - [ ] 1차: 10초 이내, 30분 이상
  - [ ] 2차: 10분 이내, 30분 이상
  - [ ] 3차: 30분 이내
  - [ ] 주파수제어: 5분 이내, 30분 이상
  - [ ] 초속응성: 1초 이내, 5분 이상

- [ ] 상정고장 정의가 명확한가?
  - [ ] 단일고장: 설비 1개 탈락
  - [ ] 이중고장: 설비 2개 동시/연속 탈락
  - [ ] N-1 기준: 345kV 단일고장 후 공급지장 없음

- [ ] 용어사전이 구축되었는가?
  - [ ] KPX 400+ 용어 수집 완료
  - [ ] KEPCO 4,372 용어 자동 추출 완료
  - [ ] glossary.json 파일 생성 및 색인 완료

- [ ] 모든 AI 응답에 Evidence chain이 포함되는가?
  - [ ] pandapower 솔버 결과 근거
  - [ ] 참고 문서 명시
  - [ ] snapshot_ts 포함

---

## 12. 참고 문헌

1. **한국전력거래소(KPX).** "전력거래용어 해설집." 2003년 12월.
   - 400+ 용어 정의, 공식 출처

2. **한국전력공사(KEPCO).** "전력관련 용어사전 정보." 2019년 8월 28일.
   - 4,372 항목 기술 용어, CSV 형식

3. **산업통상자원부.** "전력계통 신뢰도 및 전기품질 유지기준."
   - 산업통상자원부 고시 제2023-65호, 2023년 4월 25일.
   - 법정 정량 기준, 전기사업법 제16조 근거

4. **pandapower 공식 문서.** "pandapower — An Open Source Grid Modeling and Analysis Tool for Active Distribution Networks."
   - https://pandapower.readthedocs.io/

5. **IEC 60320 / IEEE 1159.** Voltage and Frequency Standards for Power Systems.

6. **IEEE Standard 738.** IEEE Standard for Calculating the Current-Temperature Relationship of Bare Overhead Conductors.

---

**작성자:** AI-EMS 설계팀
**최종 검토:** 2026-03-25
**버전 관리:** git commit `domain-knowledge-v51-korean`
