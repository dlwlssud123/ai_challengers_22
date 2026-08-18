# DBSCAN + SHAP API 계약서

Base URL: `http://localhost:8000`  
Content-Type: `application/json; charset=utf-8`

## 원칙

- `POST /api/v1/clusters`는 **대구시 전체 행정동의 동일 시점 스냅샷**을 한 번에 받는다. 최소 12건, 최대 500건이다.
- 각 요청에서 StandardScaler, DBSCAN 파라미터 탐색, 대리 Tree 모델, SHAP을 새로 계산한다. 서버는 분석 결과나 모델을 저장하지 않는다.
- DBSCAN에는 새 행정동 1건에 대한 `predict`가 없다. What-If 결과는 변경된 모든 행정동 Feature를 합쳐 다시 요청해야 한다.
- `global_installation_priority`는 `response_facility_shortage` 내림차순, `dong_code` 오름차순으로 정한 정책 우선순위다. 회귀모델의 인과적 효과 크기가 아니다.

## 상태 확인

`GET /health`

```json
{"status":"ok","service":"daegu-heat-api"}
```

## Feature 사전

`GET /api/v1/clusters/features`는 아래 여섯 key와 정의를 반환한다.

| key | 화면 표시 | 입력 책임 |
|---|---|---|
| `heat_exposure` | 고온 노출 | 기온·폭염일수 등을 사전 산출 |
| `elderly_concentration` | 고령자 집중도 | 인구 원자료에서 산출 |
| `green_deficit` | 녹지 부족도 | 보통 `100 - green_ratio_percent` |
| `access_deficit` | 접근성 결손 | 격자 접근성 모듈에서 산출 |
| `future_heat_illness_risk` | 미래 온열질환 위험 | 회귀/시나리오 모듈에서 산출 |
| `response_facility_shortage` | 대응시설 부족도 | 보호필요도·시설대응력에서 산출 |

숫자는 모두 유한값이어야 하며, 한 요청에서는 동일한 산식·단위를 사용해야 한다. API는 요청 내부 표준화만 수행하므로 서로 다른 산식의 값 혼합을 보정하지 않는다.

## 군집 분석

`POST /api/v1/clusters`

```json
{
  "records": [
    {
      "dong_code": "2711051000",
      "district_name": "중구",
      "dong_name": "동인동",
      "features": {
        "heat_exposure": 71.2,
        "elderly_concentration": 22.4,
        "green_deficit": 86.0,
        "access_deficit": 48.2,
        "future_heat_illness_risk": 68.1,
        "response_facility_shortage": 62.8
      }
    }
  ]
}
```

실제 호출에는 최소 12개의 유일한 `dong_code`가 필요하다.

응답 핵심 필드:

| 경로 | 타입 | 프론트엔드 사용처 |
|---|---|---|
| `metadata.dbscan` | object | KPI: 군집수·노이즈·Silhouette |
| `metadata.surrogate_validation` | object | SHAP 품질 경고 표시 |
| `metadata.warnings` | string[] | 화면 경고 영역 |
| `global_feature_importance` | array | 전역 SHAP 막대그래프 |
| `clusters` | array | 군집 카드·SHAP 원인·추천시설 |
| `assignments` | array | 지도 레이어 join과 행정동 우선순위 표 |

`assignments`의 `dong_code`를 GeoJSON 행정동 코드와 join한다. 좌표·경계는 API에서 만들거나 추정하지 않는다.

오류:

- `422`: Feature 누락, 중복 행정동 코드, 상수 Feature, DBSCAN이 해석 가능한 군집을 못 만든 경우
- `500`: 의존성 또는 예기치 않은 서버 오류. 프론트는 요청 payload를 사용자에게 노출하지 말고 재시도 버튼을 제공한다.

## What-If 연결 순서

1. 사용자가 후보 쉼터/그늘막 위치를 지도에서 선택한다.
2. 격자 모듈이 해당 시설의 영향권만 재계산한 뒤 행정동별 `access_deficit`을 갱신한다.
3. 취약도·회귀 모듈이 변경된 `future_heat_illness_risk`, `response_facility_shortage`를 재계산한다.
4. **변경되지 않은 행정동까지 포함한 전체 records**를 `/api/v1/clusters`로 전송한다.
5. 이전 응답과 새 응답을 `dong_code` 기준으로 비교해 Before/After KPI를 표시한다.

군집 번호 자체는 재분석마다 바뀔 수 있으므로 `C1`만으로 비교하지 말고, `dong_code`의 Feature 변화·우선순위 변화·추천시설 변화를 비교한다.
