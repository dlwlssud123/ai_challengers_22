# 대구 폭염 취약시설 분석 · 개발 인계 최종본

이 패키지는 첨부된 `dbscan_shap_analysis.py`의 검증 로직을 유지하면서, 해커톤 서비스에서 사용할 수 있도록 **오프라인 배치 파이프라인**과 **FastAPI 스냅샷 분석 API**를 분리한 최종 인계본이다.

## 포함 범위

- `src/analysis/dbscan_shap_batch.py`: 원본 4개 자료 결합 → DBSCAN 파라미터 탐색 → Tree 대리모델 → SHAP → CSV/PNG/정책 리포트 생성
- `src/analysis/cluster_service.py`: 프론트가 보낸 행정동 전체 Feature 스냅샷을 분석하는 재사용 모듈
- `src/api/main.py`: `/health`, `/api/v1/clusters/features`, `/api/v1/clusters`
- `frontend/app.py`: API 계약을 검증할 수 있는 Streamlit 연동 화면
- `docs/`: API·데이터 계약 및 QA 체크리스트

## 빠른 실행

```bash
cp .env.example .env
docker compose up --build
```

- API 문서: `http://localhost:8000/docs`
- 테스트 프론트: `http://localhost:8501`

로컬 실행 시에는 다음을 사용한다.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn src.api.main:app --reload
```

## 오프라인 배치 실행

필수 원자료를 `data/raw/`에 둔 뒤 실행한다.

```bash
python src/analysis/dbscan_shap_batch.py \
  --input-dir data/raw --output-dir data/outputs
```

세부 파일명·필드 계약은 [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md)를 따른다. 실제 대구 원자료와 행정동 경계 GeoJSON은 포함하지 않았다.

## 서비스 연동 결정

1. 격자 접근성 모듈이 `access_deficit`을 계산한다.
2. 회귀/시나리오 모듈이 `future_heat_illness_risk`, `response_facility_shortage`를 계산한다.
3. 프론트 또는 BFF가 모든 행정동의 여섯 Feature를 `/api/v1/clusters`로 보낸다.
4. 응답의 `assignments`를 `dong_code` 기준으로 GeoJSON과 결합해 지도와 추천 카드를 그린다.

DBSCAN은 개별 행정동의 신규 값을 `predict`하는 알고리즘이 아니다. 따라서 시설 후보를 바꾼 후에는 **대구 전체 행정동 스냅샷을 재분석**해야 하며, Before/After는 C번호가 아닌 `dong_code`의 위험도·우선순위·추천 변화로 비교한다.

## 검수에서 반영한 사항

| 항목 | 첨부본 상태 | 최종본 처리 |
|---|---|---|
| 분석 실행 경로 | 업로드 폴더 위치에 의존 | `data/raw`, `data/outputs`와 환경변수로 명시 |
| 웹 연동 | CLI 배치 전용 | JSON API와 Pydantic 계약 추가 |
| DBSCAN 해석 | 새 관측치 예측 경계 불명확 | 전체 스냅샷 재군집화 원칙을 코드·문서에 고정 |
| FE 전달물 | CSV/PNG 중심 | KPI·군집 카드·지도 join에 필요한 JSON 응답 정의 |
| 운영 보안 | API 키 호출이 분석 스크립트 안에 있음 | ALAN은 오프라인 배치 전용으로 격리, API는 키/경로를 받지 않음 |
| 품질 경고 | 산출물에 존재 | API `warnings`와 프론트 화면에도 노출 |

## 주의 사항

- SHAP은 DBSCAN 군집을 흉내 낸 Tree 대리모델의 설명값이지 인과적 시설 효과가 아니다.
- Macro-F1 또는 Accuracy 경고가 나오면 해당 결과를 정책 확정 근거로 쓰지 말고 원자료·Feature 산식을 검토한다.
- 첨부본은 공식 행정동 경계가 없어 지도 대신 PCA 산점도를 만든다. 지도는 별도 공식 GeoJSON을 `dong_code`로 결합해야 한다.
- ALAN API의 실제 URL·인증·payload 규격은 공급사 문서에 맞춰 운영 전 확인해야 한다.

상세 인계 사항은 [API 계약서](docs/API_CONTRACT.md), [데이터 계약서](docs/DATA_CONTRACT.md), [QA 체크리스트](docs/HANDOFF_CHECKLIST.md)를 확인한다.
