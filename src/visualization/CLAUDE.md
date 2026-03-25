# 시각화 — GIS 지도 + SLD + Streamlit

## 이 디렉토리의 역할
운영자 대시보드 + NL Navigation 목적지 + HITL 승인 UI.
MapLibre GL JS 기반 GIS 지도 + D3.js 변전소 SLD + Streamlit 프레임워크.

## v5.1 축소 범위 — Phase 3 구현
- **구현**: L1(전국 345kV) + L2(권역 345+154kV) + L4(변전소 SLD)
- **설계만 유지**: L3(광역/도시), L5(베이), 2.5D 틸트, 3D 몰입형

## 핵심 아키텍처
- **MapLibre GL JS**: GIS 지도 (벡터 타일, 다크 테마)
- **D3.js**: 변전소 SLD 렌더링 (SVG)
- **Streamlit**: 앱 프레임워크 + 3열 레이아웃
- **WebSocket**: Redis Pub/Sub → 브라우저 4초 갱신

## 시맨틱 줌 (v5.1 구현 범위)
| 레벨 | 줌 범위 | 표시 내용 | v5.1 구현 |
|------|---------|----------|-----------|
| L1 전국 | z5~7 | 345kV 간선 + 대규모 발전소 | ✓ Phase 3 |
| L2 권역 | z8~10 | 345+154kV + 모든 변전소 | ✓ Phase 3 |
| L3 광역 | z11~13 | 도시화 단선도 | △ 설계만 |
| L4 변전소 SLD | 클릭 | 모선·CB·변압기·선로 | ✓ Phase 3 |
| L5 베이 | 클릭 | CT/PT/계전기 | △ 설계만 |

## 디렉토리 구조
```
visualization/
├── CLAUDE.md            # 이 파일
├── map/                 # MapLibre GIS 관련
│   ├── semantic_zoom.py # 줌 레벨 기반 필터링
│   ├── layers.py        # 6개 맵 레이어
│   └── styles.py        # 다크 테마 스타일
├── sld/                 # D3.js SLD 관련
│   ├── renderer.py      # SLD SVG 렌더링
│   ├── symbols.py       # 전기 심볼 (모선, CB, 변압기)
│   └── data_binding.py  # 실시간 데이터 바인딩
└── streamlit_app/       # Streamlit 메인
    ├── app.py           # 3열 레이아웃
    ├── components/      # 위젯들
    └── hitl_popup.py    # HITL 승인 팝업
```

## 6개 맵 레이어 (z-index 순)
1. **base(0)**: 기본 지도 다크 타일
2. **grid_topo(1)**: 송전선로 + 변전소 아이콘
3. **realtime(2)**: SCADA 실시간 (전압 색상, 조류 방향)
4. **alarm(3)**: 활성 알람 마커
5. **weather(4)**: 기상 레이어 (Phase 4)
6. **study(5)**: Study 비교 오버레이 (향후)

## SCADA 실시간 오버레이
- 전압 색상: 정상(#39ff14) → 경계(#ffb347) → 위반(#ff3b3b)
- 조류 방향: 애니메이션 화살표 (Deck.gl Arc)
- 알람 마커: 점멸 + 심각도 색상

## HITL 승인 팝업 (다크 테마)
- 배경: #050a12, 테두리: 앰버 글로우
- 최대 3건 동시 표시
- 버튼: 승인(#39ff14) / 거부(#ff3b3b)
- Evidence chain 영역 + 카운트다운

## NL→지도 MCP Tool (Phase 3 구현)
- map_fly_to: 좌표/설비 이동
- map_set_filter: 전압/설비 필터링
- map_highlight: 특정 설비 강조
- map_fit_bounds: 영역 맞춤

## Screen Registry
navigate_to(screen_id)로 화면 전환. NL 발화 키워드 매핑:
- main_dashboard: 홈, 메인
- sld_154kv: 154kV, 단선도
- se_result: SE, 상태추정
- alarm_list: 알람, 경보
- ai_insight: 인사이트, 예측

## 폐쇄망 고려사항
- PMTiles 한반도 사전 캐시 (~2-5GB)
- 한글 글리프 로컬 생성
- CDN 의존 없는 번들링 (vendor.js)
- 색상 테마: 다크 (#050a12 배경)

## 필수 규칙
1. AI 분석 패널 읽기 전용
2. Screen Registry에 screen_id 등록 필수
3. 4초 주기 WebSocket 갱신
4. 다크 테마 일관성 유지
5. 폐쇄망: 모든 자원 로컬 번들링
