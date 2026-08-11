# AI 폭염 도시처방

대구광역시 9개 구·군의 사회·건강 취약도와 기상청 실시간 폭염 위험, 공공 무더위쉼터 현황을 SGIS 행정동 지도에서 제공하는 Streamlit 정책지원 MVP입니다.

현재 버전은 팀원 저장소의 공간분석·지도 UI를 선별 통합하고, 기존 저장소의 SGIS 실시간 클라이언트, Alan 연동 경계, Streamlit Secrets, 기본/다크 모드와 반응형 스타일을 함께 유지합니다.

## 현재 동작하는 기능

- 대구 실제 행정동 150개 SGIS 경계
- 재난안전데이터공유플랫폼 API 기반 무더위쉼터 좌표·수용인원·운영정보(장애 시 캐시/로컬 CSV 대체)
- 9개 구·군 K-means 사회·건강 취약도와 기상청 실시간 위험 기반 정책 우선순위
- 기상청 관측기간 중 가장 더운 날을 사용한 극한폭염 시나리오
- 종합 정책 우선순위·사회건강 취약도·쉼터 부족도 히트맵 전환
- 지도 클릭 행정동 선택과 구·군 상세 지표·공공 쉼터 수 표시
- 예산·시설 수에 따른 구·군 시설 배분 대시보드
- 기본/다크 모드와 모바일 반응형 화면
- API·Solver 장애 시 명시적 Fallback

공간 거리와 면적은 EPSG:5179에서 계산하고 지도 표시는 EPSG:4326을 사용합니다.

## 실행

가장 간단한 실행 방법:

```powershell
.\run_app.ps1
```

기존 `.venv`가 삭제되거나 이동된 Python을 가리키면 스크립트가 `.venv-rebuilt`를 새로 만들어 사용합니다.

직접 실행:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

검증:

```powershell
python -m pytest -q
python scripts\validate_data.py
```

## 주요 구조

```text
app.py                    통합 Streamlit 정책 대시보드
src/config.py             환경변수·Streamlit Secrets·분석 설정
src/data/                 쉼터 정규화, 데이터 로더, 후보지 생성
src/analysis/             위험도·접근성·사각지대·군집·최적화·시뮬레이션
src/ui/                   Folium 지도와 KPI 컴포넌트
src/pipeline.py           실제 공간분석 실행 흐름
src/spatial_policy.py     공간분석 결과를 기존 Alan 정책 계약으로 변환
src/sgis_client.py        기존 SGIS 인증·실시간 경계 조회 클라이언트
src/alan_client.py        기존 Alan 프롬프트·응답 검증·Fallback 경계
src/integration.py        기존 Mock/provider 통합 계약(하위 호환)
data/raw/areas.geojson    수성구 SGIS 기반 행정동 분석 스냅샷
data/*.csv                팀이 제공한 실제 시설 원본과 API Fallback
```

기존 `src/accessibility.py`, `src/optimization.py`, `src/vulnerability.py` 계약은 삭제하지 않았습니다. 새 공간분석 구현은 `src/analysis/`에 분리되어 기존 팀 코드와 테스트를 깨지 않고 병행할 수 있습니다.

## 데이터 및 API 전환

현재 쉼터는 재난안전데이터공유플랫폼 `DSSP-IF-10942`를 우선 호출하고, 마지막 정상 캐시와 `data`/`data/raw`의 CSV를 순서대로 대체 소스로 사용합니다. 응답은 내부 표준 스키마로 정규화한 뒤 상세 공간분석과 구·군별 시설 집계에 함께 사용합니다.

권장 우선순위는 다음과 같습니다.

1. 공공데이터 API
2. 마지막 정상 캐시
3. 현재 CSV 스냅샷

API 키는 GitHub에 올리지 않고 로컬 `.env` 또는 Streamlit Cloud Secrets에 저장합니다. 상세 계약은 `docs/무더위쉼터_API_활용_및_팀협업_가이드.md`를 참고하세요.

## 아직 남은 한계

- 행정동 내 고령인구 균등분포 가정
- 실제 도로망이 아닌 직선거리 접근권역
- 신규 공간 후보는 토지·규제·현장 설치 가능성을 확인하지 않은 DEMO 후보
- 시설 이용률과 온열질환 감소의 인과효과 미검증
- Alan 공식 요청 명세가 없어 현재 정책 문장은 계산 결과 기반 템플릿 사용
- 기상청 대구 ASOS 143번 최신 기온·습도를 사용하며 장애 시 마지막 정상 캐시 또는 기존 기상 스냅샷 사용
