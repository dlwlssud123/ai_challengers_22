# temperAIture

대구광역시 행정동별 폭염 취약도, 고령인구, 녹지율, 무더위쉼터 접근성을 보여주는 React + FastAPI 애플리케이션입니다.

## 실행

백엔드:

```powershell
.\run_backend.ps1
```

프론트엔드:

```powershell
.\run_frontend.ps1
```

- React: http://127.0.0.1:5173
- FastAPI 문서: http://127.0.0.1:8000/docs

## 주요 API

- `GET /api/overview?metric=vulnerability`
- `GET /api/overview?metric=accessibility`
- `POST /api/allocation`
- `POST /api/ai-briefing`
- `GET /api/download/dong-summary.csv`

## 데이터

최종 행정동 요약 CSV는 `data/processed/daegu_all_dong_accessibility_summary.csv`입니다.
SGIS 경계, 무더위쉼터 API, 행정동 인구·녹지율, 100m 격자 접근성 지표를 결합합니다.
