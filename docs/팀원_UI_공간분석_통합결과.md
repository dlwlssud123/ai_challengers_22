# 팀원 저장소 UI·공간분석 통합 결과

작성일: 2026-08-11  
참조 저장소: https://github.com/mike010010/estsoft_contest

## 통합 원칙

팀원 저장소를 통째로 덮어쓰지 않고, 현재 저장소의 기존 공개 함수와 테스트를 보존한 상태에서 공간분석과 UI 모듈을 별도 패키지로 이식했다.

## 가져온 부분

- `src/data/`: 실제 쉼터 CSV 자동 탐색·인코딩 처리·표준화·품질검사
- `src/analysis/`: 위험도, 접근성, 사각지대, 군집화, 최대커버리지 최적화, Before/After 시뮬레이션
- `src/ui/`: Folium 지도, 마커 클러스터, 접근권역·사각지대·추천 후보 레이어
- `src/pipeline.py`: 전체 공간분석 실행 흐름
- `src/config.py`, `src/schemas.py`: 설정과 내부 결과 스키마
- `data/raw/areas.geojson`: 수성구 23개 행정동의 SGIS 기반 분석 스냅샷
- 핵심 공간분석·지도·최적화 테스트와 데이터 검증 스크립트

## 기존 저장소에서 유지한 부분

- `src/sgis_client.py`: SGIS AccessToken, 실시간 행정동 경계 조회와 좌표 변환
- `src/alan_client.py`: Alan 프롬프트, 응답 검증과 안전한 Fallback 경계
- `src/integration.py`: 기존 provider·Mock 통합 함수 계약
- `src/accessibility.py`, `src/optimization.py`, `src/vulnerability.py`: 다른 팀 모델을 연결하기 위한 기존 어댑터
- 환경변수와 Streamlit Cloud Secrets 양쪽 지원
- 기본/다크 모드와 모바일 반응형 스타일
- 기존 자동 테스트

## 의도적으로 가져오지 않은 부분

- OpenAI Responses 기반 정책 브리핑: 프로젝트의 기존 Alan 연동 방향과 중복되어 제외
- 팀원 저장소의 중복 쉼터 CSV: 현재 `data` 폴더 원본을 직접 탐색하도록 변경
- 구형 SGIS 호출 코드로 기존 `src/sgis_client.py` 교체: 인증·캐시·오류처리가 이미 구현되어 있어 유지
- 팀원 저장소 전체 README와 발표 문서: 현재 저장소 상태에 맞게 README만 새로 작성

## 충돌 방지 구조

```text
기존 팀 함수 계약                 새 실제 공간분석
src/accessibility.py             src/analysis/accessibility.py
src/optimization.py              src/analysis/optimizer.py
src/vulnerability.py             src/analysis/risk.py
src/integration.py               src/pipeline.py
```

기존 모듈은 삭제하거나 이름을 바꾸지 않았다. 새 대시보드는 `src/pipeline.py`를 사용하고, 기존 테스트 또는 다른 팀 코드가 호출하는 함수는 그대로 유지한다.

## 현재 데이터 흐름

```text
data/*.csv 실제 쉼터 131개
        ↓ 자동 탐색·표준화
src/data/shelters.py
        ↓
src/pipeline.py
        ├─ 행정동 위험·접근성 점수
        ├─ 300/500/700m 접근권역
        ├─ 고위험 사각지대
        └─ 예산·최대 시설 수 기반 최적화
        ↓
app.py 지도·KPI·Before/After·정책 요약
```

향후 공공데이터 OpenAPI가 준비되면 API 응답을 `src/data/shelters.py`의 표준 컬럼으로 변환해 CSV보다 앞에 연결한다. CSV는 API 장애 시 Fallback으로 유지한다.

## 검증 결과

- 자동 테스트: 29개 통과 예정 기준(기존 14개 포함, 공간분석·UI·스모크 테스트 추가)
- 데이터 품질검사: 9개 통과
- 실제 데이터 파이프라인: 행정동 23개, 쉼터 131개
- Streamlit 헤드리스 렌더링과 도시처방 실행 버튼 검증

최종 숫자는 통합 완료 시점의 전체 테스트 실행 결과를 기준으로 갱신한다.
